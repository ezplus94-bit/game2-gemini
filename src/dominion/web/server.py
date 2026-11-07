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
from fastapi.responses import HTMLResponse, JSONResponse

from .rooms import Connection, RoomManager

log = logging.getLogger("dominion.web")

MAX_MESSAGE_CHARS = 10_000
INDEX_HTML = (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")
README_PATH = Path(__file__).resolve().parents[3] / "README.md"       # repo root (absent when only the package is installed)


def parse_guide(text: str) -> list:
    """Split README markdown into a tree for the in-game guide: one entry per ``##`` section, each with its ``###``
    sub-sections as ``children``. Headings inside code fences are not headings. Plain data, safe to send as JSON."""
    sections: list = []
    current = child = None
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
        heading = None if fenced else (2 if line.startswith("## ") else 3 if line.startswith("### ") else None)
        if heading == 2:
            current = {"title": line[3:].strip(), "body": [], "children": []}
            sections.append(current)
            child = None
        elif heading == 3 and current is not None:
            child = {"title": line[4:].strip(), "body": []}
            current["children"].append(child)
        elif child is not None:
            child["body"].append(line)
        elif current is not None:
            current["body"].append(line)
    for sec in sections:
        sec["body"] = "\n".join(sec["body"]).strip()
        for kid in sec["children"]:
            kid["body"] = "\n".join(kid["body"]).strip()
    return sections


def generated_guide() -> list:
    """Fallback when README.md is not next to the package: a card table per card set, built from the card registry."""
    from ..cards import expansions, get_card, kingdom_cards

    sections = []
    for exp in expansions():
        rows = ["| Card | Cost | Effect |", "|---|---|---|"]
        for name in sorted(kingdom_cards([exp]), key=lambda n: (get_card(n).cost, n)):
            card = get_card(name)
            rows.append(f"| **{name}** | ${card.cost} | {card.text.replace('|', '/')} |")
        sections.append({"title": f"{exp} Kingdom cards", "body": "\n".join(rows), "children": []})
    return [{"title": "Cards", "body": "", "children": sections}]


_guide_cache: dict = {}


def guide_sections() -> list:
    try:
        mtime = README_PATH.stat().st_mtime
    except OSError:
        return generated_guide()
    if _guide_cache.get("mtime") != mtime:
        _guide_cache["mtime"] = mtime
        _guide_cache["sections"] = parse_guide(README_PATH.read_text(encoding="utf-8"))
    return _guide_cache["sections"]


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

    @app.get("/api/guide")
    async def guide() -> JSONResponse:
        """The README (rules, features and every card table) as sections for the in-page Game Guide."""
        return JSONResponse({"sections": guide_sections()}, headers={"Cache-Control": "no-cache"})

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
