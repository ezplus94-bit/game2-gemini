"""Text-mode prototype UI.

The UI only *displays* state and *submits* actions. It never decides what is
legal: the menu is built from ``game.legal_actions`` and free-form answers are
validated by the engine, which may reject them.

    python -m dominion                       # you vs one BigMoney bot
    python -m dominion --humans 2 --bots 0   # hot-seat
    python -m dominion --humans 0 --bots 2   # watch two bots
"""

from __future__ import annotations

import argparse
from typing import Callable, Optional, Sequence

from ..ai import BigMoneyBot, run_game
from ..cards import get_card
from ..engine import (
    Buy, Choose, EndPhase, Game, GameConfig, GameStatus, IllegalActionError,
    Phase, PlayAction, PlayAllTreasures, PlayTreasure, SpendCoffers, SpendVillagers,
    final_scores, new_game,
)


def parse_selection(text: str, options: Sequence[str]) -> tuple:
    """Turn '1 3' or '1,3' (1-based positions) into a tuple of option names."""
    text = text.strip()
    if not text:
        return ()
    picks = []
    for token in text.replace(",", " ").split():
        if not token.isdigit():
            raise ValueError(f"'{token}' is not a number.")
        index = int(token)
        if not 1 <= index <= len(options):
            raise ValueError(f"{index} is not between 1 and {len(options)}.")
        picks.append(index)
    if len(set(picks)) != len(picks):
        raise ValueError("Each number can only be used once.")
    return tuple(options[i - 1] for i in picks)


def render_state(game: Game) -> str:
    s = game.state
    viewer = s.players[s.pending.decision.player if s.pending is not None else s.current_player]
    current = s.players[s.current_player]
    lines = [
        "",
        f"=== Turn {s.turn_number}: {current.name} - {s.phase.value.upper()} phase ===",
        f"Actions: {s.actions}   Buys: {s.buys}   Coins: ${s.coins}   Coffers: {current.coffers}   Villagers: {current.villagers}",
        "Supply: " + "  ".join(
            f"{name} ${get_card(name).cost} x{count}"
            for name, count in sorted(s.supply.items(), key=lambda kv: (get_card(kv[0]).cost, kv[0]))
            if count > 0
        ),
        "In play: " + (", ".join(current.in_play) or "-"),
        f"{viewer.name}'s hand: " + (", ".join(sorted(viewer.hand)) or "-"),
        f"Deck: {len(viewer.deck)}   Discard: {len(viewer.discard)}",
    ]
    return "\n".join(lines)


def describe_action(action) -> str:
    if isinstance(action, PlayAction):
        return f"Play {action.card} - {get_card(action.card).text}"
    if isinstance(action, PlayTreasure):
        return f"Play {action.card}"
    if isinstance(action, PlayAllTreasures):
        return "Play all Treasures"
    if isinstance(action, Buy):
        return f"Buy {action.card} (${get_card(action.card).cost})"
    if isinstance(action, SpendCoffers):
        return f"Spend {action.count} Coffers (+${action.count})"
    if isinstance(action, SpendVillagers):
        return f"Spend {action.count} Villager(s) (+{action.count} Action(s))"
    if isinstance(action, EndPhase):
        return "End phase"
    return str(action)


class TextUI:
    def __init__(self, game: Game, bots: dict, input_fn: Callable, print_fn: Callable) -> None:
        self.game = game
        self.bots = bots
        self.input = input_fn
        self.print = print_fn
        self._log_pos = 0

    def run(self) -> int:
        game = self.game
        self._flush_log()
        steps = 0
        while game.state.status is GameStatus.ACTIVE:
            steps += 1
            if steps > 100000:
                self.print("Stopping: too many steps.")
                return 1
            player = game.acting_player
            try:
                if player in self.bots:
                    game.apply(player, self.bots[player].choose(game, player))
                else:
                    if not self._human_step(player):
                        self.print("Game abandoned.")
                        return 0
            except IllegalActionError as err:
                self.print(f"  Illegal: {err}")
            self._flush_log()
        self._print_result()
        return 0

    # ------------------------------------------------------------------
    def _human_step(self, player: int) -> bool:
        """Return False if the user quit."""
        game = self.game
        self.print(render_state(game))
        try:
            if game.state.pending is not None:
                return self._ask_decision(player)
            return self._ask_menu(player)
        except EOFError:
            return False

    def _ask_menu(self, player: int) -> bool:
        legal = self.game.legal_actions(player)
        for number, action in enumerate(legal, 1):
            self.print(f"  {number}. {describe_action(action)}")
        raw = self.input("> ").strip().lower()
        if raw in ("q", "quit"):
            return False
        if raw.isdigit() and 1 <= int(raw) <= len(legal):
            self.game.apply(player, legal[int(raw) - 1])
        else:
            self.print("  Enter the number of an option (or q to quit).")
        return True

    def _ask_decision(self, player: int) -> bool:
        decision = self.game.state.pending.decision
        self.print(f"  {decision.prompt}")
        for number, option in enumerate(decision.options, 1):
            self.print(f"  {number}. {option}")
        self.print(
            f"  Pick {decision.min_choices}"
            + (f" to {decision.max_choices}" if decision.max_choices != decision.min_choices else "")
            + " (numbers separated by spaces; blank for none; q to quit)"
        )
        raw = self.input("> ").strip()
        if raw.lower() in ("q", "quit"):
            return False
        try:
            selection = parse_selection(raw, decision.options)
        except ValueError as err:
            self.print(f"  {err}")
            return True
        self.game.apply(player, Choose(selection))   # engine validates the answer
        return True

    def _flush_log(self) -> None:
        log = self.game.state.log
        for line in log[self._log_pos:]:
            self.print("  " + line)
        self._log_pos = len(log)

    def _print_result(self) -> None:
        s = self.game.state
        self.print("\n=== Game over ===")
        for player, score in zip(s.players, final_scores(s)):
            self.print(f"  {player.name}: {score} VP in {player.turns_taken} turns")
        self.print("Winner(s): " + ", ".join(s.players[i].name for i in s.winners))


def main(argv: Optional[Sequence[str]] = None, input_fn: Callable = input, print_fn: Callable = print) -> int:
    parser = argparse.ArgumentParser(prog="dominion", description="Text-mode Modinion prototype.")
    parser.add_argument("--humans", type=int, default=1, help="number of human players")
    parser.add_argument("--bots", type=int, default=1, help="number of BigMoney bots")
    parser.add_argument("--seed", type=int, default=None, help="random seed (for repeatable games)")
    parser.add_argument("--kingdom", nargs="+", default=None, help="Kingdom card names (default: random)")
    args = parser.parse_args(argv)

    names = [f"Player {i + 1}" for i in range(args.humans)] + [f"Bot {i + 1}" for i in range(args.bots)]
    try:
        game = new_game(GameConfig(names, args.kingdom, args.seed))
    except ValueError as err:
        print_fn(f"Cannot start game: {err}")
        return 2
    bots = {i: BigMoneyBot() for i in range(args.humans, args.humans + args.bots)}
    return TextUI(game, bots, input_fn, print_fn).run()


if __name__ == "__main__":
    raise SystemExit(main())
