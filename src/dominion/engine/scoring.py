"""Victory point totals and winner determination."""

from __future__ import annotations

from collections import Counter

from ..cards import get_card
from . import landmarks
from .state import GameState, PlayerState


def score_player(player: PlayerState, state: GameState = None) -> int:
    """VP of one player. With ``state`` the Empires Landmarks that change the score count too."""
    cards = player.all_cards()
    total = (sum(get_card(c).victory_points(cards) for c in cards) + player.vp_tokens + 4 * player.tavern.count("Distant Lands")
             - 2 * player.miserable)                                     # Nocturne: Miserable -2, Twice Miserable -4
    if state is not None and state.ally == "Plateau Shepherds":          # Allies: pair Favors with cards costing $2, 2 VP per pair
        total += 2 * min(player.favors, sum(1 for c in cards if get_card(c).cost == 2 and not get_card(c).potion_cost and not get_card(c).debt_cost))
    if state is not None and state.landmarks:
        total += landmarks.score_adjustment(state, state.players.index(player))
    return total


def final_scores(state: GameState) -> list:
    return [score_player(p, state) for p in state.players]


def determine_winners(state: GameState) -> list:
    """Highest VP wins (a player who resigned cannot win); ties go to the player with
    the fewest turns; any remaining tie is shared."""
    scores = final_scores(state)
    eligible = [i for i in range(len(scores)) if i not in state.resigned] or list(range(len(scores)))
    best = max(scores[i] for i in eligible)
    tied = [i for i in eligible if scores[i] == best]
    fewest = min(state.players[i].turns_taken for i in tied)
    return [i for i in tied if state.players[i].turns_taken == fewest]


def vp_breakdown(player: PlayerState, state: GameState = None) -> list:
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
    if "Distant Lands" in player.tavern:
        rows.append({"card": "Distant Lands on the Tavern mat", "count": player.tavern.count("Distant Lands"), "vp": 4 * player.tavern.count("Distant Lands")})
    if player.vp_tokens:
        rows.append({"card": "VP tokens", "count": player.vp_tokens, "vp": player.vp_tokens})
    if player.miserable:
        rows.append({"card": "Miserable" if player.miserable == 1 else "Twice Miserable", "count": 1, "vp": -2 * player.miserable})
    if state is not None and state.ally == "Plateau Shepherds":
        pairs = min(player.favors, sum(1 for c in cards if get_card(c).cost == 2 and not get_card(c).potion_cost and not get_card(c).debt_cost))
        if pairs:
            rows.append({"card": "Plateau Shepherds (Favor pairs)", "count": pairs, "vp": 2 * pairs})
    if state is not None and state.landmarks:
        rows.extend(landmarks.score_rows(state, state.players.index(player)))
    rows.sort(key=lambda r: (-r["vp"], r["card"]))
    return rows


def final_stats(state: GameState) -> list:
    """Per-player end-of-game summary (public once the game is over)."""
    stats = []
    for p in state.players:
        owned = Counter(p.all_cards())
        stats.append({
            "name": p.name,
            "vp": score_player(p, state),
            "turns": p.turns_taken,
            "bought": dict(sorted(Counter(p.bought).items())),
            "bought_total": len(p.bought),
            "gained_total": len(p.gained),
            "deck": dict(sorted(owned.items())),
            "deck_total": sum(owned.values()),
            "vp_breakdown": vp_breakdown(p, state),
        })
    return stats
