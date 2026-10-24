# --- Hinterlands Game Loop Integration ---
from ..cards.hinterlands import (
    HINTERLANDS_CARDS,
    _gain_card as hinterlands_gain_card,
    _discard_card as hinterlands_discard_card,
    _trash_card as hinterlands_trash_card,
    _card_cost as hinterlands_card_cost,
)

# --- dark_ages_gain_card ---
from ..cards.dark_ages import _gain_card as dark_ages_gain_card

# --- guilds_gain_card ---
from ..cards.guilds import (
    _gain_card as guilds_gain_card,
    _add_coffers as add_coffers,
    _spend_coffers as spend_coffers,
)


# --- Guilds (2013 / 2024 2E) Game Engine Hooks (Overpay, Coffers, Merchant Guild, Baker Setup) ---
def _guilds_patch_game_class():
    from ..cards import guilds as _guilds_mod

    game_cls = globals().get("Game")
    if game_cls is None:
        return

    orig_init = getattr(game_cls, "__init__", None)
    if orig_init and not getattr(game_cls, "_guilds_init_wrapped", False):
        def _wrapped_init(self, *args, **kwargs):
            orig_init(self, *args, **kwargs)
            if not hasattr(self, "card_registry") or not isinstance(self.card_registry, dict):
                self.card_registry = {}
            self.card_registry.update(_guilds_mod.GUILDS_CARDS)
            for p in getattr(self, "players", []):
                if not hasattr(p, "coffers"):
                    p.coffers = 0
                if not hasattr(p, "coin_tokens"):
                    p.coin_tokens = 0
                if not hasattr(p, "merchant_guild_triggers"):
                    p.merchant_guild_triggers = 0
            supply = getattr(self, "supply", {})
            if "Baker" in supply:
                _guilds_mod.setup_baker(self)

        game_cls.__init__ = _wrapped_init
        game_cls._guilds_init_wrapped = True

    def spend_coffers(self, player, amount: int = 1) -> int:
        actual = _guilds_mod._spend_coffers(player, amount)
        player.coins = (getattr(player, "coins", 0) or 0) + actual
        return actual

    if not hasattr(game_cls, "spend_coffers"):
        game_cls.spend_coffers = spend_coffers

    orig_buy = getattr(game_cls, "buy_card", None)
    if orig_buy and not getattr(game_cls, "_guilds_buy_wrapped", False):
        import inspect
        sig = inspect.signature(orig_buy)

        def _wrapped_buy_card(self, player, card_name, *args, overpay: int = 0, spend_coffers_count: int = 0, **kwargs):
            if spend_coffers_count > 0:
                self.spend_coffers(player, spend_coffers_count)
            spec = _guilds_mod.GUILDS_CARDS.get(
                card_name if isinstance(card_name, str) else getattr(card_name, "name", str(card_name))
            )
            base_cost = _guilds_mod._get_card_cost(self, card_name, player=player)
            avail_coins = getattr(player, "coins", 0) or 0
            # Auto-spend coffers if needed to afford base cost + requested overpay
            needed = base_cost + max(0, int(overpay)) - avail_coins
            if needed > 0 and (getattr(player, "coffers", 0) or 0) >= needed:
                self.spend_coffers(player, needed)

            if "overpay" in sig.parameters:
                res = orig_buy(self, player, card_name, *args, overpay=overpay, **kwargs)
            else:
                res = orig_buy(self, player, card_name, *args, **kwargs)
                if overpay > 0 and spec is not None and getattr(spec, "can_overpay", False):
                    actual_overpay = min(int(overpay), getattr(player, "coins", 0) or 0)
                    player.coins = (getattr(player, "coins", 0) or 0) - actual_overpay
                    if callable(getattr(spec, "on_overpay", None)):
                        spec.on_overpay(self, player, actual_overpay, spec)

            # Merchant Guild trigger: +1 Coffers per Merchant Guild in play when buying a card
            mg_count = getattr(player, "merchant_guild_triggers", 0) or 0
            if mg_count == 0 and hasattr(player, "in_play"):
                mg_count = sum(
                    1 for c in player.in_play if _guilds_mod._card_name(c) == "Merchant Guild"
                )
            if mg_count > 0:
                _guilds_mod._add_coffers(player, mg_count)

            return res

        game_cls.buy_card = _wrapped_buy_card
        game_cls._guilds_buy_wrapped = True
    elif orig_buy is None:
        def buy_card(self, player, card_name, overpay: int = 0, spend_coffers_count: int = 0):
            if spend_coffers_count > 0:
                self.spend_coffers(player, spend_coffers_count)
            name = card_name if isinstance(card_name, str) else getattr(card_name, "name", str(card_name))
            spec = _guilds_mod.GUILDS_CARDS.get(name) or getattr(self, "card_registry", {}).get(name)
            base_cost = _guilds_mod._get_card_cost(self, name, player=player)
            total_cost = base_cost + max(0, int(overpay))
            if (getattr(player, "coins", 0) or 0) < total_cost:
                deficit = total_cost - (getattr(player, "coins", 0) or 0)
                if (getattr(player, "coffers", 0) or 0) >= deficit:
                    self.spend_coffers(player, deficit)
            if (getattr(player, "buys", 1) or 0) <= 0 or (getattr(player, "coins", 0) or 0) < total_cost:
                raise ValueError(f"Cannot buy {name}")
            player.buys = (getattr(player, "buys", 1) or 1) - 1
            player.coins = (getattr(player, "coins", 0) or 0) - total_cost
            gained = _guilds_mod._gain_card(self, player, name)
            mg_count = getattr(player, "merchant_guild_triggers", 0) or sum(
                1 for c in getattr(player, "in_play", []) if _guilds_mod._card_name(c) == "Merchant Guild"
            )
            if mg_count > 0:
                _guilds_mod._add_coffers(player, mg_count)
            if overpay > 0 and spec is not None and callable(getattr(spec, "on_overpay", None)):
                spec.on_overpay(self, player, int(overpay), spec)
            return gained

        game_cls.buy_card = buy_card


_guilds_patch_game_class()