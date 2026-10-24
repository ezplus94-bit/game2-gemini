"""Chat and consent-based undo, through the room protocol."""

import asyncio

import pytest

from dominion.engine import GameConfig, new_game
from helpers import snapshot
from test_web_rooms import Client, RoomManager, run, two_player_room, wait_until


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
