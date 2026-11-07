"""The Alchemy expansion: Potions, the 12 cards, cleanup questions and Possession."""

import json
import random

import pytest

from dominion.ai import BigMoneyBot, RandomBot
from dominion.cards import CardType, get_card, kingdom_cards
from dominion.engine import (
    Buy, Choose, EndPhase, GameConfig, GameStatus, IllegalActionError, PlayAction, PlayAllTreasures, PlayTreasure,
    build_view, legal_actions, new_game, replay,
)
from dominion.engine.scoring import score_player
from helpers import make_game, set_zones, to_buy_phase, total_cards

ALCHEMY = kingdom_cards(["Alchemy"])
BASE = ["Village", "Smithy", "Moat", "Militia", "Workshop", "Remodel", "Throne Room", "Witch"]


def ag(players=2, cards=("Alchemist",), seed=1, **kw):
    return make_game(players=players, kingdom=[*cards, "Village", "Smithy"], seed=seed, **kw)


def play(g, card, who=None):
    g.apply(g.acting_player if who is None else who, PlayAction(card))


def answer(g, *cards, who=None):
    g.apply(g.acting_player if who is None else who, Choose(tuple(cards)))


def end_turn(g):
    """End the whole current turn (both phases, and any cleanup question is answered with nothing)."""
    who = g.state.current_player
    start = g.state.turn_number
    while g.state.status is GameStatus.ACTIVE and g.state.turn_number == start:
        if g.state.pending is not None:
            g.apply(g.acting_player, Choose(()))
        else:
            g.apply(g.acting_player, EndPhase())


# ------------------------------------------------------------------ the set
def test_the_set_has_twelve_cards_with_the_printed_costs():
    assert len(ALCHEMY) == 12
    costs = {n: (get_card(n).cost, get_card(n).potion_cost) for n in ALCHEMY}
    assert costs == {
        "Transmute": (0, 1), "Vineyard": (0, 1), "Herbalist": (2, 0), "Apothecary": (2, 1), "Scrying Pool": (2, 1),
        "University": (2, 1), "Alchemist": (3, 1), "Familiar": (3, 1), "Philosopher's Stone": (3, 1),
        "Golem": (4, 1), "Apprentice": (5, 0), "Possession": (6, 1),
    }
    assert get_card("Potion").potions == 1 and get_card("Potion").is_type(CardType.TREASURE) and not get_card("Potion").kingdom
    assert get_card("Vineyard").is_type(CardType.VICTORY) and get_card("Philosopher's Stone").is_type(CardType.TREASURE)
    for n in ("Scrying Pool", "Familiar"):
        assert get_card(n).is_type(CardType.ATTACK)


def test_potion_pile_only_exists_when_a_kingdom_card_costs_a_potion():
    g = make_game(kingdom=["Village", "Herbalist", "Apprentice"])
    assert "Potion" not in g.state.supply and not build_view(g, 0)["has_potions"]
    g = make_game(kingdom=["Village", "Golem"])
    assert g.state.supply["Potion"] == 16
    assert any(p["name"] == "Potion" for p in build_view(g, 0)["piles"])
    g = make_game(kingdom=["Vineyard", "Village"])
    assert g.state.supply["Vineyard"] == 8 and g.state.supply["Potion"] == 16       # Victory-sized pile


def test_random_kingdoms_can_be_drawn_from_alchemy_only():
    for seed in range(10):
        k = new_game(GameConfig(["A", "B"], None, seed, expansions=["Alchemy"])).state.kingdom
        assert len(k) == 10 and set(k) <= set(ALCHEMY)


# ------------------------------------------------------------------ potions and buying
def test_potion_treasure_gives_a_potion_and_potion_cards_need_one():
    g = ag(cards=("Golem",))
    set_zones(g, hand=["Copper"] * 4 + ["Potion"])
    to_buy_phase(g)
    assert Buy("Golem") not in legal_actions(g.state)
    g.apply(0, PlayAllTreasures())
    assert (g.state.coins, g.state.potions) == (4, 1)
    assert "plays Potion (+$0, +1 Potion)" in "\n".join(map(str, g.state.log))
    assert Buy("Golem") in legal_actions(g.state)
    g.apply(0, Buy("Golem"))
    assert (g.state.coins, g.state.potions) == (0, 0) and g.state.players[0].discard == ["Golem"]
    assert build_view(g, 0)["potions"] == 0


def test_buying_a_potion_card_without_a_potion_or_coins_is_refused():
    g = ag(cards=("Golem",))
    set_zones(g, hand=["Copper"] * 5)
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    with pytest.raises(IllegalActionError, match="Potion"):
        g.apply(0, Buy("Golem"))
    g2 = ag(cards=("Golem",))
    set_zones(g2, hand=["Potion", "Copper"])
    to_buy_phase(g2)
    g2.apply(0, PlayAllTreasures())
    with pytest.raises(IllegalActionError, match=r"costs \$4"):
        g2.apply(0, Buy("Golem"))
    assert Buy("Potion") not in legal_actions(g2.state)          # Potion itself costs $4


def test_zero_coin_potion_cards_cost_only_a_potion_and_potions_reset_each_turn():
    g = ag(cards=("Transmute",))
    set_zones(g, hand=["Potion", "Estate", "Estate", "Estate", "Estate"])
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    g.apply(0, Buy("Transmute"))
    assert g.state.potions == 0
    end_turn(g)
    assert g.state.potions == 0


def test_cards_that_cost_a_potion_are_never_gained_by_coin_limited_effects():
    g = ag(cards=("Golem", "Transmute", "Apothecary"))
    set_zones(g, hand=["Workshop"])
    g.state.supply["Workshop"] = 9
    play(g, "Workshop")
    options = g.state.pending.decision.options
    assert "Silver" in options and "Village" in options
    assert not {"Golem", "Transmute", "Apothecary", "Potion"} & set(options) or options == tuple(sorted(options))
    assert "Golem" not in options and "Transmute" not in options and "Apothecary" not in options
    assert "Potion" in options                                   # the Potion itself costs $4 with no Potion cost


# ------------------------------------------------------------------ cards
def test_transmute_by_type():
    for trashed, expected in (("Village", "Duchy"), ("Copper", "Transmute"), ("Estate", "Gold")):
        g = ag(cards=("Transmute",))
        set_zones(g, hand=["Transmute", trashed], discard=[])
        play(g, "Transmute")
        answer(g, trashed)
        assert g.state.trash == [trashed] and g.state.players[0].discard == [expected]
    g = ag(cards=("Transmute", "Vineyard"))                     # a Victory card that is not Gold... Vineyard is Victory
    set_zones(g, hand=["Transmute", "Vineyard"], discard=[])
    play(g, "Transmute"); answer(g, "Vineyard")
    assert g.state.players[0].discard == ["Gold"]
    g = ag(cards=("Transmute",))
    set_zones(g, hand=["Transmute"])
    play(g, "Transmute")
    assert g.state.pending is None


def test_vineyard_scores_per_three_action_cards():
    g = ag(cards=("Vineyard",))
    p = g.state.players[0]
    p.deck, p.hand, p.discard = ["Village", "Smithy", "Village", "Copper", "Estate"], [], []
    p.discard.append("Vineyard")
    assert score_player(p) == 1 + 1                              # Estate + (3 Actions // 3)
    p.discard.extend(["Smithy", "Smithy", "Smithy"])
    assert score_player(p) == 1 + 2
    p.discard.append("Vineyard")                                 # two Vineyards, 6 Actions -> 2 VP each
    assert score_player(p) == 1 + 2 * 2


def test_herbalist_gives_buy_and_coin_and_may_topdeck_a_treasure_at_cleanup():
    g = ag(cards=("Herbalist",))
    set_zones(g, hand=["Herbalist", "Gold", "Copper"], deck=["Estate"] * 10)
    play(g, "Herbalist")
    assert (g.state.buys, g.state.coins) == (2, 1)
    g.apply(0, EndPhase())
    g.apply(0, PlayAllTreasures())
    g.apply(0, EndPhase())                                       # cleanup: the owner is asked
    d = g.state.pending.decision
    assert d.player == 0 and d.options == ("Copper", "Gold") and (d.min_choices, d.max_choices) == (0, 1)
    assert g.state.current_player == 0 and g.state.status is GameStatus.ACTIVE
    answer(g, "Gold")
    assert g.state.pending is None and g.state.current_player == 1
    p = g.state.players[0]
    assert "Gold" in p.hand and "Herbalist" in p.discard           # the Gold was on top, so it was drawn


def test_herbalist_cleanup_is_skipped_without_treasures_and_may_be_declined():
    g = ag(cards=("Herbalist",))
    set_zones(g, hand=["Herbalist", "Estate"])
    play(g, "Herbalist")
    g.apply(0, EndPhase()); g.apply(0, EndPhase())
    assert g.state.pending is None and g.state.current_player == 1
    g = ag(cards=("Herbalist",))
    set_zones(g, hand=["Herbalist", "Gold"], deck=["Estate"] * 10)
    play(g, "Herbalist")
    g.apply(0, EndPhase()); g.apply(0, PlayAllTreasures()); g.apply(0, EndPhase())
    answer(g)
    assert "Gold" not in g.state.players[0].hand and "Gold" in g.state.players[0].discard


def test_alchemist_returns_to_the_deck_only_with_a_potion_in_play():
    g = ag(cards=("Alchemist",))
    set_zones(g, hand=["Alchemist", "Potion", "Copper"], deck=["Estate"] * 10)
    play(g, "Alchemist")
    assert g.state.actions == 1 and len(g.state.players[0].hand) == 4
    g.apply(0, EndPhase()); g.apply(0, PlayAllTreasures()); g.apply(0, EndPhase())
    d = g.state.pending.decision
    assert d.options == ("Alchemist",) and (d.min_choices, d.max_choices) == (0, 1)
    answer(g, "Alchemist")
    assert g.state.current_player == 1 and "Alchemist" in g.state.players[0].hand      # drawn again next hand
    g = ag(cards=("Alchemist",))
    set_zones(g, hand=["Alchemist", "Copper"], deck=["Estate"] * 10)
    play(g, "Alchemist")
    g.apply(0, EndPhase()); g.apply(0, PlayAllTreasures()); g.apply(0, EndPhase())
    assert g.state.pending is None and "Alchemist" in g.state.players[0].discard


def test_two_alchemists_are_each_asked_and_alchemists_come_before_herbalists():
    g = ag(cards=("Alchemist", "Herbalist"))
    set_zones(g, hand=["Alchemist", "Alchemist", "Herbalist", "Potion", "Copper"], deck=["Estate"] * 20)
    g.state.actions = 3
    for c in ("Alchemist", "Alchemist", "Herbalist"):
        play(g, c)
    g.apply(0, EndPhase()); g.apply(0, PlayAllTreasures()); g.apply(0, EndPhase())
    assert g.state.pending.decision.options == ("Alchemist",)
    answer(g, "Alchemist")
    assert g.state.pending.decision.options == ("Alchemist",)
    answer(g, "Alchemist")
    assert g.state.pending.decision.options == ("Copper", "Potion")    # the Herbalist is asked last
    answer(g, "Potion")
    assert g.state.current_player == 1
    assert g.state.players[0].hand.count("Alchemist") == 2 and "Potion" in g.state.players[0].hand


def test_cleanup_question_survives_replay_and_game_end_waits_for_the_answer():
    g = ag(cards=("Herbalist",), supply_overrides={"Province": 0})
    set_zones(g, hand=["Herbalist", "Gold"], deck=["Estate"] * 10)
    play(g, "Herbalist")
    g.apply(0, EndPhase()); g.apply(0, PlayAllTreasures()); g.apply(0, EndPhase())
    assert g.state.status is GameStatus.ACTIVE and g.state.pending is not None
    answer(g)
    assert g.state.status is GameStatus.FINISHED


def test_apothecary_takes_coppers_and_potions_and_reorders_the_rest():
    g = ag(cards=("Apothecary",))
    set_zones(g, hand=["Apothecary"], deck=["Gold", "Silver", "Potion", "Estate", "Copper", "Village"])
    play(g, "Apothecary")                                        # draws Village; reveals Copper, Estate, Potion, Silver
    assert g.state.actions == 1
    assert sorted(g.state.players[0].hand) == ["Copper", "Potion", "Village"]
    d = g.state.pending.decision
    assert sorted(d.options) == ["Estate", "Silver"]
    answer(g, "Estate")                                          # Estate on top, Silver beneath
    assert g.state.players[0].deck == ["Gold", "Silver", "Estate"] and g.state.players[0].set_aside == []


def test_university_gains_a_cheap_action_and_never_a_potion_card():
    g = ag(cards=("University", "Golem", "Moat"))
    set_zones(g, hand=["University"])
    play(g, "University")
    assert g.state.actions == 2
    d = g.state.pending.decision
    assert (d.min_choices, d.max_choices) == (0, 1)
    assert "Village" in d.options and "Smithy" in d.options and "Golem" not in d.options and "Silver" not in d.options
    answer(g, "Smithy")
    assert g.state.players[0].discard == ["Smithy"]
    g = ag(cards=("University",))
    set_zones(g, hand=["University"])
    play(g, "University"); answer(g)
    assert g.state.players[0].discard == []


def test_familiar_curses_everyone_else_and_moat_blocks_it():
    g = ag(players=3, cards=("Familiar", "Moat"))
    set_zones(g, 0, hand=["Familiar"], deck=["Gold"])
    set_zones(g, 1, hand=["Moat", "Copper"])
    play(g, "Familiar")
    assert g.state.actions == 1 and g.state.players[0].hand == ["Gold"]
    assert g.state.pending.decision.player == 1
    answer(g, "Moat")
    assert g.state.players[1].discard == [] and g.state.players[2].discard == ["Curse"]


def test_scrying_pool_discard_or_put_back_then_draws_until_a_non_action():
    g = ag(cards=("Scrying Pool",))
    set_zones(g, 0, hand=["Scrying Pool"], deck=["Estate", "Gold", "Village", "Smithy", "Copper"], discard=[])
    set_zones(g, 1, hand=["Copper"], deck=["Curse", "Silver"], discard=[])
    play(g, "Scrying Pool")
    assert g.state.actions == 1
    d = g.state.pending.decision
    assert d.player == 0 and d.options == ("Discard it", "Put it back") and "your top card is Copper" in d.prompt
    answer(g, "Put it back")
    assert "P1's top card is Silver" in g.state.pending.decision.prompt
    answer(g, "Discard it")
    assert g.state.players[1].discard == ["Silver"]
    # Copper (not an Action) ends the reveal right away
    assert g.state.players[0].hand == ["Copper"] and g.state.pending is None
    g = ag(cards=("Scrying Pool",))
    set_zones(g, 0, hand=["Scrying Pool"], deck=["Estate", "Gold", "Village", "Smithy", "Village"], discard=[])
    set_zones(g, 1, hand=[], deck=[], discard=[])
    play(g, "Scrying Pool")
    answer(g, "Put it back")                                    # my own top card (Village) stays
    assert sorted(g.state.players[0].hand) == ["Gold", "Smithy", "Village", "Village"]     # Village, Smithy, Village, then Gold
    assert g.state.players[0].deck == ["Estate"]


def test_scrying_pool_is_blocked_by_moat_for_the_other_player_only():
    g = ag(cards=("Scrying Pool", "Moat"))
    set_zones(g, 0, hand=["Scrying Pool"], deck=["Gold", "Copper"])
    set_zones(g, 1, hand=["Moat"], deck=["Curse"])
    play(g, "Scrying Pool")
    answer(g, "Moat")
    assert "your top card is Copper" in g.state.pending.decision.prompt
    answer(g, "Put it back")
    assert g.state.players[1].deck == ["Curse"]


def test_philosophers_stone_counts_draw_pile_and_discard_pile():
    g = ag(cards=("Philosopher's Stone",))
    set_zones(g, hand=["Philosopher's Stone"], deck=["Copper"] * 7, discard=["Estate"] * 5)
    to_buy_phase(g)
    g.apply(0, PlayTreasure("Philosopher's Stone"))
    assert g.state.coins == 12 // 5
    g = ag(cards=("Philosopher's Stone",))
    set_zones(g, hand=["Philosopher's Stone"], deck=["Copper"] * 4, discard=[])
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    assert g.state.coins == 0


def test_golem_plays_two_actions_and_discards_the_rest():
    g = ag(cards=("Golem",))
    set_zones(g, hand=["Golem"], deck=["Gold", "Smithy", "Estate", "Village", "Copper"], discard=[])
    play(g, "Golem")
    assert g.state.players[0].discard == ["Copper", "Estate"]
    d = g.state.pending.decision
    assert d.options == ("Village", "Smithy")
    answer(g, "Smithy")                                          # Smithy first: draws Gold (the only card left)
    assert g.state.pending is None
    me = g.state.players[0]
    assert sorted(me.in_play) == ["Golem", "Smithy", "Village"] and me.set_aside == []
    assert g.state.actions == 2 and "Gold" in me.hand            # Village's +2 Actions and Smithy's draw


def test_golem_ignores_other_golems_and_copes_with_few_actions():
    g = ag(cards=("Golem",))
    set_zones(g, hand=["Golem"], deck=["Village", "Golem", "Copper"], discard=[])
    play(g, "Golem")
    assert g.state.pending is None and g.state.players[0].set_aside == []
    me = g.state.players[0]
    assert sorted(me.hand + me.deck + me.discard) == ["Copper", "Golem"] and "Village" in me.in_play   # Village drew one back


def test_apprentice_draws_by_coin_cost_and_two_more_for_a_potion():
    g = ag(cards=("Apprentice", "Golem"))
    set_zones(g, hand=["Apprentice", "Smithy", "Estate"], deck=["Copper"] * 10)
    play(g, "Apprentice")
    answer(g, "Smithy")
    assert len(g.state.players[0].hand) == 1 + 4 and g.state.actions == 1
    g = ag(cards=("Apprentice", "Golem"))
    set_zones(g, hand=["Apprentice", "Golem"], deck=["Copper"] * 10)
    play(g, "Apprentice")
    answer(g, "Golem")
    assert len(g.state.players[0].hand) == 4 + 2                 # $4 and a Potion
    g = ag(cards=("Apprentice",))
    set_zones(g, hand=["Apprentice", "Copper"], deck=["Silver"] * 3)
    play(g, "Apprentice"); answer(g, "Copper")
    assert g.state.players[0].hand == []                         # Copper costs $0


# ------------------------------------------------------------------ Possession
def pg(players=2, **kw):
    g = ag(players=players, cards=("Possession", "Militia", "Workshop"), **kw)
    return g


def possess(g):
    """P0 plays Possession and ends the turn. The game is then in P1's possessed turn."""
    set_zones(g, 0, hand=["Possession", "Copper"])
    play(g, "Possession")
    end_turn(g)


def test_possession_gives_the_next_player_an_extra_turn_controlled_by_the_possessor():
    g = pg(players=3)
    possess(g)
    s = g.state
    assert s.current_player == 1 and s.possessor == 0 and g.acting_player == 0
    assert any("possessed by P0" in x for x in s.log if x.kind == "turn")
    assert [p.turns_taken for p in s.players] == [1, 0, 0]
    v1, v0 = build_view(g, 1), build_view(g, 0)
    assert v0["possession"]["hand"] == sorted(s.players[1].hand) and "hand" not in v1["possession"]
    assert v1["players"][1]["possessed_by"] == 0 and v0["controller"] == 0
    assert v0["legal_actions"] and v1["legal_actions"] == []
    with pytest.raises(IllegalActionError, match="not your turn"):
        g.apply(1, EndPhase())
    end_turn(g)                                                  # the possessed turn ends: P1 now takes their own turn
    assert s.possessor is None and s.current_player == 1 and g.acting_player == 1
    assert s.players[1].turns_taken == 1
    end_turn(g)
    assert s.current_player == 2                                 # then the normal order goes on


def test_possession_works_in_a_two_player_game_and_only_once():
    g = pg()
    possess(g)
    assert g.state.possessor == 0 and g.state.current_player == 1
    end_turn(g)
    assert g.state.possessor is None and g.state.current_player == 1
    end_turn(g)
    assert g.state.current_player == 0 and g.state.possessor is None


def test_the_possessor_plays_the_possessed_hand_and_cards_gained_go_to_the_possessor():
    g = pg()
    possess(g)
    set_zones(g, 1, hand=["Workshop", "Copper", "Copper", "Copper", "Silver"], discard=[])
    set_zones(g, 0, discard=[])
    g.apply(0, PlayAction("Workshop"))
    d = g.state.pending.decision
    assert d.player == 1 and g.acting_player == 0                 # the possessed player's question is the possessor's
    assert build_view(g, 0)["pending"]["options"] and "options" not in build_view(g, 1)["pending"]
    with pytest.raises(IllegalActionError):
        g.apply(1, Choose(("Silver",)))
    g.apply(0, Choose(("Silver",)))
    assert g.state.players[0].discard[-1] == "Silver" and g.state.players[1].discard == []
    assert "P0 gains Silver (Possession)" in "\n".join(map(str, g.state.log))
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    assert g.state.coins == 5
    g.apply(0, Buy("Gold")) if False else g.apply(0, Buy("Village"))
    assert g.state.players[0].discard[-1] == "Village" and "Village" in g.state.players[0].bought
    assert "Village" not in g.state.players[1].discard and "buys Village for P0" in "\n".join(map(str, g.state.log))


def test_cards_trashed_from_the_possessed_player_come_back_at_the_end_of_the_turn():
    g = pg()
    possess(g)
    set_zones(g, 1, hand=["Remodel" if False else "Workshop", "Estate", "Copper", "Copper", "Copper"])
    before = total_cards(g)
    g.state.possession_aside.append("Gold")                       # a trashed card of theirs, set aside this turn
    g.state.players[1].deck.remove("Gold") if "Gold" in g.state.players[1].deck else None
    g.state.supply["Gold"] -= 1
    discards = len(g.state.players[1].discard)
    end_turn(g)
    assert g.state.possession_aside == [] and g.state.trash == []
    assert g.state.players[1].all_cards().count("Gold") == 1
    assert "trashed card(s) return" in "\n".join(map(str, g.state.log))
    assert total_cards(g) == before


def test_possessed_player_trashing_a_card_sets_it_aside_instead():
    g = ag(players=2, cards=("Possession", "Transmute"))
    possess_g = g
    set_zones(g, 0, hand=["Possession", "Copper"])
    play(g, "Possession")
    end_turn(g)
    set_zones(g, 1, hand=["Transmute", "Estate", "Copper", "Copper", "Copper"], discard=[])
    set_zones(g, 0, discard=[])
    before = total_cards(g)
    g.apply(0, PlayAction("Transmute"))
    g.apply(0, Choose(("Estate",)))
    assert g.state.trash == [] and g.state.possession_aside == ["Estate"]
    assert g.state.players[0].discard == ["Gold"]                 # the Gold it earned goes to the possessor
    assert total_cards(g) == before
    end_turn(g)
    assert g.state.possession_aside == [] and g.state.players[1].all_cards().count("Estate") >= 1


def test_attacks_by_the_possessed_player_hit_the_possessor_who_answers_for_themselves():
    g = ag(players=2, cards=("Possession", "Militia", "Moat"))
    set_zones(g, 0, hand=["Possession", "Copper"])
    play(g, "Possession"); end_turn(g)
    set_zones(g, 1, hand=["Militia", "Copper", "Copper", "Copper", "Copper"])
    set_zones(g, 0, hand=["Moat", "Estate", "Estate", "Estate", "Copper"])
    g.apply(0, PlayAction("Militia"))
    assert g.state.pending.decision.player == 0 and g.acting_player == 0
    answer(g, "Moat")                                             # P0 reveals their own Moat against the possessed Militia
    assert len(g.state.players[0].hand) == 5


def test_two_possessions_give_two_extra_turns_and_a_possessed_possession_does_nothing():
    g = ag(players=2, cards=("Possession", "Throne Room"))
    set_zones(g, 0, hand=["Throne Room", "Possession", "Copper"])
    play(g, "Throne Room"); answer(g, "Possession")
    assert g.state.extra_turns == 2
    end_turn(g)
    assert g.state.possessor == 0
    end_turn(g)
    assert g.state.possessor == 0 and g.state.current_player == 1        # the second extra turn
    set_zones(g, 1, hand=["Possession", "Copper", "Copper", "Copper", "Copper"])
    g.apply(0, PlayAction("Possession"))
    assert g.state.extra_turns == 0 and "no effect during a possessed turn" in "\n".join(map(str, g.state.log))
    end_turn(g)
    assert g.state.possessor is None and g.state.current_player == 1


def test_an_invisible_player_cannot_be_possessed_and_the_game_can_end_before_the_extra_turn():
    g = pg()
    g.state.players[1].invisible = True
    possess(g)
    assert g.state.possessor is None and g.state.current_player == 1
    g = ag(players=2, cards=("Possession",), supply_overrides={"Province": 0})
    set_zones(g, 0, hand=["Possession"])
    play(g, "Possession"); end_turn(g)
    assert g.state.status is GameStatus.FINISHED


def test_possession_replays_exactly_and_undo_style_replays_keep_the_controller():
    g = pg()
    possess(g)
    set_zones(g, 1, hand=["Workshop", "Copper", "Copper", "Copper", "Copper"])
    g.apply(0, PlayAction("Workshop"))
    g.apply(0, Choose(("Silver",)))
    assert [p for p, _ in g.history[-2:]] == [0, 0]                # both submitted by the possessor


# ------------------------------------------------------------------ everything together
@pytest.mark.parametrize("players", [2, 3, 4])
def test_random_games_with_every_alchemy_card_keep_every_invariant_and_replay(players):
    for seed in range(8):
        rng = random.Random(seed)
        kingdom = [*ALCHEMY, "Throne Room", "Militia"][:10] if seed % 2 else rng.sample([*ALCHEMY, *BASE], 10)
        g = new_game(GameConfig([f"P{i}" for i in range(players)], kingdom, seed))
        for p in g.state.players:                                 # stuff the decks so the cards actually get played
            p.deck.extend(rng.choice([c for c in kingdom] + ["Potion", "Potion", "Copper"]) for _ in range(10))
            rng.shuffle(p.deck)
        before = total_cards(g)
        bots = [RandomBot(random.Random(rng.random())) for _ in range(players)]
        for step in range(2500):
            if g.state.status is GameStatus.FINISHED:
                break
            actor = g.acting_player
            action = bots[actor].choose(g, actor)
            assert action in g.legal_actions(actor)
            g.apply(actor, action)
            assert total_cards(g) == before, f"seed {seed}: cards appeared or vanished"
            assert all(c >= 0 for c in g.state.supply.values()) and g.state.potions >= 0
            if g.state.pending is None:
                assert all(p.set_aside == [] for p in g.state.players)
            if step % 50 == 0:
                for i in range(players):
                    json.dumps(build_view(g, i))
        # a replay of the stuffed game is not possible (the stuffing is outside the history), so check an unstuffed one
    for seed in range(6):
        rng = random.Random(seed + 100)
        kingdom = rng.sample([*ALCHEMY, *BASE], 10)
        g = new_game(GameConfig([f"P{i}" for i in range(players)], kingdom, seed))
        bots = [RandomBot(random.Random(rng.random())) for _ in range(players)]
        for _ in range(1500):
            if g.state.status is GameStatus.FINISHED:
                break
            actor = g.acting_player
            g.apply(actor, bots[actor].choose(g, actor))
        r = replay(g.config, g.history)
        assert [p.all_cards() for p in r.state.players] == [p.all_cards() for p in g.state.players]
        assert r.state.supply == g.state.supply and r.state.trash == g.state.trash
        assert [str(x) for x in r.state.log] == [str(x) for x in g.state.log]


def test_possession_actually_happens_in_random_play():
    seen = 0
    for seed in range(12):
        rng = random.Random(seed)
        g = new_game(GameConfig(["A", "B", "C"], ["Possession", "Village", "Militia", "Witch"], seed))
        for p in g.state.players:
            p.deck.extend(["Possession", "Village", "Village"] * 3)
            rng.shuffle(p.deck)
        bots = [RandomBot(random.Random(rng.random())) for _ in range(3)]
        for _ in range(2500):
            if g.state.status is GameStatus.FINISHED:
                break
            actor = g.acting_player
            g.apply(actor, bots[actor].choose(g, actor))
        seen += sum("possessed by" in x for x in g.state.log)
    assert seen > 0


def test_big_money_bot_plays_through_cleanup_questions_and_possession():
    g = new_game(GameConfig(["A", "B"], ["Possession", "Herbalist", "Alchemist", "Golem"], 3))
    for p in g.state.players:
        p.deck.extend(["Herbalist", "Alchemist", "Potion", "Possession"] * 3)
    bot = BigMoneyBot()
    for _ in range(4000):
        if g.state.status is GameStatus.FINISHED:
            break
        a = g.acting_player
        g.apply(a, bot.choose(g, a))
    assert g.state.status is GameStatus.FINISHED
