"""Empires Landmarks: standing rules for the whole game.

Most hand out VP from a pool when something happens (``after_gain``, ``after_buy``, ``end_of_turn``, ``after_trash``);
the rest change the final score (``score_adjustment``). Pools live in ``GameState.landmark_vp``; pile tokens
(Aqueduct, Defiled Shrine) in ``GameState.pile_vp``.
"""

from __future__ import annotations

from collections import Counter

from ..cards import CardType, get_card
from .state import GameState

POOL_LANDMARKS = ("Arena", "Basilica", "Baths", "Battlefield", "Colonnade", "Labyrinth")   # 6 VP per player
POOL_PER_PLAYER = 6


def setup(state: GameState, rng) -> None:
    """Put the starting VP on the Landmarks and piles, and choose Obelisk's pile."""
    n = len(state.players)
    for name in state.landmarks:
        if name in POOL_LANDMARKS:
            state.landmark_vp[name] = POOL_PER_PLAYER * n
        elif name == "Aqueduct":
            state.landmark_vp[name] = 0
            state.pile_vp["Silver"] = state.pile_vp.get("Silver", 0) + 8
            state.pile_vp["Gold"] = state.pile_vp.get("Gold", 0) + 8
        elif name == "Defiled Shrine":
            state.landmark_vp[name] = 0
            for pile in action_piles(state):
                if not get_card(pile).is_type(CardType.GATHERING):
                    state.pile_vp[pile] = state.pile_vp.get(pile, 0) + 2
        elif name == "Obelisk":
            piles = action_piles(state)
            state.obelisk = rng.choice(piles) if piles else None


def action_piles(state: GameState) -> list:
    """Kingdom piles whose (top) card is an Action, by pile name (a split pile or Knights counts once)."""
    out = []
    for name in state.kingdom:
        top = state.stacks[name][0] if name in state.stacks and state.stacks[name] else (
            state.stack_cards[name][0] if name in state.stack_cards else name)
        if name == "Castles":
            continue
        if get_card(top).is_type(CardType.ACTION):
            out.append(name)
    return out


def _give(state: GameState, player: int, landmark: str, n: int) -> None:
    """Move up to n VP from a Landmark pool to the player."""
    got = max(0, min(n, state.landmark_vp.get(landmark, 0)))
    if got:
        state.landmark_vp[landmark] -= got
        state.players[player].vp_tokens += got
        state.log.append(f"{state.players[player].name} takes {got} VP from {landmark} ({state.landmark_vp[landmark]} left).", "gain", 1)


def after_gain(state: GameState, event) -> None:
    """A card was gained (called for every gain, once its own effects were looked at)."""
    if not state.landmarks:
        return
    card = get_card(event.card)
    player = event.player
    me = state.players[player]
    pile = state.stack_of.get(event.card, event.card)
    on = state.landmarks
    if "Aqueduct" in on:
        if card.is_type(CardType.TREASURE) and state.pile_vp.get(event.card, 0) > 0:
            state.pile_vp[event.card] -= 1
            state.landmark_vp["Aqueduct"] += 1
            state.log.append(f"Aqueduct: 1 VP moves from the {event.card} pile onto Aqueduct.", "info", 1)
        if card.is_type(CardType.VICTORY):
            _give(state, player, "Aqueduct", state.landmark_vp.get("Aqueduct", 0))
    if "Battlefield" in on and card.is_type(CardType.VICTORY):
        _give(state, player, "Battlefield", 2)
    if "Colonnade" in on and event.buy_phase and card.is_type(CardType.ACTION) and event.card in me.in_play:
        _give(state, player, "Colonnade", 2)
    if "Defiled Shrine" in on:
        if card.is_type(CardType.ACTION) and state.pile_vp.get(pile, 0) > 0:
            state.pile_vp[pile] -= 1
            state.landmark_vp["Defiled Shrine"] += 1
            state.log.append(f"Defiled Shrine: 1 VP moves from the {pile} pile onto Defiled Shrine.", "info", 1)
        if event.bought and event.card == "Curse":
            _give(state, player, "Defiled Shrine", state.landmark_vp.get("Defiled Shrine", 0))
    if "Labyrinth" in on and event.nth == 2:
        _give(state, player, "Labyrinth", 2)
    if "Mountain Pass" in on and event.card == "Province" and not state.mountain_done:
        state.mountain_done = True
        state.mountain_next = player
        state.log.append(f"{me.name} is the first to gain a Province: Mountain Pass bidding follows this turn.", "special", 1)


def after_buy(state: GameState, player: int, card: str) -> None:
    """A card was bought (``state.coins`` is what is left)."""
    if "Basilica" in state.landmarks and state.coins >= 2:
        _give(state, player, "Basilica", 2)


def after_trash(state: GameState, player: int) -> None:
    if "Tomb" in state.landmarks:
        state.players[player].vp_tokens += 1
        state.log.append(f"Tomb: {state.players[player].name} gets +1 VP for trashing a card.", "gain", 1)


def end_of_turn(state: GameState, player: int) -> None:
    if "Baths" in state.landmarks and not state.players[player].gained_turn:
        _give(state, player, "Baths", 2)


def _pile_empty(state: GameState, card: str) -> bool:
    pile = state.stack_of.get(card)
    if pile is not None:
        return not state.stacks.get(pile)
    return card in state.supply and state.supply[card] == 0


def score_adjustment(state: GameState, index: int) -> int:
    """VP from the scoring Landmarks for one player."""
    if not state.landmarks:
        return 0
    me = state.players[index]
    cards = me.all_cards()
    count = Counter(cards)
    total = 0
    on = state.landmarks
    if "Bandit Fort" in on:
        total -= 2 * (count["Silver"] + count["Gold"])
    if "Fountain" in on and count["Copper"] >= 10:
        total += 15
    if "Keep" in on:
        for name in count:
            if get_card(name).is_type(CardType.TREASURE):
                if all(count[name] >= Counter(o.all_cards())[name] for o in state.players if o is not me):
                    total += 5
    if "Museum" in on:
        total += 2 * len(count)
    if "Obelisk" in on and state.obelisk:
        total += 2 * sum(1 for c in cards if state.stack_of.get(c, c) == state.obelisk)
    if "Orchard" in on:
        total += 4 * sum(1 for n, c in count.items() if get_card(n).is_type(CardType.ACTION) and c >= 3)
    if "Palace" in on:
        total += 3 * min(count["Copper"], count["Silver"], count["Gold"])
    if "Tower" in on:
        total += sum(c for n, c in count.items() if not get_card(n).is_type(CardType.VICTORY) and _pile_empty(state, n))
    if "Triumphal Arch" in on:
        actions = sorted((c for n, c in count.items() if get_card(n).is_type(CardType.ACTION)), reverse=True)
        if len(actions) >= 2:
            total += 3 * actions[1]
    if "Wall" in on:
        total -= max(0, len(cards) - 15)
    if "Wolf Den" in on:
        total -= 3 * sum(1 for c in count.values() if c == 1)
    return total


def score_rows(state: GameState, index: int) -> list:
    """Per-Landmark breakdown (for the end-of-game stats): rows (landmark, vp) that add up to ``score_adjustment``."""
    rows = []
    for name in state.landmarks:
        saved = state.landmarks
        state.landmarks = (name,)
        try:
            v = score_adjustment(state, index)
        finally:
            state.landmarks = saved
        if v:
            rows.append({"card": name, "count": 1, "vp": v})
    return rows
