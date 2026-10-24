"""Basic supply cards: Treasures, Victory cards and Curse (and the Potion, which only joins the Supply
when a Kingdom card costs a Potion)."""

from __future__ import annotations

from .base import CardDef, CardType, treasure, victory
from .registry import register

COPPER = register(treasure("Copper", 0, 1))
SILVER = register(treasure("Silver", 3, 2))
GOLD = register(treasure("Gold", 6, 3))
PLATINUM = register(treasure("Platinum", 9, 5))
POTION = register(treasure("Potion", 4, 0, potions=1, text="1 Potion"))

ESTATE = register(victory("Estate", 2, vp=1))
DUCHY = register(victory("Duchy", 5, vp=3))
PROVINCE = register(victory("Province", 8, vp=6))
COLONY = register(victory("Colony", 11, vp=10))

CURSE = register(
    CardDef("Curse", 0, frozenset({CardType.CURSE}), vp=-1, text="-1 VP")
)

# --- Hinterlands Basic Supply Hooks (Duchy -> Duchess, Province -> Fool's Gold) ---
HINTERLANDS_BASIC_HOOKS = {
    "Duchy": "gain_duchess_if_in_supply",
    "Province": "fools_gold_reaction",
}

# --- DARK_AGES_BASIC_HOOKS ---
from .dark_ages import (
    DARK_AGES_NON_SUPPLY_CARDS,
    RUINS_CARDS,
    RUINS_PILE_SPEC,
    SHELTER_CARDS,
)

DARK_AGES_BASIC_HOOKS = {
    "Ruins": RUINS_PILE_SPEC,
    **{c.name: c for c in RUINS_CARDS},
    **{c.name: c for c in SHELTER_CARDS},
    **{c.name: c for c in DARK_AGES_NON_SUPPLY_CARDS},
}

# --- GUILDS_BASIC_HOOKS ---
GUILDS_BASIC_HOOKS = {
    "coffers_supported": True,
    "overpay_supported": True,
    "rewards_supported": True,
}
