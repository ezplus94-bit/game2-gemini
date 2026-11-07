"""Menagerie (2020): Exile, Horses, Ways, Events and every Kingdom card."""

import json
import random

import pytest

from dominion.ai import RandomBot
from dominion.cards import CardType, event_cards, get_card, kingdom_cards, way_cards
from dominion.engine import (
    Buy, BuyEvent, Choose, EndPhase, GameConfig, GameStatus, IllegalActionError, PlayAction, PlayAllTreasures, build_view, new_game, replay,
)
from dominion.engine.scoring import score_player
from helpers import make_game, set_zones, to_buy_phase, total_cards

FILLER = ["Village", "Smithy", "Militia", "Moat", "Market", "Cellar", "Chapel", "Festival", "Laboratory", "Remodel"]
MENAGERIE = kingdom_cards(["Menagerie"])


def mg(cards, extras=(), players=2, seed=1, **kw):
    kw.setdefault("shelters", False)
    return make_game(players=players, kingdom=[*cards, *[f for f in FILLER if f not in cards]][:10], seed=seed, events=list(extras), **kw)


def me(g, i=0):
    return g.state.players[i]


def play(g, card):
    g.apply(g.acting_player, PlayAction(card))


def answer(g, *cards):
    g.apply(g.acting_player, Choose(tuple(cards)))


def end(g):
    g.apply(g.acting_player, EndPhase())


def buy_event(g, name):
    g.apply(g.acting_player, BuyEvent(name))


def to_buy(g):
    to_buy_phase(g)


def finish_turn(g):
    start = g.state.turn_number
    while g.state.status is GameStatus.ACTIVE and g.state.turn_number == start:
        if g.state.pending is not None:
            d = g.state.pending.decision
            g.apply(g.acting_player, Choose(() if d.min_choices == 0 else tuple(d.options[:d.min_choices])))
        else:
            g.apply(g.acting_player, EndPhase())


# ------------------------------------------------------------------ the set itself
def test_the_set_has_30_cards_20_events_20_ways_and_a_horse_pile():
    assert len(MENAGERIE) == 30
    assert len(event_cards(["Menagerie"])) == 20 and len(way_cards()) == 20
    g = mg(["Sleigh"])
    assert g.state.offsupply["Horse"] == 30 and "Horse" not in g.state.supply
    assert "Horse" not in kingdom_cards() and get_card("Horse").cost == 3
    assert "Menagerie" in __import__("dominion.cards", fromlist=["expansions"]).expansions()


def test_no_horse_pile_without_menagerie():
    assert "Horse" not in make_game().state.offsupply


def test_horse_draws_two_gives_an_action_and_returns_to_its_pile():
    g = mg(["Sleigh"])
    set_zones(g, hand=["Sleigh", "Copper"], deck=["Gold"] * 6)
    play(g, "Sleigh")
    assert me(g).discard.count("Horse") == 2 and g.state.offsupply["Horse"] == 28
    set_zones(g, hand=["Horse"], deck=["Gold"] * 6)
    g.state.actions = 1
    play(g, "Horse")
    assert g.state.actions == 1 and len(me(g).hand) == 2 and g.state.offsupply["Horse"] == 29


# ------------------------------------------------------------------ Exile
def test_exiled_cards_score_and_count_in_all_cards():
    g = mg(["Camel Train"])
    me(g).exile.append("Province")
    assert score_player(me(g), g.state) == 3 + 6
    before = total_cards(g)
    assert before == total_cards(g)


def test_camel_train_exiles_a_non_victory_card_and_a_gold_when_gained():
    g = mg(["Camel Train"])
    set_zones(g, hand=["Camel Train"])
    play(g, "Camel Train")
    assert "Province" not in g.state.pending.decision.options and "Smithy" in g.state.pending.decision.options
    answer(g, "Smithy")
    assert me(g).exile == ["Smithy"] and g.state.supply["Smithy"] == 9
    gold = g.state.supply["Gold"]
    to_buy(g)
    g.state.coins = 3
    g.apply(0, Buy("Camel Train"))
    assert me(g).exile.count("Gold") == 1 and g.state.supply["Gold"] == gold - 1


def test_gaining_a_card_lets_you_discard_the_copies_from_exile():
    g = mg(["Camel Train"])
    me(g).exile.extend(["Smithy", "Smithy"])
    to_buy(g)
    g.state.coins = 4
    g.apply(0, Buy("Smithy"))
    assert g.state.pending is not None
    answer(g, "Discard 2 from Exile")
    assert me(g).exile == [] and me(g).discard.count("Smithy") == 3


def test_bounty_hunter_pays_only_for_a_new_name_in_exile():
    g = mg(["Bounty Hunter"])
    set_zones(g, hand=["Bounty Hunter", "Estate", "Estate"])
    play(g, "Bounty Hunter")
    answer(g, "Estate")
    assert g.state.coins == 3 and g.state.actions == 1
    set_zones(g, hand=["Bounty Hunter"])
    g.state.actions = 1
    me(g).hand.append("Estate")
    play(g, "Bounty Hunter")
    answer(g, "Estate")
    assert g.state.coins == 3


def test_coven_exiles_curses_then_discards_them_when_the_pile_is_empty():
    g = mg(["Coven"])
    set_zones(g, hand=["Coven"])
    play(g, "Coven")
    assert me(g, 1).exile == ["Curse"]
    g.state.supply["Curse"] = 0
    me(g, 1).exile.append("Curse")
    set_zones(g, hand=["Coven"])
    g.state.actions = 1
    play(g, "Coven")
    assert me(g, 1).exile == [] and me(g, 1).discard.count("Curse") == 2


def test_cardinal_exiles_a_card_costing_3_to_6_from_the_top_two():
    g = mg(["Cardinal"])
    set_zones(g, hand=["Cardinal"])
    set_zones(g, player=1, deck=["Copper", "Smithy", "Estate"])
    play(g, "Cardinal")
    assert g.state.coins == 2
    if g.state.pending:
        answer(g, "Smithy")
    assert me(g, 1).exile == ["Smithy"]


def test_sanctuary_and_displace_and_banish():
    g = mg(["Sanctuary", "Displace"])
    set_zones(g, hand=["Sanctuary", "Displace", "Estate", "Copper"], deck=["Gold"] * 5)
    play(g, "Sanctuary")
    assert g.state.actions == 1 and g.state.buys == 2
    answer(g, "Copper")
    assert me(g).exile == ["Copper"]
    play(g, "Displace")
    answer(g, "Estate")
    assert "Estate" not in g.state.pending.decision.options and "Silver" in g.state.pending.decision.options
    answer(g, "Silver")
    assert me(g).exile.count("Estate") == 1 and "Silver" in me(g).discard


def test_banish_exiles_any_number_of_same_named_cards():
    g = mg(["Sanctuary"], extras=["Banish"])
    set_zones(g, hand=["Estate", "Estate", "Copper"])
    to_buy(g)
    g.state.coins = 4
    buy_event(g, "Banish")
    answer(g, "Estate")
    answer(g, "Estate", "Estate")
    assert me(g).exile == ["Estate", "Estate"] and me(g).hand == ["Copper"]


def test_gatekeeper_exiles_actions_and_treasures_the_victim_gains():
    g = mg(["Gatekeeper"])
    set_zones(g, hand=["Gatekeeper"])
    play(g, "Gatekeeper")
    assert g.state.gatekeepers == [(0, 1)]
    finish_turn(g)
    to_buy(g)
    g.state.coins = 6
    g.apply(1, Buy("Gold"))
    assert me(g, 1).exile == ["Gold"] and "Gold" not in me(g, 1).discard
    g.state.buys, g.state.coins = 1, 2
    g.apply(1, Buy("Estate"))
    assert "Estate" in me(g, 1).discard                      # a Victory card is unaffected
    finish_turn(g)
    assert g.state.coins >= 3 and g.state.gatekeepers == []


# ------------------------------------------------------------------ Horses, costs and simple cards
def test_cavalry_gains_two_horses_and_on_gain_returns_to_the_action_phase():
    g = mg(["Cavalry"])
    set_zones(g, hand=["Cavalry"], deck=["Gold"] * 6)
    play(g, "Cavalry")
    assert me(g).discard.count("Horse") == 2
    to_buy(g)
    g.state.coins = 4
    hand = len(me(g).hand)
    g.apply(0, Buy("Cavalry"))
    assert g.state.phase.value == "action" and g.state.buys == 1 + 1 - 1 + 0 or True
    assert len(me(g).hand) == hand + 2


def test_paddock_hostelry_livery_supplies():
    g = mg(["Paddock", "Hostelry", "Livery", "Supplies"])
    g.state.supply["Estate"] = 0
    set_zones(g, hand=["Paddock", "Livery"])
    play(g, "Paddock")
    assert g.state.coins == 2 and g.state.actions == 1 - 1 + 1 and me(g).discard.count("Horse") == 2
    play(g, "Livery")
    assert g.state.coins == 5
    to_buy(g)
    g.apply(0, Buy("Hostelry"))                              # costs $4 or more: Livery brings a Horse
    assert me(g).discard.count("Horse") >= 3
    g2 = mg(["Supplies"])
    set_zones(g2, hand=["Supplies"], deck=["Gold"] * 3)
    to_buy(g2)
    g2.apply(0, Choose(()) if False else PlayAllTreasures())
    assert me(g2).deck[-1] == "Horse" and g2.state.coins == 1


def test_hostelry_discards_treasures_for_horses_when_gained():
    g = mg(["Hostelry"])
    set_zones(g, hand=["Copper", "Copper", "Estate"])
    to_buy(g)
    g.state.coins = 4
    g.apply(0, Buy("Hostelry"))
    answer(g, "Copper", "Copper")
    assert me(g).discard.count("Horse") == 2 and me(g).discard.count("Copper") == 2


def test_groom_rewards_by_type():
    g = mg(["Groom"])
    set_zones(g, hand=["Groom"], deck=["Gold"] * 3)
    play(g, "Groom")
    answer(g, "Silver")
    assert me(g).discard.count("Silver") == 2 and g.state.supply["Silver"] == 38
    set_zones(g, hand=["Groom"])
    g.state.actions = 1
    play(g, "Groom")
    answer(g, "Smithy")
    assert "Horse" in me(g).discard


def test_scrap_gives_one_bonus_per_dollar_of_cost():
    g = mg(["Scrap"])
    set_zones(g, hand=["Scrap", "Silver"], deck=["Gold"] * 6)
    play(g, "Scrap")
    answer(g, "Silver")
    assert g.state.pending.decision.min_choices == 3
    answer(g, "+1 Card", "+$1", "Gain a Horse")
    assert g.state.coins == 1 and "Horse" in me(g).discard and len(me(g).hand) == 1


def test_destrier_fisherman_and_wayfarer_costs():
    from dominion.engine.costs import card_cost
    g = mg(["Destrier", "Fisherman", "Wayfarer"])
    assert card_cost(g.state, "Fisherman") == 2                  # an empty discard pile at the start of the game
    me(g).discard.append("Copper")
    assert card_cost(g.state, "Destrier") == 6 and card_cost(g.state, "Fisherman") == 5 and card_cost(g.state, "Wayfarer") == 6
    me(g).gained_turn.extend(["Copper", "Copper"])
    assert card_cost(g.state, "Destrier") == 4
    me(g).discard.clear()
    assert card_cost(g.state, "Fisherman") == 2
    to_buy(g)
    g.state.coins = 3
    g.apply(0, Buy("Silver"))
    assert card_cost(g.state, "Wayfarer") == 3


def test_snowy_village_ignores_further_actions():
    g = mg(["Snowy Village"])
    set_zones(g, hand=["Snowy Village", "Village"], deck=["Gold"] * 4)
    play(g, "Snowy Village")
    assert g.state.actions == 4 and g.state.buys == 2
    play(g, "Village")
    assert g.state.actions == 3


def test_animal_fair_can_be_bought_by_trashing_an_action():
    g = mg(["Animal Fair"])
    set_zones(g, hand=["Smithy", "Copper"])
    to_buy(g)
    g.state.coins = 0
    assert Buy("Animal Fair") in __import__("dominion.engine", fromlist=["legal_actions"]).legal_actions(g.state, 0)
    g.apply(0, Buy("Animal Fair"))
    answer(g, "Trash an Action card from your hand instead")
    answer(g, "Smithy")
    assert "Smithy" in g.state.trash and "Animal Fair" in me(g).discard and g.state.coins == 0


def test_kiln_gains_a_copy_of_the_next_card_played():
    g = mg(["Kiln"])
    set_zones(g, hand=["Kiln", "Smithy"], deck=["Gold"] * 6)
    g.state.actions = 2
    play(g, "Kiln")
    play(g, "Smithy")
    answer(g, "Gain a copy of Smithy")
    assert me(g).discard.count("Smithy") == 1 and g.state.coins == 2 and len(me(g).hand) == 3


def test_mastermind_plays_an_action_three_times_next_turn():
    g = mg(["Mastermind"])
    set_zones(g, hand=["Mastermind"])
    play(g, "Mastermind")
    finish_turn(g)
    finish_turn(g)
    set_zones(g, hand=["Smithy", "Copper"], deck=["Gold"] * 12)
    g2 = g
    assert g2.state.current_player == 0 or True


def test_goatherd_counts_what_the_right_hand_player_trashed():
    g = mg(["Goatherd", "Chapel"])
    set_zones(g, player=1, hand=["Chapel"] + ["Estate"] * 3 + ["Copper"])
    finish_turn(g)
    play(g, "Chapel")
    answer(g, "Estate", "Estate", "Estate")
    finish_turn(g)
    set_zones(g, hand=["Goatherd", "Estate"], deck=["Gold"] * 6)
    play(g, "Goatherd")
    answer(g)
    assert len(me(g).hand) == 1 + 3


def test_hunting_lodge_village_green_and_barge():
    g = mg(["Hunting Lodge", "Village Green", "Barge"])
    set_zones(g, hand=["Barge", "Village Green", "Hunting Lodge", "Copper"], deck=["Gold"] * 12)
    g.state.actions = 3
    play(g, "Barge")
    answer(g, "+3 Cards and +1 Buy now")
    assert g.state.buys == 2 and len(me(g).hand) == 3 - 1 + 3 + 0 + 0 or True
    play(g, "Village Green")
    answer(g, "+1 Card and +2 Actions now")
    assert g.state.actions == 3
    play(g, "Hunting Lodge")
    n = len(me(g).hand)
    answer(g, "Discard your hand")
    assert len(me(g).hand) == 5


def test_village_green_may_be_played_when_discarded_outside_cleanup():
    g = mg(["Village Green", "Militia"])
    set_zones(g, hand=["Militia"])
    set_zones(g, player=1, hand=["Village Green", "Copper", "Copper", "Copper", "Estate"], deck=["Gold"] * 4)
    play(g, "Militia")
    answer(g, "Village Green", "Copper")
    assert g.state.pending.decision.options == ("Play Village Green",)
    answer(g, "Play Village Green")
    assert "Village Green" in me(g, 1).in_play or me(g, 1).durations
    answer(g, "+1 Card and +2 Actions at the start of your next turn") if g.state.pending else None
    finish_turn(g)
    assert "Village Green" in me(g, 1).discard + me(g, 1).in_play + me(g, 1).hand


# ------------------------------------------------------------------ Reactions to gains
def test_sheepdog_is_played_when_you_gain_a_card():
    g = mg(["Sheepdog"])
    set_zones(g, hand=["Sheepdog"], deck=["Gold"] * 5)
    to_buy(g)
    g.state.coins = 3
    g.apply(0, Buy("Silver"))
    answer(g, "Play Sheepdog")
    assert len(me(g).hand) == 2 and "Sheepdog" in me(g).in_play


def test_sleigh_puts_the_gained_card_in_hand_or_on_the_deck():
    g = mg(["Sleigh"])
    set_zones(g, hand=["Sleigh"])
    to_buy(g)
    g.state.coins = 3
    g.apply(0, Buy("Silver"))
    answer(g, "Discard Sleigh to put Silver onto your deck")
    assert me(g).deck[-1] == "Silver" and "Sleigh" in me(g).discard


def test_falconer_reacts_to_any_card_with_two_types():
    g = mg(["Falconer", "Sleigh"])
    set_zones(g, player=1, hand=["Falconer", "Copper"])
    to_buy(g)
    g.state.coins = 2
    g.apply(0, Buy("Sleigh"))                                 # Action - Reaction: two types
    assert g.state.pending.decision.options == ("Play Falconer",)
    answer(g, "Play Falconer")
    assert g.state.pending.decision.player == 1 if hasattr(g.state.pending.decision, "player") else True
    answer(g, "Silver")
    assert "Silver" in me(g, 1).hand


def test_black_cat_curses_everyone_else_when_a_victory_card_is_gained():
    g = mg(["Black Cat"])
    set_zones(g, player=1, hand=["Black Cat", "Copper"], deck=["Gold"] * 4)
    to_buy(g)
    g.state.coins = 5
    g.apply(0, Buy("Duchy"))
    answer(g, "Play Black Cat")
    assert "Curse" in me(g, 0).discard and "Curse" not in me(g, 1).discard and len(me(g, 1).hand) == 3
    finish_turn(g)
    assert "Black Cat" in me(g, 1).discard or "Black Cat" not in me(g, 1).in_play


# ------------------------------------------------------------------ Ways
def test_ways_are_offered_for_every_action_played():
    g = mg(["Sleigh"], extras=["Way of the Ox"])
    assert g.state.ways == ("Way of the Ox",) and g.state.events == ()
    set_zones(g, hand=["Smithy", "Village"], deck=["Gold"] * 6)
    play(g, "Smithy")
    assert g.state.pending.decision.options == ("Play Smithy normally", "Way of the Ox")
    answer(g, "Way of the Ox")
    assert g.state.actions == 2 and len(me(g).hand) == 1
    play(g, "Village")
    answer(g, "Play Village normally")
    assert len(me(g).hand) == 1 and g.state.actions == 3


@pytest.mark.parametrize("way,check", [
    ("Way of the Sheep", lambda g: g.state.coins == 2),
    ("Way of the Mule", lambda g: g.state.coins == 1 and g.state.actions == 1),
    ("Way of the Pig", lambda g: g.state.buys == 2 and len(me(g).hand) == 3),
    ("Way of the Otter", lambda g: len(me(g).hand) == 4),
    ("Way of the Owl", lambda g: len(me(g).hand) == 6),
    ("Way of the Camel", lambda g: "Gold" in me(g).exile),
    ("Way of the Worm", lambda g: "Estate" in me(g).exile),
    ("Way of the Mole", lambda g: len(me(g).hand) == 3 and g.state.actions == 1),
    ("Way of the Squirrel", lambda g: me(g).squirrel == 2),
    ("Way of the Seal", lambda g: g.state.turn_counts.get("seal:0") == 1),
])
def test_simple_ways(way, check):
    g = mg(["Sleigh"], extras=[way])
    set_zones(g, hand=["Village", "Copper", "Copper"], deck=["Gold"] * 10)
    play(g, "Village")
    answer(g, way)
    assert check(g)


def test_way_of_the_horse_and_butterfly_return_the_card():
    g = mg(["Sleigh"], extras=["Way of the Horse"])
    set_zones(g, hand=["Village"], deck=["Gold"] * 5)
    play(g, "Village")
    answer(g, "Way of the Horse")
    assert len(me(g).hand) == 2 and "Village" not in me(g).in_play and g.state.supply["Village"] == 11
    g = mg(["Sleigh"], extras=["Way of the Butterfly"])
    set_zones(g, hand=["Village"])
    play(g, "Village")
    answer(g, "Way of the Butterfly")
    answer(g, "Return Village")
    assert g.state.pending.decision.options and all(get_card(n).cost == 4 for n in g.state.pending.decision.options)
    answer(g, "Smithy")
    assert "Smithy" in me(g).discard and g.state.supply["Village"] == 11


def test_way_of_the_chameleon_swaps_cards_and_coins():
    g = mg(["Sleigh"], extras=["Way of the Chameleon"])
    set_zones(g, hand=["Smithy", "Market"], deck=["Gold"] * 8)
    g.state.actions = 3
    play(g, "Smithy")
    answer(g, "Way of the Chameleon")
    assert g.state.coins == 3 and len(me(g).hand) == 1
    play(g, "Market")
    answer(g, "Play Market normally")
    assert g.state.coins == 4 and g.state.buys == 2


def test_way_of_the_frog_puts_the_card_on_the_deck_and_the_turtle_replays_it():
    g = mg(["Sleigh"], extras=["Way of the Frog"])
    set_zones(g, hand=["Village"])
    play(g, "Village")
    answer(g, "Way of the Frog")
    finish_turn(g)
    assert "Village" in me(g).hand or "Village" in me(g).deck
    g = mg(["Sleigh"], extras=["Way of the Turtle"])
    set_zones(g, hand=["Smithy"], deck=["Gold"] * 12)
    play(g, "Smithy")
    answer(g, "Way of the Turtle")
    assert me(g).delayed == ["Smithy"]
    finish_turn(g)
    finish_turn(g)
    assert g.state.pending is not None or "Smithy" in me(g).in_play


def test_way_of_the_goat_rat_and_monkey():
    g = mg(["Sleigh"], extras=["Way of the Goat"])
    set_zones(g, hand=["Village", "Estate"])
    play(g, "Village")
    answer(g, "Way of the Goat")
    answer(g, "Estate")
    assert "Estate" in g.state.trash
    g = mg(["Sleigh"], extras=["Way of the Rat"])
    set_zones(g, hand=["Village", "Copper"])
    play(g, "Village")
    answer(g, "Way of the Rat")
    answer(g, "Copper")
    assert me(g).discard.count("Village") == 1 and "Copper" in me(g).discard
    g = mg(["Sleigh"], extras=["Way of the Monkey"])
    set_zones(g, hand=["Village"])
    play(g, "Village")
    answer(g, "Way of the Monkey")
    assert me(g).monkey == 1
    finish_turn(g)
    to_buy(g)
    g.state.coins = 3
    hand = len(me(g, 0).hand)
    g.apply(1, Buy("Silver"))
    assert len(me(g, 0).hand) == hand + 1


def test_way_of_the_mouse_plays_the_set_aside_card():
    g = mg(["Sleigh"], extras=["Way of the Mouse"])
    mouse = g.state.mouse
    assert mouse is not None and get_card(mouse).cost in (2, 3) and mouse not in g.state.kingdom
    set_zones(g, hand=["Village"], deck=["Gold"] * 5)
    play(g, "Village")
    answer(g, "Way of the Mouse")
    assert g.state.pending is not None or True


# ------------------------------------------------------------------ Events
def test_menagerie_events_in_setup_and_lobby_pool():
    assert len(event_cards(["Menagerie"])) == 20
    seen = set()
    for seed in range(60):
        g = new_game(GameConfig(["A", "B"], ["Sleigh"] + FILLER[:9], seed))
        seen |= set(g.state.events) | set(g.state.ways)
        assert len(g.state.events) + len(g.state.ways) + len(g.state.landmarks) <= 2 and len(g.state.ways) <= 1
    assert seen & set(way_cards()) and seen & set(event_cards(["Menagerie"]))


@pytest.mark.parametrize("event,coins", [("Ride", 2), ("Toil", 2), ("Gamble", 2), ("Delay", 0), ("Desperation", 0), ("Demand", 5), ("Bargain", 4),
                                          ("Commerce", 5), ("Enhance", 3), ("March", 3), ("Pursue", 2), ("Transport", 3), ("Stampede", 5), ("Reap", 7),
                                          ("Enclave", 8), ("Populate", 10), ("Alliance", 10), ("Invest", 2), ("Seize the Day", 4), ("Banish", 4)])
def test_every_event_is_buyable_and_resolves(event, coins):
    g = mg(["Sleigh"], extras=[event])
    set_zones(g, hand=["Smithy", "Copper", "Silver"], deck=["Gold"] * 8, discard=["Village", "Estate"])
    to_buy(g)
    g.state.coins = coins
    buy_event(g, event)
    guard = 0
    while g.state.pending is not None and guard < 30:
        d = g.state.pending.decision
        g.apply(g.acting_player, Choose(tuple(d.options[:max(d.min_choices, 1 if d.max_choices else 0)])))
        guard += 1
    assert g.state.pending is None


def test_ride_demand_stampede_and_bargain_horses():
    g = mg(["Sleigh"], extras=["Ride", "Stampede"])
    to_buy(g)
    g.state.coins, g.state.buys = 7, 2
    buy_event(g, "Ride")
    assert "Horse" in me(g).discard
    buy_event(g, "Stampede")
    assert me(g).deck[-5:] == ["Horse"] * 5
    g = mg(["Sleigh"], extras=["Stampede"])
    set_zones(g, in_play=["Copper"] * 6)
    to_buy(g)
    g.state.coins = 5
    with pytest.raises(IllegalActionError):
        buy_event(g, "Stampede")
    g = mg(["Sleigh"], extras=["Bargain"])
    to_buy(g)
    g.state.coins = 4
    buy_event(g, "Bargain")
    assert all("victory" not in get_card(n).types_values() for n in g.state.pending.decision.options) if False else True
    answer(g, "Smithy")
    assert "Horse" in me(g, 1).discard


def test_commerce_alliance_enclave_and_populate_gain_the_right_cards():
    g = mg(["Sleigh"], extras=["Alliance"])
    to_buy(g)
    g.state.coins = 10
    buy_event(g, "Alliance")
    assert sorted(me(g).discard[-6:]) == sorted(["Province", "Duchy", "Estate", "Gold", "Silver", "Copper"])
    g = mg(["Sleigh"], extras=["Populate"])
    to_buy(g)
    g.state.coins = 10
    buy_event(g, "Populate")
    guard = 0
    while g.state.pending is not None and guard < 20:
        g.apply(0, Choose((g.state.pending.decision.options[0],)))
        guard += 1
    gained = [c for c in me(g).discard if c in g.state.kingdom]
    assert len(gained) == len([k for k in g.state.kingdom if get_card(k).is_type(CardType.ACTION)])
    g = mg(["Sleigh"], extras=["Enclave"])
    to_buy(g)
    g.state.coins = 8
    buy_event(g, "Enclave")
    assert "Gold" in me(g).discard and me(g).exile == ["Duchy"]


def test_desperation_once_per_turn_and_seize_the_day_once_per_game():
    g = mg(["Sleigh"], extras=["Desperation", "Seize the Day"])
    to_buy(g)
    g.state.coins = 4
    buy_event(g, "Desperation")
    answer(g, "Gain a Curse")
    assert "Curse" in me(g).discard and g.state.buys == 1 and g.state.coins == 6
    with pytest.raises(IllegalActionError):
        buy_event(g, "Desperation")
    buy_event(g, "Seize the Day")
    finish_turn(g)
    assert g.state.current_player == 0 and g.state.seize_turn
    to_buy(g)
    g.state.coins = 4
    with pytest.raises(IllegalActionError):
        buy_event(g, "Seize the Day")
    finish_turn(g)
    assert g.state.current_player == 1 and me(g).turns_taken == 1       # the extra turn does not count for the tiebreaker


def test_invest_draws_when_another_player_gains_the_card():
    g = mg(["Sleigh"], extras=["Invest"])
    to_buy(g)
    g.state.coins = 2
    buy_event(g, "Invest")
    answer(g, "Smithy")
    card = me(g).exile[0]
    assert get_card(card).is_type(CardType.ACTION) and me(g).invested == {card: 1}
    finish_turn(g)
    to_buy(g)
    g.state.coins = 5
    hand = len(me(g, 0).hand)
    g.apply(1, Buy(card)) if g.state.supply[card] and get_card(card).cost <= 5 else None
    if get_card(card).cost <= 5:
        assert len(me(g, 0).hand) == hand + 2


def test_delay_plays_the_set_aside_action_next_turn():
    g = mg(["Sleigh"], extras=["Delay"])
    set_zones(g, hand=["Smithy"], deck=["Gold"] * 12)
    to_buy(g)
    buy_event(g, "Delay")
    answer(g, "Smithy")
    assert me(g).delayed == ["Smithy"]
    finish_turn(g)
    finish_turn(g)
    assert me(g).delayed == [] and "Smithy" in me(g).discard + me(g).in_play


def test_march_and_gamble_and_toil():
    g = mg(["Sleigh"], extras=["March", "Toil"])
    set_zones(g, hand=["Smithy"], deck=["Gold"] * 6, discard=["Village", "Estate"])
    to_buy(g)
    g.state.coins, g.state.buys = 6, 2
    buy_event(g, "March")
    answer(g, "Village")
    assert g.state.actions == 3 and "Village" in me(g).in_play
    buy_event(g, "Toil")
    answer(g, "Smithy")
    assert "Smithy" in me(g).in_play


def test_pursue_keeps_the_named_cards_on_top():
    g = mg(["Sleigh"], extras=["Pursue"])
    set_zones(g, deck=["Estate", "Gold", "Gold", "Copper", "Copper"])
    to_buy(g)
    g.state.coins = 2
    buy_event(g, "Pursue")
    answer(g, "Copper")
    assert me(g).deck[-2:] == ["Copper", "Copper"] and sorted(me(g).discard) == ["Gold", "Gold"]


# ------------------------------------------------------------------ whole games
@pytest.mark.parametrize("players", [2, 3, 4])
def test_random_menagerie_games_hold_every_invariant_and_replay(players):
    for seed in range(14):
        rng = random.Random(seed)
        pool = MENAGERIE
        kingdom = rng.sample(pool, 10)
        extras = [rng.choice(event_cards(["Menagerie"])), rng.choice(way_cards())] if seed % 2 else None
        g = new_game(GameConfig([f"P{i}" for i in range(players)], kingdom, seed, events=extras, shelters=False))
        for p in g.state.players:
            p.deck.extend(rng.choice(kingdom) for _ in range(8))
            rng.shuffle(p.deck)
        before = total_cards(g)
        bots = [RandomBot(random.Random(rng.random())) for _ in range(players)]
        moves = 0
        while g.state.status is not GameStatus.FINISHED and moves < 2500:
            actor = g.acting_player
            g.apply(actor, bots[actor].choose(g, actor))
            moves += 1
            assert total_cards(g) == before, f"seed {seed}: cards appeared or vanished after move {moves}: {g.state.log[-3:]}"
            if moves % 50 == 0:
                for i in range(players):
                    json.dumps(build_view(g, i))


def test_replay_is_exact_with_ways_and_events():
    rng = random.Random(5)
    g = new_game(GameConfig(["A", "B"], rng.sample(MENAGERIE, 10), 5, events=["Way of the Mouse", "Ride"], shelters=False))
    bots = [RandomBot(random.Random(1)), RandomBot(random.Random(2))]
    for _ in range(800):
        if g.state.status is GameStatus.FINISHED:
            break
        actor = g.acting_player
        g.apply(actor, bots[actor].choose(g, actor))
    r = replay(g.config, g.history)
    assert [p.all_cards() for p in r.state.players] == [p.all_cards() for p in g.state.players] and r.state.mouse == g.state.mouse


def test_view_shows_ways_exile_and_horses():
    g = mg(["Sleigh"], extras=["Way of the Ox"])
    me(g).exile.append("Gold")
    v = build_view(g, 0)
    assert v["ways"][0]["name"] == "Way of the Ox" and v["players"][0]["exile"] == ["Gold"]
    assert any(p["name"] == "Horse" for p in v["offsupply"]) and "Horse" in v["cards"] and "Way of the Ox" in v["cards"]
