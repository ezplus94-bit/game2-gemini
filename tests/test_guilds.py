"""Unit tests for Dominion: Guilds (2013 / Combined 2nd Edition with Cornucopia in 2024)."""

from __future__ import annotations

import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from dominion.cards.guilds import (
    CORNUCOPIA_GUILDS_2E_NEW_KINGDOM_CARDS,
    GUILDS_1E_REMOVED_CARDS,
    GUILDS_ALL_KINGDOM_CARDS,
    GUILDS_CARD_SPECS,
    GUILDS_CORE_KINGDOM_CARDS,
    GUILDS_KINGDOM_CARDS_1E,
    GUILDS_KINGDOM_CARDS_2E,
    OVERPAY_CARDS,
    REWARDS,
    add_coffers,
    apply_guilds_cleanup,
    execute_guilds_card,
    guilds_on_gain_card,
    resolve_merchant_guild_end_of_buy,
    resolve_overpay,
    score_guilds_cards,
    setup_guilds_game,
    spend_coffers,
)


class TestGuildsExpansion(unittest.TestCase):
    def test_card_rosters_1e_and_2e(self) -> None:
        self.assertEqual(len(GUILDS_KINGDOM_CARDS_1E), 13)
        self.assertEqual(len(GUILDS_CORE_KINGDOM_CARDS), 10)
        self.assertEqual(len(GUILDS_1E_REMOVED_CARDS), 3)
        self.assertEqual(len(CORNUCOPIA_GUILDS_2E_NEW_KINGDOM_CARDS), 8)
        self.assertEqual(len(REWARDS), 6)
        for card_name in GUILDS_ALL_KINGDOM_CARDS + REWARDS:
            self.assertIn(card_name, GUILDS_CARD_SPECS)

    def test_coffers_add_and_spend(self) -> None:
        player = {"coins": 2, "coffers": 0}
        self.assertEqual(add_coffers(player, 3), 3)
        spend_coffers(player, 2)
        self.assertEqual(player["coffers"], 1)
        self.assertEqual(player["coins"], 4)
        with self.assertRaises(ValueError):
            spend_coffers(player, 5)

    def test_baker_setup_and_candlestick_maker(self) -> None:
        p1 = {"hand": [], "deck": ["Copper"], "discard": [], "actions": 1, "buys": 1, "coins": 0, "coffers": 0}
        p2 = {"hand": [], "deck": ["Silver"], "discard": [], "actions": 1, "buys": 1, "coins": 0, "coffers": 0}
        game = {"players": [p1, p2], "kingdom": ["Baker", "Candlestick Maker"]}
        setup_info = setup_guilds_game(game)
        self.assertTrue(setup_info["baker_active"])
        self.assertEqual(p1["coffers"], 1)
        self.assertEqual(p2["coffers"], 1)

        execute_guilds_card("Candlestick Maker", p1, game)
        self.assertEqual(p1["actions"], 2)
        self.assertEqual(p1["buys"], 2)
        self.assertEqual(p1["coffers"], 2)

        execute_guilds_card("Baker", p1, game)
        self.assertEqual(p1["coffers"], 3)
        self.assertEqual(p1["hand"], ["Copper"])

    def test_overpay_masterpiece_stonemason_farrier_infirmary(self) -> None:
        player = {"hand": ["Estate", "Curse"], "deck": ["Silver", "Gold"], "discard": [], "coffers": 0}
        game = {"trash": []}

        mp = resolve_overpay("Masterpiece", 3, player, game)
        self.assertEqual(mp["gained"], ["Silver", "Silver", "Silver"])

        sm = resolve_overpay("Stonemason", 4, player, game, {"overpay_action_card": "Plaza"})
        self.assertEqual(sm["gained"], ["Plaza", "Plaza"])

        resolve_overpay("Farrier", 2, player, game)
        self.assertEqual(player["farrier_extra_cards"], 2)
        cleanup = apply_guilds_cleanup(player)
        self.assertEqual(len(cleanup["farrier_drawn"]), 2)

        player["hand"] = ["Estate", "Curse"]
        player["deck"] = ["Copper", "Silver"]
        inf = resolve_overpay("Infirmary", 2, player, game, {"trash_cards": ["Estate", "Curse"]})
        self.assertEqual(inf["replays"], 2)
        self.assertEqual(inf["trashed"], ["Estate", "Curse"])

    def test_butcher_journeyman_advisor_and_soothsayer(self) -> None:
        p1 = {"hand": ["Estate"], "deck": ["Copper", "Curse", "Silver", "Gold"], "discard": [], "coffers": 1}
        p2 = {"hand": ["Copper"], "deck": ["Estate"], "discard": [], "coffers": 0}
        game = {"players": [p1, p2], "trash": [], "curses": 10}

        execute_guilds_card(
            "Butcher",
            p1,
            game,
            {"trash_card": "Estate", "spend_coffers": 3, "gain_card": "Baker"},
        )
        self.assertIn("Baker", p1["discard"])
        self.assertEqual(p1["coffers"], 0)

        jm = execute_guilds_card("Journeyman", p1, game, {"named_card": "Curse"})
        self.assertEqual(jm["drawn_non_named"], ["Copper", "Silver", "Gold"])
        self.assertIn("Curse", p1["discard"])

        execute_guilds_card("Soothsayer", p1, game)
        self.assertIn("Gold", p1["discard"])
        self.assertIn("Curse", p2["discard"])
        self.assertEqual(len(p2["hand"]), 2)

    def test_merchant_guild_end_of_buy_coffers(self) -> None:
        player = {"hand": [], "deck": [], "discard": [], "in_play": [], "buys": 1, "coins": 0, "coffers": 0}
        execute_guilds_card("Merchant Guild", player)
        guilds_on_gain_card("Silver", player, phase="Buy")
        guilds_on_gain_card("Copper", player, phase="Buy")
        earned = resolve_merchant_guild_end_of_buy(player)
        self.assertEqual(earned, 2)
        self.assertEqual(player["coffers"], 2)

    def test_2e_footpad_ferryman_farmhands_carnival_and_joust_rewards(self) -> None:
        p1 = {
            "hand": ["Province", "Copper", "Silver", "Estate"],
            "deck": ["Copper", "Baker", "Butcher", "Baker", "Plaza", "Gold"],
            "discard": [],
            "in_play": [],
            "actions": 1,
            "buys": 1,
            "coins": 0,
            "coffers": 0,
        }
        p2 = {"hand": ["Copper", "Silver", "Gold", "Estate", "Duchy"], "deck": [], "discard": []}
        game = {
            "players": [p1, p2],
            "kingdom": ["Footpad", "Ferryman", "Joust", "Carnival", "Farmhands"],
            "trash": [],
        }
        setup_guilds_game(game, num_players=2, ferryman_pile="Plaza")

        # Footpad attack & Action-phase gain draw (draws "Copper" from top of p1["deck"])
        execute_guilds_card("Footpad", p1, game)
        self.assertEqual(len(p2["hand"]), 3)
        gain_res = guilds_on_gain_card("Ferryman", p1, game, phase="Action")
        self.assertEqual(gain_res["ferryman_bonus"], "Plaza")
        self.assertEqual(gain_res["footpad_draw"], ["Copper"])

        # Carnival reveals next 4: ["Baker", "Butcher", "Baker", "Plaza"] -> 3 distinct to hand, 1 duplicate Baker discarded
        carn = execute_guilds_card("Carnival", p1, game)
        self.assertEqual(len(carn["to_hand"]), 3)
        self.assertEqual(carn["discarded"], ["Baker"])

        # Joust sets aside Province and claims a Reward
        joust_res = execute_guilds_card("Joust", p1, game, {"reward": "Huge Turnip"})
        self.assertEqual(joust_res["gained_reward"], "Huge Turnip")
        self.assertIn("Huge Turnip", p1["hand"])

        # Huge Turnip gives +2 Coffers and +$1 per Coffers
        turnip_res = execute_guilds_card("Huge Turnip", p1, game)
        self.assertGreaterEqual(turnip_res["turnip_coins"], 4)

        # Demesne scoring
        deck_all = ["Demesne", "Gold", "Gold", "Gold", "Silver"]
        self.assertEqual(score_guilds_cards(deck_all), 3)


if __name__ == "__main__":
    unittest.main()
