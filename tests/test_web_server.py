"""End-to-end: a real uvicorn server and real WebSocket clients."""

import json
import time
import urllib.request

import pytest

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
