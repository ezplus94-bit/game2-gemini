import json

import pytest

from dominion.engine import (
    Buy, Choose, EndPhase, PlayAction, PlayAllTreasures, PlayTreasure,
    action_from_dict, action_to_dict, build_view,
)
from helpers import make_game, set_zones, to_buy_phase

ALL_ACTIONS = [
    PlayAction("Village"), PlayTreasure("Copper"), PlayAllTreasures(), Buy("Silver"),
    EndPhase(), Choose(("Estate", "Estate")), Choose(()),
]


@pytest.mark.parametrize("action", ALL_ACTIONS)
def test_action_round_trip_through_json(action):
    wire = json.loads(json.dumps(action_to_dict(action)))
    assert action_from_dict(wire) == action


@pytest.mark.parametrize("bad", [
    None, "buy", [], {}, {"type": "hack"}, {"type": "buy"}, {"type": "buy", "card": 5},
    {"type": "buy", "card": ""}, {"type": "buy", "card": "x" * 500},
    {"type": "choose"}, {"type": "choose", "selection": "Copper"},
    {"type": "choose", "selection": [1, 2]}, {"type": "choose", "selection": ["a"] * 100},
])
def test_codec_rejects_malformed_actions(bad):
    with pytest.raises(ValueError):
        action_from_dict(bad)


def test_view_is_json_serializable_and_shows_own_hand():
    g = make_game()
    view = build_view(g, 0)
    json.dumps(view)
    assert view["hand"] == sorted(g.state.players[0].hand)
    assert view["you"] == 0 and view["status"] == "active"


def test_view_hides_other_players_cards():
    g = make_game()
    set_zones(g, 1, hand=["Gold", "Gold", "Province", "Province", "Curse"],
              deck=["Festival"] * 3, discard=["Market", "Laboratory"])
    view = build_view(g, 0)
    opp = view["players"][1]
    assert opp["hand_count"] == 5 and opp["deck_count"] == 3
    assert opp["discard_top"] == "Laboratory"                                  # only the top of a discard pile is public
    assert "discard_count" not in opp                                           # the size of a discard pile is not
    assert not {"hand", "deck", "discard"} & set(opp)
    # Outside the public supply list, card catalogue and log, none of the
    # opponent's hidden cards may appear anywhere in player 0's view.
    private = {k: v for k, v in view.items() if k not in ("piles", "cards", "log")}
    text = json.dumps(private)
    for hidden in ("Gold", "Province", "Curse", "Festival", "Market"):
        assert hidden not in text, hidden


def test_legal_actions_only_for_the_acting_player():
    g = make_game()
    assert build_view(g, 0)["legal_actions"] == [{"type": "end_phase"}]
    assert build_view(g, 1)["legal_actions"] == []


def test_pending_decision_details_go_only_to_the_decider():
    g = make_game()
    set_zones(g, 0, hand=["Cellar", "Gold", "Estate"])
    g.apply(0, PlayAction("Cellar"))
    mine = build_view(g, 0)
    theirs = build_view(g, 1)
    assert sorted(mine["pending"]["options"]) == ["Estate", "Gold"]
    assert mine["pending"]["min"] == 0 and mine["pending"]["max"] == 2
    assert theirs["pending"] == {"player": 0, "source": "Cellar"}      # no options leaked
    assert mine["legal_actions"] == [] and theirs["legal_actions"] == []


def test_buy_phase_view_lists_buyable_cards():
    g = make_game()
    set_zones(g, 0, hand=["Gold", "Gold", "Estate", "Estate", "Estate"])
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    legal = build_view(g, 0)["legal_actions"]
    assert {"type": "buy", "card": "Gold"} in legal
    assert {"type": "buy", "card": "Province"} not in legal


def test_finished_view_has_scores_and_winners():
    g = make_game(supply_overrides={"Province": 0})
    g.apply(0, EndPhase())
    g.apply(0, EndPhase())
    view = build_view(g, 1)
    assert view["status"] == "finished" and view["winners"] and len(view["final_scores"]) == 2


def test_everyone_can_see_everyones_victory_points():
    g = make_game()
    set_zones(g, 1, hand=["Province", "Estate"], deck=["Curse", "Duchy"], discard=["Estate"])
    set_zones(g, 0, hand=["Copper"], deck=["Gardens"] + ["Copper"] * 9, discard=[])
    view = build_view(g, 0)
    assert view["players"][1]["vp"] == 6 + 1 - 1 + 3 + 1
    assert view["players"][0]["vp"] == 1                                 # Gardens with 11 cards
    assert build_view(g, 1)["players"][0]["vp"] == 1


def test_nobody_may_look_through_or_count_a_discard_pile_or_the_whole_deck():
    """Rulebook: you may count your draw pile but not look through it, and may not look at or count your discard pile
    (only its top card is public). Nothing in the view lets the page do either; trash is public."""
    g = make_game()
    set_zones(g, 0, hand=["Gold", "Estate"], deck=["Copper", "Silver", "Province"], discard=["Market", "Laboratory", "Curse"])
    g.state.trash.extend(["Estate", "Copper"])
    view = build_view(g, 0)
    assert "my_discard" not in view and "my_cards" not in view
    me = view["players"][0]
    assert me["deck_count"] == 3                                     # you may count your draw pile
    assert me["discard_top"] == "Curse" and "discard_count" not in me
    assert view["trash"] == ["Estate", "Copper"]                      # the trash pile is public and may be searched
    text = json.dumps({k: v for k, v in view.items() if k not in ("piles", "cards", "log")})
    for hidden in ("Market", "Laboratory", "Silver", "Province"):    # discard / draw pile contents never appear
        assert hidden not in text, hidden
    for i in range(len(g.state.players)):
        v = build_view(g, i)
        assert all("discard_count" not in p for p in v["players"])


def test_a_card_may_still_show_you_your_discard_pile():
    """Harbinger is the rule's exception: its decision lists the cards in your discard pile (and nothing else does)."""
    from dominion.engine import Choose, PlayAction
    g = make_game(kingdom=["Harbinger", "Village"])
    set_zones(g, 0, hand=["Harbinger"], deck=["Copper"], discard=["Gold", "Estate", "Estate"])
    g.apply(0, PlayAction("Harbinger"))
    view = build_view(g, 0)
    assert sorted(view["pending"]["options"]) == ["Estate", "Gold"]
    g.apply(0, Choose(("Gold",)))
    after = build_view(g, 0)
    assert after["pending"] is None and "my_discard" not in after
