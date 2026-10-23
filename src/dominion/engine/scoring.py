"""Victory point totals and winner determination."""

from __future__ import annotations

from collections import Counter

from ..cards import get_card
from .state import GameState, PlayerState


def score_player(player: PlayerState) -> int:
    cards = player.all_cards()
    return sum(get_card(c).victory_points(cards) for c in cards) + player.vp_tokens


def final_scores(state: GameState) -> list:
    return [score_player(p) for p in state.players]


def determine_winners(state: GameState) -> list:
    """Highest VP wins (a player who resigned cannot win); ties go to the player with
    the fewest turns; any remaining tie is shared."""
    scores = final_scores(state)
    eligible = [i for i in range(len(scores)) if i not in state.resigned] or list(range(len(scores)))
    best = max(scores[i] for i in eligible)
    tied = [i for i in eligible if scores[i] == best]
    fewest = min(state.players[i].turns_taken for i in tied)
    return [i for i in tied if state.players[i].turns_taken == fewest]


def vp_breakdown(player: PlayerState) -> list:
    """Where a player's points come from: one row per card name that scores (or costs) points.

    Variable cards (Gardens, Duke) are summed over every copy, so the rows add up
    to exactly ``score_player``."""
    cards = player.all_cards()
    rows = []
    for name, count in sorted(Counter(cards).items()):
        card = get_card(name)
        total = count * card.victory_points(cards)
        if total != 0:
            rows.append({"card": name, "count": count, "vp": total})
    if player.vp_tokens != 0:
        rows.append({"card": "VP tokens", "count": player.vp_tokens, "vp": player.vp_tokens})
    rows.sort(key=lambda r: (-r["vp"], r["card"]))
    return rows


def final_stats(state: GameState) -> list:
    """Per-player end-of-game summary (public once the game is over)."""
    stats = []
    for p in state.players:
        owned = Counter(p.all_cards())
        stats.append({
            "name": p.name,
            "vp": score_player(p),
            "turns": p.turns_taken,
            "bought": dict(sorted(Counter(p.bought).items())),
            "bought_total": len(p.bought),
            "gained_total": len(p.gained),
            "deck": dict(sorted(owned.items())),
            "deck_total": sum(owned.values()),
            "vp_breakdown": vp_breakdown(p),
        })
    return stats
