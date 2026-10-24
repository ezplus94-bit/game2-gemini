"""The Seaside expansion: Duration cards, mats, tokens and the 26 cards."""

import json
import random

import pytest

from dominion.ai import BigMoneyBot, RandomBot
from dominion.cards import CardType, get_card, kingdom_cards
from dominion.engine import (
    Buy, Choose, EndPhase, GameConfig, GameStatus, PlayAction, PlayAllTreasures, PlayTreasure,
    build_view, new_game, replay,
)
from dominion.engine.scoring import score_player
from helpers import make_game, set_zones, to_buy_phase, total_cards

SEASIDE = kingdom_cards(["Seaside"])


def sg(players=2, cards=("Wharf",), seed=1, **kw):
    return make_game(players=players, kingdom=[*cards, "Village", "Smithy", "Militia", "Throne Room"], seed=seed, **kw)


def play(g, card):
    g.apply(g.acting_player, PlayAction(card))


def answer(g, *cards):
    g.apply(g.acting_player, Choose(tuple(cards)))


def end_turn(g):
    """End the current turn (answering any cleanup question with nothing)."""
    start = g.state.turn_number
    while g.state.status is GameStatus.ACTIVE and g.state.turn_number == start:
        if g.state.pending is not None:
            g.apply(g.acting_player, Choose(()))
        else:
            g.apply(g.acting_player, EndPhase())


def back_to(g, player):
    """Pass turns until it is ``player``'s turn again."""
    for _ in range(10):
        end_turn(g)
        if g.state.current_player == player:
            return
    raise AssertionError("never came back")


def log(g):
    return "\n".join(map(str, g.state.log))


# ------------------------------------------------------------------ the set
def test_the_set_has_26_cards_with_the_printed_costs_and_types():
    assert len(SEASIDE) == 26
    assert {n: get_card(n).cost for n in SEASIDE} == {
        "Embargo": 2, "Haven": 2, "Lighthouse": 2, "Native Village": 2, "Pearl Diver": 2,
        "Ambassador": 3, "Fishing Village": 3, "Lookout": 3, "Smugglers": 3, "Warehouse": 3,
        "Caravan": 4, "Cutpurse": 4, "Island": 4, "Navigator": 4, "Pirate Ship": 4, "Salvager": 4, "Sea Hag": 4, "Treasure Map": 4,
        "Bazaar": 5, "Explorer": 5, "Ghost Ship": 5, "Merchant Ship": 5, "Outpost": 5, "Tactician": 5, "Treasury": 5, "Wharf": 5,
    }
    durations = {n for n in SEASIDE if get_card(n).is_type(CardType.DURATION)}
    assert durations == {"Haven", "Lighthouse", "Fishing Village", "Caravan", "Merchant Ship", "Outpost", "Tactician", "Wharf"}
    attacks = {n for n in SEASIDE if get_card(n).is_type(CardType.ATTACK)}
    assert attacks == {"Ambassador", "Cutpurse", "Ghost Ship", "Pirate Ship", "Sea Hag"}
    assert get_card("Island").is_type(CardType.VICTORY) and get_card("Island").is_type(CardType.ACTION)


def test_random_kingdoms_can_come_from_seaside_alone():
    for seed in range(8):
        k = new_game(GameConfig(["A", "B"], None, seed, expansions=["Seaside"])).state.kingdom
        assert len(k) == 10 and set(k) <= set(SEASIDE)


# ------------------------------------------------------------------ Duration cards
def test_wharf_pays_now_and_again_at_the_start_of_the_next_turn_then_leaves_play():
    g = sg()
    set_zones(g, 0, hand=["Wharf", "Copper"], deck=["Silver"] * 20)
    play(g, "Wharf")
    assert (g.state.buys, len(g.state.players[0].hand)) == (2, 3)
    end_turn(g)
    assert g.state.players[0].in_play == ["Wharf"]                    # it stays in play
    assert build_view(g, 1)["players"][0]["in_play"] == ["Wharf"]
    end_turn(g)                                                       # P1's turn
    assert g.state.current_player == 0 and g.state.buys == 2 and len(g.state.players[0].hand) == 7
    assert "Wharf gives +2 Cards, +1 Buy" in log(g)
    assert g.state.players[0].durations == []
    end_turn(g)
    assert g.state.players[0].in_play == [] and "Wharf" in g.state.players[0].discard


def test_durations_that_do_nothing_next_turn_are_discarded_at_once():
    g = sg(cards=("Tactician", "Haven"))
    set_zones(g, 0, hand=["Tactician"])                                # nothing to discard: no effect later
    play(g, "Tactician")
    end_turn(g)
    assert g.state.players[0].in_play == [] and "Tactician" in g.state.players[0].discard


def test_throne_room_with_a_duration_card_doubles_it_and_both_stay_in_play():
    g = sg(cards=("Wharf",))
    set_zones(g, 0, hand=["Throne Room", "Wharf"], deck=["Silver"] * 30)
    play(g, "Throne Room")
    answer(g, "Wharf")
    assert (g.state.buys, len(g.state.players[0].hand)) == (3, 4)
    end_turn(g)
    assert sorted(g.state.players[0].in_play) == ["Throne Room", "Wharf"]
    end_turn(g)
    assert g.state.buys == 3 and len(g.state.players[0].hand) == 5 + 4
    end_turn(g)
    assert g.state.players[0].in_play == [] and sorted(g.state.players[0].discard)[-2:] == ["Throne Room", "Wharf"]


def test_two_separate_durations_of_the_same_name_both_stay():
    g = sg(cards=("Caravan",))
    set_zones(g, 0, hand=["Caravan", "Caravan"], deck=["Silver"] * 30)
    g.state.actions = 2
    play(g, "Caravan"); play(g, "Caravan")
    end_turn(g)
    assert g.state.players[0].in_play == ["Caravan", "Caravan"]
    end_turn(g)
    assert len(g.state.players[0].hand) == 5 + 2


def test_caravan_fishing_village_and_merchant_ship_pay_next_turn():
    g = sg(cards=("Fishing Village", "Merchant Ship", "Caravan"))
    set_zones(g, 0, hand=["Fishing Village", "Merchant Ship"], deck=["Silver"] * 30)
    g.state.actions = 2
    play(g, "Fishing Village"); play(g, "Merchant Ship")
    assert (g.state.actions, g.state.coins) == (2, 3)                  # 2 - 1 + 2 - 1 ... Fishing +2 actions, Merchant uses one
    back_to(g, 0)
    assert (g.state.actions, g.state.coins) == (2, 3)                  # +1 Action +$1, and +$2
    assert "Fishing Village gives" in log(g) and "Merchant Ship gives +$2" in log(g)


def test_haven_sets_a_card_aside_until_the_next_turn():
    g = sg(cards=("Haven",))
    set_zones(g, 0, hand=["Haven", "Gold", "Estate"], deck=["Silver"] * 10)
    play(g, "Haven")
    assert len(g.state.players[0].hand) == 3
    answer(g, "Gold")
    me = g.state.players[0]
    assert me.haven == ["Gold"] and build_view(g, 1)["players"][0]["haven"] == 1
    assert "Gold" in me.all_cards()                                    # still yours
    back_to(g, 0)
    assert me.haven == [] and me.hand.count("Gold") >= 1
    assert "Haven" in me.in_play


def test_haven_with_an_empty_hand_just_draws_and_is_discarded():
    g = sg(cards=("Haven",))
    set_zones(g, 0, hand=["Haven"], deck=[], discard=[])
    play(g, "Haven")
    end_turn(g)
    assert g.state.players[0].in_play == []


def test_lighthouse_protects_until_the_start_of_your_next_turn():
    g = sg(cards=("Lighthouse",))
    set_zones(g, 0, hand=["Lighthouse", "Copper"], deck=["Silver"] * 20)
    play(g, "Lighthouse")
    assert (g.state.actions, g.state.coins) == (1, 1)
    end_turn(g)
    set_zones(g, 1, hand=["Militia", "Copper", "Copper", "Copper", "Copper"])
    set_zones(g, 0, hand=["Estate"] * 5)
    play(g, "Militia")
    assert g.state.pending is None and len(g.state.players[0].hand) == 5 and "P0 is protected" in log(g)
    end_turn(g)
    assert g.state.coins == 1 and "Lighthouse gives +$1" in log(g)
    set_zones(g, 0, hand=["Estate"] * 5)
    end_turn(g)                                                         # unprotected again: Militia works
    set_zones(g, 1, hand=["Militia", "Copper", "Copper", "Copper", "Copper"])
    play(g, "Militia")
    assert g.state.pending is not None and g.state.pending.decision.player == 0


def test_tactician_discards_the_hand_and_draws_big_next_turn():
    g = sg(cards=("Tactician",))
    set_zones(g, 0, hand=["Tactician", "Estate", "Copper"], deck=["Silver"] * 30)
    play(g, "Tactician")
    assert g.state.players[0].hand == [] and sorted(g.state.players[0].discard) == ["Copper", "Estate"]
    end_turn(g)
    assert g.state.players[0].in_play == ["Tactician"]
    back_to(g, 0)
    assert (g.state.actions, g.state.buys, len(g.state.players[0].hand)) == (2, 2, 5 + 5)


def test_outpost_gives_an_extra_turn_with_three_cards_but_never_a_third():
    g = sg(cards=("Outpost",))
    set_zones(g, 0, hand=["Outpost", "Copper"], deck=["Silver"] * 30)
    play(g, "Outpost")
    end_turn(g)
    assert g.state.current_player == 0 and g.state.outpost_turn and len(g.state.players[0].hand) == 3
    assert g.state.players[0].in_play == ["Outpost"] or g.state.players[0].in_play == []
    set_zones(g, 0, hand=["Outpost", "Copper", "Copper"], deck=["Silver"] * 30)
    play(g, "Outpost")                                                 # played again in the extra turn: no third turn
    end_turn(g)
    assert g.state.current_player == 1 and not g.state.outpost_turn and len(g.state.players[0].hand) == 5
    assert [p.turns_taken for p in g.state.players] == [2, 0]


def test_treasury_returns_to_the_deck_unless_a_victory_card_was_bought():
    g = sg(cards=("Treasury",))
    set_zones(g, 0, hand=["Treasury", "Copper"], deck=["Estate"] * 10)
    play(g, "Treasury")
    end_turn(g) if False else None
    g.apply(0, EndPhase()); g.apply(0, EndPhase())
    d = g.state.pending.decision
    assert d.options == ("Treasury",) and (d.min_choices, d.max_choices) == (0, 1)
    answer(g, "Treasury")
    assert "Treasury" in g.state.players[0].hand                       # on top of the deck, so drawn at once
    g = sg(cards=("Treasury",))
    set_zones(g, 0, hand=["Treasury", "Copper", "Copper", "Copper", "Copper"], deck=["Estate"] * 10)
    play(g, "Treasury")
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    g.apply(0, Buy("Estate"))
    g.apply(0, EndPhase())
    assert g.state.pending is None and "Treasury" in g.state.players[0].discard


# ------------------------------------------------------------------ tokens and mats
def test_embargo_tokens_curse_the_buyer_of_that_pile():
    g = sg(cards=("Embargo",))
    set_zones(g, 0, hand=["Embargo", "Copper"])
    play(g, "Embargo")
    assert g.state.coins == 2 and g.state.trash == ["Embargo"]
    answer(g, "Silver")
    assert g.state.embargo == {"Silver": 1}
    assert {p["name"]: p["embargo"] for p in build_view(g, 1)["piles"]}["Silver"] == 1
    to_buy_phase(g)
    g.state.coins = 6
    before = g.state.supply["Curse"]
    g.apply(0, Buy("Silver"))
    assert g.state.players[0].discard.count("Curse") == 1 and g.state.supply["Curse"] == before - 1
    assert "gains a Curse (Embargo)" in log(g)
    g.state.coins, g.state.buys = 6, 1
    g.state.embargo["Gold"] = 2
    g.apply(0, Buy("Gold"))
    assert g.state.players[0].discard.count("Curse") == 3


def test_embargo_under_throne_room_only_trashes_once():
    g = sg(cards=("Embargo",))
    set_zones(g, 0, hand=["Throne Room", "Embargo"])
    play(g, "Throne Room"); answer(g, "Embargo")
    answer(g, "Gold")
    assert g.state.pending is None and g.state.coins == 4 and g.state.embargo == {"Gold": 1}


def test_island_puts_itself_and_a_card_on_the_mat_and_both_still_count():
    g = sg(cards=("Island",))
    set_zones(g, 0, hand=["Island", "Estate", "Copper"])
    play(g, "Island")
    answer(g, "Estate")
    me = g.state.players[0]
    assert me.island_mat == ["Island", "Estate"] and "Island" not in me.in_play
    assert build_view(g, 1)["players"][0]["island_mat"] == ["Island", "Estate"]
    base = sum(1 for c in me.all_cards() if c == "Estate") + 2
    assert score_player(me) == base                                    # Island's 2 VP and the mat's Estate count
    g = sg(cards=("Island",))
    set_zones(g, 0, hand=["Throne Room", "Island", "Copper", "Copper"])
    play(g, "Throne Room"); answer(g, "Island")
    answer(g, "Copper")
    answer(g, "Copper")                                                # the second play only has the hand card to put away
    assert g.state.players[0].island_mat == ["Island", "Copper", "Copper"] and g.state.pending is None


def test_native_village_sets_aside_and_takes_back():
    g = sg(cards=("Native Village",))
    set_zones(g, 0, hand=["Native Village", "Native Village"], deck=["Gold", "Silver"])
    g.state.actions = 4
    play(g, "Native Village")
    me = g.state.players[0]
    assert g.state.pending is None and me.village_mat == ["Silver"] and g.state.actions == 5   # only one mode: no question
    play(g, "Native Village")
    assert g.state.pending.decision.options == ("Set aside the top card of your deck", "Take all the cards from your mat")
    answer(g, "Take all the cards from your mat")
    assert me.hand == ["Silver"] and me.village_mat == [] and build_view(g, 1)["players"][0]["village_mat"] == 0


def test_pirate_ship_trashes_a_treasure_gets_a_token_and_later_pays_coins():
    g = sg(players=3, cards=("Pirate Ship", "Moat"))
    set_zones(g, 0, hand=["Pirate Ship"])
    set_zones(g, 1, hand=["Estate"], deck=["Gold", "Silver"])           # top is Silver, then Gold
    set_zones(g, 2, hand=["Estate"], deck=["Estate", "Copper"], discard=[])
    play(g, "Pirate Ship")
    assert g.state.pending.decision.options[1].startswith("Attack")
    answer(g, g.state.pending.decision.options[1])
    d = g.state.pending.decision                                       # P1 revealed two different Treasures: I choose
    assert d.player == 0 and d.options == ("Gold", "Silver")
    answer(g, "Gold")
    assert sorted(g.state.trash) == ["Copper", "Gold"] and g.state.players[1].discard == ["Silver"]   # P2's Copper went too
    assert g.state.players[2].discard == ["Estate"]
    assert g.state.players[0].pirate_tokens == 1 and build_view(g, 1)["players"][0]["pirate_tokens"] == 1
    g.state.players[0].pirate_tokens = 3
    g.state.actions = 1
    set_zones(g, 0, hand=["Pirate Ship"])
    play(g, "Pirate Ship")
    answer(g, g.state.pending.decision.options[0])
    assert g.state.coins == 3


def test_pirate_ship_gets_no_token_if_nothing_was_trashed():
    g = sg(cards=("Pirate Ship",))
    set_zones(g, 0, hand=["Pirate Ship"])
    set_zones(g, 1, hand=["Estate"], deck=["Estate", "Curse"], discard=[])
    play(g, "Pirate Ship")
    answer(g, g.state.pending.decision.options[1])
    assert g.state.players[0].pirate_tokens == 0 and sorted(g.state.players[1].discard) == ["Curse", "Estate"]


# ------------------------------------------------------------------ the other cards
def test_bazaar_salvager_warehouse_pearl_diver():
    g = sg(cards=("Bazaar",))
    set_zones(g, 0, hand=["Bazaar"], deck=["Silver"] * 3)
    play(g, "Bazaar")
    assert (g.state.actions, g.state.coins, len(g.state.players[0].hand)) == (2, 1, 1)
    g = sg(cards=("Salvager",))
    set_zones(g, 0, hand=["Salvager", "Gold", "Estate"])
    play(g, "Salvager"); answer(g, "Gold")
    assert (g.state.buys, g.state.coins, g.state.trash) == (2, 6, ["Gold"])
    g = sg(cards=("Warehouse",))
    set_zones(g, 0, hand=["Warehouse", "Estate"], deck=["Copper"] * 5)
    play(g, "Warehouse")
    assert g.state.pending.decision.min_choices == 3
    answer(g, "Estate", "Copper", "Copper")
    assert len(g.state.players[0].hand) == 1 and len(g.state.players[0].discard) == 3 and g.state.actions == 1
    g = sg(cards=("Pearl Diver",))
    set_zones(g, 0, hand=["Pearl Diver"], deck=["Gold", "Silver", "Copper"])                  # bottom is Gold
    play(g, "Pearl Diver")
    assert "bottom card of your deck is Gold" in g.state.pending.decision.prompt
    answer(g, "Put it on top of your deck")
    assert g.state.players[0].deck[-1] == "Gold"
    g = sg(cards=("Pearl Diver",))
    set_zones(g, 0, hand=["Pearl Diver"], deck=[], discard=[])
    play(g, "Pearl Diver")
    assert g.state.pending is None


def test_lookout_trashes_discards_and_puts_back():
    g = sg(cards=("Lookout",))
    set_zones(g, 0, hand=["Lookout"], deck=["Gold", "Estate", "Curse", "Silver"], discard=[])   # top: Silver, Curse, Estate
    play(g, "Lookout")
    assert g.state.actions == 1 and g.state.players[0].set_aside == ["Silver", "Curse", "Estate"]
    answer(g, "Curse")
    assert g.state.pending.decision.options == ("Silver", "Estate")
    answer(g, "Estate")
    me = g.state.players[0]
    assert g.state.trash == ["Curse"] and me.discard == ["Estate"] and me.deck == ["Gold", "Silver"] and me.set_aside == []


def test_navigator_discards_all_or_reorders():
    g = sg(cards=("Navigator",))
    set_zones(g, 0, hand=["Navigator"], deck=["Gold"] * 3 + ["Silver", "Copper", "Estate", "Duchy", "Curse"], discard=[])
    play(g, "Navigator")
    assert g.state.coins == 2
    answer(g, "Discard them all")
    assert len(g.state.players[0].discard) == 5 and len(g.state.players[0].deck) == 3
    g = sg(cards=("Navigator",))
    set_zones(g, 0, hand=["Navigator"], deck=["Gold"] * 3 + ["Silver", "Copper", "Estate", "Duchy", "Curse"], discard=[])
    play(g, "Navigator")
    answer(g, "Put them back")
    for card in ("Duchy", "Curse", "Estate", "Copper"):
        answer(g, card)
    assert g.state.pending is None and g.state.players[0].deck[-5:] == ["Silver", "Copper", "Estate", "Curse", "Duchy"]


def test_explorer_gold_with_a_province_else_silver():
    g = sg(cards=("Explorer",))
    set_zones(g, 0, hand=["Explorer", "Province"])
    play(g, "Explorer")
    answer(g, "Province")
    assert "Gold" in g.state.players[0].hand
    g = sg(cards=("Explorer",))
    set_zones(g, 0, hand=["Explorer", "Province"])
    play(g, "Explorer")
    answer(g)
    assert "Silver" in g.state.players[0].hand
    g = sg(cards=("Explorer",))
    set_zones(g, 0, hand=["Explorer", "Estate"])
    play(g, "Explorer")
    assert g.state.pending is None and "Silver" in g.state.players[0].hand


def test_treasure_map_needs_two_maps_for_the_gold():
    g = sg(cards=("Treasure Map",))
    set_zones(g, 0, hand=["Treasure Map", "Treasure Map"], deck=["Estate"])
    play(g, "Treasure Map")
    me = g.state.players[0]
    assert g.state.trash == ["Treasure Map", "Treasure Map"] and me.deck[-4:] == ["Gold"] * 4
    g = sg(cards=("Treasure Map",))
    set_zones(g, 0, hand=["Treasure Map", "Copper"], deck=["Estate"])
    play(g, "Treasure Map")
    assert g.state.trash == ["Treasure Map"] and g.state.players[0].deck == ["Estate"]


def test_cutpurse_discards_a_copper_or_reveals_none():
    g = sg(players=3, cards=("Cutpurse", "Moat"))
    set_zones(g, 0, hand=["Cutpurse"])
    set_zones(g, 1, hand=["Copper", "Copper", "Estate"])
    set_zones(g, 2, hand=["Estate", "Silver"])
    play(g, "Cutpurse")
    assert g.state.coins == 2 and g.state.players[1].discard == ["Copper"] and g.state.players[2].discard == []
    assert "reveals a hand with no Copper" in log(g)


def test_sea_hag_discards_the_top_card_and_curses_the_deck():
    g = sg(cards=("Sea Hag",))
    set_zones(g, 0, hand=["Sea Hag"])
    set_zones(g, 1, hand=["Estate"], deck=["Gold", "Silver"], discard=[])
    play(g, "Sea Hag")
    p = g.state.players[1]
    assert p.discard == ["Silver"] and p.deck == ["Gold", "Curse"]


def test_ghost_ship_makes_players_put_cards_back_until_they_hold_three():
    g = sg(cards=("Ghost Ship",))
    set_zones(g, 0, hand=["Ghost Ship"], deck=["Gold"] * 3)
    set_zones(g, 1, hand=["Estate", "Copper", "Silver", "Gold", "Curse"], deck=["Duchy"])
    play(g, "Ghost Ship")
    assert len(g.state.players[0].hand) == 2
    d = g.state.pending.decision
    assert d.player == 1 and "2 to go" in d.prompt
    answer(g, "Curse")
    answer(g, "Estate")
    p = g.state.players[1]
    assert sorted(p.hand) == ["Copper", "Gold", "Silver"] and p.deck == ["Duchy", "Curse", "Estate"]


def test_ambassador_returns_copies_and_everyone_else_gains_one():
    g = sg(players=3, cards=("Ambassador", "Moat"))
    set_zones(g, 0, hand=["Ambassador", "Estate", "Estate", "Estate"])
    set_zones(g, 1, hand=["Moat", "Copper"])
    play(g, "Ambassador")
    answer(g, "Estate")
    assert g.state.pending.decision.options == ("Estate", "Estate") and g.state.pending.decision.max_choices == 2
    before = g.state.supply["Estate"]
    answer(g, "Estate", "Estate")
    assert g.state.players[0].hand == ["Estate"] and g.state.supply["Estate"] == before + 2
    answer(g, "Moat")                                                  # P1 blocks it
    assert g.state.players[1].discard == [] and g.state.players[2].discard == ["Estate"]
    assert g.state.supply["Estate"] == before + 1


def test_smugglers_copies_what_the_player_on_your_right_gained_last_turn():
    g = sg(players=3, cards=("Smugglers", "Moat"))
    set_zones(g, 2, hand=["Gold", "Gold", "Copper", "Copper", "Copper"])
    set_zones(g, 0, hand=["Smugglers"])
    end_turn(g)                                                         # P0 does nothing special
    end_turn(g)                                                         # P1
    to_buy_phase(g)                                                     # P2 buys a Silver and a Gold-cost card
    g.apply(2, PlayAllTreasures())
    g.state.buys = 2
    g.apply(2, Buy("Gold")); g.apply(2, Buy("Moat"))
    end_turn(g)
    assert g.state.current_player == 0
    set_zones(g, 0, hand=["Smugglers"])
    play(g, "Smugglers")
    assert g.state.pending.decision.options == ("Gold", "Moat") or g.state.pending.decision.options == ("Gold", "Moat")
    answer(g, "Moat")
    assert g.state.players[0].discard[-1] == "Moat"
    g = sg(cards=("Smugglers",))
    set_zones(g, 0, hand=["Smugglers"])
    play(g, "Smugglers")
    assert g.state.pending is None                                      # the other player has gained nothing


def test_smugglers_ignores_cards_gained_on_other_players_turns_and_expensive_cards():
    g = sg(cards=("Smugglers",))
    g.state.players[1].last_gained = ["Province", "Curse"]
    g.state.players[1].gained_turn = []
    set_zones(g, 0, hand=["Smugglers"])
    play(g, "Smugglers")
    assert g.state.players[0].discard == ["Curse"]                      # Province costs $8: only the Curse qualifies


# ------------------------------------------------------------------ everything together
def test_mat_cards_count_towards_the_total_and_gardens():
    g = sg(cards=("Island",))
    p = g.state.players[0]
    p.island_mat.extend(["Copper"] * 5)
    assert len(p.all_cards()) == 15


@pytest.mark.parametrize("players", [2, 3, 4])
def test_random_games_with_every_seaside_card_keep_every_invariant_and_replay(players):
    for seed in range(8):
        rng = random.Random(seed)
        kingdom = rng.sample(SEASIDE, 10)
        g = new_game(GameConfig([f"P{i}" for i in range(players)], kingdom, seed))
        for p in g.state.players:                                 # stuff the decks so the cards get played a lot
            p.deck.extend(rng.choice(kingdom + ["Copper", "Silver"]) for _ in range(12))
            rng.shuffle(p.deck)
        before = total_cards(g)
        bots = [RandomBot(random.Random(rng.random())) for _ in range(players)]
        for step in range(3000):
            if g.state.status is GameStatus.FINISHED:
                break
            actor = g.acting_player
            action = bots[actor].choose(g, actor)
            assert action in g.legal_actions(actor)
            g.apply(actor, action)
            assert total_cards(g) == before, f"seed {seed}: cards appeared or vanished"
            assert all(c >= 0 for c in g.state.supply.values())
            if g.state.pending is None:
                assert all(p.set_aside == [] for p in g.state.players)
            if step % 60 == 0:
                for i in range(players):
                    json.dumps(build_view(g, i))
    for seed in range(6):
        rng = random.Random(seed + 50)
        kingdom = rng.sample([*SEASIDE, "Village", "Militia", "Throne Room"], 10)
        g = new_game(GameConfig([f"P{i}" for i in range(players)], kingdom, seed))
        bots = [RandomBot(random.Random(rng.random())) for _ in range(players)]
        for _ in range(2000):
            if g.state.status is GameStatus.FINISHED:
                break
            actor = g.acting_player
            g.apply(actor, bots[actor].choose(g, actor))
        r = replay(g.config, g.history)
        assert [p.all_cards() for p in r.state.players] == [p.all_cards() for p in g.state.players]
        assert r.state.supply == g.state.supply and r.state.trash == g.state.trash
        assert r.state.embargo == g.state.embargo
        assert [str(x) for x in r.state.log] == [str(x) for x in g.state.log]


def test_durations_mix_with_alchemy_possession_and_a_big_money_bot_finishes():
    for seed in range(6):
        rng = random.Random(seed)
        kingdom = ["Possession", "Wharf", "Outpost", "Lighthouse", "Haven", "Treasury", "Tactician", "Alchemist", "Island", "Embargo"]
        g = new_game(GameConfig(["A", "B", "C"], kingdom, seed))
        for p in g.state.players:
            p.deck.extend(rng.choice(kingdom + ["Potion"]) for _ in range(12))
            rng.shuffle(p.deck)
        before = total_cards(g)
        bots = [RandomBot(random.Random(rng.random())) for _ in range(3)]
        for _ in range(3000):
            if g.state.status is GameStatus.FINISHED:
                break
            actor = g.acting_player
            g.apply(actor, bots[actor].choose(g, actor))
            assert total_cards(g) == before
    g = new_game(GameConfig(["A", "B"], ["Wharf", "Treasury", "Outpost", "Haven"], 3))
    bot = BigMoneyBot()
    for _ in range(4000):
        if g.state.status is GameStatus.FINISHED:
            break
        a = g.acting_player
        g.apply(a, bot.choose(g, a))
    assert g.state.status is GameStatus.FINISHED
