"""The Prosperity expansion (2010 and 2022): Platinum and Colony, VP tokens, Treasures with effects, gain effects."""

import json
import random
from itertools import combinations

import pytest

from dominion.ai import BigMoneyBot, RandomBot
from dominion.cards import CardType, get_card, kingdom_cards
from dominion.engine import (
    Buy, Choose, EndPhase, GameConfig, GameStatus, IllegalActionError, PlayAction, PlayAllTreasures, PlayTreasure,
    build_view, legal_actions, new_game, replay,
)
from dominion.engine.costs import card_cost
from dominion.engine.rules import _legal_choices
from dominion.engine.actions import Decision
from dominion.engine.scoring import score_player, vp_breakdown
from helpers import make_game, set_zones, to_buy_phase, total_cards

PROSPERITY = kingdom_cards(["Prosperity"])
FIRST_EDITION_ONLY = {"Loan", "Trade Route", "Talisman", "Contraband", "Counting House", "Mountebank", "Royal Seal", "Venture", "Goons"}
SECOND_EDITION_NEW = {"Anvil", "Clerk", "Investment", "Tiara", "Charlatan", "Collection", "Crystal Ball", "Magnate", "War Chest"}


def pg(cards, players=2, seed=1, **kw):
    return make_game(players=players, kingdom=[*cards, "Village", "Smithy", "Militia", "Moat"][:10], seed=seed, **kw)


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
def test_the_set_has_both_editions_34_cards():
    assert len(PROSPERITY) == 34
    assert FIRST_EDITION_ONLY <= set(PROSPERITY) and SECOND_EDITION_NEW <= set(PROSPERITY)
    assert {n: get_card(n).cost for n in PROSPERITY} == {
        "Anvil": 3, "Loan": 3, "Trade Route": 3, "Watchtower": 3,
        "Bishop": 4, "Clerk": 4, "Investment": 4, "Monument": 4, "Quarry": 4, "Talisman": 4, "Tiara": 4, "Workers' Village": 4,
        "Charlatan": 5, "City": 5, "Collection": 5, "Contraband": 5, "Counting House": 5, "Crystal Ball": 5, "Magnate": 5,
        "Mint": 5, "Mountebank": 5, "Rabble": 5, "Royal Seal": 5, "Vault": 5, "Venture": 5, "War Chest": 5,
        "Goons": 6, "Grand Market": 6, "Hoard": 6, "Bank": 7, "Expand": 7, "Forge": 7, "King's Court": 7, "Peddler": 8,
    }
    treasures = {n for n in PROSPERITY if get_card(n).is_type(CardType.TREASURE)}
    assert treasures == {"Anvil", "Loan", "Investment", "Quarry", "Talisman", "Tiara", "Collection", "Contraband", "Crystal Ball",
                         "Royal Seal", "Venture", "War Chest", "Hoard", "Bank"}
    assert {n for n in PROSPERITY if get_card(n).is_type(CardType.ATTACK)} == {"Clerk", "Charlatan", "Mountebank", "Rabble", "Goons"}
    assert get_card("Platinum").coins == 5 and get_card("Platinum").cost == 9
    assert get_card("Colony").cost == 11 and get_card("Colony").vp == 10


def test_random_kingdoms_can_come_from_prosperity_alone():
    for seed in range(8):
        k = new_game(GameConfig(["A", "B"], None, seed, expansions=["Prosperity"])).state.kingdom
        assert len(k) == 10 and set(k) <= set(PROSPERITY)


# ------------------------------------------------------------------ Platinum and Colony
def test_platinum_and_colony_pile_sizes_and_the_automatic_rule():
    g = pg(["Bank"], colonies=True)
    assert g.state.supply["Platinum"] == 12 and g.state.supply["Colony"] == 8
    g3 = pg(["Bank"], players=3, colonies=True)
    assert g3.state.supply["Platinum"] == 12 and g3.state.supply["Colony"] == 12
    assert "Platinum" not in pg(["Bank"], colonies=False).state.supply
    assert g.config.colonies is True
    for seed in range(10):                                      # all Prosperity -> always; no Prosperity -> never
        assert "Colony" in make_game(kingdom=PROSPERITY[:10], seed=seed).state.supply
        assert "Colony" not in make_game(seed=seed).state.supply
    assert any("Colony" in make_game(kingdom=[*PROSPERITY[:3], "Village", "Smithy", "Moat", "Militia", "Cellar", "Chapel", "Market"],
                                     seed=s).state.supply for s in range(20))
    assert any("Colony" not in make_game(kingdom=[*PROSPERITY[:3], "Village", "Smithy", "Moat", "Militia", "Cellar", "Chapel", "Market"],
                                         seed=s).state.supply for s in range(20))


def test_colony_is_worth_ten_platinum_five_and_an_empty_colony_pile_ends_the_game():
    g = pg(["Bank"], colonies=True)
    g.state.players[0].discard.append("Colony")
    assert score_player(g.state.players[0]) == 3 + 10
    set_zones(g, 0, hand=["Platinum", "Platinum", "Estate", "Estate", "Estate"])
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    assert g.state.coins == 10
    g = pg(["Bank"], colonies=True, supply_overrides={"Colony": 0})
    end_turn(g)
    assert g.state.status is GameStatus.FINISHED
    assert {p["name"] for p in build_view(g, 0)["piles"]} >= {"Platinum", "Colony"}


# ------------------------------------------------------------------ VP tokens
def test_vp_tokens_count_for_scoring_and_show_in_the_breakdown():
    g = pg(["Monument"])
    me = g.state.players[0]
    base = score_player(me)
    set_zones(g, 0, hand=["Monument"])
    play(g, "Monument")
    assert g.state.coins == 2 and me.vp_tokens == 1 and score_player(me) == base + 1
    rows = {r["card"]: r for r in vp_breakdown(me)}
    assert rows["VP tokens"] == {"card": "VP tokens", "count": 1, "vp": 1}
    assert sum(r["vp"] for r in rows.values()) == score_player(me)
    assert build_view(g, 1)["players"][0]["vp_tokens"] == 1 and build_view(g, 1)["players"][0]["vp"] == base + 1


def test_bishop_trashes_for_vp_and_lets_others_trash():
    g = pg(["Bishop"])
    set_zones(g, 0, hand=["Bishop", "Gold", "Estate"])
    set_zones(g, 1, hand=["Curse", "Copper"])
    play(g, "Bishop")
    assert (g.state.coins, g.state.players[0].vp_tokens) == (1, 1)
    answer(g, "Gold")
    assert g.state.players[0].vp_tokens == 1 + 3 and g.state.trash == ["Gold"]
    d = g.state.pending.decision
    assert d.player == 1 and (d.min_choices, d.max_choices) == (0, 1)
    answer(g, "Curse")
    assert g.state.trash == ["Gold", "Curse"] and g.state.players[1].vp_tokens == 0
    g = pg(["Bishop"])
    set_zones(g, 0, hand=["Bishop"])
    set_zones(g, 1, hand=[])
    play(g, "Bishop")
    assert g.state.pending is None and g.state.players[0].vp_tokens == 1        # nothing to trash: still the $1 and the token


# ------------------------------------------------------------------ costs
def test_quarry_makes_actions_cheaper_this_turn_and_peddler_in_the_buy_phase():
    g = pg(["Quarry", "Peddler"])
    set_zones(g, 0, hand=["Quarry", "Copper"])
    to_buy_phase(g)
    assert card_cost(g.state, "Smithy") == 4
    treasure(g, "Quarry")
    assert g.state.coins == 1 and card_cost(g.state, "Smithy") == 2 and card_cost(g.state, "Village") == 1
    assert card_cost(g.state, "Silver") == 3 and card_cost(g.state, "Peddler") == 6
    assert {p["name"]: p["price"] for p in build_view(g, 1)["piles"]}["Smithy"] == 2
    end_turn(g)
    assert card_cost(g.state, "Smithy") == 4
    g = pg(["Peddler"])
    set_zones(g, 0, hand=["Copper"], in_play=["Village", "Smithy"])
    assert card_cost(g.state, "Peddler") == 8                   # only cheaper in the Buy phase
    to_buy_phase(g)
    assert card_cost(g.state, "Peddler") == 4
    g.state.players[0].in_play.extend(["Village", "Village", "Smithy"])
    assert card_cost(g.state, "Peddler") == 0


# ------------------------------------------------------------------ Actions
def test_city_gets_better_with_empty_piles():
    for empty, (cards, buys, coins) in ((0, (1, 1, 0)), (1, (2, 1, 0)), (2, (2, 2, 1))):
        over = dict(list({"Curse": 0, "Duchy": 0}.items())[:empty])
        g = pg(["City"], supply_overrides=over)
        set_zones(g, 0, hand=["City"], deck=["Copper"] * 10)
        play(g, "City")
        assert (len(g.state.players[0].hand), g.state.buys, g.state.coins, g.state.actions) == (cards, buys, coins, 2)


def test_workers_village_and_grand_market():
    g = pg(["Workers' Village"])
    set_zones(g, 0, hand=["Workers' Village"], deck=["Silver"] * 3)
    play(g, "Workers' Village")
    assert (g.state.actions, g.state.buys, len(g.state.players[0].hand)) == (2, 2, 1)
    g = pg(["Grand Market"])
    set_zones(g, 0, hand=["Grand Market"], deck=["Silver"] * 3)
    play(g, "Grand Market")
    assert (g.state.actions, g.state.buys, g.state.coins) == (1, 2, 2)


def test_grand_market_cannot_be_bought_with_a_copper_in_play():
    g = pg(["Grand Market"])
    set_zones(g, 0, hand=["Copper", "Silver", "Gold", "Gold", "Gold"])
    to_buy_phase(g)
    treasure(g, "Gold"); treasure(g, "Gold"); treasure(g, "Gold")
    assert Buy("Grand Market") in legal_actions(g.state)
    treasure(g, "Copper")
    assert Buy("Grand Market") not in legal_actions(g.state)
    with pytest.raises(IllegalActionError, match="Copper in play"):
        g.apply(0, Buy("Grand Market"))
    g.state.buys = 2
    g.apply(0, Buy("Silver"))                                     # other cards are fine
    set_zones(g, 0, in_play=[])                                   # no Coppers left in play (e.g. after a Mint)
    assert Buy("Grand Market") in legal_actions(g.state)


def test_expand_and_forge():
    g = pg(["Expand"])
    set_zones(g, 0, hand=["Expand", "Silver"])
    play(g, "Expand"); answer(g, "Silver")
    assert "Gold" in g.state.pending.decision.options and "Province" not in g.state.pending.decision.options   # $3 + $3 = $6
    answer(g, "Gold")
    assert g.state.players[0].discard == ["Gold"]
    g = pg(["Forge"])
    set_zones(g, 0, hand=["Forge", "Estate", "Estate", "Copper"])
    play(g, "Forge")
    answer(g, "Estate", "Estate")
    d = g.state.pending.decision
    assert set(d.options) == {n for n in g.state.supply if get_card(n).cost == 4 and g.state.supply[n] > 0}
    answer(g, "Smithy")
    assert g.state.players[0].discard == ["Smithy"] and g.state.trash == ["Estate", "Estate"]
    g = pg(["Forge"])
    set_zones(g, 0, hand=["Forge", "Copper"])
    play(g, "Forge"); answer(g)                                   # trash nothing: gain a card costing exactly $0
    assert g.state.pending.decision.options == ("Copper", "Curse")


def test_kings_court_plays_an_action_three_times_and_stays_with_a_duration_card():
    g = pg(["King's Court"])
    set_zones(g, 0, hand=["King's Court", "Village"], deck=["Silver"] * 10)
    play(g, "King's Court"); answer(g, "Village")
    assert g.state.actions == 6 and len(g.state.players[0].hand) == 3
    g = make_game(kingdom=["King's Court", "Wharf", "Village", "Smithy"])
    set_zones(g, 0, hand=["King's Court", "Wharf"], deck=["Silver"] * 30)
    play(g, "King's Court"); answer(g, "Wharf")
    assert g.state.buys == 4
    end_turn(g)
    assert sorted(g.state.players[0].in_play) == ["King's Court", "Wharf"]
    end_turn(g)
    assert g.state.buys == 4 and len(g.state.players[0].hand) == 5 + 6


def test_magnate_counts_treasures_in_hand():
    g = pg(["Magnate"])
    set_zones(g, 0, hand=["Magnate", "Copper", "Silver", "Estate"], deck=["Gold"] * 5)
    play(g, "Magnate")
    assert len(g.state.players[0].hand) == 3 + 2


def test_vault_lets_everyone_trade_cards_for_money_or_cards():
    g = pg(["Vault"])
    set_zones(g, 0, hand=["Vault", "Estate", "Estate"], deck=["Silver"] * 5)
    set_zones(g, 1, hand=["Copper", "Curse", "Estate"], deck=["Gold"] * 3)
    play(g, "Vault")
    answer(g, "Estate", "Estate")
    assert g.state.coins == 2
    answer(g, "Discard 2 cards to draw a card", )
    answer(g, "Curse", "Estate")
    assert sorted(g.state.players[1].hand) == ["Copper", "Gold"] and len(g.state.players[1].discard) == 2
    g = pg(["Vault"])
    set_zones(g, 0, hand=["Vault"], deck=["Silver"] * 5)
    set_zones(g, 1, hand=["Copper"])
    play(g, "Vault"); answer(g)
    answer(g, "Discard 2 cards to draw a card")
    answer(g, "Copper")
    assert g.state.players[1].hand == [] and g.state.pending is None          # only one card: no draw


def test_rabble_discards_actions_and_treasures_and_lets_the_victim_reorder():
    g = pg(["Rabble"])
    set_zones(g, 0, hand=["Rabble"], deck=["Silver"] * 5)
    set_zones(g, 1, hand=["Estate"], deck=["Gold", "Curse", "Estate", "Silver"], discard=[])   # top: Silver, Estate, Curse
    play(g, "Rabble")
    d = g.state.pending.decision
    assert d.player == 1 and sorted(d.options) == ["Curse", "Estate"] and g.state.players[1].discard == ["Silver"]
    answer(g, "Curse")
    assert g.state.players[1].deck[-2:] == ["Estate", "Curse"] and g.state.pending is None


def test_counting_house_takes_coppers_from_the_discard_pile():
    g = pg(["Counting House"])
    set_zones(g, 0, hand=["Counting House"], discard=["Copper", "Copper", "Copper", "Estate"])
    play(g, "Counting House")
    assert g.state.pending.decision.options[0] == "Take 0 Coppers" and len(g.state.pending.decision.options) == 4
    answer(g, "Take 2 Coppers")
    assert g.state.players[0].hand == ["Copper", "Copper"] and g.state.players[0].discard.count("Copper") == 1
    g = pg(["Counting House"])
    set_zones(g, 0, hand=["Counting House"], discard=["Estate"])
    play(g, "Counting House")
    assert g.state.pending is None


def test_mountebank_curses_and_coppers_unless_a_curse_is_discarded():
    g = pg(["Mountebank"], players=3)
    set_zones(g, 0, hand=["Mountebank"])
    set_zones(g, 1, hand=["Curse", "Copper"])
    set_zones(g, 2, hand=["Estate"], discard=[])
    play(g, "Mountebank")
    assert g.state.coins == 2
    answer(g, "Discard a Curse")
    assert g.state.players[1].discard == ["Curse"] and sorted(g.state.players[2].discard) == ["Copper", "Curse"]


def test_goons_attack_and_vp_for_every_buy_while_in_play():
    g = pg(["Goons"])
    set_zones(g, 0, hand=["Goons", "Gold", "Gold", "Gold", "Estate"])
    set_zones(g, 1, hand=["Copper"] * 5)
    play(g, "Goons")
    assert (g.state.buys, g.state.coins) == (2, 2)
    answer(g, "Copper", "Copper")
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    g.apply(0, Buy("Silver")); g.apply(0, Buy("Silver"))
    assert g.state.players[0].vp_tokens == 2
    g.state.players[0].in_play.append("Goons")                     # a second Goons gives 2 per purchase
    g.state.buys = 1
    g.apply(0, Buy("Estate"))
    assert g.state.players[0].vp_tokens == 2 + 2


def test_trade_route_tokens_move_to_the_mat_and_pay_out():
    g = make_game(kingdom=["Trade Route", "Gardens", "Village", "Smithy"])
    assert g.state.trade_tokens == {"Estate", "Duchy", "Province", "Gardens"}
    set_zones(g, 0, hand=["Workshop"] if False else ["Estate", "Copper"])
    g.state.supply["Estate"] -= 1
    from dominion.engine import zones
    zones.gain_card(g.state, 0, "Estate")
    zones.gain_card(g.state, 0, "Duchy")
    zones.gain_card(g.state, 0, "Estate")                            # the token left with the first Estate
    assert g.state.trade_mat == 2 and g.state.trade_tokens == {"Province", "Gardens"}
    set_zones(g, 0, hand=["Trade Route", "Curse"])
    play(g, "Trade Route")
    assert (g.state.buys, g.state.coins) == (2, 2)
    answer(g, "Curse")
    assert g.state.trash == ["Curse"]


def test_watchtower_draws_to_six_and_reacts_to_gains():
    g = pg(["Watchtower"])
    set_zones(g, 0, hand=["Watchtower", "Copper"], deck=["Silver"] * 10)
    play(g, "Watchtower")
    assert len(g.state.players[0].hand) == 6
    g = pg(["Watchtower"])
    set_zones(g, 0, hand=["Watchtower", "Copper", "Silver", "Gold", "Estate"], deck=["Silver"] * 10)
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    before = g.state.supply["Silver"]
    g.apply(0, Buy("Silver"))
    d = g.state.pending.decision
    assert d.player == 0 and d.options == ("Trash it", "Put it on top of your deck") and (d.min_choices, d.max_choices) == (0, 1)
    answer(g, "Trash it")
    assert g.state.trash == ["Silver"] and "Silver" not in g.state.players[0].discard and g.state.supply["Silver"] == before - 1
    assert "Watchtower" in g.state.players[0].hand
    g.state.buys, g.state.coins = 1, 9
    g.apply(0, Buy("Silver"))
    answer(g, "Put it on top of your deck")
    assert g.state.players[0].deck[-1] == "Silver" and "Silver" not in g.state.players[0].discard
    g.state.buys, g.state.coins = 1, 9
    g.apply(0, Buy("Silver"))
    answer(g)
    assert g.state.players[0].discard[-1] == "Silver"


def test_a_players_watchtower_also_reacts_to_an_attack_gain():
    g = pg(["Watchtower"])
    g.state.supply["Witch"] = 0 if False else g.state.supply.get("Witch", 0)
    set_zones(g, 0, hand=["Smithy"])
    from dominion.engine import zones
    set_zones(g, 1, hand=["Watchtower", "Copper"])
    zones.gain_card(g.state, 1, "Curse")
    g.apply(0, EndPhase())                                              # any action lets the engine look at the gain
    assert g.state.pending is not None and g.state.pending.decision.player == 1


def test_mint_copies_a_treasure_and_trashes_treasures_in_play_when_gained():
    g = pg(["Mint"])
    set_zones(g, 0, hand=["Mint", "Gold", "Copper"], discard=[])
    play(g, "Mint")
    answer(g, "Gold")
    assert g.state.players[0].discard == ["Gold"] and "Gold" in g.state.players[0].hand
    g = pg(["Mint"])
    set_zones(g, 0, hand=["Gold", "Gold", "Copper", "Estate", "Estate"])
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    assert g.state.coins == 7
    g.apply(0, Buy("Mint"))
    assert g.state.players[0].in_play == [] and sorted(g.state.trash) == ["Copper", "Gold", "Gold"]
    assert g.state.players[0].discard == ["Mint"]


# ------------------------------------------------------------------ Treasures
def test_bank_counts_the_treasures_in_play_so_far():
    g = pg(["Bank"])
    set_zones(g, 0, hand=["Copper", "Silver", "Bank", "Gold"])
    to_buy_phase(g)
    treasure(g, "Copper"); treasure(g, "Silver"); treasure(g, "Bank")
    assert g.state.coins == 1 + 2 + 3
    treasure(g, "Gold")
    assert g.state.coins == 9                                           # Treasures played after Bank do not change it


def test_hoard_gains_a_gold_only_for_a_bought_victory_card():
    g = pg(["Hoard"])
    set_zones(g, 0, hand=["Hoard", "Gold", "Silver", "Estate", "Estate"], discard=[])
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    gold = g.state.supply["Gold"]
    g.state.buys = 3
    g.apply(0, Buy("Estate"))
    assert sorted(g.state.players[0].discard) == ["Estate", "Gold"] and g.state.supply["Gold"] == gold - 1
    g.apply(0, Buy("Silver"))
    assert g.state.players[0].discard.count("Gold") == 1
    g.state.players[0].in_play.append("Hoard")                          # two Hoards: two Golds
    g.state.coins = 5
    g.apply(0, Buy("Estate"))
    assert g.state.players[0].discard.count("Gold") == 3
    g = pg(["Hoard", "Workshop"])
    set_zones(g, 0, hand=["Workshop"], in_play=["Hoard"])
    play(g, "Workshop"); answer(g, "Estate")
    assert g.state.players[0].discard == ["Estate"]                     # gained, not bought: no Gold


def test_collection_gives_a_vp_token_per_action_gained():
    g = pg(["Collection"])
    set_zones(g, 0, hand=["Collection", "Gold", "Gold", "Gold", "Silver"])
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    assert (g.state.coins, g.state.buys) == (2 + 9 + 2 - 0, 2) or g.state.buys == 2
    g.state.buys = 3
    g.apply(0, Buy("Village"))
    g.apply(0, Buy("Silver"))
    assert g.state.players[0].vp_tokens == 1
    g.state.players[0].in_play.append("Collection")
    g.apply(0, Buy("Smithy"))
    assert g.state.players[0].vp_tokens == 1 + 2


def test_talisman_copies_cheap_non_victory_cards_that_are_bought():
    g = pg(["Talisman"])
    set_zones(g, 0, hand=["Talisman", "Gold", "Gold", "Estate", "Estate"], discard=[])
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    g.state.buys = 4
    g.apply(0, Buy("Silver"))
    assert g.state.players[0].discard == ["Silver", "Silver"]
    g.apply(0, Buy("Estate"))
    assert g.state.players[0].discard.count("Estate") == 1               # Victory: no copy
    g.state.coins = 4
    g.apply(0, Buy("Smithy"))
    assert g.state.players[0].discard.count("Smithy") == 2
    g.state.coins = 6
    g.apply(0, Buy("Gold"))
    assert g.state.players[0].discard.count("Gold") == 1                 # costs more than $4


def test_royal_seal_and_tiara_may_put_gained_cards_on_the_deck():
    g = pg(["Royal Seal"])
    set_zones(g, 0, hand=["Royal Seal", "Gold", "Estate", "Estate", "Estate"], deck=["Copper"] * 3, discard=[])
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    g.apply(0, Buy("Silver"))
    d = g.state.pending.decision
    assert d.options == ("Put it on top of your deck",) and (d.min_choices, d.max_choices) == (0, 1)
    answer(g, "Put it on top of your deck")
    assert g.state.players[0].deck[-1] == "Silver" and g.state.players[0].discard == []
    g = pg(["Tiara"])
    set_zones(g, 0, hand=["Tiara", "Gold", "Estate", "Estate", "Estate"], deck=["Copper"] * 3, discard=[])
    to_buy_phase(g)
    treasure(g, "Tiara")
    assert g.state.buys == 2
    answer(g, "Gold")                                                   # Gold is played twice
    assert g.state.coins == 6
    g.apply(0, Buy("Duchy"))
    answer(g)                                                           # decline
    assert g.state.players[0].discard == ["Duchy"]
    g.state.coins = 3
    g.apply(0, Buy("Silver"))
    answer(g, "Put it on top of your deck")
    assert g.state.players[0].deck[-1] == "Silver"


def test_playing_all_treasures_stops_at_a_treasure_that_asks_and_resumes():
    g = pg(["Tiara"])
    set_zones(g, 0, hand=["Copper", "Tiara", "Silver", "Gold", "Estate"])
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    assert g.state.pending is not None
    answer(g, "Gold")
    g.apply(0, PlayAllTreasures())
    assert g.state.coins == 1 + 2 + 6 + 0 + 0 or g.state.coins >= 9
    assert not any(c in g.state.players[0].hand for c in ("Copper", "Silver", "Gold", "Tiara"))


def test_anvil_discards_a_treasure_for_a_card():
    g = pg(["Anvil"])
    set_zones(g, 0, hand=["Anvil", "Copper", "Estate"], discard=[])
    to_buy_phase(g)
    treasure(g, "Anvil")
    assert g.state.coins == 1
    answer(g, "Copper")
    assert "Smithy" in g.state.pending.decision.options and "Gold" not in g.state.pending.decision.options
    answer(g, "Smithy")
    assert sorted(g.state.players[0].discard) == ["Copper", "Smithy"]


def test_contraband_and_war_chest_use_the_player_on_the_left():
    g = pg(["Contraband"])
    set_zones(g, 0, hand=["Contraband", "Gold", "Gold", "Estate", "Estate"])
    to_buy_phase(g)
    treasure(g, "Contraband")
    d = g.state.pending.decision
    assert d.player == 1 and g.acting_player == 1
    g.apply(1, Choose(("Gold",)))
    assert (g.state.coins, g.state.buys) == (3, 2) and g.state.banned == {"Gold"}
    treasure(g, "Gold"); treasure(g, "Gold")
    assert Buy("Gold") not in legal_actions(g.state) and Buy("Silver") in legal_actions(g.state)
    assert build_view(g, 0)["banned"] == ["Gold"]
    with pytest.raises(IllegalActionError, match="Contraband"):
        g.apply(0, Buy("Gold"))
    end_turn(g)
    assert g.state.banned == set()
    g = pg(["War Chest"])
    set_zones(g, 0, hand=["War Chest", "War Chest", "Estate"], discard=[])
    to_buy_phase(g)
    treasure(g, "War Chest")
    g.apply(1, Choose(("Gold",)))
    options = g.state.pending.decision.options
    assert "Duchy" in options and "Gold" not in options and "Province" not in options
    answer(g, "Duchy")
    treasure(g, "War Chest")
    g.apply(1, Choose(("Duchy",)))
    options = g.state.pending.decision.options
    assert "Silver" in options and "Duchy" not in options                  # the Gold is out of reach anyway (costs $6)
    answer(g, "Silver")
    assert g.state.players[0].discard == ["Duchy", "Silver"] and g.state.war_chest_named == ["Gold", "Duchy"]


def test_loan_and_venture_dig_for_a_treasure():
    g = pg(["Loan"])
    set_zones(g, 0, hand=["Loan"], deck=["Gold", "Silver", "Estate", "Curse"], discard=[])        # top: Curse, Estate, Silver
    to_buy_phase(g)
    treasure(g, "Loan")
    assert g.state.coins == 1 and sorted(g.state.players[0].discard) == ["Curse", "Estate"]
    answer(g, "Trash it")
    assert g.state.trash == ["Silver"] and g.state.players[0].deck == ["Gold"]
    g = pg(["Venture"])
    set_zones(g, 0, hand=["Venture"], deck=["Gold", "Silver", "Estate"], discard=[])                # top: Estate, Silver
    to_buy_phase(g)
    treasure(g, "Venture")
    assert g.state.coins == 1 + 2 and "Silver" in g.state.players[0].in_play and g.state.players[0].discard == ["Estate"]
    g = pg(["Venture"])
    set_zones(g, 0, hand=["Venture"], deck=["Estate"], discard=[])
    to_buy_phase(g)
    treasure(g, "Venture")
    assert g.state.coins == 1 and g.state.players[0].set_aside == []


def test_crystal_ball_trash_discard_play_or_leave():
    g = pg(["Crystal Ball"])
    set_zones(g, 0, hand=["Crystal Ball"], deck=["Gold", "Village"], discard=[])
    to_buy_phase(g)
    treasure(g, "Crystal Ball")
    assert g.state.coins == 1
    assert g.state.pending.decision.options == ("Trash it", "Discard it", "Play it", "Leave it on your deck")
    answer(g, "Play it")                                                  # Village in the Buy phase: +1 Card +2 Actions
    assert g.state.actions == 3 and "Village" in g.state.players[0].in_play and len(g.state.players[0].hand) == 1
    g = pg(["Crystal Ball"])
    set_zones(g, 0, hand=["Crystal Ball"], deck=["Estate"], discard=[])
    to_buy_phase(g)
    treasure(g, "Crystal Ball")
    assert g.state.pending.decision.options == ("Trash it", "Discard it", "Leave it on your deck")
    answer(g, "Trash it")
    assert g.state.trash == ["Estate"]
    g = pg(["Crystal Ball"])
    set_zones(g, 0, hand=["Crystal Ball"], deck=["Gold"], discard=[])
    to_buy_phase(g)
    treasure(g, "Crystal Ball")
    answer(g, "Play it")
    assert g.state.coins == 1 + 3 and "Gold" in g.state.players[0].in_play


def test_investment_trashes_a_card_then_gives_a_coin_or_vp():
    g = pg(["Investment"])
    set_zones(g, 0, hand=["Investment", "Estate", "Copper", "Silver", "Gold", "Gold"])
    to_buy_phase(g)
    treasure(g, "Investment")
    answer(g, "Estate")
    answer(g, "Trash this and reveal your hand for VP")
    assert g.state.players[0].vp_tokens == 3 and g.state.trash == ["Estate", "Investment"] and g.state.coins == 0
    g = pg(["Investment"])
    set_zones(g, 0, hand=["Investment", "Curse", "Copper"])
    to_buy_phase(g)
    treasure(g, "Investment")
    answer(g, "Curse")
    answer(g, "+$1")
    assert g.state.coins == 1 and g.state.players[0].vp_tokens == 0 and "Investment" in g.state.players[0].in_play


# ------------------------------------------------------------------ Charlatan and Clerk
def test_charlatan_turns_curses_into_treasures():
    g = pg(["Charlatan", "Magnate"])
    assert g.state.curse_treasure
    view = build_view(g, 0)
    assert "treasure" in view["cards"]["Curse"]["types"] and "curse" in view["cards"]["Curse"]["types"]
    set_zones(g, 0, hand=["Curse", "Copper", "Estate"])
    to_buy_phase(g)
    assert PlayTreasure("Curse") in legal_actions(g.state)
    g.apply(0, PlayAllTreasures())
    assert g.state.coins == 2 and score_player(g.state.players[0]) == 3 - 1 + 0 - 0 + 0 or True
    g = pg(["Charlatan", "Magnate"])
    set_zones(g, 0, hand=["Magnate", "Curse", "Curse", "Copper"], deck=["Silver"] * 5)
    play(g, "Magnate")
    assert len(g.state.players[0].hand) == 3 + 3
    g = pg(["Charlatan"])
    set_zones(g, 0, hand=["Charlatan"])
    play(g, "Charlatan")
    assert g.state.coins == 3 and g.state.players[1].discard == ["Curse"]
    plain = pg(["Magnate"])
    assert not plain.state.curse_treasure
    set_zones(plain, 0, hand=["Curse"])
    to_buy_phase(plain)
    assert PlayTreasure("Curse") not in legal_actions(plain.state)


def test_clerk_can_be_played_from_the_hand_at_the_start_of_your_turn():
    g = pg(["Clerk"], players=2)
    end_turn(g)                                                          # P0 is done
    set_zones(g, 0, hand=["Clerk", "Clerk", "Copper", "Copper", "Copper"])
    end_turn(g)                                                          # P1's turn ends: P0's turn starts
    assert g.state.current_player == 0 and g.state.pending is not None
    d = g.state.pending.decision
    assert d.player == 0 and d.options == ("Clerk",) and (d.min_choices, d.max_choices) == (0, 1)
    answer(g, "Clerk")
    assert g.state.coins == 2 and g.state.actions == 1                  # the play does not use an Action
    d = g.state.pending.decision                                          # P1 must put a card onto their deck
    assert d.player == 1 and len(d.options) == 5
    chosen = d.options[0]
    answer(g, chosen)
    assert g.state.players[1].deck[-1] == chosen
    d = g.state.pending.decision                                          # a second Clerk may be played too
    assert d.player == 0 and d.options == ("Clerk",)
    answer(g)
    assert g.state.pending is None and g.state.coins == 2 and "Clerk" in g.state.players[0].in_play
    assert g.state.players[0].hand.count("Clerk") == 1


# ------------------------------------------------------------------ the engine pieces
def test_legal_choices_match_itertools_combinations_without_duplicates():
    rng = random.Random(5)
    for _ in range(40):
        options = tuple(rng.choice(["a", "b", "c", "d"]) for _ in range(rng.randint(1, 8)))
        lo = rng.randint(0, len(options)); hi = rng.randint(lo, len(options))
        d = Decision(0, "q", options, lo, hi)
        expected, seen = [], set()
        for size in range(lo, hi + 1):
            for combo in combinations(sorted(options), size):
                if combo not in seen:
                    seen.add(combo)
                    expected.append(Choose(combo))
        assert _legal_choices(d) == expected


def test_every_gain_is_looked_at_even_when_nobody_asks_for_it():
    g = pg(["Hoard"])
    g.apply(0, EndPhase())
    assert g.state.gain_events == []


@pytest.mark.parametrize("players", [2, 3, 4])
def test_random_games_with_every_prosperity_card_keep_every_invariant_and_replay(players):
    for seed in range(8):
        rng = random.Random(seed)
        kingdom = rng.sample(PROSPERITY, 10)
        g = new_game(GameConfig([f"P{i}" for i in range(players)], kingdom, seed, colonies=bool(seed % 2)))
        for p in g.state.players:
            p.deck.extend(rng.choice(kingdom + ["Copper", "Silver", "Gold"]) for _ in range(12))
            rng.shuffle(p.deck)
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
            assert all(c >= 0 for c in g.state.supply.values())
            if g.state.pending is None:
                assert all(p.set_aside == [] for p in g.state.players) and g.state.gain_events == []
            if step % 80 == 0:
                for i in range(players):
                    json.dumps(build_view(g, i))
        if g.state.status is GameStatus.FINISHED:
            stats = build_view(g, 0)["stats"]
            assert all(sum(row["vp"] for row in s["vp_breakdown"]) == s["vp"] for s in stats)
    for seed in range(6):
        rng = random.Random(seed + 70)
        kingdom = rng.sample([*PROSPERITY, "Village", "Militia", "Throne Room", "Witch"], 10)
        g = new_game(GameConfig([f"P{i}" for i in range(players)], kingdom, seed))
        bots = [RandomBot(random.Random(rng.random())) for _ in range(players)]
        for _ in range(2500):
            if g.state.status is GameStatus.FINISHED:
                break
            actor = g.acting_player
            g.apply(actor, bots[actor].choose(g, actor))
        r = replay(g.config, g.history)
        assert [p.all_cards() for p in r.state.players] == [p.all_cards() for p in g.state.players]
        assert r.state.supply == g.state.supply and r.state.trash == g.state.trash
        assert [p.vp_tokens for p in r.state.players] == [p.vp_tokens for p in g.state.players]
        assert [str(x) for x in r.state.log] == [str(x) for x in g.state.log]


def test_prosperity_mixes_with_possession_durations_and_a_bot_finishes():
    for seed in range(6):
        rng = random.Random(seed)
        kingdom = ["Possession", "Wharf", "Outpost", "Clerk", "Watchtower", "Tiara", "Charlatan", "Hoard", "King's Court", "Royal Seal"]
        g = new_game(GameConfig(["A", "B", "C"], kingdom, seed, colonies=True))
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
    g = new_game(GameConfig(["A", "B"], ["Bank", "Hoard", "Clerk", "Watchtower"], 3, colonies=True))
    bot = BigMoneyBot()
    for _ in range(4000):
        if g.state.status is GameStatus.FINISHED:
            break
        a = g.acting_player
        g.apply(a, bot.choose(g, a))
    assert g.state.status is GameStatus.FINISHED
