"""Card costs as they are *right now* (Bridge makes cards cheaper for a turn) and which piles are walled off."""

from __future__ import annotations

from ..cards import CardType, get_card
from .state import GameState, Phase


def _prosperity_reduction(state: GameState, name: str) -> int:
    if not state.players:
        return 0
    in_play = state.players[state.current_player].in_play
    extra = 0
    card = get_card(name)
    if card.is_type(CardType.ACTION):
        extra += 2 * in_play.count("Quarry")
    if name == "Peddler" and state.phase is Phase.BUY:
        extra += 2 * sum(1 for c in in_play if get_card(c).is_type(CardType.ACTION))
    return extra


def card_cost(state: GameState, name: str) -> int:
    """Printed cost minus this turn's cost reduction, never below $0."""
    extra = _prosperity_reduction(state, name)
    if extra:
        return max(0, get_card(name).cost - state.cost_reduction - extra)
    return max(0, get_card(name).cost - state.cost_reduction)


def is_walled(state: GameState, name: str, player: int) -> bool:
    """True if Fortnite walls keep ``player`` away from this pile. The wall's owner is never blocked, and
    neither is a player wearing the Invisibility Cloak."""
    owner = state.walls.get(name)
    return owner is not None and owner != player and not state.players[player].invisible
