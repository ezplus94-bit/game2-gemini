# --- Hinterlands Effect Dispatchers ---
from ..cards.hinterlands import (
    HINTERLANDS_CARDS,
    _gain_card,
    _discard_card,
    _trash_card,
    _play_card_effect,
)


def execute_hinterlands_card(game, player, card_name: str) -> bool:
    spec = HINTERLANDS_CARDS.get(card_name)
    if spec and spec.on_play:
        spec.on_play(game, player)
        return True
    return False

# --- execute_dark_ages_card ---
from ..cards.dark_ages import ALL_DARK_AGES_CARDS_BY_NAME


def execute_dark_ages_card(state, player, card_name: str, choices: dict | None = None) -> bool:
    """Execute the on_play handler for any Dark Ages card."""
    spec = ALL_DARK_AGES_CARDS_BY_NAME.get(card_name)
    if spec is None or spec.on_play is None:
        return False
    spec.on_play(state, player, choices or {})
    return True

# --- execute_guilds_card ---
try:
    from ..cards.guilds import execute_guilds_card, resolve_overpay
except ImportError:
    def execute_guilds_card(game, player, card_name: str) -> bool:
        return False

    def resolve_overpay(game, player, card, overpaid: int) -> None:
        pass


# --- Guilds (2013 / 2024 2E) Effects Helpers ---
def trigger_overpay_effect(game, player, card, overpaid: int) -> None:
    if overpaid <= 0:
        return
    fn = getattr(card, "on_overpay", None)
    if callable(fn):
        fn(game, player, overpaid, card)
        return
    registry = getattr(game, "card_registry", {})
    name = card if isinstance(card, str) else getattr(card, "name", str(card))
    spec = registry.get(name)
    if spec is not None and callable(getattr(spec, "on_overpay", None)):
        spec.on_overpay(game, player, overpaid, spec)