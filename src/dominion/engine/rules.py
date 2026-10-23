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
    Action, Buy, Cheat, Choose, Decision, EndGame, EndPhase, PlayAction, PlayAllTreasures, PlayTreasure, Resign, SpendCoffer,
)
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
        if not get_card(action.card).is_type(CardType.TREASURE):
            return f"{action.card} is not a Treasure."
        return None

    if isinstance(action, PlayAllTreasures):
        if state.phase is not Phase.BUY:
            return "Treasures can only be played during the Buy phase."
        if not _treasures_in_hand(me.hand):
            return "You have no Treasures in hand."
        return None

    if isinstance(action, SpendCoffer):
        if state.phase is not Phase.BUY:
            return "Coffers can only be spent during the Buy phase."
        if me.coffers < 1:
            return "You have no Coffers to spend."
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
        if action.card in state.contraband_banned:
            return f"You cannot buy {action.card} this turn (Contraband)."
        if action.card == "Grand Market" and "Copper" in me.in_play:
            return "You cannot buy Grand Market while you have a Copper in play."
        cost = card_cost(state, action.card)
        if cost > state.coins:
            return f"{action.card} costs ${cost} but you only have ${state.coins}."
        potion_cost = get_card(action.card).potion_cost
        if potion_cost > state.potions:
            return f"{action.card} costs {potion_cost} Potion(s) but you only have {state.potions}."
        return None

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
    treasures = sorted(set(_treasures_in_hand(me.hand)))
    for card in treasures:
        result.append(PlayTreasure(card))
    if treasures:
        result.append(PlayAllTreasures())
    if me.coffers >= 1:
        result.append(SpendCoffer())
    if state.buys >= 1 and not state.buy_locked:
        for name in sorted(state.supply):
            if state.supply[name] > 0 and card_cost(state, name) <= state.coins and not is_walled(state, name, actor) and state.potions >= get_card(name).potion_cost and name not in state.contraband_banned and not (name == "Grand Market" and "Copper" in me.in_play):
                result.append(Buy(name))
    result.append(EndPhase())
    return result


# ------------------------------------------------------------------ helpers
def _treasures_in_hand(hand: list) -> list:
    return [c for c in hand if get_card(c).is_type(CardType.TREASURE)]


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
    seen = set()
    result = []
    options = sorted(decision.options)
    for size in range(decision.min_choices, decision.max_choices + 1):
        for combo in combinations(options, size):
            if combo not in seen:
                seen.add(combo)
                result.append(Choose(combo))
    return result
