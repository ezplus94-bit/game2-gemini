"""The web layer: room logic with fake connections, a real server, chat, undo and fuzzed playtests."""

import asyncio
import json
import pytest
import time
import urllib.request
import logging
import random
from dominion.web.rooms import Connection, RoomManager
from dominion.engine import GameConfig, new_game, replay
from helpers import snapshot
from dominion.cards import kingdom_cards


# ======================================================================
# from test_web_rooms.py
# ======================================================================

TIMEOUT = 5.0


class Client:
    """A fake browser: records every message the server sends."""

    def __init__(self, manager):
        self.manager = manager
        self.inbox = []
        self.conn = Connection(self._send)

    async def _send(self, message):
        self.inbox.append(json.loads(json.dumps(message)))   # must be JSON-serializable

    async def say(self, **message):
        await self.manager.handle(self.conn, message)

    def last(self, kind):
        return next((m for m in reversed(self.inbox) if m["type"] == kind), None)

    @property
    def token(self):
        return self.last("joined")["token"]

    @property
    def view(self):
        return self.last("game")["view"]

    def last_error(self):
        return self.last("error")["message"] if self.last("error") else None


async def wait_until(predicate, timeout=TIMEOUT):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("timed out waiting for condition")
        await asyncio.sleep(0.001)


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 30))


async def two_player_room(manager, bot=False):
    host = Client(manager)
    await host.say(type="create", name="Ann")
    code = host.last("joined")["room"]
    other = None
    if bot:
        await host.say(type="add_bot")
    else:
        other = Client(manager)
        await other.say(type="join", room=code, name="Bo")
    return host, other, code


def test_create_and_join_lobby():
    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, code = await two_player_room(m)
        assert len(code) == 4 and host.last("joined")["seat"] == 0
        assert guest.last("joined")["seat"] == 1
        lobby = host.last("lobby")
        assert [p["name"] for p in lobby["players"]] == ["Ann", "Bo"]
        assert lobby["host"] == 0 and guest.last("lobby")["you"] == 1

        stranger = Client(m)
        await stranger.say(type="join", room="ZZZZ", name="X")
        assert stranger.last_error() == "Room not found."
        await stranger.say(type="create", name="")
        assert stranger.last_error() == "Please enter a name."
    run(scenario())


def test_duplicate_names_are_made_unique():
    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, code = await two_player_room(m)
        third = Client(m)
        await third.say(type="join", room=code, name="Bo")
        names = [p["name"] for p in host.last("lobby")["players"]]
        assert names == ["Ann", "Bo", "Bo 2"]
    run(scenario())


def test_only_host_can_use_host_controls():
    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, code = await two_player_room(m)
        for msg in ({"type": "add_bot"}, {"type": "start"}, {"type": "set_kingdom", "kingdom": ["Village"]},
                    {"type": "remove_seat", "seat": 0}):
            await guest.say(**msg)
            assert guest.last_error() == "Only the host can do that.", msg
    run(scenario())


def test_kingdom_selection_is_validated():
    async def scenario():
        m = RoomManager(bot_delay=0)
        host, _, _ = await two_player_room(m, bot=True)
        await host.say(type="set_kingdom", kingdom=["Village", "Smithy"])
        assert host.last("lobby")["kingdom"] == ["Village", "Smithy"]
        for bad in (["Nope"], ["Village", "Village"], "Village", ["Copper"], [1],
                    ["Cellar", "Chapel", "Village", "Workshop", "Gardens", "Remodel",
                     "Smithy", "Festival", "Laboratory", "Market", "Moneylender"]):
            await host.say(type="set_kingdom", kingdom=bad)
            assert host.last_error(), bad
        assert host.last("lobby")["kingdom"] == ["Village", "Smithy"]
        await host.say(type="set_kingdom", kingdom=[])
        assert host.last("lobby")["kingdom"] is None
    run(scenario())


def test_cannot_start_alone_or_with_absent_player():
    async def scenario():
        m = RoomManager(bot_delay=0)
        host = Client(m)
        await host.say(type="create", name="Ann")
        await host.say(type="start")
        assert "at least 2 players" in host.last_error()
        guest = Client(m)
        await guest.say(type="join", room=host.last("joined")["room"], name="Bo")
        await m.disconnect(guest.conn)
        await host.say(type="start")
        assert "Waiting for Bo" in host.last_error()
    run(scenario())


def test_game_start_gives_each_player_only_their_own_hand():
    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, code = await two_player_room(m)
        await host.say(type="start")
        a, b = host.view, guest.view
        assert a["you"] == 0 and b["you"] == 1 and len(a["hand"]) == 5 and len(b["hand"]) == 5
        assert a["players"][1]["hand_count"] == 5 and "hand" not in a["players"][1]
        assert a["players"][0]["is_bot"] is False and a["players"][1]["connected"] is True
        # start is one-way
        await host.say(type="add_bot")
        assert "already started" in host.last_error()
        late = Client(m)
        await late.say(type="join", room=code, name="Late")
        assert "already started" in late.last_error()
    run(scenario())


def test_actions_are_checked_by_the_engine_and_identity_comes_from_the_seat():
    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, _ = await two_player_room(m)
        await host.say(type="start")
        version = guest.view["version"]
        # Not guest's turn. Claiming to be player 0 in the payload changes nothing.
        await guest.say(type="action", action={"type": "end_phase", "player": 0})
        assert guest.last_error() == "It is not your turn."
        await guest.say(type="action", action={"type": "buy", "card": "Province"})
        assert guest.last_error() == "It is not your turn."
        # Malformed payloads are reported, not crashes.
        await host.say(type="action", action={"type": "nuke"})
        assert host.last_error() == "Unknown action type."
        await host.say(type="action")
        assert host.last_error() == "Action must be an object."
        # Illegal for the host too (Buy phase action in Action phase).
        await host.say(type="action", action={"type": "buy", "card": "Copper"})
        assert "Buy phase" in host.last_error()
        assert host.view["version"] == version                    # nothing changed
        # A legal action goes through and reaches both players.
        await host.say(type="action", action={"type": "end_phase"})
        assert host.view["phase"] == "buy" and guest.view["phase"] == "buy"
        assert guest.view["version"] == version + 1
    run(scenario())


def test_messages_before_joining_and_unknown_types():
    async def scenario():
        m = RoomManager(bot_delay=0)
        c = Client(m)
        await c.say(type="action", action={"type": "end_phase"})
        assert c.last_error() == "Join a room first."
        await c.say(type="start")
        assert c.last_error() == "Join a room first."
        await c.say(type="dance")
        assert c.last_error() == "Unknown message type."
    run(scenario())


def test_reconnect_with_token_restores_the_seat():
    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, code = await two_player_room(m)
        await host.say(type="start")
        token, hand = guest.token, guest.view["hand"]

        await m.disconnect(guest.conn)
        assert host.view["players"][1]["connected"] is False

        back = Client(m)
        await back.say(type="join", room=code, token=token, name="whatever")
        assert back.last("joined")["seat"] == 1
        assert back.view["you"] == 1 and back.view["hand"] == hand
        assert host.view["players"][1]["connected"] is True

        impostor = Client(m)
        for bad_token in ("wrong", "tökén-ünïcode", "", 12345, None):
            await impostor.say(type="join", room=code, token=bad_token, name="Eve")
            assert "already started" in impostor.last_error(), bad_token
    run(scenario())


def test_full_game_against_a_bot_through_the_protocol():
    async def scenario():
        m = RoomManager(bot_delay=0)
        host, _, code = await two_player_room(m, bot=True)
        await host.say(type="set_kingdom", kingdom=["Village", "Smithy", "Market"])
        await host.say(type="start")
        assert [p["is_bot"] for p in host.view["players"]] == [False, True]

        for _ in range(5000):
            await wait_until(lambda: host.view["status"] == "finished"
                             or host.view["acting_player"] == 0)
            v = host.view
            if v["status"] == "finished":
                break
            legal = [a for a in v["legal_actions"]]
            kinds = {(a["type"], a.get("card")) for a in legal}
            if v["phase"] == "action":
                action = {"type": "end_phase"}
            elif ("play_all_treasures", None) in kinds:
                action = {"type": "play_all_treasures"}
            else:
                action = {"type": "end_phase"}
                for card in ("Province", "Gold", "Silver"):
                    if ("buy", card) in kinds:
                        action = {"type": "buy", "card": card}
                        break
            await host.say(type="action", action=action)
            assert host.last_error() is None, host.last_error()
        else:
            pytest.fail("game never finished")

        v = host.view
        assert v["winners"] and len(v["final_scores"]) == 2

        await host.say(type="rematch")
        assert host.last("lobby")["players"][1]["is_bot"] is True
    run(scenario())


def test_rematch_requires_a_finished_game():
    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, _ = await two_player_room(m)
        await host.say(type="rematch")
        assert host.last_error() == "The game is not finished."
        await host.say(type="start")
        await host.say(type="rematch")
        assert host.last_error() == "The game is not finished."
    run(scenario())


def test_leave_and_remove_in_lobby_and_host_transfer():
    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, code = await two_player_room(m)
        third = Client(m)
        await third.say(type="join", room=code, name="Cy")
        await host.say(type="remove_seat", seat=2)
        assert third.last("left")["reason"] and len(host.last("lobby")["players"]) == 2
        await host.say(type="remove_seat", seat=0)
        assert "Leave" in host.last_error()
        await host.say(type="leave")
        assert host.last("left") and guest.last("lobby")["host"] == 0 and guest.last("lobby")["you"] == 0
        await guest.say(type="leave")
        assert code not in m.rooms                                  # empty room is deleted
    run(scenario())


def test_idle_rooms_are_swept_but_active_ones_are_kept():
    async def scenario():
        m = RoomManager(bot_delay=0, idle_seconds=100)
        host, guest, code = await two_player_room(m)
        m.sweep(now=m.rooms[code].last_active + 1000)
        assert code in m.rooms                                      # people still connected
        await m.disconnect(host.conn)
        await m.disconnect(guest.conn)
        m.sweep(now=m.rooms[code].last_active + 50)
        assert code in m.rooms
        m.sweep(now=m.rooms[code].last_active + 1000)
        assert code not in m.rooms
    run(scenario())


def test_room_limit():
    async def scenario():
        m = RoomManager(bot_delay=0, max_rooms=1)
        await Client(m).say(type="create", name="A")
        c = Client(m)
        await c.say(type="create", name="B")
        assert "busy" in c.last_error()
    run(scenario())


def test_production_setting_picks_a_random_first_player():
    async def scenario():
        starters = set()
        for _ in range(30):
            m = RoomManager(bot_delay=0, random_start=True)
            host, guest, _ = await two_player_room(m)
            await host.say(type="start")
            assert host.view["current_player"] == host.view["acting_player"]
            starters.add(host.view["current_player"])
            if host.view["current_player"] == 1:                    # the guest can really move first
                await guest.say(type="action", action={"type": "end_phase"})
                assert guest.last_error() is None and guest.view["phase"] == "buy"
        assert starters == {0, 1}
    run(scenario())

# ======================================================================
# from test_web_server.py
# ======================================================================

uvicorn = pytest.importorskip("uvicorn")
ws_client = pytest.importorskip("websockets.sync.client")


class Browser:
    def __init__(self, port):
        self._manager = ws_client.connect(f"ws://127.0.0.1:{port}/ws", open_timeout=5)
        self.ws = self._manager.__enter__()

    def say(self, **msg):
        self.ws.send(json.dumps(msg))

    def recv(self, kind=None, timeout=5):
        """Next message (of the given type, skipping others)."""
        end = time.time() + timeout
        while time.time() < end:
            msg = json.loads(self.ws.recv(timeout=max(0.01, end - time.time())))
            if kind is None or msg["type"] == kind:
                return msg
        raise AssertionError(f"no {kind} message")

    def close(self):
        self._manager.__exit__(None, None, None)


def get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
        return r.status, r.read().decode()


def test_page_and_health(server):
    status, body = get(server, "/")
    assert status == 200 and "<title>Modinion</title>" in body and "WebSocket" in body
    status, body = get(server, "/healthz")
    assert json.loads(body)["ok"] is True


def test_garbage_messages_do_not_kill_the_connection(server):
    b = Browser(server)
    b.ws.send("this is not json")
    assert "JSON" in b.recv("error")["message"]
    b.ws.send("[1, 2, 3]")
    assert "objects" in b.recv("error")["message"]
    b.ws.send("x" * 20000)
    assert "too large" in b.recv("error")["message"]
    b.say(type="ping")
    assert b.recv("pong")
    b.close()


def test_two_browsers_and_a_bot_play_a_turn(server):
    a, b = Browser(server), Browser(server)
    a.say(type="create", name="Ann")
    code = a.recv("joined")["room"]
    b.say(type="join", room=code, name="Bo")
    b.recv("joined")
    a.say(type="add_bot")
    a.say(type="start")
    va = a.recv("game")["view"]
    while va["version"] != 0 or va["status"] != "active":
        va = a.recv("game")["view"]
    vb = b.recv("game")
    assert len(va["players"]) == 3 and va["hand"] and "hand" not in va["players"][1]

    a.say(type="action", action={"type": "end_phase"})
    nxt = a.recv("game")["view"]
    assert nxt["phase"] == "buy"
    b.say(type="action", action={"type": "end_phase"})            # not Bo's turn
    assert b.recv("error")["message"] == "It is not your turn."
    a.close()
    b.close()


def test_reconnecting_over_a_new_socket(server):
    a = Browser(server)
    a.say(type="create", name="Ann")
    joined = a.recv("joined")
    a.say(type="add_bot")
    a.say(type="start")
    a.recv("game")
    a.close()                                  # the tab dies
    time.sleep(0.2)
    again = Browser(server)
    again.say(type="join", room=joined["room"], token=joined["token"], name="Ann")
    assert again.recv("joined")["seat"] == 0
    view = again.recv("game")["view"]
    assert view["you"] == 0 and view["status"] == "active"
    again.close()

# ======================================================================
# from test_web_chat_undo.py
# ======================================================================

async def started(m, bot=False):
    host, guest, code = await two_player_room(m, bot=bot)
    await host.say(type="start")
    return host, guest, m.rooms[code]


# ---------------------------------------------------------------------- chat
def test_chat_reaches_everyone_cleaned_up_and_capped():
    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, _ = await two_player_room(m)
        await host.say(type="chat", text="  hello    there  ")
        for c in (host, guest):
            assert c.last("chat") == {"type": "chat", "name": "Ann", "text": "hello there", "system": False}
        for bad in ("", "   ", 5, None):
            await host.say(type="chat", text=bad)
            assert host.last_error() == "Type a message first."
        await host.say(type="chat", text="x" * 1000)
        assert len(guest.last("chat")["text"]) == 300
    run(scenario())


def test_chat_history_survives_reconnect_and_game_start():
    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, code = await two_player_room(m)
        await guest.say(type="chat", text="first")
        await host.say(type="start")
        await host.say(type="chat", text="second")
        token = guest.token
        await m.disconnect(guest.conn)
        back = Client(m)
        await back.say(type="join", room=code, token=token, name="x")
        assert [x["text"] for x in back.last("chat_history")["messages"]] == ["first", "second"]
    run(scenario())


def test_chat_is_rate_limited_per_player_and_needs_a_room():
    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, _ = await two_player_room(m)
        for i in range(5):
            await host.say(type="chat", text=f"m{i}")
            assert host.last_error() is None
        await host.say(type="chat", text="too many")
        assert "too fast" in host.last_error()
        await guest.say(type="chat", text="I can still talk")
        assert guest.last_error() is None
        loner = Client(m)
        await loner.say(type="chat", text="hi")
        assert loner.last_error() == "Join a room first."
    run(scenario())


# ---------------------------------------------------------------------- undo
def test_undo_with_consent_restores_the_exact_earlier_state():
    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, room = await started(m)
        before = snapshot(room.game)
        await host.say(type="action", action={"type": "end_phase"})
        await host.say(type="undo_request")
        assert host.last("game")["undo"]["you_requested"] and guest.last("game")["undo"]["you_vote"]
        assert guest.last("game")["undo"]["description"] == "end a phase"
        await host.say(type="action", action={"type": "end_phase"})
        assert "undo vote" in host.last_error()                         # play is paused meanwhile
        await guest.say(type="undo_vote", approve=True)
        assert snapshot(room.game) == before and host.view["version"] == 0
        assert "undo" not in host.last("game") and room.undo is None
        assert any("Undo approved" in x["text"] for x in host.inbox if x["type"] == "chat")
        await host.say(type="action", action={"type": "end_phase"})      # and play simply continues
        assert host.view["version"] == 1 and host.view["phase"] == "buy"
    run(scenario())


def test_denied_cancelled_and_timed_out_requests_change_nothing():
    async def scenario():
        m = RoomManager(bot_delay=0, undo_timeout=0.05)
        host, guest, room = await started(m)
        await host.say(type="action", action={"type": "end_phase"})
        after = snapshot(room.game)

        await host.say(type="undo_request")
        await guest.say(type="undo_vote", approve=False)
        assert snapshot(room.game) == after and room.undo is None
        assert any("denied" in x["text"] for x in host.inbox if x["type"] == "chat")

        m.undo_timeout = 30
        await host.say(type="undo_request")
        await guest.say(type="undo_cancel")
        assert "no undo request" in guest.last_error()                    # only the requester may cancel
        await host.say(type="undo_cancel")
        assert room.undo is None and snapshot(room.game) == after

        m.undo_timeout = 0.05
        await host.say(type="undo_request")
        await wait_until(lambda: room.undo is None)
        assert any("timed out" in x["text"] for x in host.inbox if x["type"] == "chat")
        assert snapshot(room.game) == after
    run(scenario())


def test_undo_reaches_back_across_turns_to_your_own_last_action():
    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, room = await started(m)
        await guest.say(type="undo_request")                            # nobody has done anything yet
        assert "Nothing to undo" in guest.last_error()
        await host.say(type="undo_request")
        assert "Nothing to undo" in host.last_error()
        await host.say(type="action", action={"type": "end_phase"})
        before_last = snapshot(room.game)                               # just before the host's last action
        await host.say(type="action", action={"type": "end_phase"})     # the host's turn is over ...
        await guest.say(type="undo_request")                            # the guest still has nothing to undo
        assert "Nothing to undo" in guest.last_error()
        await guest.say(type="action", action={"type": "end_phase"})    # ... and the guest is part-way through theirs
        assert room.game.state.current_player == 1
        await host.say(type="undo_request")                             # the host asks DURING the guest's turn
        assert room.undo is not None and room.undo.requester == 0 and room.undo.later == 1
        assert any("1 later action" in x["text"] for x in guest.inbox if x["type"] == "chat")
        await guest.say(type="undo_vote", approve=True)
        assert room.undo is None
        assert snapshot(room.game) == before_last                       # everything since the host's last action is gone
        assert room.game.state.current_player == 0 and len(room.game.history) == 1
    run(scenario())


def test_three_players_can_undo_from_the_middle_of_a_later_turn():
    """P1 plays, P2 plays, P3 is part-way through: P1 may still take back their last action, if P2 and P3 agree."""
    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, code = await two_player_room(m)
        third = Client(m)
        await third.say(type="join", room=code, name="Cy")
        await host.say(type="start")
        room = m.rooms[code]
        end = {"type": "action", "action": {"type": "end_phase"}}
        await host.say(**end)
        mark = snapshot(room.game)                                       # just before P1's last action
        await host.say(**end)                                            # P1's turn is over
        await guest.say(**end); await guest.say(**end)                   # P2's whole turn
        await third.say(**end)                                           # P3 is in their Buy phase
        assert room.game.state.current_player == 2
        await host.say(type="undo_request")                              # P1 asks during P3's turn
        assert room.undo is not None and room.undo.later == 3
        assert third.last("game")["undo"]["you_vote"] and guest.last("game")["undo"]["you_vote"]
        await guest.say(type="undo_vote", approve=True)
        assert room.undo is not None                                     # P3 has not agreed yet
        await third.say(type="undo_vote", approve=False)                 # P3 refuses: nothing changes
        assert room.undo is None and room.game.state.current_player == 2
        await host.say(type="undo_request")
        await guest.say(type="undo_vote", approve=True)
        await third.say(type="undo_vote", approve=True)
        assert room.undo is None and snapshot(room.game) == mark
        assert room.game.state.current_player == 0 and len(room.game.history) == 1
        # the next player to ask can reach back too: P2 has done nothing in this timeline
        await guest.say(type="undo_request")
        assert "Nothing to undo" in guest.last_error()
    run(scenario())


def test_undo_unavailable_after_game_over_and_vote_rules():
    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, room = await started(m)
        await guest.say(type="undo_vote", approve=True)
        assert "nothing for you to vote on" in guest.last_error()
        await host.say(type="action", action={"type": "end_phase"})
        await host.say(type="undo_request")
        await host.say(type="undo_vote", approve=True)                   # requester cannot vote
        assert "nothing for you to vote on" in host.last_error()
        await guest.say(type="undo_vote", approve="yes")
        assert guest.last_error() == "Vote yes or no."
        await host.say(type="undo_cancel")

        room.game = new_game(GameConfig(["Ann", "Bo"], None, 1, supply_overrides={"Province": 0}))
        await host.say(type="action", action={"type": "end_phase"})
        await host.say(type="action", action={"type": "end_phase"})      # game over
        await host.say(type="undo_request")
        assert "only available during a game" in host.last_error()
    run(scenario())


def test_cannot_ask_while_a_voter_is_disconnected_and_solo_undo_needs_no_vote():
    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, room = await started(m)
        await host.say(type="action", action={"type": "end_phase"})
        await m.disconnect(guest.conn)
        await host.say(type="undo_request")
        assert "disconnected" in host.last_error() and room.undo is None

        m2 = RoomManager(bot_delay=0)
        solo, _, room2 = await started(m2, bot=True)
        before = snapshot(room2.game)
        await solo.say(type="action", action={"type": "end_phase"})
        await solo.say(type="undo_request")                              # only a bot to ask: no vote
        assert room2.undo is None and snapshot(room2.game) == before
    run(scenario())


def test_three_humans_must_all_agree():
    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, code = await two_player_room(m)
        third = Client(m)
        await third.say(type="join", room=code, name="Cy")
        await host.say(type="start")
        room = m.rooms[code]
        before = snapshot(room.game)
        await host.say(type="action", action={"type": "end_phase"})
        await host.say(type="undo_request")
        await guest.say(type="undo_vote", approve=True)
        assert room.undo is not None and third.last("game")["undo"]["you_vote"]
        assert guest.last("game")["undo"]["waiting_on"] == ["Cy"]
        await third.say(type="undo_vote", approve=True)
        assert room.undo is None and snapshot(room.game) == before
    run(scenario())

# ======================================================================
# from test_web_fuzz.py
# ======================================================================

JUNK = [
    {"type": "action", "action": {"type": "buy", "card": "Province"}},
    {"type": "action", "action": {"type": "choose", "selection": ["Gold"] * 3}},
    {"type": "action", "action": 5},
    {"type": "start"}, {"type": "rematch"}, {"type": "add_bot"}, {"type": "leave_not_real"},
    {"type": "set_kingdom", "kingdom": ["Nope"]}, {"type": "remove_seat", "seat": 99},
    {"type": "join", "room": "ZZZZ", "name": "x"}, {"type": "create", "name": "again"},
]


def random_answer(rng, view):
    """A legal-looking action for the acting player, or None."""
    pending = view["pending"]
    if pending and "options" in pending:
        n = rng.randint(pending["min"], pending["max"])
        picked = rng.sample(range(len(pending["options"])), n)
        return {"type": "choose", "selection": [pending["options"][i] for i in picked]}
    if view["legal_actions"]:
        return rng.choice(view["legal_actions"])
    return None


async def play_one(seed, manager_cls):
    rng = random.Random(seed)
    m = manager_cls(bot_delay=0, random_start=bool(seed % 2))
    humans = rng.choice([1, 2, 3])
    bots = rng.choice([1, 2]) if humans == 1 else rng.choice([0, 1])
    host = Client(m)
    await host.say(type="create", name="H0")
    code = host.last("joined")["room"]
    clients = [host]
    for i in range(1, humans):
        c = Client(m)
        await c.say(type="join", room=code, name=f"H{i}")
        clients.append(c)
    for _ in range(min(bots, 4 - humans)):
        await host.say(type="add_bot")
    await host.say(type="set_kingdom", kingdom=rng.sample(kingdom_cards(), 10))
    await host.say(type="start")
    assert host.last("game"), host.last_error()
    room = m.rooms[code]
    tokens = [c.token for c in clients]

    for step in range(30000):
        game = room.game
        if game.state.status.value == "finished":
            break
        await wait_until(lambda: room.game.state.status.value == "finished"
                         or not room.seats[room.game.acting_player].is_bot)
        if room.game.state.status.value == "finished":
            break
        r = rng.random()
        i = rng.randrange(len(clients))
        if r < 0.04:                                       # connection drops and comes back
            await m.disconnect(clients[i].conn)
            fresh = Client(m)
            await fresh.say(type="join", room=code, token=tokens[i], name="ignored")
            assert fresh.last("joined"), fresh.last_error()
            clients[i] = fresh
        elif r < 0.09:                                     # someone asks to undo; the others vote at random
            await clients[i].say(type="undo_request")
            if room.undo is not None:
                for voter in list(room.undo.votes):
                    if room.undo is not None:
                        await clients[voter].say(type="undo_vote", approve=rng.random() < 0.7)
        elif r < 0.12:                                     # junk
            await rng.choice(clients).say(**rng.choice(JUNK))
        else:                                              # the acting human plays
            actor = room.game.acting_player
            if actor >= len(clients):
                continue
            c = clients[actor]
            action = random_answer(rng, c.view)
            if action is not None:
                await c.say(type="action", action=action)
    else:
        pytest.fail(f"seed {seed}: game did not finish")

    # consistency checks on the final state of every client
    state = room.game.state
    for idx, c in enumerate(clients):
        v = c.view
        assert v["you"] == idx and v["hand"] == sorted(state.players[idx].hand)
        assert all("hand" not in p and "deck" not in p for p in v["players"])
    assert state.winners
    assert snapshot(replay(room.game.config, room.game.history)) == snapshot(room.game)
    return room


@pytest.mark.parametrize("seed", range(12))
def test_simulated_playtest(seed, caplog):
    from dominion.web.rooms import RoomManager
    caplog.set_level(logging.ERROR)
    asyncio.run(asyncio.wait_for(play_one(seed, RoomManager), 120))
    assert not caplog.records, [r.getMessage() for r in caplog.records]
