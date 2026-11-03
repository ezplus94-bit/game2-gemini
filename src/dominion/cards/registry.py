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


def kingdom_cards(expansions=None) -> list[str]:
    """Names of every card that may be selected as a Kingdom pile.
    ``expansions`` (e.g. ``["Intrigue"]``) limits the list to those card sets; None = all."""
    return sorted(
        name for name, card in _CARDS.items()
        if card.kingdom and (expansions is None or card.expansion in expansions)
    )


def supporting_cards(expansion: str) -> list[str]:
    """Cards of a card set that are never a Kingdom pile themselves (Dark Ages: the Knights, Ruins, Shelters, Spoils...)."""
    return sorted(name for name, card in _CARDS.items()
                  if card.expansion == expansion and not card.kingdom and card.companion_of is None and CardType.EVENT not in card.types
                  and CardType.CATASTROPHE not in card.types and CardType.SPECIAL not in card.types
                  and CardType.PRIZE not in card.types and CardType.REWARD not in card.types and CardType.LANDMARK not in card.types
                  and CardType.WAY not in card.types and CardType.ALLY not in card.types)


def event_cards(expansions=None) -> list[str]:
    """Names of every Event (Adventures, Empires): bought with a Buy, never gained, never part of the Kingdom.
    ``expansions`` limits the list to those card sets."""
    return sorted(name for name, card in _CARDS.items()
                  if CardType.EVENT in card.types and (expansions is None or card.expansion in expansions))


def landmark_cards(expansions=None) -> list[str]:
    """Names of every Landmark (Empires): a standing rule for the whole game, never bought or gained."""
    return sorted(name for name, card in _CARDS.items()
                  if CardType.LANDMARK in card.types and (expansions is None or card.expansion in expansions))


def project_cards(expansions=None) -> list[str]:
    """Names of every Project (Renaissance): bought with a Buy and its cost in $, a permanent ability for the buyer, never part of the Kingdom."""
    return sorted(name for name, card in _CARDS.items()
                  if CardType.PROJECT in card.types and (expansions is None or card.expansion in expansions))


def way_cards(expansions=None) -> list[str]:
    """Names of every Way (Menagerie): a standing option for each Action played, never bought or gained, never part of the Kingdom."""
    return sorted(name for name, card in _CARDS.items()
                  if CardType.WAY in card.types and (expansions is None or card.expansion in expansions))


def ally_cards() -> list[str]:
    """Names of every Ally (Allies): the landscape cards that say what Favor tokens can be spent on."""
    return sorted(name for name, card in _CARDS.items() if CardType.ALLY in card.types)


def expansions() -> list[str]:
    """Names of the card sets that have Kingdom cards (Base first)."""
    found = {card.expansion for card in _CARDS.values() if card.kingdom}
    return sorted(found, key=lambda e: (e != "Base", e))
