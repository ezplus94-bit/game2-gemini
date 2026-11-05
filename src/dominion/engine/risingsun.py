"""Rising Sun rules that live in the engine (the cards and Events are in ``cards/risingsun.py``).

  * Sun tokens and the Prophecy: ``GameState.prophecy`` / ``suns`` / ``prophecy_on``. ``remove_sun`` is what every Omen calls first.
  * Each Prophecy is applied where it matters: gains (``after_gain_steps``), plays (``after_play_steps``, ``treasure_play_bonus``), the start of a turn
    (``start_of_turn_steps``), Clean-up (``start_cleanup_steps``, ``end_cleanup_steps``), costs (``costs.card_cost``), Buys (``costs.can_buy``), Treasures
    as Actions (``cardtypes.has_type``, ``effects.play_effect``) and Divine Wind (``divine_wind``).
  * Setup: ``pick_prophecy``, ``pick_riverboat``, ``pick_attack_pile``.
  * Shadows: ``zones.shuffle_deck`` puts them at the bottom; ``PlayAction(card, from_deck=True)`` plays one from the deck.

Known simplifications: Shadows can be played from the deck in the Action phase only (not when Throne Room, Procession, Practice... "play a card from your hand");
Harsh Winter and the Tax Event share the Debt tokens on piles; Divine Wind's new piles are the ordinary kind (Riverboat's set-aside card is not re-picked).
"""

from __future__ import annotations

import random

from ..cards import CardType, get_card, kingdom_cards, prophecy_cards
from .cardtypes import has_type, is_treasure
from .costs import card_cost
from .effects import EffectContext
from .state import DurationEntry, GameState

SUNS = {2: 5, 3: 8, 4: 10, 5: 12, 6: 13}
NOT_FOR_RIVERBOAT = frozenset({"Ferryman", "Young Witch", "Tournament", "Joust"})       # cards that need a setup of their own


def active(state: GameState, name: str) -> bool:
    return state.prophecy_on and state.prophecy == name


def pile_key(state: GameState, card: str) -> str:
    if get_card(card).is_type(CardType.LOOT):
        return "Loot"
    return state.stack_of.get(card, card)


# ------------------------------------------------------------------ Sun tokens
def remove_sun(state: GameState, player: int):
    if state.prophecy is None or state.suns <= 0:
        return
    state.suns -= 1
    state.log.append(f"{state.players[player].name} removes a Sun token from {state.prophecy} ({state.suns} left).", "info", 1)
    if state.suns == 0:
        state.prophecy_on = True
        state.log.append(f"The last Sun token is gone: {state.prophecy} is in force! ({get_card(state.prophecy).text})", "system")
        yield from happen(state, player)


def happen(state: GameState, player: int):
    """What a Prophecy does at the very moment it begins."""
    if state.prophecy == "Kind Emperor":
        yield from kind_emperor_gain(state, player)
    elif state.prophecy == "Divine Wind":
        divine_wind(state, player)


def kind_emperor_gain(state: GameState, player: int):
    ctx = EffectContext(state, player, "Kind Emperor")
    options = ctx.gainable(99, CardType.ACTION)
    if options:
        (card,) = yield ctx.choose("Kind Emperor: gain an Action card to your hand.", options)
        ctx.gain(card, destination="hand")


def divine_wind(state: GameState, player: int) -> None:
    """Remove every Kingdom pile from the Supply and set up 10 new random ones."""
    from . import setup
    old = list(state.kingdom)
    for name in old:
        for card in state.stack_cards.get(name, (name,)):
            state.supply.pop(card, None)
            state.stack_of.pop(card, None)
        state.stacks.pop(name, None)
        state.stack_cards.pop(name, None)
        state.pile_debt.pop(name, None)
        state.pile_tokens.pop(name, None)
        state.trade_tokens.discard(name) if isinstance(state.trade_tokens, set) else None
    seen = {*old, *([state.bane] if state.bane else [])}
    pool = [c for c in kingdom_cards(state.card_sets) if c not in seen]
    new = state.rng.sample(pool, min(10, len(pool)))
    n = len(state.players)
    fresh = setup._build_supply(n, new, [], {}, False, None, 0)
    basics = {"Copper", "Silver", "Gold", "Estate", "Duchy", "Province", "Curse", "Platinum", "Colony", "Potion"}
    for name, count in fresh.items():
        if name in new or (name == "Potion" and name not in state.supply):
            state.supply[name] = count
    stacks = setup._build_stacks(n, new, new, state.supply, random.Random(state.rng.randrange(2 ** 32)))
    for pile, cards in stacks.items():
        if pile in ("Ruins",) and "Ruins" in state.stacks:
            continue
        state.stacks[pile] = cards
        state.stack_cards[pile] = tuple(cards)
        for card in cards:
            state.stack_of[card] = pile
    for name, count in setup._build_offsupply(n, new).items():
        state.offsupply.setdefault(name, count)
    state.kingdom = tuple(new)
    state.log.append(f"Divine Wind removes the old Kingdom piles. The new Kingdom: {', '.join(new)}.", "system")
    del basics


# ------------------------------------------------------------------ gains
def after_gain_steps(state: GameState, event):
    gainer = event.player
    me = state.players[gainer]
    card = event.card
    if card == "Gold":
        me.gold_gained = True
    if not state.prophecy_on:
        return
    which = state.prophecy
    ctx = EffectContext(state, gainer, card)
    present = lambda: event.zone is not None and card in getattr(me, event.zone)   # noqa: E731
    if which == "Bureaucracy":
        definition = get_card(card)
        if card_cost(state, card) > 0 or definition.debt_cost or definition.potion_cost:
            ctx.log("Bureaucracy: gain a Copper.")
            ctx.gain("Copper")
    elif which == "Growth":
        if is_treasure(state, card):
            options = ctx.gainable(card_cost(state, card) - 1)
            if options:
                (new,) = yield ctx.choose("Growth: you gained a Treasure. Gain a cheaper card.", options)
                ctx.gain(new)
    elif which == "Harsh Winter":
        if state.current_player == gainer:
            pile = pile_key(state, card)
            tokens = state.pile_debt.get(pile, 0)
            if tokens > 0:
                state.pile_debt[pile] = 0
                me.debt += tokens
                ctx.log(f"Harsh Winter: {me.name} takes {tokens} Debt from the {pile} pile ({me.debt} in all).")
            else:
                state.pile_debt[pile] = 2
                ctx.log(f"Harsh Winter: 2 Debt are put on the {pile} pile.")
    elif which == "Progress":
        if present() and event.zone != "deck":
            ctx.log(f"Progress: {card} goes onto your deck.")
            ctx.put_gained_on_deck(event)
    elif which == "Rapid Expansion":
        if (has_type(state, card, CardType.ACTION) or is_treasure(state, card)) and present():
            from .plunder import _hasty_start
            zone = getattr(me, event.zone)
            zone.pop(len(zone) - 1 - zone[::-1].index(card))
            me.plunder_aside.append(card)
            event.zone = None
            me.durations.append(DurationEntry("Rapid Expansion", (), _hasty_start, [card]))
            ctx.log(f"Rapid Expansion: {card} is set aside; it is played at the start of {me.name}'s next turn.")


# ------------------------------------------------------------------ plays
def after_play_steps(state: GameState, player: int, card: str) -> None:
    if not state.prophecy_on or state.current_player != player:
        return
    definition = get_card(card)
    ctx = EffectContext(state, player, card)
    if state.prophecy == "Approaching Army" and definition.is_type(CardType.ATTACK):
        ctx.log("Approaching Army: +$1.")
        ctx.add_coins(1)
    elif state.prophecy == "Great Leader" and has_type(state, card, CardType.ACTION):
        ctx.log("Great Leader: +1 Action.")
        ctx.add_actions(1)


def treasure_play_bonus(state: GameState, player: int, card: str) -> None:
    """Good Harvest and Panic: what a Treasure play does first."""
    if not state.prophecy_on:
        return
    ctx = EffectContext(state, player, card)
    if state.prophecy == "Good Harvest" and state.current_player == player and not state.turn_counts.get("harvest:" + card):
        state.turn_counts["harvest:" + card] = 1
        ctx.log(f"Good Harvest: first {card} this turn, +1 Buy and +$1.")
        ctx.add_buys(1)
        ctx.add_coins(1)
    elif state.prophecy == "Panic":
        ctx.log("Panic: +2 Buys.")
        ctx.add_buys(2)


# ------------------------------------------------------------------ turns
def start_of_turn_steps(state: GameState, player: int):
    if not state.prophecy_on:
        return
    me = state.players[player]
    if state.prophecy == "Kind Emperor":
        yield from kind_emperor_gain(state, player)
    elif state.prophecy == "Sickness":
        ctx = EffectContext(state, player, "Sickness")
        curse, discard = "Gain a Curse onto your deck", "Discard 3 cards"
        (mode,) = yield ctx.choose("Sickness: choose one.", (curse, discard))
        if mode == curse:
            ctx.gain("Curse", destination="deck")
        else:
            n = min(3, len(me.hand))
            if n:
                chosen = yield ctx.choose("Sickness: discard 3 cards.", tuple(sorted(me.hand)), n, n)
                for c in chosen:
                    ctx.discard(c)


def start_cleanup_steps(state: GameState, player: int):
    me = state.players[player]
    ctx = EffectContext(state, player, "River Shrine")
    for _ in range(state.turn_counts.get("river_shrine", 0)):        # River Shrine: no gain in the Buy phase means a gain now
        if me.buy_gains == 0:
            options = ctx.gainable(4)
            if options:
                (card,) = yield ctx.choose("River Shrine: you gained no cards in your Buy phase. Gain a card costing up to $4.", options)
                ctx.gain(card)
    if active(state, "Biding Time") and me.hand:
        cards = list(me.hand)
        for c in cards:
            ctx.aside(c)
        me.durations.append(DurationEntry("Biding Time", (), _biding_start, cards))
        ctx.log(f"Biding Time: {me.name} sets their hand aside face down.")


def _biding_start(ctx, entry):
    n = 0
    for c in entry.data:
        if c in ctx.aside_cards():
            ctx.aside_to(c, "hand")
            n += 1
    ctx.log(f"Biding Time: {n} card(s) go back into the hand.")


def end_cleanup_steps(state: GameState, player: int, remaining: list) -> None:
    """Panic: Treasures discarded from play return to their piles."""
    if not active(state, "Panic"):
        return
    me = state.players[player]
    ctx = EffectContext(state, player, "Panic")
    for c in list(remaining):
        if not is_treasure(state, c):
            continue
        if c in state.supply:
            state.supply[c] += 1
            pile = state.stack_of.get(c)
            if pile is not None:
                state.stacks[pile].insert(0, c)
        elif c in state.offsupply:
            state.offsupply[c] += 1
            if get_card(c).is_type(CardType.LOOT):
                state.loot.insert(0, c)
        else:
            continue                                              # (Heirlooms have no pile to return to)
        remaining.remove(c)
        me.in_play.remove(c)
        ctx.log(f"Panic: {c} returns to its pile.")


# ------------------------------------------------------------------ setup
def pick_prophecy(requested, kingdom: list, seed: int):
    """The Prophecy of a game with an Omen in the Kingdom (the host may name one among the events)."""
    if not any(get_card(n).is_type(CardType.OMEN) for n in kingdom):
        return None
    for name in requested or ():
        if name in prophecy_cards():
            return name
    return random.Random(seed ^ 0x5E11).choice(prophecy_cards())


def pick_attack_pile(kingdom: list, seed: int, expansions, multi_piles) -> str:
    """Approaching Army: one more Kingdom pile that is an Attack."""
    pool = [c for c in kingdom_cards(expansions) if c not in kingdom and c not in multi_piles and get_card(c).is_type(CardType.ATTACK)
            and get_card(c).is_type(CardType.ACTION)]
    return random.Random(seed ^ 0xA77A).choice(pool)


def pick_riverboat(used: list, seed: int, expansions, multi_piles):
    """Riverboat's setup: an unused non-Duration Action card costing exactly $5."""
    pool = [c for c in kingdom_cards(expansions)
            if c not in used and c not in multi_piles and c not in NOT_FOR_RIVERBOAT and get_card(c).is_type(CardType.ACTION)
            and not get_card(c).is_type(CardType.DURATION) and get_card(c).cost == 5 and not get_card(c).potion_cost and not get_card(c).debt_cost]
    return random.Random(seed ^ 0x817E).choice(sorted(pool)) if pool else None
