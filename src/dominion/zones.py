# --- Hinterlands Zone Transition Hooks ---
from .cards.hinterlands import _discard_card as hinterlands_discard_card
from .cards.hinterlands import _trash_card as hinterlands_trash_card
from .cards.hinterlands import _gain_card as hinterlands_gain_card

# --- dark_ages_trash_card ---
from .cards.dark_ages import (
    _push_to_pile,
    _non_supply_piles,
    _trash_card as dark_ages_trash_card,
    react_market_square_on_trash,
)


def dark_ages_return_to_pile(state, player, card_name: str, pile_name: str | None = None) -> bool:
    """Return a non-supply card (such as Madman or Spoils) from play/hand to its pile."""
    target_pile = pile_name or card_name
    in_play = state.get("in_play", []) if isinstance(state, dict) else getattr(player, "in_play", [])
    if card_name in in_play:
        in_play.remove(card_name)
    _push_to_pile(_non_supply_piles(state), target_pile, card_name)
    return True

# --- guilds_zone_helpers ---
def guilds_zone_helpers(player_state: dict) -> dict:
    return {
        "coffers": player_state.get("coffers", 0),
        "joust_set_aside": list(player_state.get("joust_set_aside", [])),
        "farmhands_pending": list(player_state.get("farmhands_pending", [])),
    }


# --- Guilds (2013 / 2024 2E) Zone/Mat Definitions ---
COFFERS_MAT = "coffers_mat"
