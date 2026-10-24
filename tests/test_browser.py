"""Optional: runs the real page in jsdom (Node) against a live server.

Skipped unless Node and jsdom are installed:
    cd tests/browser && npm install
"""

import shutil
import subprocess
from pathlib import Path

import pytest

BROWSER_DIR = Path(__file__).parent / "browser"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (BROWSER_DIR / "node_modules" / "jsdom").exists(),
    reason="needs Node.js and `npm install` in tests/browser",
)


@pytest.mark.parametrize("script", ["e2e.js", "reconnect.js", "lifecycle.js"])
def test_browser_scripts(server, script):
    result = subprocess.run(
        ["node", script, str(server)], cwd=BROWSER_DIR, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"ok":true' in result.stdout


def _game_message(game, player=0, room="ABCD"):
    from dominion.engine import build_view

    view = build_view(game, player)
    for i, pl in enumerate(view["players"]):
        pl["is_bot"] = False
        pl["connected"] = True
    return {"type": "game", "room": room, "host": 0, "view": view}


def test_page_renders_real_engine_views(tmp_path):
    """The page against views built by the real engine: text choices, Bridge prices, catastrophes, stats."""
    import json
    import random

    from dominion.ai import BigMoneyBot
    from dominion.engine import Buy, Choose, GameConfig, GameStatus, PlayAction, PlayAllTreasures, new_game
    from helpers import make_game, set_zones

    fx = {}
    # a Pawn waiting for two text choices
    g = make_game(players=2, kingdom=["Pawn", "Moat", "Market", "Nobles"], seed=1)
    set_zones(g, 0, hand=["Pawn", "Copper"], deck=["Silver", "Gold"])
    g.apply(0, PlayAction("Pawn"))
    fx["pawn"] = _game_message(g)
    # an optional Moat reveal
    g = make_game(players=2, kingdom=["Militia", "Moat", "Market", "Nobles"], seed=1)
    set_zones(g, 0, hand=["Militia"])
    set_zones(g, 1, hand=["Moat", "Copper", "Copper", "Copper", "Copper"])
    g.apply(0, PlayAction("Militia"))
    fx["moat"] = _game_message(g, player=1)
    # Bridge in play: everything costs $1 less
    g = make_game(players=2, kingdom=["Bridge", "Moat", "Market", "Nobles"], seed=1)
    set_zones(g, 0, hand=["Bridge", "Copper", "Copper", "Copper", "Copper"])
    g.apply(0, PlayAction("Bridge"))
    fx["bridge"] = _game_message(g)
    # Grand Swap just played
    g = make_game(players=2, kingdom=["Moat", "Village", "Smithy", "Nobles"], catastrophes=["Grand Swap"], seed=2)
    set_zones(g, 0, hand=["Grand Swap"], deck=["Gold", "Gold"], discard=["Estate"])
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Copper", "Silver"], discard=[])
    g.apply(0, PlayAction("Grand Swap"))
    g.apply(0, Choose(("P1",)))
    fx["swap"] = _game_message(g)
    # The Snap just played
    g = make_game(players=2, kingdom=["Moat", "Village", "Smithy", "Nobles"], catastrophes=["The Snap"], seed=2)
    set_zones(g, 0, hand=["The Snap", "Copper"], deck=["Gold", "Silver", "Estate", "Copper"])
    fx["snap_before"] = _game_message(g)
    g.apply(0, PlayAction("The Snap"))
    fx["snap"] = _game_message(g)
    # ... and a later view with more log lines (muted check)
    from dominion.engine import EndPhase
    g.apply(0, EndPhase())
    g.apply(0, EndPhase())
    fx["snap2"] = _game_message(g)
    # my turn in the Buy phase with Treasures in hand (and the Action phase with an Action to play)
    from helpers import to_buy_phase
    g = make_game(players=2, kingdom=["Moat", "Market", "Smithy", "Nobles"], seed=1)
    set_zones(g, 0, hand=["Smithy", "Copper", "Copper", "Silver", "Estate"])
    fx["action_phase"] = _game_message(g)
    to_buy_phase(g)
    fx["buy"] = _game_message(g)
    # out of Buys in the Buy phase (the turn should end by itself)
    g = make_game(players=2, kingdom=["Moat", "Market", "Smithy", "Nobles"], seed=1)
    set_zones(g, 0, hand=["Copper"] * 5)
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    fx["buy_before"] = _game_message(g)
    g.apply(0, Buy("Silver"))
    fx["buys_out"] = _game_message(g)
    # protection and a Rosebud gift on the player panels, special cards in the supply
    g = make_game(players=2, kingdom=["Moat", "Market", "Smithy", "Nobles"], catastrophes=["Rosebud", "God Mode"], seed=1)
    g.state.players[0].protection = 3
    g.state.players[1].protected_forever = True
    g.state.players[1].bonus_coins = 12
    fx["protected"] = _game_message(g)
    # Rosebud played: a gold banner, no red shake
    g = make_game(players=2, kingdom=["Moat", "Market", "Smithy", "Nobles"], catastrophes=["Rosebud"], seed=1)
    set_zones(g, 0, hand=["Rosebud", "Copper"])
    fx["rose_before"] = _game_message(g)
    g.apply(0, PlayAction("Rosebud"))
    g.apply(0, Choose(("P1",)))
    fx["rose_after"] = _game_message(g)
    # cheat code used
    g = new_game(GameConfig(["P0", "P1"], ["Moat", "Market", "Smithy", "Nobles"], 1, cheats=True))
    fx["cheat_before"] = _game_message(g)
    from dominion.engine import Cheat
    g.apply(0, Cheat("coins"))
    fx["cheat_after"] = _game_message(g)
    # a resignation
    g = make_game(players=2, kingdom=["Moat", "Market", "Smithy", "Nobles"], seed=1)
    from dominion.engine import Resign
    g.apply(1, Resign())
    fx["resigned"] = _game_message(g)
    # lobby views as the server sends them
    import asyncio
    from test_web_rooms import Client, RoomManager

    async def lobbies():
        m = RoomManager(bot_delay=0)
        host = Client(m); await host.say(type="create", name="Ann")
        guest = Client(m); await guest.say(type="join", room=host.last("joined")["room"], name="Bo")
        out = {"off_host": host.last("lobby"), "off_guest": guest.last("lobby")}
        await host.say(type="set_cheats", cheats=True)
        out["on_host"], out["on_guest"] = host.last("lobby"), guest.last("lobby")
        return out
    fx["lobby"] = asyncio.run(lobbies())
    # Fortnite walls, Roofie blindness, Invisibility Cloak, Midas Touch, Exodia
    KING = ["Moat", "Village", "Smithy", "Militia"]
    g = make_game(players=3, kingdom=KING, catastrophes=["Fortnite", "Roofie"], seed=5)
    set_zones(g, 0, hand=["Fortnite"])
    g.apply(0, PlayAction("Fortnite")); g.apply(0, Choose(("Gold", "Province")))
    fx["walls_p1"] = _game_message(g, player=1)
    fx["walls_p0"] = _game_message(g, player=0)
    g = make_game(players=3, kingdom=KING, catastrophes=["Roofie", "Invisibility Cloak"], seed=5)
    g.state.players[2].invisible = True
    set_zones(g, 0, hand=["Roofie"])
    set_zones(g, 1, hand=["Smithy", "Smithy", "Copper", "Estate", "Estate"], deck=["Gold"] * 6)
    fx["roofie_before_p1"] = _game_message(g, player=1)
    g.apply(0, PlayAction("Roofie"))
    fx["roofie_p1"] = _game_message(g, player=1)               # P1 is blinded
    fx["roofie_p0"] = _game_message(g, player=0)               # the attacker still sees everything
    g = make_game(players=2, kingdom=KING, catastrophes=["Midas Touch"], seed=5)
    set_zones(g, 0, hand=["Midas Touch", "Copper", "Copper"])
    g.apply(0, PlayAction("Midas Touch"))
    fx["midas"] = _game_message(g)
    EX = ["Exodia the Forbidden One", "Right Arm of the Forbidden One", "Left Arm of the Forbidden One",
          "Right Leg of the Forbidden One", "Left Leg of the Forbidden One"]
    g = make_game(players=2, kingdom=KING, catastrophes=[EX[0]], seed=5)
    set_zones(g, 0, hand=["Village"] + EX[1:], deck=["Copper", EX[0]])
    fx["exodia_before"] = _game_message(g)
    g.apply(0, PlayAction("Village"))
    fx["exodia_won"] = _game_message(g)
    g = make_game(players=2, kingdom=KING, catastrophes=[EX[0]], seed=5)
    fx["exodia_piles"] = _game_message(g)
    # a finished game
    g = make_game(players=3, kingdom=["Moat", "Village", "Smithy", "Gardens", "Duke"], seed=4)
    bots = [BigMoneyBot() for _ in range(3)]
    while g.state.status is not GameStatus.FINISHED:
        p = g.acting_player
        g.apply(p, bots[p].choose(g, p))
    fx["finished"] = _game_message(g)

    path = tmp_path / "fixtures.json"
    path.write_text(json.dumps(fx))
    result = subprocess.run(
        ["node", "render.js", str(path)], cwd=BROWSER_DIR, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"ok":true' in result.stdout


def _layout_fixtures():
    """Worst-case screens built by the real engine: 4 players, 10 Kingdom cards plus 8 house-rule piles
    (Exodia brings five), a 9-card hand, 200 log lines, pending questions, a finished 4-player game, a full lobby."""
    import asyncio

    from dominion.ai import BigMoneyBot
    from dominion.engine import GameStatus, PlayAction
    from helpers import make_game, set_zones
    from test_web_rooms import Client, RoomManager

    king = ["Village", "Smithy", "Moat", "Militia", "Lurker", "Pawn", "Nobles", "Replace", "Torturer", "Throne Room"]
    cats = ["Exodia the Forbidden One", "Fortnite", "Chance Time", "The Snap"]
    bots = [BigMoneyBot() for _ in range(4)]

    def run_out(g, plies):
        for _ in range(plies):
            a = g.acting_player
            g.apply(a, bots[a].choose(g, a))
            if g.state.status is GameStatus.FINISHED:
                break

    fx = {}
    g = make_game(players=4, kingdom=king, catastrophes=cats, seed=11)
    run_out(g, 160)
    g.state.walls["Gold"] = 1
    g.state.players[2].protection = 3
    g.state.players[1].invisible = True
    cur = g.state.current_player
    set_zones(g, cur, hand=["Copper", "Copper", "Silver", "Gold", "Estate", "Smithy", "Village", "Moat", "Nobles"],
              in_play=["Village", "Smithy", "Silver", "Copper", "Gold"])
    fx["mid"] = _game_message(g, player=cur)
    d = make_game(players=3, kingdom=king, catastrophes=cats, seed=5)
    set_zones(d, 0, hand=["Throne Room", "Smithy", "Village", "Moat", "Nobles", "Lurker", "Copper", "Estate"], deck=["Copper"] * 8)
    d.apply(0, PlayAction("Throne Room"))
    fx["decision"] = _game_message(d)
    d2 = make_game(players=3, kingdom=king, catastrophes=cats, seed=5)
    set_zones(d2, 0, hand=["Lurker"])
    d2.state.trash.extend(["Smithy", "Village"])
    d2.apply(0, PlayAction("Lurker"))
    fx["decision_lurker"] = _game_message(d2)
    f = make_game(players=4, kingdom=king, catastrophes=cats, seed=4)
    run_out(f, 4000)
    fx["finished"] = _game_message(f)
    big = make_game(players=4, kingdom=king, catastrophes=cats, seed=12)
    run_out(big, 120)
    cur = big.state.current_player
    set_zones(big, cur, hand=["Copper"] * 6 + ["Silver"] * 4 + ["Gold"] * 3 + ["Estate", "Duchy", "Village", "Smithy", "Moat", "Nobles", "Militia", "Lurker", "Pawn",
              "Throne Room", "Torturer"], in_play=["Village", "Smithy", "Moat", "Pawn", "Copper", "Copper", "Silver", "Gold", "Nobles", "Militia", "Lurker", "Replace"])
    fx["big_hand"] = _game_message(big, player=cur)

    async def lobby():
        m = RoomManager(bot_delay=0)
        h = Client(m); await h.say(type="create", name="Ann")
        c = Client(m); await c.say(type="join", room=h.last("joined")["room"], name="Bo")
        await h.say(type="add_bot")
        await h.say(type="set_catastrophes", catastrophes=["Chance Time", "Grand Theft Auto", "The Snap"])
        return {"lobby": h.last("lobby"), "joined": h.last("joined")}
    fx.update(asyncio.run(lobby()))
    return fx


def test_the_page_itself_never_scrolls_in_a_real_browser(tmp_path):
    """Optional (needs `cd tests/browser/layout && npm install`, which downloads a headless Chromium).
    Renders the real page at four screen sizes: no vertical or horizontal page scroll, nothing but the log (and the
    pop-up of results / the card pickers) scrolls inside itself, the turn bar and chat stay on screen, pop-ups are centred."""
    import json
    layout_dir = BROWSER_DIR / "layout"
    if not (layout_dir / "node_modules").is_dir() or not shutil.which("node"):
        pytest.skip("layout tests need node and `npm install` in tests/browser/layout")
    path = tmp_path / "fixtures.json"
    path.write_text(json.dumps(_layout_fixtures()))
    result = subprocess.run(["node", "layout.mjs", str(path)], cwd=layout_dir, capture_output=True, text=True, timeout=240)
    assert result.returncode == 0, result.stdout + result.stderr
    rows = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    assert len(rows) == 28
    for r in rows:
        where = f"{r['size']} {r['screen']}"
        assert r["pageScrollY"] <= 0 and r["bodyScrollY"] <= 0, f"{where}: the page scrolls vertically ({r['pageScrollY']}px)"
        assert r["pageScrollX"] <= 0, f"{where}: the page scrolls sideways"
        allowed = {"log", "gameover", "picker-panel"} | ({"supply-panel", "inplay-panel", "hand-panel"} if r["screen"] == "bighand" else set())
        if r["screen"] in ("mid", "decision", "lurker") and r["vw"] >= 1366 and r["vh"] >= 768:
            assert set(r["innerScrolls"]) <= {"log"}, f"{where}: a panel scrolls inside itself: {r['innerScrolls']}"
        assert set(r["innerScrolls"]) <= allowed | ({"supply-panel"} if r["vh"] < 768 else set()), f"{where}: {r['innerScrolls']}"
        if r["screen"] in ("mid", "decision", "lurker", "finished"):
            assert r["topbar"] and r["topbar"]["b"] <= r["vh"] and r["topbar"]["l"] > r["vw"] * 0.6, f"{where}: the turn bar must sit at the bottom right"
            assert r["chat"] and r["chat"]["b"] <= r["topbar"]["t"] + 1, f"{where}: the chat must sit above the turn bar"
            assert r["players"] and r["players"]["r"] < r["vw"] * 0.25, f"{where}: players must be on the left"
            assert r["hand"] and r["hand"]["b"] <= r["vh"], f"{where}: the hand must be fully on screen"
        assert all(v != "visible" for v in r["overflowY"].values()), f"{where}: a panel lets its content spill out instead of scrolling: {r['overflowY']}"
        if r["screen"] == "bighand":
            assert r["supply"] and r["supply"]["b"] - r["supply"]["t"] >= 0.28 * r["vh"], f"{where}: a huge hand squeezes the Supply away"
            assert r["bottom"]["b"] - r["bottom"]["t"] <= 0.47 * r["vh"], f"{where}: the hand and in-play row grew too tall"
        for pop in ("decision", "gameover"):
            if r.get(pop):
                box = r[pop]
                assert box["l"] >= 0 and box["t"] >= 0 and box["r"] <= r["vw"] and box["b"] <= r["vh"], f"{where}: {pop} pop-up leaves the screen"
                assert abs((box["l"] + box["r"]) / 2 - r["vw"] / 2) <= 4, f"{where}: {pop} pop-up is not centred"
