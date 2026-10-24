"""Shared test helpers."""

from dominion.engine import EndPhase, GameConfig, new_game

DEFAULT_KINGDOM = [
    "Cellar", "Chapel", "Festival", "Gardens", "Laboratory",
    "Market", "Moneylender", "Remodel", "Smithy", "Village",
]


def make_game(players=2, kingdom=None, seed=1, **kwargs):
    names = [f"P{i}" for i in range(players)]
    return new_game(GameConfig(names, kingdom or DEFAULT_KINGDOM, seed, **kwargs))


def set_zones(game, player=0, hand=None, deck=None, discard=None, in_play=None):
    """Overwrite a player's zones. Note: deck's TOP is the END of the list."""
    p = game.state.players[player]
    if hand is not None:
        p.hand = list(hand)
    if deck is not None:
        p.deck = list(deck)
    if discard is not None:
        p.discard = list(discard)
    if in_play is not None:
        p.in_play = list(in_play)


def to_buy_phase(game):
    game.apply(game.acting_player, EndPhase())


def total_cards(game):
    """Every card in the game: supply + trash + all player zones (+ cards set aside by Possession)."""
    s = game.state
    return sum(s.supply.values()) + len(s.trash) + len(s.possession_aside) + sum(len(p.all_cards()) for p in s.players)


def snapshot(game):
    s = game.state
    return (
        tuple((p.name, tuple(p.deck), tuple(p.hand), tuple(p.discard),
               tuple(p.in_play), p.turns_taken) for p in s.players),
        tuple(sorted(s.supply.items())),
        tuple(s.trash),
        s.current_player, s.phase, s.actions, s.buys, s.coins,
        s.status, tuple(s.winners), s.pending is not None,
    )
