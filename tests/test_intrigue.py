"""Every Intrigue card, one rule at a time."""

import random

import pytest

from dominion.ai import BigMoneyBot, RandomBot, run_game
from dominion.cards import CardType, get_card, kingdom_cards
from dominion.engine import (
    Buy, Choose, EndPhase, GameConfig, IllegalActionError, PlayAction, PlayAllTreasures, PlayTreasure,
    build_view, new_game,
)
from dominion.engine.scoring import score_player
from helpers import make_game, set_zones, to_buy_phase, total_cards
from test_bots import play_checked

IN = kingdom_cards(["Intrigue"])


def ig(players=2, kingdom=None, seed=3):
    return make_game(players=players, kingdom=kingdom or ["Village", "Smithy", "Moat", "Gardens"], seed=seed)


def play(g, card, player=0):
    g.apply(player, PlayAction(card))


def answer(g, *cards, player=0):
    g.apply(player, Choose(tuple(cards)))


def hand(g, p=0):
    return sorted(g.state.players[p].hand)


def with_pile(g, name, count=10):
    g.state.supply[name] = count


# ------------------------------------------------------------------ the set itself
def test_there_are_26_intrigue_cards_with_expected_names():
    assert len(IN) == 26
    assert set(IN) == {
        "Courtyard", "Lurker", "Pawn", "Masquerade", "Shanty Town", "Steward", "Swindler", "Wishing Well",
        "Baron", "Bridge", "Conspirator", "Diplomat", "Ironworks", "Mill", "Mining Village", "Secret Passage",
        "Courtier", "Duke", "Minion", "Patrol", "Replace", "Torturer", "Trading Post", "Upgrade", "Harem", "Nobles",
    }
    for name in IN:
        assert get_card(name).expansion == "Intrigue" and get_card(name).text


def test_intrigue_costs_match_the_printed_cards():
    costs = {n: get_card(n).cost for n in IN}
    assert costs == {
        "Courtyard": 2, "Lurker": 2, "Pawn": 2, "Masquerade": 3, "Shanty Town": 3, "Steward": 3, "Swindler": 3,
        "Wishing Well": 3, "Baron": 4, "Bridge": 4, "Conspirator": 4, "Diplomat": 4, "Ironworks": 4, "Mill": 4,
        "Mining Village": 4, "Secret Passage": 4, "Courtier": 5, "Duke": 5, "Minion": 5, "Patrol": 5, "Replace": 5,
        "Torturer": 5, "Trading Post": 5, "Upgrade": 5, "Harem": 6, "Nobles": 6,
    }


def test_double_type_cards():
    assert get_card("Harem").is_type(CardType.TREASURE) and get_card("Harem").is_type(CardType.VICTORY)
    for n in ("Nobles", "Mill"):
        assert get_card(n).is_type(CardType.ACTION) and get_card(n).is_type(CardType.VICTORY)
    for n in ("Swindler", "Torturer", "Minion", "Replace"):
        assert get_card(n).is_type(CardType.ATTACK)
    assert get_card("Diplomat").is_type(CardType.REACTION)


def test_victory_sized_piles_for_double_type_cards():
    g = make_game(players=2, kingdom=["Harem", "Nobles", "Mill", "Duke", "Pawn"])
    assert [g.state.supply[n] for n in ("Harem", "Nobles", "Mill", "Duke")] == [8, 8, 8, 8]
    assert g.state.supply["Pawn"] == 10
    g3 = make_game(players=3, kingdom=["Harem", "Pawn"])
    assert g3.state.supply["Harem"] == 12


def test_random_kingdom_respects_chosen_expansions():
    for seed in range(20):
        k = new_game(GameConfig(["A", "B"], None, seed, expansions=["Intrigue"])).state.kingdom
        assert len(k) == 10 and set(k) <= set(IN)
        k = new_game(GameConfig(["A", "B"], None, seed, expansions=["Base"])).state.kingdom
        assert not set(k) & set(IN)
    with pytest.raises(ValueError):
        new_game(GameConfig(["A", "B"], None, 1, expansions=["Nope"]))
    with pytest.raises(ValueError):
        new_game(GameConfig(["A", "B"], None, 1, expansions=[]))


# ------------------------------------------------------------------ $2
def test_courtyard_draws_three_then_puts_one_card_on_the_deck():
    g = ig()
    set_zones(g, hand=["Courtyard", "Copper"], deck=["Silver", "Gold", "Estate", "Duchy"])
    play(g, "Courtyard")
    assert hand(g) == ["Copper", "Duchy", "Estate", "Gold"]
    answer(g, "Gold")
    assert g.state.players[0].deck[-1] == "Gold" and "Gold" not in hand(g)


def test_pawn_applies_exactly_the_two_chosen_effects():
    g = ig()
    set_zones(g, hand=["Pawn", "Copper"], deck=["Silver", "Gold"])
    play(g, "Pawn")
    with pytest.raises(IllegalActionError):
        answer(g, "+1 Card")                         # must choose two
    with pytest.raises(IllegalActionError):
        answer(g, "+1 Card", "+1 Card")              # must be different
    answer(g, "+1 Card", "+$1")
    s = g.state
    assert (s.actions, s.buys, s.coins) == (0, 1, 1) and len(s.players[0].hand) == 2
    g2 = ig()
    set_zones(g2, hand=["Pawn"])
    play(g2, "Pawn")
    answer(g2, "+1 Action", "+1 Buy")
    assert (g2.state.actions, g2.state.buys, g2.state.coins) == (1, 2, 0)


def test_lurker_trashes_from_supply_or_gains_from_trash():
    g = ig()
    set_zones(g, hand=["Lurker"])
    play(g, "Lurker")
    assert g.state.actions == 1
    # nothing in the trash: only the Supply option exists, so it is asked straight away
    assert "Smithy" in g.state.pending.decision.options and "Gardens" not in g.state.pending.decision.options
    answer(g, "Smithy")
    assert g.state.supply["Smithy"] == 9 and g.state.trash == ["Smithy"]
    # now both modes exist
    set_zones(g, hand=["Lurker"], in_play=[])
    g.state.actions = 1
    play(g, "Lurker")
    assert set(g.state.pending.decision.options) == {
        "Trash an Action card from the Supply", "Gain an Action card from the trash"}
    answer(g, "Gain an Action card from the trash")
    answer(g, "Smithy")
    assert g.state.trash == [] and g.state.players[0].discard[-1] == "Smithy"


def test_lurker_cannot_touch_catastrophe_cards():
    g = make_game(players=3, kingdom=["Village", "Smithy"], catastrophes=["Time Stop"])
    set_zones(g, hand=["Lurker"])
    g.state.supply["Lurker"] = 9
    play(g, "Lurker")
    assert "Time Stop" not in g.state.pending.decision.options
    answer(g, "Village")
    g.state.trash.append("Time Stop")                 # a used Catastrophe card sits in the trash
    set_zones(g, hand=["Lurker"], in_play=[])
    g.state.actions = 1
    play(g, "Lurker")
    # the only Action in the trash is Village (just trashed), never Time Stop
    answer(g, "Gain an Action card from the trash")
    assert g.state.pending.decision.options == ("Village",)


# ------------------------------------------------------------------ $3
def test_masquerade_passes_cards_left_at_once_then_trashes():
    g = ig(players=3)
    set_zones(g, 0, hand=["Masquerade", "Copper", "Estate"], deck=["Silver", "Silver"])
    set_zones(g, 1, hand=["Gold", "Duchy"])
    set_zones(g, 2, hand=["Province"])
    play(g, "Masquerade")
    assert hand(g) == ["Copper", "Estate", "Silver", "Silver"]
    answer(g, "Copper", player=0)
    answer(g, "Gold", player=1)
    answer(g, "Province", player=2)
    # 0 -> 1, 1 -> 2, 2 -> 0 (simultaneously: nobody passes on a card they just received)
    assert hand(g, 0) == ["Estate", "Province", "Silver", "Silver"]
    assert hand(g, 1) == ["Copper", "Duchy"]
    assert hand(g, 2) == ["Gold"]
    answer(g, "Estate", player=0)                    # optional trash
    assert g.state.trash == ["Estate"] and g.state.pending is None


def test_masquerade_skips_players_with_empty_hands_and_may_trash_nothing():
    g = ig()
    set_zones(g, 0, hand=["Masquerade"], deck=["Copper", "Copper"])
    set_zones(g, 1, hand=[])
    play(g, "Masquerade")
    answer(g, "Copper", player=0)
    assert hand(g, 1) == ["Copper"] and hand(g, 0) == ["Copper"]
    answer(g, player=0)
    assert g.state.trash == []


def test_masquerade_choice_is_hidden_from_other_players():
    g = ig()
    set_zones(g, 0, hand=["Masquerade"], deck=["Copper", "Copper"])
    set_zones(g, 1, hand=["Gold"])
    play(g, "Masquerade")
    answer(g, "Copper", player=0)
    assert build_view(g, 0)["pending"].get("options") is None      # it is player 1's decision
    assert build_view(g, 1)["pending"]["options"] == ["Gold"]


def test_shanty_town_draws_only_without_actions_in_hand():
    g = ig()
    set_zones(g, hand=["Shanty Town", "Copper"], deck=["Silver", "Gold"])
    play(g, "Shanty Town")
    assert g.state.actions == 2 and hand(g) == ["Copper", "Gold", "Silver"]
    g = ig()
    set_zones(g, hand=["Shanty Town", "Village"], deck=["Silver", "Gold"])
    play(g, "Shanty Town")
    assert g.state.actions == 2 and hand(g) == ["Village"]
    assert any("reveals their hand" in line for line in g.state.log)


def test_steward_three_modes():
    for mode, check in (
        ("+2 Cards", lambda s: len(s.players[0].hand) == 3),
        ("+$2", lambda s: s.coins == 2),
    ):
        g = ig()
        set_zones(g, hand=["Steward", "Copper"], deck=["Silver", "Gold"])
        play(g, "Steward")
        answer(g, mode)
        assert check(g.state)
    g = ig()
    set_zones(g, hand=["Steward", "Copper", "Estate", "Gold"])
    play(g, "Steward")
    answer(g, "Trash 2 cards from your hand")
    with pytest.raises(IllegalActionError):
        answer(g, "Copper")
    answer(g, "Copper", "Estate")
    assert sorted(g.state.trash) == ["Copper", "Estate"] and hand(g) == ["Gold"]


def test_steward_with_an_empty_hand_has_no_trash_option():
    g = ig()
    set_zones(g, hand=["Steward"])
    play(g, "Steward")
    assert g.state.pending.decision.options == ("+2 Cards", "+$2")


def test_swindler_trashes_top_card_and_attacker_picks_replacement_of_equal_cost():
    g = ig()
    set_zones(g, 0, hand=["Swindler"])
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Estate", "Silver"])
    play(g, "Swindler")
    assert g.state.coins == 2
    assert g.state.trash == ["Silver"]
    d = g.state.pending.decision
    assert d.player == 0
    assert set(d.options) == {n for n in g.state.supply if get_card(n).cost == 3 and g.state.supply[n] > 0}
    assert {"Silver", "Village"} <= set(d.options)
    answer(g, "Village")
    assert g.state.players[1].discard[-1] == "Village" and g.state.supply["Village"] == 9


def test_swindler_with_nothing_costing_the_same_just_trashes():
    g = ig()
    set_zones(g, 0, hand=["Swindler"])
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Province"], discard=[])
    g.state.supply["Province"] = 0
    play(g, "Swindler")
    assert g.state.pending is None and g.state.trash == ["Province"]


def test_swindler_is_blocked_by_moat():
    g = ig()
    set_zones(g, 0, hand=["Swindler"])
    set_zones(g, 1, hand=["Moat"] * 1 + ["Copper"] * 4, deck=["Silver"])
    play(g, "Swindler")
    answer(g, "Moat", player=1)
    assert g.state.trash == [] and g.state.pending is None


def test_wishing_well_hit_and_miss():
    g = ig()
    set_zones(g, hand=["Wishing Well"], deck=["Gold", "Silver", "Copper"])
    play(g, "Wishing Well")
    assert hand(g) == ["Copper"] and g.state.actions == 1
    answer(g, "Silver")                              # next card is Silver: a hit
    assert hand(g) == ["Copper", "Silver"] and g.state.players[0].deck == ["Gold"]
    g = ig()
    set_zones(g, hand=["Wishing Well"], deck=["Gold", "Silver", "Copper"])
    play(g, "Wishing Well")
    answer(g, "Gold")                                # miss: Silver goes back on top
    assert hand(g) == ["Copper"] and g.state.players[0].deck == ["Gold", "Silver"]


# ------------------------------------------------------------------ $4
def test_baron_discard_estate_for_coins_or_gain_one():
    g = ig()
    set_zones(g, hand=["Baron", "Estate"])
    play(g, "Baron")
    answer(g, "Estate")
    assert g.state.coins == 4 and g.state.buys == 2 and g.state.players[0].discard == ["Estate"]
    g = ig()
    set_zones(g, hand=["Baron", "Estate"])
    play(g, "Baron")
    answer(g)                                        # decline
    assert g.state.coins == 0 and g.state.players[0].discard == ["Estate"] and hand(g) == ["Estate"]
    assert g.state.supply["Estate"] == 7
    g = ig()
    set_zones(g, hand=["Baron", "Copper"])
    play(g, "Baron")
    assert g.state.pending is None and g.state.players[0].discard == ["Estate"]


def test_bridge_reduces_costs_everywhere_for_the_turn_only():
    g = ig(kingdom=["Village", "Smithy", "Gardens", "Market"])
    set_zones(g, hand=["Bridge", "Copper", "Copper", "Copper", "Copper"])
    play(g, "Bridge")
    assert (g.state.coins, g.state.buys, g.state.cost_reduction) == (1, 2, 1)
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    assert Buy("Province") not in g.legal_actions() and Buy("Market") in g.legal_actions()   # $5 now costs $4
    assert Buy("Gold") in g.legal_actions()                      # $5 coins: Gold costs $5-1
    g.apply(0, Buy("Market"))
    assert g.state.coins == 1                                    # paid $4, not $5
    assert build_view(g, 0)["cost_reduction"] == 1
    prices = {p["name"]: p["price"] for p in build_view(g, 0)["piles"]}
    assert prices["Market"] == 4 and prices["Copper"] == 0
    g.apply(0, EndPhase())
    assert g.state.cost_reduction == 0
    assert {p["name"]: p["price"] for p in build_view(g, 1)["piles"]}["Market"] == 5


def test_bridge_never_drops_below_zero_and_stacks():
    g = ig()
    set_zones(g, hand=["Bridge", "Bridge"], in_play=[])
    g.state.actions = 2
    play(g, "Bridge")
    play(g, "Bridge")
    assert g.state.cost_reduction == 2
    to_buy_phase(g)
    assert Buy("Copper") in g.legal_actions()                    # $0 stays $0 (no negative cost)
    g.apply(0, Buy("Copper"))
    assert g.state.coins == 2


def test_bridge_changes_what_workshop_style_gains_can_reach():
    g = make_game(players=2, kingdom=["Bridge", "Workshop", "Smithy", "Market"])
    set_zones(g, hand=["Bridge", "Workshop"])
    g.state.actions = 2
    play(g, "Bridge")
    play(g, "Workshop")
    assert "Market" in g.state.pending.decision.options          # costs $4 this turn


def test_conspirator_counts_actions_played_including_throne_room_repeats():
    g = make_game(players=2, kingdom=["Village", "Throne Room", "Smithy"])
    set_zones(g, hand=["Conspirator", "Village", "Conspirator"], deck=["Silver", "Gold"])
    g.state.actions = 3
    play(g, "Conspirator")                                       # 1st action: just +$2
    assert g.state.coins == 2 and len(g.state.players[0].hand) == 2
    play(g, "Village")                                           # 2nd (draws a card, +2 actions)
    before = len(g.state.players[0].hand)
    play(g, "Conspirator")                                       # 3rd: +$2, +1 card, +1 action
    assert g.state.coins == 4 and len(g.state.players[0].hand) == before - 1 + 1


def test_conspirator_with_throne_room():
    g = make_game(players=2, kingdom=["Throne Room", "Smithy"])
    set_zones(g, hand=["Throne Room", "Conspirator"], deck=["Silver", "Gold", "Copper"])
    play(g, "Throne Room")
    answer(g, "Conspirator")
    # plays: Throne Room (1), Conspirator (2), Conspirator again (3) -> the second copy draws
    assert g.state.coins == 4 and hand(g) == ["Copper"] and g.state.actions == 1


def test_diplomat_actions_depend_on_hand_size_after_drawing():
    g = ig()
    set_zones(g, hand=["Diplomat", "Copper", "Copper"], deck=["Silver", "Gold"])
    play(g, "Diplomat")
    assert g.state.actions == 2                                  # 4 cards left in hand
    g = ig()
    set_zones(g, hand=["Diplomat"] + ["Copper"] * 5, deck=["Silver", "Gold"])
    play(g, "Diplomat")
    assert g.state.actions == 0                                  # 7 cards in hand


def test_diplomat_reaction_draws_two_discards_three_when_attacked():
    g = make_game(players=2, kingdom=["Militia", "Moat", "Village"])
    set_zones(g, 0, hand=["Militia"])
    set_zones(g, 1, hand=["Diplomat", "Copper", "Copper", "Estate", "Estate"], deck=["Gold", "Silver"], discard=[])
    play(g, "Militia")
    d = g.state.pending.decision
    assert d.player == 1 and d.options == ("Diplomat",) and d.min_choices == 0
    answer(g, "Diplomat", player=1)
    assert len(hand(g, 1)) == 7                                  # drew 2
    d = g.state.pending.decision
    assert (d.min_choices, d.max_choices) == (3, 3)
    answer(g, "Estate", "Estate", "Copper", player=1)
    assert len(hand(g, 1)) == 4
    # Militia now makes them discard down to 3
    assert g.state.pending.decision.player == 1 and g.state.pending.decision.min_choices == 1


def test_diplomat_reaction_not_offered_with_fewer_than_five_cards_or_when_declined():
    g = make_game(players=2, kingdom=["Militia", "Moat"])
    set_zones(g, 0, hand=["Militia"])
    set_zones(g, 1, hand=["Diplomat", "Copper", "Copper", "Estate"])
    play(g, "Militia")
    assert g.state.pending is None or g.state.pending.decision.options != ("Diplomat",)
    g = make_game(players=2, kingdom=["Militia", "Moat"])
    set_zones(g, 0, hand=["Militia"])
    set_zones(g, 1, hand=["Diplomat", "Copper", "Copper", "Estate", "Estate"], deck=["Gold", "Silver"])
    play(g, "Militia")
    answer(g, player=1)                                          # decline
    assert len(hand(g, 1)) == 5


def test_diplomat_then_moat_can_both_be_used():
    g = make_game(players=2, kingdom=["Militia", "Moat"])
    set_zones(g, 0, hand=["Militia"])
    set_zones(g, 1, hand=["Diplomat", "Moat", "Copper", "Estate", "Estate"], deck=["Gold", "Silver"])
    play(g, "Militia")
    answer(g, "Diplomat", player=1)
    answer(g, "Estate", "Estate", "Copper", player=1)
    d = g.state.pending.decision
    assert d.options == ("Moat",)
    answer(g, "Moat", player=1)
    assert g.state.pending is None and len(hand(g, 1)) == 4      # Moat protected them from Militia


def test_ironworks_bonus_depends_on_gained_type():
    for gain, expected in (("Silver", (0, 1, 0)), ("Village", (1, 0, 0)), ("Estate", (0, 0, 1)), ("Copper", (0, 1, 0))):
        g = make_game(players=2, kingdom=["Ironworks", "Village", "Gardens"])
        set_zones(g, hand=["Ironworks"], deck=["Gold", "Gold"])
        play(g, "Ironworks")
        answer(g, gain)
        s = g.state
        assert (s.actions - 0, s.coins, len(s.players[0].hand)) == (expected[0], expected[1], expected[2]), gain


def test_ironworks_gaining_nobles_gives_action_and_card():
    g = make_game(players=2, kingdom=["Ironworks", "Gardens"])
    g.state.supply["Nobles"] = 8
    # Nobles costs 6, too expensive for Ironworks: confirm it is not offered
    set_zones(g, hand=["Ironworks"])
    play(g, "Ironworks")
    assert "Nobles" not in g.state.pending.decision.options


def test_mill_is_action_and_victory_and_discards_two_for_coins():
    g = make_game(players=2, kingdom=["Mill", "Village"])
    set_zones(g, hand=["Mill", "Estate", "Estate", "Copper"], deck=["Silver"])
    play(g, "Mill")
    assert g.state.actions == 1
    answer(g, "Yes")
    answer(g, "Estate", "Estate")
    assert g.state.coins == 2
    g = make_game(players=2, kingdom=["Mill"])
    set_zones(g, hand=["Mill", "Estate"], deck=["Silver"])
    play(g, "Mill")
    answer(g, "No")
    assert g.state.coins == 0 and len(g.state.players[0].hand) == 2


def test_mill_scores_one_vp():
    g = make_game(players=2, kingdom=["Mill"])
    base = score_player(g.state.players[0])
    g.state.players[0].discard.append("Mill")
    assert score_player(g.state.players[0]) == base + 1


def test_mining_village_may_trash_itself_for_coins():
    g = ig()
    set_zones(g, hand=["Mining Village"], deck=["Silver"])
    play(g, "Mining Village")
    assert g.state.actions == 2
    answer(g, "Mining Village")
    assert g.state.coins == 2 and g.state.trash == ["Mining Village"] and "Mining Village" not in g.state.players[0].in_play
    g = ig()
    set_zones(g, hand=["Mining Village"], deck=["Silver"])
    play(g, "Mining Village")
    answer(g)
    assert g.state.coins == 0 and g.state.players[0].in_play == ["Mining Village"]


def test_mining_village_thrown_twice_only_trashes_once():
    g = make_game(players=2, kingdom=["Throne Room", "Mining Village"])
    set_zones(g, hand=["Throne Room", "Mining Village"], deck=["Silver", "Silver", "Silver"])
    play(g, "Throne Room")
    answer(g, "Mining Village")
    answer(g, "Mining Village")                                  # first play: trash it for $2
    assert g.state.coins == 2
    assert g.state.pending is None                               # second play: it is gone, no prompt
    assert g.state.trash == ["Mining Village"] and g.state.actions == 4


def test_secret_passage_puts_card_at_chosen_spot():
    g = ig()
    set_zones(g, hand=["Secret Passage", "Gold"], deck=["Copper"] * 8 + ["Silver", "Silver"])
    play(g, "Secret Passage")
    assert g.state.actions == 1 and len(hand(g)) == 3
    answer(g, "Gold")
    d = g.state.pending.decision
    assert d.options[0] == "On top of your deck" and d.options[-1] == "On the bottom of your deck"
    answer(g, "3rd from the top")
    deck = g.state.players[0].deck
    assert deck[-3] == "Gold" and len(deck) == 9


def test_secret_passage_on_the_bottom_and_with_a_tiny_deck():
    g = ig()
    set_zones(g, hand=["Secret Passage", "Gold"], deck=["Copper", "Copper", "Silver"])
    play(g, "Secret Passage")                                    # draws 2: deck has 1 left
    answer(g, "Gold")
    assert g.state.pending.decision.options == ("On top of your deck", "On the bottom of your deck")
    answer(g, "On the bottom of your deck")
    assert g.state.players[0].deck[0] == "Gold"


def test_secret_passage_with_an_empty_deck_still_works():
    g = ig()
    set_zones(g, hand=["Secret Passage", "Gold"], deck=[], discard=[])
    play(g, "Secret Passage")
    answer(g, "Gold")
    assert g.state.pending.decision.options == ("On top of your deck",)
    answer(g, "On top of your deck")
    assert g.state.players[0].deck == ["Gold"]


# ------------------------------------------------------------------ $5
def test_courtier_number_of_choices_equals_types_of_revealed_card():
    cases = {"Gold": 1, "Moat": 2, "Estate": 1, "Militia": 2, "Nobles": 2, "Harem": 2}
    for card, n in cases.items():
        g = make_game(players=2, kingdom=["Courtier", "Moat", "Militia", "Nobles", "Harem"])
        set_zones(g, hand=["Courtier", card])
        play(g, "Courtier")
        answer(g, card)
        d = g.state.pending.decision
        assert (d.min_choices, d.max_choices) == (n, n), card


def test_courtier_effects():
    g = make_game(players=2, kingdom=["Courtier", "Moat"])
    set_zones(g, hand=["Courtier", "Moat"])
    play(g, "Courtier")
    answer(g, "Moat")
    answer(g, "+$3", "Gain a Gold")
    s = g.state
    assert s.coins == 3 and s.players[0].discard == ["Gold"] and s.actions == 0 and s.buys == 1
    g = make_game(players=2, kingdom=["Courtier"])
    set_zones(g, hand=["Courtier", "Copper"])
    play(g, "Courtier")
    answer(g, "Copper")
    answer(g, "+1 Buy")
    assert g.state.buys == 2


def test_duke_scores_one_vp_per_duchy():
    g = make_game(players=2, kingdom=["Duke"])
    p = g.state.players[0]
    base = score_player(p)
    p.discard.extend(["Duke", "Duke", "Duchy", "Duchy", "Duchy"])
    assert score_player(p) == base + 3 * 3 + 2 * 3


def test_minion_coins_mode():
    g = ig()
    set_zones(g, hand=["Minion", "Copper"])
    play(g, "Minion")
    answer(g, "+$2")
    assert g.state.coins == 2 and g.state.actions == 1 and hand(g) == ["Copper"]


def test_minion_attack_mode_only_hits_players_with_five_or_more_cards():
    g = make_game(players=3, kingdom=["Minion", "Moat"])
    set_zones(g, 0, hand=["Minion", "Copper", "Copper"], deck=["Gold"] * 6)
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Silver"] * 6, discard=[])
    set_zones(g, 2, hand=["Copper"] * 4, deck=["Silver"] * 6, discard=[])
    play(g, "Minion")
    answer(g, "Discard your hand, +4 Cards, and attack")
    assert hand(g, 0) == ["Gold"] * 4
    assert hand(g, 1) == ["Silver"] * 4 and g.state.players[1].discard == ["Copper"] * 5
    assert hand(g, 2) == ["Copper"] * 4


def test_minion_attack_respects_moat():
    g = ig(kingdom=["Minion", "Moat"])
    set_zones(g, 0, hand=["Minion"], deck=["Gold"] * 6)
    set_zones(g, 1, hand=["Moat"] + ["Copper"] * 4, deck=["Silver"] * 6)
    play(g, "Minion")
    answer(g, "Discard your hand, +4 Cards, and attack")
    answer(g, "Moat", player=1)
    assert len(hand(g, 1)) == 5 and hand(g, 0) == ["Gold"] * 4


def test_patrol_takes_victory_and_curses_and_reorders_the_rest():
    g = ig()
    set_zones(g, hand=["Patrol"], deck=["Silver", "Copper", "Estate", "Curse", "Gold", "Duchy", "Estate"])
    # top is the END of the list: draws Estate, Duchy, Gold; then reveals Curse, Estate, Copper, Silver
    play(g, "Patrol")
    assert hand(g) == sorted(["Duchy", "Estate", "Estate", "Gold", "Curse"])
    d = g.state.pending.decision
    assert sorted(d.options) == ["Copper", "Silver"]
    answer(g, "Silver")                                          # Silver on top, Copper beneath
    assert g.state.players[0].deck[-2:] == ["Copper", "Silver"]


def test_patrol_with_identical_leftovers_asks_nothing():
    g = ig()
    set_zones(g, hand=["Patrol"], deck=["Copper", "Copper", "Copper", "Copper", "Copper", "Copper", "Copper"])
    play(g, "Patrol")
    assert g.state.pending is None and len(g.state.players[0].deck) == 4


def test_replace_action_goes_on_deck_victory_curses_others():
    g = make_game(players=3, kingdom=["Replace", "Village", "Gardens", "Moat"])
    set_zones(g, hand=["Replace", "Silver"])
    play(g, "Replace")
    answer(g, "Silver")
    d = g.state.pending.decision
    assert "Village" in d.options and "Gardens" in d.options and "Smithy" not in d.options
    answer(g, "Village")
    assert g.state.players[0].deck[-1] == "Village" and g.state.trash == ["Silver"]
    assert g.state.supply["Curse"] == 20
    g = make_game(players=3, kingdom=["Replace", "Gardens", "Moat"])
    set_zones(g, hand=["Replace", "Silver"])
    set_zones(g, 1, hand=["Copper"] * 5)
    set_zones(g, 2, hand=["Moat"] + ["Copper"] * 4)
    play(g, "Replace")
    answer(g, "Silver")
    answer(g, "Gardens")
    answer(g, "Moat", player=2)
    assert g.state.players[0].discard[-1] == "Gardens"
    assert g.state.players[1].discard[-1] == "Curse" and "Curse" not in g.state.players[2].discard


def test_replace_gaining_nobles_both_decks_and_curses():
    g = make_game(players=2, kingdom=["Replace", "Nobles"])
    set_zones(g, hand=["Replace", "Gold"])
    play(g, "Replace")
    answer(g, "Gold")
    answer(g, "Nobles")
    assert g.state.players[0].deck[-1] == "Nobles"               # Action: onto the deck
    assert g.state.players[1].discard[-1] == "Curse"             # Victory: curses the others


def test_torturer_discard_two_or_gain_curse_to_hand():
    g = ig(kingdom=["Torturer", "Moat"])
    set_zones(g, 0, hand=["Torturer"], deck=["Silver"] * 3)
    set_zones(g, 1, hand=["Copper", "Copper", "Estate", "Gold", "Silver"])
    play(g, "Torturer")
    assert g.state.pending.decision.player == 1
    answer(g, "Discard 2 cards", player=1)
    answer(g, "Copper", "Estate", player=1)
    assert len(hand(g, 1)) == 3 and len(g.state.players[1].discard) == 2
    g = ig(kingdom=["Torturer", "Moat"])
    set_zones(g, 0, hand=["Torturer"], deck=["Silver"] * 3)
    set_zones(g, 1, hand=["Copper"] * 5)
    play(g, "Torturer")
    answer(g, "Gain a Curse", player=1)
    assert hand(g, 1) == sorted(["Copper"] * 5 + ["Curse"])


def test_torturer_forces_the_possible_option():
    g = ig(kingdom=["Torturer"])
    set_zones(g, 0, hand=["Torturer"], deck=["Silver"] * 3)
    set_zones(g, 1, hand=["Copper"])                             # cannot discard 2
    play(g, "Torturer")
    assert g.state.pending is None and "Curse" in hand(g, 1)
    g = ig(kingdom=["Torturer"])
    g.state.supply["Curse"] = 0
    set_zones(g, 0, hand=["Torturer"], deck=["Silver"] * 3)
    set_zones(g, 1, hand=["Copper"] * 5)
    play(g, "Torturer")
    assert g.state.pending.decision.min_choices == 2             # curses are gone: must discard 2


def test_trading_post_needs_two_trashes_for_the_silver():
    g = ig()
    set_zones(g, hand=["Trading Post", "Estate", "Copper", "Gold"])
    play(g, "Trading Post")
    answer(g, "Estate", "Copper")
    assert sorted(g.state.trash) == ["Copper", "Estate"] and sorted(hand(g)) == ["Gold", "Silver"]
    g = ig()
    set_zones(g, hand=["Trading Post", "Estate"])
    play(g, "Trading Post")
    answer(g, "Estate")                                          # only one card: no Silver
    assert hand(g) == [] and g.state.trash == ["Estate"]


def test_upgrade_gains_exactly_one_more():
    g = ig(kingdom=["Upgrade", "Village", "Smithy", "Moat", "Gardens"])
    set_zones(g, hand=["Upgrade", "Silver"], deck=["Copper"])
    play(g, "Upgrade")
    assert g.state.actions == 1
    answer(g, "Silver")
    d = g.state.pending.decision
    assert all(get_card(o).cost == 4 for o in d.options)           # Silver costs $3
    assert set(d.options) == {"Smithy", "Gardens"}
    answer(g, "Smithy")
    assert g.state.players[0].discard[-1] == "Smithy"


def test_upgrade_with_nothing_at_that_cost_just_trashes():
    g = make_game(players=2, kingdom=["Upgrade"])
    set_zones(g, hand=["Upgrade", "Province"])
    play(g, "Upgrade")
    answer(g, "Province")
    assert g.state.pending is None and g.state.trash == ["Province"]


# ------------------------------------------------------------------ $6
def test_harem_is_a_treasure_worth_two_and_two_vp():
    g = make_game(players=2, kingdom=["Harem"])
    set_zones(g, hand=["Harem", "Copper", "Copper", "Copper", "Copper"])
    p = g.state.players[0]
    no_harem = score_player(p) - 2
    assert no_harem == sum(c == "Estate" for c in p.all_cards())
    to_buy_phase(g)
    g.apply(0, PlayTreasure("Harem"))
    assert g.state.coins == 2
    assert score_player(p) == no_harem + 2          # still counts as 2 VP while in play
    g.apply(0, PlayAllTreasures())
    assert g.state.coins == 6


def test_nobles_choose_cards_or_actions_and_is_worth_two():
    g = make_game(players=2, kingdom=["Nobles"])
    set_zones(g, hand=["Nobles"], deck=["Silver"] * 3)
    base = score_player(g.state.players[0])
    play(g, "Nobles")
    answer(g, "+3 Cards")
    assert len(hand(g)) == 3 and g.state.actions == 0
    g = make_game(players=2, kingdom=["Nobles"])
    set_zones(g, hand=["Nobles"])
    play(g, "Nobles")
    answer(g, "+2 Actions")
    assert g.state.actions == 2
    g.state.players[0].discard.append("Nobles")
    assert score_player(g.state.players[0]) >= base + 2


def test_nobles_and_harem_in_hand_do_the_right_thing_for_attacks_that_check_victory():
    g = make_game(players=2, kingdom=["Bureaucrat", "Nobles", "Harem"])
    set_zones(g, 0, hand=["Bureaucrat"])
    set_zones(g, 1, hand=["Nobles", "Harem", "Copper", "Copper", "Copper"])
    play(g, "Bureaucrat")
    d = g.state.pending.decision
    assert d.player == 1 and set(d.options) == {"Nobles", "Harem"}


# ------------------------------------------------------------------ whole-game checks
KINGDOM_A = ["Courtyard", "Lurker", "Pawn", "Masquerade", "Shanty Town", "Steward", "Swindler", "Wishing Well", "Baron", "Bridge"]
KINGDOM_B = ["Conspirator", "Diplomat", "Ironworks", "Mill", "Mining Village", "Secret Passage", "Courtier", "Duke", "Minion", "Patrol"]
KINGDOM_C = ["Replace", "Torturer", "Trading Post", "Upgrade", "Harem", "Nobles", "Moat", "Militia", "Throne Room", "Gardens"]


@pytest.mark.parametrize("kingdom", [KINGDOM_A, KINGDOM_B, KINGDOM_C])
@pytest.mark.parametrize("players", [2, 3, 4])
def test_random_games_with_intrigue_conserve_cards_and_finish(kingdom, players):
    for seed in range(4):
        g = make_game(players=players, kingdom=kingdom, seed=seed)
        before = total_cards(g)
        rng = random.Random(seed)
        bots = [RandomBot(random.Random(rng.random())) for _ in range(players)]
        for _ in range(4000):
            if g.state.status.value == "finished":
                break
            play_checked(g, bots)
            assert total_cards(g) == before
        # a random game may not finish in 4000 moves, but it must never break an invariant
        for p in g.state.players:
            assert all(c in g.state.supply or c in ("Copper", "Estate") for c in p.all_cards())


def test_every_intrigue_card_survives_replay_after_random_play():
    from dominion.engine import replay
    g = make_game(players=3, kingdom=KINGDOM_A, seed=7)
    bots = [RandomBot(random.Random(i)) for i in range(3)]
    for _ in range(600):
        if g.state.status.value == "finished":
            break
        play_checked(g, bots)
    r = replay(g.config, g.history)
    assert [p.all_cards() for p in r.state.players] == [p.all_cards() for p in g.state.players]
    assert r.state.supply == g.state.supply and r.state.trash == g.state.trash


def test_bigmoney_bot_handles_intrigue_text_choices():
    g = make_game(players=2, kingdom=KINGDOM_A, seed=2)
    set_zones(g, 0, hand=["Pawn"])
    play(g, "Pawn")
    move = BigMoneyBot().choose(g, 0)
    g.apply(0, move)
    assert g.state.pending is None


def test_courtier_offers_at_most_four_effects_even_for_a_card_with_more_types():
    from dominion.cards import CardDef, register, unregister
    five = CardDef(
        "Five Types", 1,
        frozenset({CardType.ACTION, CardType.ATTACK, CardType.REACTION, CardType.TREASURE, CardType.VICTORY}),
        coins=1, vp=0, on_play=lambda ctx: None, text="test card",
    )
    register(five)
    try:
        g = make_game(players=2, kingdom=["Courtier"])
        set_zones(g, hand=["Courtier", "Five Types"])
        play(g, "Courtier")
        answer(g, "Five Types")
        d = g.state.pending.decision
        assert (d.min_choices, d.max_choices) == (4, 4) and len(d.options) == 4
    finally:
        unregister("Five Types")
