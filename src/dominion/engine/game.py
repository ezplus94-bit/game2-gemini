"""The Game: owns a GameState and is the only thing that mutates it.

    game.apply(player, action)   # validated, then executed
    game.legal_actions(player)   # what that player may do right now

Cards are resolved here. If an effect needs an answer from a player it yields
a Decision; the engine parks the suspended effect in ``state.pending`` and the
next legal action is a ``Choose``.

Possession: ``player`` in ``apply`` is always the player who *submits* the action. During a Possession turn that
is the possessor, while the cards played are the possessed player's (``state.current_player``).
"""

from __future__ import annotations

import inspect
from typing import Optional

from ..cards import CardType, get_card
from . import zones
from .actions import (
    Action, Buy, Cheat, Choose, EndGame, EndPhase, PlayAction, PlayAllTreasures, PlayTreasure, Resign,
)
from .constants import CHEAT_AMOUNT, EXODIA_PIECES, HAND_SIZE
from .costs import card_cost
from .effects import EffectContext
from .rules import IllegalActionError, acting_player, is_game_over, legal_actions, validate
from .scoring import determine_winners, final_scores
from .state import GameState, GameStatus, PendingEffect, Phase


class Game:
    def __init__(self, state: GameState, config=None) -> None:
        self.state = state
        self.config = config        # resolved GameConfig (seed + kingdom filled in)
        self.history: list = []     # [(player, action), ...] - enough to replay
        self.history_turns: list = []   # turn number each action was taken in (same length)

    # ------------------------------------------------------------ queries
    @property
    def acting_player(self) -> int:
        return acting_player(self.state)

    def legal_actions(self, player: Optional[int] = None) -> list:
        return legal_actions(self.state, player)

    def validate(self, player: int, action: Action) -> Optional[str]:
        return validate(self.state, player, action)

    def clone(self) -> "Game":
        """Independent copy, made by replaying history (the game is
        deterministic). Needed because suspended effects are live generators."""
        from .setup import replay
        return replay(self.config, self.history)

    # ------------------------------------------------------------ mutation
    def apply(self, player: int, action: Action) -> None:
        error = validate(self.state, player, action)
        if error is not None:
            raise IllegalActionError(error)

        turn = self.state.turn_number
        owner = self.state.current_player        # whose cards are played (the possessed player's under Possession)
        if isinstance(action, PlayAction):
            self._play_action(owner, action.card)
        elif isinstance(action, PlayTreasure):
            self._play_treasure(owner, action.card)
        elif isinstance(action, PlayAllTreasures):
            for card in [c for c in self.state.players[owner].hand
                         if get_card(c).is_type(CardType.TREASURE)]:
                self._play_treasure(owner, card)
        elif isinstance(action, Buy):
            self._buy(owner, action.card)
        elif isinstance(action, EndPhase):
            self._end_phase(owner)
        elif isinstance(action, Choose):
            self._choose(action)
        elif isinstance(action, Resign):
            self._resign(player)
        elif isinstance(action, EndGame):
            self._end_early(player)
        elif isinstance(action, Cheat):
            self._cheat(player, action.kind)
        else:  # pragma: no cover - validate() already rejects unknown actions
            raise IllegalActionError("Unknown action.")

        self.history.append((player, action))
        self.history_turns.append(turn)
        self._check_exodia()

    def _check_exodia(self) -> None:
        """All five Exodia pieces in one hand win the game on the spot (checked after every action)."""
        s = self.state
        if s.status is not GameStatus.ACTIVE:
            return
        for i, p in enumerate(s.players):
            if all(piece in p.hand for piece in EXODIA_PIECES):
                s.end_reason = f"{p.name} is holding all five pieces of Exodia the Forbidden One!"
                s.log.append(f"EXODIA! {p.name} holds all five pieces in their hand and wins instantly!", "special", 0)
                self._finish(winners=[i])
                return

    # ------------------------------------------------------------ handlers
    def _play_action(self, player: int, card: str) -> None:
        s = self.state
        me = s.players[player]
        me.hand.remove(card)
        me.in_play.append(card)
        s.actions -= 1
        s.plays_this_turn += 1
        s.log.append(f"{me.name} plays {card}.", "play")
        if get_card(card).on_next_turn is not None and card != "Tactician":
            me.duration_effects.append(card)
        result = get_card(card).on_play(EffectContext(s, player, card))
        if inspect.isgenerator(result):
            self._advance(result, None, card)

    def _play_treasure(self, player: int, card: str) -> None:
        s = self.state
        me = s.players[player]
        me.hand.remove(card)
        me.in_play.append(card)
        definition = get_card(card)
        value = definition.coins_fn(s, player) if definition.coins_fn is not None else definition.coins
        potions = definition.potions
        note = ""
        if s.midas and value < 3:
            value, potions, note = 3, 0, " as Gold"         # Midas Touch: everything turns to gold
        s.coins += value
        s.potions += potions
        extra = f", +{potions} Potion" if potions else ""
        s.log.append(f"{me.name} plays {card}{note} (+${value}{extra})." if potions
                     else f"{me.name} plays {card}{note} (+${value}).", "treasure")
        self._fire("treasure_played", player, card)

    def _buy(self, player: int, card: str) -> None:
        s = self.state
        s.coins -= card_cost(s, card)
        s.potions -= get_card(card).potion_cost
        s.buys -= 1
        s.bought_this_turn.append(card)
        zones.gain_card(s, player, card)
        taker = zones.beneficiary(s, player)
        s.players[taker].bought.append(card)
        if taker != player:                                   # Possession: the controlling player gets what is bought
            s.log.append(f"{s.players[player].name} buys {card} for {s.players[taker].name} (Possession).", "buy")
        else:
            s.log.append(f"{s.players[player].name} buys {card}.", "buy")
        for _ in range(s.embargo_tokens.get(card, 0)):
            if zones.gain_card(s, player, "Curse"):
                s.log.append(f"{s.players[taker].name} gains a Curse (Embargo on {card}).", "trash", 1)

    def _cheat(self, player: int, kind: str) -> None:
        s = self.state
        if kind == "coins":
            s.coins += CHEAT_AMOUNT
        elif kind == "actions":
            s.actions += CHEAT_AMOUNT
        else:
            s.buys += CHEAT_AMOUNT
        s.log.append(f"{s.players[player].name} uses a cheat code: +{CHEAT_AMOUNT} {kind}!", "cheat")

    def _resign(self, player: int) -> None:
        s = self.state
        s.resigned.append(player)
        s.end_reason = f"{s.players[player].name} resigned."
        s.log.append(f"{s.players[player].name} resigns.", "end")
        self._finish()

    def _end_early(self, player: int) -> None:
        s = self.state
        s.end_reason = f"{s.players[player].name} ended the game early."
        s.log.append(f"{s.players[player].name} ends the game early; the current scores count.", "end")
        self._finish()

    def _fire(self, event: str, player: int, *args) -> None:
        s = self.state
        for trigger in list(s.triggers):
            if trigger.event == event and trigger.owner == player:
                trigger.handler(EffectContext(s, player, trigger.source), trigger, *args)

    def _end_phase(self, player: int) -> None:
        s = self.state
        if s.phase is Phase.ACTION:
            s.phase = Phase.BUY
            s.log.append(f"{s.players[player].name} moves to the Buy phase.", "phase")
        else:
            self._cleanup(player)

    def _choose(self, action: Choose) -> None:
        pending = self.state.pending
        self.state.log.append(
            f"{self.state.players[pending.decision.player].name} chooses "
            f"{', '.join(action.selection) if action.selection else 'nothing'}.",
            "choice", 1,
        )
        self._advance(pending.generator, action.selection, pending.source)

    def _advance(self, generator, answer, source: str) -> None:
        """Run a suspended effect until it finishes or asks the next question."""
        try:
            decision = generator.send(answer)
        except StopIteration:
            self.state.pending = None
            return
        if not 0 <= decision.player < len(self.state.players):
            raise ValueError(f"{source} asked an unknown player.")
        self.state.pending = PendingEffect(decision, generator, source)

    def _cleanup(self, player: int) -> None:
        """End of turn. It runs as a generator so a card may ask its owner something first (Herbalist, Alchemist);
        with nothing to ask it simply runs to the end in one go."""
        self._advance(self._cleanup_steps(player), None, "Cleanup")

    def _cleanup_steps(self, player: int):
        s = self.state
        me = s.players[player]
        # "When you discard this from play" effects, e.g. Alchemist (needs a Potion in play) before Herbalist.
        for card in sorted((c for c in me.in_play if get_card(c).on_cleanup is not None),
                           key=lambda c: (get_card(c).cleanup_order, c)):
            if card not in me.in_play:
                continue
            result = get_card(card).on_cleanup(EffectContext(s, player, card))
            if inspect.isgenerator(result):
                yield from result
        returned = zones.return_possession_cards(s)
        if returned:
            s.log.append(f"{me.name}'s {returned} trashed card(s) return to their discard pile.", "reveal")
        me.discard.extend(me.hand)
        still_active = []
        resolved = list(me.resolved_durations)
        me.resolved_durations.clear()
        for card in me.in_play:
            if card in resolved:
                resolved.remove(card)
                me.discard.append(card)
            elif get_card(card).is_type(CardType.DURATION):
                if card == "Tactician" and me.tactician_active == 0:
                    me.discard.append(card)
                elif card == "Outpost" and s.outpost_turn:
                    me.discard.append(card)
                else:
                    still_active.append(card)
            else:
                me.discard.append(card)
        me.hand.clear()
        me.in_play.clear()
        me.duration.extend(still_active)
        draw_count = 3 if (s.outpost_queued and not s.outpost_turn) else HAND_SIZE
        zones.draw_cards(s, player, draw_count)
        me.last_turn_gained = list(me.gained_this_turn)
        me.gained_this_turn.clear()
        me.turns_taken += 1
        s.actions, s.buys, s.coins = 1, 1, 0
        s.potions = 0
        s.bought_this_turn.clear()
        s.triggers.clear()
        s.buy_locked = False
        s.cost_reduction = 0
        s.plays_this_turn = 0
        s.midas = False
        if me.blind > 0:
            me.blind -= 1
            if me.blind == 0:
                s.log.append(f"{me.name} can see again.", "reveal")
        s.phase = Phase.ACTION
        if me.protection_fresh:                 # the turn protection was gained does not count
            me.protection_fresh = False
        elif me.protection > 0:
            me.protection -= 1
            if me.protection == 0:
                s.log.append(f"{me.name}'s protection runs out.", "reveal")
        s.log.append(f"{me.name} ends their turn.", "phase")

        if is_game_over(s):
            self._finish()
        else:
            self._after_turn(player)

    def _resolve_start_of_turn_durations(self, player: int) -> None:
        s = self.state
        me = s.players[player]
        active_cards = list(me.duration)
        me.duration.clear()
        for card in active_cards:
            me.in_play.append(card)
            me.resolved_durations.append(card)
        effects = list(me.duration_effects)
        me.duration_effects.clear()
        for card in effects:
            fn = get_card(card).on_next_turn
            if fn is not None:
                s.log.append(f"{me.name}'s {card} resolves.", "play", 1)
                res = fn(EffectContext(s, player, card))
                if inspect.isgenerator(res):
                    self._advance(res, None, card)

    def _after_turn(self, player: int) -> None:
        """Decide whose turn comes next, keeping Outpost and Possession's extra turns in mind."""
        s = self.state
        if s.outpost_queued and not s.outpost_turn:
            s.outpost_queued = False
            s.outpost_turn = True
            s.turn_number += 1
            s.log.append(f"Turn {s.turn_number} - {s.players[player].name} (Outpost)", "turn")
            self._resolve_start_of_turn_durations(player)
            return
        s.outpost_turn = False
        s.outpost_queued = False
        if s.possessor is not None:                          # a possessed turn just ended
            possessor = s.possessor
            s.possessor = None
            if s.extra_turns > 0 and s.extra_owner == possessor:
                self._start_possession(possessor)            # another Possession was played: another extra turn
            else:
                s.extra_turns = 0
                s.extra_owner = None
                self._next_turn(advance=False)               # the possessed player now takes their own, normal turn
        elif s.extra_turns > 0:
            self._start_possession(player)
        else:
            self._next_turn()

    def _start_possession(self, possessor: int) -> None:
        """The player to the possessor's left takes an extra turn that the possessor controls."""
        s = self.state
        s.extra_turns -= 1
        s.possessor = possessor
        s.current_player = (possessor + 1) % len(s.players)
        s.turn_number += 1
        s.log.append(
            f"Turn {s.turn_number} - {s.players[s.current_player].name} (possessed by {s.players[possessor].name})",
            "turn",
        )
        self._resolve_start_of_turn_durations(s.current_player)

    def _next_turn(self, advance: bool = True) -> None:
        """Pass the turn, consuming skipped turns (a skipped turn still counts as taken).
        With ``advance=False`` the current player keeps the turn (their own turn after a Possession turn)."""
        s = self.state
        for _ in range(len(s.players) * 3):                 # bounded: cannot loop forever
            if advance:
                s.current_player = (s.current_player + 1) % len(s.players)
            advance = True
            s.turn_number += 1
            nxt = s.players[s.current_player]
            for pile in [p for p, owner in s.walls.items() if owner == s.current_player]:
                del s.walls[pile]                        # Fortnite walls come down when their builder's next turn starts
                s.log.append(f"The wall around {pile} comes down.", "reveal")
            if nxt.skips > 0:
                nxt.skips -= 1
                nxt.skip_protected = True
                nxt.turns_taken += 1
                s.log.append(f"{nxt.name}'s turn is skipped.", "skip")
                continue
            nxt.skip_protected = False
            s.log.append(f"Turn {s.turn_number} - {nxt.name}", "turn")
            if nxt.bonus_coins:
                s.coins += nxt.bonus_coins
                s.log.append(f"{nxt.name} receives ${nxt.bonus_coins} from Rosebud.", "gain", 1)
                nxt.bonus_coins = 0
            self._resolve_start_of_turn_durations(s.current_player)
            return

    def _finish(self, winners=None) -> None:
        s = self.state
        zones.return_possession_cards(s)
        s.status = GameStatus.FINISHED
        s.pending = None                 # an unanswered question dies with the game
        s.winners = list(winners) if winners is not None else determine_winners(s)
        scores = final_scores(s)
        summary = ", ".join(f"{p.name}: {v} VP" for p, v in zip(s.players, scores))
        s.log.append(f"Game over. {summary}.", "end")
        s.log.append("Winner(s): " + ", ".join(s.players[i].name for i in s.winners), "end")
