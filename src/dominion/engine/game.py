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
from . import allies, landmarks, menagerie, nocturne, plunder, renaissance, risingsun, zones
from .cardtypes import is_plain_treasure, is_treasure, treasure_coins
from .actions import (
    Action, Buy, BuyEvent, Cheat, Choose, EndGame, EndPhase, PayDebt, PlayAction, PlayAllTreasures, PlayTreasure, Resign, SpendCoffers, SpendVillager,
)
from .constants import CHEAT_AMOUNT, EXODIA_PIECES, HAND_SIZE
from .costs import card_cost, spend_buy
from .effects import EffectContext, ally_after_play, apply_play_bonuses, call_steps, citadel_check, fire_triggers, play_effect, urchin_steps
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
            self._play_action(owner, action.card, action.from_deck)
        elif isinstance(action, PlayTreasure):
            self._play_treasure(owner, action.card)
        elif isinstance(action, PlayAllTreasures):
            plain = [c for c in self.state.players[owner].hand if is_plain_treasure(self.state, c)]
            if self.state.voyage_turn:                         # Voyage: only as many as the turn still allows, the most valuable first
                plain = sorted(plain, key=lambda c: -treasure_coins(self.state, c))[:max(0, 3 - self.state.hand_plays)]
            for card in plain:
                self._play_treasure(owner, card)
                if self.state.pending is not None:         # a Treasure asked something: the rest wait for another "play all"
                    break
        elif isinstance(action, Buy):
            if action.card == "Animal Fair" and any(get_card(c).is_type(CardType.ACTION) for c in self.state.players[owner].hand):
                self._advance(self._buy_fair_steps(owner), None, "Animal Fair")      # Menagerie: may be bought by trashing an Action
            else:
                self._buy(owner, action.card, action.overpay)
        elif isinstance(action, BuyEvent):
            self._buy_event(owner, action.card)
        elif isinstance(action, SpendCoffers):
            self._spend_coffers(owner, action.count)
        elif isinstance(action, SpendVillager):
            self._spend_villager(owner, action.count)
        elif isinstance(action, PayDebt):
            self._pay_debt(owner, action.count)
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

        self._settle()
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
    def _play_action(self, player: int, card: str, from_deck: bool = False) -> None:
        s = self.state
        me = s.players[player]
        (me.deck if from_deck else me.hand).remove(card)         # (a Shadow card can come from anywhere in the deck)
        me.in_play.append(card)
        s.turn_counts["any_play"] = 1                            # Plunder: a Treasure is no longer the first card played (Landing Party)
        night = s.phase is Phase.NIGHT                           # Nocturne: Night cards cost no Action; only Actions (Werewolf) count as plays
        if not night:
            s.actions -= 1
            if not from_deck:
                s.hand_plays += 1                                # Voyage counts cards played from the hand
        if not night or get_card(card).is_type(CardType.ACTION):
            s.plays_this_turn += 1
        s.log.append(f"{me.name} plays {card}{' (Night phase)' if night else ''}{' from their deck' if from_deck else ''}.", "play")
        self._advance(self._play_steps(player, card), None, card)

    def _play_steps(self, player: int, card: str):
        """Urchins in play may react to an Attack being played; then the card does what it says."""
        s = self.state
        s.played_log.append(card)
        again = citadel_check(s, player, card)                    # Renaissance: Citadel plays the first Action of the turn again
        snap = plunder.before_play(s)
        yield from urchin_steps(s, player, card)
        apply_play_bonuses(s, player, card)
        on_play = get_card(card).on_play
        if on_play is None and s.players[player].inherited is not None:     # Adventures: an Estate that Inheritance made an Action
            on_play = get_card(s.players[player].inherited).on_play
        yield from play_effect(s, player, card, on_play)           # Kiln, then a Way (Menagerie) or the card's effect (Enchantress may replace it)
        yield from call_steps(s, player, "after_action", card)    # Adventures: Royal Carriage, Coin of the Realm
        yield from ally_after_play(s, player, card)                # Allies: Circle of Witches, League of Shopkeepers, Fellowship of Scribes
        yield from plunder.after_play_steps(s, player, card, snap)  # Plunder: Harbor Village, Frigate, Flagship, Inspiring
        if again:
            s.log.append(f"{s.players[player].name}'s Citadel plays {card} again.", "play", 1)
            yield from EffectContext(s, player, "Citadel").resolve(card)

    def _play_treasure(self, player: int, card: str) -> None:
        s = self.state
        me = s.players[player]
        me.hand.remove(card)
        me.in_play.append(card)
        s.hand_plays += 1
        first = not s.turn_counts.get("any_play")                # Plunder: Landing Party cares about the first card played on a turn
        s.turn_counts["any_play"] = 1
        self._advance(self._treasure_steps(player, card, first), None, card)

    def _treasure_steps(self, player: int, card: str, first: bool):
        s = self.state
        yield from EffectContext(s, player, card).resolve_treasure(card)     # its $ and its own effect
        if first and s.current_player == player:
            yield from plunder.treasure_played_first(s, player, card)

    def _spend_coffers(self, player: int, count: int) -> None:
        s = self.state
        s.players[player].coffers -= count
        s.coins += count
        s.log.append(f"{s.players[player].name} spends {count} Coffers token{'s' if count != 1 else ''} for +${count}.", "treasure")

    def _spend_villager(self, player: int, count: int) -> None:
        s = self.state
        s.players[player].villagers -= count
        s.actions += count
        s.log.append(f"{s.players[player].name} spends {count} Villager{'s' if count != 1 else ''} for +{count} Action{'s' if count != 1 else ''}.", "play")

    def _pay_debt(self, player: int, count: int) -> None:
        s = self.state
        s.players[player].debt -= count
        s.coins -= count
        s.log.append(f"{s.players[player].name} pays off {count} Debt token{'s' if count != 1 else ''} ({s.players[player].debt} left).", "treasure")

    def _take_buy_debt(self, player: int, card_name: str) -> None:
        """Empires: buying a card with Debt in its cost (or from a pile with Tax's Debt on it) makes the buyer take the tokens."""
        s = self.state
        taker = zones.beneficiary(s, player)
        owed = get_card(card_name).debt_cost
        pile = s.stack_of.get(card_name, card_name)
        extra = 0 if risingsun.active(s, "Harsh Winter") else s.pile_debt.get(pile, 0)      # (Harsh Winter takes the tokens itself, for every gain)
        if extra:
            s.pile_debt[pile] = 0
        if owed + extra:
            s.players[taker].debt += owed + extra
            note = f" ({extra} from Tax)" if extra else ""
            s.log.append(f"{s.players[taker].name} takes {owed + extra} Debt token{'s' if owed + extra != 1 else ''}{note} ({s.players[taker].debt} in all).", "info", 1)

    def _buy_fair_steps(self, player: int):
        """Menagerie, Animal Fair: \"instead of paying this card's cost, you may trash an Action card from your hand\"."""
        s = self.state
        me = s.players[player]
        ctx = EffectContext(s, player, "Animal Fair")
        pay = f"Pay ${card_cost(s, 'Animal Fair')}"
        trash = "Trash an Action card from your hand instead"
        options = [trash] if s.coins < card_cost(s, "Animal Fair") else [pay, trash]
        (mode,) = yield ctx.choose("Animal Fair: pay its cost, or trash an Action card from your hand instead?", tuple(options))
        if mode == trash:
            actions = tuple(sorted({c for c in me.hand if get_card(c).is_type(CardType.ACTION)}))
            (card,) = yield ctx.choose("Animal Fair: trash an Action card from your hand instead of paying.", actions)
            ctx.trash(card)
            self._buy(player, "Animal Fair", 0, pay_cost=False)
        else:
            self._buy(player, "Animal Fair", 0)

    def _buy(self, player: int, card: str, overpay: int = 0, pay_cost: bool = True) -> None:
        s = self.state
        if pay_cost:
            s.coins -= card_cost(s, card) + overpay
        s.overpaid = overpay
        s.potions -= get_card(card).potion_cost
        spend_buy(s)
        s.buying = True                                       # the gain below is a purchase (Hoard, Goons, Talisman)
        s.bought_turn += 1
        zones.gain_card(s, player, card)
        s.buying = False
        s.overpaid = 0
        self._take_buy_debt(player, card)
        landmarks.after_buy(s, player, card)
        taker = zones.beneficiary(s, player)
        s.players[taker].bought.append(card)
        if get_card(card).is_type(CardType.VICTORY):
            s.bought_victory = True
        if taker != player:                                   # Possession: the controlling player gets what is bought
            s.log.append(f"{s.players[player].name} buys {card} for {s.players[taker].name} (Possession).", "buy")
        else:
            s.log.append(f"{s.players[player].name} buys {card}" + (f", overpaying ${overpay}." if overpay else "."), "buy")
        for _ in range(s.embargo.get(card, 0)):               # Embargo: a Curse for each token on the pile
            if zones.gain_card(s, player, "Curse"):
                s.log.append(f"{s.players[zones.beneficiary(s, player)].name} gains a Curse (Embargo).", "gain", 1)

    def _buy_event(self, player: int, name: str) -> None:
        s = self.state
        event = get_card(name)
        s.coins -= event.cost
        spend_buy(s)
        if event.debt_cost:
            s.players[player].debt += event.debt_cost
            s.log.append(f"{s.players[player].name} takes {event.debt_cost} Debt tokens ({s.players[player].debt} in all).", "info", 1)
        if event.once_per_turn:
            s.turn_counts["event:" + name] = 1
        s.log.append(f"{s.players[player].name} buys the event {name}.", "buy")
        self._advance(self._event_steps(player, name), None, name)

    def _event_steps(self, player: int, name: str):
        result = get_card(name).on_play(EffectContext(self.state, player, name))
        if inspect.isgenerator(result):
            yield from result

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
        fire_triggers(self.state, event, player, *args)

    def _end_phase(self, player: int) -> None:
        s = self.state
        if s.phase is Phase.ACTION:
            s.phase = Phase.BUY
            s.log.append(f"{s.players[player].name} moves to the Buy phase.", "phase")
            nocturne.start_of_buy_phase(s, player)                 # Nocturne: Deluded and Envious are returned and take effect
            renaissance.start_of_buy_phase(s, player)              # Renaissance: Treasure Chest
            self._advance(self._start_buy_steps(player), None, "Start of Buy phase")
        elif s.phase is Phase.BUY:
            self._advance(self._end_buy_steps(player), None, "End of Buy phase")
        else:                                                      # Nocturne: the Night phase is over
            self._advance(self._cleanup_steps(player), None, "Cleanup")

    def _start_buy_steps(self, player: int):
        """The things that happen at the start of the Buy phase: Arena (Empires), then the Ally (Allies)."""
        s = self.state
        if "Arena" in s.landmarks and s.landmark_vp.get("Arena", 0) > 0 and any(
                get_card(c).is_type(CardType.ACTION) for c in s.players[player].hand):
            yield from self._arena_steps(player)
        yield from allies.start_of_buy_steps(s, player)

    def _arena_steps(self, player: int):
        """Empires, Arena: at the start of the Buy phase the player may discard an Action card for 2 VP."""
        s = self.state
        me = s.players[player]
        options = tuple(sorted({c for c in me.hand if get_card(c).is_type(CardType.ACTION)}))
        chosen = yield EffectContext(s, player, "Arena").choose("Arena: you may discard an Action card to take 2 VP.", options, 0, 1)
        if chosen:
            EffectContext(s, player, "Arena").discard(chosen[0])
            landmarks._give(s, player, "Arena", 2)

    def _end_buy_steps(self, player: int):
        self._fire("buy_phase_end", player)                    # Merchant Guild: "at the end of your Buy phase"
        yield from call_steps(self.state, player, "buy_end")   # Adventures: Wine Merchant
        yield from renaissance.end_of_buy_steps(self.state, player)      # Renaissance: Exploration, Pageant
        me = self.state.players[player]
        if any(get_card(c).is_type(CardType.NIGHT) for c in me.hand):      # Nocturne: Action, Buy, Night, Clean-up
            self.state.phase = Phase.NIGHT
            self.state.log.append(f"{me.name} moves to the Night phase.", "phase")
            return
        yield from self._cleanup_steps(player)

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
            current = self.state.pending
            if current is None or current.generator is generator:      # (a later effect may already be waiting)
                self.state.pending = None
            return
        if not 0 <= decision.player < len(self.state.players):
            raise ValueError(f"{source} asked an unknown player.")
        self.state.pending = PendingEffect(decision, generator, source)

    def _settle(self) -> None:
        """Once nothing is waiting for an answer, look at the cards that were just gained: "when you gain" effects
        (Hoard, Collection, Mint, Royal Seal, Watchtower...) happen now, one gain at a time."""
        s = self.state
        renaissance.scan_reveals(s)                                # Renaissance: Patron
        if s.status is not GameStatus.ACTIVE:
            s.gain_events.clear()
            s.trash_events.clear()
            s.star_draws.clear()
            s.discard_events.clear()
            return
        if s.pending is None and (s.gain_events or s.trash_events or s.star_draws or s.discard_events):
            self._advance(self._settle_steps(), None, "Gain")

    def _settle_steps(self):
        """Gains first, then trashes, until nothing is waiting (a gain can cause a trash and the other way round)."""
        s = self.state
        while s.gain_events or s.trash_events or s.star_draws or s.discard_events:
            if s.star_draws:
                yield from renaissance.star_chart_steps(s)
            elif s.gain_events:
                yield from self._gain_steps()
            elif s.trash_events:
                yield from self._trash_step(s.trash_events.pop(0))
            else:
                yield from menagerie.discard_steps(s)               # Menagerie: Village Green discarded

    def _trash_step(self, event):
        """\"When you trash this\" (Squire, Catacombs, Fortress...) and Reactions to a trash (Market Square)."""
        s = self.state
        own = get_card(event.card).on_trash
        if own is not None:
            result = own(EffectContext(s, event.player, event.card), event)
            if inspect.isgenerator(result):
                yield from result
        landmarks.after_trash(s, event.player)                     # Empires: Tomb
        yield from renaissance.trash_steps(s, event)               # Renaissance: Priest, Sewers
        hand = s.players[event.player].hand
        for name in sorted(set(hand)):
            hook = get_card(name).on_trash_reaction
            if hook is None or name not in hand:
                continue
            result = hook(EffectContext(s, event.player, name), event)
            if inspect.isgenerator(result):
                yield from result

    def _gain_steps(self):
        s = self.state
        while s.gain_events:
            event = s.gain_events.pop(0)
            player = event.player
            me = s.players[player]
            replaced = yield from self._gain_replacement(event)      # "when you would gain a card" (Trader)
            if replaced:
                continue
            own = get_card(event.card).on_gain                       # "when you gain this" (Mint)
            if own is not None:
                result = own(EffectContext(s, player, event.card), event)
                if inspect.isgenerator(result):
                    yield from result
            landmarks.after_gain(s, event)                           # Empires: Landmarks
            yield from renaissance.gain_steps(s, event)              # Renaissance: Academy, Guildhall, Road Network, Cargo Ship, Innovation
            yield from menagerie.after_gain_steps(s, event)          # Menagerie: Exile, Invest, Livery, Way of the Monkey / Seal
            yield from allies.after_gain_steps(s, event)             # Allies: Guildmaster, Garrison, Skirmisher and the Allies that trigger on a gain
            yield from plunder.after_gain_steps(s, event)            # Plunder: Traits, Rush, Mirror, Mining Road, waiting Durations, Mapmaker, Stowaway
            yield from risingsun.after_gain_steps(s, event)          # Rising Sun: the Prophecies that react to a gain, and the Gold Kintsugi remembers
            if s.current_player == player and get_card(event.card).is_type(CardType.VICTORY) and s.turn_counts.get("Groundskeeper"):
                EffectContext(s, player, "Groundskeeper").add_vp(s.turn_counts["Groundskeeper"])
            over = get_card(event.card).on_overpay                   # "Overpay:" (Guilds)
            if over is not None and event.overpaid:
                result = over(EffectContext(s, player, event.card), event)
                if inspect.isgenerator(result):
                    yield from result
            if s.changeling and event.card != "Changeling" and s.supply.get("Changeling", 0) > 0 and card_cost(s, event.card) >= 3:
                ctx = EffectContext(s, player, "Changeling")           # Nocturne: a gained card costing $3+ may become a Changeling
                if ctx.can_return_gained(event):
                    chosen = yield ctx.choose(f"You gained {event.card}. You may exchange it for a Changeling.", ("Exchange it for a Changeling",), 0, 1)
                    if chosen:
                        ctx.exchange_gained_for(event, "Changeling")
            if event.bought:                                         # Adventures: Plan's Trashing token, Haunted Woods, Swamp Hag
                pile = s.stack_of.get(event.card, event.card)
                if me.tokens.get("Trashing") == pile and me.hand:
                    ctx = EffectContext(s, player, "Plan")
                    chosen = yield ctx.choose(f"You bought {event.card}, which has your Trashing token. You may trash a card from your hand.",
                                              tuple(sorted(me.hand)), 0, 1)
                    if chosen:
                        ctx.trash(chosen[0])
                n_players = len(s.players)
                for other in [(player + k) % n_players for k in range(1, n_players)]:
                    for name in sorted(set(s.players[other].in_play)):
                        hook = get_card(name).on_buy_by_other
                        if hook is not None and name in s.players[other].in_play:
                            result = hook(EffectContext(s, other, name), event)
                            if inspect.isgenerator(result):
                                yield from result
            if s.current_player == player:                           # Adventures: Travelling Fair
                for _ in range(s.turn_counts.get("Travelling Fair", 0)):
                    ctx = EffectContext(s, player, "Travelling Fair")
                    if ctx.gained_card_present(event):
                        chosen = yield ctx.choose(f"Travelling Fair: you may put {event.card} onto your deck.", (f"Put {event.card} on your deck",), 0, 1)
                        if chosen:
                            ctx.put_gained_on_deck(event)
            if event.bought:                                         # Empires: Charm
                for _ in range(s.turn_counts.pop("Charm", 0)):
                    ctx = EffectContext(s, player, "Charm")
                    options = ctx.same_cost_cards(event.card)
                    if options:
                        chosen = yield ctx.choose(f"Charm: you bought {event.card}. You may also gain a differently named card with the same cost.", options, 0, 1)
                        if chosen:
                            ctx.gain(chosen[0])
            yield from call_steps(s, player, "gain", event)          # Adventures: Duplicate
            if s.footpad and s.phase is Phase.ACTION:                # Footpad: +1 Card for a card gained in an Action phase
                EffectContext(s, player, "Footpad").draw(1)
            for name in sorted(set(me.in_play)):                     # "while this is in play / this turn, when you gain a card"
                hook = get_card(name).on_gain_in_play
                if hook is None:
                    continue
                for _ in range(me.in_play.count(name)):
                    result = hook(EffectContext(s, player, name), event)
                    if inspect.isgenerator(result):
                        yield from result
            for name in sorted(set(me.hand)):                        # Reactions in hand (Watchtower)
                hook = get_card(name).on_gain_reaction
                if hook is None or name not in me.hand:
                    continue
                result = hook(EffectContext(s, player, name), event)
                if inspect.isgenerator(result):
                    yield from result
            yield from menagerie.gain_reaction_steps(s, event)       # Menagerie: Sheepdog, Sleigh, Falconer, Black Cat
            if s.duchess and event.card == "Duchy" and s.supply.get("Duchess", 0) > 0:     # Duchess: a Duchy may bring a Duchess
                ctx = EffectContext(s, player, "Duchess")
                chosen = yield ctx.choose("You gained a Duchy. You may gain a Duchess.", ("Gain a Duchess",), 0, 1)
                if chosen:
                    ctx.gain("Duchess")
            n = len(s.players)
            for other in [(player + k) % n for k in range(1, n)]:     # Reactions to ANOTHER player's gain (Fool's Gold)
                for name in sorted(set(s.players[other].hand)):
                    hook = get_card(name).on_other_gain
                    if hook is None or name not in s.players[other].hand:
                        continue
                    result = hook(EffectContext(s, other, name), event)
                    if inspect.isgenerator(result):
                        yield from result

    def _gain_replacement(self, event):
        """Generator returning True if the gain was replaced: a Reaction in hand (Trader) lets its owner gain another card
        (a Silver) instead. The card just gained goes back where it came from, as if it had never been gained."""
        s = self.state
        me = s.players[event.player]
        if event.zone is None:
            return False
        for name in sorted(set(me.hand)):
            instead = get_card(name).gain_replacement
            if not instead or event.card == instead or name not in me.hand:
                continue
            zone = getattr(me, event.zone)
            if event.card not in zone or s.supply.get(instead, 0) <= 0:
                continue
            ctx = EffectContext(s, event.player, name)
            chosen = yield ctx.choose(
                f"You would gain {event.card}. You may reveal {name} to gain a {instead} instead.", (f"Reveal {name}",), 0, 1)
            if not chosen:
                continue
            zone.pop(len(zone) - 1 - zone[::-1].index(event.card))
            if event.from_supply:
                s.supply[event.card] += 1
            elif event.card in s.offsupply:
                s.offsupply[event.card] += 1
                if get_card(event.card).is_type(CardType.LOOT):          # Plunder: back on top of the Loot pile
                    s.loot.insert(0, event.card)
            else:
                s.trash.append(event.card)
            for tally in (me.gained, me.gained_turn):
                if event.card in tally:
                    tally.pop(len(tally) - 1 - tally[::-1].index(event.card))
            if event.bought and event.card in me.bought:
                me.bought.pop(len(me.bought) - 1 - me.bought[::-1].index(event.card))
            ctx.log(f"{me.name} reveals {name} and gains a {instead} instead of {event.card}.", "reveal")
            zones.gain_card(s, event.player, instead)
            return True
        return False

    def _begin_turn(self, player: int) -> None:
        self._advance(self._begin_turn_steps(player), None, "Start of turn")

    def _begin_turn_steps(self, player: int):
        """Duration cards do what they promised, then the player may play Clerks from their hand."""
        s = self.state
        me = s.players[player]
        menagerie.start_of_turn(s, player)                     # Menagerie: Gatekeeper and Way of the Monkey end
        allies.start_of_turn(s, player)                        # Allies: Highwaymen and Warlords end
        entries, me.durations = me.durations, []
        for entry in entries:                                  # Plunder: waiting Durations (Abundance, Cage, Quartermaster...) stay where they are
            if isinstance(entry.data, dict) and entry.data.get("persist"):
                me.durations.append(entry)
        for entry in entries:
            if isinstance(entry.data, dict) and entry.data.get("persist") and entry.handler is None:
                continue
            if entry.handler is not None:
                result = entry.handler(EffectContext(s, player, entry.source), entry)
                if inspect.isgenerator(result):
                    yield from result
        yield from call_steps(s, player, "start")              # Adventures: Guide, Ratcatcher, Transmogrify, Teacher
        yield from nocturne.start_of_turn_steps(s, player)     # Nocturne: held Boons (Blessed Village), Lost in the Woods
        yield from renaissance.start_of_turn_steps(s, player)  # Renaissance: Barracks, Fair, Key and the Projects that act at the start of the turn
        yield from allies.start_of_turn_steps(s, player)       # Allies: the Ally's start-of-turn ability
        yield from plunder.start_of_turn_steps(s, player)      # Plunder: Shaman, Shy
        yield from risingsun.start_of_turn_steps(s, player)    # Rising Sun: Kind Emperor, Sickness
        while True:
            options = tuple(sorted({c for c in me.hand if get_card(c).play_at_turn_start}))
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
        """End of turn. It runs as a generator so a card may ask its owner something first (Herbalist, Alchemist);
        with nothing to ask it simply runs to the end in one go."""
        self._advance(self._cleanup_steps(player), None, "Cleanup")

    def _cleanup_steps(self, player: int):
        s = self.state
        me = s.players[player]
        s.cleanup_active = True
        was_extra = s.outpost_turn or s.mission_turn or s.seize_turn      # Menagerie: Seize the Day (not a third turn in a row)
        seize_extra = s.seize_turn
        yield from allies.end_of_turn_steps(s, player, was_extra)          # Allies: Island Folk's extra turn
        yield from plunder.start_cleanup_steps(s, player)                  # Plunder: Friendly and Patient, \"at the start of Clean-up\"
        yield from risingsun.start_cleanup_steps(s, player)                # Rising Sun: River Shrine, Biding Time
        schemed = []                                         # Hinterlands: Scheme, "at the start of Clean-up"
        for _ in range(s.turn_counts.get("Scheme", 0)):
            kept = {n for e in me.durations for n in e.cards}
            options = tuple(sorted({c for c in me.in_play if get_card(c).is_type(CardType.ACTION) and c not in kept}))
            if not options:
                break
            chosen = yield EffectContext(s, player, "Scheme").choose(
                "Scheme: you may choose an Action card you have in play. If you discard it from play this turn, put it on your deck.",
                options, 0, 1)
            if chosen:
                schemed.append(chosen[0])
        schemed.extend(s.frogged)                            # Menagerie: Way of the Frog puts the card onto the deck when it is discarded from play
        s.frogged = []
        yield from renaissance.cleanup_improve_steps(s, player)   # Renaissance: Improve, "at the start of Clean-up"
        me.durations[:] = [e for e in me.durations if not (e.source == "Cargo Ship" and not e.data["cards"])]    # a Cargo Ship that set nothing aside is discarded
        me.durations[:] = [e for e in me.durations if not (isinstance(e.data, dict) and e.data.get("expires") and not e.data.get("armed"))]    # Plunder: a Taskmaster that nothing triggered
        # "When you discard this from play" effects, e.g. Alchemist (needs a Potion in play) before Herbalist.
        for card in sorted((c for c in me.in_play if get_card(c).on_cleanup is not None),
                           key=lambda c: (get_card(c).cleanup_order, c)):
            if card not in me.in_play:
                continue
            result = get_card(card).on_cleanup(EffectContext(s, player, card))
            if inspect.isgenerator(result):
                yield from result
        landmarks.end_of_turn(s, player)                     # Empires: Baths
        # Seaside: a Treasury's question needs to know whether a Victory card was bought; Outpost shortens the next hand
        outpost = s.outpost_flag and not s.outpost_turn and s.possessor is None
        s.outpost_turn = False
        s.outpost_flag = False
        if outpost:
            s.outpost_next = True
        mission = s.mission_flag and not s.mission_turn and s.possessor is None and not outpost     # Adventures: Mission
        s.mission_turn = False
        s.mission_flag = False
        if mission:
            s.mission_next = True
        seize = s.seize_flag and not was_extra and not outpost and not mission and s.possessor is None
        journey = bool(seize and s.turn_counts.get("journey_keep"))
        s.seize_flag = False
        s.seize_turn = False
        if seize:
            s.seize_next = True
            s.voyage_next = s.voyage_flag                       # Voyage: the extra turn is limited to 3 cards from the hand
        s.voyage_flag = False
        s.voyage_turn = False
        s.hand_plays = 0
        s.skirmishers.clear()
        returned = zones.return_possession_cards(s)
        if returned:
            s.log.append(f"{me.name}'s {returned} trashed card(s) return to their discard pile.", "reveal")
        staying, remaining = [], list(me.in_play)            # Duration cards that still have something to do stay in play
        for entry in me.durations:
            for name in entry.cards:
                if name in remaining:
                    remaining.remove(name)
                    staying.append(name)
        for card in schemed:                                   # Scheme: chosen Actions go back on the deck instead of the discard pile
            if card in remaining:
                remaining.remove(card)
                me.deck.append(card)
                s.log.append(f"{me.name} puts {card} on their deck (Scheme).", "info", 1)
        yield from renaissance.horn_steps(s, player, remaining)  # Renaissance: Horn
        if journey:                                            # Plunder: Journey leaves the cards in play
            staying.extend(remaining)
            remaining = []
        yield from plunder.end_cleanup_steps(s, player, remaining)   # Plunder: Trickster, Tireless, Reckless
        risingsun.end_cleanup_steps(s, player, remaining)            # Rising Sun: Panic
        for other_index, other in enumerate(s.players):          # Menagerie: Reactions played on another player's turn are discarded in this Clean-up
            if other_index != player and other.in_play:
                keep = [n for e in other.durations for n in e.cards]
                gone = []
                for name in list(other.in_play):
                    if name in keep:
                        keep.remove(name)
                    else:
                        gone.append(name)
                if gone:
                    for name in gone:
                        other.in_play.remove(name)
                    other.discard.extend(gone)
        me.discard.extend(me.joust_aside)                      # a Province set aside by Joust is discarded now
        me.joust_aside.clear()
        yield from allies.coastal_haven_steps(s, player)        # Allies: Coastal Haven keeps cards in hand
        me.discard.extend(me.hand)
        me.discard.extend(remaining)
        me.hand.clear()
        me.in_play[:] = staying
        for _ in range(s.turn_counts.get("Donate", 0)):      # Empires: Donate, "after this turn"
            yield from self._donate_steps(player)
        flag = 1 if s.artifacts.get("Flag") == player else 0         # Renaissance: the Flag, +1 Card when drawing your hand
        zones.draw_cards(s, player, (3 if outpost else HAND_SIZE) + me.extra_draw + flag)
        me.extra_draw = 0
        yield from renaissance.star_chart_steps(s)             # Renaissance: Star Chart, after a shuffle in the middle of the draw
        plunder.end_of_turn_cards(s, player)                   # Plunder: set-aside cards go into hands, Tireless cards onto the deck
        for sq_index, sq in enumerate(s.players):             # Menagerie: Way of the Squirrel, +2 Cards at the end of this turn
            if sq.squirrel:
                zones.draw_cards(s, sq_index, sq.squirrel)
                s.log.append(f"{sq.name} draws {sq.squirrel} cards (Way of the Squirrel).", "draw", 1)
                sq.squirrel = 0
        if me.saved:                                           # Adventures: Save puts its card into the new hand
            me.hand.extend(me.saved)
            s.log.append(f"{me.name} puts the card set aside with Save into their hand.", "info", 1)
            me.saved.clear()
        nocturne.end_of_turn_draws(s)                          # Nocturne: The River's Gift, Faithful Hounds, kept Boons, Deluded / Envious
        me.buy_gains = 0
        me.last_gained, me.gained_turn = me.gained_turn, []
        me.trashed_last, me.trashed_turn = me.trashed_turn, 0   # Menagerie: Goatherd
        s.bought_victory = False
        if not seize_extra:                                   # a Seize the Day turn does not count for the tiebreaker
            me.turns_taken += 1
        s.actions, s.buys, s.coins = 1, 1, 0
        s.potions = 0
        s.bought_turn = 0
        s.triggers.clear()
        s.turn_counts.clear()
        s.buy_locked = False
        s.cost_reduction = 0
        s.plays_this_turn = 0
        s.played_log = []
        s.midas = False
        s.action_cost_reduction = 0
        s.banned.clear()
        s.no_more_actions = False
        s.last_gain = None
        s.war_chest_named.clear()
        s.buying = False
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
        s.prev_turn = player

        if s.mountain_next is not None:                      # Empires: Mountain Pass bidding, after the turn
            yield from self._mountain_steps()
        s.cleanup_active = False
        if s.fleet_queue is not None:                              # Renaissance: a Fleet turn just ended
            self._fleet_next()
        elif is_game_over(s):
            self._game_ends(player)
        else:
            self._after_turn(player)

    def _donate_steps(self, player: int):
        """Put the whole deck and discard pile into the hand, trash any number of those cards, shuffle the rest into the deck."""
        s = self.state
        me = s.players[player]
        me.hand.extend(me.deck)
        me.hand.extend(me.discard)
        me.deck, me.discard = [], []
        ctx = EffectContext(s, player, "Donate")
        ctx.log(f"{me.name} puts their deck and discard pile into their hand ({len(me.hand)} cards).")
        options = tuple(sorted(me.hand))
        chosen = yield ctx.choose("Donate: you may trash any number of these cards; the rest are shuffled into your deck.", options, 0, len(options))
        for card in chosen:
            ctx.trash(card)
        s.rng.shuffle(me.hand)
        me.deck, me.hand = list(me.hand), []

    def _mountain_steps(self):
        s = self.state
        gainer = s.mountain_next
        s.mountain_next = None
        n = len(s.players)
        high, best = 0, None
        for p in [(gainer + 1 + k) % n for k in range(n)]:
            ctx = EffectContext(s, p, "Mountain Pass")
            options = ("Pass", *(f"Bid {b}" for b in range(high + 1, 41)))
            chosen = yield ctx.choose(f"Mountain Pass: the highest bid so far is {high} Debt. You may bid more (up to 40), or pass. "
                                      "The high bidder takes +8 VP and as much Debt as they bid.", options)
            if chosen[0] != "Pass":
                high, best = int(chosen[0].split()[1]), p
                s.log.append(f"{s.players[p].name} bids {high} Debt.", "info", 1)
        if best is None:
            s.log.append("Nobody bids on Mountain Pass.", "info", 1)
        else:
            s.players[best].vp_tokens += 8
            s.players[best].debt += high
            s.log.append(f"{s.players[best].name} wins the Mountain Pass bidding: +8 VP and {high} Debt.", "gain", 1)

    def _game_ends(self, player: int) -> None:
        """The end of the game: first an extra round of turns for the players with Fleet (Renaissance), in turn order from the next player."""
        s = self.state
        n = len(s.players)
        fleet = [(player + k) % n for k in range(1, n + 1) if "Fleet" in s.players[(player + k) % n].projects]
        if not fleet:
            self._finish()
            return
        s.fleet_queue = fleet
        s.log.append("The game is over, but each player with Fleet now takes an extra turn.", "end")
        self._fleet_next()

    def _fleet_next(self) -> None:
        s = self.state
        s.voyage_next = False
        s.outpost_next = s.mission_next = s.seize_next = False     # nothing keeps the game going after the Fleet turns
        s.extra_turns, s.extra_owner, s.possessor = 0, None, None
        if not s.fleet_queue:
            self._finish()
            return
        s.current_player = s.fleet_queue.pop(0)
        s.turn_number += 1
        s.log.append(f"Turn {s.turn_number} - {s.players[s.current_player].name} (Fleet)", "turn")
        self._begin_turn(s.current_player)

    def _after_turn(self, player: int) -> None:
        """Decide whose turn comes next, keeping Possession's extra turns in mind."""
        s = self.state
        if s.possessor is not None:                          # a possessed turn just ended
            possessor = s.possessor
            s.possessor = None
            if s.extra_turns > 0 and s.extra_owner == possessor:
                self._start_possession(possessor)            # another Possession was played: another extra turn
            else:
                s.extra_turns = 0
                s.extra_owner = None
                self._next_turn(advance=False)               # the possessed player now takes their own, normal turn
        elif s.mission_next:                                  # Adventures: Mission, an extra turn without buying cards
            s.mission_next = False
            s.mission_turn = True
            s.buy_locked = True
            self._next_turn(advance=False)
        elif s.seize_next:                                    # Menagerie: Seize the Day, an extra turn
            s.seize_next = False
            s.seize_turn = True
            s.voyage_turn, s.voyage_next = s.voyage_next, False
            self._next_turn(advance=False)
        elif s.outpost_next:                                  # Outpost: the same player takes another turn
            s.outpost_next = False
            s.outpost_turn = True
            self._next_turn(advance=False)
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
        self._begin_turn(s.current_player)

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
            self._begin_turn(s.current_player)
            return

    def _finish(self, winners=None) -> None:
        s = self.state
        s.cleanup_active = False
        zones.return_possession_cards(s)
        s.gain_events.clear()
        s.trash_events.clear()
        s.discard_events.clear()
        s.status = GameStatus.FINISHED
        s.pending = None                 # an unanswered question dies with the game
        s.winners = list(winners) if winners is not None else determine_winners(s)
        scores = final_scores(s)
        summary = ", ".join(f"{p.name}: {v} VP" for p, v in zip(s.players, scores))
        s.log.append(f"Game over. {summary}.", "end")
        s.log.append("Winner(s): " + ", ".join(s.players[i].name for i in s.winners), "end")
