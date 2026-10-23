"""The Cornucopia & Guilds expansion (2011/2013): all 26 Kingdom cards, 5 Prizes, Bane, Coffers, and Overpay."""

import json
import random

import pytest

from dominion.ai import BigMoneyBot, RandomBot
from dominion.cards import CardType, get_card, kingdom_cards
from dominion.cards.Cornucopia import PRIZES
from dominion.engine import (
    Buy, Choose, EndPhase, GameConfig, GameStatus, IllegalActionError, PlayAction, PlayAllTreasures,
    PlayTreasure, SpendCoffer, action_from_dict, action_to_dict, build_view, legal_actions, new_game,
    replay, score_player,
)
from dominion.engine.costs import card_cost
from helpers import make_game, set_zones, to_buy_phase, total_cards

CORNUCOPIA = kingdom_cards(["Cornucopia"])


def cg(players=2, cards=("Hamlet",), seed=1, **kw):
    base_fill = [c for c in ("Village", "Smithy", "Moat", "Workshop") if c not in cards]
    return make_game(players=players, kingdom=[*cards, *base_fill[:3]], seed=seed, **kw)


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


def test_cornucopia_and_guilds_has_26_kingdom_cards_and_5_prizes():
    assert len(CORNUCOPIA) == 26
    assert set(CORNUCOPIA) == {
        # Cornucopia (13)
        "Hamlet", "Fortune Teller", "Menagerie", "Farming Village", "Horse Traders",
        "Remake", "Tournament", "Young Witch", "Harvest", "Horn of Plenty",
        "Hunting Party", "Jester", "Fairgrounds",
        # Guilds (13)
        "Candlestick Maker", "Stonemason", "Doctor", "Masterpiece", "Advisor",
        "Herald", "Plaza", "Taxman", "Baker", "Butcher",
        "Journeyman", "Merchant Guild", "Soothsayer",
    }
    assert len(PRIZES) == 5
    for p in PRIZES:
        c = get_card(p)
        assert c.cost == 0 and not c.kingdom and c.expansion == "Cornucopia"


def test_hamlet_discards_for_action_and_buy():
    g = cg(cards=("Hamlet",))
    set_zones(g, 0, hand=["Hamlet", "Copper", "Estate"], deck=["Silver"])
    play(g, "Hamlet")
    answer(g, "Copper")
    answer(g, "Estate")
    assert g.state.actions == 2 and g.state.buys == 2
    assert g.state.players[0].hand == ["Silver"]


def test_fortune_teller_topdecks_victory_or_curse_and_discards_rest():
    g = cg(cards=("Fortune Teller",))
    set_zones(g, 0, hand=["Fortune Teller"])
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Gold", "Estate", "Silver", "Copper"], discard=[])
    play(g, "Fortune Teller")
    assert g.state.coins == 2
    assert g.state.players[1].deck[-1] == "Estate"
    assert sorted(g.state.players[1].discard) == ["Copper", "Silver"]


def test_menagerie_draws_three_when_hand_unique_else_one():
    g = cg(cards=("Menagerie",))
    set_zones(g, 0, hand=["Menagerie", "Copper", "Silver", "Estate"], deck=["Gold"] * 5)
    play(g, "Menagerie")
    assert len(g.state.players[0].hand) == 6 and g.state.actions == 1

    g2 = cg(cards=("Menagerie",))
    set_zones(g2, 0, hand=["Menagerie", "Copper", "Copper"], deck=["Gold"] * 5)
    play(g2, "Menagerie")
    assert len(g2.state.players[0].hand) == 3


def test_farming_village_finds_action_or_treasure():
    g = cg(cards=("Farming Village",))
    set_zones(g, 0, hand=["Farming Village"], deck=["Silver", "Estate", "Curse"], discard=[])
    play(g, "Farming Village")
    assert g.state.actions == 2
    assert g.state.players[0].hand == ["Silver"]
    assert sorted(g.state.players[0].discard) == ["Curse", "Estate"]


def test_horse_traders_play_and_reaction_returns_next_turn():
    g = cg(cards=("Horse Traders", "Fortune Teller"))
    set_zones(g, 0, hand=["Fortune Teller"], deck=["Copper"] * 5)
    set_zones(g, 1, hand=["Horse Traders", "Copper", "Estate"], deck=["Gold", "Silver", "Copper", "Copper"])
    play(g, "Fortune Teller")
    # P1 may reveal Horse Traders first
    assert g.state.pending.decision.player == 1
    answer(g, "Horse Traders", who=1)
    assert "Horse Traders" not in g.state.players[1].hand
    assert g.state.players[1].horse_traders_aside == ["Horse Traders"]
    end_turn(g)
    # Start of P1's turn: Horse Traders returns to hand + draws 1 card
    assert "Horse Traders" in g.state.players[1].hand
    assert g.state.players[1].horse_traders_aside == []
    assert len(g.state.players[1].hand) == 4  # 2 left in hand + Horse Traders + 1 drawn
    play(g, "Horse Traders", who=1)
    answer(g, "Copper", "Estate", who=1)
    assert g.state.buys == 2 and g.state.coins == 3


def test_remake_trashes_twice_for_exact_plus_one():
    g = cg(cards=("Remake",))
    set_zones(g, 0, hand=["Remake", "Estate", "Copper"], discard=[])
    play(g, "Remake")
    answer(g, "Estate")  # $2 -> gain $3
    answer(g, "Silver")
    answer(g, "Copper")  # $0 -> $1 (nothing costs $1, so no gain prompt)
    assert "Estate" in g.state.trash and "Copper" in g.state.trash
    assert "Silver" in g.state.players[0].discard


def test_tournament_and_all_five_prizes():
    g = cg(cards=("Tournament",))
    assert set(g.state.prizes) == set(PRIZES)
    set_zones(g, 0, hand=["Tournament", "Province"], deck=["Copper"] * 5, discard=[])
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Copper"] * 5)
    before = total_cards(g)
    play(g, "Tournament")
    answer(g, "Province")
    answer(g, "Bag of Gold")
    # Since no one else revealed Province, P0 also draws 1 card (the topdecked Bag of Gold!) and gets +$1
    assert "Bag of Gold" in g.state.players[0].hand
    assert g.state.coins == 1 and g.state.actions == 1
    assert "Bag of Gold" not in g.state.prizes
    assert total_cards(g) == before

    # Play Bag of Gold
    play(g, "Bag of Gold")
    assert g.state.players[0].deck[-1] == "Gold"

    # Test Princess cost reduction, Diadem, Followers, Trusty Steed
    set_zones(g, 0, hand=["Princess", "Followers", "Trusty Steed", "Diadem"], deck=["Copper"] * 10)
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Copper"] * 5)
    g.state.actions = 4
    play(g, "Princess")
    assert card_cost(g.state, "Province") == 6
    play(g, "Followers")
    answer(g, "Copper", "Copper", who=1)
    assert len(g.state.players[1].hand) == 3 and "Curse" in g.state.players[1].discard
    play(g, "Trusty Steed")
    answer(g, "+2 Actions", "+$2")
    to_buy_phase(g)
    # 3 unused actions left (started with 4, played 3 actions, Trusty Steed gave +2 -> 3 unused)
    coins_before = g.state.coins
    g.apply(0, PlayTreasure("Diadem"))
    assert g.state.coins == coins_before + 2 + 3


def test_young_witch_setup_bane_and_attack_counter():
    g = cg(cards=("Young Witch",))
    bane = g.state.bane_card
    assert bane is not None and bane in g.state.supply
    assert get_card(bane).cost in (2, 3) and get_card(bane).potion_cost == 0
    set_zones(g, 0, hand=["Young Witch", "Copper", "Estate"], deck=["Silver", "Gold"])
    set_zones(g, 1, hand=[bane, "Copper"])
    play(g, "Young Witch")
    answer(g, "Copper", "Estate")
    answer(g, bane, who=1)
    assert "Curse" not in g.state.players[1].all_cards()


def test_harvest_horn_of_plenty_hunting_party_jester_and_fairgrounds():
    g = cg(cards=("Harvest", "Horn of Plenty", "Hunting Party", "Jester", "Fairgrounds"))
    set_zones(g, 0, hand=["Harvest", "Hunting Party", "Jester", "Horn of Plenty"],
              deck=["Gold", "Silver", "Copper", "Copper", "Estate", "Duchy", "Province", "Village"])
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Silver", "Estate"])
    g.state.actions = 3
    play(g, "Harvest")  # reveals Village, Province, Duchy, Estate -> 4 unique -> +$4
    assert g.state.coins == 4
    play(g, "Hunting Party")  # draws Copper, then reveals Copper (dup), Silver (non-dup -> hand)
    assert "Silver" in g.state.players[0].hand
    play(g, "Jester")  # +$2; P1 discards Estate (Victory -> P1 gains Curse)
    assert "Curse" in g.state.players[1].discard

    to_buy_phase(g)
    # In play: Harvest, Hunting Party, Jester + Horn of Plenty = 4 unique cards
    g.apply(0, PlayTreasure("Horn of Plenty"))
    answer(g, "Estate")
    # Gaining Estate (Victory) trashes Horn of Plenty from play
    assert "Horn of Plenty" in g.state.trash

    # Fairgrounds scoring: 2 VP per 5 unique cards
    p0 = g.state.players[0]
    set_zones(g, 0, hand=["Fairgrounds", "Copper", "Silver", "Gold", "Estate", "Duchy",
                          "Province", "Village", "Smithy", "Moat"], deck=[], discard=[], in_play=[])
    assert len(set(p0.all_cards())) == 10
    assert score_player(p0) == 1 + 3 + 6 + 4  # Estate(1) + Duchy(3) + Province(6) + Fairgrounds(4)


def test_coffers_baker_candlestick_plaza_merchant_guild_butcher():
    g = cg(cards=("Baker", "Candlestick Maker", "Plaza", "Merchant Guild", "Butcher"))
    # Baker setup gives each player 1 Coffer
    assert g.state.players[0].coffers == 1 and g.state.players[1].coffers == 1
    set_zones(g, 0, hand=["Candlestick Maker", "Plaza", "Merchant Guild", "Butcher", "Copper", "Estate"],
              deck=["Silver"] * 5)
    play(g, "Candlestick Maker")  # +1 Action, +1 Buy, +1 Coffer (now 2)
    play(g, "Plaza")  # +1 Card, +2 Actions; discard Copper for +1 Coffer (now 3)
    answer(g, "Copper")
    assert g.state.players[0].coffers == 3
    play(g, "Merchant Guild")  # +1 Buy, +$1
    play(g, "Butcher")  # +2 Coffers (now 5); trash Estate ($2) + spend 3 Coffers -> gain $5 Baker
    answer(g, "Estate")
    answer(g, "3")
    answer(g, "Baker")
    assert g.state.players[0].coffers == 2 and "Baker" in g.state.players[0].discard

    to_buy_phase(g)
    wire = action_to_dict(SpendCoffer())
    assert action_from_dict(wire) == SpendCoffer()
    g.apply(0, SpendCoffer())
    g.apply(0, SpendCoffer())
    assert g.state.players[0].coffers == 0 and g.state.coins == 3
    g.apply(0, Buy("Silver"))
    # Merchant Guild in play gives +1 Coffer on buy
    assert g.state.players[0].coffers == 1


def test_overpay_masterpiece_stonemason_doctor_and_herald():
    g = cg(cards=("Masterpiece", "Stonemason", "Doctor", "Herald"))
    # Masterpiece overpay
    set_zones(g, 0, hand=[], discard=[])
    to_buy_phase(g)
    g.state.coins = 5
    g.state.buys = 4
    g.apply(0, Buy("Masterpiece"))  # costs $3, $2 left
    answer(g, "$2")
    assert g.state.players[0].discard.count("Silver") == 2 and g.state.coins == 0

    # Stonemason overpay
    g.state.coins = 5
    g.apply(0, Buy("Stonemason"))  # costs $2, $3 left -> overpay $3 for two $3 Actions
    answer(g, "$3")
    answer(g, "Village")
    answer(g, "Village")
    assert g.state.players[0].discard.count("Village") == 2

    # Doctor overpay
    set_zones(g, 0, deck=["Curse", "Gold"], discard=[])
    g.state.coins = 4
    g.apply(0, Buy("Doctor"))  # costs $3, $1 left
    answer(g, "$1")
    answer(g, "Trash it")  # trashes Gold (top of deck)
    assert "Gold" in g.state.trash

    # Herald overpay
    set_zones(g, 0, deck=["Copper"], discard=["Silver", "Estate"])
    g.state.coins = 5
    g.apply(0, Buy("Herald"))  # costs $4, $1 left
    answer(g, "$1")
    answer(g, "Silver")
    assert g.state.players[0].deck[-1] == "Silver"


def test_advisor_taxman_journeyman_soothsayer_doctor_herald_stonemason_on_play():
    g = cg(cards=("Advisor", "Taxman", "Journeyman", "Soothsayer", "Doctor", "Herald", "Stonemason"))
    set_zones(g, 0, hand=["Advisor", "Doctor", "Herald", "Stonemason", "Journeyman", "Taxman", "Soothsayer", "Copper", "Gold"],
              deck=["Copper", "Estate", "Silver", "Village", "Copper", "Copper", "Estate", "Gold", "Silver", "Duchy"])
    set_zones(g, 1, hand=["Copper", "Silver", "Estate", "Estate", "Duchy"], deck=["Gold"])
    g.state.actions = 10

    play(g, "Advisor")  # reveals Duchy, Silver, Gold; P1 chooses Gold to discard
    answer(g, "Gold", who=1)
    assert "Gold" in g.state.players[0].discard and "Duchy" in g.state.players[0].hand

    play(g, "Doctor")  # name Copper; reveals Estate, Copper, Copper -> trashes 2 Coppers, puts Estate back
    answer(g, "Copper")
    assert g.state.trash.count("Copper") == 2 and g.state.players[0].deck[-1] == "Estate"

    play(g, "Herald")  # draws Estate, then reveals Village (Action) and plays it!
    assert "Village" in g.state.players[0].in_play

    play(g, "Stonemason")  # trash Gold ($6) -> gain 2 cards costing <= $5
    answer(g, "Gold")
    answer(g, "Silver")
    answer(g, "Silver")

    play(g, "Taxman")  # trash Copper -> P1 (5 cards) discards Copper; P0 gains Silver onto deck
    answer(g, "Copper")
    answer(g, "Silver")
    assert "Copper" in g.state.players[1].discard and g.state.players[0].deck[-1] == "Silver"

    play(g, "Journeyman")  # name Copper; reveals up to 3 non-Coppers into hand
    answer(g, "Copper")

    set_zones(g, 1, hand=[], deck=["Gold"], discard=[])
    play(g, "Soothsayer")
    assert "Curse" in g.state.players[1].discard and g.state.players[1].hand == ["Gold"]


@pytest.mark.parametrize("players", [2, 3])
def test_random_games_with_cornucopia_and_guilds_hold_invariants_and_replay(players):
    for seed in range(6):
        rng = random.Random(seed)
        kingdom = rng.sample(CORNUCOPIA, 10)
        g = new_game(GameConfig([f"P{i}" for i in range(players)], kingdom, seed))
        before = total_cards(g)
        bots = [RandomBot(random.Random(rng.random())) for _ in range(players)]
        for step in range(1500):
            if g.state.status is GameStatus.FINISHED:
                break
            actor = g.acting_player
            action = bots[actor].choose(g, actor)
            assert action in g.legal_actions(actor)
            g.apply(actor, action)
            assert total_cards(g) == before
            if step % 50 == 0:
                for i in range(players):
                    json.dumps(build_view(g, i))
        r = replay(g.config, g.history)
        assert [p.all_cards() for p in r.state.players] == [p.all_cards() for p in g.state.players]
        assert r.state.supply == g.state.supply and r.state.trash == g.state.trash
