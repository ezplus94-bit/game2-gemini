import pytest

from dominion.engine import (
    Buy, Choose, EndPhase, IllegalActionError, PlayAction, PlayAllTreasures, PlayTreasure,
)
from helpers import make_game, set_zones, to_buy_phase


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
