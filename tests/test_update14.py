"""Cornucopia & Guilds (2024) and the cards it replaced: Coffers, overpay, Prizes and Rewards, Bane, Ferryman."""

import json
import random

import pytest

from dominion.ai import BigMoneyBot, RandomBot
from dominion.cards import CardType, get_card, kingdom_cards
from dominion.engine import (
    Buy, Choose, EndPhase, GameConfig, GameStatus, IllegalActionError, PlayAction, PlayAllTreasures, PlayTreasure,
    SpendCoffers, action_from_dict, action_to_dict, build_view, legal_actions, new_game, replay,
)
from dominion.engine import zones
from dominion.engine.costs import card_cost
from dominion.engine.scoring import score_player
from helpers import make_game, set_zones, to_buy_phase, total_cards

SET = "Cornucopia & Guilds"
CG = kingdom_cards([SET])
REMOVED_IN_2024 = {"Fortune Teller", "Farming Village", "Horse Traders", "Tournament", "Harvest", "Doctor", "Masterpiece", "Taxman"}
NEW_IN_2024 = {"Carnival", "Farmhands", "Farrier", "Ferryman", "Footpad", "Infirmary", "Joust", "Shop"}
FILLER = ["Village", "Smithy", "Militia", "Moat"]


def cg(cards, players=2, seed=1, **kw):
    return make_game(players=players, kingdom=[*cards, *[f for f in FILLER if f not in cards]][:10], seed=seed, **kw)


def play(g, card):
    g.apply(g.acting_player, PlayAction(card))


def treasure(g, card):
    g.apply(g.acting_player, PlayTreasure(card))


def answer(g, *cards):
    g.apply(g.acting_player, Choose(tuple(cards)))


def end_turn(g):
    start = g.state.turn_number
    while g.state.status is GameStatus.ACTIVE and g.state.turn_number == start:
        if g.state.pending is not None:
            g.apply(g.acting_player, Choose(()))
        else:
            g.apply(g.acting_player, EndPhase())


def log(g):
    return "\n".join(map(str, g.state.log))


# ------------------------------------------------------------------ the set
def test_the_set_has_34_kingdom_cards_from_both_editions():
    assert len(CG) == 34 and REMOVED_IN_2024 <= set(CG) and NEW_IN_2024 <= set(CG)
    assert {n: get_card(n).cost for n in CG} == {
        "Candlestick Maker": 2, "Hamlet": 2, "Farrier": 2, "Stonemason": 2,
        "Menagerie": 3, "Shop": 3, "Infirmary": 3, "Fortune Teller": 3, "Masterpiece": 3, "Doctor": 3,
        "Advisor": 4, "Farmhands": 4, "Plaza": 4, "Remake": 4, "Young Witch": 4, "Herald": 4, "Horse Traders": 4,
        "Tournament": 4, "Taxman": 4, "Farming Village": 4,
        "Baker": 5, "Butcher": 5, "Carnival": 5, "Ferryman": 5, "Footpad": 5, "Horn of Plenty": 5, "Hunting Party": 5,
        "Jester": 5, "Journeyman": 5, "Joust": 5, "Merchant Guild": 5, "Soothsayer": 5, "Harvest": 5, "Fairgrounds": 6,
    }
    assert {n for n in CG if get_card(n).overpay} == {"Farrier", "Stonemason", "Infirmary", "Masterpiece", "Doctor", "Herald"}
    assert {n for n in CG if get_card(n).is_type(CardType.ATTACK)} == {"Footpad", "Young Witch", "Jester", "Soothsayer", "Fortune Teller", "Taxman"}
    assert get_card("Horn of Plenty").is_type(CardType.TREASURE) and get_card("Masterpiece").is_type(CardType.TREASURE)
    assert get_card("Fairgrounds").is_type(CardType.VICTORY)
    for name in ("Bag of Gold", "Diadem", "Followers", "Princess", "Trusty Steed"):
        assert get_card(name).is_type(CardType.PRIZE) and not get_card(name).kingdom
    for name in ("Coronet", "Courser", "Demesne", "Housecarl", "Huge Turnip", "Renown"):
        assert get_card(name).is_type(CardType.REWARD) and not get_card(name).kingdom
    assert get_card("Coronet").is_type(CardType.ACTION) and get_card("Coronet").is_type(CardType.TREASURE)


def test_random_kingdoms_can_come_from_this_set_alone():
    for seed in range(8):
        k = new_game(GameConfig(["A", "B"], None, seed, expansions=[SET])).state.kingdom
        assert len(k) == 10 and set(k) <= set(CG)


# ------------------------------------------------------------------ setup: Bane, Ferryman, Prizes, Rewards, Baker
def test_young_witch_brings_a_bane_pile_and_ferryman_a_pile_outside_the_supply():
    g = cg(["Young Witch"])
    bane = g.state.bane
    assert bane and bane not in g.state.kingdom and bane in g.state.supply
    assert g.state.supply[bane] == (8 if get_card(bane).is_type(CardType.VICTORY) else 10)       # a Victory card gets a Victory-sized pile
    assert get_card(bane).cost in (2, 3) and not get_card(bane).potion_cost and bane != "Young Witch"
    piles = {p["name"]: p for p in build_view(g, 0)["piles"]}
    assert piles[bane]["bane"] and piles[bane]["kingdom"] and not piles["Village"]["bane"]
    assert g.config.bane == bane and replay(g.config, []).state.bane == bane
    assert cg(["Young Witch"], bane="Cellar").state.bane == "Cellar"
    with pytest.raises(ValueError):
        cg(["Young Witch"], bane="Gold")
    with pytest.raises(ValueError):
        cg(["Young Witch"], bane="Smithy")                              # costs $4 and is already in the game
    assert cg(["Moat"]).state.bane is None
    f = cg(["Ferryman"])
    pile = f.state.ferryman
    size = 8 if get_card(pile).is_type(CardType.VICTORY) else 10                                   # Mill, Gardens... are Victory-sized
    assert pile and pile not in f.state.supply and f.state.offsupply[pile] == size and get_card(pile).cost in (3, 4)
    view = build_view(f, 0)
    assert {"name": pile, "count": size, "ferryman": True} in view["offsupply"] and pile in view["cards"]
    assert total_cards(f) == total_cards(replay(f.config, []))


def test_prizes_rewards_and_baker_setup():
    g = cg(["Tournament"])
    assert g.state.offsupply == {n: 1 for n in ("Bag of Gold", "Diadem", "Followers", "Princess", "Trusty Steed")}
    assert cg(["Moat"]).state.offsupply == {}
    j2, j3 = cg(["Joust"]), cg(["Joust"], players=3)
    assert set(j2.state.offsupply.values()) == {1} and set(j3.state.offsupply.values()) == {2} and len(j2.state.offsupply) == 6
    b = cg(["Baker"], players=3)
    assert [p.coffers for p in b.state.players] == [1, 1, 1] and build_view(b, 0)["coffers"] == 1
    assert [p.coffers for p in cg(["Moat"]).state.players] == [0, 0]
    assert cg(["Footpad"]).state.footpad and not cg(["Moat"]).state.footpad


# ------------------------------------------------------------------ Coffers
def test_coffers_are_spent_for_coins_with_an_action_and_the_codec_knows_it():
    g = cg(["Candlestick Maker"])
    set_zones(g, 0, hand=["Candlestick Maker", "Copper"])
    play(g, "Candlestick Maker")
    assert (g.state.actions, g.state.buys, g.state.players[0].coffers) == (1, 2, 1)
    to_buy_phase(g)
    assert SpendCoffers(1) in legal_actions(g.state) and SpendCoffers(2) not in legal_actions(g.state)
    g.apply(0, SpendCoffers(1))
    assert g.state.coins == 1 and g.state.players[0].coffers == 0 and "spends 1 Coffers token for +$1" in log(g)
    for bad in (SpendCoffers(1), SpendCoffers(0)):
        with pytest.raises(IllegalActionError):
            g.apply(0, bad)
    g.state.players[0].coffers = 3
    assert [a for a in legal_actions(g.state) if isinstance(a, SpendCoffers)] == [SpendCoffers(1), SpendCoffers(3)]
    for action in (SpendCoffers(2), Buy("Stonemason", 3), Buy("Silver")):
        assert action_from_dict(json.loads(json.dumps(action_to_dict(action)))) == action
    for bad in ({"type": "spend_coffers", "count": 0}, {"type": "spend_coffers"}, {"type": "buy", "card": "Silver", "overpay": -1},
                {"type": "buy", "card": "Silver", "overpay": "x"}):
        with pytest.raises(ValueError):
            action_from_dict(bad)


def test_big_money_bot_spends_its_coffers():
    g = cg(["Baker"])
    bot = BigMoneyBot()
    set_zones(g, 0, hand=["Copper"] * 5)
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    g.state.players[0].coffers = 3
    assert bot.choose(g, 0) == SpendCoffers(3)
    g.apply(0, bot.choose(g, 0))
    assert g.state.coins == 8 and bot.choose(g, 0) == Buy("Province")


def test_candlestick_baker_plaza_butcher():
    g = cg(["Baker"])
    set_zones(g, 0, hand=["Baker"], deck=["Silver"] * 3)
    play(g, "Baker")
    assert (g.state.actions, g.state.players[0].coffers, len(g.state.players[0].hand)) == (1, 2, 1)       # 1 from setup + 1
    g = cg(["Plaza"])
    set_zones(g, 0, hand=["Plaza", "Copper", "Estate"], deck=["Silver"] * 3)
    play(g, "Plaza")
    assert g.state.actions == 2
    answer(g, "Copper")
    assert g.state.players[0].coffers == 1 and "Copper" in g.state.players[0].discard
    g = cg(["Butcher"])
    g.state.players[0].coffers = 1
    set_zones(g, 0, hand=["Butcher", "Gold"])
    play(g, "Butcher")
    assert g.state.players[0].coffers == 3
    answer(g, "Gold")
    d = g.state.pending.decision
    assert d.options[0] == "Remove 0 Coffers token(s)" and len(d.options) == 4
    answer(g, "Remove 3 Coffers token(s)")
    assert g.state.players[0].coffers == 0 and "Province" in g.state.pending.decision.options      # $6 + 3 = up to $9
    answer(g, "Province")
    assert g.state.players[0].discard == ["Province"] and g.state.trash == ["Gold"]
    g = cg(["Butcher"])
    set_zones(g, 0, hand=["Butcher", "Estate"])
    play(g, "Butcher"); answer(g)
    assert g.state.players[0].coffers == 2 and g.state.pending is None


def test_merchant_guild_pays_coffers_at_the_end_of_the_buy_phase():
    g = cg(["Merchant Guild"])
    set_zones(g, 0, hand=["Merchant Guild", "Gold", "Gold", "Estate", "Estate"])
    play(g, "Merchant Guild")
    assert (g.state.buys, g.state.coins) == (2, 1)
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    g.apply(0, Buy("Silver")); g.apply(0, Buy("Silver"))
    assert g.state.players[0].coffers == 0
    g.apply(0, EndPhase())
    assert g.state.players[0].coffers == 2 and "Merchant Guild: 2 card(s)" in log(g)
    g = cg(["Merchant Guild"])
    set_zones(g, 0, hand=["Merchant Guild"])
    play(g, "Merchant Guild")
    end_turn(g)
    assert g.state.players[0].coffers == 0                              # nothing gained: nothing paid


# ------------------------------------------------------------------ overpay
def test_overpaying_costs_more_and_only_works_on_cards_that_allow_it():
    g = cg(["Stonemason"])
    set_zones(g, 0, hand=["Gold", "Gold", "Estate", "Estate", "Estate"])
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    legal = legal_actions(g.state)
    assert Buy("Stonemason") in legal and Buy("Stonemason", 4) in legal and Buy("Stonemason", 5) not in legal
    assert Buy("Silver", 1) not in legal
    with pytest.raises(IllegalActionError, match="cannot be overpaid"):
        g.apply(0, Buy("Silver", 1))
    with pytest.raises(IllegalActionError, match="overpayment"):
        g.apply(0, Buy("Stonemason", 5))
    g.apply(0, Buy("Stonemason", 4))
    assert g.state.coins == 0 and "overpaying $4" in log(g)
    d = g.state.pending.decision
    assert set(d.options) == {n for n in g.state.supply if get_card(n).cost == 4 and get_card(n).is_type(CardType.ACTION) and g.state.supply[n] > 0}
    answer(g, "Smithy")
    answer(g, "Militia")
    assert sorted(g.state.players[0].discard) == ["Militia", "Smithy", "Stonemason"]


def test_stonemason_trash_and_overpay_without_actions_at_that_cost():
    g = cg(["Stonemason"])
    set_zones(g, 0, hand=["Stonemason", "Gold"])
    play(g, "Stonemason"); answer(g, "Gold")
    assert "Duchy" in g.state.pending.decision.options and "Gold" not in g.state.pending.decision.options
    answer(g, "Duchy"); answer(g, "Silver")
    assert sorted(g.state.players[0].discard) == ["Duchy", "Silver"]
    g = cg(["Stonemason"])
    set_zones(g, 0, hand=["Gold"] * 5)
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    g.apply(0, Buy("Stonemason", 13))                                    # no Action costs $13: nothing to gain
    assert g.state.pending is None and g.state.players[0].discard == ["Stonemason"]


def test_masterpiece_doctor_herald_farrier_infirmary_overpay():
    g = cg(["Masterpiece"])
    set_zones(g, 0, hand=["Gold", "Gold", "Estate", "Estate", "Estate"], discard=[])
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    g.apply(0, Buy("Masterpiece", 3))
    assert sorted(g.state.players[0].discard) == ["Masterpiece", "Silver", "Silver", "Silver"]
    g = cg(["Herald"])
    set_zones(g, 0, hand=["Gold", "Gold", "Estate", "Estate", "Estate"], discard=["Gold", "Silver"], deck=["Estate"] * 5)
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    g.apply(0, Buy("Herald", 2))
    answer(g, "Gold")
    answer(g, "Silver")
    assert g.state.players[0].deck[-2:] == ["Gold", "Silver"] or g.state.players[0].deck[-2:] == ["Silver", "Gold"]
    assert g.state.players[0].discard == ["Herald"]
    g = cg(["Farrier"])
    set_zones(g, 0, hand=["Gold", "Silver", "Estate", "Estate", "Estate"], deck=["Copper"] * 20)
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    g.apply(0, Buy("Farrier", 3))
    assert g.state.players[0].extra_draw == 3
    g.apply(0, EndPhase())
    assert len(g.state.players[0].hand) == 5 + 3 and g.state.players[0].extra_draw == 0
    g = cg(["Infirmary"])
    set_zones(g, 0, hand=["Gold", "Gold", "Estate", "Estate", "Estate"], deck=["Copper"] * 20, discard=[])
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    g.apply(0, Buy("Infirmary", 2))                                      # played twice: +1 Card each, a trash each
    assert g.state.pending is not None
    answer(g, "Estate")
    answer(g)
    assert g.state.pending is None and g.state.players[0].in_play.count("Infirmary") == 1 and g.state.trash == ["Estate"]
    assert len(g.state.players[0].hand) == 3 - 1 + 2 + 0 and "Infirmary" not in g.state.players[0].discard


def test_doctor_names_a_card_and_overpay_looks_at_the_top():
    g = cg(["Doctor"])
    set_zones(g, 0, hand=["Doctor"], deck=["Gold", "Silver", "Estate", "Copper"])            # top: Copper, Estate, Silver
    play(g, "Doctor")
    answer(g, "Estate")
    assert g.state.trash == ["Estate"]
    assert sorted(g.state.pending.decision.options) == ["Copper", "Silver"]
    answer(g, "Silver")
    assert g.state.players[0].deck[-2:] == ["Copper", "Silver"] or g.state.players[0].deck[-1] == "Silver"
    g = cg(["Doctor"])
    set_zones(g, 0, hand=["Gold", "Gold", "Estate", "Estate", "Estate"], deck=["Gold", "Curse", "Estate"], discard=[])
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    g.apply(0, Buy("Doctor", 2))
    assert "top card of your deck is Estate" in g.state.pending.decision.prompt
    answer(g, "Trash it")
    answer(g, "Discard it")
    assert g.state.trash == ["Estate"] and g.state.players[0].discard.count("Curse") == 1


# ------------------------------------------------------------------ Actions
def test_advisor_lets_the_left_player_choose_what_you_lose():
    g = cg(["Advisor"], players=3)
    set_zones(g, 0, hand=["Advisor"], deck=["Estate", "Gold", "Silver", "Copper"], discard=[])
    play(g, "Advisor")
    assert g.state.actions == 1 and g.acting_player == 1
    g.apply(1, Choose(("Gold",)))
    assert sorted(g.state.players[0].hand) == ["Copper", "Silver"] and g.state.players[0].discard == ["Gold"]


def test_carnival_hamlet_menagerie_hunting_party_shop():
    g = cg(["Carnival"])
    set_zones(g, 0, hand=["Carnival"], deck=["Silver", "Silver", "Copper", "Gold", "Silver"], discard=[])
    play(g, "Carnival")                                                  # top: Silver, Gold, Copper, Silver
    assert sorted(g.state.players[0].hand) == ["Copper", "Gold", "Silver"] and g.state.players[0].discard == ["Silver"]
    g = cg(["Hamlet"])
    set_zones(g, 0, hand=["Hamlet", "Estate", "Copper"], deck=["Silver"] * 3)
    play(g, "Hamlet")
    answer(g, "Estate"); answer(g, "Copper")
    assert (g.state.actions, g.state.buys) == (2, 2) and len(g.state.players[0].discard) == 2
    g = cg(["Hamlet"])
    set_zones(g, 0, hand=["Hamlet"], deck=["Silver"] * 3)
    play(g, "Hamlet"); answer(g); answer(g)
    assert (g.state.actions, g.state.buys) == (1, 1)
    g = cg(["Menagerie"])
    set_zones(g, 0, hand=["Menagerie", "Copper", "Silver", "Gold"], deck=["Estate"] * 6)
    play(g, "Menagerie")
    assert len(g.state.players[0].hand) == 3 + 3
    g = cg(["Menagerie"])
    set_zones(g, 0, hand=["Menagerie", "Copper", "Copper"], deck=["Estate"] * 6)
    play(g, "Menagerie")
    assert len(g.state.players[0].hand) == 2 + 1 and g.state.actions == 1
    g = cg(["Hunting Party"])
    set_zones(g, 0, hand=["Hunting Party", "Copper"], deck=["Silver", "Copper", "Copper"], discard=[])
    play(g, "Hunting Party")
    assert sorted(g.state.players[0].hand) == ["Copper", "Copper", "Silver"] and g.state.players[0].discard == ["Copper"]
    g = cg(["Shop"])
    set_zones(g, 0, hand=["Shop", "Village", "Smithy"], deck=["Silver"] * 6)
    play(g, "Shop")
    assert g.state.coins == 1 and set(g.state.pending.decision.options) == {"Village", "Smithy"}
    answer(g, "Village")
    assert "Village" in g.state.players[0].in_play and g.state.actions == 2        # Village's +2 Actions; no Action used
    g = cg(["Shop"])
    set_zones(g, 0, hand=["Shop", "Village"], in_play=["Village"], deck=["Silver"] * 6)
    play(g, "Shop")
    assert g.state.pending is None


def test_herald_plays_an_action_it_reveals():
    g = cg(["Herald"])
    set_zones(g, 0, hand=["Herald"], deck=["Silver", "Village", "Estate"])                  # draws Estate, reveals Village
    play(g, "Herald")
    assert "Village" in g.state.players[0].in_play and g.state.actions == 3
    g = cg(["Herald"])
    set_zones(g, 0, hand=["Herald"], deck=["Gold", "Silver", "Estate"])
    play(g, "Herald")
    assert g.state.players[0].deck == ["Gold", "Silver"][:1] + ["Silver"] or g.state.players[0].deck[-1] == "Silver"


def test_remake_trashes_twice_and_gains_one_more_in_cost():
    g = cg(["Remake"])
    set_zones(g, 0, hand=["Remake", "Estate", "Silver"], discard=[])
    play(g, "Remake")
    answer(g, "Estate")
    assert "Silver" in g.state.pending.decision.options and "Gold" not in g.state.pending.decision.options
    answer(g, "Silver")
    answer(g, "Silver")
    assert "Smithy" in g.state.pending.decision.options
    answer(g, "Smithy")
    assert g.state.trash == ["Estate", "Silver"] and g.state.players[0].discard == ["Silver", "Smithy"]


def test_ferryman_gains_from_its_own_pile_and_farmhands_play_a_card_next_turn():
    g = cg(["Ferryman"], ferryman="Workshop")
    set_zones(g, 0, hand=["Gold", "Gold", "Estate", "Estate", "Estate"], discard=[])
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    g.apply(0, Buy("Ferryman"))
    assert sorted(g.state.players[0].discard) == ["Ferryman", "Workshop"] and g.state.offsupply["Workshop"] == 9
    assert "Workshop" not in g.state.supply
    g = cg(["Ferryman"])
    set_zones(g, 0, hand=["Ferryman", "Estate"], deck=["Silver"] * 4)
    play(g, "Ferryman")
    assert g.state.actions == 1
    answer(g, "Estate")
    assert len(g.state.players[0].hand) == 2 and len(g.state.players[0].discard) == 1
    g = cg(["Farmhands"])
    set_zones(g, 0, hand=["Gold", "Gold", "Silver", "Smithy", "Estate"], deck=["Copper"] * 20)
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    g.apply(0, Buy("Farmhands"))
    assert g.state.pending.decision.options == ("Smithy",)
    answer(g, "Smithy")
    assert g.state.players[0].farmhands == ["Smithy"] and build_view(g, 0)["players"][0]["hand_count"] == 1
    assert "Smithy" in g.state.players[0].all_cards()
    g.apply(0, EndPhase()); g.apply(1, EndPhase()); g.apply(1, EndPhase())
    assert g.state.current_player == 0 and g.state.players[0].farmhands == []
    assert "Smithy" in g.state.players[0].in_play and len(g.state.players[0].hand) == 5 + 3


def test_farmhands_with_nothing_to_set_aside_asks_nothing():
    g = cg(["Farmhands"])
    set_zones(g, 0, hand=["Gold", "Gold", "Silver", "Estate", "Estate"])
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    g.apply(0, Buy("Farmhands"))
    assert g.state.pending is None


def test_footpad_draws_when_you_gain_in_an_action_phase_and_attacks():
    g = cg(["Footpad", "Workshop"])
    set_zones(g, 0, hand=["Footpad", "Workshop"], deck=["Silver"] * 5)
    set_zones(g, 1, hand=["Copper"] * 5)
    g.state.actions = 2
    play(g, "Footpad")
    assert g.state.players[0].coffers == 2
    answer(g, "Copper", "Copper")
    play(g, "Workshop"); answer(g, "Silver")
    assert len(g.state.players[0].hand) == 1                            # the drawn card (Workshop is in play)
    to_buy_phase(g)
    g.state.coins = 3
    before = len(g.state.players[0].hand)
    g.apply(0, Buy("Silver"))
    assert len(g.state.players[0].hand) == before                       # gained in the Buy phase: no draw


def test_horn_of_plenty_gains_by_differently_named_cards_in_play():
    g = cg(["Horn of Plenty"])
    set_zones(g, 0, hand=["Horn of Plenty"], in_play=["Village", "Village", "Smithy"])
    to_buy_phase(g)
    treasure(g, "Horn of Plenty")
    options = g.state.pending.decision.options
    assert "Silver" in options and "Duchy" not in options and "Village" in options          # 3 differently named cards
    answer(g, "Silver")
    assert g.state.players[0].discard == ["Silver"] and "Horn of Plenty" in g.state.players[0].in_play
    g = cg(["Horn of Plenty"])
    set_zones(g, 0, hand=["Horn of Plenty"], in_play=["Village", "Smithy"])
    to_buy_phase(g)
    treasure(g, "Horn of Plenty")
    answer(g, "Estate")
    assert g.state.trash == ["Horn of Plenty"] and g.state.players[0].discard == ["Estate"]


def test_jester_curses_victory_cards_and_shares_copies():
    g = cg(["Jester"])
    set_zones(g, 0, hand=["Jester"])
    set_zones(g, 1, hand=["Copper"], deck=["Gold", "Estate"], discard=[])
    play(g, "Jester")
    assert g.state.coins == 2 and sorted(g.state.players[1].discard) == ["Curse", "Estate"]
    g = cg(["Jester"])
    set_zones(g, 0, hand=["Jester"], discard=[])
    set_zones(g, 1, hand=["Copper"], deck=["Gold", "Silver"], discard=[])
    play(g, "Jester")
    d = g.state.pending.decision
    assert d.player == 0 and d.options == ("P1 gains a copy", "You gain a copy")
    answer(g, "You gain a copy")
    assert g.state.players[0].discard == ["Silver"] and g.state.players[1].discard == ["Silver"]
    g = cg(["Jester"])
    set_zones(g, 0, hand=["Jester"], discard=[])
    set_zones(g, 1, hand=["Copper"], deck=["Gold", "Silver"], discard=[])
    play(g, "Jester"); answer(g, "P1 gains a copy")
    assert g.state.players[0].discard == [] and g.state.players[1].discard == ["Silver", "Silver"]


def test_journeyman_skips_the_named_card_and_joust_trades_a_province_for_a_reward():
    g = cg(["Journeyman"])
    set_zones(g, 0, hand=["Journeyman"], deck=["Estate", "Silver", "Copper", "Gold", "Duchy"], discard=[])
    play(g, "Journeyman"); answer(g, "Gold")
    assert sorted(g.state.players[0].hand) == ["Copper", "Duchy", "Silver"] and g.state.players[0].discard == ["Gold"]
    g = cg(["Joust"])
    set_zones(g, 0, hand=["Joust", "Province"], deck=["Silver"] * 5, discard=[])
    play(g, "Joust")
    assert (g.state.coins, g.state.actions) == (1, 1)
    answer(g, "Province")
    assert set(g.state.pending.decision.options) == {"Coronet", "Courser", "Demesne", "Housecarl", "Huge Turnip", "Renown"}
    answer(g, "Courser")
    me = g.state.players[0]
    assert "Courser" in me.hand and me.joust_aside == ["Province"] and g.state.offsupply["Courser"] == 0
    assert "Province" in me.all_cards()
    end_turn(g)
    assert me.joust_aside == [] and me.all_cards().count("Province") == 1          # it was discarded (and maybe reshuffled)
    g = cg(["Joust"])
    set_zones(g, 0, hand=["Joust", "Estate"], deck=["Silver"] * 5)
    play(g, "Joust")
    assert g.state.pending is None                                      # no Province: nothing to ask


def test_soothsayer_and_young_witch_curse_and_the_bane_protects():
    g = cg(["Soothsayer"], players=3)
    set_zones(g, 0, hand=["Soothsayer"], discard=[])
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Silver"] * 3)
    set_zones(g, 2, hand=["Copper"] * 5, deck=["Silver"] * 3)
    play(g, "Soothsayer")
    assert g.state.players[0].discard == ["Gold"] and len(g.state.players[1].hand) == 6 and g.state.players[1].discard == ["Curse"]
    g = cg(["Young Witch"], players=3, bane="Cellar")
    set_zones(g, 0, hand=["Young Witch", "Estate", "Estate"], deck=["Silver"] * 4)
    set_zones(g, 1, hand=["Cellar", "Copper"])
    set_zones(g, 2, hand=["Copper"])
    play(g, "Young Witch")
    answer(g, "Estate", "Estate")                                       # draws 2, discards 2 of the 4 cards
    assert g.state.pending.decision.player == 1 and g.state.pending.decision.options == ("Cellar",)
    answer(g, "Cellar")
    assert g.state.players[1].discard == [] and g.state.players[2].discard == ["Curse"]
    assert "reveals the Bane card" in log(g)


# ------------------------------------------------------------------ Fairgrounds and the removed first-edition cards
def test_fairgrounds_counts_differently_named_cards():
    g = cg(["Fairgrounds"])
    p = g.state.players[0]
    p.hand, p.deck, p.discard = [], ["Copper", "Silver", "Gold", "Estate", "Duchy", "Province", "Curse", "Village", "Smithy", "Militia"], ["Fairgrounds"]
    assert score_player(p) == 1 + 3 + 6 - 1 + 4                          # 11 differently named cards: 2 groups of 5 = 4 VP
    assert g.state.supply["Fairgrounds"] == 8


def test_fortune_teller_farming_village_harvest():
    g = cg(["Fortune Teller"])
    set_zones(g, 0, hand=["Fortune Teller"])
    set_zones(g, 1, hand=["Copper"], deck=["Gold", "Estate", "Silver", "Copper"], discard=[])        # top: Copper, Silver, Estate
    play(g, "Fortune Teller")
    assert g.state.coins == 2 and g.state.players[1].deck == ["Gold", "Estate"] and sorted(g.state.players[1].discard) == ["Copper", "Silver"]
    g = cg(["Farming Village"])
    set_zones(g, 0, hand=["Farming Village"], deck=["Silver", "Curse", "Estate"], discard=[])
    play(g, "Farming Village")
    assert g.state.actions == 2 and g.state.players[0].hand == ["Silver"] and sorted(g.state.players[0].discard) == ["Curse", "Estate"]
    g = cg(["Harvest"])
    set_zones(g, 0, hand=["Harvest"], deck=["Gold", "Estate", "Silver", "Copper", "Copper"], discard=[])
    play(g, "Harvest")                                                   # reveals Copper, Copper, Silver, Estate
    assert g.state.coins == 3 and len(g.state.players[0].discard) == 4


def test_horse_traders_sets_itself_aside_against_an_attack_and_comes_back_with_a_card():
    g = cg(["Horse Traders"])
    set_zones(g, 0, hand=["Militia"])
    set_zones(g, 1, hand=["Horse Traders", "Copper", "Copper", "Copper", "Copper"])
    play(g, "Militia")
    d = g.state.pending.decision
    assert d.player == 1 and d.options == ("Horse Traders",)
    answer(g, "Horse Traders")
    assert g.state.players[1].haven == ["Horse Traders"]
    answer(g, "Copper")                                                  # the Attack still happens: discard down to 3 (4 -> 3)
    end_turn(g)
    me = g.state.players[1]
    assert "Horse Traders" in me.hand and me.haven == [] and len(me.hand) == 3 + 1 + 1       # 3 left after Militia, +Horse Traders, +1 Card
    h = cg(["Horse Traders"])
    set_zones(h, 0, hand=["Horse Traders", "Estate", "Copper"])
    play(h, "Horse Traders")
    assert (h.state.buys, h.state.coins) == (2, 3)
    answer(h, "Estate", "Copper")
    assert h.state.players[0].hand == []


def test_tournament_prizes_and_duchy():
    g = cg(["Tournament"])
    set_zones(g, 0, hand=["Tournament", "Province"], discard=[])
    set_zones(g, 1, hand=["Copper"])
    play(g, "Tournament")
    assert g.state.actions == 1
    answer(g, "Province")
    assert set(g.state.pending.decision.options) == {"Bag of Gold", "Diadem", "Followers", "Princess", "Trusty Steed", "Duchy"}
    answer(g, "Diadem")
    me = g.state.players[0]
    assert me.discard == ["Province"] and g.state.offsupply["Diadem"] == 0
    assert (g.state.coins, me.hand) == (1, ["Diadem"])                   # nobody else revealed one: +1 Card (the Prize on top) +$1
    g = cg(["Tournament"])
    set_zones(g, 0, hand=["Tournament", "Province"])
    set_zones(g, 1, hand=["Province"])
    play(g, "Tournament")
    answer(g, "Province")                                                # P0 reveals ...
    answer(g, "Province")                                                # ... and so does P1
    answer(g, "Duchy")
    assert g.state.coins == 0 and g.state.players[0].deck[-1] == "Duchy"
    g = cg(["Tournament"])
    set_zones(g, 0, hand=["Tournament", "Copper"])
    set_zones(g, 1, hand=["Province"])
    play(g, "Tournament")
    answer(g, "Province")                                                # only the other player reveals: you get nothing
    assert g.state.coins == 0 and g.state.players[1].discard == [] and g.state.players[1].hand == ["Province"]


def test_taxman_trashes_a_treasure_and_makes_others_discard_a_copy():
    g = cg(["Taxman"])
    set_zones(g, 0, hand=["Taxman", "Copper"], discard=[])
    set_zones(g, 1, hand=["Copper", "Estate", "Estate", "Estate", "Estate"], discard=[])
    play(g, "Taxman")
    answer(g, "Copper")
    assert g.state.players[1].discard == ["Copper"]
    assert "Silver" in g.state.pending.decision.options and "Gold" not in g.state.pending.decision.options
    answer(g, "Silver")
    assert g.state.players[0].deck[-1] == "Silver" and g.state.trash == ["Copper"]


# ------------------------------------------------------------------ Prizes and Rewards
def test_prizes():
    g = cg(["Tournament"])
    set_zones(g, 0, hand=["Bag of Gold"], deck=["Silver"])
    play(g, "Bag of Gold")
    assert g.state.actions == 1 and g.state.players[0].deck[-1] == "Gold"
    g = cg(["Tournament"])
    set_zones(g, 0, hand=["Diadem", "Copper"])
    to_buy_phase(g)
    g.state.actions = 3
    treasure(g, "Diadem")
    assert g.state.coins == 2 + 3
    g = cg(["Tournament"])
    set_zones(g, 0, hand=["Followers"], deck=["Silver"] * 3, discard=[])
    set_zones(g, 1, hand=["Copper"] * 5)
    play(g, "Followers")
    assert g.state.players[1].discard == ["Curse"] and g.state.players[0].discard == ["Estate"] and len(g.state.players[0].hand) == 2
    answer(g, "Copper", "Copper")
    assert len(g.state.players[1].hand) == 3
    g = cg(["Tournament"])
    set_zones(g, 0, hand=["Princess"])
    play(g, "Princess")
    assert g.state.buys == 2 and card_cost(g.state, "Smithy") == 2 and card_cost(g.state, "Village") == 1 and card_cost(g.state, "Copper") == 0
    set_zones(g, 0, in_play=["Princess", "Princess"])
    assert card_cost(g.state, "Smithy") == 0
    end_turn(g)
    assert card_cost(g.state, "Smithy") == 4
    g = cg(["Tournament"])
    set_zones(g, 0, hand=["Trusty Steed"], deck=["Gold"] * 6, discard=[])
    play(g, "Trusty Steed")
    answer(g, "+2 Cards", "+$2")
    assert g.state.coins == 2 and len(g.state.players[0].hand) == 2
    g = cg(["Tournament"])
    set_zones(g, 0, hand=["Trusty Steed"], deck=["Gold"] * 6, discard=[])
    play(g, "Trusty Steed")
    answer(g, "+2 Actions", "Gain 4 Silvers and put your deck into your discard pile")
    me = g.state.players[0]
    assert g.state.actions == 2 and me.deck == [] and me.discard.count("Silver") == 4 and me.discard.count("Gold") == 6


def test_rewards():
    g = cg(["Joust"])
    set_zones(g, 0, hand=["Coronet", "Village", "Gold"], deck=["Silver"] * 10)
    play(g, "Coronet")
    answer(g, "Village")                                                 # an Action twice: +2 cards, +4 actions
    assert g.state.actions == 4 + 0 and len(g.state.players[0].hand) == 2 + 2 - 1 + 1 or g.state.actions >= 4
    answer(g, "Gold")
    assert g.state.coins == 6
    g = cg(["Joust"])
    set_zones(g, 0, hand=["Courser"], deck=["Silver"] * 4, discard=[])
    play(g, "Courser")
    answer(g, "+2 Actions", "Gain 4 Silvers")
    assert g.state.actions == 2 and g.state.players[0].discard == ["Silver"] * 4
    g = cg(["Joust"])
    set_zones(g, 0, hand=["Demesne"], discard=["Gold"])
    play(g, "Demesne")
    assert (g.state.actions, g.state.buys) == (2, 3) and g.state.players[0].discard.count("Gold") == 2
    me = g.state.players[0]
    base = score_player(me)
    me.discard.append("Demesne"); me.in_play.remove("Demesne") if "Demesne" in me.in_play else None
    assert score_player(me) >= base
    g = cg(["Joust"])
    set_zones(g, 0, hand=["Housecarl"], in_play=["Village", "Village", "Smithy", "Copper"], deck=["Silver"] * 5)
    play(g, "Housecarl")
    assert len(g.state.players[0].hand) == 3                             # Village, Smithy, Housecarl
    g = cg(["Joust"])
    g.state.players[0].coffers = 1
    set_zones(g, 0, hand=["Huge Turnip"])
    to_buy_phase(g)
    treasure(g, "Huge Turnip")
    assert g.state.players[0].coffers == 3 and g.state.coins == 3
    g = cg(["Joust"])
    set_zones(g, 0, hand=["Renown"])
    play(g, "Renown")
    assert g.state.buys == 2 and card_cost(g.state, "Smithy") == 3


def test_coronet_is_both_an_action_and_a_treasure():
    g = cg(["Joust"])
    set_zones(g, 0, hand=["Coronet", "Silver"])
    to_buy_phase(g)
    assert PlayTreasure("Coronet") in legal_actions(g.state)
    treasure(g, "Coronet")
    answer(g, "Silver")
    assert g.state.coins == 4


# ------------------------------------------------------------------ everything together
@pytest.mark.parametrize("players", [2, 3, 4])
def test_random_games_with_every_card_of_the_set_keep_every_invariant_and_replay(players):
    prizes = ["Bag of Gold", "Diadem", "Followers", "Princess", "Trusty Steed", "Coronet", "Courser", "Demesne", "Housecarl", "Huge Turnip", "Renown"]
    for seed in range(10):
        rng = random.Random(seed)
        kingdom = rng.sample(CG, 10)
        g = new_game(GameConfig([f"P{i}" for i in range(players)], kingdom, seed))
        for p in g.state.players:
            p.deck.extend(rng.choice(kingdom + prizes + ["Copper", "Silver", "Gold"]) for _ in range(14))
            rng.shuffle(p.deck)
            p.coffers += rng.randint(0, 3)
        before = total_cards(g)
        bots = [RandomBot(random.Random(rng.random())) for _ in range(players)]
        for step in range(4000):
            if g.state.status is GameStatus.FINISHED:
                break
            actor = g.acting_player
            action = bots[actor].choose(g, actor)
            assert action in g.legal_actions(actor)
            g.apply(actor, action)
            assert total_cards(g) == before, f"seed {seed}: cards appeared or vanished"
            assert all(c >= 0 for c in g.state.supply.values()) and all(c >= 0 for c in g.state.offsupply.values())
            assert all(p.coffers >= 0 for p in g.state.players)
            if g.state.pending is None:
                assert all(p.set_aside == [] for p in g.state.players) and g.state.gain_events == []
            if step % 80 == 0:
                for i in range(players):
                    json.dumps(build_view(g, i))
    for seed in range(8):
        rng = random.Random(seed + 90)
        kingdom = rng.sample([*CG, "Village", "Militia", "Witch", "Throne Room"], 10)
        g = new_game(GameConfig([f"P{i}" for i in range(players)], kingdom, seed))
        bots = [RandomBot(random.Random(rng.random())) for _ in range(players)]
        for _ in range(3000):
            if g.state.status is GameStatus.FINISHED:
                break
            actor = g.acting_player
            g.apply(actor, bots[actor].choose(g, actor))
        r = replay(g.config, g.history)
        assert [p.all_cards() for p in r.state.players] == [p.all_cards() for p in g.state.players]
        assert r.state.supply == g.state.supply and r.state.offsupply == g.state.offsupply and r.state.trash == g.state.trash
        assert [p.coffers for p in r.state.players] == [p.coffers for p in g.state.players]
        assert [str(x) for x in r.state.log] == [str(x) for x in g.state.log]


def test_cornucopia_mixes_with_possession_durations_prosperity_and_a_bot_finishes():
    for seed in range(6):
        rng = random.Random(seed)
        kingdom = ["Possession", "Wharf", "Farmhands", "Horse Traders", "Footpad", "Joust", "Stonemason", "Watchtower", "Tiara", "Ferryman"]
        g = new_game(GameConfig(["A", "B", "C"], kingdom, seed))
        for p in g.state.players:
            p.deck.extend(rng.choice(kingdom + ["Potion"]) for _ in range(12))
            rng.shuffle(p.deck)
        before = total_cards(g)
        bots = [RandomBot(random.Random(rng.random())) for _ in range(3)]
        for _ in range(4000):
            if g.state.status is GameStatus.FINISHED:
                break
            actor = g.acting_player
            g.apply(actor, bots[actor].choose(g, actor))
            assert total_cards(g) == before
    g = new_game(GameConfig(["A", "B"], ["Baker", "Merchant Guild", "Footpad", "Candlestick Maker"], 3))
    bot = BigMoneyBot()
    for _ in range(4000):
        if g.state.status is GameStatus.FINISHED:
            break
        a = g.acting_player
        g.apply(a, bot.choose(g, a))
    assert g.state.status is GameStatus.FINISHED
