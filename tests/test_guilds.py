"""Unit test suite for Dominion: Guilds (2013 / 2024 2nd Edition)."""

from __future__ import annotations

import pytest

from dominion.cards.guilds import (
    ALL_GUILDS_NAMES,
    GUILDS_1E_NAMES,
    GUILDS_2E_NAMES,
    GUILDS_CARD_DEFS,
    GUILDS_CARDS,
    _add_coffers,
    _spend_coffers,
    overpay_doctor,
    overpay_farrier,
    overpay_herald,
    overpay_infirmary,
    overpay_masterpiece,
    overpay_stonemason,
    play_advisor,
    play_baker,
    play_butcher,
    play_candlestick_maker,
    play_doctor,
    play_farrier,
    play_footpad,
    play_herald,
    play_infirmary,
    play_journeyman,
    play_masterpiece,
    play_merchant_guild,
    play_plaza,
    play_shop,
    play_soothsayer,
    play_stonemason,
    play_taxman,
    setup_baker,
)


class DummyPlayer:
    def __init__(self, name: str = "P1") -> None:
        self.name = name
        self.hand: list = []
        self.deck: list = []
        self.discard: list = []
        self.in_play: list = []
        self.actions: int = 1
        self.buys: int = 1
        self.coins: int = 0
        self.coffers: int = 0
        self.coin_tokens: int = 0
        self.decisions: list = []
        self.named_card: str | None = None
        self.merchant_guild_triggers: int = 0


class DummyGame:
    def __init__(self, players: list[DummyPlayer] | None = None, supply: dict[str, int] | None = None) -> None:
        self.players = players or [DummyPlayer("P1"), DummyPlayer("P2")]
        self.trash: list = []
        self.card_registry = dict(GUILDS_CARDS)
        base_supply = {
            "Copper": 46,
            "Silver": 40,
            "Gold": 30,
            "Estate": 8,
            "Duchy": 8,
            "Province": 8,
            "Curse": 10,
        }
        for name in ALL_GUILDS_NAMES:
            base_supply[name] = 10
        if supply:
            base_supply.update(supply)
        self.supply = base_supply

    def get_cost(self, card, player=None) -> int:
        name = card if isinstance(card, str) else getattr(card, "name", str(card))
        basic_costs = {
            "Copper": 0,
            "Curse": 0,
            "Estate": 2,
            "Silver": 3,
            "Duchy": 5,
            "Gold": 6,
            "Province": 8,
        }
        if name in basic_costs:
            return basic_costs[name]
        spec = self.card_registry.get(name)
        if spec is not None:
            c = getattr(spec, "cost", 0)
            return int(c.coins if hasattr(c, "coins") else c)
        return 0


def test_guilds_card_catalog_completeness():
    """Verify all 13 original 2013 Guilds cards and 4 2024 2E cards are registered."""
    expected_1e = {
        "Candlestick Maker",
        "Stonemason",
        "Doctor",
        "Masterpiece",
        "Advisor",
        "Plaza",
        "Taxman",
        "Herald",
        "Baker",
        "Butcher",
        "Journeyman",
        "Merchant Guild",
        "Soothsayer",
    }
    assert expected_1e == set(GUILDS_1E_NAMES)
    assert len(GUILDS_1E_NAMES) == 13
    expected_2e_additions = {"Farrier", "Shop", "Infirmary", "Footpad"}
    assert expected_2e_additions.issubset(set(GUILDS_2E_NAMES))
    assert len(GUILDS_CARD_DEFS) == 17
    for name in ALL_GUILDS_NAMES:
        assert name in GUILDS_CARDS


def test_candlestick_maker():
    game = DummyGame()
    p1 = game.players[0]
    play_candlestick_maker(game, p1)
    assert p1.actions == 2
    assert p1.buys == 2
    assert p1.coffers == 1
    assert p1.coin_tokens == 1


def test_stonemason_play_and_overpay():
    game = DummyGame()
    p1 = game.players[0]
    p1.hand = ["Gold"]
    p1.decisions = ["Gold", "Baker", "Butcher"]
    play_stonemason(game, p1)
    assert "Gold" in game.trash
    assert "Baker" in p1.discard
    assert "Butcher" in p1.discard

    # Overpay $4 -> gain 2 Action cards costing $4
    p1.discard.clear()
    p1.decisions = ["Plaza", "Advisor"]
    overpay_stonemason(game, p1, overpaid=4)
    assert p1.discard == ["Plaza", "Advisor"]


def test_doctor_play_and_overpay():
    game = DummyGame()
    p1 = game.players[0]
    p1.deck = ["Copper", "Silver", "Copper", "Gold"]
    play_doctor(game, p1, named_card="Copper")
    assert game.trash.count("Copper") == 2
    assert p1.deck == ["Silver", "Gold"]

    p1.decisions = ["trash", "discard"]
    overpay_doctor(game, p1, overpaid=2)
    assert "Silver" in game.trash
    assert "Gold" in p1.discard


def test_masterpiece_play_and_overpay():
    game = DummyGame()
    p1 = game.players[0]
    play_masterpiece(game, p1)
    assert p1.coins == 1
    overpay_masterpiece(game, p1, overpaid=3)
    assert p1.discard.count("Silver") == 3


def test_advisor():
    game = DummyGame()
    p1, p2 = game.players[0], game.players[1]
    p1.deck = ["Copper", "Gold", "Estate"]
    p2.decisions = ["Gold"]
    play_advisor(game, p1)
    assert p1.actions == 2
    assert "Gold" in p1.discard
    assert set(p1.hand) == {"Copper", "Estate"}


def test_plaza():
    game = DummyGame()
    p1 = game.players[0]
    p1.deck = ["Estate"]
    p1.hand = ["Copper"]
    p1.decisions = ["Copper"]
    play_plaza(game, p1)
    assert p1.actions == 3
    assert "Estate" in p1.hand
    assert "Copper" in p1.discard
    assert p1.coffers == 1


def test_taxman():
    game = DummyGame()
    p1, p2 = game.players[0], game.players[1]
    p1.hand = ["Silver"]
    p2.hand = ["Silver", "Copper", "Estate", "Duchy", "Province"]
    p1.decisions = ["Silver", "Gold"]
    play_taxman(game, p1)
    assert "Silver" in game.trash
    assert "Silver" in p2.discard
    assert len(p2.hand) == 4
    assert p1.deck[0] == "Gold"


def test_herald_play_and_overpay():
    game = DummyGame()
    p1 = game.players[0]
    p1.deck = ["Silver", "Candlestick Maker"]
    play_herald(game, p1)
    # Draws Silver, reveals Candlestick Maker and plays it for +1 Action, +1 Buy, +1 Coffers
    assert "Silver" in p1.hand
    assert p1.actions == 3
    assert p1.buys == 2
    assert p1.coffers == 1

    p1.discard = ["Gold", "Copper"]
    p1.decisions = ["Gold"]
    overpay_herald(game, p1, overpaid=1)
    assert p1.deck[0] == "Gold"


def test_baker_and_setup():
    game = DummyGame()
    setup_baker(game)
    assert all(p.coffers == 1 for p in game.players)
    p1 = game.players[0]
    p1.deck = ["Copper"]
    play_baker(game, p1)
    assert p1.coffers == 2
    assert p1.actions == 2
    assert "Copper" in p1.hand


def test_butcher():
    game = DummyGame()
    p1 = game.players[0]
    p1.hand = ["Estate"]
    # Trash Estate ($2), spend 2 Coffers -> gain up to $4 (Plaza)
    p1.decisions = ["Estate", 2, "Plaza"]
    play_butcher(game, p1)
    assert "Estate" in game.trash
    assert p1.coffers == 0
    assert "Plaza" in p1.discard


def test_journeyman():
    game = DummyGame()
    p1 = game.players[0]
    p1.deck = ["Copper", "Silver", "Copper", "Gold", "Estate"]
    play_journeyman(game, p1, named_card="Copper")
    assert p1.hand == ["Silver", "Gold", "Estate"]
    assert p1.discard == ["Copper", "Copper"]


def test_merchant_guild_and_soothsayer():
    game = DummyGame()
    p1, p2 = game.players[0], game.players[1]
    play_merchant_guild(game, p1)
    assert p1.buys == 2
    assert p1.coins == 1
    assert p1.merchant_guild_triggers == 1

    p2.deck = ["Copper"]
    play_soothsayer(game, p1)
    assert "Gold" in p1.discard
    assert "Curse" in p2.discard
    assert "Copper" in p2.hand


def test_guilds_2e_cards():
    game = DummyGame()
    p1, p2 = game.players[0], game.players[1]
    p1.deck = ["Copper", "Silver", "Gold"]
    play_farrier(game, p1)
    assert p1.actions == 2
    assert p1.buys == 2
    overpay_farrier(game, p1, overpaid=2)
    assert len(p1.hand) == 3

    p1.hand = ["Candlestick Maker"]
    p1.deck = ["Estate"]
    p1.decisions = ["Candlestick Maker"]
    play_shop(game, p1)
    assert p1.coffers == 1

    p1.hand = ["Curse", "Copper"]
    p1.deck = ["Silver", "Gold"]
    p1.decisions = ["Curse", "Copper"]
    overpay_infirmary(game, p1, overpaid=2)
    assert "Curse" in game.trash

    p2.hand = ["Copper", "Copper", "Copper", "Copper", "Copper", "Copper"]
    play_footpad(game, p1)
    assert len(p2.hand) == 4
