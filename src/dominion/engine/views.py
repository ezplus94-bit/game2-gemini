# --- Hinterlands View Serialization ---
from ..cards.hinterlands import HINTERLANDS_CARDS


def serialize_hinterlands_state(player) -> dict:
    return {
        "crossroads_played_this_turn": getattr(player, "crossroads_played_this_turn", 0),
        "fools_gold_played_this_turn": getattr(player, "fools_gold_played_this_turn", 0),
        "actions_gained_this_turn": getattr(player, "actions_gained_this_turn", 0),
        "cauldrons_played_this_turn": getattr(player, "cauldrons_played_this_turn", 0),
        "schemes_active_this_turn": getattr(player, "schemes_active_this_turn", 0),
    }

# --- serialize_dark_ages_state ---
def serialize_dark_ages_state(state, player=None) -> dict:
    """Serialize Dark Ages zones, piles, and flags for UI and CLI views."""
    get = (lambda obj, k, d=None: obj.get(k, d) if isinstance(obj, dict) else getattr(obj, k, d))
    knights_pile = get(state, "knights_pile", []) or []
    ruins_pile = get(state, "ruins_pile", []) or []
    trash = get(state, "trash", []) or []
    non_supply = get(state, "non_supply", {}) or {}
    return {
        "expansion": "Dark Ages (2012)",
        "shelters_enabled": bool(get(state, "shelters_enabled", False)),
        "trash": list(trash),
        "trash_count": len(trash),
        "top_knight": knights_pile[0] if knights_pile else None,
        "knights_remaining": len(knights_pile),
        "top_ruins": ruins_pile[0] if ruins_pile else None,
        "ruins_remaining": len(ruins_pile),
        "non_supply": dict(non_supply),
    }

# --- serialize_guilds_state ---
def serialize_guilds_state(player: dict, game: dict | None = None) -> dict:
    return {
        "coffers": player.get("coffers", 0),
        "farrier_extra_cards": player.get("farrier_extra_cards", 0),
        "rewards_remaining": len((game or {}).get("rewards_pile", [])),
        "ferryman_pile": (game or {}).get("ferryman_pile"),
    }