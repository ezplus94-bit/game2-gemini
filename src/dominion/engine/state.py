"""Plain data describing a game in progress. No rules live here."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from .actions import Decision


class LogLine(str):
    """A log message that remembers when and how it happened.

    It *is* a ``str`` (so ``"text" in log`` and string comparisons keep working);
    ``turn`` is the turn number, ``kind`` a colour class, ``indent`` the nesting depth.
    """

    turn: int = 0
    kind: str = "info"
    indent: int = 0

    def __new__(cls, text: str, turn: int = 0, kind: str = "info", indent: int = 0):
        obj = super().__new__(cls, text)
        obj.turn, obj.kind, obj.indent = turn, kind, indent
        return obj


def classify(text: str) -> str:
    """Best-effort colour class for a plain message (explicit kinds win over this)."""
    t = text
    if t.startswith("Game over") or t.startswith("Winner"):
        return "end"
    if " buys " in t:
        return "buy"
    if " gains " in t:
        return "gain"
    if " trashes " in t or " trash " in t:
        return "trash"
    if " plays " in t:
        return "play"
    if " discards " in t or " discard " in t:
        return "discard"
    if " draws " in t:
        return "draw"
    if "reveals" in t or "unaffected" in t:
        return "reveal"
    if "ends their turn" in t or "moves to the Buy phase" in t or "skipped" in t:
        return "phase"
    return "info"


class GameLog(list):
    """Event history. ``append`` wraps plain strings into ``LogLine`` objects."""

    def __init__(self) -> None:
        super().__init__()
        self.turn_of = lambda: 0           # set by GameState: returns the current turn number

    def append(self, text, kind=None, indent: int = 0) -> None:      # type: ignore[override]
        if isinstance(text, LogLine):
            super().append(text)
            return
        text = str(text)
        super().append(LogLine(text, self.turn_of(), kind or classify(text), indent))


class Phase(str, Enum):
    ACTION = "action"
    BUY = "buy"
    # Cleanup is automatic unless a card asks the player something (Herbalist, Alchemist), so it is not a phase.


class GameStatus(str, Enum):
    ACTIVE = "active"
    FINISHED = "finished"


@dataclass
class PlayerState:
    """One player's zones. Cards are card *names*.

    The top of the draw pile is the END of ``deck`` (``deck.pop()`` draws).
    """
    name: str
    deck: list = field(default_factory=list)       # draw pile
    hand: list = field(default_factory=list)
    discard: list = field(default_factory=list)
    in_play: list = field(default_factory=list)
    set_aside: list = field(default_factory=list)  # for future cards (Library, Sentry...)
    duration: list = field(default_factory=list)
    duration_effects: list = field(default_factory=list)
    resolved_durations: list = field(default_factory=list)
    haven_aside: list = field(default_factory=list)
    native_village_mat: list = field(default_factory=list)
    island_mat: list = field(default_factory=list)
    horse_traders_aside: list = field(default_factory=list)
    coffers: int = 0
    pirate_coins: int = 0
    tactician_active: int = 0
    last_turn_gained: list = field(default_factory=list)
    gained_this_turn: list = field(default_factory=list)
    protection: int = 0                            # Guardian Angel: Attacks skip this player while > 0 (own turns left)
    protection_fresh: bool = False                 # true during the turn protection was gained (that turn is not counted)
    protected_forever: bool = False                # God Mode: protected for the rest of the game
    bonus_coins: int = 0                           # Rosebud gift, added to the coins of this player's next turn
    invisible: bool = False                        # Invisibility Cloak: no other player's card affects this player
    blind: int = 0                                 # Roofie: turns left in which this player cannot read cards
    bought: list = field(default_factory=list)     # every card this player bought (stats)
    gained: list = field(default_factory=list)     # every card this player gained, bought or not (stats)
    vp_tokens: int = 0
    turns_taken: int = 0
    skips: int = 0                 # turns this player will skip
    skip_protected: bool = False   # just had a turn skipped: cannot be skipped again until they play one

    def all_cards(self) -> list:
        return [
            *self.deck, *self.hand, *self.discard, *self.in_play, *self.set_aside,
            *self.duration, *self.haven_aside, *self.native_village_mat, *self.island_mat,
            *self.horse_traders_aside,
        ]


@dataclass
class Trigger:
    """A delayed effect that lasts until end of turn (e.g. Merchant's Silver bonus).
    ``handler(ctx, trigger, *event_args)`` runs when ``event`` happens."""
    event: str
    source: str
    handler: Any
    owner: int
    used: bool = False


@dataclass
class PendingEffect:
    """A card effect that is paused, waiting for a player's answer."""
    decision: Decision
    generator: Any    # the suspended effect (a live generator)
    source: str       # name of the card that asked


@dataclass
class GameState:
    players: list
    supply: dict                      # card name -> cards remaining
    kingdom: tuple                    # Kingdom card names (display order)
    rng: random.Random
    trash: list = field(default_factory=list)
    current_player: int = 0
    phase: Phase = Phase.ACTION
    actions: int = 1
    buys: int = 1
    coins: int = 0
    turn_number: int = 1
    status: GameStatus = GameStatus.ACTIVE
    pending: Optional[PendingEffect] = None
    empty_pile_limit: int = 3
    catastrophes: tuple = ()          # names of the Catastrophe piles in this game
    buy_locked: bool = False          # set by Cataclysm: no buying for the rest of this turn
    cost_reduction: int = 0           # Bridge: cards cost this much less this turn
    plays_this_turn: int = 0          # Actions played this turn, Throne Room repeats included (Conspirator)
    triggers: list = field(default_factory=list)  # Trigger objects, cleared at end of turn
    cheats: bool = False              # cheat codes allowed in this game (host's choice)
    walls: dict = field(default_factory=dict)     # Fortnite: pile name -> index of the player who walled it off
    midas: bool = False               # Midas Touch: every Treasure played this turn is worth $3
    potions: int = 0                  # Alchemy: Potions available to spend this turn
    possessor: Optional[int] = None   # Possession: who controls the current (extra) turn, or None
    extra_turns: int = 0              # Possession: extra turns still to be taken after the current turn
    extra_owner: Optional[int] = None  # ... and the player who will control them
    possession_aside: list = field(default_factory=list)   # the possessed player's cards trashed this turn (they come back)
    contraband_banned: list = field(default_factory=list)
    trade_route_piles: set = field(default_factory=set)
    pending_gain_reactions: list = field(default_factory=list)
    embargo_tokens: dict = field(default_factory=dict)
    bought_this_turn: list = field(default_factory=list)
    outpost_queued: bool = False
    outpost_turn: bool = False
    prizes: list = field(default_factory=list)
    bane_card: Optional[str] = None
    resigned: list = field(default_factory=list)  # players who resigned (they cannot win)
    end_reason: Optional[str] = None  # why the game ended early (resignation / ended by host)
    winners: list = field(default_factory=list)   # player indices, set when finished
    log: GameLog = field(default_factory=GameLog)  # human-readable event history

    def __post_init__(self) -> None:
        self.log.turn_of = lambda: self.turn_number
