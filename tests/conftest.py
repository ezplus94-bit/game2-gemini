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
