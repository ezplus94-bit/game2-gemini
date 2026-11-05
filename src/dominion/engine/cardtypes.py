"""Card types as they are in THIS game: a few cards change what another card is (Charlatan makes Curses Treasures)."""

from __future__ import annotations

from ..cards import CardType, get_card


def has_type(state, name: str, card_type: CardType, capitalism: bool = True) -> bool:
    card = get_card(name)
    if card.is_type(card_type):
        return True
    if card_type is CardType.TREASURE:
        if name == "Curse" and state.curse_treasure:
            return True
        # Renaissance: with Capitalism, during your turns, Actions with a "+$" amount in their text are also Treasures
        if (capitalism and card.is_type(CardType.ACTION) and "+$" in card.text
                and "Capitalism" in state.players[state.current_player].projects):
            return True
    return False


def is_treasure(state, name: str) -> bool:
    return has_type(state, name, CardType.TREASURE)


def is_plain_treasure(state, name: str) -> bool:
    """A Treasure by its own type (what "play all Treasures" plays), not one that Capitalism turned an Action into."""
    return has_type(state, name, CardType.TREASURE, capitalism=False) and not get_card(name).is_type(CardType.ACTION)     # (Spell Scroll is played by hand)


def treasure_coins(state, name: str) -> int:
    """The $ a Treasure makes when played (a Curse is worth $1 when Charlatan is in the game)."""
    if name == "Curse" and state.curse_treasure:
        return 1
    return get_card(name).coins


def type_values(state, name: str) -> list:
    """Sorted type names of a card in this game."""
    types = {t.value for t in get_card(name).types}
    if has_type(state, name, CardType.TREASURE):
        types.add(CardType.TREASURE.value)
    return sorted(types)
