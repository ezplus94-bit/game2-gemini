"""Rising Sun (2024): 25 Kingdom cards, 10 Events, 15 Prophecies; Shadows, Omens and Sun tokens, Debt."""

import json
import random

import pytest

from dominion.ai import RandomBot
from dominion.cards import CardType, event_cards, get_card, kingdom_cards, prophecy_cards
from dominion.engine import (Buy, BuyEvent, Choose, EndPhase, GameConfig, GameStatus, IllegalActionError, PlayAction, PlayAllTreasures, PlayTreasure,
                             build_view, legal_actions, new_game, replay)
from helpers import make_game, set_zones, to_buy_phase, total_cards

FILLER = ["Village", "Smithy", "Militia", "Moat", "Market", "Cellar", "Chapel", "Festival", "Laboratory", "Remodel"]
RISING = kingdom_cards(["Rising Sun"])


def rg(cards, prophecy=None, extras=(), active=True, players=2, seed=1):
    """A game with these Kingdom cards (an Omen is added when a Prophecy is asked for); the Prophecy is already in force."""
    cards = list(cards)
    if prophecy and not any(get_card(c).is_type(CardType.OMEN) for c in cards):
        cards.append("Tea House")
    kingdom = [*cards, *[f for f in FILLER if f not in cards]][:10]
    g = make_game(players=players, kingdom=kingdom, seed=seed, events=[*extras, *([prophecy] if prophecy else [])], shelters=False)
    if prophecy and active:
        g.state.suns, g.state.prophecy_on = 0, True
    return g


def me(g, i=0):
    return g.state.players[i]


def pick(g, *names):
    g.apply(g.acting_player, Choose(tuple(names)))


def play(g, card, from_deck=False):
    g.apply(g.acting_player, PlayAction(card, from_deck))


def buy(g, card):
    g.apply(g.acting_player, BuyEvent(card) if CardType.EVENT in get_card(card).types else Buy(card))


def end_turn(g):
    while g.state.pending is None and g.state.status is GameStatus.ACTIVE:
        before = (g.state.current_player, g.state.turn_number)
        g.apply(g.acting_player, EndPhase())
        if (g.state.current_player, g.state.turn_number) != before:
            return


def test_the_set_has_25_kingdom_cards_10_events_15_prophecies():
    assert len(RISING) == 25 and len(event_cards(["Rising Sun"])) == 10 and len(prophecy_cards()) == 15
    assert sum(get_card(c).is_type(CardType.SHADOW) for c in RISING) == 5 and sum(get_card(c).is_type(CardType.OMEN) for c in RISING) == 6


def test_an_omen_in_the_kingdom_brings_a_prophecy_with_suns():
    g = rg(["Tea House"], prophecy="Panic", active=False)
    assert g.state.prophecy == "Panic" and g.state.suns == 5 and not g.state.prophecy_on
    assert make_game(players=2, kingdom=FILLER, seed=1, shelters=False).state.prophecy is None
    assert rg(["Tea House"], prophecy="Panic", active=False, players=4).state.suns == 10


def test_omens_remove_suns_and_the_last_one_starts_the_prophecy():
    g = rg(["Tea House"], prophecy="Panic", active=False)
    g.state.suns = 2
    set_zones(g, hand=["Tea House", "Tea House"], deck=["Copper"] * 10)
    g.state.actions = 2
    play(g, "Tea House")
    assert g.state.suns == 1 and not g.state.prophecy_on
    play(g, "Tea House")
    assert g.state.suns == 0 and g.state.prophecy_on and g.state.coins == 4


# ------------------------------------------------------------------ Shadows
def test_a_shadow_can_be_played_from_the_deck():
    g = rg(["Alley"])
    set_zones(g, hand=["Copper"], deck=["Copper", "Alley", "Copper"])
    assert PlayAction("Alley", True) in legal_actions(g.state, 0)
    play(g, "Alley", from_deck=True)
    pick(g, "Copper")
    assert "Alley" in me(g).in_play and g.state.actions == 1 and len(me(g).hand) == 1
    with pytest.raises(IllegalActionError):
        play(g, "Copper", from_deck=True)


def test_shadow_goes_to_bottom_of_a_fresh_shuffle():
    from dominion.engine import zones
    g = rg(["Alley"])
    cards = ["Copper", "Alley", "Silver", "Gold", "Alley", "Copper"]
    zones.shuffle_deck(g.state, cards)
    assert cards[:2] == ["Alley", "Alley"]


def test_ronin_draws_to_seven_and_fishmonger_gives_a_buy():
    g = rg(["Ronin", "Fishmonger"])
    set_zones(g, hand=["Ronin", "Copper"], deck=["Copper"] * 20)
    play(g, "Ronin")
    assert len(me(g).hand) == 7
    set_zones(g, hand=["Fishmonger"])
    g.state.actions = 1
    play(g, "Fishmonger")
    assert g.state.buys == 2 and g.state.coins == 1


def test_ninja_makes_others_discard_to_three():
    g = rg(["Ninja"])
    set_zones(g, 0, hand=["Ninja"], deck=["Copper"] * 5)
    set_zones(g, 1, hand=["Copper"] * 5)
    play(g, "Ninja")
    pick(g, "Copper", "Copper")
    assert len(me(g, 1).hand) == 3


def test_tanuki_can_gain_a_debt_card_for_a_debt_card():
    g = rg(["Tanuki", "Artist", "Daimyo"])
    set_zones(g, hand=["Tanuki", "Artist"])
    play(g, "Tanuki")
    pick(g, "Artist")
    assert "Daimyo" in g.state.supply
    pick(g, "Daimyo")
    assert "Daimyo" in me(g).discard


# ------------------------------------------------------------------ Debt cards and others
def test_root_cellar_and_litter_and_envoy_and_craftsman_take_debt():
    g = rg(["Root Cellar", "Litter", "Imperial Envoy", "Craftsman"])
    set_zones(g, hand=["Root Cellar", "Litter", "Imperial Envoy", "Craftsman"], deck=["Copper"] * 30)
    g.state.actions = 4
    play(g, "Root Cellar")
    play(g, "Litter")
    play(g, "Imperial Envoy")
    assert me(g).debt == 3 + 1 + 2 and g.state.buys == 2
    play(g, "Craftsman")
    assert me(g).debt == 8
    pick(g, "Silver")
    assert "Silver" in me(g).discard


def test_gold_mine_gains_gold_for_debt():
    g = rg(["Gold Mine"])
    set_zones(g, hand=["Gold Mine"], deck=["Copper"] * 5)
    play(g, "Gold Mine")
    pick(g, "Gain a Gold and take 4 Debt")
    assert "Gold" in me(g).discard and me(g).debt == 4 and me(g).gold_gained


def test_aristocrat_depends_on_how_many_are_in_play():
    g = rg(["Aristocrat"])
    set_zones(g, hand=["Aristocrat", "Aristocrat", "Aristocrat"], deck=["Copper"] * 10)
    g.state.actions = 3
    play(g, "Aristocrat")
    assert g.state.actions == 2 + 3
    play(g, "Aristocrat")
    assert len(me(g).hand) == 1 + 3
    play(g, "Aristocrat")
    assert g.state.coins == 3


def test_artist_counts_cards_with_a_single_copy():
    g = rg(["Artist", "Village"])
    set_zones(g, hand=["Artist", "Village", "Copper", "Copper"], deck=["Copper"] * 10)
    g.state.actions = 2
    play(g, "Village")
    play(g, "Artist")
    assert len(me(g).hand) == 2 + 1 + 2


def test_change_trashes_and_takes_debt_or_pays_out_when_in_debt():
    g = rg(["Change"])
    set_zones(g, hand=["Change", "Copper"])
    play(g, "Change")
    pick(g, "Copper")
    pick(g, "Province")
    assert me(g).debt == 8 and "Province" in me(g).discard
    g = rg(["Change"])
    set_zones(g, hand=["Change"])
    me(g).debt = 1
    play(g, "Change")
    assert g.state.coins == 3


def test_daimyo_replays_the_next_non_command_action():
    g = rg(["Daimyo"])
    set_zones(g, hand=["Daimyo", "Village"], deck=["Copper"] * 10)
    g.state.actions = 2
    play(g, "Daimyo")
    play(g, "Village")
    assert g.state.actions == 2 - 1 + 1 - 1 + 2 + 2 and len(me(g).hand) == 1 + 1 + 1


def test_rice_counts_types_and_rice_broker_trashes_for_cards():
    g = rg(["Rice", "Fishmonger", "Daimyo"])
    set_zones(g, hand=["Fishmonger", "Copper", "Rice"], deck=["Copper"] * 10)
    play(g, "Fishmonger")
    g.apply(g.acting_player, EndPhase())
    g.apply(g.acting_player, PlayAllTreasures())
    assert g.state.coins == 1 + 1 + 3 and g.state.buys == 3
    g = rg(["Rice Broker"])
    set_zones(g, hand=["Rice Broker", "Copper", "Village"], deck=["Copper"] * 10)
    play(g, "Rice Broker")
    pick(g, "Copper")
    assert len(me(g).hand) == 1 + 2


def test_snake_witch_returns_to_its_pile_for_a_curse():
    g = rg(["Snake Witch"])
    set_zones(g, hand=["Snake Witch", "Copper", "Silver"], deck=["Gold"] * 5)
    n = g.state.supply["Snake Witch"]
    play(g, "Snake Witch")
    pick(g, "Reveal and return Snake Witch")
    assert g.state.supply["Snake Witch"] == n + 1 and "Curse" in me(g, 1).discard


def test_kitsune_chooses_two_options():
    g = rg(["Kitsune"], prophecy="Panic", active=False)
    set_zones(g, hand=["Kitsune"])
    play(g, "Kitsune")
    pick(g, "+$2", "Gain a Silver")
    assert g.state.coins == 2 and "Silver" in me(g).discard and g.state.suns == 4


def test_mountain_shrine_and_poet_and_rustic_village_and_river_shrine():
    g = rg(["Mountain Shrine"], prophecy="Panic", active=False)
    g.state.trash.append("Village")
    set_zones(g, hand=["Mountain Shrine", "Copper"], deck=["Copper"] * 10)
    play(g, "Mountain Shrine")
    pick(g, "Copper")
    assert g.state.coins == 2 and len(me(g).hand) == 2
    g = rg(["Poet"], prophecy="Panic", active=False)
    set_zones(g, hand=["Poet"], deck=["Copper", "Copper", "Gold"])
    play(g, "Poet")
    assert len(me(g).hand) == 2 and g.state.suns == 4


def test_river_shrine_gains_in_cleanup_if_nothing_was_gained():
    g = rg(["River Shrine"], prophecy="Panic", active=False)
    set_zones(g, hand=["River Shrine"], deck=["Copper"] * 10)
    play(g, "River Shrine")
    g.apply(g.acting_player, EndPhase())
    g.apply(g.acting_player, EndPhase())
    assert g.state.pending is not None
    pick(g, "Silver")
    assert "Silver" in me(g).discard


def test_samurai_attacks_once_and_pays_every_turn():
    g = rg(["Samurai"])
    set_zones(g, 0, hand=["Samurai"], deck=["Copper"] * 20)
    set_zones(g, 1, hand=["Copper"] * 5)
    play(g, "Samurai")
    pick(g, "Copper", "Copper")
    end_turn(g)
    end_turn(g)
    assert g.state.current_player == 0 and g.state.coins == 1


def test_riverboat_plays_the_set_aside_card_next_turn():
    g = rg(["Riverboat"])
    card = g.state.riverboat
    assert card is not None and get_card(card).cost == 5 and not get_card(card).is_type(CardType.DURATION)
    set_zones(g, 0, hand=["Riverboat"], deck=["Copper"] * 20)
    play(g, "Riverboat")
    end_turn(g)
    end_turn(g)
    assert "Riverboat plays the set-aside " + card in " ".join(str(line) for line in g.state.log)


# ------------------------------------------------------------------ Events
def test_amass_asceticism_credit_gather_receive_tribute():
    g = rg(["Village"], extras=["Amass"], active=False)
    to_buy_phase(g)
    g.state.coins = 2
    buy(g, "Amass")
    pick(g, "Smithy")
    assert "Smithy" in me(g).discard
    g = rg(["Village"], extras=["Credit"], active=False)
    to_buy_phase(g)
    g.state.coins = 2
    buy(g, "Credit")
    pick(g, "Gold")
    assert "Gold" in me(g).discard and me(g).debt == 6 and me(g).gold_gained
    g = rg(["Village"], extras=["Gather"], active=False)
    to_buy_phase(g)
    g.state.coins = 7
    buy(g, "Gather")
    pick(g, "Silver")
    pick(g, "Smithy")
    pick(g, "Market")
    assert sorted(get_card(c).cost for c in me(g).discard) == [3, 4, 5]


def test_continue_returns_to_the_action_phase_and_plays_the_gained_card():
    g = rg(["Village"], extras=["Continue"], active=False)
    set_zones(g, hand=["Copper"] * 5, deck=["Copper"] * 10)
    to_buy_phase(g)
    buy(g, "Continue")
    assert me(g).debt == 8
    pick(g, "Village")
    assert g.state.phase.value == "action" and "Village" in me(g).in_play and g.state.actions == 1 + 1 - 1 + 2 + 1


def test_foresight_sets_aside_the_first_action_for_the_end_of_turn():
    g = rg(["Village"], extras=["Foresight"], active=False)
    set_zones(g, hand=["Copper"] * 5, deck=["Village", "Estate", "Copper"])
    to_buy_phase(g)
    g.state.coins = 2
    buy(g, "Foresight")
    assert me(g).eot_hand == ["Village"] and sorted(me(g).discard) == ["Copper", "Estate"]


def test_practice_plays_an_action_twice_and_sea_trade_draws_per_action():
    g = rg(["Village"], extras=["Practice", "Sea Trade"], active=False)
    set_zones(g, hand=["Village", "Copper"], deck=["Copper"] * 10)
    to_buy_phase(g)
    g.state.coins = 7
    g.state.buys = 2
    actions = g.state.actions
    buy(g, "Practice")
    pick(g, "Village")
    assert g.state.actions == actions + 4 and len(me(g).hand) == 1 + 2
    buy(g, "Sea Trade")
    assert len(me(g).hand) >= 3 + 1
    pick(g, "Copper")


def test_kintsugi_trashes_and_gains_up_to_two_more_after_a_gold():
    g = rg(["Village"], extras=["Kintsugi"], active=False)
    set_zones(g, hand=["Estate", "Copper"])
    me(g).gold_gained = True
    to_buy_phase(g)
    g.state.coins = 3
    buy(g, "Kintsugi")
    pick(g, "Estate")
    pick(g, "Silver")
    assert "Estate" in g.state.trash and "Silver" in me(g).discard


# ------------------------------------------------------------------ Prophecies
def test_approaching_army_adds_an_attack_pile_and_pays_for_attacks():
    g = rg(["Militia"], prophecy="Approaching Army", active=False)
    assert len(g.state.kingdom) == 11
    g.state.suns, g.state.prophecy_on = 0, True
    set_zones(g, 0, hand=["Militia"])
    set_zones(g, 1, hand=["Copper", "Copper"])
    play(g, "Militia")
    assert g.state.coins == 3


def test_bureaucracy_great_leader_and_good_harvest():
    g = rg(["Village"], prophecy="Bureaucracy")
    to_buy_phase(g)
    g.state.coins = 3
    buy(g, "Village")
    assert "Copper" in me(g).discard
    g = rg(["Village"], prophecy="Great Leader")
    set_zones(g, hand=["Smithy"], deck=["Copper"] * 10)
    play(g, "Smithy")
    assert g.state.actions == 1
    g = rg(["Village"], prophecy="Good Harvest")
    set_zones(g, hand=["Copper", "Copper", "Silver"])
    to_buy_phase(g)
    g.apply(g.acting_player, PlayAllTreasures())
    assert g.state.coins == 1 + 1 + 2 + 2 and g.state.buys == 3


def test_panic_gives_buys_and_returns_treasures_to_their_piles():
    g = rg(["Village"], prophecy="Panic")
    set_zones(g, hand=["Copper", "Silver"])
    n = g.state.supply["Silver"]
    to_buy_phase(g)
    g.apply(g.acting_player, PlayAllTreasures())
    assert g.state.buys == 5
    g.apply(g.acting_player, EndPhase())
    assert g.state.supply["Silver"] == n + 1 and "Silver" not in me(g).discard


def test_flourishing_trade_makes_cards_cheaper_and_actions_into_buys():
    g = rg(["Village"], prophecy="Flourishing Trade")
    to_buy_phase(g)
    g.state.coins = 2
    g.state.buys = 0
    g.state.actions = 2
    assert get_card("Village").cost == 3
    buy(g, "Village")
    assert "Village" in me(g).discard and g.state.actions == 1 and g.state.buys == 0


def test_growth_progress_and_kind_emperor_and_sickness():
    g = rg(["Village"], prophecy="Progress")
    to_buy_phase(g)
    g.state.coins = 3
    buy(g, "Village")
    assert me(g).deck[-1] == "Village"
    g = rg(["Village"], prophecy="Growth")
    to_buy_phase(g)
    g.state.coins = 6
    buy(g, "Gold")
    pick(g, "Silver")
    assert "Silver" in me(g).discard
    g = rg(["Village"], prophecy="Kind Emperor")
    end_turn(g)
    end_turn(g)
    assert g.state.pending is not None
    pick(g, "Village")
    assert "Village" in me(g, 1).hand
    g = rg(["Village"], prophecy="Sickness")
    end_turn(g)
    end_turn(g)
    assert g.state.pending is not None
    pick(g, "Gain a Curse onto your deck")
    assert me(g, 1).deck[-1] == "Curse"


def test_harsh_winter_puts_debt_on_a_pile_and_the_next_gain_takes_it():
    g = rg(["Village"], prophecy="Harsh Winter")
    to_buy_phase(g)
    g.state.coins = 6
    g.state.buys = 3
    buy(g, "Village")
    assert g.state.pile_debt["Village"] == 2
    buy(g, "Village")
    assert g.state.pile_debt["Village"] == 0 and me(g).debt == 2


def test_rapid_expansion_sets_a_gained_action_aside_for_next_turn():
    g = rg(["Village"], prophecy="Rapid Expansion")
    set_zones(g, hand=["Copper"] * 3, deck=["Copper"] * 20)
    to_buy_phase(g)
    g.state.coins = 3
    buy(g, "Village")
    assert me(g).plunder_aside == ["Village"]
    end_turn(g)
    end_turn(g)
    assert "Village" in me(g).in_play


def test_enlightenment_lets_a_treasure_be_played_as_an_action():
    g = rg(["Village"], prophecy="Enlightenment")
    set_zones(g, hand=["Copper", "Gold"], deck=["Copper"] * 10)
    assert PlayAction("Gold") in legal_actions(g.state, 0)
    play(g, "Gold")
    assert g.state.actions == 1 and len(me(g).hand) == 2 and g.state.coins == 0


def test_biding_time_keeps_the_hand_for_next_turn():
    g = rg(["Village"], prophecy="Biding Time")
    set_zones(g, hand=["Gold", "Gold", "Gold", "Gold", "Gold"], deck=["Copper"] * 20)
    end_turn(g)
    assert me(g).hand == ["Copper"] * 5 or len(me(g).hand) == 5
    end_turn(g)
    assert me(g).hand.count("Gold") == 5 and len(me(g).hand) == 10


def test_divine_wind_replaces_the_kingdom():
    g = rg(["Poet"], prophecy="Divine Wind", active=False)
    old = set(g.state.kingdom)
    g.state.suns = 1
    set_zones(g, hand=["Poet"], deck=["Copper"] * 10)
    play(g, "Poet")
    assert g.state.prophecy_on and len(g.state.kingdom) == 10 and not (old & set(g.state.kingdom))
    assert all(c in g.state.supply for c in g.state.kingdom) and not any(c in g.state.supply for c in old if c not in g.state.kingdom)


# ------------------------------------------------------------------ whole games
@pytest.mark.parametrize("players", [2, 3])
def test_random_games_with_every_prophecy_hold_the_invariants(players):
    for i, prophecy in enumerate(prophecy_cards()):
        rng = random.Random(i * 11 + players)
        kingdom = rng.sample(RISING, 9) + ["Tea House"] if True else []
        kingdom = list(dict.fromkeys(kingdom))
        g = new_game(GameConfig([f"P{k}" for k in range(players)], kingdom, i, events=[prophecy], shelters=False))
        for p in g.state.players:
            p.deck.extend(rng.choice(RISING) for _ in range(6))
            rng.shuffle(p.deck)
        before = total_cards(g)
        bots = [RandomBot(random.Random(rng.random())) for _ in range(players)]
        moves = 0
        while g.state.status is not GameStatus.FINISHED and moves < 1200:
            actor = g.acting_player
            g.apply(actor, bots[actor].choose(g, actor))
            moves += 1
            if g.state.prophecy == "Divine Wind" and g.state.prophecy_on:
                before = total_cards(g)
            assert total_cards(g) == before, f"{prophecy}: {list(g.state.log)[-3:]}"
            if moves % 60 == 0:
                for k in range(players):
                    json.dumps(build_view(g, k))


def test_replay_is_exact_with_rising_sun():
    rng = random.Random(9)
    kingdom = rng.sample(RISING, 9) + ["Tea House"]
    g = new_game(GameConfig(["A", "B"], list(dict.fromkeys(kingdom)), 9, events=["Credit", "Approaching Army"], shelters=False))
    bots = [RandomBot(random.Random(1)), RandomBot(random.Random(2))]
    for _ in range(600):
        if g.state.status is GameStatus.FINISHED:
            break
        a = g.acting_player
        g.apply(a, bots[a].choose(g, a))
    r = replay(g.config, g.history)
    assert [p.all_cards() for p in r.state.players] == [p.all_cards() for p in g.state.players]
    assert (r.state.prophecy, r.state.suns, r.state.kingdom) == (g.state.prophecy, g.state.suns, g.state.kingdom)


def test_foresight_with_no_action_in_the_whole_deck_stops():
    g = rg(["Village"], extras=["Foresight"], active=False)
    set_zones(g, hand=["Copper"] * 5, deck=["Copper", "Estate"], discard=["Silver", "Copper"])
    to_buy_phase(g)
    g.state.coins = 2
    before = total_cards(g)
    buy(g, "Foresight")
    assert total_cards(g) == before and not me(g).eot_hand and len(me(g).discard) == 4 and not me(g).deck
