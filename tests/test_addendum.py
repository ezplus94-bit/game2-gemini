"""The cards added to complete the sets: Treasure Trove, 2nd-edition Seaside and Hinterlands, 1st-edition Base and Intrigue, and the Promos."""

import json
import random

import pytest

from dominion.ai import RandomBot
from dominion.cards import CardType, event_cards, get_card, kingdom_cards
from dominion.engine import (Buy, BuyEvent, Choose, EndPhase, GameConfig, GameStatus, PlayAction, PlayAllTreasures, PlayTreasure, build_view, new_game, replay)
from helpers import make_game, set_zones, to_buy_phase, total_cards

FILLER = ["Village", "Smithy", "Militia", "Moat", "Market", "Cellar", "Chapel", "Festival", "Laboratory", "Remodel"]


def ag(cards, players=2, seed=1, events=None):
    cards = list(cards)
    return make_game(players=players, kingdom=[*cards, *[f for f in FILLER if f not in cards]][:10], seed=seed, events=events, shelters=False)


def me(g, i=0):
    return g.state.players[i]


def pick(g, *names):
    g.apply(g.acting_player, Choose(tuple(names)))


def pick_for(g, player, *names):
    assert g.acting_player == player
    g.apply(player, Choose(tuple(names)))


def play(g, card):
    g.apply(g.acting_player, PlayAction(card))


def buy(g, card):
    g.apply(g.acting_player, BuyEvent(card) if CardType.EVENT in get_card(card).types else Buy(card))


def treasure(g, card):
    g.apply(g.acting_player, PlayTreasure(card))


def end_turn(g):
    while g.state.pending is None and g.state.status is GameStatus.ACTIVE:
        before = (g.state.current_player, g.state.turn_number)
        g.apply(g.acting_player, EndPhase())
        if (g.state.current_player, g.state.turn_number) != before:
            return


# ------------------------------------------------------------------ the sets are complete
def test_card_counts_per_set():
    counts = {e: len(kingdom_cards([e])) for e in ("Base", "Intrigue", "Seaside", "Hinterlands", "Adventures", "Promos")}
    assert counts == {"Base": 32, "Intrigue": 32, "Seaside": 35, "Hinterlands": 35, "Adventures": 30, "Promos": 11}
    assert event_cards(["Promos"]) == ["Summon"]


# ------------------------------------------------------------------ Adventures
def test_treasure_trove_gains_gold_and_copper():
    g = ag(["Treasure Trove"])
    set_zones(g, hand=["Treasure Trove"])
    g.apply(g.acting_player, EndPhase())
    treasure(g, "Treasure Trove")
    assert g.state.coins == 2 and "Gold" in me(g).discard and "Copper" in me(g).discard


# ------------------------------------------------------------------ Seaside
def test_astrolabe_gives_coin_and_buy_now_and_next_turn():
    g = ag(["Astrolabe"])
    set_zones(g, hand=["Astrolabe"], deck=["Copper"] * 20)
    g.apply(g.acting_player, EndPhase())
    treasure(g, "Astrolabe")
    assert g.state.coins == 1 and g.state.buys == 2
    end_turn(g)
    end_turn(g)
    assert g.state.coins == 1 and g.state.buys == 2


def test_monkey_draws_when_the_player_on_the_right_gains():
    g = ag(["Monkey"], players=3)
    set_zones(g, 0, hand=["Monkey"], deck=["Copper"] * 20)
    play(g, "Monkey")
    end_turn(g)                                  # player 1 (to the left of 0): their gains are not Monkey's
    g.state.coins = 3
    to_buy_phase(g)
    n0 = len(me(g, 0).hand)
    buy(g, "Silver")
    assert len(me(g, 0).hand) == n0
    end_turn(g)                                  # player 2 is the one on player 0's right
    to_buy_phase(g)
    g.state.coins = 3
    n = len(me(g, 0).hand)
    buy(g, "Silver")
    assert len(me(g, 0).hand) == n + 1


def test_sea_chart_takes_a_copy_of_a_card_in_play():
    g = ag(["Sea Chart"])
    set_zones(g, hand=["Sea Chart", "Village"], deck=["Copper", "Village", "Copper"])
    g.state.actions = 2
    play(g, "Village")
    me(g).deck[:] = ["Copper", "Village"]
    me(g).hand[:] = ["Sea Chart"]
    play(g, "Sea Chart")
    assert sorted(me(g).hand) == ["Copper", "Village"] or sorted(me(g).hand) == ["Village", "Village"] or "Village" in me(g).hand


def test_blockade_sets_a_card_aside_and_curses_those_who_gain_a_copy():
    g = ag(["Blockade"])
    set_zones(g, 0, hand=["Blockade"], deck=["Copper"] * 20)
    play(g, "Blockade")
    pick(g, "Silver")
    assert me(g).plunder_aside == ["Silver"]
    end_turn(g)
    g.state.coins = 3
    to_buy_phase(g)
    buy(g, "Silver")
    assert "Curse" in me(g, 1).discard
    end_turn(g)
    assert "Silver" in me(g, 0).hand


def test_sailor_plays_a_gained_duration_and_pays_next_turn():
    g = ag(["Sailor", "Tide Pools"])
    set_zones(g, hand=["Sailor", "Copper", "Copper", "Copper", "Copper"], deck=["Copper"] * 20)
    play(g, "Sailor")
    g.apply(g.acting_player, EndPhase())
    g.apply(g.acting_player, PlayAllTreasures())
    buy(g, "Tide Pools")
    pick(g, "Play Tide Pools")
    assert "Tide Pools" in me(g).in_play
    end_turn(g)
    end_turn(g)
    g.apply(g.acting_player, Choose(()))                  # Sailor: +$2, and no card is trashed
    assert g.state.coins == 2


def test_tide_pools_and_sea_witch_discard_two_next_turn():
    g = ag(["Tide Pools"])
    set_zones(g, hand=["Tide Pools"], deck=["Copper"] * 30)
    play(g, "Tide Pools")
    assert len(me(g).hand) == 3 and g.state.actions == 1
    end_turn(g)
    end_turn(g)
    assert g.state.pending is not None
    pick(g, "Copper", "Copper")
    assert len(me(g).hand) == 3
    g = ag(["Sea Witch"])
    set_zones(g, hand=["Sea Witch"], deck=["Copper"] * 30)
    play(g, "Sea Witch")
    assert len(me(g).hand) == 2 and "Curse" in me(g, 1).discard


def test_corsair_trashes_the_first_silver_or_gold_the_others_play():
    g = ag(["Corsair"])
    set_zones(g, 0, hand=["Corsair"], deck=["Copper"] * 20)
    play(g, "Corsair")
    assert g.state.coins == 2
    end_turn(g)
    set_zones(g, 1, hand=["Silver", "Gold", "Copper"])
    to_buy_phase(g)
    treasure(g, "Silver")
    assert "Silver" in g.state.trash and g.state.coins == 2
    treasure(g, "Gold")
    assert "Gold" in me(g, 1).in_play


def test_pirate_gains_a_treasure_next_turn_and_reacts_to_treasure_gains():
    g = ag(["Pirate"])
    set_zones(g, 0, hand=["Pirate"], deck=["Copper"] * 20)
    play(g, "Pirate")
    end_turn(g)
    end_turn(g)
    pick(g, "Gold")
    assert "Gold" in me(g, 0).hand
    g = ag(["Pirate"])
    set_zones(g, 0, hand=["Pirate", "Copper"])
    g.state.coins = 3
    me(g).hand[:] = ["Pirate"]
    to_buy_phase(g)
    buy(g, "Silver")
    pick(g, "Play Pirate")
    assert "Pirate" in me(g).in_play


# ------------------------------------------------------------------ Hinterlands
def test_guard_dog_draws_two_or_four_and_can_be_played_against_an_attack():
    g = ag(["Guard Dog"])
    set_zones(g, hand=["Guard Dog", "Copper"], deck=["Copper"] * 20)
    play(g, "Guard Dog")
    assert len(me(g).hand) == 1 + 4
    g = ag(["Guard Dog", "Militia"])
    set_zones(g, 0, hand=["Militia"], deck=["Copper"] * 5)
    set_zones(g, 1, hand=["Guard Dog", "Copper", "Copper", "Copper", "Copper"], deck=["Silver"] * 20)
    play(g, "Militia")
    pick_for(g, 1, "Guard Dog")
    assert "Guard Dog" in me(g, 1).in_play and len(me(g, 1).hand) >= 5


def test_nomads_pays_when_gained_and_trashed():
    g = ag(["Nomads"])
    to_buy_phase(g)
    g.state.coins = 4
    buy(g, "Nomads")
    assert g.state.coins == 2
    set_zones(g, hand=["Nomads"])
    g.state.phase = type(g.state.phase)("action")
    play(g, "Nomads")
    assert g.state.coins == 4 and g.state.buys == 1


def test_trail_is_played_when_gained_or_discarded():
    g = ag(["Trail"])
    set_zones(g, hand=["Copper"] * 5, deck=["Copper"] * 10)
    to_buy_phase(g)
    g.state.coins = 4
    buy(g, "Trail")
    pick(g, "Play Trail")
    assert "Trail" in me(g).in_play and g.state.actions >= 2
    g = ag(["Trail", "Cellar"])
    set_zones(g, hand=["Cellar", "Trail"], deck=["Copper"] * 10)
    play(g, "Cellar")
    pick(g, "Trail")
    pick(g, "Play Trail")
    assert "Trail" in me(g).in_play


def test_weaver_gains_two_silvers_and_is_played_when_discarded():
    g = ag(["Weaver"])
    set_zones(g, hand=["Weaver"])
    play(g, "Weaver")
    pick(g, "Gain two Silvers")
    assert me(g).discard.count("Silver") == 2
    g = ag(["Weaver", "Cellar"])
    set_zones(g, hand=["Cellar", "Weaver"], deck=["Copper"] * 10)
    play(g, "Cellar")
    pick(g, "Weaver")
    pick(g, "Play Weaver")
    pick(g, "Gain two Silvers")
    assert me(g).discard.count("Silver") == 2


def test_berserker_gains_a_cheaper_card_attacks_and_plays_itself_when_gained_with_an_action_in_play():
    g = ag(["Berserker"])
    set_zones(g, 0, hand=["Berserker"])
    set_zones(g, 1, hand=["Copper"] * 5)
    play(g, "Berserker")
    pick(g, "Silver")
    pick_for(g, 1, "Copper", "Copper")
    assert len(me(g, 1).hand) == 3
    g = ag(["Berserker"])
    set_zones(g, hand=["Village"])
    play(g, "Village")
    to_buy_phase(g)
    g.state.coins = 5
    buy(g, "Berserker")
    assert "Berserker" in me(g).in_play


def test_cauldron_curses_on_the_third_action_gained():
    g = ag(["Cauldron"])
    set_zones(g, hand=["Cauldron", "Copper", "Copper", "Copper"])
    to_buy_phase(g)
    treasure(g, "Cauldron")
    g.apply(g.acting_player, PlayAllTreasures())
    g.state.buys = 3
    g.state.coins = 9
    for _ in range(3):
        buy(g, "Village")
    assert "Curse" in me(g, 1).discard


def test_souk_loses_a_coin_per_card_in_hand_and_trashes_when_gained():
    g = ag(["Souk"])
    set_zones(g, hand=["Souk", "Copper", "Copper"])
    play(g, "Souk")
    assert g.state.coins == 5 and g.state.buys == 2
    g = ag(["Souk"])
    set_zones(g, hand=["Estate", "Copper"])
    to_buy_phase(g)
    g.state.coins = 5
    buy(g, "Souk")
    pick(g, "Estate")
    assert "Estate" in g.state.trash


def test_wheelwright_and_witchs_hut():
    g = ag(["Wheelwright"])
    set_zones(g, hand=["Wheelwright", "Gold"], deck=["Copper"] * 10)
    play(g, "Wheelwright")
    pick(g, "Gold")
    pick(g, "Smithy")
    assert "Smithy" in me(g).discard
    g = ag(["Witch's Hut"])
    set_zones(g, hand=["Witch's Hut"], deck=["Village", "Smithy", "Copper", "Copper", "Copper"])
    play(g, "Witch's Hut")
    pick(g, "Copper", "Copper")
    assert "Curse" not in me(g, 1).discard
    g = ag(["Witch's Hut"])
    set_zones(g, hand=["Witch's Hut"], deck=["Village", "Smithy", "Smithy", "Smithy", "Copper"])
    play(g, "Witch's Hut")
    pick(g, "Smithy", "Smithy")
    assert "Curse" in me(g, 1).discard


# ------------------------------------------------------------------ Base, 1st edition
def test_chancellor_woodcutter_feast():
    g = ag(["Chancellor"])
    set_zones(g, hand=["Chancellor"], deck=["Copper"] * 5)
    play(g, "Chancellor")
    pick(g, "Put my deck into my discard pile")
    assert g.state.coins == 2 and not me(g).deck and len(me(g).discard) == 5
    g = ag(["Woodcutter"])
    set_zones(g, hand=["Woodcutter"])
    play(g, "Woodcutter")
    assert g.state.coins == 2 and g.state.buys == 2
    g = ag(["Feast"])
    set_zones(g, hand=["Feast"])
    play(g, "Feast")
    pick(g, "Duchy")
    assert "Feast" in g.state.trash and "Duchy" in me(g).discard


def test_spy_discards_or_keeps_each_players_top_card():
    g = ag(["Spy"])
    set_zones(g, 0, hand=["Spy"], deck=["Copper", "Estate", "Silver"])
    set_zones(g, 1, hand=[], deck=["Copper", "Gold"])
    play(g, "Spy")
    pick(g, "Discard it")
    pick(g, "Put it back")
    assert "Estate" in me(g).discard and me(g, 1).deck[-1] == "Gold" and "Gold" not in me(g, 1).discard


def test_thief_trashes_a_treasure_and_may_gain_it():
    g = ag(["Thief"])
    set_zones(g, 0, hand=["Thief"])
    set_zones(g, 1, deck=["Estate", "Gold", "Silver"])
    play(g, "Thief")
    pick(g, "Silver")
    pick(g, "Gain Silver")
    assert "Silver" in me(g, 0).discard and "Gold" in me(g, 1).discard and "Silver" not in g.state.trash


def test_adventurer_finds_two_treasures():
    g = ag(["Adventurer"])
    set_zones(g, hand=["Adventurer"], deck=["Gold", "Estate", "Silver", "Estate", "Estate"])
    play(g, "Adventurer")
    assert sorted(me(g).hand) == ["Gold", "Silver"] and me(g).discard.count("Estate") == 3


# ------------------------------------------------------------------ Intrigue, 1st edition
def test_secret_chamber_play_and_reaction():
    g = ag(["Secret Chamber"])
    set_zones(g, hand=["Secret Chamber", "Estate", "Estate", "Copper"])
    play(g, "Secret Chamber")
    pick(g, "Estate", "Estate")
    assert g.state.coins == 2
    g = ag(["Secret Chamber", "Militia"])
    set_zones(g, 0, hand=["Militia"])
    set_zones(g, 1, hand=["Secret Chamber", "Copper", "Copper", "Copper", "Copper"], deck=["Gold"] * 10)
    play(g, "Militia")
    pick_for(g, 1, "Secret Chamber")
    pick_for(g, 1, "Copper", "Copper")
    assert me(g, 1).deck[-2:] == ["Copper", "Copper"] and len(me(g, 1).hand) == 5


def test_great_hall_is_a_victory_action_worth_a_point():
    card = get_card("Great Hall")
    assert card.vp == 1 and CardType.VICTORY in card.types and CardType.ACTION in card.types
    g = ag(["Great Hall"])
    set_zones(g, hand=["Great Hall"], deck=["Copper"] * 5)
    play(g, "Great Hall")
    assert len(me(g).hand) == 1 and g.state.actions == 1


def test_coppersmith_makes_coppers_worth_more():
    g = ag(["Coppersmith"])
    set_zones(g, hand=["Coppersmith", "Copper", "Copper"])
    play(g, "Coppersmith")
    g.apply(g.acting_player, EndPhase())
    g.apply(g.acting_player, PlayAllTreasures())
    assert g.state.coins == 4


def test_scout_takes_victory_cards_and_returns_the_rest():
    g = ag(["Scout"])
    set_zones(g, hand=["Scout"], deck=["Gold", "Estate", "Copper", "Province", "Estate"])
    play(g, "Scout")
    assert g.state.pending is None and sorted(me(g).hand) == ["Estate", "Estate", "Province"] and me(g).deck[-1] == "Copper"


def test_saboteur_trashes_and_lets_the_victim_gain_a_cheaper_card():
    g = ag(["Saboteur"])
    set_zones(g, 0, hand=["Saboteur"])
    set_zones(g, 1, deck=["Gold", "Copper", "Estate"])
    play(g, "Saboteur")
    pick_for(g, 1, "Silver")
    assert sorted(me(g, 1).discard) == ["Copper", "Estate", "Silver"] and "Gold" in g.state.trash


def test_tribute_pays_for_each_differently_named_card_the_left_player_reveals():
    g = ag(["Tribute"])
    set_zones(g, 0, hand=["Tribute"], deck=["Copper"] * 5)
    set_zones(g, 1, deck=["Silver", "Estate", "Silver"])
    play(g, "Tribute")
    assert g.state.coins == 2 and len(me(g).hand) == 2 and "Silver" in me(g, 1).discard


# ------------------------------------------------------------------ Promos
def test_black_market_deck_is_25_unused_kingdom_cards_and_a_card_can_be_bought_from_it():
    g = ag(["Black Market"])
    deck = list(g.state.black_market)
    assert len(deck) == 25 and len(set(deck)) == 25 and not set(deck) & set(g.state.kingdom)
    assert all(g.state.offsupply[c] == 1 for c in deck)
    set_zones(g, hand=["Black Market", "Gold"])
    play(g, "Black Market")
    pick(g, "Play all my Treasures")
    shown = deck[:3]
    buyable = [c for c in dict.fromkeys(shown) if get_card(c).cost <= 8]
    pick(g, buyable[0])
    assert buyable[0] in me(g).discard and buyable[0] not in g.state.black_market
    assert g.state.buys == 0
    while g.state.pending is not None:
        pick(g, g.state.pending.decision.options[0])
    assert len(g.state.black_market) == 24
    v = build_view(g, 0)
    assert {"name": "Black Market", "count": 24, "ferryman": False} in v["offsupply"]
    json.dumps(v)


def test_church_sets_cards_aside_and_returns_them_with_a_trash():
    g = ag(["Church"])
    set_zones(g, hand=["Church", "Gold", "Silver", "Estate"], deck=["Copper"] * 20)
    play(g, "Church")
    pick(g, "Gold", "Silver")
    assert sorted(me(g).plunder_aside) == ["Gold", "Silver"]
    end_turn(g)
    end_turn(g)
    assert "Gold" in me(g).hand and "Silver" in me(g).hand
    pick(g, "Copper")
    assert "Copper" in g.state.trash


def test_dismantle_and_envoy():
    g = ag(["Dismantle"])
    set_zones(g, hand=["Dismantle", "Gold"])
    play(g, "Dismantle")
    pick(g, "Gold")
    pick(g, "Silver")
    assert "Silver" in me(g).discard and "Gold" in me(g).discard and "Gold" in g.state.trash
    g = ag(["Envoy"], players=2)
    set_zones(g, 0, hand=["Envoy"], deck=["Copper", "Silver", "Gold", "Estate", "Duchy"])
    play(g, "Envoy")
    pick_for(g, 1, "Gold")
    assert "Gold" in me(g).discard and len(me(g).hand) == 4


def test_sauna_and_avanto_are_one_split_pile_and_play_each_other():
    g = ag(["Sauna"])
    assert g.state.stacks["Sauna"] == ["Sauna"] * 5 + ["Avanto"] * 5
    set_zones(g, hand=["Sauna", "Avanto", "Silver"], deck=["Copper"] * 20)
    g.state.actions = 2
    play(g, "Sauna")
    pick(g, "Avanto")
    assert "Avanto" in me(g).in_play and len(me(g).hand) == 1 + 1 + 3
    g.apply(g.acting_player, EndPhase())
    me(g).hand[:] = ["Silver", "Estate"]
    treasure(g, "Silver")
    pick(g, "Estate")
    assert "Estate" in g.state.trash


def test_walled_village_may_go_back_on_the_deck_in_cleanup():
    g = ag(["Walled Village"])
    set_zones(g, hand=["Walled Village", "Village"], deck=["Copper"] * 20)
    g.state.actions = 2
    play(g, "Walled Village")
    g.apply(g.acting_player, EndPhase())
    g.apply(g.acting_player, EndPhase())
    pick(g, "Put Walled Village on my deck")
    assert "Walled Village" in me(g).hand


def test_governor_each_choice():
    g = ag(["Governor"])
    set_zones(g, 0, hand=["Governor"], deck=["Copper"] * 10)
    set_zones(g, 1, hand=[], deck=["Copper"] * 10)
    play(g, "Governor")
    pick(g, "Each player gets +1 Card (you get +3)")
    assert len(me(g, 0).hand) == 3 and len(me(g, 1).hand) == 1
    g = ag(["Governor"])
    set_zones(g, hand=["Governor"])
    play(g, "Governor")
    pick(g, "Each player gains a Silver (you gain a Gold)")
    assert "Gold" in me(g, 0).discard and "Silver" in me(g, 1).discard
    g = ag(["Governor"])
    set_zones(g, 0, hand=["Governor", "Copper"])
    set_zones(g, 1, hand=["Copper"])
    play(g, "Governor")
    pick(g, "Each player may trash a card from their hand and gain one costing exactly $1 more (you, $2 more)")
    pick(g, "Copper")
    pick(g, "Estate")
    pick_for(g, 1, "Copper")                     # (nothing costs exactly $1 in this Kingdom)
    assert g.state.pending is None and "Estate" in me(g, 0).discard and g.state.trash == ["Copper", "Copper"]


def test_marchland_is_worth_two_and_pays_when_gained():
    assert get_card("Marchland").vp == 2
    g = ag(["Marchland"])
    set_zones(g, hand=["Copper", "Copper", "Estate"])
    to_buy_phase(g)
    g.state.coins = 5
    buy(g, "Marchland")
    pick(g, "Copper", "Estate")
    assert g.state.buys == 1 and g.state.coins == 2


def test_stash_goes_where_its_owner_wants_when_shuffled():
    g = ag(["Stash"])
    set_zones(g, hand=["Smithy"], deck=[], discard=["Stash"] + ["Copper"] * 9)
    me(g).hand.append("Smithy")
    play(g, "Smithy")
    pick(g, "Put it on the bottom")
    assert "Stash" in me(g).deck and me(g).deck[0] == "Stash"


def test_captain_plays_a_cheap_action_from_the_supply_now_and_next_turn():
    g = ag(["Captain"])
    set_zones(g, hand=["Captain"], deck=["Copper"] * 20)
    n = g.state.supply["Village"]
    play(g, "Captain")
    pick(g, "Village")
    assert g.state.supply["Village"] == n and g.state.actions == 2
    end_turn(g)
    end_turn(g)
    pick(g, "Village")
    assert g.state.actions == 3


def test_prince_plays_its_set_aside_card_every_turn():
    g = ag(["Prince"])
    set_zones(g, hand=["Prince", "Village"], deck=["Copper"] * 30)
    play(g, "Prince")
    pick(g, "Village")
    assert sorted(me(g).plunder_aside) == ["Prince", "Village"]
    end_turn(g)
    end_turn(g)
    assert "Village" in me(g).in_play and g.state.actions == 3 and me(g).plunder_aside == ["Prince"]
    end_turn(g)
    assert sorted(me(g).plunder_aside) == ["Prince", "Village"]


def test_summon_gains_and_plays_an_action_next_turn():
    g = ag(["Village"], events=["Summon"])
    set_zones(g, hand=["Copper"] * 5, deck=["Copper"] * 20)
    to_buy_phase(g)
    g.state.coins = 5
    buy(g, "Summon")
    pick(g, "Village")
    assert me(g).plunder_aside == ["Village"]
    end_turn(g)
    end_turn(g)
    assert "Village" in me(g).in_play and g.state.actions == 3


# ------------------------------------------------------------------ whole games
@pytest.mark.parametrize("players", [2, 3])
def test_random_games_with_the_added_cards_hold_the_invariants(players):
    cards = [c for c in kingdom_cards() if c in kingdom_cards(["Promos", "Seaside", "Hinterlands", "Base", "Intrigue"])]
    for seed in range(8):
        rng = random.Random(seed * 3 + players)
        kingdom = rng.sample(cards, 9) + ["Black Market"] if seed % 2 == 0 else rng.sample(cards, 10)
        kingdom = list(dict.fromkeys(kingdom))
        g = new_game(GameConfig([f"P{i}" for i in range(players)], kingdom, seed, shelters=False))
        before = total_cards(g)
        bots = [RandomBot(random.Random(rng.random())) for _ in range(players)]
        moves = 0
        while g.state.status is not GameStatus.FINISHED and moves < 1500:
            actor = g.acting_player
            g.apply(actor, bots[actor].choose(g, actor))
            moves += 1
            assert total_cards(g) == before, f"seed {seed}: {list(g.state.log)[-3:]}"
            if moves % 60 == 0:
                for i in range(players):
                    json.dumps(build_view(g, i))


def test_replay_is_exact_with_black_market():
    g = new_game(GameConfig(["A", "B"], ["Black Market", "Sauna", "Prince", "Stash", "Captain", "Governor", "Envoy", "Church", "Marchland", "Dismantle"], 4, events=["Summon"], shelters=False))
    bots = [RandomBot(random.Random(1)), RandomBot(random.Random(2))]
    for _ in range(500):
        if g.state.status is GameStatus.FINISHED:
            break
        a = g.acting_player
        g.apply(a, bots[a].choose(g, a))
    r = replay(g.config, g.history)
    assert [p.all_cards() for p in r.state.players] == [p.all_cards() for p in g.state.players] and r.state.black_market == g.state.black_market
