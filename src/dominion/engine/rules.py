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
    Action, Buy, BuyEvent, Cheat, Choose, Decision, EndGame, EndPhase, PayDebt, PlayAction, PlayAllTreasures, PlayTreasure,
    Resign, SpendCoffers, SpendVillager,
)
from .cardtypes import is_plain_treasure, is_treasure
from .constants import CHEAT_KINDS
from .costs import card_cost, is_buried, is_walled
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
        if count == 0 and name not in state.catastrophes and name not in state.stack_of     # scarce piles never end the game
    )
    empty += sum(1 for stack in state.stacks.values() if not stack)         # Knights / Ruins count as one pile each
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

    if isinstance(action, SpendCoffers):
        if not 1 <= action.count <= me.coffers:
            return f"You only have {me.coffers} Coffers token(s)."
        return None

    if isinstance(action, SpendVillager):
        if state.no_more_actions:
            return "Snowy Village: you ignore further +Actions this turn."
        if state.phase is not Phase.ACTION:
            return "Villagers can only be spent during the Action phase."
        if not 1 <= action.count <= me.villagers:
            return f"You only have {me.villagers} Villager(s)."
        return None

    if isinstance(action, PayDebt):
        if state.phase is not Phase.BUY:
            return "You can only pay off Debt during the Buy phase."
        if not 1 <= action.count <= me.debt:
            return f"You only owe {me.debt} Debt token(s)."
        if action.count > state.coins:
            return f"You only have ${state.coins} to pay off Debt with."
        return None

    if isinstance(action, PlayAction):
        if state.phase is Phase.NIGHT:                          # Nocturne: only Night cards, and they cost no Action
            if action.card not in me.hand:
                return f"{action.card} is not in your hand."
            if not get_card(action.card).is_type(CardType.NIGHT):
                return f"{action.card} is not a Night card."
            return None
        if state.phase is not Phase.ACTION:
            return "Actions can only be played during the Action phase."
        if state.actions < 1:
            return "You have no Actions left."
        if action.card not in me.hand:
            return f"{action.card} is not in your hand."
        blocked = _play_blocked(state, me, action.card)
        if blocked:
            return blocked
        if not _is_action(me, action.card):
            return f"{action.card} is not an Action card."
        return None

    if isinstance(action, PlayTreasure):
        if state.phase is not Phase.BUY:
            return "Treasures can only be played during the Buy phase."
        if action.card not in me.hand:
            return f"{action.card} is not in your hand."
        if not is_treasure(state, action.card):
            return f"{action.card} is not a Treasure."
        return _play_blocked(state, me, action.card)

    if isinstance(action, PlayAllTreasures):
        if state.phase is not Phase.BUY:
            return "Treasures can only be played during the Buy phase."
        if not _treasures_in_hand(state, me.hand):
            return "You have no Treasures in hand."
        return _play_blocked(state, me, None)

    if isinstance(action, BuyEvent):
        if state.phase is not Phase.BUY:
            return "You can only buy Events during the Buy phase."
        if action.card not in state.events:
            return f"{action.card} is not an Event in this game."
        event = get_card(action.card)
        if me.debt > 0:
            return f"You owe {me.debt} Debt token(s): pay it off before buying anything."
        if state.buys < 1:
            return "You have no Buys left."
        if event.cost > state.coins:
            return f"{action.card} costs ${event.cost} but you only have ${state.coins}."
        if event.once_per_turn and state.turn_counts.get("event:" + action.card):
            return f"{action.card} can only be bought once per turn."
        if event.can_buy_fn is not None:
            reason = event.can_buy_fn(state)
            if reason:
                return reason
        if event.is_type(CardType.PROJECT) and action.card in me.projects:
            return f"You already have a cube on {action.card}."
        if event.is_type(CardType.PROJECT) and len(me.projects) >= 2:
            return "You only have two cubes: no more Projects."
        return None

    if isinstance(action, Buy):
        if state.phase is not Phase.BUY:
            return "You can only buy during the Buy phase."
        if state.buy_locked:
            return "You may not buy cards this turn."
        if me.debt > 0:
            return f"You owe {me.debt} Debt token(s): pay it off before buying anything."
        if state.buys < 1:
            return "You have no Buys left."
        if action.card not in state.supply:
            return f"{action.card} is not in this game's supply."
        if state.supply[action.card] <= 0:
            return f"The {action.card} pile is empty."
        if is_walled(state, action.card, player):
            return f"{state.players[state.walls[action.card]].name} has walled off the {action.card} pile."
        if is_buried(state, action.card):
            return f"{action.card} is not on top of its pile."
        cost = card_cost(state, action.card)
        if action.overpay < 0 or (action.overpay and not get_card(action.card).overpay):
            return f"{action.card} cannot be overpaid for."
        if cost + action.overpay > state.coins and not _fair_by_trashing(action.card, me):
            if action.overpay:
                return f"{action.card} costs ${cost} plus an overpayment of ${action.overpay}, but you only have ${state.coins}."
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

    if state.phase is Phase.NIGHT:                               # Nocturne: any number of Night cards, then Clean-up
        for card in sorted(set(me.hand)):
            if get_card(card).is_type(CardType.NIGHT):
                result.append(PlayAction(card))
        result.append(EndPhase())
        return result

    if state.phase is Phase.ACTION:
        if state.actions >= 1:
            for card in sorted(set(me.hand)):
                if _is_action(me, card) and _play_blocked(state, me, card) is None:
                    result.append(PlayAction(card))
        if me.villagers > 0 and not state.no_more_actions:      # Renaissance: Villagers give Actions in the Action phase
            result.append(SpendVillager(1))
            if me.villagers > 1:
                result.append(SpendVillager(me.villagers))
        result.append(EndPhase())
        return result

    # Buy phase
    treasures = sorted(set(_treasures_in_hand(state, me.hand))) if _play_blocked(state, me, None) is None else []
    for card in treasures:
        result.append(PlayTreasure(card))
    if any(is_plain_treasure(state, c) for c in treasures):
        result.append(PlayAllTreasures())
    if me.coffers > 0:
        result.append(SpendCoffers(1))
        if me.coffers > 1:
            result.append(SpendCoffers(me.coffers))
    if me.debt > 0 and state.coins > 0:                          # Empires: Debt is paid off with $, one token per $
        result.append(PayDebt(1))
        if min(me.debt, state.coins) > 1:
            result.append(PayDebt(min(me.debt, state.coins)))
    if state.buys >= 1 and me.debt == 0:
        for name in state.events:                               # Adventures: Events are bought with a Buy, even when cards cannot be bought
            if validate(state, actor, BuyEvent(name)) is None:
                result.append(BuyEvent(name))
    if state.buys >= 1 and not state.buy_locked and me.debt == 0:
        for name in sorted(state.supply):
            if state.supply[name] > 0 and (card_cost(state, name) <= state.coins or _fair_by_trashing(name, me)) and not is_walled(state, name, actor) and not is_buried(state, name) and state.potions >= get_card(name).potion_cost and _buy_restriction(state, name) is None:
                result.append(Buy(name))
                if get_card(name).overpay:                       # Guilds: paying extra on purpose
                    spare = state.coins - card_cost(state, name)
                    result.extend(Buy(name, extra) for extra in range(1, min(spare, MAX_OVERPAY_OPTIONS) + 1))
    result.append(EndPhase())
    return result


MAX_OVERPAY_OPTIONS = 12      # at most this many different overpayments are offered per card in the list of legal actions


# ------------------------------------------------------------------ helpers
def _is_action(me, card: str) -> bool:
    """An Action card, or an Estate that Inheritance has turned into an Action for this player."""
    return get_card(card).is_type(CardType.ACTION) or (card == "Estate" and me.inherited is not None)


def _play_blocked(state: GameState, me, card) -> Optional[str]:
    """Allies: why this card cannot be played from the hand right now. Voyage turns allow only 3 cards from the hand; a player under a
    Warlord cannot play an Action they already have 2 or more copies of in play."""
    if state.voyage_turn and state.hand_plays >= 3:
        return "Voyage: you can only play 3 cards from your hand this turn."
    if card is not None and state.warlords and any(t == state.current_player for _, t in state.warlords) \
            and get_card(card).is_type(CardType.ACTION) and me.in_play.count(card) >= 2:
        return f"Warlord: you cannot play {card}, you already have 2 or more copies of it in play."
    return None


def _fair_by_trashing(name: str, me) -> bool:
    """Menagerie, Animal Fair: it can be bought without paying its cost by trashing an Action card from the hand."""
    return name == "Animal Fair" and any(get_card(c).is_type(CardType.ACTION) for c in me.hand)


def _treasures_in_hand(state: GameState, hand: list) -> list:
    return [c for c in hand if is_treasure(state, c)]


def _buy_restriction(state: GameState, name: str) -> Optional[str]:
    """Why ``name`` cannot be bought right now even though it is affordable (Contraband, Grand Market), or None."""
    if name in state.banned:
        return f"{name} was named by Contraband: it cannot be bought this turn."
    if state.deluded_turn and get_card(name).is_type(CardType.ACTION):
        return f"You are Deluded: you cannot buy Action cards this turn."
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
