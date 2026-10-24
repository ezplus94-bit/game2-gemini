"""Heavy self-play with every Intrigue card, Catastrophes and random players.

Each player's deck is stuffed with random Kingdom cards so Actions are played all the time. After every
move: no card is created or lost, the game never raises, every player's view is JSON-safe and hides the
other hands. (Replays are checked on un-stuffed games below, because the stuffing happens outside the history.)
"""

import json
import random

import pytest

from dominion.ai import RandomBot
from dominion.cards import get_card, kingdom_cards
from dominion.cards.registry import catastrophe_cards
from dominion.engine import GameConfig, GameStatus, build_view, new_game, replay
from helpers import total_cards


def stuffed_game(seed, players):
    rng = random.Random(seed)
    pool = kingdom_cards(["Intrigue"]) if seed % 2 else kingdom_cards()
    kingdom = rng.sample(pool, 10)
    cats = rng.sample([c for c in catastrophe_cards() if get_card(c).min_players <= players], rng.choice([0, 1, 2]))
    g = new_game(GameConfig([f"P{i}" for i in range(players)], kingdom, seed, catastrophes=cats))
    for p in g.state.players:                                  # extra cards so Actions are everywhere
        p.deck.extend(rng.choice(kingdom + cats) for _ in range(8))
        rng.shuffle(p.deck)
    return g


@pytest.mark.parametrize("players", [2, 3, 4])
def test_stuffed_random_games_hold_every_invariant(players):
    for seed in range(12):
        g = stuffed_game(seed, players)
        # the extra cards are created outside the supply on purpose: count from here on
        before = total_cards(g)
        rng = random.Random(seed)
        bots = [RandomBot(random.Random(rng.random())) for _ in range(players)]
        moves = 0
        while g.state.status is not GameStatus.FINISHED and moves < 3000:
            actor = g.acting_player
            g.apply(actor, bots[actor].choose(g, actor))
            moves += 1
            assert total_cards(g) == before, f"seed {seed}: cards appeared or vanished after move {moves}"
            if moves % 40 == 0:
                for i in range(players):
                    view = build_view(g, i)
                    json.dumps(view)
                    for j, other in enumerate(view["players"]):
                        if j != i:
                            assert "hand" not in other and "deck" not in other, "another player's cards leaked"
                    assert len(view["hand"]) == len(g.state.players[i].hand)
        if g.state.status is GameStatus.FINISHED:
            stats = build_view(g, 0)["stats"]
            assert all(sum(row["vp"] for row in s["vp_breakdown"]) == s["vp"] for s in stats)


@pytest.mark.parametrize("players", [2, 3, 4])
def test_plain_random_games_replay_exactly_with_every_intrigue_card(players):
    for seed in range(10):
        rng = random.Random(seed)
        kingdom = rng.sample(kingdom_cards(), 10)
        cats = [c for c in catastrophe_cards() if get_card(c).min_players <= players][:2]
        g = new_game(GameConfig([f"P{i}" for i in range(players)], kingdom, seed, catastrophes=cats))
        bots = [RandomBot(random.Random(rng.random())) for _ in range(players)]
        for _ in range(1500):
            if g.state.status is GameStatus.FINISHED:
                break
            actor = g.acting_player
            g.apply(actor, bots[actor].choose(g, actor))
        r = replay(g.config, g.history)
        assert [p.all_cards() for p in r.state.players] == [p.all_cards() for p in g.state.players]
        assert r.state.supply == g.state.supply and r.state.trash == g.state.trash
        assert [(str(x), x.turn, x.kind, x.indent) for x in r.state.log] == [(str(x), x.turn, x.kind, x.indent) for x in g.state.log]
