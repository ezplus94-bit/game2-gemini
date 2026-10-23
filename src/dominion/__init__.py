"""Modinion: a modular, testable deck-building game engine (the Python package keeps the name `dominion`)."""

from .cards.base import CardDef, CardType, action, action_victory, treasure, treasure_victory, victory
from .cards.registry import (
    UnknownCardError, expansions, get_card, kingdom_cards, register, unregister,
)
from .cards import basic, kingdom  # noqa: F401  (importing these registers the cards)

__version__ = "0.11.0"

__all__ = [
    "CardDef", "CardType", "action", "action_victory", "treasure", "treasure_victory", "victory",
    "UnknownCardError", "expansions", "get_card", "kingdom_cards", "register", "unregister",
]
