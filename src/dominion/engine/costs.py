# --- Hinterlands Cost Modifiers (Highway) ---
def apply_hinterlands_cost_modifiers(base_cost: int, in_play_cards=()) -> int:
    """Applies Highway (-$1 per copy in play, minimum $0)."""
    highway_count = sum(
        1 for c in in_play_cards if getattr(c, "name", str(c)) == "Highway"
    )
    return max(0, int(base_cost) - highway_count)

# --- apply_dark_ages_cost_modifiers ---
from ..cards.dark_ages import _card_cost as _da_card_cost


def apply_dark_ages_cost_modifiers(state, card_name: str, base_cost: int | None = None) -> int:
    """Return effective cost of a card including Sir Martin ($4 Knight) and state reductions."""
    if base_cost is None:
        return _da_card_cost(card_name, state)
    mod = 0
    if state is not None:
        mod = state.get("cost_reduction", 0) if isinstance(state, dict) else getattr(state, "cost_reduction", 0)
    return max(0, int(base_cost) - int(mod or 0))


def dark_ages_cost_in_range(state, card_name: str, min_cost: int = 3, max_cost: int = 6) -> bool:
    """Check whether a card costs between min_cost and max_cost (inclusive), e.g. $3-$6 for Knights/Rogue/Graverobber."""
    c = _da_card_cost(card_name, state)
    return min_cost <= c <= max_cost

# --- apply_guilds_cost_modifiers ---
def apply_guilds_cost_modifiers(base_cost: int, renown_count: int = 0) -> int:
    return max(0, int(base_cost) - 2 * int(renown_count))


# --- Guilds (2013 / 2024 2E) Overpay Cost Helpers ---
def can_card_overpay(card) -> bool:
    if hasattr(card, "can_overpay") and bool(card.can_overpay):
        return True
    if hasattr(card, "overpay") and bool(card.overpay):
        return True
    cost = getattr(card, "cost", None)
    if cost is not None and getattr(cost, "overpay", False):
        return True
    return False


def compute_overpay(paid_coins: int, base_cost: int) -> int:
    return max(0, int(paid_coins) - int(base_cost))