"""Menagerie rules that live in the engine: the Exile mat, reactions to gains and discards, and a few standing effects.

The cards (and the Ways and Events) are in ``cards/menagerie.py``. What is here:

  * Exile: ``PlayerState.exile`` is the mat. When a player gains a card they may discard the other copies of it from the mat
    (``after_gain_steps``). Exiling from the Supply is not gaining (``zones.exile_from_supply``).
  * Reactions that are played at an unusual time: Sheepdog, Sleigh (their owner's gains), Falconer (any gain of a card with two or more
    types) and Black Cat (another player gaining a Victory card). ``gain_reaction_steps`` asks the players in turn order, starting with
    the player whose turn it is, and starts again from the first player after every Reaction played. Village Green (played when it is
    discarded other than in Clean-up) goes through ``GameState.discard_events`` and ``discard_steps``.
  * Standing effects: Gatekeeper (``GameState.gatekeepers``), Invest, Livery, Way of the Monkey and Way of the Seal.
  * Way of the Mouse: ``pick_mouse_card`` chooses the unused Action card at setup.
"""

from __future__ import annotations

import random

from ..cards import CardType, get_card, kingdom_cards
from .cardtypes import is_treasure, type_values
from .costs import card_cost
from .effects import EffectContext
from .state import GameState


def pick_mouse_card(taken: list, seed: int, expansions, excluded=()) -> str | None:
    """Way of the Mouse: an unused Action Kingdom card costing $2 or $3 that is set aside at the start of the game."""
    blocked = {CardType.DURATION, CardType.RESERVE, CardType.TRAVELLER, CardType.NIGHT}
    candidates = [
        n for n in kingdom_cards(expansions)
        if n not in taken and get_card(n).is_type(CardType.ACTION) and get_card(n).cost in (2, 3)
        and not get_card(n).potion_cost and not get_card(n).debt_cost and not (blocked & get_card(n).types)
        and n not in ("Knights", "Castles", "Young Witch", "Ferryman", *excluded)
    ]
    if not candidates:
        return None
    return random.Random(seed ^ 0x3053).choice(candidates)


def start_of_turn(state: GameState, player: int) -> None:
    """The owner's next turn begins: their Gatekeeper attacks and Way of the Monkey plays end."""
    state.gatekeepers[:] = [(o, t) for o, t in state.gatekeepers if o != player]
    state.players[player].monkey = 0


# ------------------------------------------------------------------ reactions to a gain
def _reaction_options(state: GameState, p: int, event) -> list:
    """The Reactions in ``p``'s hand that may be played because of this gain."""
    me = state.players[p]
    gained = get_card(event.card)
    present = event.zone is not None and event.card in getattr(state.players[event.player], event.zone)
    out = []
    for name in sorted(set(me.hand)):
        if name == "Sheepdog" and p == event.player:
            out.append(name)
        elif name == "Sleigh" and p == event.player and present and not (event.card == "Sleigh" and event.zone == "hand" and me.hand.count("Sleigh") < 2):
            out.append(name)                                  # (the Sleigh just gained to the hand cannot be discarded to move itself)
        elif name == "Falconer" and len(type_values(state, event.card)) >= 2:
            out.append(name)
        elif name == "Black Cat" and p != event.player and gained.is_type(CardType.VICTORY):
            out.append(name)
    return out


def gain_reaction_steps(state: GameState, event):
    """Generator: Sheepdog, Sleigh, Falconer and Black Cat. Players are asked in turn order from the player whose turn it is; after a
    Reaction has been played everybody is looked at again from the first player."""
    n = len(state.players)
    declined = set()
    while state.status.value == "active":
        asked = None
        for k in range(n):
            p = state.step(state.current_player, k)
            options = [o for o in _reaction_options(state, p, event) if (p, o) not in declined]
            if options:
                asked = (p, options)
                break
        if asked is None:
            return
        p, options = asked
        ctx = EffectContext(state, p, options[0])
        gainer = state.players[event.player].name
        shown = [f"Play {o}" if o != "Sleigh" else f"Discard Sleigh to put {event.card} into your hand" for o in options]
        if "Sleigh" in options:
            shown.append(f"Discard Sleigh to put {event.card} onto your deck")
        index = {s: o for s, o in zip(shown, [*options, *(["Sleigh"] if "Sleigh" in options else [])])}
        chosen = yield ctx.choose(f"{gainer} gained {event.card}. You may use a Reaction from your hand.", tuple(shown), 0, 1)
        if not chosen:
            for o in options:
                declined.add((p, o))
            continue
        name = index[chosen[0]]
        if name == "Sleigh":
            sctx = EffectContext(state, p, "Sleigh")
            sctx.discard("Sleigh")
            if sctx.gained_card_present(event):
                if "deck" in chosen[0]:
                    sctx.put_gained_on_deck(event)
                else:
                    sctx.put_gained_in_hand(event)
        else:
            state.players[p].hand.remove(name)
            state.players[p].in_play.append(name)
            state.log.append(f"{state.players[p].name} plays {name} (Reaction).", "play")
            yield from EffectContext(state, p, name).resolve(name)


def after_gain_steps(state: GameState, event):
    """Generator: Exile (Gatekeeper, discarding copies from the mat), Invest, Way of the Monkey, Livery and Way of the Seal."""
    n = len(state.players)
    gainer = event.player
    me = state.players[gainer]
    card = get_card(event.card)
    had_copy = event.card in me.exile
    present = lambda: event.zone is not None and event.card in getattr(me, event.zone)   # noqa: E731
    # Gatekeeper: an Action or Treasure the player has no copy of in Exile is Exiled instead of staying where it went
    if not had_copy and present() and any(t == gainer for _, t in state.gatekeepers):
        if card.is_type(CardType.ACTION) or card.is_type(CardType.TREASURE) or is_treasure(state, event.card):
            zone = getattr(me, event.zone)
            zone.pop(len(zone) - 1 - zone[::-1].index(event.card))
            me.exile.append(event.card)
            event.zone = None
            state.log.append(f"{me.name} Exiles the gained {event.card} (Gatekeeper).", "info", 1)
    # "When you gain a card, you may discard the other copies of it from your Exile mat" (all of them or none)
    if had_copy and event.card in me.exile and state.status.value == "active":
        copies = me.exile.count(event.card)
        ctx = EffectContext(state, gainer, "Exile")
        chosen = yield ctx.choose(f"You gained {event.card}. You may discard the {copies} cop{'ies' if copies != 1 else 'y'} of it on your Exile mat.",
                                  (f"Discard {copies} from Exile",), 0, 1)
        if chosen:
            for _ in range(copies):
                ctx.discard_from_exile(event.card)
            me.invested.pop(event.card, None)
            ctx.log(f"{me.name} discards {copies} {event.card} from their Exile mat.")
    # Invest: every other player with an Invested copy in Exile draws 2 cards per copy
    for k in range(1, n):
        o = state.step(gainer, k)
        owner = state.players[o]
        copies = min(owner.invested.get(event.card, 0), owner.exile.count(event.card))
        if copies:
            ctx = EffectContext(state, o, "Invest")
            ctx.log(f"{owner.name}'s Invest pays off: {event.card} was gained by {me.name}.")
            ctx.draw(2 * copies)
    # Way of the Monkey: the player to the left of the gainer drew a card for each Monkey played until their next turn
    left = state.step(gainer)
    if left != gainer and state.players[left].monkey:
        EffectContext(state, left, "Way of the Monkey").draw(state.players[left].monkey)
    # Livery: this turn, a card costing $4 or more brings a Horse
    if state.current_player == gainer:
        for _ in range(state.turn_counts.get("Livery", 0)):
            if card_cost(state, event.card) >= 4:
                EffectContext(state, gainer, "Livery").gain_horse()
    # Way of the Seal: this turn, a gained card may be put onto the deck
    for _ in range(state.turn_counts.get(f"seal:{gainer}", 0)):
        ctx = EffectContext(state, gainer, "Way of the Seal")
        if ctx.gained_card_present(event):
            chosen = yield ctx.choose(f"Way of the Seal: you may put {event.card} onto your deck.", (f"Put {event.card} on your deck",), 0, 1)
            if chosen:
                ctx.put_gained_on_deck(event)


def discard_steps(state: GameState):
    """Generator: a Village Green that was discarded other than in Clean-up may be played (it is still the top of its owner's discard pile)."""
    while state.discard_events:
        player, card = state.discard_events.pop(0)
        me = state.players[player]
        if card not in me.discard or state.status.value != "active":
            continue
        ctx = EffectContext(state, player, card)
        chosen = yield ctx.choose(f"You discarded {card}. You may play it.", (f"Play {card}",), 0, 1)
        if chosen:
            me.discard.pop(len(me.discard) - 1 - me.discard[::-1].index(card))
            me.in_play.append(card)
            state.log.append(f"{me.name} plays {card} (when discarded).", "play")
            yield from ctx.resolve(card)
