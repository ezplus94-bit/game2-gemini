"""Rooms, seats and message handling for online play.

This module is transport-agnostic: a ``Connection`` wraps any async ``send``
callable (the FastAPI WebSocket in production, a fake in tests).

Security model
--------------
* A client never says *who* it is acting as. Identity comes from the seat bound
  to its connection (found via a secret token given out at join time).
* Every game action goes through ``Game.apply``, so the engine alone decides
  legality. The server only checks the message shape and whose seat it is.
* Clients only ever receive ``build_view`` output, so hidden information
  (other hands, deck order) is never sent.

All state lives in memory, so run exactly ONE server process.
"""

from __future__ import annotations

import asyncio
import logging
import random
import secrets
import string
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from ..ai import BigMoneyBot
from ..cards import expansions as all_expansions, kingdom_cards
from ..cards.registry import fenced_cards
from ..engine import (
    Buy, Cheat, Choose, EndGame, EndPhase, Resign, SpendCoffer, GameConfig, GameStatus, IllegalActionError, PlayAction,
    PlayAllTreasures, PlayTreasure, action_from_dict, build_view, new_game, replay,
)
from ..engine.constants import CHEAT_PHRASES, KINGDOM_SIZE, MAX_PLAYERS, MIN_PLAYERS
from ..engine.views import card_info

log = logging.getLogger("dominion.web")

MAX_NAME_LENGTH = 20
SEND_TIMEOUT = 5.0
CHAT_MAX_CHARS = 300
CHAT_HISTORY = 100
CHAT_BURST = 5            # at most this many messages ...
CHAT_WINDOW = 10.0        # ... per this many seconds, per player


class UserError(Exception):
    """A problem with what the client asked for; its text is shown to them."""


class Connection:
    """One client connection. ``send`` never raises; it returns False on failure."""

    def __init__(self, send: Callable[[dict], Awaitable[None]]) -> None:
        self._send = send
        self.room: Optional["Room"] = None
        self.seat: Optional["Seat"] = None

    async def send(self, message: dict) -> bool:
        try:
            await asyncio.wait_for(self._send(message), SEND_TIMEOUT)
            return True
        except Exception:
            return False


class Seat:
    def __init__(self, name: str, conn: Optional[Connection] = None, bot=None) -> None:
        self.name = name
        self.token = secrets.token_urlsafe(16)
        self.conn = conn
        self.bot = bot
        self.chat_times: list = []

    @property
    def is_bot(self) -> bool:
        return self.bot is not None

    @property
    def connected(self) -> bool:
        return self.is_bot or self.conn is not None


@dataclass
class UndoRequest:
    """A pending request to roll the game back to just before one of a player's actions."""
    id: int
    requester: int                 # seat index
    target: int                    # index in game.history of the action to undo
    later: int                     # how many later actions would be undone too
    description: str
    votes: dict = field(default_factory=dict)      # seat index -> None (waiting) / True / False
    task: Optional[asyncio.Task] = None


class Room:
    def __init__(self, code: str) -> None:
        self.code = code
        self.seats: list = []
        self.kingdom: Optional[list] = None     # None = random at start
        self.expansions: list = all_expansions()   # card sets a random Kingdom is drawn from
        self.catastrophes: list = []            # optional Catastrophe / Special cards (host chooses, max 2)
        self.cheats = False                     # cheat codes typed in the chat (host's choice, default off)
        self.game = None
        self.lock = asyncio.Lock()
        self.bot_task: Optional[asyncio.Task] = None
        self.chat: list = []
        self.undo: Optional[UndoRequest] = None
        self.undo_counter = 0
        self.last_active = time.time()

    def host_index(self) -> int:
        for i, seat in enumerate(self.seats):
            if not seat.is_bot:
                return i
        return -1

    def seat_by_token(self, token: str) -> Optional[Seat]:
        for seat in self.seats:
            if secrets.compare_digest(seat.token.encode(), token.encode()):
                return seat
        return None

    def humans_connected(self) -> bool:
        return any(s.conn is not None for s in self.seats if not s.is_bot)

    def touch(self) -> None:
        self.last_active = time.time()


class RoomManager:
    def __init__(
        self, bot_delay: float = 0.6, max_rooms: int = 100, idle_seconds: float = 3600,
        random_start: bool = False, undo_timeout: float = 60.0,
    ) -> None:
        self.rooms: dict = {}
        self.random_start = random_start
        self.undo_timeout = undo_timeout
        self.bot_delay = bot_delay
        self.max_rooms = max_rooms
        self.idle_seconds = idle_seconds
        self._handlers = {
            "ping": self._ping,
            "create": self._create,
            "join": self._join,
            "leave": self._leave,
            "set_kingdom": self._set_kingdom,
            "set_expansions": self._set_expansions,
            "set_catastrophes": self._set_catastrophes,
            "set_cheats": self._set_cheats,
            "list_games": self._list_games,
            "resign": self._resign,
            "end_game": self._end_game,
            "delete_room": self._delete_room_message,
            "add_bot": self._add_bot,
            "remove_seat": self._remove_seat,
            "start": self._start,
            "action": self._action,
            "rematch": self._rematch,
            "chat": self._chat,
            "undo_request": self._undo_request,
            "undo_vote": self._undo_vote,
            "undo_cancel": self._undo_cancel,
        }

    # ------------------------------------------------------------ entry points
    async def handle(self, conn: Connection, msg: dict) -> None:
        handler = self._handlers.get(msg.get("type"))
        if handler is None:
            await conn.send(_error("Unknown message type."))
            return
        try:
            await handler(conn, msg)
        except UserError as err:
            await conn.send(_error(str(err)))
        except Exception:
            log.exception("Unexpected error handling %r", msg.get("type"))
            await conn.send(_error("Something went wrong on the server."))

    async def disconnect(self, conn: Connection) -> None:
        room, seat = conn.room, conn.seat
        conn.room = conn.seat = None
        if room is None or seat is None:
            return
        async with room.lock:
            if seat.conn is conn:
                seat.conn = None
                room.touch()
                await self._broadcast(room)

    async def cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            self.sweep()

    def sweep(self, now: Optional[float] = None) -> None:
        """Delete rooms nobody has been connected to for a long time."""
        now = time.time() if now is None else now
        for room in list(self.rooms.values()):
            if not room.humans_connected() and now - room.last_active > self.idle_seconds:
                self._delete_room(room)

    # ------------------------------------------------------------ lobby messages
    async def _ping(self, conn, msg) -> None:
        await conn.send({"type": "pong"})

    async def _create(self, conn, msg) -> None:
        if conn.room is not None:
            raise UserError("You are already in a room.")
        name = _clean_name(msg)
        if len(self.rooms) >= self.max_rooms:
            raise UserError("The server is busy. Please try again later.")
        room = Room(self._new_code())
        self.rooms[room.code] = room
        async with room.lock:
            seat = Seat(name, conn)
            room.seats.append(seat)
            await self._welcome(conn, room, seat)

    async def _join(self, conn, msg) -> None:
        code = str(msg.get("room", "")).strip().upper()
        room = self.rooms.get(code)
        if room is None:
            raise UserError("Room not found.")
        token = msg.get("token")
        async with room.lock:
            existing = room.seat_by_token(token) if isinstance(token, str) else None
            if existing is not None:                       # reconnecting
                if existing.conn is not None and existing.conn is not conn:
                    existing.conn.room = existing.conn.seat = None
                if conn.room is not None and conn.seat is not existing:
                    raise UserError("You are already in a room.")
                existing.conn = conn
                await self._welcome(conn, room, existing)
                return
            if conn.room is not None:
                raise UserError("You are already in a room.")
            if room.game is not None:
                raise UserError("That game has already started.")
            if len(room.seats) >= MAX_PLAYERS:
                raise UserError("That room is full.")
            seat = Seat(_unique_name(room, _clean_name(msg)), conn)
            room.seats.append(seat)
            await self._welcome(conn, room, seat)

    async def _leave(self, conn, msg) -> None:
        room, seat = _require_seat(conn)
        async with room.lock:
            conn.room = conn.seat = None
            if room.game is None:
                room.seats.remove(seat)
            else:
                seat.conn = None
            await conn.send({"type": "left"})
            if not any(not s.is_bot for s in room.seats):
                self._delete_room(room)
                return
            await self._broadcast(room)

    async def _set_kingdom(self, conn, msg) -> None:
        room, seat = _require_host(conn)
        async with room.lock:
            _require_lobby(room)
            chosen = msg.get("kingdom")
            if chosen in (None, []):
                room.kingdom = None
            else:
                valid = set(kingdom_cards())
                if (
                    not isinstance(chosen, list)
                    or not all(isinstance(c, str) for c in chosen)
                    or len(set(chosen)) != len(chosen)
                    or not 1 <= len(chosen) <= KINGDOM_SIZE
                    or not set(chosen) <= valid
                ):
                    raise UserError(f"Choose between 1 and {KINGDOM_SIZE} different Kingdom cards.")
                room.kingdom = list(chosen)
            await self._broadcast(room)

    async def _set_expansions(self, conn, msg) -> None:
        room, seat = _require_host(conn)
        async with room.lock:
            _require_lobby(room)
            chosen = msg.get("expansions")
            known = all_expansions()
            if (
                not isinstance(chosen, list)
                or not chosen
                or not all(isinstance(c, str) for c in chosen)
                or len(set(chosen)) != len(chosen)
                or not set(chosen) <= set(known)
            ):
                raise UserError("Choose at least one card set.")
            room.expansions = [e for e in known if e in chosen]       # keep a stable order
            await self._broadcast(room)

    async def _set_catastrophes(self, conn, msg) -> None:
        room, seat = _require_host(conn)
        async with room.lock:
            _require_lobby(room)
            chosen = msg.get("catastrophes")
            if chosen in (None, []):
                room.catastrophes = []
            else:
                if (
                    not isinstance(chosen, list)
                    or not all(isinstance(c, str) for c in chosen)
                    or len(set(chosen)) != len(chosen)
                    or not set(chosen) <= set(fenced_cards())
                ):
                    raise UserError("Choose different Catastrophe or Special cards from the list.")
                room.catastrophes = list(chosen)
            await self._broadcast(room)

    async def _set_cheats(self, conn, msg) -> None:
        room, seat = _require_host(conn)
        async with room.lock:
            _require_lobby(room)
            value = msg.get("cheats")
            if not isinstance(value, bool):
                raise UserError("Cheat codes are either on or off.")
            room.cheats = value
            await self._broadcast(room)

    async def _add_bot(self, conn, msg) -> None:
        room, seat = _require_host(conn)
        async with room.lock:
            _require_lobby(room)
            if len(room.seats) >= MAX_PLAYERS:
                raise UserError("The room is full.")
            name = _unique_name(room, "Bot")
            room.seats.append(Seat(name, bot=BigMoneyBot()))
            await self._broadcast(room)

    async def _remove_seat(self, conn, msg) -> None:
        room, seat = _require_host(conn)
        async with room.lock:
            _require_lobby(room)
            index = msg.get("seat")
            if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(room.seats):
                raise UserError("No such player.")
            target = room.seats[index]
            if target is seat:
                raise UserError("Use Leave to remove yourself.")
            room.seats.pop(index)
            if target.conn is not None:
                target.conn.room = target.conn.seat = None
                await target.conn.send({"type": "left", "reason": "The host removed you from the room."})
            await self._broadcast(room)

    async def _start(self, conn, msg) -> None:
        room, seat = _require_host(conn)
        async with room.lock:
            _require_lobby(room)
            if len(room.seats) < MIN_PLAYERS:
                raise UserError(f"You need at least {MIN_PLAYERS} players. Add a bot or invite a friend.")
            absent = [s.name for s in room.seats if not s.is_bot and s.conn is None]
            if absent:
                raise UserError("Waiting for " + ", ".join(absent) + " to reconnect (or remove them).")
            try:
                room.game = new_game(GameConfig(
                    [s.name for s in room.seats], room.kingdom, None, random_start=self.random_start,
                    catastrophes=room.catastrophes, expansions=room.expansions, cheats=room.cheats,
                ))
            except ValueError as err:
                raise UserError(str(err)) from None
            room.touch()
            await self._broadcast(room)
        self._ensure_bots(room)

    async def _rematch(self, conn, msg) -> None:
        room, seat = _require_host(conn)
        async with room.lock:
            if room.game is None or room.game.state.status is not GameStatus.FINISHED:
                raise UserError("The game is not finished.")
            room.game = None
            room.touch()
            await self._broadcast(room)

    # ------------------------------------------------------------ my games, resign, end, delete
    async def _list_games(self, conn, msg) -> None:
        """Status of the games this browser knows about. A game is only revealed to the holder of a valid seat token."""
        asked = msg.get("games")
        if not isinstance(asked, list) or len(asked) > 20:
            raise UserError("Send up to 20 games to look up.")
        found, gone = [], []
        for entry in asked:
            code = str(entry.get("room", "")).strip().upper() if isinstance(entry, dict) else ""
            token = entry.get("token") if isinstance(entry, dict) else None
            room = self.rooms.get(code)
            seat = room.seat_by_token(token) if room is not None and isinstance(token, str) else None
            if room is None or seat is None:
                gone.append(code)
                continue
            index = room.seats.index(seat)
            game = room.game
            status = "lobby" if game is None else "finished" if game.state.status is GameStatus.FINISHED else "playing"
            found.append({
                "room": room.code,
                "status": status,
                "players": [s.name for s in room.seats],
                "you": index,
                "is_host": index == room.host_index(),
                "your_turn": status == "playing" and game.acting_player == index,
                "turn": game.state.turn_number if game is not None else 0,
            })
        await conn.send({"type": "games", "games": found, "gone": gone})

    async def _finish_early(self, conn, action, verb: str) -> None:
        room, seat = _require_seat(conn)
        async with room.lock:
            game = room.game
            if game is None:
                raise UserError("There is no game to " + verb + ".")
            if game.state.status is GameStatus.FINISHED:
                raise UserError("The game is already over.")
            if action is EndGame and room.seats.index(seat) != room.host_index():
                raise UserError("Only the host can do that.")
            if room.undo is not None:
                await self._end_undo(room, "The undo request was cancelled because the game ended.")
            try:
                game.apply(room.seats.index(seat), action())
            except IllegalActionError as err:
                raise UserError(str(err)) from None
            room.touch()
            await self._broadcast(room)

    async def _resign(self, conn, msg) -> None:
        await self._finish_early(conn, Resign, "resign from")

    async def _end_game(self, conn, msg) -> None:
        await self._finish_early(conn, EndGame, "end")

    async def _delete_room_message(self, conn, msg) -> None:
        """Host only: remove a game for everybody. Works from the home page (needs the room code and your seat token)."""
        code = str(msg.get("room", "")).strip().upper()
        token = msg.get("token")
        room = self.rooms.get(code)
        seat = room.seat_by_token(token) if room is not None and isinstance(token, str) else None
        if room is None or seat is None:
            raise UserError("Game not found.")
        if room.seats.index(seat) != room.host_index():
            raise UserError("Only the host can delete a game.")
        async with room.lock:
            for s in room.seats:
                if s.conn is not None:
                    s.conn.room = s.conn.seat = None
                    await s.conn.send({"type": "left", "reason": "The host deleted this game."})
                    s.conn = None
            self._delete_room(room)
        await conn.send({"type": "deleted", "room": code})

    # ------------------------------------------------------------ gameplay
    async def _action(self, conn, msg) -> None:
        room, seat = _require_seat(conn)
        try:
            action = action_from_dict(msg.get("action"))
        except ValueError as err:
            raise UserError(str(err)) from None
        async with room.lock:
            if room.game is None:
                raise UserError("The game has not started.")
            if room.undo is not None:
                raise UserError("Waiting for the undo vote to finish.")
            player = room.seats.index(seat)
            try:
                room.game.apply(player, action)       # the engine decides legality
            except IllegalActionError as err:
                raise UserError(str(err)) from None
            room.touch()
            await self._broadcast(room)
        self._ensure_bots(room)

    def _ensure_bots(self, room: Room) -> None:
        if room.bot_task is None or room.bot_task.done():
            room.bot_task = asyncio.create_task(self._bot_loop(room))

    async def _bot_loop(self, room: Room) -> None:
        try:
            while True:
                async with room.lock:
                    game = room.game
                    if game is None or game.state.status is GameStatus.FINISHED or room.undo is not None:
                        return
                    actor = game.acting_player
                    bot = room.seats[actor].bot
                    if bot is None:
                        return
                    game.apply(actor, bot.choose(game, actor))
                    room.touch()
                    await self._broadcast(room)
                await asyncio.sleep(self.bot_delay)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Bot loop crashed in room %s", room.code)

    # ------------------------------------------------------------ chat
    async def _chat(self, conn, msg) -> None:
        room, seat = _require_seat(conn)
        text = msg.get("text")
        text = " ".join(text.split())[:CHAT_MAX_CHARS] if isinstance(text, str) else ""
        if not text:
            raise UserError("Type a message first.")
        async with room.lock:
            kind = CHEAT_PHRASES.get(text.lower()) if room.cheats else None
            if kind is not None and room.game is not None and room.game.state.status is GameStatus.ACTIVE:
                await self._use_cheat(room, seat, kind)        # a cheat code is never shown as chat
                return
            now = time.time()
            seat.chat_times = [x for x in seat.chat_times if now - x < CHAT_WINDOW]
            if len(seat.chat_times) >= CHAT_BURST:
                raise UserError("You are sending messages too fast.")
            seat.chat_times.append(now)
            await self._say(room, seat.name, text)

    async def _use_cheat(self, room: Room, seat: Seat, kind: str) -> None:
        if room.undo is not None:
            raise UserError("Waiting for the undo vote to finish.")
        try:
            room.game.apply(room.seats.index(seat), Cheat(kind))      # the engine checks it is your turn
        except IllegalActionError as err:
            raise UserError(str(err)) from None
        room.touch()
        await self._broadcast(room)
        self._ensure_bots(room)

    async def _say(self, room: Room, name: str, text: str, system: bool = False) -> None:
        entry = {"name": name, "text": text, "system": system}
        room.chat.append(entry)
        del room.chat[:-CHAT_HISTORY]
        room.touch()
        for seat in room.seats:
            if seat.conn is not None:
                await seat.conn.send({"type": "chat", **entry})

    # ------------------------------------------------------------ undo (needs everyone's consent)
    async def _undo_request(self, conn, msg) -> None:
        room, seat = _require_seat(conn)
        async with room.lock:
            game = room.game
            if game is None or game.state.status is GameStatus.FINISHED:
                raise UserError("Undo is only available during a game.")
            if room.undo is not None:
                raise UserError("An undo request is already pending.")
            me = room.seats.index(seat)
            target = _undo_target(game, me)
            if target is None:
                raise UserError("Nothing to undo: you have not done anything yet.")
            voters = [i for i, s in enumerate(room.seats) if i != me and not s.is_bot]
            absent = [room.seats[i].name for i in voters if room.seats[i].conn is None]
            if absent:
                raise UserError("Can't ask for consent while " + ", ".join(absent) + " is disconnected.")
            later = len(game.history) - target - 1
            description = _describe_action(game.history[target][1])
            if not voters:                                  # nobody else to ask
                await self._apply_undo(room, me, target, description, later)
            else:
                room.undo_counter += 1
                req = UndoRequest(room.undo_counter, me, target, later, description,
                                  {i: None for i in voters})
                req.task = asyncio.create_task(self._undo_timeout(room, req.id))
                room.undo = req
                extra = f" (and {later} later action(s))" if later else ""
                await self._say(room, "", f"{seat.name} asks to undo: {description}{extra}. "
                                          "Everyone else must agree.", system=True)
                await self._broadcast(room)
        self._ensure_bots(room)

    async def _undo_vote(self, conn, msg) -> None:
        room, seat = _require_seat(conn)
        approve = msg.get("approve")
        if not isinstance(approve, bool):
            raise UserError("Vote yes or no.")
        async with room.lock:
            req = room.undo
            me = room.seats.index(seat)
            if req is None or req.votes.get(me, True) is not None:
                raise UserError("There is nothing for you to vote on.")
            req.votes[me] = approve
            if not approve:
                await self._end_undo(room, f"{seat.name} denied the undo request.")
            elif all(v is True for v in req.votes.values()):
                await self._apply_undo(room, req.requester, req.target, req.description, req.later)
            else:
                await self._broadcast(room)
        self._ensure_bots(room)

    async def _undo_cancel(self, conn, msg) -> None:
        room, seat = _require_seat(conn)
        async with room.lock:
            req = room.undo
            if req is None or room.seats.index(seat) != req.requester:
                raise UserError("You have no undo request to cancel.")
            await self._end_undo(room, f"{seat.name} cancelled the undo request.")
        self._ensure_bots(room)

    async def _undo_timeout(self, room: Room, request_id: int) -> None:
        await asyncio.sleep(self.undo_timeout)
        async with room.lock:
            if room.undo is None or room.undo.id != request_id:
                return
            room.undo.task = None
            await self._end_undo(room, "The undo request timed out.")
        self._ensure_bots(room)

    async def _end_undo(self, room: Room, notice: str) -> None:
        """Close the pending request without changing the game."""
        if room.undo is not None and room.undo.task is not None:
            room.undo.task.cancel()
        room.undo = None
        await self._say(room, "", notice, system=True)
        await self._broadcast(room)

    async def _apply_undo(self, room: Room, requester: int, target: int, description: str, later: int) -> None:
        """Roll back by replaying the history up to (not including) ``target``.
        The game is deterministic, so everyone redraws exactly the same cards."""
        game = room.game
        room.game = replay(game.config, game.history[:target])
        if room.undo is not None and room.undo.task is not None:
            room.undo.task.cancel()
        room.undo = None
        await self._say(room, "", f"Undo approved: {room.seats[requester].name}'s \"{description}\" "
                                  f"and {later} later action(s) were rolled back.", system=True)
        await self._broadcast(room)

    # ------------------------------------------------------------ helpers
    async def _welcome(self, conn: Connection, room: Room, seat: Seat) -> None:
        conn.room, conn.seat = room, seat
        room.touch()
        await conn.send({
            "type": "joined", "room": room.code, "token": seat.token,
            "seat": room.seats.index(seat),
        })
        await conn.send({"type": "chat_history", "messages": list(room.chat)})
        await self._broadcast(room)

    async def _broadcast(self, room: Room) -> None:
        for index, seat in enumerate(room.seats):
            if seat.conn is not None:
                if not await seat.conn.send(self._state_message(room, index)):
                    seat.conn = None         # dead socket; treat as disconnected

    def _state_message(self, room: Room, index: int) -> dict:
        if room.game is None:
            return {
                "type": "lobby",
                "room": room.code,
                "you": index,
                "host": room.host_index(),
                "players": [
                    {"name": s.name, "is_bot": s.is_bot, "connected": s.connected}
                    for s in room.seats
                ],
                "kingdom": room.kingdom,
                "available": [card_info(n) for n in kingdom_cards()],
                "expansions": room.expansions,
                "available_expansions": all_expansions(),
                "catastrophes": room.catastrophes,
                "available_catastrophes": [card_info(n) for n in fenced_cards()],
                "cheats": room.cheats,
                "min_players": MIN_PLAYERS,
                "max_players": MAX_PLAYERS,
                "kingdom_size": KINGDOM_SIZE,
            }
        view = build_view(room.game, index)
        for j, s in enumerate(room.seats):
            view["players"][j]["is_bot"] = s.is_bot
            view["players"][j]["connected"] = s.connected
        message = {"type": "game", "room": room.code, "host": room.host_index(), "view": view}
        if room.undo is not None:
            u = room.undo
            message["undo"] = {
                "requester": room.seats[u.requester].name,
                "description": u.description,
                "later": u.later,
                "you_requested": index == u.requester,
                "you_vote": u.votes.get(index, True) is None,
                "waiting_on": [room.seats[i].name for i, v in u.votes.items() if v is None],
            }
        return message

    def _new_code(self) -> str:
        while True:
            code = "".join(random.choices(string.ascii_uppercase, k=4))
            if code not in self.rooms:
                return code

    def _delete_room(self, room: Room) -> None:
        if room.bot_task is not None:
            room.bot_task.cancel()
        if room.undo is not None and room.undo.task is not None:
            room.undo.task.cancel()
        self.rooms.pop(room.code, None)


# ---------------------------------------------------------------- module helpers
def _error(message: str) -> dict:
    return {"type": "error", "message": message}


def _clean_name(msg: dict) -> str:
    name = msg.get("name")
    if not isinstance(name, str):
        raise UserError("Please enter a name.")
    name = " ".join(name.split())[:MAX_NAME_LENGTH]
    if not name:
        raise UserError("Please enter a name.")
    return name


def _unique_name(room: Room, name: str) -> str:
    taken = {s.name for s in room.seats}
    if name not in taken:
        return name
    n = 2
    while f"{name} {n}" in taken:
        n += 1
    return f"{name} {n}"


def _require_seat(conn: Connection):
    if conn.room is None or conn.seat is None:
        raise UserError("Join a room first.")
    return conn.room, conn.seat


def _require_host(conn: Connection):
    room, seat = _require_seat(conn)
    if room.seats.index(seat) != room.host_index():
        raise UserError("Only the host can do that.")
    return room, seat


def _require_lobby(room: Room) -> None:
    if room.game is not None:
        raise UserError("The game has already started.")


def _undo_target(game, seat_index: int) -> Optional[int]:
    """Index of the player's most recent action, from this turn or any earlier one. Undoing it also rolls back
    everything the other players did since."""
    for i in range(len(game.history) - 1, -1, -1):
        if game.history[i][0] == seat_index:
            return i
    return None


def _describe_action(action) -> str:
    if isinstance(action, (PlayAction, PlayTreasure)):
        return f"play {action.card}"
    if isinstance(action, PlayAllTreasures):
        return "play all Treasures"
    if isinstance(action, SpendCoffer):
        return "spend a Coffer"
    if isinstance(action, Buy):
        return f"buy {action.card}"
    if isinstance(action, EndPhase):
        return "end a phase"
    if isinstance(action, Choose):
        return "answer a card prompt"
    if isinstance(action, Cheat):
        return "use a cheat code"
    return "an action"
