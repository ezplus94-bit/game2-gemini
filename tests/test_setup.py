import pytest

from dominion.engine import GameConfig, GameStatus, Phase, new_game
from helpers import DEFAULT_KINGDOM, make_game


def test_two_player_supply_sizes():
    s = make_game(2).state
    assert s.supply["Province"] == s.supply["Duchy"] == s.supply["Estate"] == 8
    assert s.supply["Curse"] == 10
    assert s.supply["Copper"] == 60 - 14
    assert s.supply["Silver"] == 40 and s.supply["Gold"] == 30
    assert s.supply["Village"] == 10
    assert s.supply["Gardens"] == 8          # Victory Kingdom cards use the Victory pile size


def test_three_and_four_player_supply_sizes():
    s3 = make_game(3).state
    assert s3.supply["Province"] == 12 and s3.supply["Curse"] == 20
    assert s3.supply["Copper"] == 60 - 21 and s3.supply["Gardens"] == 12
    s4 = make_game(4).state
    assert s4.supply["Curse"] == 30 and s4.supply["Copper"] == 60 - 28


def test_starting_decks_and_hands():
    for p in make_game(3).state.players:
        assert len(p.hand) == 5 and len(p.deck) == 5
        assert sorted(p.hand + p.deck) == ["Copper"] * 7 + ["Estate"] * 3
        assert p.discard == [] and p.in_play == []


def test_initial_turn_state():
    s = make_game().state
    assert s.current_player == 0 and s.phase is Phase.ACTION
    assert (s.actions, s.buys, s.coins) == (1, 1, 0)
    assert s.status is GameStatus.ACTIVE and s.pending is None


@pytest.mark.parametrize("count", [1, 5])
def test_player_count_limits(count):
    with pytest.raises(ValueError):
        new_game(GameConfig([f"P{i}" for i in range(count)], DEFAULT_KINGDOM, 1))


def test_blank_player_name_rejected():
    with pytest.raises(ValueError):
        new_game(GameConfig(["A", "  "], DEFAULT_KINGDOM, 1))


@pytest.mark.parametrize("kingdom", [
    ["Nonexistent"], ["Village", "Village"], ["Copper"], [],
    DEFAULT_KINGDOM + ["Workshop"],
])
def test_invalid_kingdoms_rejected(kingdom):
    with pytest.raises(ValueError):
        new_game(GameConfig(["A", "B"], kingdom, 1))


def test_random_kingdom_is_ten_unique_kingdom_cards():
    game = new_game(GameConfig(["A", "B"], None, 5))
    assert len(set(game.state.kingdom)) == 10


def test_configurable_small_kingdom():
    game = new_game(GameConfig(["A", "B"], ["Village", "Smithy"], 1))
    assert set(game.state.kingdom) == {"Village", "Smithy"}


def test_same_seed_same_game_different_seed_differs():
    a, b = make_game(seed=7), make_game(seed=7)
    assert a.state.players[0].hand == b.state.players[0].hand
    hands = {tuple(make_game(seed=s).state.players[0].hand) for s in range(10)}
    assert len(hands) > 1


def test_supply_overrides():
    s = make_game(supply_overrides={"Province": 1}).state
    assert s.supply["Province"] == 1
    with pytest.raises(ValueError):
        make_game(supply_overrides={"Nope": 1})
    with pytest.raises(ValueError):
        make_game(supply_overrides={"Province": -1})


def test_random_start_varies_is_valid_and_reproducible():
    from dominion.engine import GameConfig, replay
    starters = set()
    for seed in range(40):
        g = new_game(GameConfig(["A", "B", "C"], DEFAULT_KINGDOM, seed, random_start=True))
        starters.add(g.state.current_player)
        assert 0 <= g.state.current_player < 3
        assert g.acting_player == g.state.current_player
        assert f"{g.state.players[g.state.current_player].name} goes first." in g.state.log
        assert replay(g.config, g.history).state.current_player == g.state.current_player
    assert starters == {0, 1, 2}


def test_random_start_does_not_change_the_shuffles_and_default_is_player_zero():
    from dominion.engine import GameConfig
    plain = new_game(GameConfig(["A", "B"], DEFAULT_KINGDOM, 9))
    rand = new_game(GameConfig(["A", "B"], DEFAULT_KINGDOM, 9, random_start=True))
    assert plain.state.current_player == 0
    assert [p.hand for p in plain.state.players] == [p.hand for p in rand.state.players]


def test_turns_rotate_correctly_when_someone_other_than_player_zero_starts():
    from dominion.engine import EndPhase, GameConfig
    g = new_game(GameConfig(["A", "B", "C"], DEFAULT_KINGDOM, 3, random_start=True))
    order = []
    for _ in range(4):
        order.append(g.state.current_player)
        g.apply(g.state.current_player, EndPhase())
        g.apply(g.state.current_player, EndPhase())
    first = order[0]
    assert order == [(first + k) % 3 for k in range(4)]
