"""Card costs as they are *right now* (Bridge makes cards cheaper for a turn) and which piles are walled off."""

from __future__ import annotations

from ..cards import get_card
from .state import GameState


def card_cost(state: GameState, name: str) -> int:
    """Printed cost minus this turn's cost reduction, never below $0."""
    return max(0, get_card(name).cost - state.cost_reduction)


def is_walled(state: GameState, name: str, player: int) -> bool:
    """True if Fortnite walls keep ``player`` away from this pile. The wall's owner is never blocked, and
    neither is a player wearing the Invisibility Cloak."""
    owner = state.walls.get(name)
    return owner is not None and owner != player and not state.players[player].invisible
