import pytest

from dominion.engine import (
    Choose, EndPhase, IllegalActionError, PlayAction, PlayAllTreasures, score_player,
)
from helpers import make_game, set_zones, to_buy_phase


def play(game, card):
    game.apply(0, PlayAction(card))


# ----------------------------------------------------------- simple cards
def test_village():
    g = make_game()
    set_zones(g, hand=["Village", "Copper"], deck=["Silver", "Gold"])
    play(g, "Village")
    s = g.state
    assert s.actions == 2                    # 1 - 1 (played) + 2
    assert sorted(s.players[0].hand) == ["Copper", "Gold"]


def test_smithy_draws_three():
    g = make_game()
    set_zones(g, hand=["Smithy"], deck=["Copper"] * 5)
    play(g, "Smithy")
    assert len(g.state.players[0].hand) == 3 and g.state.actions == 0


def test_market():
    g = make_game()
    set_zones(g, hand=["Market"], deck=["Silver"])
    play(g, "Market")
    s = g.state
    assert (s.actions, s.buys, s.coins) == (1, 2, 1)
    assert s.players[0].hand == ["Silver"]


def test_festival():
    g = make_game()
    set_zones(g, hand=["Festival"])
    play(g, "Festival")
    s = g.state
    assert (s.actions, s.buys, s.coins) == (2, 2, 2)


def test_laboratory():
    g = make_game()
    set_zones(g, hand=["Laboratory"], deck=["Gold", "Silver", "Copper"])
    play(g, "Laboratory")
    assert len(g.state.players[0].hand) == 2 and g.state.actions == 1


def test_action_cards_chain_with_extra_actions():
    g = make_game()
    set_zones(g, hand=["Village", "Smithy"], deck=["Copper"] * 6)
    play(g, "Village")
    play(g, "Smithy")
    assert len(g.state.players[0].hand) == 1 + 3      # Village drew 1, Smithy drew 3
    assert g.state.actions == 1


def test_cannot_play_action_with_no_actions_left():
    g = make_game()
    set_zones(g, hand=["Smithy", "Smithy"], deck=["Copper"] * 6)
    play(g, "Smithy")
    with pytest.raises(IllegalActionError):
        play(g, "Smithy")


# ------------------------------------------------------ interactive cards
def test_cellar_discards_then_draws_same_number():
    g = make_game()
    set_zones(g, hand=["Cellar", "Copper", "Estate", "Estate", "Silver"],
              deck=["Copper", "Gold", "Silver"])      # top of deck is the END
    play(g, "Cellar")
    assert g.state.actions == 1                        # +1 Action
    decision = g.state.pending.decision
    assert sorted(decision.options) == ["Copper", "Estate", "Estate", "Silver"]
    assert (decision.min_choices, decision.max_choices) == (0, 4)
    g.apply(0, Choose(("Estate", "Estate")))
    p = g.state.players[0]
    assert g.state.pending is None
    assert p.discard == ["Estate", "Estate"]
    assert sorted(p.hand) == ["Copper", "Gold", "Silver", "Silver"]
    assert p.deck == ["Copper"]


def test_cellar_choosing_nothing_is_allowed():
    g = make_game()
    set_zones(g, hand=["Cellar", "Copper", "Copper"])
    play(g, "Cellar")
    g.apply(0, Choose(()))
    assert g.state.pending is None and len(g.state.players[0].hand) == 2


def test_invalid_answers_are_rejected_and_leave_the_decision_open():
    g = make_game()
    set_zones(g, hand=["Cellar", "Copper", "Estate", "Estate"])
    play(g, "Cellar")
    with pytest.raises(IllegalActionError):
        g.apply(0, Choose(("Gold",)))                          # not in hand
    with pytest.raises(IllegalActionError):
        g.apply(0, Choose(("Estate", "Estate", "Estate")))     # only two Estates
    assert g.state.pending is not None
    g.apply(0, Choose(("Estate",)))                            # a valid answer still works


def test_chapel_trashes_up_to_four():
    g = make_game()
    set_zones(g, hand=["Chapel", "Estate", "Estate", "Estate", "Copper", "Copper"])
    play(g, "Chapel")
    with pytest.raises(IllegalActionError):
        g.apply(0, Choose(("Estate", "Estate", "Estate", "Copper", "Copper")))   # 5 > 4
    g.apply(0, Choose(("Estate", "Estate", "Estate", "Copper")))
    assert sorted(g.state.trash) == ["Copper", "Estate", "Estate", "Estate"]
    assert g.state.players[0].hand == ["Copper"]


def test_workshop_gains_card_costing_up_to_four():
    g = make_game(kingdom=["Workshop", "Village", "Market"])
    set_zones(g, hand=["Workshop"])
    play(g, "Workshop")
    options = g.state.pending.decision.options
    assert "Silver" in options and "Village" in options
    assert "Gold" not in options and "Market" not in options       # cost 6 and 5
    with pytest.raises(IllegalActionError):
        g.apply(0, Choose(("Gold",)))
    g.apply(0, Choose(("Silver",)))
    assert g.state.players[0].discard == ["Silver"] and g.state.supply["Silver"] == 39


def test_workshop_cannot_offer_empty_piles():
    g = make_game(kingdom=["Workshop"], supply_overrides={"Silver": 0})
    set_zones(g, hand=["Workshop"])
    play(g, "Workshop")
    assert "Silver" not in g.state.pending.decision.options


def test_remodel_trash_then_gain_up_to_two_more():
    g = make_game()
    set_zones(g, hand=["Remodel", "Estate", "Copper"])
    play(g, "Remodel")
    g.apply(0, Choose(("Estate",)))                       # cost 2 -> may gain up to $4
    assert g.state.trash == ["Estate"]
    options = g.state.pending.decision.options
    assert "Smithy" in options and "Silver" in options
    assert "Gold" not in options and "Market" not in options
    with pytest.raises(IllegalActionError):
        g.apply(0, Choose(("Gold",)))
    g.apply(0, Choose(("Smithy",)))
    assert g.state.players[0].discard == ["Smithy"] and g.state.pending is None


def test_remodel_gold_into_province():
    g = make_game()
    set_zones(g, hand=["Remodel", "Gold"])
    play(g, "Remodel")
    g.apply(0, Choose(("Gold",)))
    assert "Province" in g.state.pending.decision.options      # $6 + $2 = $8
    g.apply(0, Choose(("Province",)))
    assert g.state.players[0].discard == ["Province"]


def test_remodel_with_empty_hand_does_nothing():
    g = make_game()
    set_zones(g, hand=["Remodel"])
    play(g, "Remodel")
    assert g.state.pending is None


def test_moneylender_trashes_copper_for_three_coins():
    g = make_game()
    set_zones(g, hand=["Moneylender", "Copper", "Copper"])
    play(g, "Moneylender")
    g.apply(0, Choose(("Copper",)))
    assert g.state.coins == 3 and g.state.trash == ["Copper"]
    assert g.state.players[0].hand == ["Copper"]


def test_moneylender_may_decline_and_needs_a_copper():
    g = make_game()
    set_zones(g, hand=["Moneylender", "Copper"])
    play(g, "Moneylender")
    g.apply(0, Choose(()))
    assert g.state.coins == 0 and g.state.trash == []

    g2 = make_game()
    set_zones(g2, hand=["Moneylender", "Estate"])
    play(g2, "Moneylender")
    assert g2.state.pending is None          # no Copper -> no question asked


# ------------------------------------------------------------------ scoring
def test_gardens_scores_per_ten_cards():
    g = make_game()
    set_zones(g, hand=[], deck=["Gardens"] + ["Copper"] * 24, discard=[])     # 25 cards
    assert score_player(g.state.players[0]) == 2
    set_zones(g, deck=["Gardens"] + ["Copper"] * 8)                           # 9 cards
    assert score_player(g.state.players[0]) == 0


def test_victory_points_and_curses():
    g = make_game()
    set_zones(g, hand=["Province", "Duchy", "Estate", "Curse", "Curse"], deck=[], discard=[])
    assert score_player(g.state.players[0]) == 6 + 3 + 1 - 2
