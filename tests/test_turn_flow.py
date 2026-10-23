import pytest

from dominion.engine import (
    Buy, EndPhase, IllegalActionError, Phase, PlayAction, PlayAllTreasures, PlayTreasure,
)
from dominion.engine.zones import draw_cards
from helpers import make_game, set_zones, snapshot, to_buy_phase


def test_end_action_phase_moves_to_buy():
    g = make_game()
    g.apply(0, EndPhase())
    assert g.state.phase is Phase.BUY


def test_play_all_treasures_adds_coins():
    g = make_game()
    set_zones(g, hand=["Copper", "Copper", "Silver", "Estate", "Estate"])
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    assert g.state.coins == 4
    assert sorted(g.state.players[0].in_play) == ["Copper", "Copper", "Silver"]
    assert g.state.players[0].hand == ["Estate", "Estate"]


def test_play_single_treasure():
    g = make_game()
    set_zones(g, hand=["Gold", "Copper", "Estate", "Estate", "Estate"])
    to_buy_phase(g)
    g.apply(0, PlayTreasure("Gold"))
    assert g.state.coins == 3 and g.state.players[0].hand.count("Gold") == 0


def test_buy_gains_card_and_spends_resources():
    g = make_game()
    set_zones(g, hand=["Silver", "Copper", "Estate", "Estate", "Estate"])
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    g.apply(0, Buy("Silver"))
    assert g.state.coins == 0 and g.state.buys == 0
    assert g.state.players[0].discard == ["Silver"]
    assert g.state.supply["Silver"] == 39


def test_only_one_buy_by_default():
    g = make_game()
    set_zones(g, hand=["Gold", "Gold", "Estate", "Estate", "Estate"])
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    g.apply(0, Buy("Silver"))
    with pytest.raises(IllegalActionError):
        g.apply(0, Buy("Silver"))


def test_cannot_overspend_and_failed_action_changes_nothing():
    g = make_game()
    set_zones(g, hand=["Copper", "Copper", "Estate", "Estate", "Estate"])
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    before = snapshot(g)
    with pytest.raises(IllegalActionError):
        g.apply(0, Buy("Gold"))
    assert snapshot(g) == before


def test_cannot_buy_from_empty_or_missing_pile():
    g = make_game(supply_overrides={"Silver": 0})
    set_zones(g, hand=["Gold", "Gold", "Gold", "Gold", "Gold"])
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    with pytest.raises(IllegalActionError):
        g.apply(0, Buy("Silver"))
    with pytest.raises(IllegalActionError):
        g.apply(0, Buy("Workshop"))      # not in this game's Kingdom


def test_phase_restrictions():
    g = make_game()
    set_zones(g, hand=["Village", "Copper", "Copper", "Copper", "Copper"])
    with pytest.raises(IllegalActionError):
        g.apply(0, PlayTreasure("Copper"))     # treasures only in Buy phase
    with pytest.raises(IllegalActionError):
        g.apply(0, Buy("Copper"))              # buying only in Buy phase
    to_buy_phase(g)
    with pytest.raises(IllegalActionError):
        g.apply(0, PlayAction("Village"))      # actions only in Action phase


def test_wrong_player_rejected():
    g = make_game()
    before = snapshot(g)
    with pytest.raises(IllegalActionError):
        g.apply(1, EndPhase())
    assert snapshot(g) == before


def test_cleanup_discards_draws_and_passes_turn():
    g = make_game()
    set_zones(g, hand=["Copper", "Copper", "Estate", "Estate", "Estate"],
              deck=["Copper"] * 5, discard=[])
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    g.apply(0, EndPhase())
    p0 = g.state.players[0]
    assert len(p0.hand) == 5 and p0.in_play == []
    assert sorted(p0.discard) == ["Copper", "Copper", "Estate", "Estate", "Estate"]
    assert p0.turns_taken == 1
    s = g.state
    assert s.current_player == 1 and s.phase is Phase.ACTION
    assert (s.actions, s.buys, s.coins) == (1, 1, 0) and s.turn_number == 2


def test_turn_order_wraps_around():
    g = make_game(players=3)
    for expected in (0, 1, 2, 0):
        assert g.state.current_player == expected
        g.apply(expected, EndPhase())
        g.apply(expected, EndPhase())


def test_draw_reshuffles_discard_when_deck_runs_out():
    g = make_game()
    set_zones(g, hand=[], deck=["Copper", "Copper"], discard=["Silver"] * 3 + ["Gold"] * 2)
    drawn = draw_cards(g.state, 0, 4)
    assert len(drawn) == 4 and drawn[:2] == ["Copper", "Copper"]
    p = g.state.players[0]
    assert len(p.deck) == 3 and p.discard == []


def test_draw_with_no_cards_left_draws_fewer():
    g = make_game()
    set_zones(g, hand=[], deck=["Copper"], discard=[])
    assert draw_cards(g.state, 0, 3) == ["Copper"]


def test_reshuffle_actually_randomizes_the_discard_pile():
    g = make_game()
    original = ["Copper"] * 15 + ["Gold"] * 15
    set_zones(g, hand=[], deck=[], discard=list(original))
    drawn = draw_cards(g.state, 0, 1)
    p = g.state.players[0]
    assert sorted(p.deck + drawn) == sorted(original)      # nothing lost
    assert p.deck + drawn != original                      # ...but the order changed
