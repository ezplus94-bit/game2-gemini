"""JSON <-> Action conversion for anything that crosses a network.

``action_from_dict`` is strict: it only builds the six known Action types and
checks the shape of every field. It does NOT check legality; that is still the
engine's job (``Game.apply``).
"""

from __future__ import annotations

from typing import Any

from .actions import (
    Action, Buy, Choose, EndPhase, PlayAction, PlayAllTreasures, PlayTreasure, SpendCoffers, SpendVillagers,
)

MAX_SELECTION = 50
MAX_NAME_LENGTH = 60


def action_to_dict(action: Action) -> dict:
    if isinstance(action, PlayAction):
        return {"type": "play_action", "card": action.card}
    if isinstance(action, PlayTreasure):
        return {"type": "play_treasure", "card": action.card}
    if isinstance(action, PlayAllTreasures):
        return {"type": "play_all_treasures"}
    if isinstance(action, Buy):
        return {"type": "buy", "card": action.card}
    if isinstance(action, EndPhase):
        return {"type": "end_phase"}
    if isinstance(action, Choose):
        return {"type": "choose", "selection": list(action.selection)}
    if isinstance(action, SpendCoffers):
        return {"type": "spend_coffers", "count": action.count}
    if isinstance(action, SpendVillagers):
        return {"type": "spend_villagers", "count": action.count}
    raise ValueError(f"Cannot encode action: {action!r}")


def _card_name(data: dict) -> str:
    card = data.get("card")
    if not isinstance(card, str) or not 0 < len(card) <= MAX_NAME_LENGTH:
        raise ValueError("Action needs a 'card' name.")
    return card


def action_from_dict(data: Any) -> Action:
    if not isinstance(data, dict):
        raise ValueError("Action must be an object.")
    kind = data.get("type")
    if kind == "play_action":
        return PlayAction(_card_name(data))
    if kind == "play_treasure":
        return PlayTreasure(_card_name(data))
    if kind == "play_all_treasures":
        return PlayAllTreasures()
    if kind == "buy":
        return Buy(_card_name(data))
    if kind == "end_phase":
        return EndPhase()
    if kind == "choose":
        selection = data.get("selection")
        if not isinstance(selection, list) or len(selection) > MAX_SELECTION:
            raise ValueError("'selection' must be a short list of card names.")
        if not all(isinstance(c, str) and len(c) <= MAX_NAME_LENGTH for c in selection):
            raise ValueError("'selection' must contain card names.")
        return Choose(tuple(selection))
    if kind == "spend_coffers":
        count = data.get("count", 1)
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise ValueError("'count' must be a positive integer.")
        return SpendCoffers(count)
    if kind == "spend_villagers":
        count = data.get("count", 1)
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise ValueError("'count' must be a positive integer.")
        return SpendVillagers(count)
    raise ValueError("Unknown action type.")
