"""Exodia, Invisibility Cloak, Midas Touch, Fortnite, Monopoly, Grand Theft Auto, Roofie, Chance Time."""

import random
from collections import Counter

import pytest

from dominion.ai import RandomBot
from dominion.cards import CardType, get_card
from dominion.cards.registry import catastrophe_cards, companion_cards, fenced_cards, special_cards
from dominion.cards.special import CHANCE_OUTCOMES
from dominion.engine import (
    Buy, Cheat, Choose, EndPhase, GameConfig, GameStatus, IllegalActionError, PlayAction, PlayAllTreasures,
    build_view, legal_actions, new_game, replay,
)
from dominion.engine.constants import EXODIA_PIECES
from dominion.engine.effects import EffectContext
from helpers import make_game, set_zones, to_buy_phase, total_cards
from test_bots import play_checked

KINGDOM = ["Moat", "Village", "Smithy", "Militia", "Workshop", "Council Room", "Witch", "Masquerade"]
HEAD, RA, LA, RL, LL = EXODIA_PIECES


def g_with(cards, players=3, **kw):
    return make_game(players=players, kingdom=KINGDOM, catastrophes=list(cards), **kw)


def play(g, card, player=0):
    g.apply(player, PlayAction(card))


def answer(g, player, *cards):
    g.apply(player, Choose(tuple(cards)))


def log_text(g):
    return "\n".join(str(x) for x in g.state.log)


def end_turn(g):
    """Finish the current player's turn from whichever phase they are in."""
    p = g.state.current_player
    while g.state.current_player == p and g.state.status is GameStatus.ACTIVE:
        g.apply(p, EndPhase())


# ================================================================== Exodia
def test_exodia_has_five_pieces_and_the_four_limbs_come_with_the_head():
    assert len(EXODIA_PIECES) == 5 and len(set(EXODIA_PIECES)) == 5
    assert HEAD in fenced_cards() and not set(companion_cards()) & set(fenced_cards())
    assert set(companion_cards()) == set(EXODIA_PIECES[1:]) and get_card(HEAD).companions == tuple(EXODIA_PIECES[1:])
    assert [get_card(n).cost for n in EXODIA_PIECES] == [5, 3, 3, 3, 3]
    for n in EXODIA_PIECES:
        assert get_card(n).is_type(CardType.SPECIAL) and not get_card(n).is_type(CardType.ACTION)


def test_picking_exodia_puts_all_five_piles_in_the_game_but_counts_as_one_pick():
    g = g_with([HEAD, "Rosebud"])
    assert all(g.state.supply[n] == 2 for n in EXODIA_PIECES) and g.state.supply["Rosebud"] == 2
    assert set(EXODIA_PIECES) <= set(g.state.catastrophes)
    assert g.config.catastrophes == [HEAD, "Rosebud"]            # the config keeps only what was picked
    piles = {p["name"]: p for p in build_view(g, 0)["piles"]}
    assert all(piles[n]["catastrophe"] for n in EXODIA_PIECES)
    g3 = g_with([HEAD, "Rosebud", "Time Stop"])                   # any number of picks is fine
    assert g3.state.supply["Time Stop"] == 2 and g3.config.catastrophes == [HEAD, "Rosebud", "Time Stop"]
    with pytest.raises(ValueError, match="comes with|not a"):
        g_with([RA])                                              # a limb cannot be picked alone
    r = replay(g.config, [])
    assert set(r.state.catastrophes) == set(g.state.catastrophes)


def test_empty_exodia_piles_never_end_the_game():
    g = g_with([HEAD])
    for n in EXODIA_PIECES:
        g.state.supply[n] = 0
    g.state.supply["Village"] = 0
    g.state.supply["Moat"] = 0
    from dominion.engine.rules import is_game_over
    assert not is_game_over(g.state)


def test_all_five_pieces_in_hand_win_instantly():
    g = g_with([HEAD], players=2)
    set_zones(g, 0, hand=["Village", RA, LA, RL, LL], deck=["Copper", HEAD])       # the top of the deck is the end of the list
    play(g, "Village")                                            # draws the head: five pieces
    s = g.state
    assert s.status is GameStatus.FINISHED and s.winners == [0]
    assert "holding all five pieces of Exodia" in s.end_reason
    assert "EXODIA!" in log_text(g) and any(l.kind == "special" and "EXODIA!" in l for l in s.log)
    v = build_view(g, 1)
    assert v["status"] == "finished" and v["winners"] == [0] and v["end_reason"] == s.end_reason and "stats" in v


def test_exodia_needs_all_five_different_pieces_in_the_hand_at_the_same_time():
    g = g_with([HEAD], players=2)
    set_zones(g, 0, hand=["Village", RA, LA, RL, "Copper"], deck=[LA, "Copper"])          # a second Left Arm, no Left Leg... no head
    play(g, "Village")
    assert g.state.status is GameStatus.ACTIVE
    g = g_with([HEAD], players=2)
    set_zones(g, 0, hand=[HEAD, RA, LA, RL, "Copper"], discard=[LL], deck=[])             # fifth piece in the discard pile
    assert g.state.status is GameStatus.ACTIVE
    g.apply(0, EndPhase())
    assert g.state.status is GameStatus.ACTIVE                    # pieces in the Buy phase, still not complete
    g = g_with([HEAD], players=2)
    set_zones(g, 0, hand=[HEAD, RA, LA, RL, LL])                  # set up directly: checked after the next action
    g.apply(0, EndPhase())
    assert g.state.status is GameStatus.FINISHED and g.state.winners == [0]


def test_an_opponent_can_win_on_someone_elses_turn_and_exodia_beats_the_normal_scores():
    g = g_with([HEAD], players=2)
    set_zones(g, 0, hand=["Council Room"], deck=["Gold"] * 6)
    set_zones(g, 1, hand=[HEAD, RA, LA, RL], deck=[LL])
    g.state.players[0].discard.extend(["Province"] * 5)           # P0 is far ahead on points
    play(g, "Council Room")                                       # each other player draws a card: P1 gets the last piece
    assert g.state.status is GameStatus.FINISHED and g.state.winners == [1]


def test_exodia_win_survives_a_replay():
    g = new_game(GameConfig(["A", "B"], KINGDOM, 3, catastrophes=[HEAD], cheats=True))
    g.apply(0, EndPhase())
    g.apply(0, Cheat("coins")); g.apply(0, Cheat("buys"))
    for n in EXODIA_PIECES:
        g.apply(0, Buy(n))
    r = replay(g.config, g.history)
    assert r.state.supply == g.state.supply and r.state.players[0].gained == g.state.players[0].gained


# ================================================================== Invisibility Cloak
def test_invisibility_cloak_is_permanent_and_blocks_attacks_without_questions():
    g = g_with(["Invisibility Cloak"], players=3)
    set_zones(g, 0, hand=["Invisibility Cloak"])
    play(g, "Invisibility Cloak")
    assert g.state.players[0].invisible and g.state.trash == ["Invisibility Cloak"]
    assert "puts on the Invisibility Cloak" in log_text(g)
    assert build_view(g, 1)["players"][0]["invisible"] is True
    for _ in range(9):
        end_turn(g)
    assert g.state.players[0].invisible
    set_zones(g, g.state.current_player, hand=["Militia"])
    g.state.actions = 1
    cur = g.state.current_player
    if cur == 0:
        end_turn(g); cur = g.state.current_player
    set_zones(g, cur, hand=["Militia"])
    set_zones(g, 0, hand=["Moat"] + ["Copper"] * 4)
    play(g, "Militia", cur)
    assert "P0 is protected and unaffected" in log_text(g)
    assert len(g.state.players[0].hand) == 5


def test_cataclysm_leaves_the_cloaked_player_alone():
    g = g_with(["Cataclysm"], players=3)
    g.state.players[1].invisible = True
    set_zones(g, 0, hand=["Cataclysm", "Gold"], deck=["Gold"] * 3)
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Silver"] * 5, discard=["Estate"] * 2)
    set_zones(g, 2, hand=["Copper"] * 5, deck=["Copper"] * 5)
    keep = (list(g.state.players[1].hand), list(g.state.players[1].deck), list(g.state.players[1].discard))
    before = total_cards(g)
    play(g, "Cataclysm")
    p1 = g.state.players[1]
    assert (p1.hand, p1.deck, p1.discard) == keep
    assert total_cards(g) == before
    assert "P1 is invisible and keeps their cards" in log_text(g)
    assert sum(1 for l in g.state.log if l.kind == "summary") == 2          # only P0 and P2 took part


def test_cloaked_player_who_plays_cataclysm_still_takes_part():
    g = g_with(["Cataclysm"], players=2)
    g.state.players[0].invisible = True
    set_zones(g, 0, hand=["Cataclysm", "Gold"], deck=["Gold"] * 3)
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Copper"] * 5)
    play(g, "Cataclysm")
    assert sum(1 for l in g.state.log if l.kind == "summary") == 2


def test_masquerade_passes_around_a_cloaked_player():
    g = g_with(["Invisibility Cloak"], players=3)
    g.state.players[1].invisible = True
    set_zones(g, 0, hand=["Masquerade", "Copper"], deck=["Silver", "Silver"])
    set_zones(g, 1, hand=["Gold", "Gold"])
    set_zones(g, 2, hand=["Duchy"])
    play(g, "Masquerade")
    d = g.state.pending.decision
    assert d.player == 0                                          # P1 is asked nothing
    g.apply(0, Choose(("Copper",)))
    assert g.state.pending.decision.player == 2
    g.apply(2, Choose(("Duchy",)))
    assert sorted(g.state.players[2].hand) == ["Copper"]         # P0's card skipped the cloaked P1
    assert sorted(g.state.players[0].hand) == ["Duchy", "Silver", "Silver"]
    assert g.state.players[1].hand == ["Gold", "Gold"]


def test_walls_do_not_apply_to_a_cloaked_player():
    g = g_with(["Fortnite", "Invisibility Cloak"], players=3)
    set_zones(g, 0, hand=["Fortnite"])
    play(g, "Fortnite")
    answer(g, 0, "Gold")
    g.state.players[2].invisible = True
    end_turn(g)                                                   # P1's turn
    g.state.coins = 9
    to_buy_phase(g)
    assert Buy("Gold") not in legal_actions(g.state)
    end_turn(g)                                                   # P2 (cloaked): not blocked
    g.state.coins = 9
    to_buy_phase(g)
    assert Buy("Gold") in legal_actions(g.state)


# ================================================================== Midas Touch
def test_midas_touch_turns_every_treasure_into_a_gold_for_the_turn():
    g = g_with(["Midas Touch"], players=2)
    set_zones(g, 0, hand=["Midas Touch", "Copper", "Copper", "Silver", "Gold"])
    play(g, "Midas Touch")
    assert g.state.midas and g.state.trash == ["Midas Touch"]
    assert build_view(g, 1)["midas"] is True
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    assert g.state.coins == 12                                    # four Treasures at $3 each
    assert "plays Copper as Gold (+$3)" in log_text(g) and "plays Gold (+$3)" in log_text(g)
    end_turn(g)
    assert g.state.midas is False
    set_zones(g, 1, hand=["Copper"] * 5)
    to_buy_phase(g)
    g.apply(1, PlayAllTreasures())
    assert g.state.coins == 5                                     # back to normal on the next turn


def test_midas_touch_without_playing_it_changes_nothing_and_harem_counts():
    g = g_with(["Midas Touch"], players=2)
    set_zones(g, 0, hand=["Copper"] * 5)
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    assert g.state.coins == 5
    g = make_game(players=2, kingdom=["Harem", "Village"], catastrophes=["Midas Touch"])
    set_zones(g, 0, hand=["Midas Touch", "Harem", "Copper"])
    play(g, "Midas Touch")
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    assert g.state.coins == 6


def test_midas_touch_is_single_use_and_does_not_stack_oddly_with_throne_room():
    g = make_game(players=2, kingdom=["Throne Room"], catastrophes=["Midas Touch"])
    set_zones(g, 0, hand=["Throne Room", "Midas Touch", "Copper"])
    play(g, "Throne Room")
    answer(g, 0, "Midas Touch")
    assert g.state.trash == ["Midas Touch"] and g.state.pending is None
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    assert g.state.coins == 3


# ================================================================== Fortnite
def test_fortnite_walls_up_to_three_piles_and_blocks_other_players_buying_and_gaining():
    g = g_with(["Fortnite"], players=3)
    set_zones(g, 0, hand=["Fortnite"])
    play(g, "Fortnite")
    options = g.state.pending.decision.options
    assert "Gold" in options and "Province" in options and "Fortnite" not in options and "Curse" in options
    assert not set(options) & set(g.state.catastrophes)
    assert (g.state.pending.decision.min_choices, g.state.pending.decision.max_choices) == (0, 3)
    with pytest.raises(IllegalActionError):
        answer(g, 0, "Gold", "Silver", "Duchy", "Province")
    answer(g, 0, "Gold", "Province", "Workshop")
    assert g.state.walls == {"Gold": 0, "Province": 0, "Workshop": 0}
    assert "builds walls around Gold, Province, Workshop" in log_text(g)
    piles = {p["name"]: p for p in build_view(g, 1)["piles"]}
    assert piles["Gold"]["walled_by"] == 0 and piles["Silver"]["walled_by"] is None
    # the builder may still buy; everyone else may not
    to_buy_phase(g)
    g.state.coins = 20; g.state.buys = 3
    assert Buy("Gold") in legal_actions(g.state)
    g.apply(0, EndPhase())
    p1 = g.state.current_player
    g.state.coins = 20; g.state.buys = 3
    to_buy_phase(g)
    assert Buy("Gold") not in legal_actions(g.state) and Buy("Silver") in legal_actions(g.state)
    with pytest.raises(IllegalActionError, match="walled off"):
        g.apply(p1, Buy("Gold"))
    # Workshop-style gains do not offer walled piles either
    set_zones(g, p1, hand=["Workshop"])
    g.state.phase = type(g.state.phase).ACTION; g.state.actions = 1
    play(g, "Workshop", p1)
    assert "Silver" in g.state.pending.decision.options


def test_walls_come_down_when_the_builders_next_turn_starts_even_if_it_is_skipped():
    g = g_with(["Fortnite", "Long Night"], players=3)
    set_zones(g, 0, hand=["Fortnite"])
    play(g, "Fortnite")
    answer(g, 0, "Gold")
    end_turn(g); end_turn(g)                                      # P1 and P2 play with the wall up
    assert g.state.walls == {"Gold": 0}
    end_turn(g)                                                   # back to P0: the wall is gone
    assert g.state.walls == {} and "The wall around Gold comes down" in log_text(g)
    g = g_with(["Fortnite", "Long Night"], players=3)
    set_zones(g, 0, hand=["Fortnite"])
    play(g, "Fortnite")
    answer(g, 0, "Gold")
    g.state.players[0].skips = 1                                  # P0's next turn is skipped
    end_turn(g); end_turn(g)
    end_turn(g)
    assert g.state.walls == {}                                    # still down: it never outlives its builder's turn slot


def test_fortnite_cannot_wall_walled_empty_or_single_use_piles_and_can_choose_nothing():
    g = g_with(["Fortnite", "Rosebud"], players=2)
    g.state.walls["Silver"] = 1
    g.state.supply["Duchy"] = 0
    set_zones(g, 0, hand=["Fortnite"])
    play(g, "Fortnite")
    opts = g.state.pending.decision.options
    assert "Silver" not in opts and "Duchy" not in opts and "Rosebud" not in opts
    answer(g, 0)                                                  # wall nothing
    assert g.state.walls == {"Silver": 1}


def test_gains_from_a_walled_pile_fail_for_others_but_not_for_the_builder():
    from dominion.engine import zones
    g = g_with(["Fortnite"], players=2)
    g.state.walls["Curse"] = 0
    assert zones.gain_card(g.state, 1, "Curse") is False and g.state.supply["Curse"] == 10
    assert zones.gain_card(g.state, 0, "Curse") is True
    set_zones(g, 0, hand=["Witch"])
    g.state.supply["Witch"] = 10
    g.state.players[1].invisible = False
    play(g, "Witch")
    assert g.state.pending is None and "Curse" not in g.state.players[1].discard    # the Curse could not be gained


def test_swindler_respects_walls_for_the_player_who_receives_the_card():
    g = make_game(players=2, kingdom=["Swindler", "Village", "Moat"], catastrophes=["Fortnite"])
    g.state.walls["Village"] = 0
    set_zones(g, 0, hand=["Swindler"])
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Silver", "Silver"])
    play(g, "Swindler")
    assert "Village" not in g.state.pending.decision.options      # P1 would gain it: walled off
    g2 = make_game(players=2, kingdom=["Swindler", "Village", "Moat"], catastrophes=["Fortnite"])
    g2.state.walls["Village"] = 1                                 # walled by the victim: they may gain it
    set_zones(g2, 0, hand=["Swindler"])
    set_zones(g2, 1, hand=["Copper"] * 5, deck=["Silver", "Silver"])
    play(g2, "Swindler")
    assert "Village" in g2.state.pending.decision.options


# ================================================================== Monopoly
def test_monopoly_everyone_pays_a_gold_then_a_silver_then_nothing():
    g = g_with(["Monopoly"], players=4)
    set_zones(g, 0, hand=["Monopoly"], discard=[])
    set_zones(g, 1, hand=["Gold", "Gold", "Silver", "Copper", "Copper"])
    set_zones(g, 2, hand=["Silver", "Copper", "Copper", "Copper", "Estate"])
    set_zones(g, 3, hand=["Copper"] * 5)
    before = total_cards(g)
    play(g, "Monopoly")
    s = g.state
    assert sorted(s.players[0].discard) == ["Gold", "Silver"]
    assert sorted(s.players[1].hand) == ["Copper", "Copper", "Gold", "Silver"]
    assert "Silver" not in s.players[2].hand and s.players[3].hand == ["Copper"] * 5
    assert total_cards(g) == before and s.trash == ["Monopoly"]
    text = log_text(g)
    assert "P1 pays P0 a Gold" in text and "P2 pays P0 a Silver" in text and "P3 has no Gold or Silver" in text
    assert "MONOPOLY!" in text


def test_monopoly_ignores_moat_but_respects_protection():
    g = g_with(["Monopoly", "Guardian Angel"], players=3)
    g.state.players[2].protection = 2
    set_zones(g, 0, hand=["Monopoly"], discard=[])
    set_zones(g, 1, hand=["Moat", "Gold", "Copper", "Copper", "Copper"])
    set_zones(g, 2, hand=["Gold"] * 5)
    play(g, "Monopoly")
    assert g.state.pending is None                             # Moat is not even asked about
    assert g.state.players[0].discard == ["Gold"] and "Gold" not in g.state.players[1].hand   # P1 paid despite the Moat
    assert g.state.players[2].hand == ["Gold"] * 5             # P2 is protected


# ================================================================== Grand Theft Auto
def test_grand_theft_auto_steals_a_random_card_from_one_or_two_players():
    g = g_with(["Grand Theft Auto"], players=4)
    set_zones(g, 0, hand=["Grand Theft Auto"], discard=[])
    set_zones(g, 1, hand=["Gold"] * 5)
    set_zones(g, 2, hand=["Silver"] * 5)
    set_zones(g, 3, hand=["Province"] * 5)
    play(g, "Grand Theft Auto")
    d = g.state.pending.decision
    assert d.options == ("P1", "P2", "P3") and (d.min_choices, d.max_choices) == (1, 2)
    with pytest.raises(IllegalActionError):
        answer(g, 0, "P1", "P2", "P3")
    before = total_cards(g)
    answer(g, 0, "P1", "P3")
    assert sorted(g.state.players[0].discard) == ["Gold", "Province"]
    assert len(g.state.players[1].hand) == 4 and len(g.state.players[3].hand) == 4 and len(g.state.players[2].hand) == 5
    assert total_cards(g) == before
    text = log_text(g)
    assert "P0 steals a Gold from P1!" in text and "P0 steals a Province from P3!" in text and "GRAND THEFT AUTO" in text


def test_grand_theft_auto_in_a_two_player_game_and_with_nothing_to_steal():
    g = g_with(["Grand Theft Auto"], players=2)
    set_zones(g, 0, hand=["Grand Theft Auto"], discard=[])
    set_zones(g, 1, hand=[])
    play(g, "Grand Theft Auto")
    d = g.state.pending.decision
    assert d.options == ("P1",) and (d.min_choices, d.max_choices) == (1, 1)
    answer(g, 0, "P1")
    assert g.state.players[0].discard == [] and "has no cards in hand to steal" in log_text(g)


def test_grand_theft_auto_ignores_moat_respects_protection_and_is_random_but_seeded():
    g = g_with(["Grand Theft Auto"], players=3)
    g.state.players[2].protected_forever = True
    set_zones(g, 0, hand=["Grand Theft Auto"], discard=[])
    set_zones(g, 1, hand=["Moat", "Gold", "Gold", "Gold", "Gold"])
    set_zones(g, 2, hand=["Gold"] * 5)
    play(g, "Grand Theft Auto")
    answer(g, 0, "P1", "P2")
    assert g.state.pending is None
    assert len(g.state.players[0].discard) == 1 and g.state.players[0].discard == ["Gold"]    # one theft: P2 is protected, Moat did not help P1
    assert len(g.state.players[1].hand) == 4 and len(g.state.players[2].hand) == 5
    stolen = set()
    for seed in range(12):
        h = g_with(["Grand Theft Auto"], players=2, seed=seed)
        set_zones(h, 0, hand=["Grand Theft Auto"], discard=[])
        set_zones(h, 1, hand=["Gold", "Silver", "Copper", "Estate", "Duchy"])
        play(h, "Grand Theft Auto"); answer(h, 0, "P1")
        stolen.add(h.state.players[0].discard[0])
    assert len(stolen) >= 3


# ================================================================== Roofie
def test_roofie_blinds_other_players_until_the_end_of_their_next_turn():
    g = g_with(["Roofie"], players=3)
    set_zones(g, 0, hand=["Roofie"])
    play(g, "Roofie")
    s = g.state
    assert [p.blind for p in s.players] == [0, 1, 1]
    assert "ROOFIE!" in log_text(g) and "P1 is blinded" in log_text(g)
    assert build_view(g, 1)["blind"] is True and build_view(g, 0)["blind"] is False
    assert [p["blind"] for p in build_view(g, 0)["players"]] == [0, 1, 1]
    end_turn(g)                                                   # P1's turn: still blind during it
    assert s.players[1].blind == 1 and build_view(g, 1)["blind"] is True
    end_turn(g)
    assert s.players[1].blind == 0 and "P1 can see again" in log_text(g)
    assert s.players[2].blind == 1                                # P2's turn is next
    end_turn(g)
    assert s.players[2].blind == 0 and build_view(g, 2)["blind"] is False


def test_roofie_ignores_moat_respects_protection_and_does_not_stack():
    g = g_with(["Roofie"], players=3)
    g.state.players[2].protected_forever = True
    set_zones(g, 0, hand=["Roofie"])
    set_zones(g, 1, hand=["Moat"] + ["Copper"] * 4)
    play(g, "Roofie")
    assert g.state.pending is None
    assert [p.blind for p in g.state.players] == [0, 1, 0]       # Moat did not help; protection did
    h = g_with(["Roofie"], players=2)
    h.state.players[1].blind = 1
    set_zones(h, 0, hand=["Roofie"])
    play(h, "Roofie")
    assert h.state.players[1].blind == 1


# ================================================================== Chance Time
def force(monkeypatch, index):
    monkeypatch.setattr(EffectContext, "random_int", lambda self, n: index if n == len(CHANCE_OUTCOMES) else 0)


def test_chance_time_has_six_outcomes_and_every_one_can_come_up():
    assert len(CHANCE_OUTCOMES) == 6
    seen = Counter()
    for seed in range(60):
        g = g_with(["Chance Time"], players=3, seed=seed)
        set_zones(g, 0, hand=["Chance Time", "Copper"], deck=["Gold"] * 8)
        play(g, "Chance Time")
        for o in CHANCE_OUTCOMES:
            if f"lands on {o}!" in log_text(g):
                seen[o] += 1
        assert g.state.trash.count("Chance Time") == 1
    assert set(seen) == set(CHANCE_OUTCOMES) and all(seen[o] >= 3 for o in CHANCE_OUTCOMES)


def test_chance_time_jackpot_and_coin_shower(monkeypatch):
    force(monkeypatch, 0)
    g = g_with(["Chance Time"], players=2)
    set_zones(g, 0, hand=["Chance Time"], discard=[])
    play(g, "Chance Time")
    assert g.state.players[0].discard == ["Gold", "Gold"] and "CHANCE TIME! The wheel lands on JACKPOT!" in log_text(g)
    force(monkeypatch, 1)
    g = g_with(["Chance Time"], players=2)
    set_zones(g, 0, hand=["Chance Time"])
    play(g, "Chance Time")
    assert (g.state.coins, g.state.buys) == (8, 2)


def test_chance_time_hand_swap_skips_protected_and_cloaked_players(monkeypatch):
    force(monkeypatch, 2)
    g = g_with(["Chance Time"], players=3)
    set_zones(g, 0, hand=["Chance Time", "Estate"])
    set_zones(g, 1, hand=["Gold", "Gold"])
    set_zones(g, 2, hand=["Silver"])
    play(g, "Chance Time")
    mine = sorted(g.state.players[0].hand)
    assert mine in (["Gold", "Gold"], ["Silver"]) and "swap hands" in log_text(g)
    g = g_with(["Chance Time"], players=3)
    g.state.players[1].invisible = True
    g.state.players[2].protection = 2
    set_zones(g, 0, hand=["Chance Time", "Estate"])
    play(g, "Chance Time")
    assert g.state.players[0].hand == ["Estate"] and "Nobody can be swapped with" in log_text(g)


def test_chance_time_bowsers_revenge_hurts_only_the_player(monkeypatch):
    force(monkeypatch, 3)
    g = g_with(["Chance Time"], players=2)
    set_zones(g, 0, hand=["Chance Time"], deck=["Gold"] * 5, discard=[])
    before = total_cards(g)
    play(g, "Chance Time")
    assert len(g.state.players[0].deck) == 3 and g.state.trash == ["Chance Time", "Gold", "Gold"]
    assert total_cards(g) == before


def test_chance_time_friends_forever_gives_everyone_a_silver_even_the_cloaked(monkeypatch):
    force(monkeypatch, 4)
    g = g_with(["Chance Time"], players=3)
    g.state.players[1].invisible = True
    set_zones(g, 0, hand=["Chance Time"], discard=[])
    for i in (1, 2):
        g.state.players[i].discard.clear()
    play(g, "Chance Time")
    assert all(g.state.players[i].discard == ["Silver"] for i in range(3))


def test_chance_time_new_hands_for_everybody_but_the_cloaked(monkeypatch):
    force(monkeypatch, 5)
    g = g_with(["Chance Time"], players=3)
    g.state.players[1].invisible = True
    set_zones(g, 0, hand=["Chance Time", "Estate"], deck=["Gold"] * 10, discard=[])
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Gold"] * 10, discard=[])
    set_zones(g, 2, hand=["Copper"] * 5, deck=["Silver"] * 10, discard=[])
    before = total_cards(g)
    play(g, "Chance Time")
    assert g.state.players[0].hand == ["Gold"] * 5 and g.state.players[2].hand == ["Silver"] * 5
    assert g.state.players[1].hand == ["Copper"] * 5
    assert "Estate" in g.state.players[0].discard and total_cards(g) == before


# ================================================================== everything together
def flooded_game(seed, players):
    """Cheats give everybody money every turn so they can buy the house-rule cards and play them."""
    rng = random.Random(seed)
    cats = rng.sample([c for c in fenced_cards() if get_card(c).min_players <= players], 2)
    g = new_game(GameConfig([f"P{i}" for i in range(players)], KINGDOM, seed, catastrophes=cats, cheats=True))
    return g, rng


@pytest.mark.parametrize("players", [2, 3, 4])
def test_house_rule_cards_in_random_play_keep_every_card_and_replay_exactly(players):
    for seed in range(10):
        g, rng = flooded_game(seed, players)
        bots = [RandomBot(random.Random(rng.random())) for _ in range(players)]
        for _ in range(900):
            if g.state.status is GameStatus.FINISHED:
                break
            actor = g.acting_player
            s = g.state
            if (s.pending is None and actor == s.current_player and s.coins < 20
                    and not s.buy_locked and rng.random() < 0.7):
                g.apply(actor, Cheat("coins")); g.apply(actor, Cheat("buys"))        # money to buy the special cards
                continue
            g.apply(actor, bots[actor].choose(g, actor))
        r = replay(g.config, g.history)
        assert [p.all_cards() for p in r.state.players] == [p.all_cards() for p in g.state.players]
        assert r.state.supply == g.state.supply and r.state.trash == g.state.trash and r.state.walls == g.state.walls
        assert [str(x) for x in r.state.log] == [str(x) for x in g.state.log]
        assert [(p.invisible, p.blind, p.protection, p.bonus_coins) for p in r.state.players] == \
               [(p.invisible, p.blind, p.protection, p.bonus_coins) for p in g.state.players]


@pytest.mark.parametrize("card", fenced_cards())
def test_every_house_rule_card_survives_stuffed_random_games(card):
    """Decks are stuffed with the card (and Exodia's other pieces) so it gets played all the time."""
    import json
    played = 0
    for players in (2, 3, 4):
        if players < get_card(card).min_players:
            continue
        for seed in range(3):
            rng = random.Random(seed * 7 + players)
            g = make_game(players=players, kingdom=KINGDOM, catastrophes=[card], seed=seed)
            for p in g.state.players:
                p.deck.extend([card] * 3)
                if card == HEAD:
                    p.deck.extend(list(EXODIA_PIECES[1:]) * 2)
                rng.shuffle(p.deck)
            before = total_cards(g)
            bots = [RandomBot(random.Random(rng.random())) for _ in range(players)]
            for step in range(700):
                if g.state.status is GameStatus.FINISHED:
                    break
                play_checked(g, bots)
                assert total_cards(g) == before, f"{card}: cards appeared or vanished"
                if step % 60 == 0:
                    for i in range(players):
                        json.dumps(build_view(g, i))
            played += sum(1 for line in g.state.log if f"plays {card}" in line)
            for p in g.state.players:
                assert p.blind in (0, 1) and 0 <= p.protection <= 5
                assert not g.state.walls or all(0 <= o < players for o in g.state.walls.values())
    if card != HEAD:                                     # Exodia pieces are not played; the others must have been
        assert played > 0, f"{card} was never played in the stress games"
