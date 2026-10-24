"""Comprehensive unit test suite for Dominion: Dark Ages (2012)."""

from __future__ import annotations

import unittest

from src.dominion.cards.dark_ages import (
    ALL_DARK_AGES_CARDS_BY_NAME,
    DARK_AGES_CARDS,
    DARK_AGES_KINGDOM_BY_NAME,
    DARK_AGES_KINGDOM_CARDS,
    DARK_AGES_NON_SUPPLY_CARDS,
    KNIGHT_CARDS,
    RUINS_CARDS,
    SHELTER_CARDS,
    cleanup_hermit_discard_from_play,
    react_beggar_on_attack,
    react_hovel_on_victory_buy,
    trigger_urchin_on_attack,
)
from src.dominion.costs import apply_dark_ages_cost_modifiers, dark_ages_cost_in_range
from src.dominion.effects import execute_dark_ages_card
from src.dominion.game import dark_ages_gain_card
from src.dominion.rules import (
    apply_dark_ages_attack_triggers,
    apply_dark_ages_buy_triggers,
    apply_dark_ages_cleanup_rules,
)
from src.dominion.scoring import score_dark_ages_cards
from src.dominion.setup import setup_dark_ages_game, setup_dark_ages_pile_size
from src.dominion.state import reset_dark_ages_turn_state
from src.dominion.views import serialize_dark_ages_state
from src.dominion.zones import dark_ages_trash_card


def make_test_state(kingdom=None, num_players=2, use_shelters=False):
    kingdom = kingdom or ["Rats", "Death Cart", "Knights", "Hermit", "Urchin", "Bandit Camp"]
    players = [
        {
            "name": f"P{i+1}",
            "hand": [],
            "deck": ["Copper"] * 7 + ["Estate"] * 3,
            "discard": [],
            "in_play": [],
            "actions": 1,
            "buys": 1,
            "coins": 0,
            "cards_bought_this_turn": 0,
        }
        for i in range(num_players)
    ]
    state = {
        "players": players,
        "supply": {
            "Copper": 46,
            "Silver": 40,
            "Gold": 30,
            "Estate": 8,
            "Duchy": 8,
            "Province": 8,
            "Curse": 10,
            "Village": 10,
            "Smithy": 10,
            "Market": 10,
        },
        "trash": [],
        "non_supply": {"Madman": 10, "Mercenary": 10, "Spoils": 15},
    }
    setup_dark_ages_game(state, kingdom, num_players=num_players, use_shelters=use_shelters, seed=42)
    return state


class TestDarkAgesCatalogAndSetup(unittest.TestCase):
    def test_card_counts_and_categories(self):
        self.assertEqual(len(DARK_AGES_KINGDOM_CARDS), 35)
        self.assertEqual(len(KNIGHT_CARDS), 10)
        self.assertEqual(len(RUINS_CARDS), 5)
        self.assertEqual(len(SHELTER_CARDS), 3)
        self.assertEqual(len(DARK_AGES_NON_SUPPLY_CARDS), 3)

        # Verify Sir Martin costs $4 and Dame Josephine is Victory worth 2 VP
        sir_martin = ALL_DARK_AGES_CARDS_BY_NAME["Sir Martin"]
        self.assertEqual(sir_martin.cost, 4)
        dame_josephine = ALL_DARK_AGES_CARDS_BY_NAME["Dame Josephine"]
        self.assertIn("Victory", dame_josephine.types)
        self.assertEqual(dame_josephine.vp, 2)

    def test_setup_rats_knights_ruins_and_shelters(self):
        state = make_test_state(
            kingdom=["Rats", "Marauder", "Knights", "Hermit", "Urchin"],
            num_players=3,
            use_shelters=True,
        )
        self.assertEqual(state["supply"]["Rats"], 20)
        self.assertEqual(len(state["knights_pile"]), 10)
        self.assertEqual(len(state["ruins_pile"]), 20)  # 10 * (3 - 1)
        self.assertTrue(state["shelters_enabled"])
        p1_cards = state["players"][0]["deck"] + state["players"][0]["hand"]
        self.assertIn("Hovel", p1_cards)
        self.assertIn("Necropolis", p1_cards)
        self.assertIn("Overgrown Estate", p1_cards)
        self.assertNotIn("Estate", p1_cards)


class TestDarkAgesWhenTrashedAndReactions(unittest.TestCase):
    def test_fortress_returns_to_hand_when_trashed(self):
        state = make_test_state()
        p1 = state["players"][0]
        p1["hand"] = ["Fortress"]
        dark_ages_trash_card(state, p1, "Fortress", source_zone="hand")
        self.assertIn("Fortress", p1["hand"])
        self.assertNotIn("Fortress", state["trash"])

    def test_squire_feodum_overgrown_estate_cultist_hunting_grounds_on_trash(self):
        state = make_test_state()
        p1 = state["players"][0]
        p1["hand"] = ["Squire", "Feodum", "Overgrown Estate", "Cultist", "Hunting Grounds", "Sir Vander"]
        p1["deck"] = ["Copper"] * 10

        dark_ages_trash_card(state, p1, "Squire", source_zone="hand", choices={"gain_attack": "Urchin"})
        self.assertIn("Urchin", p1["discard"])

        dark_ages_trash_card(state, p1, "Feodum", source_zone="hand")
        self.assertEqual(p1["discard"].count("Silver"), 3)

        hand_before = len(p1["hand"])
        dark_ages_trash_card(state, p1, "Overgrown Estate", source_zone="hand")
        self.assertEqual(len(p1["hand"]), hand_before)  # lost 1, drew 1

        hand_before = len(p1["hand"])
        dark_ages_trash_card(state, p1, "Cultist", source_zone="hand")
        self.assertEqual(len(p1["hand"]), hand_before + 2)  # lost 1, drew 3

        dark_ages_trash_card(state, p1, "Hunting Grounds", source_zone="hand", choices={"hunting_grounds_gain": "estates"})
        self.assertEqual(p1["discard"].count("Estate"), 3)

        dark_ages_trash_card(state, p1, "Sir Vander", source_zone="hand")
        self.assertIn("Gold", p1["discard"])

    def test_market_square_reaction_on_trash(self):
        state = make_test_state()
        p1 = state["players"][0]
        p1["hand"] = ["Copper", "Market Square"]
        dark_ages_trash_card(state, p1, "Copper", source_zone="hand", choices={"react_market_square": True})
        self.assertNotIn("Market Square", p1["hand"])
        self.assertIn("Market Square", p1["discard"])
        self.assertIn("Gold", p1["discard"])

    def test_hovel_reaction_on_victory_buy(self):
        state = make_test_state()
        p1 = state["players"][0]
        p1["hand"] = ["Hovel", "Copper"]
        triggered = apply_dark_ages_buy_triggers(state, p1, "Province", {"trash_hovel": True})
        self.assertTrue(triggered)
        self.assertIn("Hovel", state["trash"])
        self.assertEqual(p1["cards_bought_this_turn"], 1)


class TestDarkAgesNonSupplyLifecycles(unittest.TestCase):
    def test_hermit_to_madman_lifecycle(self):
        state = make_test_state()
        p1 = state["players"][0]
        p1["hand"] = ["Estate"]
        p1["in_play"] = ["Hermit"]
        execute_dark_ages_card(
            state,
            p1,
            "Hermit",
            {"trash_card": "Estate", "trash_zone": "hand", "gain_card": "Silver"},
        )
        self.assertIn("Estate", state["trash"])
        self.assertIn("Silver", p1["discard"])

        # Cleanup with 0 buys -> trashes Hermit and gains Madman
        transformed = apply_dark_ages_cleanup_rules(state, p1)
        self.assertTrue(transformed)
        self.assertIn("Hermit", state["trash"])
        self.assertIn("Madman", p1["discard"])

        # Play Madman with 3 cards in hand -> +2 Actions, returns to Madman pile, draws 3 cards
        p1["hand"] = ["Copper", "Copper", "Copper"]
        p1["in_play"] = ["Madman"]
        p1["deck"] = ["Silver", "Silver", "Silver", "Gold"]
        madman_before = state["non_supply"]["Madman"]
        execute_dark_ages_card(state, p1, "Madman")
        self.assertEqual(state["non_supply"]["Madman"], madman_before + 1)
        self.assertEqual(len(p1["hand"]), 6)

    def test_urchin_to_mercenary_and_beggar_reaction(self):
        state = make_test_state()
        p1, p2 = state["players"][0], state["players"][1]
        p1["in_play"] = ["Urchin"]
        p2["hand"] = ["Beggar", "Copper", "Copper", "Copper", "Copper"]
        res = apply_dark_ages_attack_triggers(
            state,
            p1,
            "Marauder",
            {"trash_urchin": True, "react_beggar": True},
        )
        self.assertTrue(res["urchin_triggered"])
        self.assertIn("Urchin", state["trash"])
        self.assertIn("Mercenary", p1["discard"])
        self.assertEqual(p2["deck"][0], "Silver")
        self.assertIn("Silver", p2["discard"])

        # Play Mercenary trashing 2 cards
        p1["hand"] = ["Copper", "Estate"]
        p1["deck"] = ["Gold", "Gold"]
        p2["hand"] = ["Copper"] * 5
        execute_dark_ages_card(state, p1, "Mercenary", {"trash_cards": ["Copper", "Estate"]})
        self.assertEqual(len(p1["hand"]), 2)
        self.assertEqual(p1["coins"], 2)
        self.assertEqual(len(p2["hand"]), 3)

    def test_spoils_gain_and_return(self):
        state = make_test_state()
        p1, p2 = state["players"][0], state["players"][1]
        p1["in_play"] = ["Pillage"]
        p2["hand"] = ["Copper", "Copper", "Copper", "Silver", "Gold"]
        execute_dark_ages_card(state, p1, "Pillage", {"force_discard": "Gold"})
        self.assertIn("Pillage", state["trash"])
        self.assertNotIn("Gold", p2["hand"])
        self.assertEqual(p1["discard"].count("Spoils"), 2)

        spoils_before = state["non_supply"]["Spoils"]
        p1["in_play"] = ["Spoils"]
        execute_dark_ages_card(state, p1, "Spoils")
        self.assertEqual(p1["coins"], 3)
        self.assertEqual(state["non_supply"]["Spoils"], spoils_before + 1)


class TestDarkAgesKingdomMechanics(unittest.TestCase):
    def test_forager_graverobber_rogue_trash_interactions(self):
        state = make_test_state()
        p1 = state["players"][0]
        state["trash"] = ["Copper", "Silver", "Smithy"]
        p1["hand"] = ["Gold"]
        execute_dark_ages_card(state, p1, "Forager", {"trash_card": "Gold"})
        # 3 differently named Treasures in trash: Copper, Silver, Gold
        self.assertEqual(p1["coins"], 3)

        # Graverobber gains Smithy ($4) from trash onto deck
        execute_dark_ages_card(state, p1, "Graverobber", {"mode": "from_trash", "trash_target": "Smithy"})
        self.assertEqual(p1["deck"][0], "Smithy")

        # Rogue gains Gold ($6) from trash
        execute_dark_ages_card(state, p1, "Rogue", {"trash_target": "Gold"})
        self.assertIn("Gold", p1["discard"])

    def test_procession_counterfeit_and_band_of_misfits(self):
        state = make_test_state()
        p1 = state["players"][0]
        p1["hand"] = ["Fortress"]
        p1["deck"] = ["Copper"] * 5
        execute_dark_ages_card(
            state,
            p1,
            "Procession",
            {"action_card": "Fortress", "gain_card": "Market"},
        )
        # Fortress played twice (+2 Cards, +4 Actions), trashed (Fortress returns to hand!), and gained Market ($5)
        self.assertIn("Fortress", p1["hand"])
        self.assertIn("Market", p1["discard"])
        self.assertEqual(p1["actions"], 5)

        # Counterfeit plays Silver twice (+$4 + $1 = $5) and trashes Silver
        p1["coins"] = 0
        p1["hand"] = ["Silver"]
        execute_dark_ages_card(state, p1, "Counterfeit", {"treasure_card": "Silver"})
        self.assertEqual(p1["coins"], 5)
        self.assertIn("Silver", state["trash"])

        # Band of Misfits emulates Smithy ($4 < $5)
        p1["hand"] = []
        p1["deck"] = ["Copper", "Silver", "Gold"]
        execute_dark_ages_card(state, p1, "Band of Misfits", {"emulate_card": "Smithy"})
        self.assertEqual(len(p1["hand"]), 3)

    def test_poor_house_rebuild_mystic_sage_vagrant_ironmonger(self):
        state = make_test_state()
        p1 = state["players"][0]
        p1["hand"] = ["Copper", "Silver"]
        execute_dark_ages_card(state, p1, "Poor House")
        self.assertEqual(p1["coins"], 2)  # +$4 - 2 Treasures = $2

        p1["deck"] = ["Copper", "Estate", "Province"]
        execute_dark_ages_card(
            state,
            p1,
            "Rebuild",
            {"named_card": "Province", "gain_card": "Duchy"},
        )
        self.assertIn("Estate", state["trash"])
        self.assertIn("Duchy", p1["discard"])

        p1["deck"] = ["Gold"]
        execute_dark_ages_card(state, p1, "Mystic", {"named_card": "Gold"})
        self.assertIn("Gold", p1["hand"])

        p1["deck"] = ["Copper", "Estate", "Silver"]
        execute_dark_ages_card(state, p1, "Sage")
        self.assertIn("Silver", p1["hand"])

        p1["deck"] = ["Estate", "Copper"]
        execute_dark_ages_card(state, p1, "Vagrant")
        self.assertIn("Estate", p1["hand"])

        p1["deck"] = ["Estate", "Copper"]
        execute_dark_ages_card(state, p1, "Ironmonger", {"discard_revealed": True})
        self.assertIn("Estate", p1["discard"])

    def test_knights_clash_and_scoring(self):
        state = make_test_state()
        p1, p2 = state["players"][0], state["players"][1]
        p1["in_play"] = ["Sir Bailey"]
        p2["deck"] = ["Sir Vander", "Copper"]
        execute_dark_ages_card(state, p1, "Sir Bailey")
        # Sir Vander ($5 Knight) trashed -> Sir Vander gains Gold for p2 AND Sir Bailey trashes itself!
        self.assertIn("Sir Vander", state["trash"])
        self.assertIn("Gold", p2["discard"])
        self.assertIn("Sir Bailey", state["trash"])

        # Scoring test: 7 Silvers + 2 Feodums (2 * 2 = 4 VP) + Dame Josephine (2 VP) + Overgrown Estate (0 VP) = 6 VP
        cards = ["Silver"] * 7 + ["Feodum", "Feodum", "Dame Josephine", "Overgrown Estate"]
        self.assertEqual(score_dark_ages_cards(cards), 6)

        view = serialize_dark_ages_state(state)
        self.assertEqual(view["expansion"], "Dark Ages (2012)")
        self.assertGreaterEqual(view["trash_count"], 2)


if __name__ == "__main__":
    unittest.main()
