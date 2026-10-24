"""Card costs as they are *right now* (Bridge, Quarry and Peddler make cards cheaper) and which piles are walled off."""

from __future__ import annotations

from ..cards import CardType, get_card
from .state import GameState


def card_cost(state: GameState, name: str) -> int:
    """Printed cost minus this turn's reductions (Bridge for every card, Quarry for Actions, a card's own
    ``cost_mod`` such as Peddler's), never below $0."""
    card = get_card(name)
    reduction = state.cost_reduction
    if card.is_type(CardType.ACTION):
        reduction += state.action_cost_reduction
    if card.cost_mod is not None:
        reduction += card.cost_mod(state)
    return max(0, card.cost - reduction)


def is_walled(state: GameState, name: str, player: int) -> bool:
    """True if Fortnite walls keep ``player`` away from this pile. The wall's owner is never blocked, and
    neither is a player wearing the Invisibility Cloak."""
    owner = state.walls.get(name)
    return owner is not None and owner != player and not state.players[player].invisible
