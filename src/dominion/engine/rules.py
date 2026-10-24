"""Rules validation: the single authority on what is legal.

``validate`` answers "may this player do this right now?" and ``legal_actions``
enumerates every legal action. Neither mutates anything. UIs and bots must pick
from ``legal_actions`` (or submit and be rejected by ``validate``); they never
decide legality themselves.

During a Possession turn the player whose turn it is (``state.current_player``) is the *possessed* player; every
decision about that turn is made by ``state.possessor``, so that is the player the game waits for.
"""

from __future__ import annotations

from collections import Counter
from itertools import combinations
from typing import Optional

from ..cards import CardType, get_card
from .actions import (
    Action, Buy, Cheat, Choose, Decision, EndGame, EndPhase, PlayAction, PlayAllTreasures, PlayTreasure, Resign,
)
from .cardtypes import is_treasure
from .constants import CHEAT_KINDS
from .costs import card_cost, is_walled
from .state import GameState, GameStatus, Phase


class IllegalActionError(Exception):
    """Raised by ``Game.apply`` when an action is rejected."""


def turn_controller(state: GameState) -> int:
    """Who makes the decisions of the current turn: the possessor during a Possession turn, else the turn's owner."""
    return state.possessor if state.possessor is not None else state.current_player


def acting_player(state: GameState) -> int:
    """Whose input the game is waiting for."""
    if state.pending is not None:
        asked = state.pending.decision.player
        if state.possessor is not None and asked == state.current_player:
            return state.possessor                  # the possessor answers for the possessed player
        return asked
    return turn_controller(state)


def is_game_over(state: GameState) -> bool:
    if state.supply.get("Province", 1) == 0 or state.supply.get("Colony", 1) == 0:
        return True
    empty = sum(
        1 for name, count in state.supply.items()
        if count == 0 and name not in state.catastrophes     # scarce piles never end the game
    )
    return empty >= state.empty_pile_limit


def validate(state: GameState, player: int, action: Action) -> Optional[str]:
    """Return None if legal, otherwise a human-readable reason."""
    if state.status is GameStatus.FINISHED:
        return "The game is over."
    if not isinstance(player, int) or not 0 <= player < len(state.players):
        return "Unknown player."

    # Giving up and ending the game are allowed at any moment, even in the middle of a card effect.
    if isinstance(action, (Resign, EndGame)):
        return None
    if isinstance(action, Cheat):
        if not state.cheats:
            return "Cheat codes are not turned on in this game."
        if action.kind not in CHEAT_KINDS:
            return "Unknown cheat code."
        if state.pending is not None:
            return "Answer the pending decision first."
        if player != turn_controller(state):
            return "Cheat codes only work on your own turn."
        return None

    # A paused card effect takes priority over everything else.
    if state.pending is not None:
        if player != acting_player(state):
            return "Waiting for another player to make a decision."
        if not isinstance(action, Choose):
            return "A decision is pending; you must answer it first."
        return _validate_choice(state.pending.decision, action)

    if player != turn_controller(state):
        return "It is not your turn."
    if isinstance(action, Choose):
        return "There is no pending decision."

    me = state.players[state.current_player]      # the hand being played (the possessed player's, under Possession)

    if isinstance(action, EndPhase):
        return None

    if isinstance(action, PlayAction):
        if state.phase is not Phase.ACTION:
            return "Actions can only be played during the Action phase."
        if state.actions < 1:
            return "You have no Actions left."
        if action.card not in me.hand:
            return f"{action.card} is not in your hand."
        if not get_card(action.card).is_type(CardType.ACTION):
            return f"{action.card} is not an Action card."
        return None

    if isinstance(action, PlayTreasure):
        if state.phase is not Phase.BUY:
            return "Treasures can only be played during the Buy phase."
        if action.card not in me.hand:
            return f"{action.card} is not in your hand."
        if not is_treasure(state, action.card):
            return f"{action.card} is not a Treasure."
        return None

    if isinstance(action, PlayAllTreasures):
        if state.phase is not Phase.BUY:
            return "Treasures can only be played during the Buy phase."
        if not _treasures_in_hand(state, me.hand):
            return "You have no Treasures in hand."
        return None

    if isinstance(action, Buy):
        if state.phase is not Phase.BUY:
            return "You can only buy during the Buy phase."
        if state.buy_locked:
            return "You may not buy cards this turn."
        if state.buys < 1:
            return "You have no Buys left."
        if action.card not in state.supply:
            return f"{action.card} is not in this game's supply."
        if state.supply[action.card] <= 0:
            return f"The {action.card} pile is empty."
        if is_walled(state, action.card, player):
            return f"{state.players[state.walls[action.card]].name} has walled off the {action.card} pile."
        cost = card_cost(state, action.card)
        if cost > state.coins:
            return f"{action.card} costs ${cost} but you only have ${state.coins}."
        potion_cost = get_card(action.card).potion_cost
        if potion_cost > state.potions:
            return f"{action.card} costs {potion_cost} Potion(s) but you only have {state.potions}."
        return _buy_restriction(state, action.card)

    return "Unknown action."


def legal_actions(state: GameState, player: Optional[int] = None) -> list:
    """Every legal action for ``player`` (default: whoever the game awaits)."""
    if state.status is GameStatus.FINISHED:
        return []
    actor = acting_player(state)
    if player is not None and player != actor:
        return []

    if state.pending is not None:
        return _legal_choices(state.pending.decision)

    me = state.players[state.current_player]
    result: list = []

    if state.phase is Phase.ACTION:
        if state.actions >= 1:
            for card in sorted(set(me.hand)):
                if get_card(card).is_type(CardType.ACTION):
                    result.append(PlayAction(card))
        result.append(EndPhase())
        return result

    # Buy phase
    treasures = sorted(set(_treasures_in_hand(state, me.hand)))
    for card in treasures:
        result.append(PlayTreasure(card))
    if treasures:
        result.append(PlayAllTreasures())
    if state.buys >= 1 and not state.buy_locked:
        for name in sorted(state.supply):
            if state.supply[name] > 0 and card_cost(state, name) <= state.coins and not is_walled(state, name, actor) and state.potions >= get_card(name).potion_cost and _buy_restriction(state, name) is None:
                result.append(Buy(name))
    result.append(EndPhase())
    return result


# ------------------------------------------------------------------ helpers
def _treasures_in_hand(state: GameState, hand: list) -> list:
    return [c for c in hand if is_treasure(state, c)]


def _buy_restriction(state: GameState, name: str) -> Optional[str]:
    """Why ``name`` cannot be bought right now even though it is affordable (Contraband, Grand Market), or None."""
    if name in state.banned:
        return f"{name} was named by Contraband: it cannot be bought this turn."
    check = get_card(name).can_buy_fn
    return check(state) if check is not None else None


def _validate_choice(decision: Decision, action: Choose) -> Optional[str]:
    n = len(action.selection)
    if not decision.min_choices <= n <= decision.max_choices:
        if decision.min_choices == decision.max_choices:
            return f"Choose exactly {decision.min_choices}."
        return f"Choose between {decision.min_choices} and {decision.max_choices}."
    unavailable = Counter(action.selection) - Counter(decision.options)
    if unavailable:
        names = ", ".join(sorted(unavailable.elements()))
        return f"Not available to choose: {names}."
    return None


def _legal_choices(decision: Decision) -> list:
    """All distinct selections (as multisets). Can be large for big optional
    choices (2^n for n cards); fine for a hand, so UIs may prefer validate()."""
    counts = sorted(Counter(decision.options).items())
    result = []
    for size in range(decision.min_choices, decision.max_choices + 1):
        for combo in _multisets(counts, size):
            result.append(Choose(combo))
    return result


def _multisets(items: list, size: int):
    """Every distinct selection of ``size`` cards from ``items`` (a sorted list of (name, copies)), in the order
    ``itertools.combinations`` would give for the sorted options, but without enumerating duplicates."""
    if size == 0:
        yield ()
        return
    for index, (name, copies) in enumerate(items):
        rest = items[index + 1:]
        for take in range(min(copies, size), 0, -1):
            for tail in _multisets(rest, size - take):
                yield (name,) * take + tail
