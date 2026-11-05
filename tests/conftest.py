import socket
import threading
import time

import pytest


@pytest.fixture(scope="session")
def server():
    """A real uvicorn server (bots move instantly). Yields its port."""
    uvicorn = pytest.importorskip("uvicorn")
    from dominion.web.server import create_app

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    srv = uvicorn.Server(uvicorn.Config(create_app(bot_delay=0, random_start=False), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    assert srv.started, "server did not start"
    yield port
    srv.should_exit = True
    thread.join(5)


@pytest.fixture(autouse=True)
def _no_random_inherited(monkeypatch):
    """Plunder's Inherited Trait asks every player a question before the first turn. Tests that start random games and then press
    End phase would sometimes meet that question, so random landscape picks skip it (tests that ask for Inherited by name still get it)."""
    from dominion.engine import setup

    original = setup._resolve_events

    def resolve(requested, kingdom, seed):
        picked = original(requested, kingdom, seed)
        return picked if requested is not None else [n for n in picked if n != "Inherited"]

    monkeypatch.setattr(setup, "_resolve_events", resolve)
