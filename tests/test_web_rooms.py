"""Room manager tests using fake connections (no network)."""

import asyncio
import json

import pytest

from dominion.web.rooms import Connection, RoomManager

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
