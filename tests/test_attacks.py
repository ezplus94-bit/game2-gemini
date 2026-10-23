import random

import pytest

from dominion.ai import BigMoneyBot, RandomBot
from dominion.engine import (
    Choose, GameConfig, GameStatus, IllegalActionError, PlayAction, build_view, new_game, replay,
)
from helpers import make_game, set_zones, snapshot, total_cards
from test_bots import play_checked

ATTACKS = ["Militia", "Witch", "Moat", "Bandit", "Throne Room"]


def game(players=3, **kw):
    return make_game(players=players, kingdom=kw.pop("kingdom", ATTACKS), **kw)


def play(g, card, player=0):
    g.apply(player, PlayAction(card))


def answer(g, player, *cards):
    g.apply(player, Choose(tuple(cards)))


# ------------------------------------------------------------------- Moat
def test_moat_draws_two_when_played():
    g = game()
    set_zones(g, hand=["Moat"], deck=["Copper"] * 4)
    play(g, "Moat")
    assert len(g.state.players[0].hand) == 2


# ----------------------------------------------------------------- Militia
def test_militia_makes_each_other_player_discard_down_to_three_in_turn_order():
    g = game()
    set_zones(g, 0, hand=["Militia"])
    set_zones(g, 1, hand=["Copper"] * 5)
    set_zones(g, 2, hand=["Estate", "Estate", "Estate", "Gold", "Silver"])
    play(g, "Militia")
    s = g.state
    assert s.coins == 2 and g.acting_player == 1
    d = s.pending.decision
    assert (d.player, d.min_choices, d.max_choices) == (1, 2, 2)
    assert g.legal_actions(player=0) == []                    # the attacker has to wait
    with pytest.raises(IllegalActionError):
        answer(g, 1, "Copper")                                # must discard exactly 2
    with pytest.raises(IllegalActionError):
        answer(g, 2, "Estate", "Estate")                      # not player 2's decision yet
    answer(g, 1, "Copper", "Copper")
    assert g.acting_player == 2
    answer(g, 2, "Estate", "Estate")
    assert s.pending is None
    assert [len(p.hand) for p in s.players] == [0, 3, 3]
    assert sorted(s.players[2].hand) == ["Estate", "Gold", "Silver"]


def test_militia_skips_players_with_three_or_fewer_cards():
    g = game()
    set_zones(g, 0, hand=["Militia"])
    set_zones(g, 1, hand=["Copper"] * 3)
    set_zones(g, 2, hand=["Copper", "Copper"])
    play(g, "Militia")
    assert g.state.pending is None and len(g.state.players[1].hand) == 3


def test_attack_decisions_are_private_to_the_defender():
    g = game()
    set_zones(g, 0, hand=["Militia"])
    set_zones(g, 1, hand=["Gold", "Gold", "Silver", "Copper", "Copper"])
    play(g, "Militia")
    defender, attacker, bystander = build_view(g, 1), build_view(g, 0), build_view(g, 2)
    assert sorted(defender["pending"]["options"]) == ["Copper", "Copper", "Gold", "Gold", "Silver"]
    assert defender["pending"]["source"] == "Militia"
    assert attacker["pending"] == {"player": 1, "source": "Militia"}
    assert bystander["pending"] == {"player": 1, "source": "Militia"}


# -------------------------------------------------------------- Moat vs attacks
def test_revealing_moat_makes_you_unaffected_and_others_still_discard():
    g = game()
    set_zones(g, 0, hand=["Militia"])
    set_zones(g, 1, hand=["Moat", "Copper", "Copper", "Copper", "Copper"])
    set_zones(g, 2, hand=["Copper"] * 5)
    play(g, "Militia")
    d = g.state.pending.decision
    assert d.player == 1 and d.options == ("Moat",) and (d.min_choices, d.max_choices) == (0, 1)
    answer(g, 1, "Moat")
    assert g.acting_player == 2                                # player 1 is skipped
    answer(g, 2, "Copper", "Copper")
    assert len(g.state.players[1].hand) == 5 and len(g.state.players[2].hand) == 3
    assert any("reveals Moat" in line for line in g.state.log)


def test_declining_to_reveal_moat_means_the_attack_hits():
    g = game()
    set_zones(g, 0, hand=["Militia"])
    set_zones(g, 1, hand=["Moat", "Copper", "Copper", "Copper", "Copper"])
    set_zones(g, 2, hand=["Copper"] * 3)
    play(g, "Militia")
    answer(g, 1)                                               # do not reveal
    assert g.state.pending.decision.player == 1 and g.state.pending.decision.max_choices == 2
    answer(g, 1, "Moat", "Copper")
    assert len(g.state.players[1].hand) == 3


def test_all_reactions_are_asked_before_any_attack_effect():
    g = game()
    set_zones(g, 0, hand=["Militia"])
    set_zones(g, 1, hand=["Moat", "Copper", "Copper", "Copper", "Copper"])
    set_zones(g, 2, hand=["Moat", "Copper", "Copper", "Copper", "Copper"])
    play(g, "Militia")
    answer(g, 1)                                               # player 1 declines...
    d = g.state.pending.decision                               # ...and player 2 is asked about Moat next,
    assert d.player == 2 and d.options == ("Moat",)            # not player 1 about discarding
    answer(g, 2, "Moat")
    assert g.state.pending.decision.player == 1                # now the discards begin
    assert g.state.pending.decision.max_choices == 2


def test_players_without_a_reaction_are_never_asked_about_one():
    g = game()
    set_zones(g, 0, hand=["Witch"], deck=["Copper"] * 3)
    set_zones(g, 1, hand=["Copper"] * 5)
    play(g, "Witch")
    assert g.state.pending is None


# -------------------------------------------------------------------- Witch
def test_witch_draws_two_and_gives_each_other_player_a_curse():
    g = game()
    set_zones(g, 0, hand=["Witch"], deck=["Copper"] * 4)
    before = g.state.supply["Curse"]
    play(g, "Witch")
    s = g.state
    assert len(s.players[0].hand) == 2
    assert s.players[1].discard == ["Curse"] and s.players[2].discard == ["Curse"]
    assert s.players[0].discard == [] and s.supply["Curse"] == before - 2


def test_witch_blocked_by_moat_and_with_empty_curse_pile():
    g = game()
    set_zones(g, 0, hand=["Witch"], deck=["Copper"] * 4)
    set_zones(g, 1, hand=["Moat", "Copper"])
    play(g, "Witch")
    answer(g, 1, "Moat")
    assert g.state.players[1].discard == [] and g.state.players[2].discard == ["Curse"]

    g2 = game(supply_overrides={"Curse": 1})
    set_zones(g2, 0, hand=["Witch"], deck=["Copper"] * 4)
    play(g2, "Witch")
    assert g2.state.players[1].discard == ["Curse"] and g2.state.players[2].discard == []
    assert g2.state.supply["Curse"] == 0


# ------------------------------------------------------------------- Bandit
def bandit(top_two, **kw):
    """Player 1's deck has these two cards on top (first = top). Returns the game."""
    g = game(**kw)
    set_zones(g, 0, hand=["Bandit"])
    set_zones(g, 1, hand=["Estate"], deck=["Curse", *reversed(top_two)], discard=[])
    set_zones(g, 2, hand=["Estate"], deck=["Curse"] * 3, discard=[])
    play(g, "Bandit")
    return g


def test_bandit_gains_gold_and_victim_chooses_between_two_treasures():
    g = bandit(["Silver", "Gold"])
    s = g.state
    assert s.players[0].discard == ["Gold"] and s.supply["Gold"] == 29
    d = s.pending.decision
    assert d.player == 1 and d.options == ("Gold", "Silver") and d.min_choices == 1
    answer(g, 1, "Silver")                                      # defender trashes the Silver
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
    g = game()
    set_zones(g, 0, hand=["Bandit"])
    set_zones(g, 1, hand=["Estate"], deck=["Silver"], discard=["Estate", "Copper"])
    set_zones(g, 2, hand=["Estate"], deck=[], discard=[])
    before = total_cards(g)
    play(g, "Bandit")
    assert total_cards(g) == before                             # cards move around, none appear or vanish
    assert g.state.players[1].set_aside == [] and g.state.pending is None

    g2 = game()
    set_zones(g2, 0, hand=["Bandit"])
    set_zones(g2, 1, hand=["Moat"], deck=["Gold", "Silver"])
    set_zones(g2, 2, hand=["Estate"], deck=["Copper", "Estate"])
    play(g2, "Bandit")
    answer(g2, 1, "Moat")
    assert g2.state.players[1].deck == ["Gold", "Silver"]       # untouched


# ------------------------------------------------------------- Throne Room
def test_throne_room_witch_attacks_twice_and_moat_is_asked_each_time():
    g = game()
    set_zones(g, 0, hand=["Throne Room", "Witch"], deck=["Copper"] * 6)
    set_zones(g, 1, hand=["Moat", "Copper"])
    play(g, "Throne Room")
    answer(g, 0, "Witch")
    answer(g, 1, "Moat")                                        # first attack: reveal Moat
    assert g.acting_player == 1                                 # second attack: asked again
    answer(g, 1)                                                # decline this time
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
    g = game(players=players, kingdom=["Bureaucrat", "Moat"])
    set_zones(g, 0, hand=["Bureaucrat"], deck=["Copper"] * 3)
    set_zones(g, 1, hand=defender_hand, deck=["Gold"] * 3)
    return g


def test_bureaucrat_gains_silver_onto_deck_and_forces_one_victory_card_back():
    g = bureaucrat_game(["Estate", "Estate", "Copper", "Copper", "Gold"])
    play(g, "Bureaucrat")
    me, them = g.state.players[0], g.state.players[1]
    assert me.deck[-1] == "Silver" and g.state.supply["Silver"] == 39      # Silver is on TOP of the deck
    assert them.deck[-1] == "Estate" and them.hand.count("Estate") == 1    # one copy, no question needed
    assert g.state.pending is None
    assert any("reveals Estate" in line for line in g.state.log)


def test_bureaucrat_defender_chooses_between_different_victory_cards():
    g = bureaucrat_game(["Estate", "Province", "Copper", "Copper", "Gold"])
    play(g, "Bureaucrat")
    d = g.state.pending.decision
    assert d.player == 1 and d.options == ("Estate", "Province") and (d.min_choices, d.max_choices) == (1, 1)
    answer(g, 1, "Province")
    assert g.state.players[1].deck[-1] == "Province" and "Province" not in g.state.players[1].hand


def test_bureaucrat_no_victory_cards_reveals_hand_and_curse_does_not_count():
    g = bureaucrat_game(["Curse", "Copper", "Copper", "Gold", "Silver"])
    play(g, "Bureaucrat")
    them = g.state.players[1]
    assert len(them.hand) == 5 and them.deck == ["Gold"] * 3
    assert any("no Victory cards" in line and "Curse" in line for line in g.state.log)


def test_bureaucrat_moat_still_lets_attacker_gain_silver():
    g = bureaucrat_game(["Moat", "Estate", "Copper", "Copper", "Gold"])
    play(g, "Bureaucrat")
    answer(g, 1, "Moat")
    assert g.state.players[1].deck == ["Gold"] * 3 and g.state.players[0].deck[-1] == "Silver"
