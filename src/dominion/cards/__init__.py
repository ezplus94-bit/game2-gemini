from .base import (
    CardDef, CardType, action, action_victory, duration, treasure, treasure_victory, victory,
)
from .registry import (
    UnknownCardError, expansions, get_card, kingdom_cards, register, unregister,
)
from . import basic, kingdom, alchemy, prosperity, seaside, Cornucopia  # noqa: F401  (importing these registers the cards)

__all__ = [
    "CardDef", "CardType", "action", "action_victory", "duration", "treasure", "treasure_victory", "victory",
    "UnknownCardError", "expansions", "get_card", "kingdom_cards", "register", "unregister",
]

# --- Hinterlands (2011 / 2nd Edition 2022) Card Registration ---
from .hinterlands import (
    HINTERLANDS_CARDS,
    HINTERLANDS_2E_CARDS,
    HINTERLANDS_1E_CARDS,
    HinterlandsCardSpec,
    get_hinterlands_cards,
)

if "ALL_CARDS" in globals() and isinstance(globals()["ALL_CARDS"], dict):
    globals()["ALL_CARDS"].update(HINTERLANDS_CARDS)
if "CARD_REGISTRY" in globals() and isinstance(globals()["CARD_REGISTRY"], dict):
    globals()["CARD_REGISTRY"].update(HINTERLANDS_CARDS)
if "EXPANSION_CARDS" in globals() and isinstance(globals()["EXPANSION_CARDS"], dict):
    globals()["EXPANSION_CARDS"]["hinterlands"] = HINTERLANDS_CARDS

# --- Dark Ages (2012) Card Registration ---
from .dark_ages import (
    ALL_DARK_AGES_CARDS_BY_NAME,
    DARK_AGES_CARDS,
    DARK_AGES_KINGDOM_BY_NAME,
    DARK_AGES_KINGDOM_CARDS,
    DARK_AGES_NON_SUPPLY_CARDS,
    KNIGHT_CARDS,
    RUINS_CARDS,
    RUINS_PILE_SPEC,
    SHELTER_CARDS,
    DarkAgesCardSpec,
)

try:
    if "ALL_CARDS" in globals():
        if isinstance(ALL_CARDS, dict):
            ALL_CARDS.update(ALL_DARK_AGES_CARDS_BY_NAME)
        elif isinstance(ALL_CARDS, list):
            existing_names = {getattr(c, "name", c) for c in ALL_CARDS}
            for _c in DARK_AGES_CARDS:
                if _c.name not in existing_names:
                    ALL_CARDS.append(_c)
    else:
        ALL_CARDS = dict(ALL_DARK_AGES_CARDS_BY_NAME)
except Exception:
    pass

try:
    if "EXPANSION_CARDS" in globals() and isinstance(EXPANSION_CARDS, dict):
        EXPANSION_CARDS["dark_ages"] = DARK_AGES_KINGDOM_CARDS
        EXPANSION_CARDS["Dark Ages"] = DARK_AGES_KINGDOM_CARDS
    else:
        EXPANSION_CARDS = {"dark_ages": DARK_AGES_KINGDOM_CARDS}
except Exception:
    pass

# --- Guilds (2013 / 2024 2E) Card Registration ---
from .guilds import (
    GUILDS_CARDS,
    GUILDS_CARD_DEFS,
    GUILDS_1E_NAMES,
    GUILDS_2E_NAMES,
    ALL_GUILDS_NAMES,
    GuildsCardSpec,
    get_cards as get_guilds_cards,
    register_cards as register_guilds_cards,
)

try:
    if "ALL_CARDS" in globals() and isinstance(ALL_CARDS, dict):
        ALL_CARDS.update(GUILDS_CARDS)
    if "CARD_REGISTRY" in globals() and isinstance(CARD_REGISTRY, dict):
        CARD_REGISTRY.update(GUILDS_CARDS)
    if "EXPANSION_CARDS" in globals() and isinstance(EXPANSION_CARDS, dict):
        EXPANSION_CARDS["guilds"] = GUILDS_CARDS
        EXPANSION_CARDS["Guilds"] = GUILDS_CARDS
except Exception:
    pass

# --- Case-Insensitive Expansion Module Aliases ---
import importlib as _importlib
import sys as _sys
from pathlib import Path as _Path

for _mod_path in _Path(__file__).resolve().parent.glob("*.py"):
    _stem = _mod_path.stem
    if _stem.lower() in ("cornucopia", "hinterlands", "guilds", "dark_ages"):
        try:
            _mod = _importlib.import_module(f"dominion.cards.{_stem}")
            _sys.modules[f"dominion.cards.{_stem.lower()}"] = _mod
            _sys.modules[f"dominion.cards.{_stem.capitalize()}"] = _mod
        except Exception:
            pass