"""The Game: owns a GameState and is the only thing that mutates it.

    game.apply(player, action)   # validated, then executed
    game.legal_actions(player)   # what that player may do right now
"""

from __future__ import annotations

import inspect
from typing import Optional

from ..cards import CardType, get_card
from . import constants as _constants
from . import zones
from .actions import (
    Action,
    Buy,
    Choose,
    EndPhase,
    PlayAction,
    PlayAllTreasures,
    PlayTreasure,
    Resign,
)

try:
    from .actions import Cheat, EndGame
except ImportError:
    Cheat = None
    EndGame = None

try:
    from .actions import SpendCoffer
except ImportError:
    SpendCoffer = None

try:
    from .cardtypes import is_treasure
except ImportError:
    def is_treasure(state: "GameState", card: str) -> bool:
        return get_card(card).is_type(CardType.TREASURE)

from .costs import card_cost
from .effects import EffectContext, fire_triggers
from .rules import IllegalActionError, acting_player, is_game_over, legal_actions, validate
from .scoring import determine_winners, final_scores
from .state import GameState, GameStatus, PendingEffect, Phase

HAND_SIZE = getattr(_constants, "HAND_SIZE", 5)
CHEAT_AMOUNT = getattr(_constants, "CHEAT_AMOUNT", 10)
EXODIA_PIECES = getattr(
    _constants,
    "EXODIA_PIECES",
    (
        "Exodia the Forbidden One",
        "Left Arm of the Forbidden One",
        "Right Arm of the Forbidden One",
        "Left Leg of the Forbidden One",
        "Right Leg of the Forbidden One",
    ),
)


class Game:
    def __init__(self, state: GameState, config=None) -> None:
        self.state = state
        self.config = config
        self.history: list = []
        self.history_turns: list = []

    @property
    def acting_player(self) -> int:
        return acting_player(self.state)

    def legal_actions(self, player: Optional[int] = None) -> list:
        return legal_actions(self.state, player)

    def validate(self, player: int, action: Action) -> Optional[str]:
        return validate(self.state, player, action)

    def clone(self) -> "Game":
        from .setup import replay
        return replay(self.config, self.history)

    def apply(self, player: int, action: Action) -> None:
        error = validate(self.state, player, action)
        if error is not None:
            raise IllegalActionError(error)

        turn = self.state.turn_number
        owner = self.state.current_player
        if isinstance(action, PlayAction):
            self._play_action(owner, action.card)
        elif isinstance(action, PlayTreasure):
            self._play_treasure(owner, action.card)
        elif isinstance(action, PlayAllTreasures):
            for card in [c for c in self.state.players[owner].hand if is_treasure(self.state, c)]:
                self._play_treasure(owner, card)
                if self.state.pending is not None:
                    break
        elif isinstance(action, Buy):
            self._buy(owner, action.card)
        elif SpendCoffer is not None and isinstance(action, SpendCoffer):
            self._spend_coffer(owner, getattr(action, "amount", getattr(action, "count", 1)) or 1)
        elif isinstance(action, EndPhase):
            self._end_phase(owner)
        elif isinstance(action, Choose):
            self._choose(action)
        elif isinstance(action, Resign):
            self._resign(player)
        elif EndGame is not None and isinstance(action, EndGame):
            self._end_early(player)
        elif Cheat is not None and isinstance(action, Cheat):
            self._cheat(player, action.kind)
        else:
            raise IllegalActionError("Unknown action.")

        self._settle()
        self.history.append((player, action))
        self.history_turns.append(turn)
        self._check_exodia()

    def _check_exodia(self) -> None:
        s = self.state
        if s.status is not GameStatus.ACTIVE:
            return
        for i, p in enumerate(s.players):
            if all(piece in p.hand for piece in EXODIA_PIECES):
                s.end_reason = f"{p.name} is holding all five pieces of Exodia!"
                s.log.append(f"EXODIA! {p.name} wins instantly!", "special", 0)
                self._finish(winners=[i])
                return

    def _play_action(self, player: int, card: str) -> None:
        s = self.state
        me = s.players[player]
        me.hand.remove(card)
        me.in_play.append(card)
        s.actions -= 1
        s.plays_this_turn += 1
        s.log.append(f"{me.name} plays {card}.", "play")
        result = get_card(card).on_play(EffectContext(s, player, card))
        if inspect.isgenerator(result):
            self._advance(result, None, card)

    def _play_treasure(self, player: int, card: str) -> None:
        s = self.state
        me = s.players[player]
        me.hand.remove(card)
        me.in_play.append(card)
        self._advance(EffectContext(s, player, card).resolve_treasure(card), None, card)

    def _spend_coffer(self, player: int, amount: int = 1) -> None:
        s = self.state
        me = s.players[player]
        me.coffers = max(0, getattr(me, "coffers", 0) - amount)
        if hasattr(me, "coin_tokens"):
            me.coin_tokens = me.coffers
        s.coins += amount
        s.log.append(f"{me.name} spends {amount} Coffer(s) (+${amount}).", "play")

    def _buy(self, player: int, card: str) -> None:
        s = self.state
        s.coins -= card_cost(s, card)
        s.potions -= get_card(card).potion_cost
        s.buys -= 1
        s.buying = True
        zones.gain_card(s, player, card)
        s.buying = False
        taker = zones.beneficiary(s, player)
        s.players[taker].bought.append(card)
        if get_card(card).is_type(CardType.VICTORY):
            s.bought_victory = True
        if taker != player:
            s.log.append(f"{s.players[player].name} buys {card} for {s.players[taker].name} (Possession).", "buy")
        else:
            s.log.append(f"{s.players[player].name} buys {card}.", "buy")
        for _ in range(s.embargo.get(card, 0)):
            if zones.gain_card(s, player, "Curse"):
                s.log.append(f"{s.players[zones.beneficiary(s, player)].name} gains a Curse (Embargo).", "gain", 1)

    def _cheat(self, player: int, kind: str) -> None:
        s = self.state
        if kind == "coins":
            s.coins += CHEAT_AMOUNT
        elif kind == "actions":
            s.actions += CHEAT_AMOUNT
        else:
            s.buys += CHEAT_AMOUNT
        s.log.append(f"{s.players[player].name} cheats: +{CHEAT_AMOUNT} {kind}!", "cheat")

    def _resign(self, player: int) -> None:
        s = self.state
        s.resigned.append(player)
        s.end_reason = f"{s.players[player].name} resigned."
        s.log.append(f"{s.players[player].name} resigns.", "end")
        self._finish()

    def _end_early(self, player: int) -> None:
        s = self.state
        s.end_reason = f"{s.players[player].name} ended the game early."
        s.log.append(f"{s.players[player].name} ends the game early.", "end")
        self._finish()

    def _fire(self, event: str, player: int, *args) -> None:
        fire_triggers(self.state, event, player, *args)

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
        try:
            decision = generator.send(answer)
        except StopIteration:
            current = self.state.pending
            if current is None or current.generator is generator:
                self.state.pending = None
            return
        if not 0 <= decision.player < len(self.state.players):
            raise ValueError(f"{source} asked an unknown player.")
        self.state.pending = PendingEffect(decision, generator, source)

    def _settle(self) -> None:
        s = self.state
        if s.status is not GameStatus.ACTIVE:
            s.gain_events.clear()
            return
        if s.pending is None and s.gain_events:
            self._advance(self._gain_steps(), None, "Gain")

    def _gain_steps(self):
        s = self.state
        while s.gain_events:
            event = s.gain_events.pop(0)
            player = event.player
            me = s.players[player]
            own = get_card(event.card).on_gain
            if own is not None:
                result = own(EffectContext(s, player, event.card), event)
                if inspect.isgenerator(result):
                    yield from result
            for name in sorted(set(me.in_play)):
                hook = get_card(name).on_gain_in_play
                if hook is None:
                    continue
                for _ in range(me.in_play.count(name)):
                    result = hook(EffectContext(s, player, name), event)
                    if inspect.isgenerator(result):
                        yield from result
            for name in sorted(set(me.hand)):
                hook = get_card(name).on_gain_reaction
                if hook is None or name not in me.hand:
                    continue
                result = hook(EffectContext(s, player, name), event)
                if inspect.isgenerator(result):
                    yield from result

    def _begin_turn(self, player: int) -> None:
        self._advance(self._begin_turn_steps(player), None, "Start of turn")

    def _begin_turn_steps(self, player: int):
        s = self.state
        me = s.players[player]
        entries, me.durations = me.durations, []
        for entry in entries:
            if entry.handler is not None:
                entry.handler(EffectContext(s, player, entry.source), entry)
        while True:
            options = tuple(sorted({c for c in me.hand if getattr(get_card(c), "play_at_turn_start", False)}))
            if not options:
                return
            ctx = EffectContext(s, player, options[0])
            chosen = yield ctx.choose("At the start of your turn you may play a card from your hand.", options, 0, 1)
            if not chosen:
                return
            card = chosen[0]
            me.hand.remove(card)
            me.in_play.append(card)
            s.plays_this_turn += 1
            s.log.append(f"{me.name} plays {card} at the start of their turn.", "play")
            result = get_card(card).on_play(EffectContext(s, player, card))
            if inspect.isgenerator(result):
                yield from result

    def _cleanup(self, player: int) -> None:
        self._advance(self._cleanup_steps(player), None, "Cleanup")

    def _cleanup_steps(self, player: int):
        s = self.state
        me = s.players[player]
        for card in sorted((c for c in me.in_play if get_card(c).on_cleanup is not None),
                           key=lambda c: (get_card(c).cleanup_order, c)):
            if card not in me.in_play:
                continue
            result = get_card(card).on_cleanup(EffectContext(s, player, card))
            if inspect.isgenerator(result):
                yield from result
        outpost = s.outpost_flag and not s.outpost_turn and s.possessor is None
        s.outpost_turn = False
        s.outpost_flag = False
        if outpost:
            s.outpost_next = True
        returned = zones.return_possession_cards(s)
        if returned:
            s.log.append(f"{me.name}'s {returned} card(s) return to discard.", "reveal")
        staying, remaining = [], list(me.in_play)
        for entry in me.durations:
            for name in entry.cards:
                if name in remaining:
                    remaining.remove(name)
                    staying.append(name)
        me.discard.extend(me.hand)
        me.discard.extend(remaining)
        me.hand.clear()
        me.in_play[:] = staying
        zones.draw_cards(s, player, 3 if outpost else HAND_SIZE)
        me.last_gained, me.gained_turn = me.gained_turn, []
        s.bought_victory = False
        me.turns_taken += 1
        s.actions, s.buys, s.coins = 1, 1, 0
        s.potions = 0
        s.triggers.clear()
        s.buy_locked = False
        s.cost_reduction = 0
        s.plays_this_turn = 0
        s.buying = False
        s.phase = Phase.ACTION
        s.log.append(f"{me.name} ends their turn.", "phase")

        if is_game_over(s):
            self._finish()
        else:
            self._after_turn(player)

    def _after_turn(self, player: int) -> None:
        s = self.state
        if s.possessor is not None:
            possessor = s.possessor
            s.possessor = None
            if s.extra_turns > 0 and s.extra_owner == possessor:
                self._start_possession(possessor)
            else:
                s.extra_turns = 0
                s.extra_owner = None
                self._next_turn(advance=False)
        elif s.outpost_next:
            s.outpost_next = False
            s.outpost_turn = True
            self._next_turn(advance=False)
        elif s.extra_turns > 0:
            self._start_possession(player)
        else:
            self._next_turn()

    def _start_possession(self, possessor: int) -> None:
        s = self.state
        s.extra_turns -= 1
        s.possessor = possessor
        s.current_player = (possessor + 1) % len(s.players)
        s.turn_number += 1
        s.log.append(f"Turn {s.turn_number} - {s.players[s.current_player].name} (possessed)", "turn")
        self._begin_turn(s.current_player)

    def _next_turn(self, advance: bool = True) -> None:
        s = self.state
        for _ in range(len(s.players) * 3):
            if advance:
                s.current_player = (s.current_player + 1) % len(s.players)
            advance = True
            s.turn_number += 1
            nxt = s.players[s.current_player]
            if getattr(nxt, "skips", 0) > 0:
                nxt.skips -= 1
                nxt.skip_protected = True
                nxt.turns_taken += 1
                s.log.append(f"{nxt.name}'s turn is skipped.", "skip")
                continue
            nxt.skip_protected = False
            s.log.append(f"Turn {s.turn_number} - {nxt.name}", "turn")
            self._begin_turn(s.current_player)
            return

    def _finish(self, winners=None) -> None:
        s = self.state
        zones.return_possession_cards(s)
        s.gain_events.clear()
        s.status = GameStatus.FINISHED
        s.pending = None
        s.winners = list(winners) if winners is not None else determine_winners(s)
        scores = final_scores(s)
        summary = ", ".join(f"{p.name}: {v} VP" for p, v in zip(s.players, scores))
        s.log.append(f"Game over. {summary}.", "end")


# --- Expansion Compatibility Exports ---
try:
    from ..cards.hinterlands import (
        HINTERLANDS_CARDS,
        _card_cost as hinterlands_card_cost,
        _discard_card as hinterlands_discard_card,
        _gain_card as hinterlands_gain_card,
        _trash_card as hinterlands_trash_card,
    )
except Exception:
    pass

try:
    from ..cards.dark_ages import _gain_card as dark_ages_gain_card
except Exception:
    pass

try:
    from ..cards.guilds import (
        _add_coffers as add_coffers,
        _gain_card as guilds_gain_card,
        _spend_coffers as spend_coffers,
    )
except Exception:
    pass