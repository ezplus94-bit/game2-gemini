"""Base-set cards, attacks and reactions."""

import pytest
import random
from dominion.engine import (
    Choose,
    EndPhase,
    IllegalActionError,
    PlayAction,
    PlayAllTreasures,
    score_player,
    PlayTreasure,
    GameConfig,
    GameStatus,
    build_view,
    new_game,
    replay,
)
from helpers import make_game, set_zones, to_buy_phase, total_cards, snapshot
from dominion.ai import BigMoneyBot, RandomBot
from test_bots import play_checked


# ======================================================================
# from test_cards.py
# ======================================================================

def play(game, card):
    game.apply(0, PlayAction(card))


# ----------------------------------------------------------- simple cards
def test_village():
    g = make_game()
    set_zones(g, hand=["Village", "Copper"], deck=["Silver", "Gold"])
    play(g, "Village")
    s = g.state
    assert s.actions == 2                    # 1 - 1 (played) + 2
    assert sorted(s.players[0].hand) == ["Copper", "Gold"]


def test_smithy_draws_three():
    g = make_game()
    set_zones(g, hand=["Smithy"], deck=["Copper"] * 5)
    play(g, "Smithy")
    assert len(g.state.players[0].hand) == 3 and g.state.actions == 0


def test_market():
    g = make_game()
    set_zones(g, hand=["Market"], deck=["Silver"])
    play(g, "Market")
    s = g.state
    assert (s.actions, s.buys, s.coins) == (1, 2, 1)
    assert s.players[0].hand == ["Silver"]


def test_festival():
    g = make_game()
    set_zones(g, hand=["Festival"])
    play(g, "Festival")
    s = g.state
    assert (s.actions, s.buys, s.coins) == (2, 2, 2)


def test_laboratory():
    g = make_game()
    set_zones(g, hand=["Laboratory"], deck=["Gold", "Silver", "Copper"])
    play(g, "Laboratory")
    assert len(g.state.players[0].hand) == 2 and g.state.actions == 1


def test_action_cards_chain_with_extra_actions():
    g = make_game()
    set_zones(g, hand=["Village", "Smithy"], deck=["Copper"] * 6)
    play(g, "Village")
    play(g, "Smithy")
    assert len(g.state.players[0].hand) == 1 + 3      # Village drew 1, Smithy drew 3
    assert g.state.actions == 1


def test_cannot_play_action_with_no_actions_left():
    g = make_game()
    set_zones(g, hand=["Smithy", "Smithy"], deck=["Copper"] * 6)
    play(g, "Smithy")
    with pytest.raises(IllegalActionError):
        play(g, "Smithy")


# ------------------------------------------------------ interactive cards
def test_cellar_discards_then_draws_same_number():
    g = make_game()
    set_zones(g, hand=["Cellar", "Copper", "Estate", "Estate", "Silver"],
              deck=["Copper", "Gold", "Silver"])      # top of deck is the END
    play(g, "Cellar")
    assert g.state.actions == 1                        # +1 Action
    decision = g.state.pending.decision
    assert sorted(decision.options) == ["Copper", "Estate", "Estate", "Silver"]
    assert (decision.min_choices, decision.max_choices) == (0, 4)
    g.apply(0, Choose(("Estate", "Estate")))
    p = g.state.players[0]
    assert g.state.pending is None
    assert p.discard == ["Estate", "Estate"]
    assert sorted(p.hand) == ["Copper", "Gold", "Silver", "Silver"]
    assert p.deck == ["Copper"]


def test_cellar_choosing_nothing_is_allowed():
    g = make_game()
    set_zones(g, hand=["Cellar", "Copper", "Copper"])
    play(g, "Cellar")
    g.apply(0, Choose(()))
    assert g.state.pending is None and len(g.state.players[0].hand) == 2


def test_invalid_answers_are_rejected_and_leave_the_decision_open():
    g = make_game()
    set_zones(g, hand=["Cellar", "Copper", "Estate", "Estate"])
    play(g, "Cellar")
    with pytest.raises(IllegalActionError):
        g.apply(0, Choose(("Gold",)))                          # not in hand
    with pytest.raises(IllegalActionError):
        g.apply(0, Choose(("Estate", "Estate", "Estate")))     # only two Estates
    assert g.state.pending is not None
    g.apply(0, Choose(("Estate",)))                            # a valid answer still works


def test_chapel_trashes_up_to_four():
    g = make_game()
    set_zones(g, hand=["Chapel", "Estate", "Estate", "Estate", "Copper", "Copper"])
    play(g, "Chapel")
    with pytest.raises(IllegalActionError):
        g.apply(0, Choose(("Estate", "Estate", "Estate", "Copper", "Copper")))   # 5 > 4
    g.apply(0, Choose(("Estate", "Estate", "Estate", "Copper")))
    assert sorted(g.state.trash) == ["Copper", "Estate", "Estate", "Estate"]
    assert g.state.players[0].hand == ["Copper"]


def test_workshop_gains_card_costing_up_to_four():
    g = make_game(kingdom=["Workshop", "Village", "Market"])
    set_zones(g, hand=["Workshop"])
    play(g, "Workshop")
    options = g.state.pending.decision.options
    assert "Silver" in options and "Village" in options
    assert "Gold" not in options and "Market" not in options       # cost 6 and 5
    with pytest.raises(IllegalActionError):
        g.apply(0, Choose(("Gold",)))
    g.apply(0, Choose(("Silver",)))
    assert g.state.players[0].discard == ["Silver"] and g.state.supply["Silver"] == 39


def test_workshop_cannot_offer_empty_piles():
    g = make_game(kingdom=["Workshop"], supply_overrides={"Silver": 0})
    set_zones(g, hand=["Workshop"])
    play(g, "Workshop")
    assert "Silver" not in g.state.pending.decision.options


def test_remodel_trash_then_gain_up_to_two_more():
    g = make_game()
    set_zones(g, hand=["Remodel", "Estate", "Copper"])
    play(g, "Remodel")
    g.apply(0, Choose(("Estate",)))                       # cost 2 -> may gain up to $4
    assert g.state.trash == ["Estate"]
    options = g.state.pending.decision.options
    assert "Smithy" in options and "Silver" in options
    assert "Gold" not in options and "Market" not in options
    with pytest.raises(IllegalActionError):
        g.apply(0, Choose(("Gold",)))
    g.apply(0, Choose(("Smithy",)))
    assert g.state.players[0].discard == ["Smithy"] and g.state.pending is None


def test_remodel_gold_into_province():
    g = make_game()
    set_zones(g, hand=["Remodel", "Gold"])
    play(g, "Remodel")
    g.apply(0, Choose(("Gold",)))
    assert "Province" in g.state.pending.decision.options      # $6 + $2 = $8
    g.apply(0, Choose(("Province",)))
    assert g.state.players[0].discard == ["Province"]


def test_remodel_with_empty_hand_does_nothing():
    g = make_game()
    set_zones(g, hand=["Remodel"])
    play(g, "Remodel")
    assert g.state.pending is None


def test_moneylender_trashes_copper_for_three_coins():
    g = make_game()
    set_zones(g, hand=["Moneylender", "Copper", "Copper"])
    play(g, "Moneylender")
    g.apply(0, Choose(("Copper",)))
    assert g.state.coins == 3 and g.state.trash == ["Copper"]
    assert g.state.players[0].hand == ["Copper"]


def test_moneylender_may_decline_and_needs_a_copper():
    g = make_game()
    set_zones(g, hand=["Moneylender", "Copper"])
    play(g, "Moneylender")
    g.apply(0, Choose(()))
    assert g.state.coins == 0 and g.state.trash == []

    g2 = make_game()
    set_zones(g2, hand=["Moneylender", "Estate"])
    play(g2, "Moneylender")
    assert g2.state.pending is None          # no Copper -> no question asked


# ------------------------------------------------------------------ scoring
def test_gardens_scores_per_ten_cards():
    g = make_game()
    set_zones(g, hand=[], deck=["Gardens"] + ["Copper"] * 24, discard=[])     # 25 cards
    assert score_player(g.state.players[0]) == 2
    set_zones(g, deck=["Gardens"] + ["Copper"] * 8)                           # 9 cards
    assert score_player(g.state.players[0]) == 0


def test_victory_points_and_curses():
    g = make_game()
    set_zones(g, hand=["Province", "Duchy", "Estate", "Curse", "Curse"], deck=[], discard=[])
    assert score_player(g.state.players[0]) == 6 + 3 + 1 - 2

# ======================================================================
# from test_cards_more.py
# ======================================================================

NEW = ["Harbinger", "Merchant", "Vassal", "Poacher", "Mine", "Library", "Sentry",
       "Artisan", "Council Room", "Throne Room"]


def game(**kw):
    return make_game(kingdom=kw.pop("kingdom", NEW), **kw)


def play__cards_more(g, card, player=0):
    g.apply(player, PlayAction(card))


def answer(g, *cards, player=0):
    g.apply(player, Choose(tuple(cards)))


# ---------------------------------------------------------------- Harbinger
def test_harbinger_puts_a_discard_on_the_deck():
    g = game()
    set_zones(g, hand=["Harbinger"], deck=["Copper", "Estate"], discard=["Gold", "Silver", "Silver"])
    play__cards_more(g, "Harbinger")
    s, p = g.state, g.state.players[0]
    assert s.actions == 1 and p.hand == ["Estate"]                    # +1 card, +1 action
    assert sorted(s.pending.decision.options) == ["Gold", "Silver"]     # unique names
    answer(g, "Gold")
    assert p.deck[-1] == "Gold" and sorted(p.discard) == ["Silver", "Silver"]


def test_harbinger_may_decline_and_empty_discard_asks_nothing():
    g = game()
    set_zones(g, hand=["Harbinger"], deck=["Copper"] * 3, discard=["Gold"])
    play__cards_more(g, "Harbinger")
    answer(g)
    assert g.state.players[0].discard == ["Gold"]
    g2 = game()
    set_zones(g2, hand=["Harbinger"], deck=["Copper"] * 3, discard=[])
    play__cards_more(g2, "Harbinger")
    assert g2.state.pending is None


# ----------------------------------------------------------------- Merchant
def test_merchant_first_silver_gives_one_coin_only_once():
    g = game()
    set_zones(g, hand=["Merchant", "Silver", "Silver", "Copper"], deck=["Copper"] * 3)
    play__cards_more(g, "Merchant")
    to_buy_phase(g)
    g.apply(0, PlayTreasure("Copper"))
    assert g.state.coins == 1                                      # Copper: no bonus
    g.apply(0, PlayTreasure("Silver"))
    assert g.state.coins == 1 + 2 + 1                              # first Silver: +$1
    g.apply(0, PlayTreasure("Silver"))
    assert g.state.coins == 1 + 2 + 1 + 2                          # second Silver: no bonus


def test_two_merchants_stack_and_bonus_expires_at_end_of_turn():
    g = game()
    set_zones(g, hand=["Merchant", "Merchant", "Silver"], deck=["Estate"] * 6)
    play__cards_more(g, "Merchant")
    play__cards_more(g, "Merchant")
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    assert g.state.coins == 2 + 2                                  # Silver + $1 per Merchant
    g.apply(0, EndPhase())
    assert g.state.triggers == []                                  # nothing carries over


def test_merchant_does_nothing_without_a_silver():
    g = game()
    set_zones(g, hand=["Merchant", "Gold"], deck=["Estate"] * 3)
    play__cards_more(g, "Merchant")
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    assert g.state.coins == 3


# ------------------------------------------------------------------- Vassal
def test_vassal_may_play_a_discarded_action():
    g = game()
    set_zones(g, hand=["Vassal"], deck=["Copper", "Smithy"], discard=[])
    set_zones(g, deck=["Copper", "Copper", "Copper", "Copper", "Smithy"])
    play__cards_more(g, "Vassal")
    assert g.state.coins == 2 and g.state.players[0].discard == ["Smithy"]
    assert g.state.pending.decision.options == ("Smithy",)
    answer(g, "Smithy")
    p = g.state.players[0]
    assert "Smithy" in p.in_play and p.discard == [] and len(p.hand) == 3   # Smithy drew 3
    assert g.state.actions == 0                                     # no Action was spent on Smithy


def test_vassal_declined_or_non_action_or_empty_deck():
    g = game()
    set_zones(g, hand=["Vassal"], deck=["Copper", "Smithy"])
    play__cards_more(g, "Vassal")
    answer(g)
    assert g.state.players[0].discard == ["Smithy"] and g.state.pending is None

    g2 = game()
    set_zones(g2, hand=["Vassal"], deck=["Gold"])
    play__cards_more(g2, "Vassal")
    assert g2.state.pending is None and g2.state.players[0].discard == ["Gold"]

    g3 = game()
    set_zones(g3, hand=["Vassal"], deck=[], discard=[])
    play__cards_more(g3, "Vassal")
    assert g3.state.pending is None and g3.state.coins == 2


# ------------------------------------------------------------------ Poacher
def test_poacher_discards_one_card_per_empty_pile():
    g = game(supply_overrides={"Curse": 0})
    set_zones(g, hand=["Poacher", "Copper", "Estate", "Gold"], deck=["Silver"])
    play__cards_more(g, "Poacher")
    s = g.state
    assert (s.actions, s.coins) == (1, 1)
    assert s.pending.decision.min_choices == s.pending.decision.max_choices == 1
    with pytest.raises(IllegalActionError):
        answer(g, "Copper", "Estate")                              # exactly one
    answer(g, "Estate")
    assert g.state.players[0].discard == ["Estate"]


def test_poacher_with_no_empty_piles_or_tiny_hand():
    g = game()
    set_zones(g, hand=["Poacher", "Copper"], deck=["Silver"])
    play__cards_more(g, "Poacher")
    assert g.state.pending is None and len(g.state.players[0].discard) == 0

    g2 = game(supply_overrides={"Curse": 0, "Duchy": 0})
    set_zones(g2, hand=["Poacher", "Copper"], deck=["Silver"])
    play__cards_more(g2, "Poacher")                                            # 2 empty piles, 2 cards: discard all
    assert g2.state.pending is None and g2.state.players[0].hand == []
    assert sorted(g2.state.players[0].discard) == ["Copper", "Silver"]


# --------------------------------------------------------------------- Mine
def test_mine_upgrades_a_treasure_into_the_hand():
    g = game()
    set_zones(g, hand=["Mine", "Copper", "Silver", "Estate"])
    play__cards_more(g, "Mine")
    assert sorted(g.state.pending.decision.options) == ["Copper", "Silver"]
    answer(g, "Copper")                                            # up to $0 + $3
    options = g.state.pending.decision.options
    assert "Silver" in options and "Gold" not in options and "Copper" in options
    answer(g, "Silver")
    assert "Silver" in g.state.players[0].hand and g.state.trash == ["Copper"]


def test_mine_silver_to_gold_and_declining_and_no_treasure():
    g = game()
    set_zones(g, hand=["Mine", "Silver"])
    play__cards_more(g, "Mine")
    answer(g, "Silver")
    answer(g, "Gold")
    assert g.state.players[0].hand == ["Gold"]

    g2 = game()
    set_zones(g2, hand=["Mine", "Silver"])
    play__cards_more(g2, "Mine")
    answer(g2)
    assert g2.state.trash == [] and g2.state.pending is None

    g3 = game()
    set_zones(g3, hand=["Mine", "Estate"])
    play__cards_more(g3, "Mine")
    assert g3.state.pending is None


# ------------------------------------------------------------------ Library
def test_library_draws_to_seven_and_can_set_aside_actions():
    g = game()
    set_zones(g, hand=["Library", "Copper", "Copper"],
              deck=["Copper"] * 4 + ["Village", "Gold", "Silver"], discard=[])
    # hand after playing: 2 cards. Draw order (top = end): Silver, Gold, Village, Copper...
    play__cards_more(g, "Library")
    d = g.state.pending.decision
    assert d.options == ("Village",) and (d.min_choices, d.max_choices) == (0, 1)
    answer(g, "Village")                                           # set it aside
    p = g.state
    assert p.pending is None
    me = p.players[0]
    assert len(me.hand) == 7 and "Village" not in me.hand
    assert "Village" in me.discard and me.set_aside == []         # discarded afterwards


def test_library_keeping_an_action_and_edge_cases():
    g = game()
    set_zones(g, hand=["Library"], deck=["Copper"] * 5 + ["Village"], discard=[])
    play__cards_more(g, "Library")
    answer(g)                                                      # keep Village
    assert len(g.state.players[0].hand) == 6 and "Village" in g.state.players[0].hand
    # the deck only had 6 cards, so Library drew them all and stopped
    g2 = game()
    set_zones(g2, hand=["Library"] + ["Copper"] * 7, deck=["Gold"] * 3)
    play__cards_more(g2, "Library")
    assert len(g2.state.players[0].hand) == 7 and g2.state.pending is None   # already 7: draws nothing


def test_library_set_aside_cards_are_not_redrawn():
    g = game()
    set_zones(g, hand=["Library"], deck=["Village", "Village", "Copper"], discard=[])
    play__cards_more(g, "Library")
    # set aside every Action it offers
    while g.state.pending:
        answer(g, "Village")
    me = g.state.players[0]
    assert me.hand == ["Copper"] and sorted(me.discard) == ["Village", "Village"]


# ------------------------------------------------------------------- Sentry
def test_sentry_trash_discard_and_reorder():
    g = game()
    set_zones(g, hand=["Sentry"], deck=["Gold", "Estate", "Curse", "Silver"], discard=[])
    # +1 card draws Silver; top two now: Curse (top), Estate
    play__cards_more(g, "Sentry")
    me = g.state.players[0]
    assert me.hand == ["Silver"] and me.set_aside == ["Curse", "Estate"]
    assert g.state.pending.decision.options == ("Curse", "Estate")
    answer(g, "Curse")                                             # trash Curse
    assert g.state.trash == ["Curse"]
    answer(g)                                                      # discard nothing
    assert me.deck == ["Gold", "Estate"] and me.set_aside == []    # Estate back on top, no order question
    assert g.state.pending is None


def test_sentry_keep_both_and_choose_order():
    g = game()
    set_zones(g, hand=["Sentry"], deck=["Gold", "Estate", "Silver", "Copper"], discard=[])
    play__cards_more(g, "Sentry")                                              # draws Copper; looks at Silver, Estate
    answer(g)                                                      # trash none
    answer(g)                                                      # discard none
    assert g.state.pending.decision.options == ("Silver", "Estate")
    answer(g, "Estate")                                            # Estate on top
    assert g.state.players[0].deck == ["Gold", "Silver", "Estate"]


def test_sentry_discard_both_and_short_deck():
    g = game()
    set_zones(g, hand=["Sentry"], deck=["Gold", "Estate", "Copper"], discard=[])
    play__cards_more(g, "Sentry")
    answer(g)
    answer(g, "Gold", "Estate")
    assert sorted(g.state.players[0].discard) == ["Estate", "Gold"]

    g2 = game()
    set_zones(g2, hand=["Sentry"], deck=[], discard=[])
    play__cards_more(g2, "Sentry")
    assert g2.state.pending is None


def test_sentry_does_not_ask_about_order_for_identical_cards():
    g = game()
    set_zones(g, hand=["Sentry"], deck=["Silver", "Silver", "Copper"], discard=[])
    play__cards_more(g, "Sentry")
    answer(g)
    answer(g)
    assert g.state.pending is None and g.state.players[0].deck == ["Silver", "Silver"]


# ------------------------------------------------------------------ Artisan
def test_artisan_gains_to_hand_then_puts_a_card_on_the_deck():
    g = game()
    set_zones(g, hand=["Artisan", "Copper", "Estate"], deck=["Silver"])
    play__cards_more(g, "Artisan")
    options = g.state.pending.decision.options
    assert "Mine" in options and "Gold" not in options and "Artisan" not in options   # costs 5 / 6 / 6
    answer(g, "Mine")
    assert "Mine" in g.state.players[0].hand
    answer(g, "Estate")
    me = g.state.players[0]
    assert me.deck[-1] == "Estate" and "Estate" not in me.hand


# -------------------------------------------------------------- Council Room
@pytest.mark.parametrize("players", [2, 3])
def test_council_room_everyone_else_draws_one(players):
    g = game(players=players)
    set_zones(g, hand=["Council Room"], deck=["Copper"] * 8)
    before = [len(p.hand) for p in g.state.players]
    play__cards_more(g, "Council Room")
    s = g.state
    assert len(s.players[0].hand) == 4 and s.buys == 2
    assert [len(p.hand) for p in s.players[1:]] == [b + 1 for b in before[1:]]


# -------------------------------------------------------------- Throne Room
def test_throne_room_plays_an_action_twice_without_spending_actions():
    g = game()
    set_zones(g, hand=["Throne Room", "Council Room"], deck=["Copper"] * 12)
    play__cards_more(g, "Throne Room")
    assert g.state.pending.decision.options == ("Council Room",)
    answer(g, "Council Room")
    s = g.state
    assert s.pending is None and s.buys == 3 and len(s.players[0].hand) == 8
    assert sorted(s.players[0].in_play) == ["Council Room", "Throne Room"]


def test_throne_room_with_questions_inside_and_declining():
    g = game()
    set_zones(g, hand=["Throne Room", "Harbinger"], deck=["Copper"] * 4, discard=["Gold", "Silver"])
    play__cards_more(g, "Throne Room")
    answer(g, "Harbinger")
    d1 = g.state.pending.decision                                   # first Harbinger asks
    assert d1.source == "Harbinger"
    answer(g, "Gold")
    d2 = g.state.pending.decision                                   # second Harbinger asks again
    assert d2.options == ("Silver",)
    answer(g, "Silver")
    assert g.state.pending is None and g.state.actions == 2          # 1 - 1 + (+1 +1)

    g2 = game()
    set_zones(g2, hand=["Throne Room", "Village"])
    play__cards_more(g2, "Throne Room")
    answer(g2)
    assert g2.state.pending is None and g2.state.actions == 0 and "Village" in g2.state.players[0].hand


def test_throne_room_needs_an_action_and_can_chain():
    g = game()
    set_zones(g, hand=["Throne Room", "Copper"])
    play__cards_more(g, "Throne Room")
    assert g.state.pending is None

    g2 = game()
    set_zones(g2, hand=["Throne Room", "Throne Room", "Council Room", "Merchant"], deck=["Copper"] * 30)
    cards_before = total_cards(g2)
    play__cards_more(g2, "Throne Room")
    answer(g2, "Throne Room")                                       # the second one is played twice...
    answer(g2, "Council Room")                                      # ...once with Council Room (x2)
    answer(g2, "Merchant")                                          # ...and once with Merchant (x2)
    s = g2.state
    assert s.pending is None and s.buys == 3 and len(s.triggers) == 2
    assert sorted(s.players[0].in_play) == ["Council Room", "Merchant", "Throne Room", "Throne Room"]
    assert total_cards(g2) == cards_before                          # nothing created or lost


def test_merchant_via_throne_room_gives_two_coins():
    g = game()
    set_zones(g, hand=["Throne Room", "Merchant", "Silver"], deck=["Estate"] * 5)
    play__cards_more(g, "Throne Room")
    answer(g, "Merchant")
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    assert g.state.coins == 2 + 2

# ======================================================================
# from test_attacks.py
# ======================================================================

ATTACKS = ["Militia", "Witch", "Moat", "Bandit", "Throne Room"]


def game__attacks(players=3, **kw):
    return make_game(players=players, kingdom=kw.pop("kingdom", ATTACKS), **kw)


def play__attacks(g, card, player=0):
    g.apply(player, PlayAction(card))


def answer__attacks(g, player, *cards):
    g.apply(player, Choose(tuple(cards)))


# ------------------------------------------------------------------- Moat
def test_moat_draws_two_when_played():
    g = game__attacks()
    set_zones(g, hand=["Moat"], deck=["Copper"] * 4)
    play__attacks(g, "Moat")
    assert len(g.state.players[0].hand) == 2


# ----------------------------------------------------------------- Militia
def test_militia_makes_each_other_player_discard_down_to_three_in_turn_order():
    g = game__attacks()
    set_zones(g, 0, hand=["Militia"])
    set_zones(g, 1, hand=["Copper"] * 5)
    set_zones(g, 2, hand=["Estate", "Estate", "Estate", "Gold", "Silver"])
    play__attacks(g, "Militia")
    s = g.state
    assert s.coins == 2 and g.acting_player == 1
    d = s.pending.decision
    assert (d.player, d.min_choices, d.max_choices) == (1, 2, 2)
    assert g.legal_actions(player=0) == []                    # the attacker has to wait
    with pytest.raises(IllegalActionError):
        answer__attacks(g, 1, "Copper")                                # must discard exactly 2
    with pytest.raises(IllegalActionError):
        answer__attacks(g, 2, "Estate", "Estate")                      # not player 2's decision yet
    answer__attacks(g, 1, "Copper", "Copper")
    assert g.acting_player == 2
    answer__attacks(g, 2, "Estate", "Estate")
    assert s.pending is None
    assert [len(p.hand) for p in s.players] == [0, 3, 3]
    assert sorted(s.players[2].hand) == ["Estate", "Gold", "Silver"]


def test_militia_skips_players_with_three_or_fewer_cards():
    g = game__attacks()
    set_zones(g, 0, hand=["Militia"])
    set_zones(g, 1, hand=["Copper"] * 3)
    set_zones(g, 2, hand=["Copper", "Copper"])
    play__attacks(g, "Militia")
    assert g.state.pending is None and len(g.state.players[1].hand) == 3


def test_attack_decisions_are_private_to_the_defender():
    g = game__attacks()
    set_zones(g, 0, hand=["Militia"])
    set_zones(g, 1, hand=["Gold", "Gold", "Silver", "Copper", "Copper"])
    play__attacks(g, "Militia")
    defender, attacker, bystander = build_view(g, 1), build_view(g, 0), build_view(g, 2)
    assert sorted(defender["pending"]["options"]) == ["Copper", "Copper", "Gold", "Gold", "Silver"]
    assert defender["pending"]["source"] == "Militia"
    assert attacker["pending"] == {"player": 1, "source": "Militia"}
    assert bystander["pending"] == {"player": 1, "source": "Militia"}


# -------------------------------------------------------------- Moat vs attacks
def test_revealing_moat_makes_you_unaffected_and_others_still_discard():
    g = game__attacks()
    set_zones(g, 0, hand=["Militia"])
    set_zones(g, 1, hand=["Moat", "Copper", "Copper", "Copper", "Copper"])
    set_zones(g, 2, hand=["Copper"] * 5)
    play__attacks(g, "Militia")
    d = g.state.pending.decision
    assert d.player == 1 and d.options == ("Moat",) and (d.min_choices, d.max_choices) == (0, 1)
    answer__attacks(g, 1, "Moat")
    assert g.acting_player == 2                                # player 1 is skipped
    answer__attacks(g, 2, "Copper", "Copper")
    assert len(g.state.players[1].hand) == 5 and len(g.state.players[2].hand) == 3
    assert any("reveals Moat" in line for line in g.state.log)


def test_declining_to_reveal_moat_means_the_attack_hits():
    g = game__attacks()
    set_zones(g, 0, hand=["Militia"])
    set_zones(g, 1, hand=["Moat", "Copper", "Copper", "Copper", "Copper"])
    set_zones(g, 2, hand=["Copper"] * 3)
    play__attacks(g, "Militia")
    answer__attacks(g, 1)                                               # do not reveal
    assert g.state.pending.decision.player == 1 and g.state.pending.decision.max_choices == 2
    answer__attacks(g, 1, "Moat", "Copper")
    assert len(g.state.players[1].hand) == 3


def test_all_reactions_are_asked_before_any_attack_effect():
    g = game__attacks()
    set_zones(g, 0, hand=["Militia"])
    set_zones(g, 1, hand=["Moat", "Copper", "Copper", "Copper", "Copper"])
    set_zones(g, 2, hand=["Moat", "Copper", "Copper", "Copper", "Copper"])
    play__attacks(g, "Militia")
    answer__attacks(g, 1)                                               # player 1 declines...
    d = g.state.pending.decision                               # ...and player 2 is asked about Moat next,
    assert d.player == 2 and d.options == ("Moat",)            # not player 1 about discarding
    answer__attacks(g, 2, "Moat")
    assert g.state.pending.decision.player == 1                # now the discards begin
    assert g.state.pending.decision.max_choices == 2


def test_players_without_a_reaction_are_never_asked_about_one():
    g = game__attacks()
    set_zones(g, 0, hand=["Witch"], deck=["Copper"] * 3)
    set_zones(g, 1, hand=["Copper"] * 5)
    play__attacks(g, "Witch")
    assert g.state.pending is None


# -------------------------------------------------------------------- Witch
def test_witch_draws_two_and_gives_each_other_player_a_curse():
    g = game__attacks()
    set_zones(g, 0, hand=["Witch"], deck=["Copper"] * 4)
    before = g.state.supply["Curse"]
    play__attacks(g, "Witch")
    s = g.state
    assert len(s.players[0].hand) == 2
    assert s.players[1].discard == ["Curse"] and s.players[2].discard == ["Curse"]
    assert s.players[0].discard == [] and s.supply["Curse"] == before - 2


def test_witch_blocked_by_moat_and_with_empty_curse_pile():
    g = game__attacks()
    set_zones(g, 0, hand=["Witch"], deck=["Copper"] * 4)
    set_zones(g, 1, hand=["Moat", "Copper"])
    play__attacks(g, "Witch")
    answer__attacks(g, 1, "Moat")
    assert g.state.players[1].discard == [] and g.state.players[2].discard == ["Curse"]

    g2 = game__attacks(supply_overrides={"Curse": 1})
    set_zones(g2, 0, hand=["Witch"], deck=["Copper"] * 4)
    play__attacks(g2, "Witch")
    assert g2.state.players[1].discard == ["Curse"] and g2.state.players[2].discard == []
    assert g2.state.supply["Curse"] == 0


# ------------------------------------------------------------------- Bandit
def bandit(top_two, **kw):
    """Player 1's deck has these two cards on top (first = top). Returns the game."""
    g = game__attacks(**kw)
    set_zones(g, 0, hand=["Bandit"])
    set_zones(g, 1, hand=["Estate"], deck=["Curse", *reversed(top_two)], discard=[])
    set_zones(g, 2, hand=["Estate"], deck=["Curse"] * 3, discard=[])
    play__attacks(g, "Bandit")
    return g


def test_bandit_gains_gold_and_victim_chooses_between_two_treasures():
    g = bandit(["Silver", "Gold"])
    s = g.state
    assert s.players[0].discard == ["Gold"] and s.supply["Gold"] == 29
    d = s.pending.decision
    assert d.player == 1 and d.options == ("Gold", "Silver") and d.min_choices == 1
    answer__attacks(g, 1, "Silver")                                      # defender trashes the Silver
    assert s.trash == ["Silver"] and s.players[1].discard == ["Gold"]
    assert s.players[1].set_aside == [] and s.pending is None   # player 2 only had Curses


def test_bandit_forced_and_unforced_cases():
    g = bandit(["Copper", "Silver"])                            # only Silver is eligible: no question
    assert g.state.pending is None and g.state.trash == ["Silver"]
    assert g.state.players[1].discard == ["Copper"]

    g2 = bandit(["Copper", "Estate"])                           # nothing eligible: both discarded
    assert g2.state.trash == [] and sorted(g2.state.players[1].discard) == ["Copper", "Estate"]

    g3 = bandit(["Silver", "Silver"])                           # identical: trash one, no question
    assert g3.state.pending is None and g3.state.trash == ["Silver"]
    assert g3.state.players[1].discard == ["Silver"]


def test_bandit_with_short_deck_reshuffles_and_respects_moat():
    g = game__attacks()
    set_zones(g, 0, hand=["Bandit"])
    set_zones(g, 1, hand=["Estate"], deck=["Silver"], discard=["Estate", "Copper"])
    set_zones(g, 2, hand=["Estate"], deck=[], discard=[])
    before = total_cards(g)
    play__attacks(g, "Bandit")
    assert total_cards(g) == before                             # cards move around, none appear or vanish
    assert g.state.players[1].set_aside == [] and g.state.pending is None

    g2 = game__attacks()
    set_zones(g2, 0, hand=["Bandit"])
    set_zones(g2, 1, hand=["Moat"], deck=["Gold", "Silver"])
    set_zones(g2, 2, hand=["Estate"], deck=["Copper", "Estate"])
    play__attacks(g2, "Bandit")
    answer__attacks(g2, 1, "Moat")
    assert g2.state.players[1].deck == ["Gold", "Silver"]       # untouched


# ------------------------------------------------------------- Throne Room
def test_throne_room_witch_attacks_twice_and_moat_is_asked_each_time():
    g = game__attacks()
    set_zones(g, 0, hand=["Throne Room", "Witch"], deck=["Copper"] * 6)
    set_zones(g, 1, hand=["Moat", "Copper"])
    play__attacks(g, "Throne Room")
    answer__attacks(g, 0, "Witch")
    answer__attacks(g, 1, "Moat")                                        # first attack: reveal Moat
    assert g.acting_player == 1                                 # second attack: asked again
    answer__attacks(g, 1)                                                # decline this time
    assert g.state.players[1].discard == ["Curse"]
    assert g.state.players[2].discard == ["Curse", "Curse"]


# ------------------------------------------------------------ self-play fuzz
ATTACK_KINGDOM = ["Militia", "Witch", "Moat", "Bandit", "Throne Room", "Library", "Sentry",
                  "Council Room", "Harbinger", "Vassal"]


@pytest.mark.parametrize("seed", range(20))
def test_random_games_with_every_attack_keep_all_invariants(seed):
    players = 2 + seed % 3
    g = new_game(GameConfig([f"P{i}" for i in range(players)], ATTACK_KINGDOM, seed))
    play_checked(g, [RandomBot(random.Random(seed * 11 + i)) for i in range(players)])
    assert g.state.status is GameStatus.FINISHED
    assert snapshot(replay(g.config, g.history)) == snapshot(g)


@pytest.mark.parametrize("seed", range(8))
def test_big_money_bots_answer_attacks_legally(seed):
    g = new_game(GameConfig(["Wild", "Money1", "Money2"], ATTACK_KINGDOM, seed))
    play_checked(g, [RandomBot(random.Random(seed)), BigMoneyBot(), BigMoneyBot()])
    assert g.state.status is GameStatus.FINISHED


# --------------------------------------------------------------- Bureaucrat
def bureaucrat_game(defender_hand, players=2):
    g = game__attacks(players=players, kingdom=["Bureaucrat", "Moat"])
    set_zones(g, 0, hand=["Bureaucrat"], deck=["Copper"] * 3)
    set_zones(g, 1, hand=defender_hand, deck=["Gold"] * 3)
    return g


def test_bureaucrat_gains_silver_onto_deck_and_forces_one_victory_card_back():
    g = bureaucrat_game(["Estate", "Estate", "Copper", "Copper", "Gold"])
    play__attacks(g, "Bureaucrat")
    me, them = g.state.players[0], g.state.players[1]
    assert me.deck[-1] == "Silver" and g.state.supply["Silver"] == 39      # Silver is on TOP of the deck
    assert them.deck[-1] == "Estate" and them.hand.count("Estate") == 1    # one copy, no question needed
    assert g.state.pending is None
    assert any("reveals Estate" in line for line in g.state.log)


def test_bureaucrat_defender_chooses_between_different_victory_cards():
    g = bureaucrat_game(["Estate", "Province", "Copper", "Copper", "Gold"])
    play__attacks(g, "Bureaucrat")
    d = g.state.pending.decision
    assert d.player == 1 and d.options == ("Estate", "Province") and (d.min_choices, d.max_choices) == (1, 1)
    answer__attacks(g, 1, "Province")
    assert g.state.players[1].deck[-1] == "Province" and "Province" not in g.state.players[1].hand


def test_bureaucrat_no_victory_cards_reveals_hand_and_curse_does_not_count():
    g = bureaucrat_game(["Curse", "Copper", "Copper", "Gold", "Silver"])
    play__attacks(g, "Bureaucrat")
    them = g.state.players[1]
    assert len(them.hand) == 5 and them.deck == ["Gold"] * 3
    assert any("no Victory cards" in line and "Curse" in line for line in g.state.log)


def test_bureaucrat_moat_still_lets_attacker_gain_silver():
    g = bureaucrat_game(["Moat", "Estate", "Copper", "Copper", "Gold"])
    play__attacks(g, "Bureaucrat")
    answer__attacks(g, 1, "Moat")
    assert g.state.players[1].deck == ["Gold"] * 3 and g.state.players[0].deck[-1] == "Silver"
