"""The vocabulary of the engine: what a player can *submit*.

Actions are plain immutable data. They are requests, not facts: the engine
decides whether each one is legal (see ``rules.py``). A UI, a bot or a network
client all talk to the engine with the same objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union


@dataclass(frozen=True)
class PlayAction:
    """Play an Action card from hand (Action phase). ``from_deck``: a Shadow card (Rising Sun) played from the deck instead."""
    card: str
    from_deck: bool = False


@dataclass(frozen=True)
class PlayTreasure:
    """Play one Treasure from hand (Buy phase)."""
    card: str


@dataclass(frozen=True)
class PlayAllTreasures:
    """Convenience: play every Treasure in hand (Buy phase)."""


@dataclass(frozen=True)
class Buy:
    """Buy a card from the supply (Buy phase). ``overpay`` is the extra $ paid on a card that may be overpaid for."""
    card: str
    overpay: int = 0


@dataclass(frozen=True)
class BuyEvent:
    """Buy an Event (Adventures) with a Buy and its cost in $ (Buy phase). Events are never gained."""
    card: str


@dataclass(frozen=True)
class SpendCoffers:
    """Remove ``count`` tokens from your Coffers mat for +$1 each (any time during your turn)."""
    count: int = 1


@dataclass(frozen=True)
class SpendVillager:
    """Remove ``count`` tokens from your Villagers mat for +1 Action each (Renaissance, Action phase)."""
    count: int = 1


@dataclass(frozen=True)
class PayDebt:
    """Spend ``count`` $ to remove that many Debt tokens (Empires, Buy phase). You cannot buy while you owe Debt."""
    count: int = 1


@dataclass(frozen=True)
class EndPhase:
    """Action phase -> Buy phase, or Buy phase -> end of turn (cleanup)."""


@dataclass(frozen=True)
class Choose:
    """Answer the pending Decision with a selection of its options."""
    selection: tuple = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "selection", tuple(self.selection))


@dataclass(frozen=True)
class Resign:
    """Give up. Allowed at any time; the game ends and the resigning player cannot win.
    Never offered in ``legal_actions`` (so bots never resign)."""


@dataclass(frozen=True)
class EndGame:
    """End the game now; the current scores are final. Never offered in ``legal_actions``."""


@dataclass(frozen=True)
class Cheat:
    """Use a cheat code ('coins', 'actions' or 'buys': +100 of it). Only when the game allows
    cheats, only on your own turn. Never offered in ``legal_actions``."""
    kind: str


Action = Union[PlayAction, PlayTreasure, PlayAllTreasures, Buy, BuyEvent, SpendCoffers, SpendVillager, PayDebt, EndPhase, Choose, Resign, EndGame, Cheat]


@dataclass(frozen=True)
class Decision:
    """A question the engine asks a player in the middle of a card effect.

    The player answers with ``Choose(selection)`` where ``selection`` is a
    sub-multiset of ``options`` with between ``min_choices`` and ``max_choices``
    entries. Options may repeat (e.g. two Estates in hand). Yes/no questions
    are just options ("Yes", "No").
    """
    player: int
    prompt: str
    options: tuple
    min_choices: int = 1
    max_choices: int = 1
    source: str = ""        # card that is asking (shown to players)

    def __post_init__(self) -> None:
        object.__setattr__(self, "options", tuple(self.options))
        if not (0 <= self.min_choices <= self.max_choices <= len(self.options)):
            raise ValueError(
                f"Invalid decision bounds: min={self.min_choices}, "
                f"max={self.max_choices}, options={len(self.options)}"
            )
