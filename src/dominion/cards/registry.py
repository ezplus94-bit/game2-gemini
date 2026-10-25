"""Global card registry: name -> CardDef.

Adding a card to the game = defining a CardDef and calling ``register``.
The engine never needs to change.
"""

from __future__ import annotations

from .base import CardDef, CardType


class UnknownCardError(KeyError):
    pass


_CARDS: dict[str, CardDef] = {}


def register(card: CardDef) -> CardDef:
    if card.name in _CARDS:
        raise ValueError(f"Card already registered: {card.name}")
    _CARDS[card.name] = card
    return card


def unregister(name: str) -> None:
    """Remove a card (intended for tests that register temporary cards)."""
    _CARDS.pop(name, None)


def get_card(name: str) -> CardDef:
    try:
        return _CARDS[name]
    except KeyError:
        raise UnknownCardError(name) from None


def fenced_cards() -> list[str]:
    """Every optional house-rule card a host can pick (Catastrophe and Special): 2 copies, own supply row.
    Companion pieces (the rest of Exodia) come in automatically with their main card and are not listed."""
    return sorted(
        name for name, card in _CARDS.items()
        if (CardType.CATASTROPHE in card.types or CardType.SPECIAL in card.types) and card.companion_of is None
    )


def special_cards() -> list[str]:
    return sorted(
        name for name, card in _CARDS.items()
        if CardType.SPECIAL in card.types and card.companion_of is None
    )


def companion_cards() -> list[str]:
    """The extra pieces that arrive with another card (Exodia's four limbs)."""
    return sorted(name for name, card in _CARDS.items() if card.companion_of is not None)


def catastrophe_cards() -> list[str]:
    """Names of every Catastrophe card (optional house-rule cards, never in a random Kingdom)."""
    return sorted(name for name, card in _CARDS.items() if CardType.CATASTROPHE in card.types)


def prize_cards() -> list[str]:
    """Names of every Cornucopia Prize card (non-Supply cards gained via Tournament)."""
    return sorted(name for name, card in _CARDS.items() if CardType.PRIZE in card.types)


def kingdom_cards(expansions=None) -> list[str]:
    """Names of every card that may be selected as a Kingdom pile.
    ``expansions`` (e.g. ``["Intrigue"]``) limits the list to those card sets; None = all."""
    return sorted(
        name for name, card in _CARDS.items()
        if card.kingdom and (expansions is None or card.expansion in expansions)
    )


def expansions() -> list[str]:
    """Names of the card sets that have Kingdom cards (Base first)."""
    found = {card.expansion for card in _CARDS.values() if card.kingdom}
    return sorted(found, key=lambda e: (e != "Base", e))
