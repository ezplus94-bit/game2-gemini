"""FastAPI app: serves the page and the /ws WebSocket.

Run locally:   uvicorn dominion.web.server:app --reload      (or: dominion-web)
Production:    uvicorn dominion.web.server:app --host 0.0.0.0 --port $PORT

Run exactly ONE worker: rooms live in this process's memory.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from .rooms import Connection, RoomManager

log = logging.getLogger("dominion.web")

MAX_MESSAGE_CHARS = 10_000
INDEX_HTML = (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")


def create_app(bot_delay: float = 0.6, random_start: bool = True) -> FastAPI:
    manager = RoomManager(bot_delay=bot_delay, random_start=random_start)

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = asyncio.create_task(manager.cleanup_loop())
        yield
        task.cancel()

    app = FastAPI(title="Modinion", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.manager = manager

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return INDEX_HTML

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"ok": True, "rooms": len(manager.rooms)}

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        conn = Connection(ws.send_json)
        try:
            while True:
                text = await ws.receive_text()
                if len(text) > MAX_MESSAGE_CHARS:
                    await conn.send({"type": "error", "message": "Message too large."})
                    continue
                try:
                    msg = json.loads(text)
                except ValueError:
                    await conn.send({"type": "error", "message": "Messages must be JSON."})
                    continue
                if not isinstance(msg, dict):
                    await conn.send({"type": "error", "message": "Messages must be JSON objects."})
                    continue
                await manager.handle(conn, msg)
        except WebSocketDisconnect:
            pass
        except Exception:
            log.exception("WebSocket crashed")
        finally:
            await manager.disconnect(conn)

    return app


app = create_app(bot_delay=float(os.environ.get("DOMINION_BOT_DELAY", "0.6")))


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()
