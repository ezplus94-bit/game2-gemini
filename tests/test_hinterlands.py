"""Unit test suite for Dominion: Hinterlands (2011 / 2nd Edition 2022)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

import pytest

from dominion.cards.hinterlands import (
    EXPANSION_ID,
    EXPANSION_NAME,
    HINTERLANDS_1E_CARDS,
    HINTERLANDS_2E_CARDS,
    HINTERLANDS_CARDS,
    _card_cost,
    _discard_card,
    _gain_card,
    _play_card_effect,
    _trash_card,
    score_silk_road,
)
from dominion.rules import apply_scheme_cleanup
from dominion.scoring import score_hinterlands_cards
from dominion.state import reset_hinterlands_turn_state


@dataclass
class DummyPlayer:
    name: str
    hand: List[Any] = field(default_factory=list)
    deck: List[Any] = field(default_factory=list)
    discard: List[Any] = field(default_factory=list)
    in_play: List[Any] = field(default_factory=list)
    actions: int = 1
    buys: int = 1
    coins: int = 0


@dataclass
class DummyGame:
    players: List[DummyPlayer] = field(default_factory=list)
    supply: Dict[str, int] = field(default_factory=dict)
    trash: List[Any] = field(default_factory=list)

    @property
    def current_player(self) -> DummyPlayer:
        return self.players[0]


def make_game() -> tuple[DummyGame, DummyPlayer, DummyPlayer]:
    p1 = DummyPlayer("Alice")
    p2 = DummyPlayer("Bob")
    supply = {
        "Copper": 40,
        "Silver": 40,
        "Gold": 30,
        "Estate": 8,
        "Duchy": 8,
        "Province": 8,
        "Curse": 10,
    }
    for cname in HINTERLANDS_CARDS:
        supply[cname] = 10
    game = DummyGame(players=[p1, p2], supply=supply)
    return game, p1, p2


def test_expansion_metadata_and_counts():
    assert EXPANSION_ID == "hinterlands"
    assert EXPANSION_NAME == "Hinterlands"
    assert len(HINTERLANDS_2E_CARDS) == 26
    assert len(HINTERLANDS_1E_CARDS) == 26
    assert len(HINTERLANDS_CARDS) == 35


def test_crossroads_first_and_second_play():
    game, p1, _ = make_game()
    reset_hinterlands_turn_state(p1)
    p1.hand = ["Estate", "Duchy", "Copper"]
    p1.deck = ["Silver", "Gold", "Oasis"]
    _play_card_effect(game, p1, "Crossroads")
    assert p1.actions == 4  # 1 base + 3 from first Crossroads
    assert len(p1.hand) == 5  # +2 cards for 2 Victory cards in hand

    # Second Crossroads play this turn grants cards for Victory cards, but no +3 Actions
    _play_card_effect(game, p1, "Crossroads")
    assert p1.actions == 4


def test_fools_gold_play_and_province_reaction():
    game, p1, p2 = make_game()
    reset_hinterlands_turn_state(p1)
    _play_card_effect(game, p1, "Fool's Gold")
    assert p1.coins == 1
    _play_card_effect(game, p1, "Fool's Gold")
    assert p1.coins == 5  # +4 on second play

    # Reaction when opponent gains a Province
    p2.hand = ["Fool's Gold"]
    _gain_card(game, p1, "Province")
    assert "Fool's Gold" in game.trash
    assert p2.deck[0] == "Gold"


def test_develop_trashes_and_gains_two_cards_onto_deck():
    game, p1, _ = make_game()
    p1.hand = ["Silver"]  # cost $3
    p1.develop_high_choice = "Spice Merchant"  # cost $4
    p1.develop_low_choice = "Crossroads"  # cost $2
    _play_card_effect(game, p1, "Develop")
    assert "Silver" in game.trash
    assert set(p1.deck[:2]) == {"Spice Merchant", "Crossroads"}


def test_guard_dog_play_and_attack_reaction():
    game, p1, p2 = make_game()
    p1.hand = ["Copper", "Estate"]
    p1.deck = ["Silver", "Gold", "Oasis", "Scheme"]
    _play_card_effect(game, p1, "Guard Dog")
    # Draws 2 -> hand has 4 (<=5) -> draws 2 more -> total 6 in hand
    assert len(p1.hand) == 6

    # Reaction to Attack (Berserker)
    p2.hand = ["Guard Dog", "Copper"]
    p2.deck = ["Silver", "Gold", "Estate", "Duchy"]
    _play_card_effect(game, p1, "Berserker")
    assert "Guard Dog" in p2.in_play
    assert len(p2.hand) == 3  # Guard Dog drew up to 5, then Berserker discarded down to 3


def test_oasis_and_tunnel_discard_reaction():
    game, p1, _ = make_game()
    p1.hand = ["Tunnel"]
    p1.deck = ["Copper"]
    p1.discard_choice = "Tunnel"
    _play_card_effect(game, p1, "Oasis")
    assert p1.actions == 2
    assert p1.coins == 1
    assert "Gold" in p1.discard  # Tunnel triggered on non-cleanup discard


def test_scheme_cleanup_topdeck():
    game, p1, _ = make_game()
    p1.deck = ["Copper"]
    _play_card_effect(game, p1, "Scheme")
    p1.in_play.append("Oasis")
    p1.scheme_topdeck_choice = "Oasis"
    apply_scheme_cleanup(p1)
    assert p1.deck[0] == "Oasis"


def test_jack_of_all_trades():
    game, p1, _ = make_game()
    p1.hand = ["Estate", "Copper"]
    p1.deck = ["Curse", "Silver", "Gold", "Oasis", "Crossroads"]
    p1.jack_discard_top = True
    _play_card_effect(game, p1, "Jack of All Trades")
    assert "Silver" in p1.discard
    assert "Curse" in p1.discard
    assert "Estate" in game.trash


def test_nomads_play_gain_and_trash():
    game, p1, _ = make_game()
    _gain_card(game, p1, "Nomads")
    assert p1.coins == 2
    _play_card_effect(game, p1, "Nomads")
    assert p1.coins == 4
    assert p1.buys == 2
    p1.hand = ["Nomads"]
    _trash_card(game, p1, "Nomads", from_zone="hand")
    assert p1.coins == 6


def test_spice_merchant_both_modes():
    game, p1, _ = make_game()
    p1.hand = ["Copper"]
    p1.deck = ["Silver", "Gold"]
    p1.spice_merchant_mode = "cards_action"
    _play_card_effect(game, p1, "Spice Merchant")
    assert "Copper" in game.trash
    assert len(p1.hand) == 2
    assert p1.actions == 2

    p1.hand = ["Silver"]
    p1.spice_merchant_mode = "buy_coins"
    _play_card_effect(game, p1, "Spice Merchant")
    assert p1.buys == 2
    assert p1.coins == 2


def test_trader_play_and_would_gain_replacement():
    game, p1, _ = make_game()
    p1.hand = ["Gold"]  # cost 6
    _play_card_effect(game, p1, "Trader")
    assert p1.discard.count("Silver") == 6

    p1.hand = ["Trader"]
    p1.use_trader_reaction = True
    _gain_card(game, p1, "Curse")
    assert "Curse" not in p1.discard
    assert p1.discard.count("Silver") == 7


def test_trail_triggers_on_gain_trash_and_discard():
    game, p1, _ = make_game()
    p1.deck = ["Copper", "Silver", "Gold"]
    _gain_card(game, p1, "Trail")
    assert "Trail" in p1.in_play
    assert p1.actions == 2
    assert len(p1.hand) == 1

    # On discard outside cleanup
    p1.in_play.clear()
    p1.hand = ["Trail"]
    _discard_card(game, p1, "Trail", phase="action")
    assert "Trail" in p1.in_play
    assert p1.actions == 3

    # On trash
    p1.in_play.clear()
    p1.hand = ["Trail"]
    _trash_card(game, p1, "Trail", from_zone="hand")
    assert "Trail" in p1.in_play
    assert "Trail" not in game.trash


def test_weaver_play_and_discard_reaction():
    game, p1, _ = make_game()
    _play_card_effect(game, p1, "Weaver")
    assert p1.discard.count("Silver") == 2

    p1.discard.clear()
    p1.hand = ["Weaver"]
    p1.weaver_mode = "card"
    p1.weaver_gain_choice = "Oasis"
    _discard_card(game, p1, "Weaver", phase="action")
    assert "Weaver" in p1.in_play
    assert "Oasis" in p1.discard


def test_berserker_when_gain_with_action_in_play():
    game, p1, p2 = make_game()
    p1.in_play = ["Oasis"]
    p1.berserker_gain_choice = "Silver"
    p2.hand = ["Copper", "Silver", "Gold", "Estate", "Duchy"]
    _gain_card(game, p1, "Berserker")
    assert "Berserker" in p1.in_play
    assert "Silver" in p1.discard
    assert len(p2.hand) == 3


def test_cartographer_filters_top_four_cards():
    game, p1, _ = make_game()
    p1.deck = ["Gold", "Curse", "Estate", "Silver", "Duchy"]
    _play_card_effect(game, p1, "Cartographer")
    assert "Gold" in p1.hand
    assert "Curse" in p1.discard
    assert "Estate" in p1.discard
    assert p1.deck[:2] == ["Silver", "Duchy"]


def test_cauldron_curses_on_third_action_gain():
    game, p1, p2 = make_game()
    reset_hinterlands_turn_state(p1)
    _play_card_effect(game, p1, "Cauldron")
    assert p1.coins == 2
    assert p1.buys == 2
    _gain_card(game, p1, "Oasis")
    _gain_card(game, p1, "Scheme")
    assert "Curse" not in p2.discard
    _gain_card(game, p1, "Crossroads")  # 3rd Action gained this turn
    assert "Curse" in p2.discard


def test_haggler_highway_and_border_village():
    game, p1, _ = make_game()
    _play_card_effect(game, p1, "Highway")
    assert _card_cost(game, "Border Village", p1) == 5

    _play_card_effect(game, p1, "Haggler")
    p1.haggler_gain_choice = "Silver"
    p1.border_village_gain_choice = "Oasis"
    _gain_card(game, p1, "Border Village", bought=True)
    assert "Oasis" in p1.discard
    assert "Silver" in p1.discard


def test_inn_play_and_when_gain_shuffle():
    game, p1, _ = make_game()
    p1.discard = ["Oasis", "Copper", "Crossroads"]
    _gain_card(game, p1, "Inn")
    assert "Oasis" in p1.deck
    assert "Crossroads" in p1.deck
    assert "Inn" in p1.deck
    assert "Copper" in p1.discard


def test_margrave_souk_stables_wheelwright_witchs_hut_farmland():
    game, p1, p2 = make_game()
    # Margrave
    p1.deck = ["Copper", "Silver", "Gold"]
    p2.hand = ["Copper", "Silver", "Gold", "Estate"]
    p2.deck = ["Duchy"]
    _play_card_effect(game, p1, "Margrave")
    assert len(p1.hand) == 3
    assert len(p2.hand) == 3

    # Souk
    p1.hand = ["Curse", "Estate"]
    _gain_card(game, p1, "Souk")
    assert "Curse" in game.trash and "Estate" in game.trash
    p1.coins = 0
    p1.hand = ["Copper", "Silver"]  # 2 cards in hand -> +$7 - $2 = +$5
    _play_card_effect(game, p1, "Souk")
    assert p1.coins == 5

    # Stables
    p1.deck = ["Oasis", "Scheme", "Crossroads"]
    _play_card_effect(game, p1, "Stables")
    assert len(p1.hand) == 4  # had 2, discarded 1 Treasure, drew 3

    # Wheelwright
    p1.deck = ["Gold"]
    p1.wheelwright_discard_choice = "Gold"
    p1.wheelwright_gain_choice = "Highway"
    _play_card_effect(game, p1, "Wheelwright")
    assert "Highway" in p1.discard

    # Witch's Hut
    p2.discard.clear()
    p1.hand = ["Oasis", "Scheme"]
    p1.deck = ["Copper", "Silver", "Gold", "Estate"]
    p1.witchs_hut_discard_choices = ["Oasis", "Scheme"]
    _play_card_effect(game, p1, "Witch's Hut")
    assert "Curse" in p2.discard

    # Farmland
    p1.hand = ["Silver"]  # cost 3 -> gain cost 5
    p1.farmland_gain_choice = "Margrave"
    _gain_card(game, p1, "Farmland", bought=True)
    assert "Silver" in game.trash
    assert "Margrave" in p1.discard


def test_first_edition_legacy_cards():
    game, p1, p2 = make_game()
    # Duchess gained with Duchy
    _gain_card(game, p1, "Duchy")
    assert "Duchess" in p1.discard
    _play_card_effect(game, p1, "Duchess")
    assert p1.coins == 2

    # Cache
    _gain_card(game, p1, "Cache")
    assert p1.discard.count("Copper") == 2

    # Embassy
    _gain_card(game, p1, "Embassy")
    assert "Silver" in p2.discard

    # Ill-Gotten Gains
    p1.igg_gain_copper = True
    _gain_card(game, p1, "Ill-Gotten Gains")
    assert "Curse" in p2.discard
    _play_card_effect(game, p1, "Ill-Gotten Gains")
    assert "Copper" in p1.hand

    # Nomad Camp gained onto deck
    _gain_card(game, p1, "Nomad Camp")
    assert p1.deck[0] == "Nomad Camp"

    # Mandarin
    p1.in_play = ["Silver", "Gold"]
    _gain_card(game, p1, "Mandarin")
    assert set(p1.deck[:2]) == {"Silver", "Gold"}

    # Noble Brigand
    p2.deck = ["Gold", "Estate"]
    _gain_card(game, p1, "Noble Brigand", bought=True)
    assert "Gold" in p1.discard

    # Oracle
    p1.deck = ["Copper", "Silver", "Gold", "Estate"]
    p2.deck = ["Duchy", "Province"]
    _play_card_effect(game, p1, "Oracle")
    assert "Duchy" in p2.discard and "Province" in p2.discard

    # Silk Road scoring
    p1.discard = ["Silk Road", "Tunnel", "Farmland", "Estate"]  # 4 Victory cards -> Silk Road = 1 VP
    assert score_silk_road(p1) == 1
    assert score_hinterlands_cards(p1) == 1 + 2 + 2
