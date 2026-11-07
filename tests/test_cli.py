import pytest

from dominion.ui.cli import describe_action, main, parse_selection, render_state
from dominion.engine import Buy, EndPhase
from helpers import make_game


def test_parse_selection_accepts_numbers_and_commas():
    options = ("Copper", "Estate", "Estate", "Silver")
    assert parse_selection("1 4", options) == ("Copper", "Silver")
    assert parse_selection("2,3", options) == ("Estate", "Estate")
    assert parse_selection("   ", options) == ()


@pytest.mark.parametrize("text", ["0", "5", "x", "1 1"])
def test_parse_selection_rejects_bad_input(text):
    with pytest.raises(ValueError):
        parse_selection(text, ("a", "b", "c", "d"))


def test_render_and_describe_do_not_crash():
    game = make_game()
    assert "ACTION phase" in render_state(game)
    assert "Buy Silver" in describe_action(Buy("Silver"))
    assert describe_action(EndPhase()) == "End phase"


def test_bot_vs_bot_game_runs_to_the_end():
    lines = []
    code = main(["--humans", "0", "--bots", "2", "--seed", "3"], print_fn=lines.append)
    assert code == 0
    assert any("Game over" in line for line in lines)


def test_invalid_setup_reports_error():
    lines = []
    assert main(["--humans", "1", "--bots", "0"], print_fn=lines.append) == 2
    assert "Cannot start game" in lines[0]


def test_human_can_quit():
    lines = []
    code = main(["--humans", "1", "--bots", "1", "--seed", "1"],
                input_fn=lambda prompt: "q", print_fn=lines.append)
    assert code == 0 and "Game abandoned." in lines
