"""Per-player projection of a game: what ONE player is allowed to see.

The full ``GameState`` contains every player's hand and deck. Anything sent to
a client must come from ``build_view`` so hidden information never leaks. The
result is plain JSON-serializable data.

Visible to everyone: supply, trash, in-play cards, turn resources, each
player's card counts and the top card of their discard pile, the event log.
Visible only to the owner: their own hand. A pending decision's prompt and options go only to the
player who must answer. During a Possession turn the possessor also sees the possessed player's hand
(``view["possession"]["hand"]``) and answers that player's questions.
"""

from __future__ import annotations

from ..cards import get_card
from .actions import Choose
from .codec import action_to_dict
from .rules import legal_actions
from .cardtypes import type_values
from .costs import card_cost
from .scoring import final_scores, final_stats, score_player
from .state import GameStatus

BASIC_PILES = ("Copper", "Silver", "Gold", "Platinum", "Estate", "Duchy", "Province", "Colony", "Curse", "Potion")
LOG_LINES = 200


def card_info(name: str, state=None) -> dict:
    card = get_card(name)
    return {
        "name": name,
        "cost": card.cost,
        "potion_cost": card.potion_cost,
        "types": type_values(state, name) if state is not None else sorted(t.value for t in card.types),
        "text": card.text,
        "min_players": card.min_players,
        "expansion": card.expansion,
        "companions": list(card.companions),
        "overpay": card.overpay,
    }


def build_view(game, player: int) -> dict:
    s = game.state
    me = s.players[player]
    viewer_blind = me.blind > 0              # Roofie: this viewer cannot read card names, costs or texts
    acting = game.acting_player              # whoever the game waits for (the possessor, under Possession)

    piles = []
    for name in [*BASIC_PILES, *s.kingdom, *s.catastrophes]:
        if name in s.supply:
            info = card_info(name, s)
            info["count"] = s.supply[name]
            info["price"] = card_cost(s, name)       # what it costs right now (Bridge)
            info["kingdom"] = name in s.kingdom
            info["catastrophe"] = name in s.catastrophes
            info["embargo"] = s.embargo.get(name, 0)         # Embargo tokens on this pile
            info["walled_by"] = s.walls.get(name)     # Fortnite: index of the player whose wall stands here, or None
            info["bane"] = (name == s.bane)
            piles.append(info)

    players = []
    for i, p in enumerate(s.players):
        players.append({
            "name": p.name,
            "hand_count": len(p.hand),
            "deck_count": len(p.deck),
            "discard_top": p.discard[-1] if p.discard else None,
            "in_play": list(p.in_play),
            "turns_taken": p.turns_taken,
            "skip_pending": p.skips > 0,
            "protection": "forever" if p.protected_forever else p.protection,
            "bonus_coins": p.bonus_coins,
            "invisible": p.invisible,
            "blind": p.blind,
            "island_mat": list(p.island_mat),             # the Island mat is face up
            "village_mat": len(p.village_mat),            # the Native Village mat is face down: only the count shows
            "haven": len(p.haven),
            "pirate_tokens": p.pirate_tokens,
            "vp_tokens": p.vp_tokens,
            "coffers": p.coffers,
            "villagers": p.villagers,
            "horse_traders": len(p.horse_traders),
            "possessed_by": s.possessor if (s.possessor is not None and i == s.current_player) else None,
            "vp": score_player(p),            # deliberately public: players asked to see each other's VP
        })

    pending = None
    if s.pending is not None:
        d = s.pending.decision
        pending = {"player": acting, "source": d.source or s.pending.source}
        if acting == player:            # prompt/options may reveal a hand: only the one who answers sees them
            pending.update(
                prompt=d.prompt, options=list(d.options), min=d.min_choices, max=d.max_choices
            )

    possession = None
    if s.possessor is not None:
        possession = {"possessor": s.possessor, "possessed": s.current_player}
        if player == s.possessor:       # "you can see all cards they can": the possessor sees the possessed hand
            possession["hand"] = sorted(s.players[s.current_player].hand)

    # Free-form answers to a pending decision are described by `pending`, not
    # enumerated (that list can be huge), so Choose actions are not listed here.
    if s.pending is not None:
        legal = []
    else:
        legal = [action_to_dict(a) for a in legal_actions(s, player) if not isinstance(a, Choose)]

    names = {name for name in s.supply} | set(s.prizes)
    for p in s.players:
        names.update(p.all_cards())
    view = {
        "status": s.status.value,
        "version": len(game.history),     # increases with every applied action
        "you": player,
        "players": players,
        "piles": piles,
        "prizes": [card_info(n, s) for n in s.prizes],
        "bane": s.bane,
        "trash": list(s.trash),
        "cost_reduction": s.cost_reduction,
        "midas": s.midas,
        "potions": s.potions,
        "trade_mat": s.trade_mat,
        "banned": sorted(s.banned),
        "has_potions": "Potion" in s.supply,
        "possession": possession,
        "controller": s.possessor if s.possessor is not None else s.current_player,
        "blind": viewer_blind,
        "cheats": s.cheats,
        "resigned": list(s.resigned),
        "end_reason": s.end_reason,
        "current_player": s.current_player,
        "acting_player": acting,
        "phase": s.phase.value,
        "actions": s.actions,
        "buys": s.buys,
        "coins": s.coins,
        "turn_number": s.turn_number,
        "hand": sorted(me.hand),
        "pending": pending,
        "legal_actions": legal,
        "log": _log_view(s.log),
        "cards": {n: card_info(n, s) for n in sorted(names)},
    }
    if s.status is GameStatus.FINISHED:
        view["final_scores"] = final_scores(s)
        view["winners"] = list(s.winners)
        view["stats"] = final_stats(s)
    return view


def _log_view(log) -> list:
    """The last LOG_LINES entries as plain data. ``i`` is the entry's position in the whole
    log, so a client can tell which entries are new."""
    first = max(0, len(log) - LOG_LINES)
    return [
        {"i": first + n, "turn": line.turn, "kind": line.kind, "indent": line.indent, "text": str(line)}
        for n, line in enumerate(log[first:])
    ]
