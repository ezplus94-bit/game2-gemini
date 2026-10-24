import pytest

from dominion.engine import (
    Buy, EndPhase, GameStatus, IllegalActionError, PlayAllTreasures, determine_winners,
)
from helpers import make_game, set_zones, to_buy_phase


def end_turn(game):
    game.apply(game.state.current_player, EndPhase())
    game.apply(game.state.current_player, EndPhase())


def test_buying_last_province_ends_game_at_end_of_turn_not_immediately():
    g = make_game(supply_overrides={"Province": 1})
    set_zones(g, hand=["Gold", "Gold", "Silver", "Estate", "Estate"])
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    g.apply(0, Buy("Province"))
    assert g.state.supply["Province"] == 0
    assert g.state.status is GameStatus.ACTIVE          # turn is not over yet
    g.apply(0, EndPhase())
    assert g.state.status is GameStatus.FINISHED
    assert g.state.winners == [0]                       # Province 6 + 3 Estates beats 3 Estates
    with pytest.raises(IllegalActionError):
        g.apply(1, EndPhase())


def test_three_empty_piles_end_the_game():
    g = make_game(supply_overrides={"Curse": 0, "Duchy": 0, "Estate": 0})
    end_turn(g)
    assert g.state.status is GameStatus.FINISHED


def test_two_empty_piles_do_not_end_the_game():
    g = make_game(supply_overrides={"Curse": 0, "Duchy": 0})
    end_turn(g)
    assert g.state.status is GameStatus.ACTIVE


def test_fewer_turns_breaks_a_tie():
    g = make_game()
    for p in g.state.players:
        set_zones(g, g.state.players.index(p), hand=[], deck=["Estate"], discard=[])
    g.state.players[0].turns_taken = 5
    g.state.players[1].turns_taken = 4
    assert determine_winners(g.state) == [1]


def test_full_tie_is_shared():
    g = make_game()
    for i in (0, 1):
        set_zones(g, i, hand=[], deck=["Estate"], discard=[])
        g.state.players[i].turns_taken = 5
    assert determine_winners(g.state) == [0, 1]


def test_higher_score_wins_regardless_of_turns():
    g = make_game()
    set_zones(g, 0, hand=[], deck=["Province"], discard=[])
    set_zones(g, 1, hand=[], deck=["Estate"], discard=[])
    g.state.players[0].turns_taken = 10
    g.state.players[1].turns_taken = 1
    assert determine_winners(g.state) == [0]
