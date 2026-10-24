"""Card types as they are in THIS game: a few cards change what another card is (Charlatan makes Curses Treasures)."""

from __future__ import annotations

from ..cards import CardType, get_card


def has_type(state, name: str, card_type: CardType) -> bool:
    if get_card(name).is_type(card_type):
        return True
    return card_type is CardType.TREASURE and name == "Curse" and state.curse_treasure


def is_treasure(state, name: str) -> bool:
    return has_type(state, name, CardType.TREASURE)


def treasure_coins(state, name: str) -> int:
    """The $ a Treasure makes when played (a Curse is worth $1 when Charlatan is in the game)."""
    if name == "Curse" and state.curse_treasure:
        return 1
    return get_card(name).coins


def type_values(state, name: str) -> list:
    """Sorted type names of a card in this game."""
    types = {t.value for t in get_card(name).types}
    if name == "Curse" and state.curse_treasure:
        types.add(CardType.TREASURE.value)
    return sorted(types)
