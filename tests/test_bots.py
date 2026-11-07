"""Self-play: bots only choose from legal actions, and the engine's invariants
must hold for every game they play."""

import random

import pytest

from dominion.ai import BigMoneyBot, RandomBot, run_game
from dominion.engine import GameConfig, GameStatus, Phase, new_game, replay
from helpers import DEFAULT_KINGDOM, snapshot, total_cards


def check_invariants(game, expected_total):
    s = game.state
    assert all(count >= 0 for count in s.supply.values())
    assert total_cards(game) == expected_total          # cards are never created or destroyed
    assert s.actions >= 0 and s.buys >= 0 and s.coins >= 0
    if s.pending is None:                              # no card may be left "in limbo" between decisions
        assert all(p.set_aside == [] for p in s.players)


def play_checked(game, bots):
    """Like run_game, but asserts invariants and legality after every action."""
    expected = total_cards(game)
    for _ in range(20000):
        if game.state.status is GameStatus.FINISHED:
            return
        player = game.acting_player
        action = bots[player].choose(game, player)
        assert action in game.legal_actions(player)
        assert game.validate(player, action) is None
        game.apply(player, action)
        check_invariants(game, expected)
    pytest.fail("game did not finish")


@pytest.mark.parametrize("seed", range(8))
def test_random_bots_play_legal_games_to_completion(seed):
    game = new_game(GameConfig(["A", "B", "C"], DEFAULT_KINGDOM, seed))
    bots = [RandomBot(random.Random(seed * 10 + i)) for i in range(3)]
    play_checked(game, bots)
    assert game.state.winners and game.state.pending is None


NEW_CARDS = ["Harbinger", "Merchant", "Vassal", "Poacher", "Mine", "Library", "Sentry",
             "Artisan", "Council Room", "Throne Room"]


@pytest.mark.parametrize("seed", range(25))
def test_random_bots_with_the_new_cards_keep_every_invariant(seed):
    players = 2 + seed % 3
    game = new_game(GameConfig([f"P{i}" for i in range(players)], NEW_CARDS, seed))
    play_checked(game, [RandomBot(random.Random(seed * 7 + i)) for i in range(players)])
    assert game.state.status is GameStatus.FINISHED
    # the replayed game must match exactly (nested effects are deterministic too)
    assert snapshot(replay(game.config, game.history)) == snapshot(game)


@pytest.mark.parametrize("players", [2, 3, 4])
def test_big_money_self_play_finishes(players):
    game = new_game(GameConfig([f"P{i}" for i in range(players)], DEFAULT_KINGDOM, 42))
    play_checked(game, [BigMoneyBot() for _ in range(players)])
    assert game.state.status is GameStatus.FINISHED


def test_big_money_beats_random():
    wins = 0
    for seed in range(20):
        game = new_game(GameConfig(["Money", "Random"], DEFAULT_KINGDOM, seed))
        run_game(game, [BigMoneyBot(), RandomBot(random.Random(seed))])
        wins += 0 in game.state.winners
    assert wins >= 16


@pytest.mark.parametrize("seed", range(5))
def test_games_are_deterministic_and_replayable(seed):
    config = GameConfig(["A", "B"], DEFAULT_KINGDOM, seed)
    original = new_game(config)
    run_game(original, [RandomBot(random.Random(1)), RandomBot(random.Random(2))])
    rebuilt = replay(original.config, original.history)
    assert snapshot(rebuilt) == snapshot(original)
    assert rebuilt.state.log == original.state.log


def test_clone_mid_game_including_pending_decision():
    # Play a natural game (no hand-editing, so it is replayable) until a decision is pending.
    game = new_game(GameConfig(["A", "B"], ["Cellar", "Village"], 3))
    bots = [RandomBot(random.Random(5)), RandomBot(random.Random(6))]
    for _ in range(5000):
        if game.state.pending is not None or game.state.status is GameStatus.FINISHED:
            break
        player = game.acting_player
        game.apply(player, bots[player].choose(game, player))
    assert game.state.pending is not None, "expected the random bots to play Cellar"
    copy = game.clone()
    assert snapshot(copy) == snapshot(game)
    answer = game.legal_actions()[0]
    game.apply(game.acting_player, answer)
    copy.apply(copy.acting_player, answer)
    assert snapshot(copy) == snapshot(game)
