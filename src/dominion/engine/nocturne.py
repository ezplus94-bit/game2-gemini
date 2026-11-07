"""Nocturne rules that live in the engine: the Boon and Hex decks, States, and the start / end of turn effects.

The cards themselves (and the effect of each Boon and Hex) are in ``cards/nocturne.py``; ``EffectContext`` has the
helpers they use (``receive_boon``, ``receive_hex``, ...). Boons, Hexes and States are not cards: they are plain names.
"""

from __future__ import annotations

from ..cards import CardType, get_card
from ..cards.nocturne import BOON_NAMES, HEX_NAMES, ZOMBIES
from .effects import EffectContext
from .state import GameState


def setup(state: GameState, used: list, rng) -> None:
    """Boons (when a Fate card is in the game), Hexes (Doom), Druid's three Boons, the Zombies in the trash."""
    types = [get_card(n).types for n in used]
    if any(CardType.FATE in t for t in types):
        boons = list(BOON_NAMES)
        rng.shuffle(boons)
        if "Druid" in used:                              # the top three Boons are set aside face up for Druid
            state.druid_boons, boons = boons[:3], boons[3:]
        state.boons = boons
    if any(CardType.DOOM in t for t in types):
        hexes = list(HEX_NAMES)
        rng.shuffle(hexes)
        state.hexes = hexes
    if "Necromancer" in used:
        state.trash.extend(ZOMBIES)


def start_of_buy_phase(state: GameState, player: int) -> None:
    """Deluded and Envious are returned at the start of the Buy phase and apply for that turn."""
    me = state.players[player]
    if me.deluded:
        me.deluded = False
        state.deluded_turn = True
        state.log.append(f"{me.name} returns Deluded: they cannot buy Action cards this turn.", "hex", 1)
    if me.envious:
        me.envious = False
        state.envious_turn = True
        state.log.append(f"{me.name} returns Envious: Silver and Gold make $1 this turn.", "hex", 1)


def start_of_turn_steps(state: GameState, player: int):
    """Generator: Boons taken with Blessed Village are received, then the holder of Lost in the Woods may discard a card
    for a Boon. (Start-of-turn effects happen in this fixed order, after the Duration cards.)"""
    me = state.players[player]
    if me.held_boons:
        held, me.held_boons = list(me.held_boons), []
        ctx = EffectContext(state, player, "Blessed Village")
        while held:
            if len(set(held)) == 1:
                boon = held.pop()
            else:
                (boon,) = yield ctx.choose("Blessed Village: choose the next saved Boon to receive.", tuple(held))
                held.remove(boon)
            yield from ctx.receive_boon(boon)
    if state.lost_in_woods == player and me.hand:
        ctx = EffectContext(state, player, "Lost in the Woods")
        chosen = yield ctx.choose("Lost in the Woods: you may discard a card to receive a Boon.", tuple(sorted(set(me.hand))), 0, 1)
        if chosen:
            ctx.discard(chosen[0])
            yield from ctx.receive_boon()


def end_of_turn_draws(state: GameState) -> None:
    """After the turn's player drew their new hand: everyone who received The River's Gift draws a card, set-aside Faithful
    Hounds return to their owners' hands, kept Boons go to the discard pile, Deluded / Envious wear off."""
    from . import zones
    for who in state.river_draws:
        zones.draw_cards(state, who, 1)
        state.log.append(f"{state.players[who].name} draws a card (The River's Gift).", "draw", 1)
    state.river_draws = []
    for p in state.players:
        if p.hounds:
            p.hand.extend(p.hounds)
            state.log.append(f"{p.name} puts {len(p.hounds)} Faithful Hound{'s' if len(p.hounds) != 1 else ''} into their hand.", "info", 1)
            p.hounds.clear()
    state.boons_discard.extend(state.kept_boons)
    state.kept_boons = []
    state.deluded_turn = False
    state.envious_turn = False
