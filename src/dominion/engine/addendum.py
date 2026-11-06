"""Engine rules for the cards added later (see ``cards/addendum.py``): the Seaside and Hinterlands 2nd-edition reactions and triggers, Coppersmith,
Walled Village, Prince, Sauna, Corsair and the Black Market deck.

  * ``after_gain_steps``: Monkey, Blockade, Cauldron, Sailor, Trail and Pirate reacting to gains.
  * ``treasure_played_steps``: Corsair (trashes a played Silver/Gold) and Sauna (may trash a card when a Silver is played).
  * ``start_cleanup_steps`` (Walled Village) and ``end_cleanup_steps`` (Prince's card goes back aside).
  * ``build_black_market``: 25 unused Kingdom cards, one of each, from the sets that need no setup of their own.
"""

from __future__ import annotations

import random

from ..cards import CardType, get_card, kingdom_cards
from .cardtypes import has_type, is_treasure
from .effects import EffectContext
from .state import GameState

BLACK_MARKET_SETS = ("Base", "Intrigue", "Seaside", "Prosperity", "Hinterlands", "Cornucopia & Guilds", "Renaissance", "Rising Sun", "Plunder")
BLACK_MARKET_EXCLUDE = frozenset({"Tournament", "Joust", "Black Market", "Sauna", "Young Witch", "Ferryman", "Replace", "Riverboat"})


def build_black_market(state: GameState, used: list, seed: int, multi_piles) -> None:
    pool = [c for c in kingdom_cards(BLACK_MARKET_SETS)
            if c not in used and c not in multi_piles and c not in BLACK_MARKET_EXCLUDE and not get_card(c).potion_cost and c != state.bane
            and not get_card(c).is_type(CardType.LOOTER)]
    random.Random(seed ^ 0xB1AC).shuffle(pool)
    state.black_market = pool[:25]
    for name in state.black_market:
        state.offsupply[name] = state.offsupply.get(name, 0) + 1


def _offer_reaction(state: GameState, event, name: str, who):
    """Players (those ``who(p)`` allows) holding ``name`` may play it from their hand, in turn order; it can be played again afterwards."""
    n = len(state.players)
    declined = set()
    while state.status.value == "active":
        asked = None
        for k in range(n):
            p = (state.current_player + k) % n
            if who(p) and name in state.players[p].hand and p not in declined:
                asked = p
                break
        if asked is None:
            return
        ctx = EffectContext(state, asked, name)
        chosen = yield ctx.choose(f"{state.players[event.player].name} gained {event.card}. You may play {name} from your hand.", (f"Play {name}",), 0, 1)
        if not chosen:
            declined.add(asked)
            continue
        ctx.put_in_play(name, "hand")
        ctx.log(f"{state.players[asked].name} plays {name} (Reaction).", "play")
        yield from ctx.resolve(name)


def after_gain_steps(state: GameState, event):
    s = state
    gainer = event.player
    me = s.players[gainer]
    card = event.card
    n = len(s.players)
    own_turn = s.current_player == gainer
    definition = get_card(card)
    ctx = EffectContext(s, gainer, card)
    present = lambda: event.zone is not None and card in getattr(me, event.zone)   # noqa: E731
    for owner, other in enumerate(s.players):
        for entry in list(other.durations):
            d = entry.data
            if not isinstance(d, dict):
                continue
            if d.get("monkey") and (owner - 1) % n == gainer and owner != gainer:      # Monkey: the player on your right gained a card
                EffectContext(s, owner, "Monkey").log("Monkey: +1 Card.")
                EffectContext(s, owner, "Monkey").draw(1, player=owner)
            if d.get("blockade") and owner != gainer and gainer in d["targets"] and own_turn and card == d["blockade"]:
                s.log.append(f"Blockade: {me.name} gained a copy of {card} and gains a Curse.", "gain", 1)
                ctx.gain("Curse")
    if own_turn and has_type(s, card, CardType.ACTION):               # Cauldron: the third Action gained this turn
        s.turn_counts["actions_gained"] = s.turn_counts.get("actions_gained", 0) + 1
        if s.turn_counts["actions_gained"] == 3:
            for _ in range(s.turn_counts.get("cauldron", 0)):
                s.log.append("Cauldron: the third Action gained this turn, each other player gains a Curse.", "info", 1)
                targets = yield from ctx.attack()
                for p in targets:
                    ctx.gain("Curse", player=p)
    if own_turn and definition.is_type(CardType.DURATION) and s.turn_counts.get("sailor", 0) > 0 and present() and event.zone in ("discard", "hand"):
        chosen = yield ctx.choose(f"Sailor: you gained {card}. You may play it.", (f"Play {card}",), 0, 1)
        if chosen and present() and event.zone in ("discard", "hand"):
            s.turn_counts["sailor"] -= 1
            ctx.put_in_play(card, event.zone)
            yield from ctx.resolve(card)
    if card == "Trail" and present() and event.zone in ("discard", "hand", "deck"):
        chosen = yield ctx.choose("Trail: you gained it. You may play it.", ("Play Trail",), 0, 1)
        if chosen and present() and event.zone in ("discard", "hand"):
            ctx.put_in_play("Trail", event.zone)
            yield from ctx.resolve("Trail")
    if is_treasure(s, card):                                           # Pirate: when any player gains a Treasure
        yield from _offer_reaction(s, event, "Pirate", lambda p: True)


def treasure_played_steps(state: GameState, player: int, card: str):
    me = state.players[player]
    if card in ("Silver", "Gold") and not state.turn_counts.get("corsair:%d" % player) and state.current_player == player:
        for owner, other in enumerate(state.players):
            if owner != player and any(isinstance(e.data, dict) and player in e.data.get("corsair", ()) for e in other.durations):
                state.turn_counts["corsair:%d" % player] = 1
                if card in me.in_play:
                    EffectContext(state, owner, "Corsair").log(f"Corsair: {me.name} trashes the first Silver or Gold they play ({card}).")
                    me.in_play.remove(card)
                    state.trash.append(card)
                break
    if card == "Silver":
        for _ in range(me.in_play.count("Sauna")):
            if not me.hand:
                break
            ctx = EffectContext(state, player, "Sauna")
            chosen = yield ctx.choose("Sauna: you played a Silver. You may trash a card from your hand.", tuple(sorted(set(me.hand))), 0, 1)
            if chosen:
                ctx.trash(chosen[0])


def start_cleanup_steps(state: GameState, player: int):
    me = state.players[player]
    for _ in range(me.in_play.count("Walled Village")):
        if "Walled Village" not in me.in_play:
            break
        others = sum(1 for c in me.in_play if has_type(state, c, CardType.ACTION)) - 1
        if others <= 1:
            ctx = EffectContext(state, player, "Walled Village")
            chosen = yield ctx.choose("Walled Village: you may put it on top of your deck.", ("Put Walled Village on my deck",), 0, 1)
            if chosen:
                ctx.put_in_play_on_deck("Walled Village")


def end_cleanup_steps(state: GameState, player: int, remaining: list) -> None:
    """Prince: the Action it played goes back aside when it is discarded from play."""
    me = state.players[player]
    for entry in me.durations:
        d = entry.data
        if entry.source == "Prince" and isinstance(d, dict) and d.get("played") and d["prince"] in remaining:
            card = d["prince"]
            remaining.remove(card)
            me.in_play.remove(card)
            me.plunder_aside.append(card)
            d["played"] = False
            state.log.append(f"Prince: {card} is set aside again.", "info", 1)
