"""Catastrophe and special house-rule cards, plus the UI, stats, resign and cheat-code features that came with them."""

import json
import random
import pytest
from collections import Counter
from dominion.ai import BigMoneyBot, RandomBot
from dominion.cards import CardType, get_card, action, kingdom_cards, register, unregister
from dominion.engine import (
    Buy,
    Choose,
    EndPhase,
    GameConfig,
    GameStatus,
    PlayAction,
    PlayAllTreasures,
    build_view,
    new_game,
    replay,
    Cheat,
    EndGame,
    IllegalActionError,
    Resign,
    legal_actions,
)
from dominion.engine.scoring import final_stats, score_player, vp_breakdown
from dominion.engine.state import LogLine
from helpers import make_game, set_zones, to_buy_phase, total_cards, snapshot
from test_bots import play_checked
from dominion.cards.registry import catastrophe_cards, fenced_cards, special_cards, companion_cards
from dominion.cards.special import CHANCE_OUTCOMES
from dominion.engine.constants import EXODIA_PIECES
from dominion.engine.effects import EffectContext


# ======================================================================
# from test_update7.py
# ======================================================================

KINGDOM = ["Moat", "Village", "Smithy", "Throne Room"]


def cg(players=3, cats=("Grand Swap",), **kw):
    return make_game(players=players, kingdom=KINGDOM, catastrophes=list(cats), **kw)


def play(g, card, player=0):
    g.apply(player, PlayAction(card))


def answer(g, player, *cards):
    g.apply(player, Choose(tuple(cards)))


def owned(g, p):
    return Counter(g.state.players[p].all_cards())


def log_text(g):
    return "\n".join(str(x) for x in g.state.log)


# ------------------------------------------------------------------ Grand Swap
def test_grand_swap_trades_draw_and_discard_piles_but_not_victory_curse_or_hands():
    g = cg(players=2)
    set_zones(g, 0, hand=["Grand Swap", "Copper"], deck=["Gold", "Gold", "Estate", "Curse"], discard=["Silver", "Province"])
    set_zones(g, 1, hand=["Village"], deck=["Copper", "Duchy", "Smithy"], discard=["Copper", "Estate"])
    play(g, "Grand Swap")
    answer(g, 0, "P1")
    s = g.state
    assert s.trash == ["Grand Swap"]
    p0, p1 = s.players
    assert sorted(p0.deck) == sorted(["Estate", "Curse", "Copper", "Smithy"])        # kept V/C + their non-V/C
    assert sorted(p1.deck) == sorted(["Duchy", "Gold", "Gold"])
    assert sorted(p0.discard) == sorted(["Province", "Copper"])
    assert sorted(p1.discard) == sorted(["Estate", "Silver"])
    assert p0.hand == ["Copper"] and p1.hand == ["Village"]


def test_grand_swap_conserves_every_card_and_victory_points_stay_put():
    g = cg(players=3)
    set_zones(g, 0, hand=["Grand Swap"], deck=["Gold"] * 5 + ["Province"] * 2, discard=["Duchy"] * 2 + ["Silver"])
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Copper"] * 5 + ["Estate"], discard=["Curse"])
    before, vp0, vp1 = total_cards(g), score_player(g.state.players[0]), score_player(g.state.players[1])
    play(g, "Grand Swap")
    answer(g, 0, "P1")
    assert total_cards(g) == before
    assert score_player(g.state.players[0]) == vp0 and score_player(g.state.players[1]) == vp1


def test_grand_swap_ignores_moat_but_protection_stops_it_and_it_is_single_use():
    g = cg(players=2)
    set_zones(g, 0, hand=["Grand Swap"], deck=["Gold"] * 5)
    set_zones(g, 1, hand=["Moat", "Copper", "Copper", "Copper", "Copper"], deck=["Copper"] * 5)
    play(g, "Grand Swap")
    answer(g, 0, "P1")
    assert g.state.pending is None                                    # Moat is never asked about
    assert g.state.players[0].deck == ["Copper"] * 5 and g.state.players[1].deck == ["Gold"] * 5   # swapped
    assert g.state.trash == ["Grand Swap"]
    h = cg(players=2)
    h.state.players[1].protected_forever = True
    set_zones(h, 0, hand=["Grand Swap"], deck=["Gold"] * 5)
    set_zones(h, 1, deck=["Copper"] * 5)
    play(h, "Grand Swap")
    answer(h, 0, "P1")
    assert h.state.players[0].deck == ["Gold"] * 5                    # protection works


def test_grand_swap_under_throne_room_does_nothing_twice():
    g = cg(players=2)
    set_zones(g, 0, hand=["Throne Room", "Grand Swap"], deck=["Gold"] * 3)
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Copper"] * 5)
    play(g, "Throne Room")
    answer(g, 0, "Grand Swap")
    answer(g, 0, "P1")
    assert g.state.pending is None and g.state.trash == ["Grand Swap"]


def test_grand_swap_logs_who_got_what():
    g = cg(players=2)
    set_zones(g, 0, hand=["Grand Swap"], deck=["Gold", "Gold"], discard=["Estate"])
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Copper", "Silver"], discard=[])
    play(g, "Grand Swap")
    answer(g, 0, "P1")
    text = log_text(g)
    assert "GRAND SWAP" in text
    assert "P0 gets 1 Copper, 1 Silver; loses 2 Gold" in text
    assert "P1 gets 2 Gold; loses 1 Copper, 1 Silver" in text
    summaries = [l for l in g.state.log if l.kind == "summary"]
    assert len(summaries) == 2 and all(l.indent == 2 for l in summaries)


# ------------------------------------------------------------------ The Snap
def test_snap_trashes_half_of_every_players_cards_including_the_player_who_played_it():
    g = cg(players=3, cats=("The Snap",))
    set_zones(g, 0, hand=["The Snap", "Copper"], deck=["Gold"] * 4, discard=["Silver"] * 3)       # 8 cards (not counting in-play)
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Estate"] * 5, discard=["Silver"])               # 11 cards
    set_zones(g, 2, hand=["Copper"] * 2, deck=[], discard=[])                                    # 2 cards
    play(g, "The Snap")                                  # 8 cards left after the Snap itself is played
    s = g.state
    assert len(s.players[0].all_cards()) == 4
    assert len(s.players[1].all_cards()) == 11 - 5
    assert len(s.players[2].all_cards()) == 1
    assert len(s.trash) == 1 + 4 + 5 + 1                 # The Snap + each player's losses


def test_snap_ignores_moat_and_protection_spares_others_but_never_the_player():
    g = cg(players=2, cats=("The Snap",))
    set_zones(g, 0, hand=["The Snap"], deck=["Gold"] * 6, discard=["Silver"] * 4)
    set_zones(g, 1, hand=["Moat"] + ["Copper"] * 4, deck=["Copper"] * 5)
    play(g, "The Snap")
    assert g.state.pending is None                             # no Moat question
    assert len(g.state.players[1].all_cards()) == 5            # Moat did not help: 10 cards halved
    assert len(g.state.players[0].all_cards()) == 5
    h = cg(players=2, cats=("The Snap",))
    h.state.players[1].protected_forever = True
    set_zones(h, 0, hand=["The Snap"], deck=["Gold"] * 6, discard=["Silver"] * 4)
    set_zones(h, 1, hand=["Moat"] + ["Copper"] * 4, deck=["Copper"] * 5)
    play(h, "The Snap")
    assert len(h.state.players[1].all_cards()) == 10           # protection works
    assert len(h.state.players[0].all_cards()) == 5            # the player who played it is never spared


def test_snap_is_random_but_seeded_and_logs_who_lost_what():
    results = set()
    for seed in range(6):
        g = cg(players=2, cats=("The Snap",), seed=seed)
        set_zones(g, 0, hand=["The Snap"], deck=["Gold", "Silver", "Copper", "Estate", "Duchy", "Province"])
        set_zones(g, 1, hand=["Copper"] * 5, deck=["Copper"] * 5)
        play(g, "The Snap")
        results.add(tuple(sorted(g.state.trash)))
        text = log_text(g)
        assert "THE SNAP" in text and "P0 loses 3 of 6 cards to the trash" in text and "P1 loses 5 of 10 cards to the trash" in text
    assert len(results) > 1                                    # different seeds trash different cards


def test_snap_on_empty_collections_does_nothing_bad():
    g = cg(players=2, cats=("The Snap",))
    set_zones(g, 0, hand=["The Snap"], deck=[], discard=[])
    set_zones(g, 1, hand=["Copper"], deck=[], discard=[])
    play(g, "The Snap")
    assert g.state.trash == ["The Snap"] and g.state.players[1].hand == ["Copper"]


# ------------------------------------------------------------------ The Purge
def test_purge_discards_half_of_each_draw_pile_and_keeps_cards():
    g = cg(players=2, cats=("The Purge",))
    set_zones(g, 0, hand=["The Purge"], deck=["Gold"] * 3 + ["Silver"] * 3, discard=["Copper"])
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Estate"] * 7, discard=[])
    before = total_cards(g)
    play(g, "The Purge")
    s = g.state
    assert len(s.players[0].deck) == 3 and len(s.players[0].discard) == 4
    assert len(s.players[1].deck) == 4 and len(s.players[1].discard) == 3
    assert total_cards(g) == before and s.trash == ["The Purge"]


def test_purge_ignores_moat_logs_who_lost_what_and_protection_spares():
    g = cg(players=2, cats=("The Purge",))
    set_zones(g, 0, hand=["The Purge"], deck=["Gold"] * 4)
    set_zones(g, 1, hand=["Moat", "Copper", "Copper", "Copper", "Copper"], deck=["Estate"] * 6)
    play(g, "The Purge")
    assert g.state.pending is None
    assert len(g.state.players[1].deck) == 3 and len(g.state.players[0].deck) == 2
    text = log_text(g)
    assert "THE PURGE" in text and "P0 discards 2 of 4 cards from their draw pile: 2 Gold" in text
    assert "P1 discards 3 of 6 cards from their draw pile: 3 Estate" in text
    h = cg(players=2, cats=("The Purge",))
    h.state.players[1].protection = 1
    set_zones(h, 0, hand=["The Purge"], deck=["Gold"] * 4)
    set_zones(h, 1, deck=["Estate"] * 6)
    play(h, "The Purge")
    assert len(h.state.players[1].deck) == 6 and "P1 discards" not in log_text(h)


def test_purge_odd_pile_rounds_down_and_empty_pile_is_fine():
    g = cg(players=2, cats=("The Purge",))
    set_zones(g, 0, hand=["The Purge"], deck=["Gold"] * 5)
    set_zones(g, 1, hand=["Copper"] * 5, deck=[])
    play(g, "The Purge")
    assert len(g.state.players[0].deck) == 3 and len(g.state.players[0].discard) == 2


# ------------------------------------------------------------------ Cataclysm summary
def test_cataclysm_logs_who_got_what():
    g = cg(players=2, cats=("Cataclysm",))
    set_zones(g, 0, hand=["Cataclysm", "Gold"], deck=["Gold"] * 3, discard=[])
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Copper"] * 5, discard=[])
    play(g, "Cataclysm")
    summaries = [str(l) for l in g.state.log if l.kind == "summary"]
    assert len(summaries) == 2
    assert all("(now " in x for x in summaries)
    assert sum(1 for l in g.state.log if l.kind == "catastrophe") == 1


# ------------------------------------------------------------------ the structured log
def test_log_lines_are_strings_with_turn_kind_indent():
    g = make_game(players=2, kingdom=KINGDOM, seed=1)
    assert all(isinstance(l, LogLine) and isinstance(l, str) for l in g.state.log)
    assert g.state.log[-1].kind == "turn" and g.state.log[-1].turn == 1
    assert "Turn 1" in g.state.log[-1]


def test_every_turn_gets_a_header_with_its_number_and_player():
    g = make_game(players=3, kingdom=KINGDOM, seed=1)
    for _ in range(4):
        p = g.state.current_player
        g.apply(p, EndPhase())
        g.apply(p, EndPhase())
    headers = [str(l) for l in g.state.log if l.kind == "turn"]
    assert headers == [f"Turn {i + 1} - P{i % 3}" for i in range(5)]
    turn_of_line = {str(l): l.turn for l in g.state.log if l.kind == "turn"}
    assert turn_of_line["Turn 3 - P2"] == 3


def test_log_kinds_for_core_events_and_effect_indent():
    g = make_game(players=2, kingdom=KINGDOM, seed=2)
    set_zones(g, 0, hand=["Smithy", "Copper", "Copper", "Copper", "Copper"], deck=["Gold"] * 5)
    play(g, "Smithy")
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    g.apply(0, Buy("Silver"))
    by_kind = {}
    for l in g.state.log:
        by_kind.setdefault(l.kind, []).append(l)
    assert str(by_kind["play"][0]) == "P0 plays Smithy."
    assert by_kind["play"][0].indent == 0
    draws = [l for l in g.state.log if "draws 3" in l]
    assert draws and draws[0].indent == 1
    assert any("buys Silver" in l for l in by_kind["buy"])
    assert by_kind["treasure"]


def test_log_view_is_json_plain_data_with_global_indexes():
    g = make_game(players=2, kingdom=KINGDOM, seed=2)
    view = build_view(g, 0)
    json.dumps(view)
    assert all(set(e) == {"i", "turn", "kind", "indent", "text"} for e in view["log"])
    assert [e["i"] for e in view["log"]] == list(range(len(g.state.log)))
    for _ in range(300):
        g.state.log.append("filler")
    v = build_view(g, 0)
    assert len(v["log"]) == 200 and v["log"][-1]["i"] == len(g.state.log) - 1 and v["log"][0]["i"] == len(g.state.log) - 200


def test_log_survives_undo_style_replay_with_identical_structure():
    g = make_game(players=2, kingdom=KINGDOM, seed=9)
    bots = [RandomBot(random.Random(1)), RandomBot(random.Random(2))]
    for _ in range(200):
        if g.state.status is GameStatus.FINISHED:
            break
        play_checked(g, bots)
    r = replay(g.config, g.history)
    assert [(str(a), a.turn, a.kind, a.indent) for a in g.state.log] == [(str(a), a.turn, a.kind, a.indent) for a in r.state.log]


# ------------------------------------------------------------------ stats
def finished_game(players=2, kingdom=None, seed=4, **kw):
    g = make_game(players=players, kingdom=kingdom or KINGDOM, seed=seed, **kw)
    bots = [BigMoneyBot() for _ in range(players)]
    for _ in range(20000):
        if g.state.status is GameStatus.FINISHED:
            return g
        p = g.acting_player
        g.apply(p, bots[p].choose(g, p))
    raise AssertionError("did not finish")


def test_stats_available_only_when_finished_and_match_scores():
    g = make_game(players=2, kingdom=KINGDOM, seed=4)
    assert "stats" not in build_view(g, 0)
    g = finished_game()
    stats = build_view(g, 0)["stats"]
    assert [s["name"] for s in stats] == ["P0", "P1"]
    for s, p in zip(stats, g.state.players):
        assert s["vp"] == score_player(p) and s["turns"] == p.turns_taken
        assert sum(r["vp"] for r in s["vp_breakdown"]) == s["vp"]
        assert s["bought_total"] == sum(s["bought"].values()) == len(p.bought)
        assert s["deck_total"] == sum(s["deck"].values()) == len(p.all_cards())
        assert s["gained_total"] >= s["bought_total"]


def test_bought_cards_are_counted_per_player():
    g = finished_game()
    for p in g.state.players:
        assert Counter(p.bought) == Counter(build_view(g, 0)["stats"][g.state.players.index(p)]["bought"])
        assert set(p.bought) <= {"Silver", "Gold", "Province"}
    assert any("Province" in p.bought for p in g.state.players)


def test_vp_breakdown_handles_gardens_duke_curses_and_double_types():
    g = make_game(players=2, kingdom=["Gardens", "Duke", "Nobles", "Harem"])
    p = g.state.players[0]
    p.discard.extend(["Gardens", "Duke", "Duchy", "Duchy", "Nobles", "Harem", "Curse", "Curse", "Province"])
    rows = {r["card"]: r for r in vp_breakdown(p)}
    total = len(p.all_cards())
    assert rows["Gardens"] == {"card": "Gardens", "count": 1, "vp": total // 10}
    assert rows["Duke"]["vp"] == 2
    assert rows["Duchy"]["vp"] == 6 and rows["Province"]["vp"] == 6
    assert rows["Nobles"]["vp"] == 2 and rows["Harem"]["vp"] == 2
    assert rows["Curse"] == {"card": "Curse", "count": 2, "vp": -2}
    assert sum(r["vp"] for r in rows.values()) == score_player(p)
    assert vp_breakdown(p) == sorted(vp_breakdown(p), key=lambda r: (-r["vp"], r["card"]))


def test_gains_are_tracked_even_when_not_bought():
    g = make_game(players=2, kingdom=["Workshop", "Smithy"], seed=3)
    set_zones(g, 0, hand=["Workshop"])
    play(g, "Workshop")
    answer(g, 0, "Smithy")
    p = g.state.players[0]
    assert p.gained == ["Smithy"] and p.bought == []


def test_gain_from_trash_counts_as_a_gain():
    g = make_game(players=2, kingdom=["Lurker", "Smithy"], seed=3)
    g.state.trash.append("Smithy")
    set_zones(g, 0, hand=["Lurker"])
    play(g, "Lurker")
    answer(g, 0, "Gain an Action card from the trash")
    answer(g, 0, "Smithy")
    assert g.state.players[0].gained == ["Smithy"] and g.state.trash == []


@pytest.mark.parametrize("cat", ["Grand Swap", "The Snap", "The Purge", "Cataclysm", "Fate Swap", "Time Stop", "Rosebud", "Guardian Angel", "God Mode"])
def test_catastrophes_in_random_play_keep_every_card(cat):
    for seed in range(6):
        g = make_game(players=3, kingdom=KINGDOM, catastrophes=[cat], seed=seed)
        rng = random.Random(seed)
        bots = [RandomBot(random.Random(rng.random())) for _ in range(3)]
        # give everybody the card so it actually gets played
        for p in g.state.players:
            p.deck.extend([cat] * 1)
        before = total_cards(g)
        for _ in range(1500):
            if g.state.status is GameStatus.FINISHED:
                break
            play_checked(g, bots)
            assert total_cards(g) == before


# ------------------------------------------------------------------ web lobby: card sets
def test_host_chooses_card_sets_in_the_lobby():
    from test_web import RoomManager, run, two_player_room
    from dominion.cards import kingdom_cards

    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, _ = await two_player_room(m)
        lobby = host.last("lobby")
        assert lobby["expansions"] == ["Base", "Adventures", "Alchemy", "Allies", "Cornucopia & Guilds", "Dark Ages", "Empires", "Hinterlands", "Intrigue", "Menagerie", "Nocturne", "Plunder", "Promos", "Prosperity", "Renaissance", "Rising Sun", "Seaside"] and lobby["available_expansions"] == ["Base", "Adventures", "Alchemy", "Allies", "Cornucopia & Guilds", "Dark Ages", "Empires", "Hinterlands", "Intrigue", "Menagerie", "Nocturne", "Plunder", "Promos", "Prosperity", "Renaissance", "Rising Sun", "Seaside"]
        assert {c["expansion"] for c in lobby["available"]} == {"Base", "Adventures", "Alchemy", "Allies", "Cornucopia & Guilds", "Dark Ages", "Empires", "Hinterlands", "Intrigue", "Menagerie", "Nocturne", "Plunder", "Promos", "Prosperity", "Renaissance", "Rising Sun", "Seaside"} and len(lobby["available"]) == 498
        await guest.say(type="set_expansions", expansions=["Base"])
        assert guest.last_error() == "Only the host can do that."
        for bad in ([], ["Nope"], ["Base", "Base"], "Base", None, [1], ["Base", "Nope"]):
            await host.say(type="set_expansions", expansions=bad)
            assert "at least one card set" in host.last_error(), bad
        await host.say(type="set_expansions", expansions=["Intrigue"])
        assert host.last("lobby")["expansions"] == ["Intrigue"] and guest.last("lobby")["expansions"] == ["Intrigue"]
        await host.say(type="start")
        kingdom = [x["name"] for x in host.view["piles"] if x["kingdom"]]
        assert set(kingdom) <= set(kingdom_cards(["Intrigue"])) and len(kingdom) == 10
        await host.say(type="set_expansions", expansions=["Base"])
        assert "already started" in host.last_error()
    run(scenario())


def test_custom_kingdom_may_mix_sets_and_ignores_card_set_choice():
    from test_web import RoomManager, run, two_player_room

    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, _ = await two_player_room(m)
        await host.say(type="set_expansions", expansions=["Base"])
        await host.say(type="set_kingdom", kingdom=["Village", "Nobles", "Torturer"])
        await host.say(type="start")
        assert sorted(x["name"] for x in host.view["piles"] if x["kingdom"]) == ["Nobles", "Torturer", "Village"]
    run(scenario())


def test_view_exposes_expansion_price_and_trash():
    g = make_game(players=2, kingdom=["Bridge", "Nobles", "Village"], seed=1)
    v = build_view(g, 0)
    assert v["cards"]["Nobles"]["expansion"] == "Intrigue" and v["cards"]["Village"]["expansion"] == "Base"
    assert all(p["price"] == p["cost"] for p in v["piles"]) and v["cost_reduction"] == 0
    assert v["trash"] == []


# ------------------------------------------------------------------ README stays in sync with the code
def test_readme_card_tables_are_up_to_date():
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("gen_card_tables", root / "tools" / "gen_card_tables.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    text = (root / "README.md").read_text(encoding="utf-8")
    assert text == gen.updated_readme(text), "run: python tools/gen_card_tables.py --write"
    for name in kingdom_all():
        assert f"| **{name}** |" in text, name


def kingdom_all():
    from dominion.cards import kingdom_cards
    from dominion.cards.registry import fenced_cards
    return [*kingdom_cards(), *fenced_cards()]


def test_readme_update_history_covers_every_update():
    from pathlib import Path
    text = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
    for n in range(1, 15):
        assert f"### Update {n}:" in text


# ------------------------------------------------------------------ a bot answering Intrigue decisions on the live room code
def _human_turn_with(room, host, hand, bot_hand=None, deck=None):
    """Wait until it is Ann's turn (the bot may go first), then give her `hand`."""
    from test_web import wait_until

    async def go():
        await wait_until(lambda: room.game.state.current_player == 0 and room.game.state.pending is None
                         and room.game.state.status.value == "active")
        me = room.game.state.players[0]
        me.hand[:] = hand
        if deck is not None:
            me.deck[:] = deck
        if bot_hand is not None:
            room.game.state.players[1].hand[:] = bot_hand
    return go()


def test_bot_answers_torturer_and_masquerade_through_the_server():
    from test_web import RoomManager, run, two_player_room, wait_until

    async def scenario():
        m = RoomManager(bot_delay=0)
        host, _none, code = await two_player_room(m, bot=True)
        await host.say(type="set_kingdom", kingdom=["Torturer", "Masquerade", "Minion", "Village"])
        await host.say(type="start")
        room = m.rooms[code]

        await _human_turn_with(room, host, ["Torturer", "Copper"], ["Copper", "Copper", "Estate", "Copper", "Copper"],
                               deck=["Silver"] * 5)
        bot = room.game.state.players[1]
        bot_cards = len(bot.all_cards())
        await host.say(type="action", action={"type": "play_action", "card": "Torturer"})
        await wait_until(lambda: room.game.state.pending is None)
        # the bot either discarded 2 cards or took a Curse into its hand: it dealt with the text choice itself
        assert (len(bot.all_cards()) == bot_cards + 1 and "Curse" in bot.hand) or len(bot.discard) >= 2
        assert host.last_error() is None

        await host.say(type="action", action={"type": "end_phase"})
        await host.say(type="action", action={"type": "end_phase"})
        await _human_turn_with(room, host, ["Masquerade", "Estate", "Copper"], ["Copper"] * 5, deck=["Silver"] * 6)
        await host.say(type="action", action={"type": "play_action", "card": "Masquerade"})
        await wait_until(lambda: room.game.state.pending is not None and room.game.state.pending.decision.player == 0)
        await host.say(type="action", action={"type": "choose", "selection": ["Estate"]})
        await wait_until(lambda: room.game.state.pending is not None and room.game.state.pending.decision.player == 0
                         and room.game.state.pending.decision.min_choices == 0)       # the optional trash is mine again
        await host.say(type="action", action={"type": "choose", "selection": []})
        assert room.game.state.pending is None
        assert host.last_error() is None
    run(scenario())

# ======================================================================
# from test_update8.py
# ======================================================================

KINGDOM__update8 = ["Moat", "Village", "Smithy", "Militia", "Witch"]


def sg(players=3, cats=("Rosebud",), **kw):
    return make_game(players=players, kingdom=KINGDOM__update8, catastrophes=list(cats), **kw)


def play__update8(g, card, player=0):
    g.apply(player, PlayAction(card))


def answer__update8(g, player, *cards):
    g.apply(player, Choose(tuple(cards)))


def log_text__update8(g):
    return "\n".join(str(x) for x in g.state.log)


# ------------------------------------------------------------------ the cards themselves
def test_special_cards_are_registered_and_fenced_like_catastrophes():
    assert special_cards() == [
        "Chance Time", "Exodia the Forbidden One", "God Mode", "Guardian Angel", "Invisibility Cloak", "Midas Touch", "Rosebud",
    ]
    assert set(fenced_cards()) == set(catastrophe_cards()) | set(special_cards())
    for n in special_cards():
        c = get_card(n)
        assert c.is_type(CardType.SPECIAL) and not c.kingdom and c.expansion == "Special"
        assert c.is_type(CardType.ACTION) == (n != "Exodia the Forbidden One")      # the Exodia pieces are not playable
    assert [get_card(n).cost for n in ("Rosebud", "Guardian Angel", "God Mode")] == [5, 6, 10]


def test_special_cards_get_two_copy_piles_and_never_end_the_game():
    g = sg(cats=("Rosebud", "God Mode"))
    assert g.state.supply["Rosebud"] == 2 and g.state.supply["God Mode"] == 2
    g.state.supply["Rosebud"] = g.state.supply["God Mode"] = 0
    g.state.supply["Village"] = 0
    g.state.supply["Moat"] = 0
    assert g.state.status is GameStatus.ACTIVE
    from dominion.engine.rules import is_game_over
    assert not is_game_over(g.state)                       # only 2 ordinary piles are empty


def test_special_cards_are_never_in_a_random_kingdom_and_need_the_host_to_pick_them():
    from dominion.cards import kingdom_cards
    assert not set(special_cards()) & set(kingdom_cards())
    g = make_game(players=2, kingdom=KINGDOM__update8, catastrophes=["Rosebud", "God Mode", "Guardian Angel"])   # no limit on how many
    assert all(g.state.supply[n] == 2 for n in ("Rosebud", "God Mode", "Guardian Angel"))


def test_lurker_cannot_touch_special_cards():
    g = make_game(players=2, kingdom=["Lurker", "Village"], catastrophes=["Rosebud"])
    set_zones(g, 0, hand=["Lurker"])
    play__update8(g, "Lurker")
    assert "Rosebud" not in g.state.pending.decision.options


# ------------------------------------------------------------------ Rosebud
def test_rosebud_gives_money_to_yourself_right_away():
    g = sg()
    set_zones(g, 0, hand=["Rosebud", "Copper"])
    play__update8(g, "Rosebud")
    assert g.state.trash == ["Rosebud"]
    d = g.state.pending.decision
    assert d.options == ("P0", "P1", "P2")
    answer__update8(g, 0, "P0")
    assert g.state.coins == 12
    assert "ROSEBUD" in log_text__update8(g)


def test_rosebud_for_another_player_arrives_at_the_start_of_their_next_turn():
    g = sg()
    set_zones(g, 0, hand=["Rosebud"])
    play__update8(g, "Rosebud")
    answer__update8(g, 0, "P2")
    assert g.state.players[2].bonus_coins == 12 and g.state.coins == 0
    assert "P2 will get +$12" in log_text__update8(g)
    g.apply(0, EndPhase()); g.apply(0, EndPhase())        # P1's turn: P2's gift is not theirs
    assert g.state.coins == 0 and g.state.players[2].bonus_coins == 12
    g.apply(1, EndPhase()); g.apply(1, EndPhase())        # P2's turn
    assert g.state.current_player == 2 and g.state.coins == 12 and g.state.players[2].bonus_coins == 0
    assert "P2 receives $12 from Rosebud" in log_text__update8(g)
    g.apply(2, EndPhase())
    assert g.state.coins == 12                            # still there in the Buy phase
    g.apply(2, EndPhase())
    g.apply(0, EndPhase()); g.apply(0, EndPhase())
    assert g.state.coins == 0                             # one-off: nothing the following turns


def test_rosebud_gift_waits_through_a_skipped_turn():
    g = sg(cats=("Rosebud", "Long Night"))
    g.state.players[1].bonus_coins = 12
    g.state.players[1].skips = 1
    g.apply(0, EndPhase()); g.apply(0, EndPhase())        # P1's turn is skipped, P2 plays
    assert g.state.current_player == 2 and g.state.players[1].bonus_coins == 12
    g.apply(2, EndPhase()); g.apply(2, EndPhase())
    g.apply(0, EndPhase()); g.apply(0, EndPhase())
    assert g.state.current_player == 1 and g.state.coins == 12


def test_rosebud_money_buys_things_and_is_single_use_under_throne_room():
    g = make_game(players=2, kingdom=["Throne Room", "Village"], catastrophes=["Rosebud"])
    set_zones(g, 0, hand=["Throne Room", "Rosebud"])
    play__update8(g, "Throne Room")
    answer__update8(g, 0, "Rosebud")
    answer__update8(g, 0, "P0")
    assert g.state.pending is None and g.state.coins == 12 and g.state.trash == ["Rosebud"]
    to_buy_phase(g)
    g.apply(0, Buy("Province"))
    assert g.state.coins == 4


# ------------------------------------------------------------------ Guardian Angel / God Mode
def test_guardian_angel_protects_for_five_of_your_own_turns():
    g = sg(cats=("Guardian Angel",), players=2)
    set_zones(g, 0, hand=["Guardian Angel"], deck=["Gold", "Gold"])
    play__update8(g, "Guardian Angel")
    me = g.state.players[0]
    assert len(me.hand) == 2 and me.protection == 5 and g.state.trash == ["Guardian Angel"]
    view = build_view(g, 1)["players"][0]
    assert view["protection"] == 5
    for turn in range(5):                                       # her 5 following turns
        g.apply(0, EndPhase()); g.apply(0, EndPhase())          # end this turn
        assert me.protection == 5 - turn if turn else me.protection == 5
        assert me.protection > 0
        g.apply(1, EndPhase()); g.apply(1, EndPhase())          # opponent's turn: she is protected throughout
    # the 5th later turn has not been played yet: protection is still on
    assert me.protection == 1
    g.apply(0, EndPhase()); g.apply(0, EndPhase())              # end of her 5th turn after the one it was played
    assert me.protection == 0
    assert "protection runs out" in log_text__update8(g)


def test_attacks_skip_a_protected_player_without_asking_questions():
    g = sg(cats=("Guardian Angel",))
    g.state.players[1].protection = 3
    set_zones(g, 0, hand=["Militia"])
    set_zones(g, 1, hand=["Moat", "Copper", "Copper", "Copper", "Copper"])
    set_zones(g, 2, hand=["Copper"] * 5)
    play__update8(g, "Militia")
    # P1 is protected: no Moat prompt and nobody makes them discard; P2 is asked to discard
    d = g.state.pending.decision
    assert d.player == 2 and d.min_choices == 2
    assert len(g.state.players[1].hand) == 5
    assert "P1 is protected and unaffected" in log_text__update8(g)


def test_protection_covers_witch_and_targeted_catastrophes():
    g = sg(cats=("Grand Swap", "Time Stop"))
    g.state.players[1].protected_forever = True
    set_zones(g, 0, hand=["Grand Swap"], deck=["Gold"] * 4)
    set_zones(g, 1, deck=["Copper"] * 4)
    play__update8(g, "Grand Swap")
    answer__update8(g, 0, "P1")
    assert g.state.players[0].deck == ["Gold"] * 4          # nothing was swapped
    assert g.state.players[1].deck == ["Copper"] * 4
    g2 = sg(cats=("The Snap",))
    g2.state.players[1].protected_forever = True
    set_zones(g2, 0, hand=["The Snap"], deck=["Gold"] * 6)
    set_zones(g2, 1, hand=["Copper"] * 5, deck=["Copper"] * 5)
    play__update8(g2, "The Snap")
    assert len(g2.state.players[1].all_cards()) == 10       # protected player untouched
    assert len(g2.state.players[0].all_cards()) == 3        # the player who played it is always hit


def test_protection_does_not_stop_things_that_are_not_attacks():
    g = sg(cats=("Cataclysm",))
    g.state.players[1].protected_forever = True
    set_zones(g, 0, hand=["Cataclysm", "Gold"], deck=["Gold"] * 3)
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Copper"] * 5)
    play__update8(g, "Cataclysm")
    assert "Every deck is combined" in log_text__update8(g)


def test_god_mode_is_permanent_and_gives_a_big_turn():
    g = sg(cats=("God Mode",), players=2)
    set_zones(g, 0, hand=["God Mode"])
    play__update8(g, "God Mode")
    s = g.state
    assert (s.actions, s.buys, s.coins) == (3, 4, 5)                  # played one action: 0 + 3 ; buys 1 + 3 ; $5
    assert s.players[0].protected_forever and s.trash == ["God Mode"]
    for _ in range(12):
        g.apply(g.state.current_player, EndPhase()); g.apply(g.state.current_player, EndPhase())
    assert s.players[0].protected_forever
    assert build_view(g, 1)["players"][0]["protection"] == "forever"
    assert "GOD MODE" in log_text__update8(g)


def test_guardian_angel_replayed_keeps_the_stronger_protection():
    g = sg(cats=("Guardian Angel",), players=2)
    g.state.players[0].protection = 3
    set_zones(g, 0, hand=["Guardian Angel", "Guardian Angel"], in_play=[])
    g.state.actions = 2
    play__update8(g, "Guardian Angel")
    assert g.state.players[0].protection == 5
    g.state.players[0].protection = 5
    play__update8(g, "Guardian Angel")
    assert g.state.players[0].protection == 5


# ------------------------------------------------------------------ resign / end game
def test_resign_ends_the_game_and_the_resigner_cannot_win():
    g = make_game(players=2, kingdom=KINGDOM__update8, seed=1)
    g.state.players[0].discard.extend(["Province"] * 4)            # P0 is far ahead ...
    g.apply(0, Resign())                                           # ... but resigns
    s = g.state
    assert s.status is GameStatus.FINISHED and s.winners == [1] and s.resigned == [0]
    assert s.end_reason == "P0 resigned."
    v = build_view(g, 1)
    assert v["status"] == "finished" and v["end_reason"] == "P0 resigned." and v["resigned"] == [0] and "stats" in v
    assert "P0 resigns." in log_text__update8(g)


def test_a_player_may_resign_off_turn_and_mid_decision():
    g = make_game(players=3, kingdom=KINGDOM__update8, seed=1)
    g.apply(2, Resign())                                           # not their turn
    assert g.state.winners and 2 not in g.state.winners
    g = make_game(players=2, kingdom=KINGDOM__update8, seed=1)
    set_zones(g, 0, hand=["Militia"])
    set_zones(g, 1, hand=["Copper"] * 5)
    play__update8(g, "Militia")
    assert g.state.pending is not None
    g.apply(1, Resign())                                           # in the middle of an Attack
    assert g.state.pending is None and g.state.winners == [0]


def test_end_game_keeps_the_current_scores():
    g = make_game(players=3, kingdom=KINGDOM__update8, seed=1)
    g.state.players[2].discard.extend(["Province"] * 2)
    g.apply(1, EndGame())
    assert g.state.status is GameStatus.FINISHED and g.state.winners == [2] and g.state.resigned == []
    assert g.state.end_reason == "P1 ended the game early."


def test_nothing_is_possible_after_the_game_ends_and_bots_never_resign():
    g = make_game(players=2, kingdom=KINGDOM__update8, seed=1)
    g.apply(0, Resign())
    for action in (Resign(), EndGame(), Cheat("coins"), EndPhase()):
        with pytest.raises(IllegalActionError):
            g.apply(0, action)
    g = make_game(players=2, kingdom=KINGDOM__update8, seed=1)
    assert not any(isinstance(a, (Resign, EndGame, Cheat)) for a in legal_actions(g.state))


def test_resign_is_part_of_the_history_and_replays():
    g = make_game(players=2, kingdom=KINGDOM__update8, seed=1)
    g.apply(0, EndPhase()); g.apply(0, EndPhase())
    g.apply(1, Resign())
    r = replay(g.config, g.history)
    assert r.state.status is GameStatus.FINISHED and r.state.winners == g.state.winners == [0]
    assert [str(x) for x in r.state.log] == [str(x) for x in g.state.log]


def test_resign_with_everyone_else_resigned_still_has_a_winner():
    from dominion.engine.scoring import determine_winners
    g = make_game(players=2, kingdom=KINGDOM__update8, seed=1)
    g.state.resigned = [0, 1]
    assert determine_winners(g.state) in ([0, 1], [0], [1])


# ------------------------------------------------------------------ cheat codes
def cheat_game(**kw):
    g = new_game(GameConfig(["P0", "P1"], KINGDOM__update8, 1, cheats=True, **kw))
    return g


def test_cheats_give_100_of_each_on_your_own_turn_and_are_logged():
    g = cheat_game()
    g.apply(0, Cheat("coins")); g.apply(0, Cheat("actions")); g.apply(0, Cheat("buys"))
    s = g.state
    assert (s.coins, s.actions, s.buys) == (100, 101, 101)
    assert "P0 uses a cheat code: +100 coins!" in log_text__update8(g)
    assert s.log[-1].kind == "cheat"
    assert build_view(g, 0)["cheats"] is True


def test_cheats_really_work_in_play():
    g = cheat_game()
    set_zones(g, 0, hand=["Village", "Village", "Village", "Copper", "Copper"], in_play=[])
    g.apply(0, Cheat("actions"))
    for _ in range(3):
        play__update8(g, "Village")
    g.apply(0, Cheat("coins")); g.apply(0, Cheat("buys"))
    to_buy_phase(g)
    for _ in range(5):
        g.apply(0, Buy("Province"))
    assert g.state.coins == 100 - 40 and g.state.buys == 101 - 5 and g.state.supply["Province"] == 3


def test_cheats_are_refused_when_off_off_turn_mid_decision_or_unknown():
    g = make_game(players=2, kingdom=KINGDOM__update8, seed=1)              # cheats not enabled
    with pytest.raises(IllegalActionError, match="not turned on"):
        g.apply(0, Cheat("coins"))
    g = cheat_game()
    with pytest.raises(IllegalActionError, match="your own turn"):
        g.apply(1, Cheat("coins"))
    with pytest.raises(IllegalActionError, match="Unknown cheat"):
        g.apply(0, Cheat("lives"))
    set_zones(g, 0, hand=["Militia"])
    play__update8(g, "Militia")
    with pytest.raises(IllegalActionError, match="pending decision"):
        g.apply(0, Cheat("coins"))
    assert g.state.coins == 2                                        # nothing was given


def test_cheats_reset_each_turn_and_replay():
    g = cheat_game()
    g.apply(0, Cheat("coins"))
    g.apply(0, EndPhase()); g.apply(0, EndPhase())
    assert g.state.coins == 0 and g.state.actions == 1 and g.state.buys == 1
    g.apply(1, Cheat("buys"))
    r = replay(g.config, g.history)
    assert r.state.buys == 101 and [str(x) for x in r.state.log] == [str(x) for x in g.state.log]


# ------------------------------------------------------------------ random play with the new cards
@pytest.mark.parametrize("players", [2, 3, 4])
def test_random_games_with_special_cards_keep_every_card_and_protection_sane(players):
    for seed in range(8):
        rng = random.Random(seed)
        g = make_game(players=players, kingdom=KINGDOM__update8, catastrophes=["Rosebud", "Guardian Angel"], seed=seed)
        for p in g.state.players:
            p.deck.extend(["Rosebud", "Guardian Angel", "Militia", "Witch"])
            rng.shuffle(p.deck)
        before = total_cards(g)
        bots = [RandomBot(random.Random(rng.random())) for _ in range(players)]
        for _ in range(1200):
            if g.state.status is GameStatus.FINISHED:
                break
            play_checked(g, bots)
            assert total_cards(g) == before
            for p in g.state.players:
                assert 0 <= p.protection <= 5 and p.bonus_coins in (0, 12, 24, 36)


# ================================================================== the server side
def _chat_texts(client):
    return [m["text"] for m in client.inbox if m["type"] == "chat"]


def test_host_turns_cheat_codes_on_and_they_work_through_the_chat():
    from test_web import Client, RoomManager, run, two_player_room

    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, code = await two_player_room(m)
        assert host.last("lobby")["cheats"] is False                    # off by default
        await guest.say(type="set_cheats", cheats=True)
        assert guest.last_error() == "Only the host can do that."
        for bad in ("yes", 1, None):
            await host.say(type="set_cheats", cheats=bad)
            assert "on or off" in host.last_error(), bad
        # while cheats are off a "cheat phrase" is only chat, in the lobby and in the game
        await host.say(type="chat", text="show me the money")
        assert "show me the money" in _chat_texts(guest)
        await host.say(type="set_cheats", cheats=True)
        assert host.last("lobby")["cheats"] and guest.last("lobby")["cheats"]
        await host.say(type="chat", text="greed is good")                # lobby: still just chat
        assert "greed is good" in _chat_texts(guest)
        await host.say(type="start")
        assert host.view["cheats"] is True and guest.view["cheats"] is True
        seen = len(_chat_texts(guest))

        await host.say(type="chat", text="  Show   ME the Money ")      # case and spacing do not matter
        assert host.view["coins"] == 100 and guest.view["coins"] == 100
        await host.say(type="chat", text="power overwhelming")
        await host.say(type="chat", text="greed is good")
        assert (host.view["actions"], host.view["buys"]) == (101, 101)
        assert len(_chat_texts(guest)) == seen, "a cheat code must not appear as chat"
        assert any("Ann uses a cheat code: +100 coins" in e["text"] for e in guest.view["log"])
        assert any(e["kind"] == "cheat" for e in guest.view["log"])

        await guest.say(type="chat", text="show me the money")           # not the guest's turn
        assert "your own turn" in guest.last_error()
        assert guest.view["coins"] == 100                                 # the host's coins, unchanged by the guest
        assert len(_chat_texts(host)) == seen

        # cheats can be taken back with an undo, like any other action
        await host.say(type="undo_request")
        await guest.say(type="undo_vote", approve=True)
        assert (host.view["coins"], host.view["actions"], host.view["buys"]) == (100, 101, 1)   # only the last cheat is taken back
    run(scenario())


def test_cheats_off_means_the_phrase_is_chat_in_the_game():
    from test_web import RoomManager, run, two_player_room

    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, code = await two_player_room(m)
        await host.say(type="start")
        await host.say(type="chat", text="show me the money")
        assert "show me the money" in _chat_texts(guest) and host.view["coins"] == 0
    run(scenario())


def test_cheat_chat_is_refused_during_an_undo_vote():
    from test_web import RoomManager, run, two_player_room

    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, code = await two_player_room(m)
        await host.say(type="set_cheats", cheats=True)
        await host.say(type="start")
        room = m.rooms[code]
        await host.say(type="action", action={"type": "end_phase"})
        await host.say(type="undo_request")
        await host.say(type="chat", text="greed is good")
        assert "undo vote" in host.last_error()
        assert room.game.state.buys == 1
    run(scenario())


def test_my_games_list_shows_only_games_you_hold_a_token_for():
    from test_web import Client, RoomManager, run, two_player_room

    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, code = await two_player_room(m)
        other_host = Client(m)
        await other_host.say(type="create", name="Zed")
        other_code = other_host.last("joined")["room"]
        home = Client(m)                                                   # a browser on the home page
        mine = [{"room": code, "token": host.token}, {"room": other_code, "token": host.token},
                {"room": "ZZZZ", "token": "x"}, {"room": code, "token": "wrong"}, "junk", {"room": 5}]
        await home.say(type="list_games", games=mine)
        reply = home.last("games")
        assert [g["room"] for g in reply["games"]] == [code]
        g = reply["games"][0]
        assert g["status"] == "lobby" and g["players"] == ["Ann", "Bo"] and g["you"] == 0 and g["is_host"] is True
        assert reply["gone"] == [other_code, "ZZZZ", code, "", "5"]
        await host.say(type="start")
        await home.say(type="list_games", games=[{"room": code, "token": guest.token}])
        g = home.last("games")["games"][0]
        assert g["status"] == "playing" and g["you"] == 1 and g["is_host"] is False
        assert g["your_turn"] is False and g["turn"] == 1
        await home.say(type="list_games", games=[{"room": code, "token": host.token}])
        assert home.last("games")["games"][0]["your_turn"] is True
        await guest.say(type="resign")
        await home.say(type="list_games", games=[{"room": code, "token": host.token}])
        assert home.last("games")["games"][0]["status"] == "finished"
        for bad in ("x", None, [{}] * 21, 5):
            await home.say(type="list_games", games=bad)
            assert "up to 20" in home.last_error()
        assert "Zed" not in json.dumps(home.last("games"))                 # other rooms never leak
    run(scenario())


def test_resign_end_game_and_rematch_through_the_server():
    from test_web import RoomManager, run, two_player_room

    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, code = await two_player_room(m)
        await guest.say(type="resign")
        assert "no game to resign" in guest.last_error()
        await host.say(type="end_game")
        assert "no game to end" in host.last_error()
        await host.say(type="start")
        await guest.say(type="end_game")
        assert guest.last_error() == "Only the host can do that."
        assert host.view["status"] == "active"
        await guest.say(type="resign")                                    # not their turn: still fine
        for c in (host, guest):
            assert c.view["status"] == "finished" and c.view["winners"] == [0]
            assert c.view["end_reason"] == "Bo resigned." and c.view["resigned"] == [1]
        await host.say(type="resign")
        assert "already over" in host.last_error()
        await host.say(type="rematch")
        assert host.last("lobby") is not None and host.inbox[-1]["type"] == "lobby"
        # the host ends a game early: scores count, nobody resigned
        await host.say(type="start")
        m.rooms[code].game.state.players[1].discard.extend(["Province"] * 2)
        await host.say(type="end_game")
        assert host.view["status"] == "finished" and host.view["winners"] == [1] and host.view["resigned"] == []
        assert host.view["end_reason"] == "Ann ended the game early."
        assert [s["name"] for s in host.view["stats"]] == ["Ann", "Bo"]
    run(scenario())


def test_resigning_cancels_a_pending_undo_vote():
    from test_web import RoomManager, run, two_player_room

    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, code = await two_player_room(m)
        await host.say(type="start")
        await host.say(type="action", action={"type": "end_phase"})
        await host.say(type="undo_request")
        assert m.rooms[code].undo is not None
        await guest.say(type="resign")
        assert m.rooms[code].undo is None and host.view["status"] == "finished"
        assert "undo" in " ".join(_chat_texts(host)).lower()
    run(scenario())


def test_only_the_host_can_delete_a_game_and_everyone_is_sent_home():
    from test_web import Client, RoomManager, run, two_player_room

    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, code = await two_player_room(m)
        home = Client(m)
        await home.say(type="delete_room", room=code, token=guest.token)
        assert home.last_error() == "Only the host can delete a game." and code in m.rooms
        for bad in ({"room": "NOPE", "token": "x"}, {"room": code, "token": "wrong"}, {"room": code}, {}):
            await home.say(type="delete_room", **bad)
            assert home.last_error() == "Game not found."
        await host.say(type="start")
        await home.say(type="delete_room", room=code, token=host.token)    # from the home page, mid-game
        assert code not in m.rooms
        assert home.inbox[-1] == {"type": "deleted", "room": code}
        for c in (host, guest):
            assert c.inbox[-1] == {"type": "left", "reason": "The host deleted this game."}
            assert c.conn.room is None
        await host.say(type="join", room=code, name="Ann", token=host.token)
        assert host.last_error() == "Room not found."
    run(scenario())


def test_delete_a_lobby_with_a_bot_and_no_leftover_tasks():
    from test_web import RoomManager, run, two_player_room

    async def scenario():
        m = RoomManager(bot_delay=0)
        host, _none, code = await two_player_room(m, bot=True)
        await host.say(type="start")
        room = m.rooms[code]
        await host.say(type="delete_room", room=code, token=host.token)
        assert code not in m.rooms
        await __import__("asyncio").sleep(0.05)
        assert room.bot_task is None or room.bot_task.done()
    run(scenario())


# ================================================================== the page's stylesheet
def test_every_card_css_class_is_one_the_page_really_puts_on_cards():
    """A rule like `.card.catastrophe` (a class no card ever has) once made Catastrophe cards unreadable."""
    import re
    from pathlib import Path
    from dominion.cards import CardType

    html = (Path(__file__).resolve().parent.parent / "src/dominion/web/static/index.html").read_text(encoding="utf-8")
    used = set(re.findall(r"\.card\.([a-z][a-z-]*)", html))
    real = {"small", "big", "clickable", "dim", "empty", "selected", "enter", "flash", "walled", "blind", "long", "xlong"} | {f"t-{t.value}" for t in CardType}
    assert used <= real, f"CSS styles card classes nothing ever sets: {sorted(used - real)}"
    # and the classes the script sets on cards are exactly these
    assert "c.classList.add(...info.types.map((t) => \"t-\" + t))" in html
    for cls in ("walled", "blind", "long", "xlong"):     # classes added later are really set by the script
        assert f'classList.add("{cls}")' in html, cls


# ================================================================== package layout (the "mixed-up __init__.py" upload problem)
def test_top_level_package_exports_the_cards_and_each_init_file_has_its_own_content():
    from pathlib import Path
    import dominion

    assert dominion.__version__ and dominion.get_card("Smithy").cost == 4
    assert {"CardDef", "CardType", "get_card", "kingdom_cards", "register"} <= set(dominion.__all__)
    root = Path(dominion.__file__).parent
    top = (root / "__init__.py").read_text(encoding="utf-8")
    cards = (root / "cards" / "__init__.py").read_text(encoding="utf-8")
    assert "from .cards.base import" in top and "from .base import" not in top      # not the cards file
    assert "from .base import" in cards and "from .cards.base import" not in cards  # not the top-level file
    for sub in ("cards", "engine", "ai", "ui", "web"):
        assert (root / sub / "__init__.py").is_file(), f"{sub}/__init__.py is missing (flattened upload?)"
    assert len({(root / p / "__init__.py").read_text(encoding="utf-8") for p in ("", "cards", "engine", "ai", "ui", "web")}) == 6


# ================================================================== update 10: the page's structure, written down as tests
def _page():
    from pathlib import Path
    return (Path(__file__).resolve().parent.parent / "src/dominion/web/static/index.html").read_text(encoding="utf-8")


def test_the_game_is_called_modinion_everywhere_the_player_can_see_it():
    import re
    html = _page()
    assert "<title>Modinion</title>" in html and "<h1>Modinion</h1>" in html and "Play Modinion online" in html
    text = re.sub(r"<script>.*?</script>|<style>.*?</style>|<!--.*?-->", "", html, flags=re.S)
    assert "Dominion" not in text, "the old name is still visible in the page"
    script = re.search(r"<script>(.*?)</script>", html, flags=re.S).group(1)
    assert "Your turn - Modinion" in script and "- Dominion" not in script
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    assert (root / "README.md").read_text(encoding="utf-8").startswith("# Modinion")
    assert "Deploying Modinion" in (root / "docs/DEPLOY.md").read_text(encoding="utf-8")


def test_the_page_is_laid_out_without_scrolling_players_left_turn_bar_bottom_right():
    import re
    html = _page()
    css = re.search(r"<style>(.*?)</style>", html, flags=re.S).group(1)
    assert re.search(r"html, body \{[^}]*overflow: hidden", css), "the page itself must never scroll"
    assert re.search(r"#game-grid \{[^}]*grid-template-columns: 230px minmax\(0, 1fr\) 330px", css)
    assert "max-height: 940px" in css and "--cw" in css                    # card size follows the screen height
    for panel in ("#supply-panel", "#hand-panel", "#inplay-panel", "#log, #chat-log", "#players-panel .players"):
        assert re.search(re.escape(panel) + r" \{[^}]*overflow(-y)?: auto", css), f"{panel} must scroll inside itself when it is too full"
    assert re.search(r"#popup-layer \{[^}]*position: fixed[^}]*justify-content: center", css)
    pos = {name: html.index(f'id="{name}"') for name in (
        "left-col", "players", "center-col", "supply-panel", "bottom-row", "right-col", "log-panel", "chat-slot-game",
        "topbar", "popup-layer", "decision", "undo-panel", "gameover")}
    assert pos["left-col"] < pos["players"] < pos["center-col"] < pos["supply-panel"] < pos["bottom-row"] < pos["right-col"]
    assert pos["right-col"] < pos["log-panel"] < pos["chat-slot-game"] < pos["topbar"], "log, chat, then the turn bar at the bottom"
    assert pos["popup-layer"] < pos["undo-panel"] < pos["decision"] < pos["gameover"]
    for removed in ("btn-deck-view", "btn-discard-view", "All the cards you own", "Your discard pile", "my_discard", "my_cards", "discard_count"):
        assert removed not in html, f"{removed} must be gone: players may not look through or count their discard pile"
    assert "brings " not in html.replace("brings it back", "") and "more pieces" not in html, "the Exodia lobby label is just the name and the cost"

# ======================================================================
# from test_update9.py
# ======================================================================

KINGDOM__update9 = ["Moat", "Village", "Smithy", "Militia", "Workshop", "Council Room", "Witch", "Masquerade"]
HEAD, RA, LA, RL, LL = EXODIA_PIECES


def g_with(cards, players=3, **kw):
    return make_game(players=players, kingdom=KINGDOM__update9, catastrophes=list(cards), **kw)


def play__update9(g, card, player=0):
    g.apply(player, PlayAction(card))


def answer__update9(g, player, *cards):
    g.apply(player, Choose(tuple(cards)))


def log_text__update9(g):
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
    play__update9(g, "Village")                                            # draws the head: five pieces
    s = g.state
    assert s.status is GameStatus.FINISHED and s.winners == [0]
    assert "holding all five pieces of Exodia" in s.end_reason
    assert "EXODIA!" in log_text__update9(g) and any(l.kind == "special" and "EXODIA!" in l for l in s.log)
    v = build_view(g, 1)
    assert v["status"] == "finished" and v["winners"] == [0] and v["end_reason"] == s.end_reason and "stats" in v


def test_exodia_needs_all_five_different_pieces_in_the_hand_at_the_same_time():
    g = g_with([HEAD], players=2)
    set_zones(g, 0, hand=["Village", RA, LA, RL, "Copper"], deck=[LA, "Copper"])          # a second Left Arm, no Left Leg... no head
    play__update9(g, "Village")
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
    play__update9(g, "Council Room")                                       # each other player draws a card: P1 gets the last piece
    assert g.state.status is GameStatus.FINISHED and g.state.winners == [1]


def test_exodia_win_survives_a_replay():
    g = new_game(GameConfig(["A", "B"], KINGDOM__update9, 3, catastrophes=[HEAD], cheats=True))
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
    play__update9(g, "Invisibility Cloak")
    assert g.state.players[0].invisible and g.state.trash == ["Invisibility Cloak"]
    assert "puts on the Invisibility Cloak" in log_text__update9(g)
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
    play__update9(g, "Militia", cur)
    assert "P0 is protected and unaffected" in log_text__update9(g)
    assert len(g.state.players[0].hand) == 5


def test_cataclysm_leaves_the_cloaked_player_alone():
    g = g_with(["Cataclysm"], players=3)
    g.state.players[1].invisible = True
    set_zones(g, 0, hand=["Cataclysm", "Gold"], deck=["Gold"] * 3)
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Silver"] * 5, discard=["Estate"] * 2)
    set_zones(g, 2, hand=["Copper"] * 5, deck=["Copper"] * 5)
    keep = (list(g.state.players[1].hand), list(g.state.players[1].deck), list(g.state.players[1].discard))
    before = total_cards(g)
    play__update9(g, "Cataclysm")
    p1 = g.state.players[1]
    assert (p1.hand, p1.deck, p1.discard) == keep
    assert total_cards(g) == before
    assert "P1 is invisible and keeps their cards" in log_text__update9(g)
    assert sum(1 for l in g.state.log if l.kind == "summary") == 2          # only P0 and P2 took part


def test_cloaked_player_who_plays_cataclysm_still_takes_part():
    g = g_with(["Cataclysm"], players=2)
    g.state.players[0].invisible = True
    set_zones(g, 0, hand=["Cataclysm", "Gold"], deck=["Gold"] * 3)
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Copper"] * 5)
    play__update9(g, "Cataclysm")
    assert sum(1 for l in g.state.log if l.kind == "summary") == 2


def test_masquerade_passes_around_a_cloaked_player():
    g = g_with(["Invisibility Cloak"], players=3)
    g.state.players[1].invisible = True
    set_zones(g, 0, hand=["Masquerade", "Copper"], deck=["Silver", "Silver"])
    set_zones(g, 1, hand=["Gold", "Gold"])
    set_zones(g, 2, hand=["Duchy"])
    play__update9(g, "Masquerade")
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
    play__update9(g, "Fortnite")
    answer__update9(g, 0, "Gold")
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
    play__update9(g, "Midas Touch")
    assert g.state.midas and g.state.trash == ["Midas Touch"]
    assert build_view(g, 1)["midas"] is True
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    assert g.state.coins == 12                                    # four Treasures at $3 each
    assert "plays Copper as Gold (+$3)" in log_text__update9(g) and "plays Gold (+$3)" in log_text__update9(g)
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
    play__update9(g, "Midas Touch")
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    assert g.state.coins == 6


def test_midas_touch_is_single_use_and_does_not_stack_oddly_with_throne_room():
    g = make_game(players=2, kingdom=["Throne Room"], catastrophes=["Midas Touch"])
    set_zones(g, 0, hand=["Throne Room", "Midas Touch", "Copper"])
    play__update9(g, "Throne Room")
    answer__update9(g, 0, "Midas Touch")
    assert g.state.trash == ["Midas Touch"] and g.state.pending is None
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    assert g.state.coins == 3


# ================================================================== Fortnite
def test_fortnite_walls_up_to_three_piles_and_blocks_other_players_buying_and_gaining():
    g = g_with(["Fortnite"], players=3)
    set_zones(g, 0, hand=["Fortnite"])
    play__update9(g, "Fortnite")
    options = g.state.pending.decision.options
    assert "Gold" in options and "Province" in options and "Fortnite" not in options and "Curse" in options
    assert not set(options) & set(g.state.catastrophes)
    assert (g.state.pending.decision.min_choices, g.state.pending.decision.max_choices) == (0, 3)
    with pytest.raises(IllegalActionError):
        answer__update9(g, 0, "Gold", "Silver", "Duchy", "Province")
    answer__update9(g, 0, "Gold", "Province", "Workshop")
    assert g.state.walls == {"Gold": 0, "Province": 0, "Workshop": 0}
    assert "builds walls around Gold, Province, Workshop" in log_text__update9(g)
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
    play__update9(g, "Workshop", p1)
    assert "Silver" in g.state.pending.decision.options


def test_walls_come_down_when_the_builders_next_turn_starts_even_if_it_is_skipped():
    g = g_with(["Fortnite", "Long Night"], players=3)
    set_zones(g, 0, hand=["Fortnite"])
    play__update9(g, "Fortnite")
    answer__update9(g, 0, "Gold")
    end_turn(g); end_turn(g)                                      # P1 and P2 play with the wall up
    assert g.state.walls == {"Gold": 0}
    end_turn(g)                                                   # back to P0: the wall is gone
    assert g.state.walls == {} and "The wall around Gold comes down" in log_text__update9(g)
    g = g_with(["Fortnite", "Long Night"], players=3)
    set_zones(g, 0, hand=["Fortnite"])
    play__update9(g, "Fortnite")
    answer__update9(g, 0, "Gold")
    g.state.players[0].skips = 1                                  # P0's next turn is skipped
    end_turn(g); end_turn(g)
    end_turn(g)
    assert g.state.walls == {}                                    # still down: it never outlives its builder's turn slot


def test_fortnite_cannot_wall_walled_empty_or_single_use_piles_and_can_choose_nothing():
    g = g_with(["Fortnite", "Rosebud"], players=2)
    g.state.walls["Silver"] = 1
    g.state.supply["Duchy"] = 0
    set_zones(g, 0, hand=["Fortnite"])
    play__update9(g, "Fortnite")
    opts = g.state.pending.decision.options
    assert "Silver" not in opts and "Duchy" not in opts and "Rosebud" not in opts
    answer__update9(g, 0)                                                  # wall nothing
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
    play__update9(g, "Witch")
    assert g.state.pending is None and "Curse" not in g.state.players[1].discard    # the Curse could not be gained


def test_swindler_respects_walls_for_the_player_who_receives_the_card():
    g = make_game(players=2, kingdom=["Swindler", "Village", "Moat"], catastrophes=["Fortnite"])
    g.state.walls["Village"] = 0
    set_zones(g, 0, hand=["Swindler"])
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Silver", "Silver"])
    play__update9(g, "Swindler")
    assert "Village" not in g.state.pending.decision.options      # P1 would gain it: walled off
    g2 = make_game(players=2, kingdom=["Swindler", "Village", "Moat"], catastrophes=["Fortnite"])
    g2.state.walls["Village"] = 1                                 # walled by the victim: they may gain it
    set_zones(g2, 0, hand=["Swindler"])
    set_zones(g2, 1, hand=["Copper"] * 5, deck=["Silver", "Silver"])
    play__update9(g2, "Swindler")
    assert "Village" in g2.state.pending.decision.options


# ================================================================== Monopoly
def test_monopoly_everyone_pays_a_gold_then_a_silver_then_nothing():
    g = g_with(["Monopoly"], players=4)
    set_zones(g, 0, hand=["Monopoly"], discard=[])
    set_zones(g, 1, hand=["Gold", "Gold", "Silver", "Copper", "Copper"])
    set_zones(g, 2, hand=["Silver", "Copper", "Copper", "Copper", "Estate"])
    set_zones(g, 3, hand=["Copper"] * 5)
    before = total_cards(g)
    play__update9(g, "Monopoly")
    s = g.state
    assert sorted(s.players[0].discard) == ["Gold", "Silver"]
    assert sorted(s.players[1].hand) == ["Copper", "Copper", "Gold", "Silver"]
    assert "Silver" not in s.players[2].hand and s.players[3].hand == ["Copper"] * 5
    assert total_cards(g) == before and s.trash == ["Monopoly"]
    text = log_text__update9(g)
    assert "P1 pays P0 a Gold" in text and "P2 pays P0 a Silver" in text and "P3 has no Gold or Silver" in text
    assert "MONOPOLY!" in text


def test_monopoly_ignores_moat_but_respects_protection():
    g = g_with(["Monopoly", "Guardian Angel"], players=3)
    g.state.players[2].protection = 2
    set_zones(g, 0, hand=["Monopoly"], discard=[])
    set_zones(g, 1, hand=["Moat", "Gold", "Copper", "Copper", "Copper"])
    set_zones(g, 2, hand=["Gold"] * 5)
    play__update9(g, "Monopoly")
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
    play__update9(g, "Grand Theft Auto")
    d = g.state.pending.decision
    assert d.options == ("P1", "P2", "P3") and (d.min_choices, d.max_choices) == (1, 2)
    with pytest.raises(IllegalActionError):
        answer__update9(g, 0, "P1", "P2", "P3")
    before = total_cards(g)
    answer__update9(g, 0, "P1", "P3")
    assert sorted(g.state.players[0].discard) == ["Gold", "Province"]
    assert len(g.state.players[1].hand) == 4 and len(g.state.players[3].hand) == 4 and len(g.state.players[2].hand) == 5
    assert total_cards(g) == before
    text = log_text__update9(g)
    assert "P0 steals a Gold from P1!" in text and "P0 steals a Province from P3!" in text and "GRAND THEFT AUTO" in text


def test_grand_theft_auto_in_a_two_player_game_and_with_nothing_to_steal():
    g = g_with(["Grand Theft Auto"], players=2)
    set_zones(g, 0, hand=["Grand Theft Auto"], discard=[])
    set_zones(g, 1, hand=[])
    play__update9(g, "Grand Theft Auto")
    d = g.state.pending.decision
    assert d.options == ("P1",) and (d.min_choices, d.max_choices) == (1, 1)
    answer__update9(g, 0, "P1")
    assert g.state.players[0].discard == [] and "has no cards in hand to steal" in log_text__update9(g)


def test_grand_theft_auto_ignores_moat_respects_protection_and_is_random_but_seeded():
    g = g_with(["Grand Theft Auto"], players=3)
    g.state.players[2].protected_forever = True
    set_zones(g, 0, hand=["Grand Theft Auto"], discard=[])
    set_zones(g, 1, hand=["Moat", "Gold", "Gold", "Gold", "Gold"])
    set_zones(g, 2, hand=["Gold"] * 5)
    play__update9(g, "Grand Theft Auto")
    answer__update9(g, 0, "P1", "P2")
    assert g.state.pending is None
    assert len(g.state.players[0].discard) == 1 and g.state.players[0].discard == ["Gold"]    # one theft: P2 is protected, Moat did not help P1
    assert len(g.state.players[1].hand) == 4 and len(g.state.players[2].hand) == 5
    stolen = set()
    for seed in range(12):
        h = g_with(["Grand Theft Auto"], players=2, seed=seed)
        set_zones(h, 0, hand=["Grand Theft Auto"], discard=[])
        set_zones(h, 1, hand=["Gold", "Silver", "Copper", "Estate", "Duchy"])
        play__update9(h, "Grand Theft Auto"); answer__update9(h, 0, "P1")
        stolen.add(h.state.players[0].discard[0])
    assert len(stolen) >= 3


# ================================================================== Roofie
def test_roofie_blinds_other_players_until_the_end_of_their_next_turn():
    g = g_with(["Roofie"], players=3)
    set_zones(g, 0, hand=["Roofie"])
    play__update9(g, "Roofie")
    s = g.state
    assert [p.blind for p in s.players] == [0, 1, 1]
    assert "ROOFIE!" in log_text__update9(g) and "P1 is blinded" in log_text__update9(g)
    assert build_view(g, 1)["blind"] is True and build_view(g, 0)["blind"] is False
    assert [p["blind"] for p in build_view(g, 0)["players"]] == [0, 1, 1]
    end_turn(g)                                                   # P1's turn: still blind during it
    assert s.players[1].blind == 1 and build_view(g, 1)["blind"] is True
    end_turn(g)
    assert s.players[1].blind == 0 and "P1 can see again" in log_text__update9(g)
    assert s.players[2].blind == 1                                # P2's turn is next
    end_turn(g)
    assert s.players[2].blind == 0 and build_view(g, 2)["blind"] is False


def test_roofie_ignores_moat_respects_protection_and_does_not_stack():
    g = g_with(["Roofie"], players=3)
    g.state.players[2].protected_forever = True
    set_zones(g, 0, hand=["Roofie"])
    set_zones(g, 1, hand=["Moat"] + ["Copper"] * 4)
    play__update9(g, "Roofie")
    assert g.state.pending is None
    assert [p.blind for p in g.state.players] == [0, 1, 0]       # Moat did not help; protection did
    h = g_with(["Roofie"], players=2)
    h.state.players[1].blind = 1
    set_zones(h, 0, hand=["Roofie"])
    play__update9(h, "Roofie")
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
        play__update9(g, "Chance Time")
        for o in CHANCE_OUTCOMES:
            if f"lands on {o}!" in log_text__update9(g):
                seen[o] += 1
        assert g.state.trash.count("Chance Time") == 1
    assert set(seen) == set(CHANCE_OUTCOMES) and all(seen[o] >= 3 for o in CHANCE_OUTCOMES)


def test_chance_time_jackpot_and_coin_shower(monkeypatch):
    force(monkeypatch, 0)
    g = g_with(["Chance Time"], players=2)
    set_zones(g, 0, hand=["Chance Time"], discard=[])
    play__update9(g, "Chance Time")
    assert g.state.players[0].discard == ["Gold", "Gold"] and "CHANCE TIME! The wheel lands on JACKPOT!" in log_text__update9(g)
    force(monkeypatch, 1)
    g = g_with(["Chance Time"], players=2)
    set_zones(g, 0, hand=["Chance Time"])
    play__update9(g, "Chance Time")
    assert (g.state.coins, g.state.buys) == (8, 2)


def test_chance_time_hand_swap_skips_protected_and_cloaked_players(monkeypatch):
    force(monkeypatch, 2)
    g = g_with(["Chance Time"], players=3)
    set_zones(g, 0, hand=["Chance Time", "Estate"])
    set_zones(g, 1, hand=["Gold", "Gold"])
    set_zones(g, 2, hand=["Silver"])
    play__update9(g, "Chance Time")
    mine = sorted(g.state.players[0].hand)
    assert mine in (["Gold", "Gold"], ["Silver"]) and "swap hands" in log_text__update9(g)
    g = g_with(["Chance Time"], players=3)
    g.state.players[1].invisible = True
    g.state.players[2].protection = 2
    set_zones(g, 0, hand=["Chance Time", "Estate"])
    play__update9(g, "Chance Time")
    assert g.state.players[0].hand == ["Estate"] and "Nobody can be swapped with" in log_text__update9(g)


def test_chance_time_bowsers_revenge_hurts_only_the_player(monkeypatch):
    force(monkeypatch, 3)
    g = g_with(["Chance Time"], players=2)
    set_zones(g, 0, hand=["Chance Time"], deck=["Gold"] * 5, discard=[])
    before = total_cards(g)
    play__update9(g, "Chance Time")
    assert len(g.state.players[0].deck) == 3 and g.state.trash == ["Chance Time", "Gold", "Gold"]
    assert total_cards(g) == before


def test_chance_time_friends_forever_gives_everyone_a_silver_even_the_cloaked(monkeypatch):
    force(monkeypatch, 4)
    g = g_with(["Chance Time"], players=3)
    g.state.players[1].invisible = True
    set_zones(g, 0, hand=["Chance Time"], discard=[])
    for i in (1, 2):
        g.state.players[i].discard.clear()
    play__update9(g, "Chance Time")
    assert all(g.state.players[i].discard == ["Silver"] for i in range(3))


def test_chance_time_new_hands_for_everybody_but_the_cloaked(monkeypatch):
    force(monkeypatch, 5)
    g = g_with(["Chance Time"], players=3)
    g.state.players[1].invisible = True
    set_zones(g, 0, hand=["Chance Time", "Estate"], deck=["Gold"] * 10, discard=[])
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Gold"] * 10, discard=[])
    set_zones(g, 2, hand=["Copper"] * 5, deck=["Silver"] * 10, discard=[])
    before = total_cards(g)
    play__update9(g, "Chance Time")
    assert g.state.players[0].hand == ["Gold"] * 5 and g.state.players[2].hand == ["Silver"] * 5
    assert g.state.players[1].hand == ["Copper"] * 5
    assert "Estate" in g.state.players[0].discard and total_cards(g) == before


# ================================================================== everything together
def flooded_game(seed, players):
    """Cheats give everybody money every turn so they can buy the house-rule cards and play them."""
    rng = random.Random(seed)
    cats = rng.sample([c for c in fenced_cards() if get_card(c).min_players <= players], 2)
    g = new_game(GameConfig([f"P{i}" for i in range(players)], KINGDOM__update9, seed, catastrophes=cats, cheats=True))
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
            g = make_game(players=players, kingdom=KINGDOM__update9, catastrophes=[card], seed=seed)
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

# ======================================================================
# from test_catastrophes.py
# ======================================================================

KINGDOM__catastrophes = ["Moat", "Village", "Smithy", "Throne Room"]


def cg__catastrophes(players=3, cats=("Time Stop",), **kw):
    return make_game(players=players, kingdom=KINGDOM__catastrophes, catastrophes=list(cats), **kw)


def play__catastrophes(g, card, player=0):
    g.apply(player, PlayAction(card))


def answer__catastrophes(g, player, *cards):
    g.apply(player, Choose(tuple(cards)))


def end_turn__catastrophes(g):
    p = g.state.current_player
    g.apply(p, EndPhase())
    g.apply(p, EndPhase())


# ------------------------------------------------------------------- setup
def test_catastrophes_are_scarce_separate_and_never_in_a_random_kingdom():
    assert set(catastrophe_cards()) == {
        "Cataclysm", "Fate Swap", "Long Night", "Time Stop", "Grand Swap", "The Snap", "The Purge",
        "Monopoly", "Grand Theft Auto", "Roofie", "Fortnite", "Reverse", "Mind Wipe", "Perish Song",
    }
    assert not set(catastrophe_cards()) & set(kingdom_cards())
    g = cg__catastrophes(cats=("Time Stop", "Fate Swap"))
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
        cg__catastrophes(players=players, cats=cats)


def test_any_number_of_house_rule_cards_may_be_chosen():
    """No limit: three, five, or every single one (those that fit the player count)."""
    for pick in (["Time Stop", "Fate Swap", "Cataclysm"], ["Chance Time", "Grand Theft Auto", "The Snap"], fenced_cards()):
        g = cg__catastrophes(players=4, cats=tuple(pick))
        assert all(g.state.supply[c] == 2 for c in pick)
        assert g.config.catastrophes == pick
        v = build_view(g, 0)
        assert {p["name"] for p in v["piles"] if p["catastrophe"]} >= set(pick)
    g = cg__catastrophes(players=4, cats=tuple(fenced_cards()))
    g.state.supply["Village"] = 0                                    # empty house-rule piles still never end the game
    for name in fenced_cards():
        g.state.supply[name] = 0
    assert g.state.status is GameStatus.ACTIVE


def test_empty_catastrophe_piles_do_not_end_the_game():
    g = cg__catastrophes(cats=("Time Stop", "Fate Swap"), supply_overrides={"Time Stop": 0, "Fate Swap": 0, "Curse": 0, "Duchy": 0})
    end_turn__catastrophes(g)
    assert g.state.status is GameStatus.ACTIVE                    # only 2 ordinary piles are empty
    g2 = cg__catastrophes(cats=("Time Stop", "Fate Swap"),
            supply_overrides={"Time Stop": 0, "Curse": 0, "Duchy": 0, "Estate": 0})
    end_turn__catastrophes(g2)
    assert g2.state.status is GameStatus.FINISHED


# --------------------------------------------------------------- Time Stop
def test_time_stop_skips_only_the_next_player_and_trashes_itself():
    g = cg__catastrophes()
    set_zones(g, 0, hand=["Time Stop"])
    play__catastrophes(g, "Time Stop")
    s = g.state
    assert s.pending is None and s.trash == ["Time Stop"] and "Time Stop" not in s.players[0].in_play
    assert [p.skips for p in s.players] == [0, 1, 0]
    assert build_view(g, 2)["players"][1]["skip_pending"] is True
    end_turn__catastrophes(g)
    assert s.current_player == 2 and s.turn_number == 3                 # player 1's turn was skipped
    assert s.players[1].turns_taken == 1 and s.players[1].skip_protected
    assert any("turn is skipped" in line for line in s.log)
    end_turn__catastrophes(g)                                                          # player 2
    end_turn__catastrophes(g)                                                          # player 0
    assert s.current_player == 1 and not s.players[1].skip_protected and s.players[1].skips == 0


def test_two_player_time_stop_is_a_double_turn():
    g = cg__catastrophes(players=2)
    set_zones(g, 0, hand=["Time Stop"])
    play__catastrophes(g, "Time Stop")
    end_turn__catastrophes(g)
    assert g.state.current_player == 0 and [p.turns_taken for p in g.state.players] == [1, 1]


def test_nobody_is_skipped_twice_in_a_row_and_skips_do_not_stack():
    g = cg__catastrophes()
    set_zones(g, 0, hand=["Time Stop", "Time Stop"])
    g.state.actions = 2
    play__catastrophes(g, "Time Stop")
    play__catastrophes(g, "Time Stop")
    assert g.state.players[1].skips == 1                                 # the second one found nothing to do
    end_turn__catastrophes(g)
    end_turn__catastrophes(g)                                                          # player 2
    set_zones(g, 0, hand=["Time Stop"])
    play__catastrophes(g, "Time Stop")                                                 # player 1 was just skipped: protected
    assert g.state.players[1].skips == 0
    end_turn__catastrophes(g)
    assert g.state.current_player == 1                                   # they really do get a turn now


def test_moat_does_not_stop_time_stop_but_protection_does():
    g = cg__catastrophes()
    set_zones(g, 0, hand=["Time Stop"])
    set_zones(g, 1, hand=["Moat", "Copper"])
    set_zones(g, 2, hand=["Moat", "Copper"])
    play__catastrophes(g, "Time Stop")
    assert g.state.pending is None                                       # nobody is even asked about Moat
    assert g.state.players[1].skips == 1 and g.state.players[2].skips == 0

    g2 = cg__catastrophes()
    g2.state.players[1].protection = 2                                   # Guardian Angel style protection still works
    set_zones(g2, 0, hand=["Time Stop"])
    set_zones(g2, 1, hand=["Moat", "Copper"])
    play__catastrophes(g2, "Time Stop")
    assert g2.state.players[1].skips == 0 and "P1 is protected and unaffected" in "\n".join(str(x) for x in g2.state.log)


def test_moat_and_diplomat_still_work_against_ordinary_attacks():
    g = make_game(players=2, kingdom=["Militia", "Moat"])
    set_zones(g, 0, hand=["Militia"])
    set_zones(g, 1, hand=["Moat"] + ["Copper"] * 4)
    play__catastrophes(g, "Militia")
    assert g.state.pending.decision.options == ("Moat",)


# --------------------------------------------------------------- Long Night
def test_long_night_skips_the_next_two_players():
    g = cg__catastrophes(players=3, cats=("Long Night",))
    set_zones(g, 0, hand=["Long Night"])
    play__catastrophes(g, "Long Night")
    assert [p.skips for p in g.state.players] == [0, 1, 1]
    end_turn__catastrophes(g)
    assert g.state.current_player == 0 and g.state.turn_number == 4
    assert [p.turns_taken for p in g.state.players] == [1, 1, 1]

    g4 = cg__catastrophes(players=4, cats=("Long Night",))
    set_zones(g4, 0, hand=["Long Night"])
    play__catastrophes(g4, "Long Night")
    end_turn__catastrophes(g4)
    assert g4.state.current_player == 3                                  # only the next two lose a turn


# ---------------------------------------------------------------- Fate Swap
def fate_game(cats=("Fate Swap",), **kw):
    g = cg__catastrophes(cats=cats, **kw)
    set_zones(g, 0, hand=["Fate Swap"], deck=["Estate", "Duchy", "Province", "Gold", "Silver"])
    set_zones(g, 1, hand=["Copper"], deck=["Copper", "Copper", "Curse"])
    return g


def test_fate_swap_swaps_the_same_number_of_top_cards_keeping_order():
    g = fate_game()
    play__catastrophes(g, "Fate Swap")
    assert g.state.pending.decision.options == ("P1", "P2")
    answer__catastrophes(g, 0, "P1")
    s = g.state
    assert s.pending is None and s.trash == ["Fate Swap"]
    assert s.players[0].deck == ["Estate", "Duchy", "Copper", "Copper", "Curse"]
    assert s.players[1].deck == ["Province", "Gold", "Silver"]            # 3 each way: the smaller pile


def test_fate_swap_is_capped_at_seven_cards():
    g = cg__catastrophes(cats=("Fate Swap",))
    set_zones(g, 0, hand=["Fate Swap"], deck=["Estate"] * 12)
    set_zones(g, 1, hand=["Copper"], deck=["Gold"] * 12)
    play__catastrophes(g, "Fate Swap")
    answer__catastrophes(g, 0, "P1")
    assert g.state.players[0].deck == ["Estate"] * 5 + ["Gold"] * 7
    assert g.state.players[1].deck == ["Gold"] * 5 + ["Estate"] * 7


def test_fate_swap_ignores_moat_but_not_an_empty_draw_pile():
    g = fate_game()
    set_zones(g, 1, hand=["Moat"])
    play__catastrophes(g, "Fate Swap")
    answer__catastrophes(g, 0, "P1")
    assert g.state.pending is None                                        # no Moat question
    assert g.state.players[0].deck == ["Estate", "Duchy", "Copper", "Copper", "Curse"]    # the swap went ahead

    g2 = fate_game()
    set_zones(g2, 1, deck=[])
    play__catastrophes(g2, "Fate Swap")
    answer__catastrophes(g2, 0, "P1")
    assert g2.state.players[0].deck == ["Estate", "Duchy", "Province", "Gold", "Silver"]
    assert any("nothing is swapped" in line for line in g2.state.log)


def test_throne_room_cannot_make_a_catastrophe_happen_twice():
    g = fate_game()
    set_zones(g, 0, hand=["Throne Room", "Fate Swap"])
    play__catastrophes(g, "Throne Room")
    answer__catastrophes(g, 0, "Fate Swap")
    answer__catastrophes(g, 0, "P1")
    assert g.state.pending is None                                        # no second question
    assert g.state.trash == ["Fate Swap"]


# ---------------------------------------------------------------- Cataclysm
def cataclysm_game(seed=1):
    g = cg__catastrophes(cats=("Cataclysm",), seed=seed)
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
    play__catastrophes(g, "Cataclysm")
    s = g.state
    assert pooled(g) == expected                                          # nothing lost, nothing made
    assert [len(p.deck + p.hand + p.discard) for p in s.players] == sizes
    assert s.players[0].hand == [] and s.players[1].hand and len(s.players[1].hand) == 5
    assert len(s.players[2].hand) == 5 and s.players[1].discard == [] == s.players[2].discard
    assert s.trash == ["Cataclysm"] and s.players[0].in_play == []
    assert any("combined" in line for line in s.log)


def test_cataclysm_locks_buys_until_the_turn_ends():
    g = cataclysm_game()
    play__catastrophes(g, "Cataclysm")
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
        play__catastrophes(g, "Cataclysm")
    assert snapshot(a) == snapshot(b) and snapshot(a) != snapshot(c)


def test_cataclysm_is_not_an_attack_and_throne_room_cannot_double_it():
    g = cataclysm_game()
    set_zones(g, 0, hand=["Throne Room", "Cataclysm", "Gold"])
    set_zones(g, 1, hand=["Moat"] + ["Province"] * 4)
    before = total_cards(g)
    play__catastrophes(g, "Throne Room")
    answer__catastrophes(g, 0, "Cataclysm")
    assert g.state.pending is None                                        # nobody was asked about Moat
    assert g.state.trash == ["Cataclysm"] and sum("combined" in l for l in g.state.log) == 1
    assert total_cards(g) == before - 1 + 1                               # one card moved to the trash, none lost


# ----------------------------------------------------------- web lobby rules
def test_host_chooses_catastrophes_in_the_lobby():
    import asyncio
    from test_web import RoomManager, run, two_player_room

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


# ------------------------------------------------------------------- Reverse, Mind Wipe, Perish Song
def test_reverse_flips_direction_draws_and_gives_an_action():
    g = cg__catastrophes(players=4, cats=("Reverse",))
    s = g.state
    set_zones(g, 0, hand=["Reverse"], deck=["Copper", "Silver"])
    play__catastrophes(g, "Reverse")
    assert s.turn_direction == -1 and s.trash == ["Reverse"]
    assert s.actions == 1 and "Silver" in s.players[0].hand               # +1 Action (spent on Reverse), +1 Card
    assert build_view(g, 0)["turn_direction"] == -1
    assert any("REVERSE" in line for line in s.log)
    assert s.step(0) == 3 and s.step(0, -1) == 1                          # left and right swapped
    end_turn__catastrophes(g)
    assert s.current_player == 3
    end_turn__catastrophes(g)
    assert s.current_player == 2


def test_reverse_twice_restores_the_order_and_swaps_left_neighbour():
    g = cg__catastrophes(players=3, cats=("Reverse",))
    set_zones(g, 0, hand=["Reverse", "Reverse"], deck=["Copper"] * 4)
    g.state.actions = 2
    play__catastrophes(g, "Reverse")
    play__catastrophes(g, "Reverse")                                                    # the second copy is a separate card: flips back
    assert g.state.turn_direction == 1


def test_reverse_changes_who_is_left_for_card_effects():
    g = make_game(players=3, kingdom=["Masquerade", "Village", "Smithy"], catastrophes=["Reverse"])
    from dominion.engine.effects import EffectContext
    ctx = EffectContext(g.state, 0, "Village")
    assert ctx.left_player() == 1 and ctx.right_player() == 2 and ctx.other_players() == [1, 2]
    g.state.turn_direction = -1
    assert ctx.left_player() == 2 and ctx.right_player() == 1 and ctx.other_players() == [2, 1]


def test_mind_wipe_discards_four_or_the_whole_hand_and_ignores_moat():
    g = cg__catastrophes(players=3, cats=("Mind Wipe",))
    s = g.state
    set_zones(g, 0, hand=["Mind Wipe"])
    set_zones(g, 1, hand=["Moat", "Copper", "Copper", "Silver", "Estate", "Gold"])
    set_zones(g, 2, hand=["Copper", "Estate", "Silver"])
    discards = (len(s.players[1].discard), len(s.players[2].discard))
    play__catastrophes(g, "Mind Wipe")
    assert s.pending is not None and s.pending.decision.player == 1       # Moat was not even offered
    assert s.pending.decision.min_choices == s.pending.decision.max_choices == 4
    answer__catastrophes(g, 1, "Copper", "Copper", "Estate", "Gold")
    assert s.pending is None and s.trash == ["Mind Wipe"]
    assert sorted(s.players[1].hand) == ["Moat", "Silver"]
    assert s.players[2].hand == [] and len(s.players[2].discard) == discards[1] + 3     # 3 cards: all discarded, no question
    assert len(s.players[1].discard) == discards[0] + 4


def test_mind_wipe_with_exactly_four_cards_asks_nothing_and_protection_spares():
    g = cg__catastrophes(players=3, cats=("Mind Wipe",))
    s = g.state
    set_zones(g, 0, hand=["Mind Wipe"])
    set_zones(g, 1, hand=["Copper"] * 4)
    set_zones(g, 2, hand=["Copper"] * 5)
    s.players[2].protection = 2
    play__catastrophes(g, "Mind Wipe")
    assert s.pending is None and s.players[1].hand == [] and len(s.players[2].hand) == 5


def test_mind_wipe_invisibility_cloak_spares_the_wearer():
    g = cg__catastrophes(players=2, cats=("Mind Wipe",))
    set_zones(g, 0, hand=["Mind Wipe"])
    set_zones(g, 1, hand=["Copper"] * 5)
    g.state.players[1].invisible = True
    play__catastrophes(g, "Mind Wipe")
    assert len(g.state.players[1].hand) == 5


def test_perish_song_ends_the_game_after_exactly_three_rounds_of_turns():
    for players in (2, 3):
        g = cg__catastrophes(players=players, cats=("Perish Song",))
        s = g.state
        set_zones(g, 0, hand=["Perish Song"])
        play__catastrophes(g, "Perish Song")
        assert s.perish_turns_left == 3 * players and s.trash == ["Perish Song"]
        assert build_view(g, 1)["perish_turns_left"] == 3 * players
        end_turn__catastrophes(g)                                                       # the turn it was played on does not count
        assert s.perish_turns_left == 3 * players
        turns = 0
        while s.status is GameStatus.ACTIVE:
            end_turn__catastrophes(g)
            turns += 1
        assert turns == 3 * players and s.end_reason == "Perish Song" and s.perish_turns_left == 0
        assert sum(p.turns_taken for p in s.players) == 3 * players + 1
        assert s.winners


def test_perish_song_second_copy_does_nothing_and_skipped_turns_count_down():
    g = cg__catastrophes(players=3, cats=("Perish Song", "Time Stop"))
    s = g.state
    set_zones(g, 0, hand=["Perish Song", "Time Stop"])
    s.actions = 2
    play__catastrophes(g, "Perish Song")
    left = s.perish_turns_left
    play__catastrophes(g, "Time Stop")                                                  # player 1 will skip their turn
    end_turn__catastrophes(g)                                                           # the song's own turn: no tick
    assert s.perish_turns_left == left - 1                                # player 1's skipped turn counted down
    assert s.current_player == 2


def test_extra_turns_do_not_count_down_the_perish_song():
    g = cg__catastrophes(players=2, cats=("Perish Song",))
    s = g.state
    set_zones(g, 0, hand=["Perish Song"])
    play__catastrophes(g, "Perish Song")
    end_turn__catastrophes(g)
    left = s.perish_turns_left
    s.outpost_turn = True                                                 # pretend this turn is an Outpost extra turn
    end_turn__catastrophes(g)
    assert s.perish_turns_left == left                                    # an extra turn does not tick


# ------------------------------------------------------------------- Exodia grouping
def test_exodia_piles_are_contiguous_in_the_supply_with_other_specials():
    g = make_game(players=2, kingdom=KINGDOM__catastrophes, catastrophes=["Chance Time", "Exodia the Forbidden One", "Rosebud"])
    names = [p["name"] for p in build_view(g, 0)["piles"]]
    exodia = ["Exodia the Forbidden One", "Right Arm of the Forbidden One", "Left Arm of the Forbidden One",
              "Right Leg of the Forbidden One", "Left Leg of the Forbidden One"]
    start = names.index(exodia[0])
    assert names[start:start + 5] == exodia
    assert "Chance Time" in names and "Rosebud" in names


def test_exodia_pieces_sort_together_in_the_hand_view():
    g = make_game(players=2, kingdom=KINGDOM__catastrophes, catastrophes=["Exodia the Forbidden One"])
    set_zones(g, 0, hand=["Left Leg of the Forbidden One", "Gold", "Right Arm of the Forbidden One", "Estate",
                          "Exodia the Forbidden One", "Left Arm of the Forbidden One", "Right Leg of the Forbidden One", "Silver"])
    hand = build_view(g, 0)["hand"]
    i = hand.index("Exodia the Forbidden One")
    assert hand[i:i + 5] == ["Exodia the Forbidden One", "Right Arm of the Forbidden One", "Left Arm of the Forbidden One",
                             "Right Leg of the Forbidden One", "Left Leg of the Forbidden One"]
