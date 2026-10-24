"""Simple bots. They are *clients* of the engine: every move is chosen from
``game.legal_actions``, so a bot can never make an illegal move."""

from __future__ import annotations

import random
from typing import Optional, Protocol, Sequence

from ..cards import CardType, UnknownCardError, get_card
from ..engine import Buy, Choose, EndPhase, Game, PlayAllTreasures, Phase


def _keep_value(name: str) -> float:
    """How much Big Money wants to keep a card (low = discard/trash first)."""
    try:
        card = get_card(name)
    except UnknownCardError:        # a text option such as "+1 Card" or "Yes": no preference
        return 0
    if card.is_type(CardType.CURSE):
        return -2
    if card.is_type(CardType.VICTORY):
        return -1
    if card.is_type(CardType.TREASURE):
        return card.coins
    return 0.5


class Bot(Protocol):
    def choose(self, game: Game, player: int): ...


class RandomBot:
    """Picks uniformly among legal actions (useful for fuzz testing)."""

    def __init__(self, rng: Optional[random.Random] = None) -> None:
        self.rng = rng or random.Random()

    def choose(self, game: Game, player: int):
        return self.rng.choice(game.legal_actions(player))


class BigMoneyBot:
    """Classic baseline: never plays Actions; buys Province > Gold > Silver."""

    def choose(self, game: Game, player: int):
        legal = game.legal_actions(player)
        state = game.state
        if state.pending is not None:
            decision = state.pending.decision
            # Give up the least useful cards, and only as many as required.
            worst = sorted(decision.options, key=_keep_value)[: decision.min_choices]
            answer = Choose(tuple(sorted(worst)))
            return answer if answer in legal else next(a for a in legal if isinstance(a, Choose))
        if state.phase is Phase.ACTION:
            return EndPhase()
        if PlayAllTreasures() in legal:
            return PlayAllTreasures()
        for card in ("Province", "Gold", "Silver"):
            if Buy(card) in legal:
                return Buy(card)
        return EndPhase()


def run_game(game: Game, bots: Sequence[Bot], max_actions: int = 20000) -> Game:
    """Play a game to completion. ``bots[i]`` controls player i."""
    for _ in range(max_actions):
        if game.state.status.value == "finished":
            return game
        player = game.acting_player
        game.apply(player, bots[player].choose(game, player))
    raise RuntimeError(f"Game did not finish within {max_actions} actions.")
