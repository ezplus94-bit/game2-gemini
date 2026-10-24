# --- Hinterlands Turn & State Tracking ---
HINTERLANDS_TURN_STATE_DEFAULTS = {
    "crossroads_played_this_turn": 0,
    "fools_gold_played_this_turn": 0,
    "actions_gained_this_turn": 0,
    "cauldrons_played_this_turn": 0,
    "schemes_active_this_turn": 0,
}


def reset_hinterlands_turn_state(player_or_state) -> None:
    """Resets per-turn counters used by Hinterlands cards."""
    for attr, default in HINTERLANDS_TURN_STATE_DEFAULTS.items():
        setattr(player_or_state, attr, default)

# --- DARK_AGES_TURN_STATE_DEFAULTS ---
DARK_AGES_TURN_STATE_DEFAULTS = {
    "cards_bought_this_turn": 0,
    "trashed_this_turn": [],
    "in_play_urchins": [],
    "shelters_enabled": False,
    "ruins_pile": [],
    "knights_pile": [],
    "non_supply": {
        "Madman": 10,
        "Mercenary": 10,
        "Spoils": 15,
    },
}


def reset_dark_ages_turn_state(state_or_player):
    """Reset per-turn Dark Ages counters on a state or player object."""
    if isinstance(state_or_player, dict):
        state_or_player["cards_bought_this_turn"] = 0
        state_or_player["trashed_this_turn"] = []
        state_or_player["in_play_urchins"] = []
    else:
        setattr(state_or_player, "cards_bought_this_turn", 0)
        setattr(state_or_player, "trashed_this_turn", [])
        setattr(state_or_player, "in_play_urchins", [])
    return state_or_player

# --- GUILDS_TURN_STATE_DEFAULTS ---
GUILDS_TURN_STATE_DEFAULTS = {
    "coffers": 0,
    "merchant_guilds_in_play": 0,
    "cards_gained_in_buy_phase": 0,
    "farrier_extra_cards": 0,
    "joust_set_aside": [],
    "farmhands_pending": [],
    "renown_discount": 0,
}


# --- Guilds (2013 / 2024 2E) State Extensions: Coffers & Overpay ---
def _guilds_patch_player_state():
    target_cls = globals().get("PlayerState") or globals().get("Player")
    if target_cls is None:
        return
    if not hasattr(target_cls, "coffers"):
        target_cls.coffers = 0
    if not hasattr(target_cls, "coin_tokens"):
        target_cls.coin_tokens = 0
    if not hasattr(target_cls, "merchant_guild_triggers"):
        target_cls.merchant_guild_triggers = 0

    def add_coffers(self, amount: int = 1) -> int:
        cur = getattr(self, "coffers", 0) or 0
        new_val = max(0, cur + int(amount))
        self.coffers = new_val
        self.coin_tokens = new_val
        return new_val

    def spend_coffers(self, amount: int = 1, for_coins: bool = True) -> int:
        cur = getattr(self, "coffers", 0) or 0
        actual = max(0, min(int(amount), cur))
        self.coffers = cur - actual
        self.coin_tokens = self.coffers
        if for_coins:
            self.coins = (getattr(self, "coins", 0) or 0) + actual
        return actual

    if not hasattr(target_cls, "add_coffers"):
        target_cls.add_coffers = add_coffers
    if not hasattr(target_cls, "spend_coffers"):
        target_cls.spend_coffers = spend_coffers


_guilds_patch_player_state()
