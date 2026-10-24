"""Adding a card requires no change to the engine."""

import pytest

from dominion.cards import action, register, unregister
from dominion.engine import Choose, GameConfig, PlayAction, new_game


@pytest.fixture
def temp_cards():
    names = []

    def add(card):
        register(card)
        names.append(card.name)
        return card

    yield add
    for name in names:
        unregister(name)


def test_custom_simple_card(temp_cards):
    temp_cards(action("Test Windfall", 1, lambda ctx: ctx.add_coins(5), "+$5"))
    g = new_game(GameConfig(["A", "B"], ["Test Windfall"], 1))
    g.state.players[0].hand = ["Test Windfall"]
    g.apply(0, PlayAction("Test Windfall"))
    assert g.state.coins == 5


def test_custom_interactive_card(temp_cards):
    def effect(ctx):
        (card,) = yield ctx.choose("Gain Gold or Silver.", ("Gold", "Silver"))
        ctx.gain(card)
        ctx.add_buys(1)

    temp_cards(action("Test Choice", 3, effect))
    g = new_game(GameConfig(["A", "B"], ["Test Choice"], 1))
    g.state.players[0].hand = ["Test Choice"]
    g.apply(0, PlayAction("Test Choice"))
    assert [a.selection for a in g.legal_actions()] == [("Gold",), ("Silver",)]
    g.apply(0, Choose(("Gold",)))
    assert g.state.players[0].discard == ["Gold"] and g.state.buys == 2


def test_card_can_ask_another_player(temp_cards):
    def effect(ctx):
        (answer,) = yield ctx.choose("Give a coin?", ("Yes", "No"), player=1)
        if answer == "Yes":
            ctx.add_coins(1)

    temp_cards(action("Test Ask", 2, effect))
    g = new_game(GameConfig(["A", "B"], ["Test Ask"], 1))
    g.state.players[0].hand = ["Test Ask"]
    g.apply(0, PlayAction("Test Ask"))
    assert g.acting_player == 1                    # the engine now waits for player 1
    assert g.legal_actions(player=0) == []
    g.apply(1, Choose(("Yes",)))
    assert g.state.coins == 1 and g.acting_player == 0


def test_effect_with_multiple_sequential_decisions(temp_cards):
    def effect(ctx):
        (first,) = yield ctx.choose("First?", ("a", "b"))
        (second,) = yield ctx.choose("Second?", ("x", "y"))
        ctx.log(f"picked {first}{second}")

    temp_cards(action("Test Two Step", 2, effect))
    g = new_game(GameConfig(["A", "B"], ["Test Two Step"], 1))
    g.state.players[0].hand = ["Test Two Step"]
    g.apply(0, PlayAction("Test Two Step"))
    g.apply(0, Choose(("b",)))
    assert g.state.pending is not None
    g.apply(0, Choose(("x",)))
    assert g.state.pending is None and "picked bx" in g.state.log
