"""Card costs as they are *right now* (Bridge, Quarry and Peddler make cards cheaper) and which piles are walled off."""

from __future__ import annotations

from ..cards import CardType, get_card
from .state import GameState


def card_cost(state: GameState, name: str) -> int:
    """Printed cost minus this turn's reductions (Bridge for every card, Quarry for Actions, a card's own
    ``cost_mod`` such as Peddler's), never below $0."""
    if name == "Wayfarer" and state.last_gain is not None:      # Menagerie: costs the same as the last other card gained this turn
        return card_cost(state, state.last_gain)
    card = get_card(name)
    name_ = name
    reduction = state.cost_reduction
    if card.is_type(CardType.ACTION):
        reduction += state.action_cost_reduction
    if card.cost_mod is not None:
        reduction += card.cost_mod(state)
    for name in state.players[state.current_player].in_play:     # "while this is in play, cards cost less" (Princess)
        reduction += get_card(name).cost_aura
    if state.players[state.current_player].tokens.get("-$2 Cost") == state.stack_of.get(name_, name_):   # Adventures: Ferry's token
        reduction += 2
    reduction += state.pile_tokens.get(state.stack_of.get(name_, name_), 0)      # Allies: Family of Inventors
    if state.traits and state.traits.get(state.stack_of.get(name_, name_)) == "Cheap":                 # Plunder: Cheap cards cost $1 less
        reduction += 1
    if "Canal" in state.players[state.current_player].projects:                                       # Renaissance: Canal, during your turns
        reduction += 1
    return max(0, card.cost - reduction)


def is_walled(state: GameState, name: str, player: int) -> bool:
    """True if Fortnite walls keep ``player`` away from this pile. The wall's owner is never blocked, and
    neither is a player wearing the Invisibility Cloak."""
    owner = state.walls.get(name)
    return owner is not None and owner != player and not state.players[player].invisible


def is_buried(state: GameState, name: str) -> bool:
    """Dark Ages mixed piles (Knights, Ruins): only the top card of the pile can be bought or gained."""
    pile = state.stack_of.get(name)
    if pile is None:
        return False
    stack = state.stacks.get(pile) or []
    return not stack or stack[0] != name


def full_cost(state: GameState, name: str) -> tuple:
    """(coins right now, Potions, Debt): a card's whole cost. Two costs are identical only if all three match."""
    card = get_card(name)
    return (card_cost(state, name), card.potion_cost, card.debt_cost)


def costs_more(state: GameState, a: str, b: str) -> bool:
    """Empires: does ``a`` cost more than ``b``? Every part of its cost is at least as big and one is bigger
    (Fortune $8 + 8 Debt costs more than Overlord 8 Debt, but Overlord does not cost more than Silver)."""
    ca, cb = full_cost(state, a), full_cost(state, b)
    return all(x >= y for x, y in zip(ca, cb)) and ca != cb
