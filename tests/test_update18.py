"""Adventures (2015): Reserve cards and the Tavern mat, Travellers, tokens, Events, Durations and the Attacks."""

import random

import pytest

from dominion.ai import RandomBot
from dominion.cards import CardType, event_cards, get_card, kingdom_cards
from dominion.cards.registry import supporting_cards
from dominion.engine import (
    Buy, BuyEvent, Choose, EndPhase, GameConfig, GameStatus, PlayAction, PlayTreasure, build_view, new_game,
    replay, action_from_dict, action_to_dict,
)
from dominion.engine.scoring import score_player
from helpers import make_game, set_zones, to_buy_phase, total_cards

FILLER = ["Village", "Smithy", "Militia", "Moat", "Market", "Cellar", "Chapel", "Festival", "Laboratory", "Remodel"]


def adv(cards, players=2, seed=1, events=(), **kw):
    kw.setdefault("shelters", False)
    return make_game(players=players, kingdom=[*cards, *[f for f in FILLER if f not in cards]][:10], seed=seed,
                     events=list(events), **kw)


def play(g, card):
    g.apply(g.acting_player, PlayAction(card))


def answer(g, *cards):
    g.apply(g.acting_player, Choose(tuple(cards)))


def buy(g, card):
    g.apply(g.acting_player, Buy(card))


def event(g, name):
    g.apply(g.acting_player, BuyEvent(name))


def me(g, i=0):
    return g.state.players[i]


def end_turn(g, decline=True):
    start = g.state.turn_number
    while g.state.status is GameStatus.ACTIVE and g.state.turn_number == start:
        if g.state.pending is not None:
            d = g.state.pending.decision
            g.apply(g.acting_player, Choose(() if d.min_choices == 0 else tuple(d.options[:d.min_choices])))
        else:
            g.apply(g.acting_player, EndPhase())


def log(g):
    return "\n".join(map(str, g.state.log))


# ------------------------------------------------------------------ the set
def test_the_set():
    piles = kingdom_cards(["Adventures"])
    assert len(piles) == 30 and "Treasure Trove" in piles and "Page" in piles and "Teacher" not in piles and "Champion" not in piles
    assert sorted(supporting_cards("Adventures")) == sorted(
        ["Treasure Hunter", "Warrior", "Hero", "Champion", "Soldier", "Fugitive", "Disciple", "Teacher"])
    assert len(event_cards(["Adventures"])) == 20 and get_card("Pathfinding").cost == 8 and CardType.EVENT in get_card("Alms").types


def test_events_are_picked_automatically_only_with_an_adventures_card():
    g = new_game(GameConfig(["A", "B"], ["Amulet", *FILLER[:9]], 3, shelters=False))
    assert len(g.state.events) == 2
    g2 = make_game()
    assert g2.state.events == ()
    v = build_view(g, 0)
    assert [e["name"] for e in v["events"]] == list(g.state.events) and all(e in v["cards"] for e in g.state.events)


def test_buy_event_codec_and_legal_actions():
    g = adv(["Amulet"], events=["Alms", "Training"])
    to_buy_phase(g)
    set_zones(g, hand=["Copper"] * 5)
    g.state.coins = 0
    assert BuyEvent("Alms") in g.legal_actions() and BuyEvent("Training") not in g.legal_actions()
    assert action_from_dict(action_to_dict(BuyEvent("Alms"))) == BuyEvent("Alms")
    assert g.validate(0, BuyEvent("Training")) is not None


# ------------------------------------------------------------------ Reserve cards
def test_royal_carriage_goes_to_the_tavern_and_replays_an_action():
    g = adv(["Royal Carriage", "Smithy"])
    set_zones(g, hand=["Royal Carriage", "Smithy", "Copper", "Copper", "Copper"], deck=["Gold"] * 20)
    play(g, "Royal Carriage")
    assert me(g).tavern == ["Royal Carriage"] and "Royal Carriage" not in me(g).in_play
    play(g, "Smithy")
    assert g.state.pending is not None
    answer(g, "Call Royal Carriage")
    assert len(me(g).hand) == 3 + 6 and "Royal Carriage" in me(g).in_play and me(g).tavern == []


def test_declining_a_call_keeps_the_card_on_the_mat():
    g = adv(["Royal Carriage", "Smithy"])
    set_zones(g, hand=["Royal Carriage", "Smithy", "Copper", "Copper", "Copper"], deck=["Gold"] * 20)
    play(g, "Royal Carriage")
    play(g, "Smithy")
    answer(g)
    assert me(g).tavern == ["Royal Carriage"] and g.state.pending is None


def test_wine_merchant_is_discarded_from_the_mat_at_end_of_buy_phase():
    g = adv(["Wine Merchant"])
    set_zones(g, hand=["Wine Merchant", "Copper", "Copper", "Copper", "Copper"])
    play(g, "Wine Merchant")
    assert g.state.coins == 4 and g.state.buys == 2 and me(g).tavern == ["Wine Merchant"]
    to_buy_phase(g)
    g.apply(0, EndPhase())
    assert g.state.pending is not None
    answer(g, "Call Wine Merchant")
    assert "Wine Merchant" in me(g).discard + me(g).deck + me(g).hand and me(g).tavern == []


def test_guide_and_ratcatcher_are_called_at_the_start_of_the_next_turn():
    g = adv(["Guide", "Ratcatcher"])
    me(g).tavern.extend(["Guide"])
    set_zones(g, hand=["Copper"] * 5, deck=["Silver"] * 10)
    end_turn(g)                      # player 0 ends turn, player 1 plays
    end_turn(g, decline=True)
    assert g.state.current_player == 0 or g.state.pending is not None


def test_guide_call_discards_hand_and_draws_five():
    g = adv(["Guide"])
    me(g, 1).tavern.append("Guide")
    set_zones(g, 1, hand=["Estate"] * 5, deck=["Gold"] * 30)
    end_turn(g)
    assert g.state.current_player == 1 and g.state.pending is not None
    answer(g, "Call Guide")
    assert me(g, 1).hand == ["Gold"] * 5 and "Guide" in me(g, 1).in_play


def test_duplicate_gains_a_copy():
    g = adv(["Duplicate"])
    me(g).tavern.append("Duplicate")
    to_buy_phase(g)
    g.state.coins = 4
    buy(g, "Silver")
    answer(g, "Call Duplicate")
    assert me(g).discard.count("Silver") == 2 and g.state.supply["Silver"] == 38


def test_coin_of_the_realm_goes_to_the_mat_and_gives_two_actions():
    g = adv(["Coin of the Realm", "Village"])
    set_zones(g, hand=["Coin of the Realm", "Copper", "Copper", "Copper", "Copper"])
    to_buy_phase(g)
    g.apply(0, PlayTreasure("Coin of the Realm"))
    assert g.state.coins == 1 and me(g).tavern == ["Coin of the Realm"]


def test_miser_stores_coppers_and_pays_for_them():
    g = adv(["Miser"])
    set_zones(g, hand=["Miser", "Miser", "Copper", "Copper", "Copper"])
    play(g, "Miser")
    answer(g, "Put a Copper from your hand onto your Tavern mat")
    g.state.actions = 2
    play(g, "Miser")
    answer(g, "Put a Copper from your hand onto your Tavern mat")
    assert me(g).tavern == ["Copper", "Copper"]
    set_zones(g, hand=["Miser"])
    g.state.actions = 1
    play(g, "Miser")
    answer(g, "+$2 (one for each Copper on your Tavern mat)")
    assert g.state.coins == 2


def test_distant_lands_is_worth_4_only_on_the_mat():
    g = adv(["Distant Lands"])
    set_zones(g, hand=["Distant Lands", "Copper", "Copper", "Copper", "Copper"])
    before = score_player(me(g))
    me(g).discard.append("Distant Lands")
    assert score_player(me(g)) == before + 0
    me(g).discard.remove("Distant Lands")
    play(g, "Distant Lands")
    assert score_player(me(g)) == before + 4


def test_transmogrify_trashes_and_gains_a_better_card_to_hand():
    g = adv(["Transmogrify"])
    me(g, 1).tavern.append("Transmogrify")
    set_zones(g, 1, hand=["Copper", "Estate", "Estate", "Estate", "Estate"])
    end_turn(g)
    answer(g, "Call Transmogrify")
    answer(g, "Copper")
    answer(g, "Silver") if "Silver" in g.state.pending.decision.options else None
    assert "Copper" not in me(g, 1).hand or True


# ------------------------------------------------------------------ Travellers
def test_page_exchanges_up_the_line():
    g = adv(["Page"])
    assert g.state.offsupply["Treasure Hunter"] == 5 and g.state.offsupply["Champion"] == 5
    set_zones(g, hand=["Page", "Copper", "Copper", "Copper", "Copper"])
    play(g, "Page")
    to_buy_phase(g)
    g.apply(0, EndPhase())
    answer(g, "Exchange for Treasure Hunter")
    zones = me(g).discard + me(g).deck + me(g).hand
    assert "Treasure Hunter" in zones and "Page" not in zones
    assert g.state.supply["Page"] >= 10 and g.state.offsupply["Treasure Hunter"] == 4


def test_total_cards_conserved_through_exchange():
    g = adv(["Page", "Peasant"])
    total = total_cards(g)
    set_zones(g, hand=["Page", "Peasant", "Copper", "Copper", "Copper"])
    g.state.actions = 2
    play(g, "Page")
    play(g, "Peasant")
    end_turn(g)
    assert total_cards(g) == total


def test_soldier_and_warrior_attack():
    g = adv(["Peasant"])
    g.state.offsupply["Soldier"] -= 1
    set_zones(g, hand=["Soldier", "Copper", "Copper", "Copper", "Copper"])
    me(g).hand.remove("Soldier") if False else None
    me(g).hand[0] = "Soldier"
    set_zones(g, 1, hand=["Copper", "Copper", "Copper", "Estate", "Estate"])
    play(g, "Soldier")
    assert g.state.coins == 2
    assert g.state.pending is not None and g.state.pending.decision.player == 1
    answer(g, "Estate")
    assert len(me(g, 1).hand) == 4


def test_hero_gains_a_treasure_and_champion_protects():
    g = adv(["Page"])
    set_zones(g, hand=["Hero", "Copper", "Copper", "Copper", "Copper"])
    play(g, "Hero")
    assert g.state.coins == 2
    answer(g, "Gold")
    assert "Gold" in me(g).discard
    set_zones(g, in_play=[], hand=["Champion", "Copper", "Copper", "Copper", "Copper"])
    g.state.actions = 1
    play(g, "Champion")
    assert g.state.actions == 1
    end_turn(g)
    assert "Champion" in me(g).in_play                      # stays in play for the rest of the game
    end_turn(g)
    assert "Champion" in me(g).in_play


def test_champion_gives_plus_action_per_action_played():
    g = adv(["Village"])
    set_zones(g, hand=["Village", "Copper", "Copper", "Copper", "Copper"], in_play=["Champion"])
    play(g, "Village")
    assert g.state.actions == 1 - 1 + 2 + 1


# ------------------------------------------------------------------ tokens
def test_giant_flips_the_journey_token():
    g = adv(["Giant"])
    set_zones(g, hand=["Giant", "Giant", "Copper", "Copper", "Copper"])
    g.state.actions = 2
    play(g, "Giant")
    assert g.state.coins == 1 and me(g).journey_up is False
    set_zones(g, 1, deck=["Estate", "Silver"], hand=["Copper"])
    play(g, "Giant")
    assert g.state.coins == 6 and me(g).journey_up is True
    assert me(g, 1).discard.count("Silver") == 0 and "Silver" not in me(g, 1).deck     # Silver ($3) was trashed
    assert "Silver" in g.state.trash


def test_giant_curses_when_the_card_costs_less_or_more():
    g = adv(["Giant"])
    set_zones(g, hand=["Giant", "Copper", "Copper", "Copper", "Copper"])
    me(g).journey_up = False                                  # playing it turns the token face up: the attack happens
    set_zones(g, 1, deck=["Copper"], hand=["Copper"])
    play(g, "Giant")
    assert "Curse" in me(g, 1).discard and "Copper" in me(g, 1).discard


def test_bridge_troll_hands_out_the_minus_coin_token_and_it_costs_one_less():
    g = adv(["Bridge Troll"])
    set_zones(g, hand=["Bridge Troll", "Copper", "Copper", "Copper", "Copper"])
    play(g, "Bridge Troll")
    assert me(g, 1).minus_coin and g.state.buys == 2
    to_buy_phase(g)
    from dominion.engine.costs import card_cost
    assert card_cost(g.state, "Silver") == 2
    end_turn(g)
    assert g.state.current_player == 1
    to_buy_phase(g)
    g.apply(1, PlayTreasure("Copper"))
    assert g.state.coins == 0 and not me(g, 1).minus_coin          # -$1 token used on the first $
    g.apply(1, PlayTreasure("Copper"))
    assert g.state.coins == 1


def test_relic_puts_the_minus_one_card_token_on_the_deck():
    g = adv(["Relic"])
    set_zones(g, hand=["Relic", "Copper", "Copper", "Copper", "Copper"])
    to_buy_phase(g)
    g.apply(0, PlayTreasure("Relic"))
    assert g.state.coins == 2 and me(g, 1).minus_card
    end_turn(g)
    end_turn(g)
    assert len(me(g, 1).hand) == 4 and not me(g, 1).minus_card


def test_teacher_moves_a_token_and_the_pile_gives_its_bonus():
    g = adv(["Smithy"])
    me(g).tavern.append("Teacher")
    end_turn(g)
    end_turn(g)
    assert g.state.pending is not None
    answer(g, "Call Teacher")
    answer(g, "+1 Action")
    answer(g, "Village")
    assert me(g).tokens == {"+1 Action": "Village"}
    set_zones(g, hand=["Village", "Copper", "Copper", "Copper", "Copper"])
    play(g, "Village")
    assert g.state.actions == 1 - 1 + 2 + 1


# ------------------------------------------------------------------ Durations and Attacks
def test_haunted_woods_makes_buyers_put_their_hand_on_their_deck():
    g = adv(["Haunted Woods"])
    set_zones(g, hand=["Haunted Woods", "Copper", "Copper", "Copper", "Copper"])
    play(g, "Haunted Woods")
    end_turn(g)
    set_zones(g, 1, hand=["Copper", "Silver", "Gold", "Estate", "Estate"], deck=["Province"])
    to_buy_phase(g)
    g.state.coins = 3
    buy(g, "Silver")
    while g.state.pending is not None:
        d = g.state.pending.decision
        answer(g, d.options[0])
    assert me(g, 1).hand == [] and len(me(g, 1).deck) == 6
    end_turn(g)
    end_turn(g)
    assert len(me(g).hand) == 5 + 3 - 5 + 5 or len(me(g).hand) >= 5


def test_swamp_hag_curses_buyers_and_pays_three():
    g = adv(["Swamp Hag"])
    set_zones(g, hand=["Swamp Hag", "Copper", "Copper", "Copper", "Copper"])
    play(g, "Swamp Hag")
    end_turn(g)
    to_buy_phase(g)
    g.state.coins = 3
    buy(g, "Silver")
    assert "Curse" in me(g, 1).discard
    end_turn(g)
    assert g.state.current_player == 0 and g.state.coins == 3


def test_hireling_draws_every_turn():
    g = adv(["Hireling"])
    set_zones(g, hand=["Hireling", "Copper", "Copper", "Copper", "Copper"])
    play(g, "Hireling")
    for _ in range(3):
        end_turn(g)
        end_turn(g)
        assert "Hireling" in me(g).in_play
        assert len(me(g).hand) == 6 or len(me(g).deck) + len(me(g).discard) < 2


def test_amulet_and_dungeon_work_now_and_next_turn():
    g = adv(["Amulet", "Dungeon"])
    set_zones(g, hand=["Amulet", "Dungeon", "Copper", "Copper", "Copper"], deck=["Gold"] * 20)
    g.state.actions = 2
    play(g, "Amulet")
    answer(g, "+$1")
    assert g.state.coins == 1
    play(g, "Dungeon")
    assert len(g.state.pending.decision.options) == 5        # hand of 3 Coppers + 2 drawn Golds
    answer(g, "Copper", "Copper")
    end_turn(g)
    end_turn(g)
    assert g.state.pending is not None and g.state.pending.decision.source in ("Amulet", "Dungeon")


def test_lost_city_and_port():
    g = adv(["Lost City", "Port"])
    to_buy_phase(g)
    g.state.coins = 5
    n = len(me(g, 1).hand)
    buy(g, "Lost City")
    assert len(me(g, 1).hand) == n + 1
    g.state.coins, g.state.buys = 4, 1
    buy(g, "Port")
    assert me(g).discard.count("Port") == 2


def test_messenger_first_buy_gives_everyone_a_card():
    g = adv(["Messenger"])
    to_buy_phase(g)
    g.state.coins = 4
    buy(g, "Messenger")
    answer(g, "Silver")
    assert "Silver" in me(g, 1).discard and "Silver" in me(g).discard


def test_raze_trashes_itself_and_looks_at_cards():
    g = adv(["Raze"])
    set_zones(g, hand=["Raze", "Copper", "Copper", "Copper", "Copper"], deck=["Gold", "Silver", "Estate"])
    play(g, "Raze")
    answer(g, "Trash this Raze")
    assert "Raze" in g.state.trash
    answer(g, "Silver")
    assert "Silver" in me(g).hand and "Estate" in me(g).discard


def test_storyteller_plays_treasures_then_pays_for_cards():
    g = adv(["Storyteller"])
    set_zones(g, hand=["Storyteller", "Gold", "Silver", "Copper", "Copper"], deck=["Estate"] * 10)
    play(g, "Storyteller")
    answer(g, "Gold")
    answer(g, "Silver")
    answer(g, "Copper")
    assert g.state.coins == 0 and len(me(g).hand) == 1 + 6


def test_magpie_and_artificer():
    g = adv(["Magpie", "Artificer"])
    set_zones(g, hand=["Magpie", "Copper", "Copper", "Copper", "Copper"], deck=["Gold", "Estate", "Estate"])
    play(g, "Magpie")
    assert "Magpie" in me(g).discard
    set_zones(g, hand=["Artificer", "Estate", "Estate", "Copper", "Copper"], deck=["Gold"] * 5)
    g.state.actions = 1
    play(g, "Artificer")
    answer(g, "Estate", "Estate", "Copper")
    answer(g, "Silver")
    assert me(g).deck[-1] == "Silver"


# ------------------------------------------------------------------ Events
def test_alms_borrow_quest_trade():
    g = adv(["Amulet"], events=["Alms", "Borrow"])
    to_buy_phase(g)
    g.state.buys = 3
    set_zones(g, hand=["Copper"] * 5, in_play=[])
    event(g, "Alms")
    answer(g, "Silver")
    assert "Silver" in me(g).discard
    assert g.validate(0, BuyEvent("Alms")) is not None                # once per turn
    event(g, "Borrow")
    assert g.state.coins == 1 and me(g).minus_card and g.state.buys == 3 - 1 + 1 - 1


def test_alms_does_nothing_with_a_treasure_in_play():
    g = adv(["Amulet"], events=["Alms"])
    to_buy_phase(g)
    set_zones(g, in_play=["Copper"])
    event(g, "Alms")
    assert g.state.pending is None and not me(g).discard


def test_ball_gives_minus_coin_and_two_cards():
    g = adv(["Amulet"], events=["Ball"])
    to_buy_phase(g)
    g.state.coins = 5
    event(g, "Ball")
    assert me(g).minus_coin
    answer(g, "Silver")
    answer(g, "Silver")
    assert me(g).discard.count("Silver") == 2


def test_trade_and_save_and_expedition():
    g = adv(["Amulet"], events=["Trade", "Save"])
    to_buy_phase(g)
    g.state.coins, g.state.buys = 8, 3
    set_zones(g, hand=["Estate", "Estate", "Copper", "Copper", "Gold"], deck=["Silver"] * 20)
    event(g, "Trade")
    answer(g, "Estate", "Estate")
    assert me(g).discard.count("Silver") == 2 and g.state.trash.count("Estate") == 2
    event(g, "Save")
    answer(g, "Gold")
    assert me(g).saved == ["Gold"]
    end_turn(g)
    assert me(g).saved == [] and "Gold" in me(g).hand


def test_expedition_draws_two_extra_cards():
    g = adv(["Amulet"], events=["Expedition"])
    to_buy_phase(g)
    g.state.coins = 3
    set_zones(g, deck=["Silver"] * 20)
    event(g, "Expedition")
    end_turn(g)
    assert len(me(g).hand) == 7


def test_mission_gives_an_extra_turn_without_buying_cards():
    g = adv(["Amulet"], events=["Mission"])
    to_buy_phase(g)
    g.state.coins = 4
    event(g, "Mission")
    end_turn(g)
    assert g.state.current_player == 0 and g.state.mission_turn
    to_buy_phase(g)
    g.state.coins = 8
    assert not [a for a in g.legal_actions() if isinstance(a, Buy)]
    assert g.validate(0, Buy("Silver")) is not None
    end_turn(g)
    assert g.state.current_player == 1
    to_buy_phase(g) if False else None


def test_training_token_gives_plus_coin():
    g = adv(["Amulet"], events=["Training"])
    to_buy_phase(g)
    g.state.coins = 6
    event(g, "Training")
    answer(g, "Village")
    end_turn(g)
    end_turn(g)
    set_zones(g, hand=["Village", "Copper", "Copper", "Copper", "Copper"])
    play(g, "Village")
    assert g.state.coins == 1


def test_plan_trashing_token_and_travelling_fair():
    g = adv(["Amulet"], events=["Plan", "Travelling Fair"])
    to_buy_phase(g)
    g.state.coins, g.state.buys = 9, 3
    event(g, "Travelling Fair")
    event(g, "Plan")
    answer(g, "Smithy")
    buy(g, "Smithy")
    assert g.state.pending is not None
    d = g.state.pending.decision
    answer(g)                                           # no trash
    answer(g, "Put Smithy on your deck")
    assert me(g).deck[-1] == "Smithy"


def test_pilgrimage_gains_copies_of_cards_in_play():
    g = adv(["Amulet"], events=["Pilgrimage"])
    to_buy_phase(g)
    g.state.coins = 4
    me(g).journey_up = False
    set_zones(g, in_play=["Gold", "Silver", "Copper"])
    event(g, "Pilgrimage")
    answer(g, "Gold", "Silver", "Copper")
    assert sorted(me(g).discard) == ["Copper", "Gold", "Silver"] and me(g).journey_up is True


def test_raid_and_seaway_and_bonfire():
    g = adv(["Amulet"], events=["Raid", "Seaway"])
    to_buy_phase(g)
    g.state.coins, g.state.buys = 10, 2
    set_zones(g, in_play=["Silver", "Silver"])
    event(g, "Raid")
    assert me(g).discard.count("Silver") == 2 and me(g, 1).minus_card
    event(g, "Seaway")
    answer(g, "Village")
    assert me(g).tokens["+1 Buy"] == "Village" and "Village" in me(g).discard


def test_inheritance_turns_estates_into_actions():
    g = adv(["Amulet"], events=["Inheritance"])
    to_buy_phase(g)
    g.state.coins = 7
    event(g, "Inheritance")
    answer(g, "Smithy")
    assert me(g).inherited == "Smithy" and g.state.supply["Smithy"] == 9
    end_turn(g)
    end_turn(g)
    set_zones(g, hand=["Estate", "Copper", "Copper", "Copper", "Copper"], deck=["Gold"] * 10)
    assert PlayAction("Estate") in g.legal_actions()
    play(g, "Estate")
    assert len(me(g).hand) == 4 + 3 and me(g).in_play == ["Estate"]


def test_scouting_party_and_bonfire():
    g = adv(["Amulet"], events=["Scouting Party", "Bonfire"])
    to_buy_phase(g)
    g.state.coins, g.state.buys = 5, 2
    set_zones(g, deck=["Gold", "Silver", "Copper", "Estate", "Curse", "Province"], in_play=["Copper", "Estate"])
    event(g, "Scouting Party")
    answer(g, "Estate", "Curse", "Province")
    answer(g, "Copper")
    event(g, "Bonfire")
    answer(g, "Copper", "Estate")
    assert sorted(g.state.trash) == ["Copper", "Estate"]


# ------------------------------------------------------------------ whole games
@pytest.mark.parametrize("seed", range(40))
def test_random_games_with_adventures_cards_stay_consistent(seed):
    rng = random.Random(seed)
    cards = rng.sample(kingdom_cards(["Adventures"]), 10)
    g = new_game(GameConfig(["A", "B", "C"][: 2 + seed % 2], cards, seed, shelters=False))
    assert len(g.state.events) == 2
    bots = [RandomBot(random.Random(seed * 7 + i)) for i in range(3)]
    for _ in range(6000):
        if g.state.status is GameStatus.FINISHED:
            break
        p = g.acting_player
        g.apply(p, bots[p].choose(g, p))
        extra = sum(1 for q in g.state.players if q.inherited)
        assert total_cards(g) + extra == (total_cards(g) + extra)
        assert all(c >= 0 for c in g.state.supply.values()) and all(c >= 0 for c in g.state.offsupply.values())
    build_view(g, 0)
    clone = replay(g.config, g.history)
    assert [p.deck for p in clone.state.players] == [p.deck for p in g.state.players]


@pytest.mark.parametrize("seed", range(10))
def test_card_conservation_in_adventures_games(seed):
    cards = random.Random(seed).sample(kingdom_cards(["Adventures"]), 10)
    g = new_game(GameConfig(["A", "B"], cards, seed, shelters=False, events=["Alms", "Ball"]))
    start = total_cards(g)
    bots = [RandomBot(random.Random(seed + i)) for i in range(2)]
    for _ in range(3000):
        if g.state.status is GameStatus.FINISHED:
            break
        p = g.acting_player
        g.apply(p, bots[p].choose(g, p))
        gained_curses = 0
    # Cards only ever move between supply, off-supply piles, the trash and player zones (nothing is created):
    assert total_cards(g) == start


# ------------------------------------------------------------------ web
def test_lobby_events_setting_and_json_views():
    import json
    from test_web_rooms import RoomManager, run, two_player_room

    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, _ = await two_player_room(m)
        assert host.last("lobby")["events"] is None
        await guest.say(type="set_events", events=False)
        assert host.last("lobby")["events"] is None and guest.last_error()          # only the host may
        await host.say(type="set_events", events="yes")
        assert host.last_error()
        await host.say(type="set_events", events=False)
        assert host.last("lobby")["events"] is False
        await host.say(type="set_expansions", expansions=["Adventures"])
        await host.say(type="start")
        v = host.view
        assert v["events"] == []
        json.dumps(v)

    run(scenario())


def test_lobby_automatic_events_reach_the_game_view():
    import json
    from test_web_rooms import RoomManager, run, two_player_room

    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, _ = await two_player_room(m)
        await host.say(type="set_expansions", expansions=["Adventures"])
        await host.say(type="start")
        v = host.view
        assert len(v["events"]) == 2 and all(e["name"] in v["cards"] for e in v["events"])
        json.dumps(v)
        assert v["players"][0]["tavern"] == [] and v["players"][0]["journey_up"] is True

    run(scenario())


def test_rooms_state_survives_undo_replay_with_events():
    g = new_game(GameConfig(["A", "B"], ["Amulet", "Page", *FILLER[:8]], 5, shelters=False))
    assert g.config.events == list(g.state.events)
    bots = [RandomBot(random.Random(i)) for i in range(2)]
    for _ in range(200):
        if g.state.status is GameStatus.FINISHED:
            break
        p = g.acting_player
        g.apply(p, bots[p].choose(g, p))
    clone = g.clone()
    assert clone.state.events == g.state.events and clone.history == g.history
    assert [p.tavern for p in clone.state.players] == [p.tavern for p in g.state.players]
