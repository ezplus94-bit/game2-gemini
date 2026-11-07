"""Engine rules: legal actions, turn flow and the end of the game."""

import pytest
from dominion.engine import (
    Buy,
    Choose,
    EndPhase,
    IllegalActionError,
    PlayAction,
    PlayAllTreasures,
    PlayTreasure,
    Phase,
    GameStatus,
    determine_winners,
)
from helpers import make_game, set_zones, to_buy_phase, snapshot
from dominion.engine.zones import draw_cards


# ======================================================================
# from test_rules.py
# ======================================================================

def test_action_phase_legal_actions():
    g = make_game()
    set_zones(g, hand=["Village", "Village", "Copper", "Copper", "Copper"])
    assert g.legal_actions() == [PlayAction("Village"), EndPhase()]


def test_no_actions_left_means_only_end_phase():
    g = make_game()
    set_zones(g, hand=["Smithy", "Village", "Copper", "Copper", "Copper"])
    g.state.actions = 0
    assert g.legal_actions() == [EndPhase()]


def test_buy_phase_legal_actions_respect_coins_and_buys():
    g = make_game()
    set_zones(g, hand=["Copper", "Copper", "Copper", "Estate", "Estate"])
    to_buy_phase(g)
    legal = g.legal_actions()
    assert PlayTreasure("Copper") in legal and PlayAllTreasures() in legal
    assert Buy("Copper") in legal and Buy("Curse") in legal     # $0 cards are always affordable
    assert Buy("Silver") not in legal                            # no coins played yet
    g.apply(0, PlayAllTreasures())
    legal = g.legal_actions()
    assert Buy("Silver") in legal and Buy("Village") in legal    # $3 cards now affordable
    assert Buy("Smithy") not in legal                            # $4
    g.apply(0, Buy("Silver"))
    assert not any(isinstance(a, Buy) for a in g.legal_actions())   # out of Buys


def test_every_legal_action_validates_and_non_actor_has_none():
    g = make_game()
    assert g.legal_actions(player=1) == []
    for action in g.legal_actions():
        assert g.validate(0, action) is None


def test_pending_decision_blocks_everything_but_the_answer():
    g = make_game()
    set_zones(g, hand=["Cellar", "Estate", "Copper", "Copper", "Copper"])
    g.apply(0, PlayAction("Cellar"))
    assert g.state.pending is not None
    assert all(isinstance(a, Choose) for a in g.legal_actions())
    for action in (EndPhase(), PlayAction("Cellar")):
        with pytest.raises(IllegalActionError):
            g.apply(0, action)
    with pytest.raises(IllegalActionError):
        g.apply(1, Choose(()))                      # wrong player


def test_choose_without_pending_decision_is_illegal():
    g = make_game()
    with pytest.raises(IllegalActionError):
        g.apply(0, Choose(()))


def test_finished_game_has_no_legal_actions():
    g = make_game(supply_overrides={"Province": 0})
    g.apply(0, EndPhase())
    g.apply(0, EndPhase())        # end of turn: Province pile is empty -> game over
    assert g.legal_actions() == []
    with pytest.raises(IllegalActionError):
        g.apply(1, EndPhase())

# ======================================================================
# from test_turn_flow.py
# ======================================================================

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

# ======================================================================
# from test_endgame.py
# ======================================================================

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
