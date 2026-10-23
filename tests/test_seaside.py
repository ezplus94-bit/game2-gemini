"""The Seaside expansion (2009): all 26 cards, Duration lifecycle, mats, tokens, and Outpost extra turns."""

from dominion.cards import CardType, get_card, kingdom_cards
from dominion.engine import (
    Buy, Choose, EndPhase, GameStatus, PlayAction, PlayAllTreasures, score_player,
)
from helpers import make_game, set_zones, to_buy_phase, total_cards

SEASIDE = kingdom_cards(["Seaside"])


def sg(players=2, cards=("Caravan",), seed=1, **kw):
    return make_game(players=players, kingdom=[*cards, "Village", "Smithy"], seed=seed, **kw)


def play(g, card, who=None):
    g.apply(g.acting_player if who is None else who, PlayAction(card))


def answer(g, *cards, who=None):
    g.apply(g.acting_player if who is None else who, Choose(tuple(cards)))


def end_turn(g):
    start = g.state.turn_number
    while g.state.status is GameStatus.ACTIVE and g.state.turn_number == start:
        if g.state.pending is not None:
            g.apply(g.acting_player, Choose(()))
        else:
            g.apply(g.acting_player, EndPhase())


def test_seaside_has_26_cards():
    assert len(SEASIDE) == 26
    assert set(SEASIDE) == {
        "Embargo", "Haven", "Lighthouse", "Native Village", "Pearl Diver",
        "Ambassador", "Fishing Village", "Lookout", "Smugglers", "Warehouse",
        "Caravan", "Cutpurse", "Island", "Navigator", "Pirate Ship", "Salvager", "Sea Hag", "Treasure Map",
        "Bazaar", "Explorer", "Ghost Ship", "Merchant Ship", "Outpost", "Tactician", "Treasury", "Wharf",
    }
    for name in ("Haven", "Lighthouse", "Fishing Village", "Caravan", "Merchant Ship", "Outpost", "Tactician", "Wharf"):
        assert get_card(name).is_type(CardType.DURATION)


def test_caravan_draws_now_and_at_start_of_next_turn():
    g = sg(cards=("Caravan",))
    set_zones(g, 0, hand=["Caravan"], deck=["Copper"] * 15)
    play(g, "Caravan")
    assert len(g.state.players[0].hand) == 1 and g.state.actions == 1
    end_turn(g)
    assert g.state.players[0].duration == ["Caravan"]
    assert "Caravan" not in g.state.players[0].discard
    end_turn(g)
    assert len(g.state.players[0].hand) == 6
    assert "Caravan" in g.state.players[0].in_play
    end_turn(g)
    assert "Caravan" in g.state.players[0].discard


def test_haven_sets_aside_card_until_next_turn():
    g = sg(cards=("Haven",))
    set_zones(g, 0, hand=["Haven", "Gold", "Copper"], deck=["Estate"] * 10)
    play(g, "Haven")
    answer(g, "Gold")
    assert "Gold" not in g.state.players[0].hand
    assert g.state.players[0].haven_aside == ["Gold"]
    end_turn(g)
    end_turn(g)
    assert "Gold" in g.state.players[0].hand and g.state.players[0].haven_aside == []


def test_lighthouse_gives_coins_and_protects_from_attacks():
    g = sg(cards=("Lighthouse", "Sea Hag"))
    set_zones(g, 0, hand=["Lighthouse"], deck=["Copper"] * 10)
    set_zones(g, 1, hand=["Sea Hag"], deck=["Copper"] * 10)
    play(g, "Lighthouse")
    assert g.state.coins == 1
    end_turn(g)
    play(g, "Sea Hag", who=1)
    assert "Curse" not in g.state.players[0].all_cards()
    end_turn(g)
    assert g.state.coins == 1


def test_embargo_trashes_self_and_curses_buyer():
    g = sg(cards=("Embargo",))
    set_zones(g, 0, hand=["Embargo", "Silver"], deck=["Copper"] * 10)
    play(g, "Embargo")
    answer(g, "Silver")
    assert "Embargo" in g.state.trash
    assert g.state.embargo_tokens["Silver"] == 1
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    g.apply(0, Buy("Silver"))
    assert "Silver" in g.state.players[0].discard and "Curse" in g.state.players[0].discard


def test_native_village_mat_push_and_take():
    g = sg(cards=("Native Village",))
    set_zones(g, 0, hand=["Native Village", "Native Village"], deck=["Gold", "Silver"])
    play(g, "Native Village")
    answer(g, "Set aside top card on mat")
    assert g.state.players[0].native_village_mat == ["Silver"]
    play(g, "Native Village")
    answer(g, "Put mat cards into hand")
    assert g.state.players[0].native_village_mat == [] and "Silver" in g.state.players[0].hand


def test_island_sets_aside_self_and_card_and_scores_2_vp():
    g = sg(cards=("Island",))
    set_zones(g, 0, hand=["Island", "Estate"], deck=[], discard=[])
    before = total_cards(g)
    play(g, "Island")
    answer(g, "Estate")
    p0 = g.state.players[0]
    assert p0.island_mat == ["Island", "Estate"]
    assert score_player(p0) == 3
    assert total_cards(g) == before


def test_pirate_ship_steals_treasure_and_accumulates_coins():
    g = sg(cards=("Pirate Ship",))
    set_zones(g, 0, hand=["Pirate Ship"], deck=["Copper"] * 10)
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Estate", "Gold"])
    play(g, "Pirate Ship")
    answer(g, "Attack for Treasures")
    assert "Gold" in g.state.trash and g.state.players[0].pirate_coins == 1


def test_treasure_map_trashes_two_and_topdecks_four_golds():
    g = sg(cards=("Treasure Map",))
    set_zones(g, 0, hand=["Treasure Map", "Treasure Map"], deck=["Copper"])
    play(g, "Treasure Map")
    assert g.state.trash.count("Treasure Map") == 2
    assert g.state.players[0].deck[-4:] == ["Gold"] * 4


def test_outpost_grants_extra_turn_with_three_card_hand():
    g = sg(cards=("Outpost",))
    set_zones(g, 0, hand=["Outpost"], deck=["Copper"] * 10)
    play(g, "Outpost")
    end_turn(g)
    assert g.state.current_player == 0 and g.state.outpost_turn is True
    assert len(g.state.players[0].hand) == 3
    end_turn(g)
    assert g.state.current_player == 1 and g.state.outpost_turn is False
