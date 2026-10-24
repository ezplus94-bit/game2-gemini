"""Simulated playtest: random 'humans' play full games through the room protocol,
dropping connections, reconnecting and sending junk, while the server must stay
consistent, never leak hidden cards and never log an unexpected error."""

import asyncio
import logging
import random

import pytest

from dominion.cards import kingdom_cards
from dominion.engine import replay
from helpers import snapshot
from test_web_rooms import Client, wait_until

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
