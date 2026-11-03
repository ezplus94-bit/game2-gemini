"""Hinterlands (2011, first edition): 26 cards, Trader's replacement, Tunnel, Scheme, Fool's Gold, Duchess."""

import random
from collections import Counter

import pytest

from dominion.ai import BigMoneyBot, RandomBot
from dominion.cards import get_card, kingdom_cards
from dominion.engine import (
    Buy, Choose, EndPhase, GameConfig, GameStatus, PlayAction, PlayAllTreasures, PlayTreasure, build_view, new_game, replay,
)
from dominion.engine.costs import card_cost
from dominion.engine.scoring import score_player
from helpers import make_game, set_zones, to_buy_phase, total_cards

SET = "Hinterlands"
HL = kingdom_cards([SET])
FILLER = ["Village", "Smithy", "Militia", "Moat", "Market", "Cellar"]


def hl(cards, players=2, seed=1, **kw):
    return make_game(players=players, kingdom=[*cards, *[f for f in FILLER if f not in cards]][:10], seed=seed, **kw)


def play(g, card):
    g.apply(g.acting_player, PlayAction(card))


def answer(g, *cards):
    g.apply(g.acting_player, Choose(tuple(cards)))


def treasure(g, card):
    g.apply(g.acting_player, PlayTreasure(card))


def buy(g, card):
    g.apply(g.acting_player, Buy(card))


def end_turn(g):
    start = g.state.turn_number
    while g.state.status is GameStatus.ACTIVE and g.state.turn_number == start:
        if g.state.pending is not None:
            g.apply(g.acting_player, Choose(()))
        else:
            g.apply(g.acting_player, EndPhase())


def log(g):
    return "\n".join(map(str, g.state.log))


def me(g, i=0):
    return g.state.players[i]


# ------------------------------------------------------------------ the set
def test_the_set_has_26_cards_with_the_right_costs():
    assert len(HL) == 26 and SET in __import__("dominion.cards", fromlist=["expansions"]).expansions()
    assert {n: get_card(n).cost for n in HL} == {
        "Crossroads": 2, "Duchess": 2, "Fool's Gold": 2,
        "Develop": 3, "Oasis": 3, "Oracle": 3, "Scheme": 3, "Tunnel": 3,
        "Jack of All Trades": 4, "Noble Brigand": 4, "Nomad Camp": 4, "Silk Road": 4, "Spice Merchant": 4, "Trader": 4,
        "Cache": 5, "Cartographer": 5, "Embassy": 5, "Haggler": 5, "Highway": 5, "Ill-Gotten Gains": 5, "Inn": 5,
        "Mandarin": 5, "Margrave": 5, "Stables": 5,
        "Border Village": 6, "Farmland": 6,
    }
    attacks = {n for n in HL if get_card(n).is_type(__import__("dominion.cards", fromlist=["CardType"]).CardType.ATTACK)}
    assert attacks == {"Oracle", "Noble Brigand", "Margrave"}


# ------------------------------------------------------------------ $2
def test_crossroads_draws_per_victory_and_gives_actions_only_the_first_time():
    g = hl(["Crossroads"])
    set_zones(g, hand=["Crossroads", "Crossroads", "Estate", "Estate", "Copper"], deck=["Gold"] * 5)
    play(g, "Crossroads")
    assert len(me(g).hand) == 4 + 2 and g.state.actions == 3        # 1 - 1 + 3
    play(g, "Crossroads")
    assert len(me(g).hand) == 5 + 2 and g.state.actions == 2        # second one: 2 more Victory cards, but no extra Actions


def test_duchess_everyone_may_discard_or_keep_their_top_card():
    g = hl(["Duchess"])
    set_zones(g, 0, hand=["Duchess"], deck=["Estate", "Gold"])
    set_zones(g, 1, deck=["Silver", "Copper"])
    play(g, "Duchess")
    assert g.state.coins == 2 and g.acting_player == 0
    answer(g, "Discard it")                                            # own top card: Gold
    assert me(g).discard == ["Gold"]
    assert g.acting_player == 1
    answer(g, "Put it back")
    assert me(g, 1).deck == ["Silver", "Copper"] and me(g, 1).discard == [] and g.state.pending is None


def test_duchess_lets_you_gain_a_duchess_with_a_duchy_only_when_it_is_in_the_game():
    g = hl(["Duchess"])
    assert g.state.duchess
    set_zones(g, hand=["Gold", "Gold", "Silver"])
    to_buy_phase(g)
    g.state.coins = 5
    buy(g, "Duchy")
    assert g.state.pending is not None
    answer(g, "Gain a Duchess")
    assert "Duchess" in me(g).discard and "Duchy" in me(g).discard and g.state.supply["Duchess"] == 9
    g2 = hl(["Smithy"])
    assert not g2.state.duchess
    to_buy_phase(g2)
    g2.state.coins = 5
    buy(g2, "Duchy")
    assert g2.state.pending is None


def test_fools_gold_is_worth_1_then_4_and_cashes_in_when_another_player_gains_a_province():
    g = hl(["Fool's Gold"])
    set_zones(g, hand=["Fool's Gold", "Fool's Gold", "Fool's Gold"])
    to_buy_phase(g)
    treasure(g, "Fool's Gold")
    assert g.state.coins == 1
    treasure(g, "Fool's Gold")
    treasure(g, "Fool's Gold")
    assert g.state.coins == 9
    # reaction: player 1 buys a Province, player 0 trashes Fool's Gold for a Gold on their deck
    g = hl(["Fool's Gold"])
    end_turn(g)
    set_zones(g, 0, hand=["Fool's Gold", "Copper"])
    set_zones(g, 1, hand=["Gold", "Gold", "Gold"])
    to_buy_phase(g)
    g.state.coins = 8
    buy(g, "Province")
    assert g.acting_player == 0
    answer(g, "Trash Fool's Gold")
    assert me(g, 0).deck[-1] == "Gold" and "Fool's Gold" in g.state.trash and "Fool's Gold" not in me(g, 0).hand


def test_fools_gold_ignores_other_cards_and_can_be_declined():
    g = hl(["Fool's Gold"])
    end_turn(g)
    set_zones(g, 0, hand=["Fool's Gold"])
    to_buy_phase(g)
    g.state.coins = 6
    buy(g, "Gold")
    assert g.state.pending is None                                    # no question: it was not a Province
    g.state.coins = 8
    g.state.buys = 1
    buy(g, "Province")
    answer(g)
    assert "Fool's Gold" in me(g, 0).hand


# ------------------------------------------------------------------ $3
def test_develop_trashes_and_gains_two_cards_on_top_of_the_deck():
    g = hl(["Develop"])
    set_zones(g, hand=["Develop", "Silver"], deck=["Copper"] * 5)       # Silver $3 -> $4 and $2
    play(g, "Develop")
    answer(g, "Silver")
    answer(g, "Smithy")                                                # $4
    answer(g, "Moat")                                                  # $2
    answer(g, "Smithy")                                                # which one on top
    assert me(g).deck[-2:] == ["Moat", "Smithy"] and "Silver" in g.state.trash
    assert g.state.pending is None


def test_develop_with_a_curse_gains_nothing_when_no_card_costs_exactly_one():
    g = hl(["Develop"])
    set_zones(g, hand=["Develop", "Curse"], deck=["Copper"] * 5)
    play(g, "Develop")
    answer(g, "Curse")
    assert g.state.trash == ["Curse"] and g.state.pending is None and me(g).deck == ["Copper"] * 5


def test_oasis_draws_acts_pays_and_discards():
    g = hl(["Oasis"])
    set_zones(g, hand=["Oasis", "Estate"], deck=["Gold", "Silver"])
    play(g, "Oasis")
    assert g.state.actions == 1 and g.state.coins == 1
    answer(g, "Estate")
    assert me(g).hand == ["Silver"] and me(g).discard == ["Estate"]


def test_oracle_the_attacker_decides_for_every_player_including_themselves():
    g = hl(["Oracle"])
    set_zones(g, 0, hand=["Oracle"], deck=["Gold", "Gold", "Copper", "Estate"])
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Silver", "Copper"])
    play(g, "Oracle")
    answer(g, "Put them back")                                         # own: Estate and Copper, put back
    assert g.acting_player == 0
    answer(g, "Estate")                                                # order (top first)
    answer(g, "Discard them")                                          # opponent's
    assert me(g, 1).discard == ["Copper", "Silver"] or sorted(me(g, 1).discard) == ["Copper", "Silver"]
    assert len(me(g).hand) == 2 and g.state.pending is None


def test_oracle_is_blocked_by_moat():
    g = hl(["Oracle"])
    set_zones(g, 0, hand=["Oracle"], deck=["Gold"] * 6)
    set_zones(g, 1, hand=["Moat", "Copper"], deck=["Silver", "Copper"])
    play(g, "Oracle")
    answer(g, "Moat")
    assert g.acting_player == 0
    answer(g, "Discard them")                                          # only the attacker's own cards were revealed
    assert me(g, 1).deck == ["Silver", "Copper"] and g.state.pending is None


def test_scheme_puts_a_chosen_action_back_on_the_deck_at_cleanup():
    g = hl(["Scheme"])
    set_zones(g, hand=["Scheme", "Village", "Copper", "Copper", "Copper"], deck=["Silver"] * 10)
    play(g, "Scheme")
    play(g, "Village")
    to_buy_phase(g)
    g.apply(0, EndPhase())
    assert g.state.pending is not None
    answer(g, "Village")
    assert g.state.pending is None
    assert "Village" in me(g).hand and "Village" not in me(g).discard    # drawn again in the next hand
    assert "Scheme" in me(g).discard


def test_scheme_played_twice_with_throne_room_asks_twice_and_a_decline_discards_normally():
    g = hl(["Scheme", "Throne Room"])
    set_zones(g, hand=["Throne Room", "Scheme", "Village", "Copper", "Copper"], deck=["Silver"] * 10)
    play(g, "Throne Room")
    answer(g, "Scheme")
    play(g, "Village")
    g.apply(0, EndPhase())
    g.apply(0, EndPhase())
    assert g.state.pending is not None
    answer(g)
    assert g.state.pending is not None
    answer(g)
    assert "Village" in me(g).discard and "Scheme" in me(g).discard


def test_tunnel_gains_a_gold_when_discarded_outside_cleanup_but_not_in_cleanup():
    g = hl(["Tunnel"])
    set_zones(g, hand=["Cellar", "Tunnel", "Copper", "Copper", "Copper"], deck=["Silver"] * 5)
    play(g, "Cellar")
    answer(g, "Tunnel")
    assert me(g).discard.count("Gold") == 1 and g.state.supply["Gold"] == 29
    g = hl(["Tunnel"])
    set_zones(g, hand=["Tunnel", "Copper", "Copper", "Copper", "Copper"])
    end_turn(g)
    assert "Gold" not in me(g).discard and g.state.supply["Gold"] == 30


def test_tunnel_triggers_for_attacks_and_deck_discards_and_is_worth_2_vp():
    g = hl(["Tunnel", "Margrave"])
    set_zones(g, 0, hand=["Margrave"], deck=["Gold"] * 5)
    set_zones(g, 1, hand=["Tunnel", "Tunnel", "Tunnel", "Copper"], deck=["Estate"] * 4)
    play(g, "Margrave")
    assert g.acting_player == 1                                        # Tunnel is not a Moat: no Reaction question
    answer(g, "Tunnel", "Tunnel")
    assert me(g, 1).discard.count("Gold") == 2 and g.state.supply["Gold"] == 28
    g = hl(["Tunnel", "Duchess"])
    set_zones(g, 0, hand=["Duchess"], deck=["Gold", "Tunnel"])
    play(g, "Duchess")
    answer(g, "Discard it")
    assert me(g).discard.count("Gold") == 1 and "Tunnel" in me(g).discard
    answer(g, "Put it back")
    assert get_card("Tunnel").vp == 2


def test_jack_of_all_trades_gains_silver_draws_to_five_and_may_trash_a_non_treasure():
    g = hl(["Jack of All Trades"])
    set_zones(g, hand=["Jack of All Trades", "Copper"], deck=["Estate", "Gold", "Gold", "Silver", "Estate"])
    play(g, "Jack of All Trades")
    assert "Silver" in me(g).discard and g.state.supply["Silver"] == 39
    answer(g, "Put it back")
    assert len(me(g).hand) == 5
    answer(g, "Estate")
    assert g.state.trash == ["Estate"] and len(me(g).hand) == 4


def test_noble_brigand_trashes_a_silver_or_gold_and_punishes_the_treasureless():
    g = hl(["Noble Brigand"])
    set_zones(g, 0, hand=["Noble Brigand"])
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Estate", "Gold", "Silver"])      # top = Silver, then Gold
    play(g, "Noble Brigand")
    assert g.state.coins == 1
    answer(g, "Gold")
    assert "Gold" in me(g).discard and "Silver" in me(g, 1).discard and "Gold" not in g.state.trash
    g = hl(["Noble Brigand"])
    set_zones(g, 0, hand=["Noble Brigand"])
    set_zones(g, 1, deck=["Gold", "Estate", "Estate"])
    play(g, "Noble Brigand")
    assert "Copper" in me(g, 1).discard and g.state.pending is None


def test_noble_brigand_also_attacks_when_bought():
    g = hl(["Noble Brigand"])
    set_zones(g, hand=["Copper"] * 5)
    me(g, 1).deck[:] = ["Estate", "Silver", "Silver"]
    to_buy_phase(g)
    g.state.coins = 4
    buy(g, "Noble Brigand")
    assert "Silver" in me(g).discard and g.state.pending is None


def test_nomad_camp_goes_on_the_deck_when_gained():
    g = hl(["Nomad Camp"])
    to_buy_phase(g)
    g.state.coins = 4
    buy(g, "Nomad Camp")
    assert me(g).deck[-1] == "Nomad Camp" and "Nomad Camp" not in me(g).discard
    set_zones(g, hand=["Nomad Camp"])
    g2 = hl(["Nomad Camp"])
    set_zones(g2, hand=["Nomad Camp"])
    play(g2, "Nomad Camp")
    assert g2.state.coins == 2 and g2.state.buys == 2


def test_silk_road_is_worth_one_vp_per_four_victory_cards():
    g = hl(["Silk Road"])
    p = me(g)
    p.deck, p.hand, p.discard = ["Silk Road"] * 2 + ["Estate"] * 8, [], []
    assert score_player(p) == 8 + 10 // 4 * 2 + 0                       # 8 Estates + 2 Silk Roads worth floor(10/4)=2 each
    assert g.state.supply["Silk Road"] == 8                             # a Victory pile


def test_spice_merchant_both_modes():
    g = hl(["Spice Merchant"])
    set_zones(g, hand=["Spice Merchant", "Copper"], deck=["Gold", "Gold"])
    play(g, "Spice Merchant")
    answer(g, "Copper")
    answer(g, "+2 Cards and +1 Action")
    assert len(me(g).hand) == 2 and g.state.actions == 1               # 1 - 1 + 1
    g = hl(["Spice Merchant"])
    set_zones(g, hand=["Spice Merchant", "Copper"])
    play(g, "Spice Merchant")
    answer(g, "Copper")
    answer(g, "+$2 and +1 Buy")
    assert g.state.coins == 2 and g.state.buys == 2


def test_trader_trashes_for_silvers_equal_to_cost():
    g = hl(["Trader"])
    set_zones(g, hand=["Trader", "Gold"])
    play(g, "Trader")
    answer(g, "Gold")
    assert me(g).discard.count("Silver") == 6 and g.state.trash == ["Gold"]


def test_trader_in_hand_replaces_a_gain_with_a_silver():
    g = hl(["Trader"])
    set_zones(g, hand=["Trader", "Gold", "Gold"])
    to_buy_phase(g)
    g.state.coins = 6
    buy(g, "Gold")
    assert g.state.pending is not None
    answer(g, "Reveal Trader")
    assert "Gold" not in me(g).discard and me(g).discard == ["Silver"]
    assert g.state.supply["Gold"] == 30 and g.state.supply["Silver"] == 39


def test_trader_replacement_stops_when_gain_effects_would_fire_and_can_be_declined():
    g = hl(["Trader", "Border Village"])
    set_zones(g, hand=["Trader"])
    to_buy_phase(g)
    g.state.coins = 6
    buy(g, "Border Village")
    answer(g, "Reveal Trader")
    assert g.state.pending is None                                      # no Border Village gain effect
    assert me(g).discard == ["Silver"] and g.state.supply["Border Village"] == 10
    g = hl(["Trader", "Nomad Camp"])
    set_zones(g, hand=["Trader"])
    to_buy_phase(g)
    g.state.coins = 4
    buy(g, "Nomad Camp")
    answer(g)
    assert me(g).deck[-1] == "Nomad Camp"


# ------------------------------------------------------------------ $5
def test_cache_gains_two_coppers():
    g = hl(["Cache"])
    set_zones(g, hand=["Cache", "Gold"])
    to_buy_phase(g)
    treasure(g, "Cache")
    assert g.state.coins == 3
    g.state.coins = 5
    buy(g, "Cache")
    assert me(g).discard.count("Copper") == 2 and "Cache" in me(g).discard


def test_cartographer_discards_some_and_reorders_the_rest():
    g = hl(["Cartographer"])
    set_zones(g, hand=["Cartographer"], deck=["Gold", "Silver", "Estate", "Copper", "Curse"])
    play(g, "Cartographer")
    assert g.state.actions == 1 and me(g).hand == ["Curse"]
    answer(g, "Estate", "Copper")
    answer(g, "Gold")                                                  # Gold goes on top
    assert sorted(me(g).discard) == ["Copper", "Estate"] and me(g).deck == ["Silver", "Gold"]
    assert g.state.pending is None


def test_embassy_draws_five_discards_three_and_hands_out_silvers_when_gained():
    g = hl(["Embassy"])
    set_zones(g, hand=["Embassy", "Estate", "Estate", "Estate"], deck=["Gold"] * 5)
    play(g, "Embassy")
    answer(g, "Estate", "Estate", "Estate")
    assert len(me(g).hand) == 5 and me(g).discard == ["Estate"] * 3
    g = hl(["Embassy"], players=3)
    to_buy_phase(g)
    g.state.coins = 5
    buy(g, "Embassy")
    assert me(g, 1).discard == ["Silver"] and me(g, 2).discard == ["Silver"] and "Silver" not in me(g, 0).discard


def test_haggler_gains_a_cheaper_non_victory_card_for_each_buy():
    g = hl(["Haggler"])
    set_zones(g, hand=["Haggler"])
    play(g, "Haggler")
    to_buy_phase(g)
    g.state.coins = 5
    g.state.buys = 2
    buy(g, "Silver")
    assert "Cellar" in g.state.pending.decision.options and "Silver" not in g.state.pending.decision.options
    answer(g, "Cellar")
    assert "Cellar" in me(g).discard and g.state.pending is None
    buy(g, "Estate")
    options = g.state.pending.decision.options
    assert "Copper" in options and "Estate" not in options and "Duchy" not in options
    answer(g, "Copper")


def test_highway_makes_everything_cheaper_and_stacks():
    g = hl(["Highway"])
    set_zones(g, hand=["Highway", "Highway"], deck=["Copper"] * 5)
    assert card_cost(g.state, "Gold") == 6
    play(g, "Highway")
    assert card_cost(g.state, "Gold") == 5
    g.state.actions += 1
    play(g, "Highway")
    assert card_cost(g.state, "Gold") == 4 and card_cost(g.state, "Copper") == 0
    assert g.state.actions == 2


def test_ill_gotten_gains_copper_to_hand_and_curses_when_gained():
    g = hl(["Ill-Gotten Gains"], players=3)
    set_zones(g, hand=["Ill-Gotten Gains"])
    to_buy_phase(g)
    treasure(g, "Ill-Gotten Gains")
    answer(g, "Gain a Copper")
    assert me(g).hand == ["Copper"] and g.state.coins == 1
    g.state.coins = 5
    buy(g, "Ill-Gotten Gains")
    assert me(g, 1).discard == ["Curse"] and me(g, 2).discard == ["Curse"] and "Curse" not in me(g, 0).discard


def test_inn_discards_two_and_shuffles_chosen_actions_into_the_deck_when_gained():
    g = hl(["Inn"])
    set_zones(g, hand=["Inn", "Estate", "Copper", "Silver"], deck=["Gold"] * 4)
    play(g, "Inn")
    assert g.state.actions == 2 and len(me(g).hand) == 5
    answer(g, "Estate", "Copper")
    assert len(me(g).hand) == 3 and sorted(me(g).discard) == ["Copper", "Estate"]
    g = hl(["Inn"])
    set_zones(g, hand=["Copper"] * 5, discard=["Village", "Smithy", "Estate"], deck=["Gold"] * 3)
    to_buy_phase(g)
    g.state.coins = 5
    buy(g, "Inn")
    assert set(g.state.pending.decision.options) == {"Village", "Smithy", "Inn"}
    answer(g, "Village", "Inn")
    assert "Village" in me(g).deck and "Inn" in me(g).deck and len(me(g).deck) == 5
    assert sorted(me(g).discard) == ["Estate", "Smithy"]


def test_mandarin_puts_a_card_back_and_topdecks_treasures_when_gained():
    g = hl(["Mandarin"])
    set_zones(g, hand=["Mandarin", "Estate"])
    play(g, "Mandarin")
    answer(g, "Estate")
    assert g.state.coins == 3 and me(g).deck[-1] == "Estate"
    g = hl(["Mandarin"])
    set_zones(g, hand=["Gold", "Silver", "Silver", "Copper", "Copper"], deck=["Estate"] * 3)
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    g.state.coins = 5
    buy(g, "Mandarin")
    answer(g, "Gold")
    answer(g, "Copper")
    answer(g, "Copper")                                                # the two Silvers need no question
    assert g.state.pending is None and me(g).in_play == []
    assert me(g).deck[-5:] == ["Gold", "Copper", "Copper", "Silver", "Silver"] and len(me(g).deck) == 3 + 5


def test_margrave_draws_discards_down_to_three_and_gives_a_buy():
    g = hl(["Margrave"])
    set_zones(g, 0, hand=["Margrave"], deck=["Gold"] * 5)
    set_zones(g, 1, hand=["Copper"] * 4, deck=["Silver", "Estate"])
    play(g, "Margrave")
    assert len(me(g).hand) == 3 and g.state.buys == 2
    assert g.acting_player == 1 and len(me(g, 1).hand) == 5
    answer(g, "Copper", "Estate")
    assert len(me(g, 1).hand) == 3 and g.state.pending is None


def test_stables_discard_a_treasure_for_cards_and_an_action():
    g = hl(["Stables"])
    set_zones(g, hand=["Stables", "Copper", "Estate"], deck=["Gold"] * 4)
    play(g, "Stables")
    answer(g, "Copper")
    assert len(me(g).hand) == 1 + 3 and g.state.actions == 1 and me(g).discard == ["Copper"]
    g = hl(["Stables"])
    set_zones(g, hand=["Stables", "Estate"])
    play(g, "Stables")
    assert g.state.pending is None


def test_border_village_gains_a_cheaper_card():
    g = hl(["Border Village"])
    to_buy_phase(g)
    g.state.coins = 6
    buy(g, "Border Village")
    options = g.state.pending.decision.options
    assert "Duchy" in options and "Gold" not in options and "Border Village" not in options
    answer(g, "Duchy")
    assert sorted(me(g).discard) == ["Border Village", "Duchy"]
    g = hl(["Border Village"])
    set_zones(g, hand=["Border Village"], deck=["Gold"] * 2)
    play(g, "Border Village")
    assert g.state.actions == 2 and len(me(g).hand) == 1


def test_farmland_trashes_a_card_and_gains_one_costing_exactly_two_more_but_only_when_bought():
    g = hl(["Farmland"])
    set_zones(g, hand=["Estate", "Copper"])
    to_buy_phase(g)
    g.state.coins = 6
    buy(g, "Farmland")
    answer(g, "Estate")                                                # $2 -> $4
    options = g.state.pending.decision.options
    assert "Smithy" in options and "Gold" not in options and all(card_cost(g.state, o) == 4 for o in options)
    answer(g, "Smithy")
    assert "Estate" in g.state.trash and "Smithy" in me(g).discard and "Farmland" in me(g).discard
    assert score_player(me(g)) == 3 + 2                                 # 3 Estates left after the trash + Farmland's 2 VP
    g = hl(["Farmland"])
    set_zones(g, hand=["Estate"])
    from dominion.engine import zones
    zones.gain_card(g.state, 0, "Farmland")                             # gained, not bought
    g._settle()
    assert g.state.pending is None and "Estate" in me(g).hand


@pytest.mark.parametrize("seed", range(8))
def test_random_games_with_only_hinterlands_conserve_cards_and_replay(seed):
    rng = random.Random(seed)
    players = 2 + seed % 3
    g = new_game(GameConfig([f"P{i}" for i in range(players)], rng.sample(HL, 10), seed))
    total = total_cards(g)
    bots = [RandomBot(random.Random(seed * 10 + i)) for i in range(players)]
    for _ in range(4000):
        if g.state.status is GameStatus.FINISHED:
            break
        p = g.acting_player
        action = bots[p].choose(g, p)
        assert action in g.legal_actions(p)
        g.apply(p, action)
        assert min(g.state.supply.values()) >= 0 and total_cards(g) == total
        if g.state.pending is None:
            assert all(not q.set_aside for q in g.state.players)
    clone = replay(g.config, g.history)
    assert [q.all_cards() for q in clone.state.players] == [q.all_cards() for q in g.state.players]


def test_big_money_finishes_a_hinterlands_game_and_views_build():
    g = new_game(GameConfig(["A", "B"], ["Tunnel", "Farmland", "Silk Road", "Trader", "Highway", "Cache", "Inn", "Oracle", "Duchess", "Crossroads"], 7))
    bots = [BigMoneyBot(), BigMoneyBot()]
    for _ in range(5000):
        if g.state.status is GameStatus.FINISHED:
            break
        p = g.acting_player
        g.apply(p, bots[p].choose(g, p))
        build_view(g, 0)
    assert g.state.status is GameStatus.FINISHED
    assert "Duchess" in g.state.supply


def test_random_kingdom_can_be_limited_to_hinterlands():
    g = new_game(GameConfig(["A", "B"], None, 5, expansions=[SET]))
    assert set(g.state.kingdom) <= set(HL) and len(g.state.kingdom) == 10
