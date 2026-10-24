# --- Hinterlands Kingdom Setup Rules ---
from .cards.hinterlands import HINTERLANDS_CARDS, HINTERLANDS_2E_CARDS


def setup_hinterlands_pile_size(card_name: str, num_players: int = 2) -> int:
    spec = HINTERLANDS_CARDS.get(card_name)
    if spec and spec.is_victory:
        return 8 if num_players == 2 else 12
    return 10

# --- setup_dark_ages_game ---
import random as _da_random
from .cards.dark_ages import (
    ALL_DARK_AGES_CARDS_BY_NAME,
    DARK_AGES_KINGDOM_BY_NAME,
    KNIGHT_CARDS,
    RUINS_CARDS,
    SHELTER_CARDS,
)


def setup_dark_ages_pile_size(card_name: str, num_players: int = 2) -> int:
    """Return initial pile size for Dark Ages cards (Rats=20, Ruins=10*(N-1), Spoils=15, others=10)."""
    if card_name == "Rats":
        return 20
    if card_name == "Ruins":
        return 10 * max(1, num_players - 1)
    if card_name == "Spoils":
        return 15
    if card_name in ("Madman", "Mercenary", "Knights"):
        return 10
    return 10


def build_ruins_pile(num_players: int = 2, seed: int | None = None) -> list[str]:
    """Build a shuffled Ruins pile of 10 * max(1, num_players - 1) cards drawn from 50 total Ruins."""
    pool: list[str] = []
    for spec in RUINS_CARDS:
        pool.extend([spec.name] * 10)
    rng = _da_random.Random(seed)
    rng.shuffle(pool)
    needed = 10 * max(1, num_players - 1)
    return pool[:needed]


def build_knights_pile(seed: int | None = None) -> list[str]:
    """Build a shuffled 10-card Knights split pile."""
    names = [k.name for k in KNIGHT_CARDS]
    rng = _da_random.Random(seed)
    rng.shuffle(names)
    return names


def setup_dark_ages_game(
    state,
    kingdom_cards: list[str],
    num_players: int = 2,
    use_shelters: bool | None = None,
    seed: int | None = None,
):
    """Configure supply, non-supply piles, Looter Ruins pile, Knights split pile, and starting Shelters."""
    supply = state.get("supply", {}) if isinstance(state, dict) else getattr(state, "supply", {})
    if isinstance(state, dict):
        state["supply"] = supply
    else:
        setattr(state, "supply", supply)

    for k in kingdom_cards:
        supply[k] = setup_dark_ages_pile_size(k, num_players)

    if "Knights" in kingdom_cards:
        knights_deck = build_knights_pile(seed=seed)
        if isinstance(state, dict):
            state["knights_pile"] = knights_deck
        else:
            setattr(state, "knights_pile", knights_deck)

    has_looter = any(
        (k in ALL_DARK_AGES_CARDS_BY_NAME and ALL_DARK_AGES_CARDS_BY_NAME[k].is_looter)
        for k in kingdom_cards
    )
    if has_looter:
        ruins_deck = build_ruins_pile(num_players=num_players, seed=seed)
        supply["Ruins"] = len(ruins_deck)
        if isinstance(state, dict):
            state["ruins_pile"] = ruins_deck
        else:
            setattr(state, "ruins_pile", ruins_deck)

    non_supply = {}
    if "Hermit" in kingdom_cards:
        non_supply["Madman"] = 10
    if "Urchin" in kingdom_cards:
        non_supply["Mercenary"] = 10
    if any(k in kingdom_cards for k in ("Bandit Camp", "Marauder", "Pillage")):
        non_supply["Spoils"] = 15
    if isinstance(state, dict):
        existing_ns = state.get("non_supply", {})
        existing_ns.update(non_supply)
        state["non_supply"] = existing_ns
    else:
        existing_ns = getattr(state, "non_supply", {}) or {}
        existing_ns.update(non_supply)
        setattr(state, "non_supply", existing_ns)

    if use_shelters is None:
        use_shelters = any(k in DARK_AGES_KINGDOM_BY_NAME for k in kingdom_cards)
    if isinstance(state, dict):
        state["shelters_enabled"] = bool(use_shelters)
    else:
        setattr(state, "shelters_enabled", bool(use_shelters))

    players = state.get("players", []) if isinstance(state, dict) else getattr(state, "players", [])
    if use_shelters and players:
        shelter_names = [s.name for s in SHELTER_CARDS]
        for p in players:
            deck = p.get("deck", []) if isinstance(p, dict) else getattr(p, "deck", [])
            hand = p.get("hand", []) if isinstance(p, dict) else getattr(p, "hand", [])
            combined = list(deck) + list(hand)
            if combined:
                estates_replaced = 0
                new_cards = []
                for c in combined:
                    if c == "Estate" and estates_replaced < 3:
                        new_cards.append(shelter_names[estates_replaced])
                        estates_replaced += 1
                    else:
                        new_cards.append(c)
                if isinstance(p, dict):
                    p["deck"] = new_cards
                    p["hand"] = []
                else:
                    setattr(p, "deck", new_cards)
                    setattr(p, "hand", [])
            else:
                starting = ["Copper"] * 7 + list(shelter_names)
                if isinstance(p, dict):
                    p["deck"] = starting
                else:
                    setattr(p, "deck", starting)
    return state

# --- setup_guilds_game ---
from dominion.cards.guilds import setup_guilds_game


# --- Guilds (2013 / 2024 2E) Setup Hook (Baker +1 Coffers at start of game) ---
def _guilds_setup_hook(game) -> None:
    from .cards.guilds import setup_baker
    supply = getattr(game, "supply", {})
    if "Baker" in supply:
        setup_baker(game)
