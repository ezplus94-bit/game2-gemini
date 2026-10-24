# --- Hinterlands Victory Scoring (Tunnel, Farmland, Silk Road) ---
from ..cards.hinterlands import HINTERLANDS_CARDS, score_silk_road


def score_hinterlands_cards(player) -> int:
    seen_ids = set()
    all_cards = []
    for attr in ("hand", "deck", "discard", "discard_pile", "in_play", "play_area"):
        z = getattr(player, attr, None)
        if isinstance(z, list) and id(z) not in seen_ids:
            seen_ids.add(id(z))
            all_cards.extend(z)
    total = 0
    for c in all_cards:
        name = getattr(c, "name", str(c))
        if name in ("Tunnel", "Farmland"):
            total += 2
        elif name == "Silk Road":
            total += score_silk_road(player)
    return total

# --- score_dark_ages_cards ---
from ..cards.dark_ages import _card_name as _da_score_card_name, score_feodum


def score_dark_ages_cards(player_cards) -> int:
    """Compute total Victory Points from Dark Ages Victory cards (Feodum, Dame Josephine, Overgrown Estate)."""
    names = [_da_score_card_name(c) for c in player_cards]
    total_vp = 0
    for name in names:
        if name == "Feodum":
            total_vp += score_feodum(names)
        elif name == "Dame Josephine":
            total_vp += 2
        elif name == "Overgrown Estate":
            total_vp += 0
    return total_vp

# --- score_guilds_cards ---
from ..cards.guilds import score_guilds_cards


# --- Guilds (2013 / 2024 2E) Scoring Notes ---
guilds_scoring_notes = "Guilds introduces Coffers and Overpay; no non-standard Victory tokens are added."