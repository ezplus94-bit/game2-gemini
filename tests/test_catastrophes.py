import random
from collections import Counter

import pytest

from dominion.ai import RandomBot
from dominion.cards import CardType, action, kingdom_cards, register, unregister
from dominion.cards.registry import catastrophe_cards, fenced_cards
from dominion.engine import (
    Buy, Choose, EndPhase, GameConfig, GameStatus, IllegalActionError, PlayAction, PlayAllTreasures,
    build_view, new_game, replay,
)
from helpers import make_game, set_zones, snapshot, total_cards
from test_bots import play_checked

KINGDOM = ["Moat", "Village", "Smithy", "Throne Room"]


def cg(players=3, cats=("Time Stop",), **kw):
    return make_game(players=players, kingdom=KINGDOM, catastrophes=list(cats), **kw)


def play(g, card, player=0):
    g.apply(player, PlayAction(card))


def answer(g, player, *cards):
    g.apply(player, Choose(tuple(cards)))


def end_turn(g):
    p = g.state.current_player
    g.apply(p, EndPhase())
    g.apply(p, EndPhase())


# ------------------------------------------------------------------- setup
def test_catastrophes_are_scarce_separate_and_never_in_a_random_kingdom():
    assert set(catastrophe_cards()) == {
        "Cataclysm", "Fate Swap", "Long Night", "Time Stop", "Grand Swap", "The Snap", "The Purge",
        "Monopoly", "Grand Theft Auto", "Roofie", "Fortnite",
    }
    assert not set(catastrophe_cards()) & set(kingdom_cards())
    g = cg(cats=("Time Stop", "Fate Swap"))
    assert g.state.supply["Time Stop"] == g.state.supply["Fate Swap"] == 2
    piles = {p["name"]: p for p in build_view(g, 0)["piles"]}
    assert piles["Time Stop"]["catastrophe"] and not piles["Time Stop"]["kingdom"]
    assert not piles["Village"]["catastrophe"] and "Cataclysm" not in piles
    for seed in range(30):
        assert not set(new_game(GameConfig(["A", "B"], None, seed)).state.kingdom) & set(catastrophe_cards())


@pytest.mark.parametrize("cats,players", [
    (["Nope"], 3), (["Time Stop", "Time Stop"], 3), (["Village"], 3), (["Long Night"], 2),
])
def test_invalid_catastrophe_choices_are_rejected(cats, players):
    with pytest.raises(ValueError):
        cg(players=players, cats=cats)


def test_any_number_of_house_rule_cards_may_be_chosen():
    """No limit: three, five, or every single one (those that fit the player count)."""
    for pick in (["Time Stop", "Fate Swap", "Cataclysm"], ["Chance Time", "Grand Theft Auto", "The Snap"], fenced_cards()):
        g = cg(players=4, cats=tuple(pick))
        assert all(g.state.supply[c] == 2 for c in pick)
        assert g.config.catastrophes == pick
        v = build_view(g, 0)
        assert {p["name"] for p in v["piles"] if p["catastrophe"]} >= set(pick)
    g = cg(players=4, cats=tuple(fenced_cards()))
    g.state.supply["Village"] = 0                                    # empty house-rule piles still never end the game
    for name in fenced_cards():
        g.state.supply[name] = 0
    assert g.state.status is GameStatus.ACTIVE


def test_empty_catastrophe_piles_do_not_end_the_game():
    g = cg(cats=("Time Stop", "Fate Swap"), supply_overrides={"Time Stop": 0, "Fate Swap": 0, "Curse": 0, "Duchy": 0})
    end_turn(g)
    assert g.state.status is GameStatus.ACTIVE                    # only 2 ordinary piles are empty
    g2 = cg(cats=("Time Stop", "Fate Swap"),
            supply_overrides={"Time Stop": 0, "Curse": 0, "Duchy": 0, "Estate": 0})
    end_turn(g2)
    assert g2.state.status is GameStatus.FINISHED


# --------------------------------------------------------------- Time Stop
def test_time_stop_skips_only_the_next_player_and_trashes_itself():
    g = cg()
    set_zones(g, 0, hand=["Time Stop"])
    play(g, "Time Stop")
    s = g.state
    assert s.pending is None and s.trash == ["Time Stop"] and "Time Stop" not in s.players[0].in_play
    assert [p.skips for p in s.players] == [0, 1, 0]
    assert build_view(g, 2)["players"][1]["skip_pending"] is True
    end_turn(g)
    assert s.current_player == 2 and s.turn_number == 3                 # player 1's turn was skipped
    assert s.players[1].turns_taken == 1 and s.players[1].skip_protected
    assert any("turn is skipped" in line for line in s.log)
    end_turn(g)                                                          # player 2
    end_turn(g)                                                          # player 0
    assert s.current_player == 1 and not s.players[1].skip_protected and s.players[1].skips == 0


def test_two_player_time_stop_is_a_double_turn():
    g = cg(players=2)
    set_zones(g, 0, hand=["Time Stop"])
    play(g, "Time Stop")
    end_turn(g)
    assert g.state.current_player == 0 and [p.turns_taken for p in g.state.players] == [1, 1]


def test_nobody_is_skipped_twice_in_a_row_and_skips_do_not_stack():
    g = cg()
    set_zones(g, 0, hand=["Time Stop", "Time Stop"])
    g.state.actions = 2
    play(g, "Time Stop")
    play(g, "Time Stop")
    assert g.state.players[1].skips == 1                                 # the second one found nothing to do
    end_turn(g)
    end_turn(g)                                                          # player 2
    set_zones(g, 0, hand=["Time Stop"])
    play(g, "Time Stop")                                                 # player 1 was just skipped: protected
    assert g.state.players[1].skips == 0
    end_turn(g)
    assert g.state.current_player == 1                                   # they really do get a turn now


def test_moat_does_not_stop_time_stop_but_protection_does():
    g = cg()
    set_zones(g, 0, hand=["Time Stop"])
    set_zones(g, 1, hand=["Moat", "Copper"])
    set_zones(g, 2, hand=["Moat", "Copper"])
    play(g, "Time Stop")
    assert g.state.pending is None                                       # nobody is even asked about Moat
    assert g.state.players[1].skips == 1 and g.state.players[2].skips == 0

    g2 = cg()
    g2.state.players[1].protection = 2                                   # Guardian Angel style protection still works
    set_zones(g2, 0, hand=["Time Stop"])
    set_zones(g2, 1, hand=["Moat", "Copper"])
    play(g2, "Time Stop")
    assert g2.state.players[1].skips == 0 and "P1 is protected and unaffected" in "\n".join(str(x) for x in g2.state.log)


def test_moat_and_diplomat_still_work_against_ordinary_attacks():
    g = make_game(players=2, kingdom=["Militia", "Moat"])
    set_zones(g, 0, hand=["Militia"])
    set_zones(g, 1, hand=["Moat"] + ["Copper"] * 4)
    play(g, "Militia")
    assert g.state.pending.decision.options == ("Moat",)


# --------------------------------------------------------------- Long Night
def test_long_night_skips_the_next_two_players():
    g = cg(players=3, cats=("Long Night",))
    set_zones(g, 0, hand=["Long Night"])
    play(g, "Long Night")
    assert [p.skips for p in g.state.players] == [0, 1, 1]
    end_turn(g)
    assert g.state.current_player == 0 and g.state.turn_number == 4
    assert [p.turns_taken for p in g.state.players] == [1, 1, 1]

    g4 = cg(players=4, cats=("Long Night",))
    set_zones(g4, 0, hand=["Long Night"])
    play(g4, "Long Night")
    end_turn(g4)
    assert g4.state.current_player == 3                                  # only the next two lose a turn


# ---------------------------------------------------------------- Fate Swap
def fate_game(cats=("Fate Swap",), **kw):
    g = cg(cats=cats, **kw)
    set_zones(g, 0, hand=["Fate Swap"], deck=["Estate", "Duchy", "Province", "Gold", "Silver"])
    set_zones(g, 1, hand=["Copper"], deck=["Copper", "Copper", "Curse"])
    return g


def test_fate_swap_swaps_the_same_number_of_top_cards_keeping_order():
    g = fate_game()
    play(g, "Fate Swap")
    assert g.state.pending.decision.options == ("P1", "P2")
    answer(g, 0, "P1")
    s = g.state
    assert s.pending is None and s.trash == ["Fate Swap"]
    assert s.players[0].deck == ["Estate", "Duchy", "Copper", "Copper", "Curse"]
    assert s.players[1].deck == ["Province", "Gold", "Silver"]            # 3 each way: the smaller pile


def test_fate_swap_is_capped_at_seven_cards():
    g = cg(cats=("Fate Swap",))
    set_zones(g, 0, hand=["Fate Swap"], deck=["Estate"] * 12)
    set_zones(g, 1, hand=["Copper"], deck=["Gold"] * 12)
    play(g, "Fate Swap")
    answer(g, 0, "P1")
    assert g.state.players[0].deck == ["Estate"] * 5 + ["Gold"] * 7
    assert g.state.players[1].deck == ["Gold"] * 5 + ["Estate"] * 7


def test_fate_swap_ignores_moat_but_not_an_empty_draw_pile():
    g = fate_game()
    set_zones(g, 1, hand=["Moat"])
    play(g, "Fate Swap")
    answer(g, 0, "P1")
    assert g.state.pending is None                                        # no Moat question
    assert g.state.players[0].deck == ["Estate", "Duchy", "Copper", "Copper", "Curse"]    # the swap went ahead

    g2 = fate_game()
    set_zones(g2, 1, deck=[])
    play(g2, "Fate Swap")
    answer(g2, 0, "P1")
    assert g2.state.players[0].deck == ["Estate", "Duchy", "Province", "Gold", "Silver"]
    assert any("nothing is swapped" in line for line in g2.state.log)


def test_throne_room_cannot_make_a_catastrophe_happen_twice():
    g = fate_game()
    set_zones(g, 0, hand=["Throne Room", "Fate Swap"])
    play(g, "Throne Room")
    answer(g, 0, "Fate Swap")
    answer(g, 0, "P1")
    assert g.state.pending is None                                        # no second question
    assert g.state.trash == ["Fate Swap"]


# ---------------------------------------------------------------- Cataclysm
def cataclysm_game(seed=1):
    g = cg(cats=("Cataclysm",), seed=seed)
    set_zones(g, 0, hand=["Cataclysm", "Gold", "Gold"], deck=["Estate"] * 6, discard=["Copper"] * 3)
    set_zones(g, 1, hand=["Province"] * 5, deck=["Copper"] * 5, discard=[])
    set_zones(g, 2, hand=["Curse"] * 5, deck=["Silver"] * 4, discard=["Duchy"] * 2)
    return g


def pooled(g):
    return Counter(c for p in g.state.players for c in (p.deck + p.hand + p.discard))


def test_cataclysm_reshuffles_everything_keeping_each_players_card_count():
    g = cataclysm_game()
    expected = Counter(c for p in g.state.players for c in (p.deck + p.hand + p.discard))
    expected["Cataclysm"] -= 1                                            # it is in play, not pooled
    sizes = [len(p.deck + p.hand + p.discard) - (1 if i == 0 else 0) for i, p in enumerate(g.state.players)]
    play(g, "Cataclysm")
    s = g.state
    assert pooled(g) == expected                                          # nothing lost, nothing made
    assert [len(p.deck + p.hand + p.discard) for p in s.players] == sizes
    assert s.players[0].hand == [] and s.players[1].hand and len(s.players[1].hand) == 5
    assert len(s.players[2].hand) == 5 and s.players[1].discard == [] == s.players[2].discard
    assert s.trash == ["Cataclysm"] and s.players[0].in_play == []
    assert any("combined" in line for line in s.log)


def test_cataclysm_locks_buys_until_the_turn_ends():
    g = cataclysm_game()
    play(g, "Cataclysm")
    assert g.state.buy_locked and g.state.buys == 0
    g.apply(0, EndPhase())
    g.state.coins = 8
    with pytest.raises(IllegalActionError):
        g.apply(0, Buy("Silver"))
    assert not any(isinstance(a, Buy) for a in g.legal_actions())
    g.apply(0, EndPhase())
    assert not g.state.buy_locked and g.state.buys == 1                    # next turn is normal


def test_cataclysm_is_deterministic_for_a_given_seed():
    a, b, c = cataclysm_game(5), cataclysm_game(5), cataclysm_game(6)
    for g in (a, b, c):
        play(g, "Cataclysm")
    assert snapshot(a) == snapshot(b) and snapshot(a) != snapshot(c)


def test_cataclysm_is_not_an_attack_and_throne_room_cannot_double_it():
    g = cataclysm_game()
    set_zones(g, 0, hand=["Throne Room", "Cataclysm", "Gold"])
    set_zones(g, 1, hand=["Moat"] + ["Province"] * 4)
    before = total_cards(g)
    play(g, "Throne Room")
    answer(g, 0, "Cataclysm")
    assert g.state.pending is None                                        # nobody was asked about Moat
    assert g.state.trash == ["Cataclysm"] and sum("combined" in l for l in g.state.log) == 1
    assert total_cards(g) == before - 1 + 1                               # one card moved to the trash, none lost


# ----------------------------------------------------------- web lobby rules
def test_host_chooses_catastrophes_in_the_lobby():
    import asyncio
    from test_web_rooms import RoomManager, run, two_player_room

    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, _ = await two_player_room(m)
        await guest.say(type="set_catastrophes", catastrophes=["Time Stop"])
        assert guest.last_error() == "Only the host can do that."
        for bad in (["Nope"], ["Village"], ["Time Stop", "Time Stop"], "Time Stop", ["Right Arm of the Forbidden One"]):
            await host.say(type="set_catastrophes", catastrophes=bad)
            assert "Choose different" in host.last_error(), bad
        many = ["Time Stop", "Fate Swap", "Cataclysm", "The Snap", "Rosebud", "Chance Time"]       # no limit on how many
        await host.say(type="set_catastrophes", catastrophes=many)
        assert host.last("lobby")["catastrophes"] == many and "max_catastrophes" not in host.last("lobby")
        await host.say(type="set_catastrophes", catastrophes=["Long Night"])
        lobby = host.last("lobby")
        assert lobby["catastrophes"] == ["Long Night"]
        assert {c["name"] for c in lobby["available_catastrophes"]} == set(fenced_cards())
        await host.say(type="start")
        assert "needs at least 3 players" in host.last_error()              # only 2 seats
        await host.say(type="set_catastrophes", catastrophes=["Time Stop"])
        await host.say(type="start")
        piles = {p["name"]: p for p in host.view["piles"]}
        assert piles["Time Stop"]["catastrophe"] and piles["Time Stop"]["count"] == 2
        await host.say(type="set_catastrophes", catastrophes=[])             # too late once started
        assert "already started" in host.last_error()
    run(scenario())


# ------------------------------------------------------- random self-play
@pytest.fixture
def cheap_catastrophes():
    """$0 copies of the real effects, so random bots actually buy and play them."""
    from dominion.cards import catastrophe as real
    atk = (CardType.ATTACK, CardType.CATASTROPHE)
    specs = [("TS0", real._time_stop, atk, 1), ("LN0", real._long_night, atk, 3),
             ("FS0", real._fate_swap, atk, 1), ("CAT0", real._cataclysm, (CardType.CATASTROPHE,), 1)]
    for name, fn, types, min_players in specs:
        register(action(name, 0, fn, "test copy", kingdom=False, extra_types=types, min_players=min_players))
    yield [s[0] for s in specs]
    for name, *_ in specs:
        unregister(name)


def test_random_games_with_catastrophes_keep_every_invariant(cheap_catastrophes):
    kingdom = ["Militia", "Witch", "Moat", "Bandit", "Throne Room", "Library", "Sentry",
               "Council Room", "Harbinger", "Vassal"]
    seen = Counter()
    for seed in range(40):
        players = 3 + seed % 2
        rng = random.Random(seed)
        cats = rng.sample(cheap_catastrophes, 2)
        g = new_game(GameConfig([f"P{i}" for i in range(players)], kingdom, seed, catastrophes=cats))
        play_checked(g, [RandomBot(random.Random(seed * 13 + i)) for i in range(players)])
        assert g.state.status is GameStatus.FINISHED
        assert snapshot(replay(g.config, g.history)) == snapshot(g)
        for line in g.state.log:
            seen["skip"] += "will skip" in line
            seen["swap"] += "swap the top" in line
            seen["cataclysm"] += "combined" in line
    assert seen["skip"] and seen["swap"] and seen["cataclysm"], seen
