"""Plunder rules that live in the engine (the cards, Events, Loot and Traits themselves are in ``cards/plunder.py``).

  * Waiting Durations: a Duration that says "the next time ..." is an entry in ``PlayerState.durations`` with ``data = {"wait": kind, ...}``.
    ``fire_waits`` runs the card's ``wait`` hook when the matching thing happens (a gain, a card played, a Supply pile emptying).
  * Traits: ``GameState.traits`` maps a Kingdom pile to the Trait lying on it. Each Trait has its own small hook below (``after_gain_steps``,
    ``start_of_turn_steps``, ``start_cleanup_steps``, ``end_cleanup_steps``, ``shuffle_steps``; Cheap is in ``costs``, Reckless in ``effects``).
  * Loot: ``GameState.loot`` is the shuffled pile, top first (the counts are also in ``offsupply``).
  * Reactions played at an odd time: Mapmaker (any Victory card gained) and Stowaway (any Duration gained).

Known simplifications: a gain that Prosper makes is looked at after the whole Event; Fated and Avoid pause only draws (not other looks at the deck)
and take the place of the Allies' Orders when both apply to the same shuffle.
"""

from __future__ import annotations

import inspect

from ..cards import CardType, get_card
from ..cards.plunder import play_aside_all, play_from_hand
from .cardtypes import has_type, is_treasure
from .costs import card_cost
from .effects import EffectContext
from . import zones
from .state import DurationEntry, GameState

LOOT_USERS = frozenset({"Cutthroat", "Jewelled Egg", "Pickaxe", "Sack of Loot", "Search", "Wealthy Village",
                        "Foray", "Invasion", "Looting", "Peril", "Prosper", "Cursed"})
LOOT_NAMES = ("Amphora", "Doubloons", "Endless Chalice", "Figurehead", "Hammer", "Insignia", "Jewels", "Orb",
              "Prize Goat", "Puzzle Box", "Sextant", "Shield", "Spell Scroll", "Staff", "Sword")


def trait_of(state: GameState, card: str):
    return state.traits.get(state.stack_of.get(card, card)) if state.traits else None


def _run(result):
    if inspect.isgenerator(result):
        yield from result


# ------------------------------------------------------------------ waiting Durations
def hook_of(card: str, key: str):
    for k, fn in get_card(card).hooks:
        if k == key:
            return fn
    return None


def fire_waits(state: GameState, kind: str, arg=None, only=None):
    """Generator: every waiting Duration of this ``kind`` (those of player ``only``, or of everybody in turn order) does its thing."""
    n = len(state.players)
    for k in range(n):
        p = (state.current_player + k) % n
        if only is not None and p != only:
            continue
        me = state.players[p]
        for entry in list(me.durations):
            d = entry.data
            if not (isinstance(d, dict) and d.get("wait") == kind) or entry not in me.durations:
                continue
            fn = hook_of(entry.source, "wait")
            if fn is None or state.status.value != "active":
                continue
            yield from _run(fn(EffectContext(state, p, entry.source), entry, arg))


# ------------------------------------------------------------------ gains
def after_gain_steps(state: GameState, event):
    s = state
    gainer = event.player
    me = s.players[gainer]
    card = event.card
    definition = get_card(card)
    own_turn = s.current_player == gainer
    present = lambda: event.zone is not None and card in getattr(me, event.zone)   # noqa: E731
    ctx = EffectContext(s, gainer, card)
    trait = trait_of(s, card)

    # ---- Traits of the gained card
    if trait == "Cursed":
        ctx.log("Cursed: gain a Loot and a Curse.")
        ctx.gain_loot()
        ctx.gain("Curse")
    elif trait == "Rich":
        ctx.log("Rich: gain a Silver.")
        ctx.gain("Silver")
    elif trait == "Nearby":
        ctx.log("Nearby: +1 Buy.")
        ctx.add_buys(1)
    elif trait == "Pious" and me.hand:
        chosen = yield ctx.choose(f"Pious: you gained {card}. You may trash a card from your hand.", tuple(sorted(set(me.hand))), 0, 1)
        if chosen:
            ctx.trash(chosen[0])
    elif trait == "Hasty" and present():
        zone = getattr(me, event.zone)
        zone.pop(len(zone) - 1 - zone[::-1].index(card))
        me.plunder_aside.append(card)
        event.zone = None
        me.durations.append(DurationEntry("Hasty", (), _hasty_start, [card]))
        ctx.log(f"Hasty: {me.name} sets {card} aside to play at the start of their next turn.")
    if card == "Province":                                        # Fawning (on any pile)
        for pile, name in list(s.traits.items()):
            if name == "Fawning":
                stack = s.stacks.get(pile)
                top = (stack[0] if stack else None) if stack is not None else pile
                if top and s.supply.get(top, 0) > 0:
                    ctx.log("Fawning: gain a Fawning card.")
                    ctx.gain(top)

    # ---- this turn's effects of Events and Loot
    if own_turn:
        for _ in range(s.turn_counts.get("insignia", 0)):
            if present() and event.zone != "deck":
                chosen = yield ctx.choose(f"Insignia: you may put {card} onto your deck.", (f"Put {card} on your deck",), 0, 1)
                if chosen:
                    ctx.put_gained_on_deck(event)
        if s.turn_counts.get("deliver") and present() and event.zone in ("discard", "hand", "deck"):
            zone = getattr(me, event.zone)
            zone.pop(len(zone) - 1 - zone[::-1].index(card))
            me.eot_hand.append(card)
            event.zone = None
            ctx.log(f"Deliver: {card} is set aside; it goes into your hand at end of turn.")
        if definition.is_type(CardType.ACTION) and event.from_supply and s.turn_counts.get("mirror", 0) > 0:
            n = s.turn_counts["mirror"]
            s.turn_counts["mirror"] = 0
            for _ in range(n):
                ctx.log(f"Mirror: gain a copy of {card}.")
                if not ctx.gain(card):
                    break
        if definition.is_type(CardType.ACTION) and s.turn_counts.get("rush", 0) > 0 and present() and event.zone in ("discard", "hand"):
            s.turn_counts["rush"] = 0
            ctx.log(f"Rush: {me.name} plays {card}.")
            ctx.put_in_play(card, event.zone)
            yield from ctx.resolve(card)
        if is_treasure(s, card) and s.turn_counts.get("mining_road", 0) > 0 and present() and event.zone in ("discard", "hand"):
            chosen = yield ctx.choose(f"Mining Road: you gained {card}. You may play it.", (f"Play {card}",), 0, 1)
            if chosen and present() and event.zone in ("discard", "hand"):
                s.turn_counts["mining_road"] -= 1
                yield from ctx.play_treasure(card, event.zone)

    # ---- Durations waiting for a gain
    if has_type(s, card, CardType.ACTION):
        yield from fire_waits(s, "gain_action", event, only=gainer)
    if definition.is_type(CardType.VICTORY):
        yield from fire_waits(s, "gain_victory", event, only=gainer)
    if is_treasure(s, card):
        yield from fire_waits(s, "gain_treasure", event, only=gainer)
        if card_cost(s, card) >= 5:
            yield from fire_waits(s, "gain_treasure5", event)
    if own_turn and card_cost(s, card) == 5:
        yield from fire_waits(s, "gain_exact5", event, only=gainer)
    if event.from_supply and ctx.pile_empty_after(card):
        yield from fire_waits(s, "pile_empty", event)
    yield from reaction_steps(s, event)


def _hasty_start(ctx, entry):
    yield from play_aside_all(ctx, entry.data, discard_rest=False)


def reaction_steps(state: GameState, event):
    """Mapmaker (any player gaining a Victory card) and Stowaway (any player gaining a Duration card) may be played from the hand."""
    card = get_card(event.card)
    kinds = [name for name, test in (("Mapmaker", card.is_type(CardType.VICTORY)), ("Stowaway", card.is_type(CardType.DURATION))) if test]
    if not kinds:
        return
    n = len(state.players)
    declined = set()
    while state.status.value == "active":
        asked = None
        for k in range(n):
            p = (state.current_player + k) % n
            options = [c for c in kinds if c in state.players[p].hand and (p, c) not in declined]
            if options:
                asked = (p, options[0])
                break
        if asked is None:
            return
        p, name = asked
        ctx = EffectContext(state, p, name)
        gainer = state.players[event.player].name
        chosen = yield ctx.choose(f"{gainer} gained {event.card}. You may play {name} from your hand.", (f"Play {name}",), 0, 1)
        if not chosen:
            declined.add((p, name))
            continue
        state.players[p].hand.remove(name)
        state.players[p].in_play.append(name)
        state.log.append(f"{state.players[p].name} plays {name} (Reaction).", "play")
        yield from EffectContext(state, p, name).resolve(name)


# ------------------------------------------------------------------ playing cards
def before_play(state: GameState) -> tuple:
    return (state.coin_ticks, state.turn_counts.get("hv_armed", 0))


def after_play_steps(state: GameState, player: int, card: str, snap: tuple):
    """After a card was played: Harbor Village, Frigate, Flagship and the Inspiring Trait."""
    if state.status.value != "active":
        return
    definition = get_card(card)
    me = state.players[player]
    ticks, armed = snap
    is_action = definition.is_type(CardType.ACTION)
    from . import risingsun
    risingsun.after_play_steps(state, player, card)                # Rising Sun: Approaching Army, Great Leader
    if is_action and armed and state.current_player == player:
        n = min(armed, state.turn_counts.get("hv_armed", 0))
        if n > 0:
            state.turn_counts["hv_armed"] -= n
            if state.coin_ticks > ticks:
                state.log.append(f"Harbor Village: {card} gave +$, so +${n}.", "info", 1)
                EffectContext(state, player, "Harbor Village").add_coins(n)
    if is_action:
        for owner, other in enumerate(state.players):          # Frigate
            if owner == player:
                continue
            for entry in list(other.durations):
                d = entry.data
                if isinstance(d, dict) and player in d.get("frigate", ()):
                    excess = len(me.hand) - 4
                    if excess > 0:
                        ctx = EffectContext(state, owner, "Frigate")
                        chosen = yield ctx.choose(f"{other.name}'s Frigate: discard {excess} card(s) to get down to 4.", tuple(sorted(me.hand)), excess, excess, player=player)
                        for c in chosen:
                            EffectContext(state, owner, "Frigate").discard(c, player=player)
        if not definition.is_type(CardType.COMMAND):           # Flagship replays the next non-Command Action
            waiting = [e for e in me.durations if isinstance(e.data, dict) and e.data.get("wait") == "play_action"]
            for e in waiting:
                me.durations.remove(e)
            daimyo = state.turn_counts.get("daimyo", 0) if state.current_player == player else 0      # Rising Sun: Daimyo replays it too
            state.turn_counts["daimyo"] = 0
            for source in [*(["Flagship"] * len(waiting)), *(["Daimyo"] * daimyo)]:
                state.log.append(f"{source}: {card} is replayed.", "play", 1)
                yield from EffectContext(state, player, source).resolve(card)
    if state.current_player == player and trait_of(state, card) == "Inspiring" and (is_action or definition.is_type(CardType.TREASURE)):
        in_play = set(me.in_play)
        ctx = EffectContext(state, player, card)
        yield from play_from_hand(ctx, "Inspiring: you may play an Action from your hand that you don't have a copy of in play.",
                                  lambda c: ctx.is_action(c) and c not in in_play)


def treasure_played_first(state: GameState, player: int, card: str):
    yield from fire_waits(state, "first_play_treasure", card, only=player)


# ------------------------------------------------------------------ start of turn
def start_of_turn_steps(state: GameState, player: int):
    me = state.players[player]
    if state.shaman:                                            # Shaman: gain a card from the trash costing up to $6
        options = tuple(sorted({c for c in state.trash if card_cost(state, c) <= 6 and not get_card(c).potion_cost and not get_card(c).debt_cost}))
        if options:
            ctx = EffectContext(state, player, "Shaman")
            (card,) = yield ctx.choose("Shaman: gain a card from the trash costing up to $6.", options)
            ctx.gain_from_trash(card)
            ctx.log(f"{me.name} gains {card} from the trash (Shaman).", "gain")
    if state.traits:
        shy = tuple(sorted({c for c in me.hand if trait_of(state, c) == "Shy"}))
        if shy:
            ctx = EffectContext(state, player, "Shy")
            chosen = yield ctx.choose("Shy: you may discard a Shy card for +2 Cards.", shy, 0, 1)
            if chosen:
                ctx.discard(chosen[0])
                ctx.draw(2)


# ------------------------------------------------------------------ Clean-up
def start_cleanup_steps(state: GameState, player: int):
    """At the start of your Clean-up phase: Friendly and Patient."""
    if not state.traits:
        return
    me = state.players[player]
    friendly = tuple(sorted({c for c in me.hand if trait_of(state, c) == "Friendly"}))
    if friendly:
        ctx = EffectContext(state, player, "Friendly")
        chosen = yield ctx.choose("Friendly: you may discard a Friendly card to gain a Friendly card.", friendly, 0, 1)
        if chosen:
            ctx.discard(chosen[0])
            pile = state.stack_of.get(chosen[0], chosen[0])
            stack = state.stacks.get(pile)
            top = (stack[0] if stack else None) if stack is not None else pile
            if top and state.supply.get(top, 0) > 0:
                ctx.gain(top)
    patient = [c for c in me.hand if trait_of(state, c) == "Patient"]
    if patient:
        ctx = EffectContext(state, player, "Patient")
        chosen = yield ctx.choose("Patient: you may set aside Patient cards from your hand to play them at the start of your next turn.",
                                  tuple(sorted(patient)), 0, len(patient))
        if chosen:
            for c in chosen:
                ctx.aside(c)
            me.durations.append(DurationEntry("Patient", (), _hasty_start, list(chosen)))
            ctx.log(f"Patient: {me.name} sets aside {', '.join(sorted(chosen))}.")


def end_cleanup_steps(state: GameState, player: int, remaining: list):
    """The cards about to be discarded from play (``remaining``): Trickster sets Treasures aside, Tireless cards go back on the deck, Reckless
    cards go back to their pile."""
    me = state.players[player]
    for _ in range(state.turn_counts.get("trickster", 0)):
        options = tuple(sorted({c for c in remaining if is_treasure(state, c)}))
        if not options:
            break
        ctx = EffectContext(state, player, "Trickster")
        chosen = yield ctx.choose("Trickster: you may set aside a Treasure you are discarding from play. It goes into your hand at end of turn.", options, 0, 1)
        if chosen:
            remaining.remove(chosen[0])
            me.in_play.remove(chosen[0])
            me.eot_hand.append(chosen[0])
            ctx.log(f"Trickster: {me.name} sets {chosen[0]} aside.")
    if not state.traits:
        return
    ctx = EffectContext(state, player, "Tireless")
    for c in list(remaining):
        t = trait_of(state, c)
        if t == "Tireless":
            remaining.remove(c)
            me.in_play.remove(c)
            me.eot_deck.append(c)
            ctx.log(f"Tireless: {c} is set aside; it goes onto your deck at end of turn.")
        elif t == "Reckless" and (c in state.supply):
            remaining.remove(c)
            me.in_play.remove(c)
            state.supply[c] += 1
            pile = state.stack_of.get(c)
            if pile is not None:
                state.stacks[pile].insert(0, c)
            ctx.log(f"Reckless: {c} returns to its pile.")


def end_of_turn_cards(state: GameState, player: int) -> None:
    """After the next hand was drawn: set-aside cards go into hands, Tireless cards onto the deck."""
    for p in state.players:
        if p.eot_hand:
            p.hand.extend(p.eot_hand)
            state.log.append(f"{p.name} puts {len(p.eot_hand)} set-aside card(s) into their hand.", "info", 1)
            p.eot_hand.clear()
    me = state.players[player]
    if me.eot_deck:
        me.deck.extend(me.eot_deck)
        me.eot_deck.clear()


# ------------------------------------------------------------------ shuffling
def wants_shuffle_pause(state: GameState, player: int) -> bool:
    me = state.players[player]
    if state.turn_counts.get("avoid", 0) > 0 and state.current_player == player and me.discard:
        return True
    return bool(state.traits) and any(trait_of(state, c) == "Fated" for c in me.discard)


def shuffle_steps(state: GameState, player: int):
    """A draw reached the end of the deck. Avoid keeps cards out of the shuffle, Fated lets the owner put cards on top or on the bottom; then
    the shuffle is made."""
    me = state.players[player]
    if me.deck or not me.discard:                      # (nothing to shuffle any more)
        return
    ctx = EffectContext(state, player, "Shuffle")
    pool = list(me.discard)
    kept: list = []
    top: list = []
    bottom: list = []
    avoid = state.turn_counts.get("avoid", 0) if state.current_player == player else 0
    state.turn_counts["avoid"] = 0
    for _ in range(avoid):
        if not pool:
            break
        picked = yield ctx.choose("Avoid: pick up to 3 of the cards about to be shuffled to go to your discard pile instead.", tuple(sorted(pool)), 0, min(3, len(pool)))
        for c in picked:
            pool.remove(c)
            kept.append(c)
    for c in [c for c in pool if trait_of(state, c) == "Fated"]:
        if c not in pool:
            continue
        (where,) = yield ctx.choose(f"Fated: you are shuffling. Where does {c} go?", ("Shuffle it in", "Put it on top of your deck", "Put it on the bottom of your deck"))
        if where.startswith("Put it on top"):
            pool.remove(c)
            top.append(c)
        elif where.startswith("Put it on the bottom"):
            pool.remove(c)
            bottom.append(c)
    shuffled = list(pool)
    zones.shuffle_deck(state, shuffled)
    me.deck = bottom + shuffled + list(reversed(top))
    me.discard = kept
    if kept or top or bottom:
        ctx.log(f"{me.name} sets cards aside while shuffling: {len(kept)} kept out, {len(top)} on top, {len(bottom)} on the bottom.")


# ------------------------------------------------------------------ setup
def pick_trait_piles(trait_names: list, kingdom: list, multi_piles, seed: int) -> dict:
    """Each Trait lies on a random Action or Treasure Kingdom pile (never two on one pile)."""
    import random
    eligible = [p for p in kingdom if p != "Castles" and (get_card(p).is_type(CardType.ACTION) or get_card(p).is_type(CardType.TREASURE) or p in multi_piles)]
    rng = random.Random(seed ^ 0x7A17)
    piles = rng.sample(eligible, min(len(eligible), len(trait_names)))
    return dict(zip(piles, trait_names))


def build_loot(state: GameState, seed: int) -> None:
    import random
    cards = [name for name in LOOT_NAMES for _ in range(2)]
    random.Random(seed ^ 0x100713).shuffle(cards)
    state.loot = cards
    for name in LOOT_NAMES:
        state.offsupply[name] = 2


def inherited_steps(state: GameState, pile: str):
    """Inherited (Setup): each player, in turn order, takes a card of the pile in place of a starting card they choose."""
    n = len(state.players)
    for k in range(n):
        p = (state.current_player + k) % n
        me = state.players[p]
        stack = state.stacks.get(pile)
        top = (stack[0] if stack else None) if stack is not None else pile
        if not top or state.supply.get(top, 0) <= 0:
            continue
        options = tuple(sorted(set(me.deck) | set(me.hand)))
        ctx = EffectContext(state, p, "Inherited")
        (old,) = yield ctx.choose(f"Inherited: you start with a {top} in place of a starting card. Which one?", options)
        state.supply[top] -= 1
        if stack is not None:
            stack.pop(0)
        for zone in (me.deck, me.hand):
            if old in zone:
                zone[zone.index(old)] = top
                break
        if old == "Copper":
            state.supply["Copper"] = state.supply.get("Copper", 0) + 1
        ctx.log(f"{me.name} starts with a {top} instead of a {old} (Inherited).")
