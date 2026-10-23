"""Grand Swap, The Snap, The Purge, the structured log and the end-of-game stats."""

import json
import random
from collections import Counter

import pytest

from dominion.ai import BigMoneyBot, RandomBot
from dominion.cards import CardType, get_card
from dominion.engine import (
    Buy, Choose, EndPhase, GameConfig, GameStatus, PlayAction, PlayAllTreasures, build_view, new_game, replay,
)
from dominion.engine.scoring import final_stats, score_player, vp_breakdown
from dominion.engine.state import LogLine
from helpers import make_game, set_zones, to_buy_phase, total_cards
from test_bots import play_checked

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
    from test_web_rooms import RoomManager, run, two_player_room
    from dominion.cards import kingdom_cards

    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, _ = await two_player_room(m)
        lobby = host.last("lobby")
        assert lobby["expansions"] == ["Base", "Alchemy", "Cornucopia", "Intrigue", "Prosperity", "Seaside"] and lobby["available_expansions"] == ["Base", "Alchemy", "Cornucopia", "Intrigue", "Prosperity", "Seaside"]
        assert {c["expansion"] for c in lobby["available"]} == {"Base", "Alchemy", "Cornucopia", "Intrigue", "Prosperity", "Seaside"} and len(lobby["available"]) == 141
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
    from test_web_rooms import RoomManager, run, two_player_room

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
    for n in range(1, 12):
        assert f"### Update {n}:" in text


# ------------------------------------------------------------------ a bot answering Intrigue decisions on the live room code
def _human_turn_with(room, host, hand, bot_hand=None, deck=None):
    """Wait until it is Ann's turn (the bot may go first), then give her `hand`."""
    from test_web_rooms import wait_until

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
    from test_web_rooms import RoomManager, run, two_player_room, wait_until

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
