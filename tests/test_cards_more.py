import pytest

from dominion.engine import (
    Choose, EndPhase, IllegalActionError, PlayAction, PlayAllTreasures, PlayTreasure,
)
from helpers import make_game, set_zones, to_buy_phase, total_cards

NEW = ["Harbinger", "Merchant", "Vassal", "Poacher", "Mine", "Library", "Sentry",
       "Artisan", "Council Room", "Throne Room"]


def game(**kw):
    return make_game(kingdom=kw.pop("kingdom", NEW), **kw)


def play(g, card, player=0):
    g.apply(player, PlayAction(card))


def answer(g, *cards, player=0):
    g.apply(player, Choose(tuple(cards)))


# ---------------------------------------------------------------- Harbinger
def test_harbinger_puts_a_discard_on_the_deck():
    g = game()
    set_zones(g, hand=["Harbinger"], deck=["Copper", "Estate"], discard=["Gold", "Silver", "Silver"])
    play(g, "Harbinger")
    s, p = g.state, g.state.players[0]
    assert s.actions == 1 and p.hand == ["Estate"]                    # +1 card, +1 action
    assert sorted(s.pending.decision.options) == ["Gold", "Silver"]     # unique names
    answer(g, "Gold")
    assert p.deck[-1] == "Gold" and sorted(p.discard) == ["Silver", "Silver"]


def test_harbinger_may_decline_and_empty_discard_asks_nothing():
    g = game()
    set_zones(g, hand=["Harbinger"], deck=["Copper"] * 3, discard=["Gold"])
    play(g, "Harbinger")
    answer(g)
    assert g.state.players[0].discard == ["Gold"]
    g2 = game()
    set_zones(g2, hand=["Harbinger"], deck=["Copper"] * 3, discard=[])
    play(g2, "Harbinger")
    assert g2.state.pending is None


# ----------------------------------------------------------------- Merchant
def test_merchant_first_silver_gives_one_coin_only_once():
    g = game()
    set_zones(g, hand=["Merchant", "Silver", "Silver", "Copper"], deck=["Copper"] * 3)
    play(g, "Merchant")
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
    play(g, "Merchant")
    play(g, "Merchant")
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    assert g.state.coins == 2 + 2                                  # Silver + $1 per Merchant
    g.apply(0, EndPhase())
    assert g.state.triggers == []                                  # nothing carries over


def test_merchant_does_nothing_without_a_silver():
    g = game()
    set_zones(g, hand=["Merchant", "Gold"], deck=["Estate"] * 3)
    play(g, "Merchant")
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    assert g.state.coins == 3


# ------------------------------------------------------------------- Vassal
def test_vassal_may_play_a_discarded_action():
    g = game()
    set_zones(g, hand=["Vassal"], deck=["Copper", "Smithy"], discard=[])
    set_zones(g, deck=["Copper", "Copper", "Copper", "Copper", "Smithy"])
    play(g, "Vassal")
    assert g.state.coins == 2 and g.state.players[0].discard == ["Smithy"]
    assert g.state.pending.decision.options == ("Smithy",)
    answer(g, "Smithy")
    p = g.state.players[0]
    assert "Smithy" in p.in_play and p.discard == [] and len(p.hand) == 3   # Smithy drew 3
    assert g.state.actions == 0                                     # no Action was spent on Smithy


def test_vassal_declined_or_non_action_or_empty_deck():
    g = game()
    set_zones(g, hand=["Vassal"], deck=["Copper", "Smithy"])
    play(g, "Vassal")
    answer(g)
    assert g.state.players[0].discard == ["Smithy"] and g.state.pending is None

    g2 = game()
    set_zones(g2, hand=["Vassal"], deck=["Gold"])
    play(g2, "Vassal")
    assert g2.state.pending is None and g2.state.players[0].discard == ["Gold"]

    g3 = game()
    set_zones(g3, hand=["Vassal"], deck=[], discard=[])
    play(g3, "Vassal")
    assert g3.state.pending is None and g3.state.coins == 2


# ------------------------------------------------------------------ Poacher
def test_poacher_discards_one_card_per_empty_pile():
    g = game(supply_overrides={"Curse": 0})
    set_zones(g, hand=["Poacher", "Copper", "Estate", "Gold"], deck=["Silver"])
    play(g, "Poacher")
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
    play(g, "Poacher")
    assert g.state.pending is None and len(g.state.players[0].discard) == 0

    g2 = game(supply_overrides={"Curse": 0, "Duchy": 0})
    set_zones(g2, hand=["Poacher", "Copper"], deck=["Silver"])
    play(g2, "Poacher")                                            # 2 empty piles, 2 cards: discard all
    assert g2.state.pending is None and g2.state.players[0].hand == []
    assert sorted(g2.state.players[0].discard) == ["Copper", "Silver"]


# --------------------------------------------------------------------- Mine
def test_mine_upgrades_a_treasure_into_the_hand():
    g = game()
    set_zones(g, hand=["Mine", "Copper", "Silver", "Estate"])
    play(g, "Mine")
    assert sorted(g.state.pending.decision.options) == ["Copper", "Silver"]
    answer(g, "Copper")                                            # up to $0 + $3
    options = g.state.pending.decision.options
    assert "Silver" in options and "Gold" not in options and "Copper" in options
    answer(g, "Silver")
    assert "Silver" in g.state.players[0].hand and g.state.trash == ["Copper"]


def test_mine_silver_to_gold_and_declining_and_no_treasure():
    g = game()
    set_zones(g, hand=["Mine", "Silver"])
    play(g, "Mine")
    answer(g, "Silver")
    answer(g, "Gold")
    assert g.state.players[0].hand == ["Gold"]

    g2 = game()
    set_zones(g2, hand=["Mine", "Silver"])
    play(g2, "Mine")
    answer(g2)
    assert g2.state.trash == [] and g2.state.pending is None

    g3 = game()
    set_zones(g3, hand=["Mine", "Estate"])
    play(g3, "Mine")
    assert g3.state.pending is None


# ------------------------------------------------------------------ Library
def test_library_draws_to_seven_and_can_set_aside_actions():
    g = game()
    set_zones(g, hand=["Library", "Copper", "Copper"],
              deck=["Copper"] * 4 + ["Village", "Gold", "Silver"], discard=[])
    # hand after playing: 2 cards. Draw order (top = end): Silver, Gold, Village, Copper...
    play(g, "Library")
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
    play(g, "Library")
    answer(g)                                                      # keep Village
    assert len(g.state.players[0].hand) == 6 and "Village" in g.state.players[0].hand
    # the deck only had 6 cards, so Library drew them all and stopped
    g2 = game()
    set_zones(g2, hand=["Library"] + ["Copper"] * 7, deck=["Gold"] * 3)
    play(g2, "Library")
    assert len(g2.state.players[0].hand) == 7 and g2.state.pending is None   # already 7: draws nothing


def test_library_set_aside_cards_are_not_redrawn():
    g = game()
    set_zones(g, hand=["Library"], deck=["Village", "Village", "Copper"], discard=[])
    play(g, "Library")
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
    play(g, "Sentry")
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
    play(g, "Sentry")                                              # draws Copper; looks at Silver, Estate
    answer(g)                                                      # trash none
    answer(g)                                                      # discard none
    assert g.state.pending.decision.options == ("Silver", "Estate")
    answer(g, "Estate")                                            # Estate on top
    assert g.state.players[0].deck == ["Gold", "Silver", "Estate"]


def test_sentry_discard_both_and_short_deck():
    g = game()
    set_zones(g, hand=["Sentry"], deck=["Gold", "Estate", "Copper"], discard=[])
    play(g, "Sentry")
    answer(g)
    answer(g, "Gold", "Estate")
    assert sorted(g.state.players[0].discard) == ["Estate", "Gold"]

    g2 = game()
    set_zones(g2, hand=["Sentry"], deck=[], discard=[])
    play(g2, "Sentry")
    assert g2.state.pending is None


def test_sentry_does_not_ask_about_order_for_identical_cards():
    g = game()
    set_zones(g, hand=["Sentry"], deck=["Silver", "Silver", "Copper"], discard=[])
    play(g, "Sentry")
    answer(g)
    answer(g)
    assert g.state.pending is None and g.state.players[0].deck == ["Silver", "Silver"]


# ------------------------------------------------------------------ Artisan
def test_artisan_gains_to_hand_then_puts_a_card_on_the_deck():
    g = game()
    set_zones(g, hand=["Artisan", "Copper", "Estate"], deck=["Silver"])
    play(g, "Artisan")
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
    play(g, "Council Room")
    s = g.state
    assert len(s.players[0].hand) == 4 and s.buys == 2
    assert [len(p.hand) for p in s.players[1:]] == [b + 1 for b in before[1:]]


# -------------------------------------------------------------- Throne Room
def test_throne_room_plays_an_action_twice_without_spending_actions():
    g = game()
    set_zones(g, hand=["Throne Room", "Council Room"], deck=["Copper"] * 12)
    play(g, "Throne Room")
    assert g.state.pending.decision.options == ("Council Room",)
    answer(g, "Council Room")
    s = g.state
    assert s.pending is None and s.buys == 3 and len(s.players[0].hand) == 8
    assert sorted(s.players[0].in_play) == ["Council Room", "Throne Room"]


def test_throne_room_with_questions_inside_and_declining():
    g = game()
    set_zones(g, hand=["Throne Room", "Harbinger"], deck=["Copper"] * 4, discard=["Gold", "Silver"])
    play(g, "Throne Room")
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
    play(g2, "Throne Room")
    answer(g2)
    assert g2.state.pending is None and g2.state.actions == 0 and "Village" in g2.state.players[0].hand


def test_throne_room_needs_an_action_and_can_chain():
    g = game()
    set_zones(g, hand=["Throne Room", "Copper"])
    play(g, "Throne Room")
    assert g.state.pending is None

    g2 = game()
    set_zones(g2, hand=["Throne Room", "Throne Room", "Council Room", "Merchant"], deck=["Copper"] * 30)
    cards_before = total_cards(g2)
    play(g2, "Throne Room")
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
    play(g, "Throne Room")
    answer(g, "Merchant")
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    assert g.state.coins == 2 + 2
