"""JSON <-> Action conversion for anything that crosses a network.

``action_from_dict`` is strict: it only builds the six known Action types and
checks the shape of every field. It does NOT check legality; that is still the
engine's job (``Game.apply``).
"""

from __future__ import annotations

from typing import Any

from .actions import Action, Buy, BuyEvent, Choose, EndPhase, PayDebt, PlayAction, PlayAllTreasures, PlayTreasure, SpendCoffers, SpendVillager

MAX_SELECTION = 50
MAX_NAME_LENGTH = 60
MAX_OVERPAY = 1000


def action_to_dict(action: Action) -> dict:
    if isinstance(action, PlayAction):
        return {"type": "play_action", "card": action.card, **({"from_deck": True} if action.from_deck else {})}
    if isinstance(action, PlayTreasure):
        return {"type": "play_treasure", "card": action.card}
    if isinstance(action, PlayAllTreasures):
        return {"type": "play_all_treasures"}
    if isinstance(action, Buy):
        out = {"type": "buy", "card": action.card}
        if action.overpay:
            out["overpay"] = action.overpay
        return out
    if isinstance(action, BuyEvent):
        return {"type": "buy_event", "card": action.card}
    if isinstance(action, SpendCoffers):
        return {"type": "spend_coffers", "count": action.count}
    if isinstance(action, SpendVillager):
        return {"type": "spend_villager", "count": action.count}
    if isinstance(action, PayDebt):
        return {"type": "pay_debt", "count": action.count}
    if isinstance(action, EndPhase):
        return {"type": "end_phase"}
    if isinstance(action, Choose):
        return {"type": "choose", "selection": list(action.selection)}
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
        return PlayAction(_card_name(data), bool(data.get("from_deck", False)))
    if kind == "play_treasure":
        return PlayTreasure(_card_name(data))
    if kind == "play_all_treasures":
        return PlayAllTreasures()
    if kind == "buy":
        overpay = data.get("overpay", 0)
        if not isinstance(overpay, int) or isinstance(overpay, bool) or not 0 <= overpay <= MAX_OVERPAY:
            raise ValueError("'overpay' must be a small whole number.")
        return Buy(_card_name(data), overpay)
    if kind == "buy_event":
        return BuyEvent(_card_name(data))
    if kind == "spend_coffers":
        count = data.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= MAX_OVERPAY:
            raise ValueError("'count' must be a small positive whole number.")
        return SpendCoffers(count)
    if kind == "spend_villager":
        count = data.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= MAX_OVERPAY:
            raise ValueError("'count' must be a small positive whole number.")
        return SpendVillager(count)
    if kind == "pay_debt":
        count = data.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= MAX_OVERPAY:
            raise ValueError("'count' must be a small positive whole number.")
        return PayDebt(count)
    if kind == "end_phase":
        return EndPhase()
    if kind == "choose":
        selection = data.get("selection")
        if not isinstance(selection, list) or len(selection) > MAX_SELECTION:
            raise ValueError("'selection' must be a short list of card names.")
        if not all(isinstance(c, str) and len(c) <= MAX_NAME_LENGTH for c in selection):
            raise ValueError("'selection' must contain card names.")
        return Choose(tuple(selection))
    raise ValueError("Unknown action type.")
