
# --- DARK_AGES_EXPANSION_NAME ---
DARK_AGES_EXPANSION_NAME = "Dark Ages (2012)"


def format_dark_ages_cli_summary(state) -> str:
    """Format a compact CLI summary of Trash, Ruins, Knights, Shelters, and Non-Supply piles."""
    from src.dominion.views import serialize_dark_ages_state

    info = serialize_dark_ages_state(state)
    ns = info["non_supply"]
    ns_str = ", ".join(f"{k}:{v}" for k, v in sorted(ns.items())) or "None"
    return (
        f"[{DARK_AGES_EXPANSION_NAME}] "
        f"Shelters={info['shelters_enabled']} | "
        f"Trash({info['trash_count']})={info['trash']} | "
        f"TopKnight={info['top_knight']} ({info['knights_remaining']}) | "
        f"Ruins={info['ruins_remaining']} | "
        f"NonSupply=({ns_str})"
    )

# --- GUILDS_EXPANSION_NAME ---
from dominion.cards.guilds import GUILDS_EXPANSION_NAME, GUILDS_ALL_KINGDOM_CARDS
