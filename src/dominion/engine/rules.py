class IllegalActionError(Exception):
    """Raised when a player attempts an invalid or illegal action."""
    pass

# --- Hinterlands Cleanup & Reaction Rules (Scheme, Trail, Weaver, Tunnel) ---
def apply_scheme_cleanup(player) -> None:
    """Allows top-decking up to `schemes_active_this_turn` Action cards from play during Clean-up."""
    schemes = getattr(player, "schemes_active_this_turn", 0)
    if schemes <= 0:
        return
    in_play = getattr(player, "in_play", getattr(player, "play_area", []))
    deck = getattr(player, "deck", [])
    choice = getattr(player, "scheme_topdeck_choice", None)
    for _ in range(schemes):
        actions_in_play = [
            c for c in in_play
            if "Action" in getattr(c, "types", ("Action",)) or getattr(c, "name", str(c)) != "Copper"
        ]
        if not actions_in_play:
            break
        target = choice if choice in actions_in_play else actions_in_play[0]
        in_play.remove(target)
        deck.insert(0, target)
    player.schemes_active_this_turn = 0

# --- apply_dark_ages_cleanup_rules ---
from ..cards.dark_ages import (
    cleanup_hermit_discard_from_play,
    react_beggar_on_attack,
    react_hovel_on_victory_buy,
    trigger_urchin_on_attack,
)


def apply_dark_ages_cleanup_rules(state, player, choices: dict | None = None) -> bool:
    """Handle Dark Ages cleanup triggers such as Hermit's discard-from-play -> Madman transformation."""
    in_play = player.get("in_play", []) if isinstance(player, dict) else getattr(player, "in_play", [])
    if "Hermit" in in_play:
        return cleanup_hermit_discard_from_play(state, player, choices)
    return False


def apply_dark_ages_attack_triggers(state, attacker, attack_card_name: str, choices: dict | None = None) -> dict:
    """Resolve Urchin in-play trigger for attacker and Beggar hand reactions for defenders."""
    choices = choices or {}
    urchin_triggered = trigger_urchin_on_attack(state, attacker, attack_card_name, choices)
    beggar_defenders = []
    players = state.get("players", []) if isinstance(state, dict) else getattr(state, "players", [])
    for p in players:
        if p is not attacker and choices.get("react_beggar", False):
            if react_beggar_on_attack(state, p, choices):
                beggar_defenders.append(p)
    return {"urchin_triggered": urchin_triggered, "beggar_defenders": beggar_defenders}


def apply_dark_ages_buy_triggers(state, buyer, bought_card_name: str, choices: dict | None = None) -> bool:
    """Record card bought this turn and trigger Hovel reaction if buying a Victory card."""
    if isinstance(buyer, dict):
        buyer["cards_bought_this_turn"] = int(buyer.get("cards_bought_this_turn", 0)) + 1
    else:
        setattr(buyer, "cards_bought_this_turn", int(getattr(buyer, "cards_bought_this_turn", 0)) + 1)
    return react_hovel_on_victory_buy(state, buyer, bought_card_name, choices)

# --- apply_guilds_cleanup_rules ---
try:
    from ..cards.guilds import (
        apply_guilds_cleanup as apply_guilds_cleanup_rules,
        resolve_merchant_guild_end_of_buy,
    )
except ImportError:
    # Safe fallbacks if Guilds cleanup handlers are missing
    def apply_guilds_cleanup_rules(state, player, choices: dict | None = None) -> bool:
        return False

    def resolve_merchant_guild_end_of_buy(state, player, choices: dict | None = None) -> bool:
        return False

# --- Guilds (2013 / 2024 2E) Rules: Spending Coffers & Overpay ---
def use_coffers_for_coins(game, player, count: int) -> int:
    if hasattr(player, "spend_coffers"):
        return player.spend_coffers(count, for_coins=True)
    cur = getattr(player, "coffers", getattr(player, "coin_tokens", 0)) or 0
    actual = max(0, min(int(count), cur))
    player.coffers = cur - actual
    player.coin_tokens = player.coffers
    player.coins = (getattr(player, "coins", 0) or 0) + actual
    return actual

