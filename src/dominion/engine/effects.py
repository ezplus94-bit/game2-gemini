"""The ONLY surface card effects may use to change the game.

A card effect receives an ``EffectContext``. Keeping effects behind this small
API means the engine can change internally without touching card code, and a
card can never put the game into a state the rules do not allow.

Interactive effects are generators::

    def my_card(ctx):
        (card,) = yield ctx.choose("Pick one", ctx.hand)   # pauses here
        ctx.discard(card)                                   # resumes here

A card that plays another card uses ``yield from ctx.resolve(card)`` so any
questions the inner card asks are passed through to the player.
"""

from __future__ import annotations

import inspect
from collections import Counter
from typing import Callable, Optional, Sequence

from ..cards import CardType, get_card
from . import zones
from .cardtypes import has_type, is_treasure as _is_treasure, treasure_coins, type_values
from .actions import Decision
from .costs import card_cost, costs_more, full_cost, is_buried, is_walled
from .state import DurationEntry, GameState, Trigger

# Cards that "stay in play" together with a Duration card they played (Throne Room).
DURATION_KEEPERS = frozenset({"Throne Room", "King's Court", "Crown", "Ghost", "Mastermind"})


class EffectContext:
    def __init__(self, state: GameState, player: int, source: str) -> None:
        self._state = state
        self.player = player      # index of the player who played the card
        self.source = source      # name of the card being resolved
        self._kept = False        # this card already made itself stay in play with a Duration card
        self._chameleon = False   # Menagerie: played with Way of the Chameleon: +Cards and +$ swap places

    def _me(self):
        return self._state.players[self.player]

    def _name(self, index: Optional[int] = None) -> str:
        return self._state.players[self.player if index is None else index].name

    # ---- read-only views
    @property
    def player_name(self) -> str:
        return self._me().name

    def name_of(self, player: int) -> str:
        return self._state.players[player].name

    def hand_of(self, player: int) -> tuple:
        return tuple(self._state.players[player].hand)

    @property
    def hand(self) -> tuple:
        return tuple(self._me().hand)

    @property
    def in_play(self) -> tuple:
        return tuple(self._me().in_play)

    @property
    def hand_size(self) -> int:
        return len(self._me().hand)

    @property
    def discard_pile(self) -> tuple:
        return tuple(self._me().discard)

    def cost_of(self, card: str) -> int:
        # Single choke point for costs, so cost reducers (Bridge) apply everywhere.
        return card_cost(self._state, card)

    def potion_cost_of(self, card: str) -> int:
        """How many Potions a card costs (Alchemy)."""
        return get_card(card).potion_cost

    def is_action(self, card: str) -> bool:
        return get_card(card).is_type(CardType.ACTION)

    def is_victory(self, card: str) -> bool:
        return get_card(card).is_type(CardType.VICTORY)

    def is_treasure(self, card: str) -> bool:
        return _is_treasure(self._state, card)             # a Curse is a Treasure in games with Charlatan

    def gainable(self, max_cost: int, card_type: Optional[CardType] = None, exact: bool = False,
                 gainer: Optional[int] = None) -> tuple:
        """Supply piles that are non-empty, not walled off against ``gainer`` (default: this player), cost at
        most ``max_cost`` (exactly ``max_cost`` with ``exact=True``) and (optionally) have the given type.
        Cards that cost a Potion are never offered: "costing up to $4" does not include a card costing $3 and a Potion."""
        s = self._state
        who = self.player if gainer is None else gainer
        return tuple(
            name for name in sorted(s.supply)
            if s.supply[name] > 0 and not is_walled(s, name, who) and not is_buried(s, name)
            and get_card(name).potion_cost == 0 and get_card(name).debt_cost == 0
            and (self.cost_of(name) == max_cost if exact else self.cost_of(name) <= max_cost)
            and (card_type is None or has_type(s, name, card_type))
        )

    @property
    def coins(self) -> int:
        """The $ the player has right now (always the current player's turn)."""
        return self._state.coins

    @property
    def bought_this_turn(self) -> int:
        return self._state.bought_turn

    @property
    def plays_this_turn(self) -> int:
        """Actions played so far this turn (Throne Room repeats count), this one included."""
        return self._state.plays_this_turn

    @property
    def deck_size(self) -> int:
        return len(self._me().deck)

    def trash_pile(self) -> tuple:
        return tuple(self._state.trash)

    def card_types(self, card: str) -> tuple:
        return tuple(type_values(self._state, card))

    def supply_count(self, card: str) -> int:
        return self._state.supply.get(card, 0)

    def supply_names(self) -> tuple:
        return tuple(sorted(self._state.supply))

    def owned(self, player: int) -> Counter:
        """Everything a player owns in draw pile, hand and discard pile, as a tally."""
        p = self._state.players[player]
        return Counter([*p.deck, *p.hand, *p.discard])

    def other_players(self) -> list:
        """Other players in turn order, starting with the one after you."""
        n = len(self._state.players)
        return [(self.player + k) % n for k in range(1, n)]

    def empty_piles(self) -> int:
        s = self._state
        return (sum(1 for name, count in s.supply.items() if count == 0 and name not in s.stack_of)     # (a card of a mixed or split pile is not a pile of its own)
                + sum(1 for stack in s.stacks.values() if not stack))

    # ---- turn resources (always the current player's turn)
    def add_actions(self, n: int) -> None:
        if self._state.current_player != self.player:       # Menagerie: a Reaction played on another player's turn (Village Green...) gets nothing from these
            return
        if self._state.no_more_actions and n > 0:          # Menagerie: Snowy Village
            self.log("Snowy Village: further +Actions are ignored this turn.")
            return
        self._state.actions += n

    def add_buys(self, n: int) -> None:
        if self._state.current_player != self.player:
            return
        self._state.buys += n

    def add_coins(self, n: int) -> None:
        if self._state.current_player != self.player:
            return
        if self._chameleon and n > 0:                      # Menagerie: Way of the Chameleon turns +$ into +Cards
            self._chameleon = False
            try:
                self.log(f"Way of the Chameleon: +${n} becomes +{n} Card(s).")
                self.draw(n)
            finally:
                self._chameleon = True
            return
        if n > 0:
            n = take_minus_coin(self._state, n)
            self._state.coin_ticks += 1
        self._state.coins += n

    # ---- card movement
    def draw(self, count: int, player: Optional[int] = None, quiet: bool = False) -> list:
        i = self.player if player is None else player
        if self._chameleon and i == self.player and count > 0:      # Menagerie: Way of the Chameleon turns +Cards into +$
            self._chameleon = False
            try:
                self.log(f"Way of the Chameleon: +{count} Card(s) becomes +${count}.")
                self.add_coins(count)
            finally:
                self._chameleon = True
            return []
        drawn = zones.draw_cards(self._state, i, count)
        if not quiet:
            self.log(f"{self._name(i)} draws {len(drawn)} card(s).")
        return drawn

    def gain(self, card: str, player: Optional[int] = None, destination: str = "discard") -> bool:
        i = self.player if player is None else player
        ok = zones.gain_card(self._state, i, card, destination)
        if ok:
            taker = zones.beneficiary(self._state, i)
            if taker != i:                                   # Possession: the card goes to whoever controls the turn
                self.log(f"{self._name(taker)} gains {card} (Possession).")
            else:
                where = "" if destination == "discard" else f" to their {destination}"
                self.log(f"{self._name(i)} gains {card}{where}.")
        return ok

    def discard(self, card: str, player: Optional[int] = None) -> None:
        i = self.player if player is None else player
        zones.discard_from_hand(self._state, i, card)
        self.log(f"{self._name(i)} discards {card}.")

    def trash(self, card: str, player: Optional[int] = None) -> None:
        i = self.player if player is None else player
        zones.trash_from_hand(self._state, i, card)
        self.log(f"{self._name(i)} trashes {card}.")

    def put_hand_on_deck(self, card: str, player: Optional[int] = None, reveal: bool = False) -> None:
        i = self.player if player is None else player
        zones.move_card(self._state, i, card, "hand", "deck")
        if reveal:
            self.log(f"{self._name(i)} reveals {card} and puts it onto their deck.")
        else:
            self.log(f"{self._name(i)} puts a card from their hand onto their deck.")

    def put_discard_on_deck(self, card: str) -> None:
        zones.move_card(self._state, self.player, card, "discard", "set_aside")
        zones.move_card(self._state, self.player, card, "set_aside", "deck")
        self.log(f"{self._name()} puts a card from their discard pile onto their deck.")

    def put_deck_into_discard(self) -> None:
        """Trusty Steed: the whole draw pile goes into the discard pile."""
        me = self._me()
        n = len(me.deck)
        me.discard.extend(me.deck)
        me.deck.clear()
        self.log(f"{self._name()} puts their deck ({n} card(s)) into their discard pile.")

    def take_from_discard(self, card: str) -> None:
        """Move a card from the discard pile into the hand (Counting House)."""
        zones.move_card(self._state, self.player, card, "discard", "hand")

    def put_in_play_on_deck(self, card: str) -> None:
        """Put a card that is in play onto the top of the deck (Herbalist, Alchemist at cleanup)."""
        zones.move_card(self._state, self.player, card, "in_play", "deck")
        self.log(f"{self._name()} puts {card} from play onto their deck.")

    def discard_top_of_deck(self, player: Optional[int] = None) -> Optional[str]:
        """Discard the top card of the deck (revealed). Returns its name or None."""
        i = self.player if player is None else player
        cards = zones.take_top_cards(self._state, i, 1)
        if not cards:
            return None
        self._state.players[i].discard.append(cards[0])
        self.log(f"{self._name(i)} discards {cards[0]} from the top of their deck.")
        zones.tunnel_discarded(self._state, i, cards[0])
        return cards[0]

    # ---- Seaside: mats, Duration cards, tokens
    def add_duration(self, handler=None, data=None, cards: Optional[Sequence[str]] = None) -> None:
        """This card stays in play until the start of its owner's next turn, when ``handler(ctx, entry)`` runs
        (a plain function; ``None`` if the card only has to stay in play)."""
        self._me().durations.append(
            DurationEntry(self.source, tuple(cards) if cards is not None else (self.source,), handler, data))

    def put_on_mat(self, card: str, mat: str, source: str = "hand") -> None:
        """Move a card between a zone and a mat: ``mat`` is "island_mat", "village_mat" or "haven"."""
        zones.move_card(self._state, self.player, card, source, mat)

    def top_card_to_village_mat(self) -> Optional[str]:
        cards = zones.take_top_cards(self._state, self.player, 1)
        if not cards:
            return None
        self._me().village_mat.extend(cards)
        self.log(f"{self._name()} sets aside the top card of their deck on their Native Village mat.")
        return cards[0]

    def mat_cards(self, mat: str) -> tuple:
        return tuple(getattr(self._me(), mat))

    def mat_to_hand(self, mat: str) -> int:
        """Put every card from a mat into the hand."""
        me = self._me()
        cards = list(getattr(me, mat))
        getattr(me, mat).clear()
        me.hand.extend(cards)
        return len(cards)

    def pirate_tokens(self) -> int:
        return self._me().pirate_tokens

    def add_pirate_token(self) -> None:
        self._me().pirate_tokens += 1
        self.log(f"{self._name()} takes a coin token for the Pirate Ship ({self._me().pirate_tokens} in all).", "gain")

    def add_embargo(self, pile: str) -> None:
        self._state.embargo[pile] = self._state.embargo.get(pile, 0) + 1
        self.log(f"{self._name()} puts an Embargo token on the {pile} pile.", "special", 1)

    def return_to_supply(self, card: str) -> bool:
        ok = zones.return_to_supply(self._state, self.player, card)
        if ok:
            self.log(f"{self._name()} returns {card} to the Supply.")
        return ok

    def mark_outpost(self) -> None:
        """Outpost: the player takes an extra turn (with a 3-card hand) after this one."""
        self._state.outpost_flag = True

    @property
    def victory_bought(self) -> bool:
        """Did a Victory card get bought this turn? (Treasury)"""
        return self._state.bought_victory

    def last_gained_by(self, player: int) -> tuple:
        """Cards ``player`` gained during their previous turn (Smugglers)."""
        return tuple(self._state.players[player].last_gained)

    def deck_bottom(self) -> Optional[str]:
        deck = self._me().deck
        return deck[0] if deck else None

    def move_bottom_to_top(self) -> None:
        deck = self._me().deck
        if deck:
            deck.append(deck.pop(0))

    # ---- the set-aside zone (cards temporarily out of every other zone)
    def take_to_set_aside(self, count: int, player: Optional[int] = None, reveal: bool = False) -> list:
        """Move the top ``count`` cards of a deck aside (top first) and return them.
        With ``reveal`` the cards are named in the public log; otherwise only counted."""
        i = self.player if player is None else player
        cards = zones.take_top_cards(self._state, i, count)
        self._state.players[i].set_aside.extend(cards)
        if reveal and cards:
            self.log(f"{self._name(i)} reveals {' and '.join(cards)}.")
        else:
            self.log(f"{self._name(i)} looks at the top {len(cards)} card(s) of their deck.")
        return cards

    def set_aside_from_hand(self, card: str) -> None:
        zones.move_card(self._state, self.player, card, "hand", "set_aside")
        self.log(f"{self._name()} sets a card aside.")

    def discard_set_aside(self, card: str, player: Optional[int] = None) -> None:
        i = self.player if player is None else player
        zones.move_card(self._state, i, card, "set_aside", "discard")
        self.log(f"{self._name(i)} discards {card}.")
        zones.tunnel_discarded(self._state, i, card)

    def trash_set_aside(self, card: str, player: Optional[int] = None) -> None:
        i = self.player if player is None else player
        zones.move_card(self._state, i, card, "set_aside", "trash")
        self.log(f"{self._name(i)} trashes {card}.")

    def put_set_aside_on_deck(self, card: str, player: Optional[int] = None) -> None:
        i = self.player if player is None else player
        zones.move_card(self._state, i, card, "set_aside", "deck")

    # ---- playing cards from inside other cards (Throne Room, Vassal, Golem)
    def put_in_play(self, card: str, zone: str = "hand") -> None:
        zones.move_card(self._state, self.player, card, zone, "in_play")
        self._state.turn_counts["any_play"] = 1               # Plunder: this is not a Treasure played first any more (Landing Party)
        if zone == "hand":
            self._state.hand_plays += 1                       # Voyage counts cards played from the hand
        self.log(f"{self._name()} plays {card} with {self.source}.")

    def resolve(self, card: str):
        """Generator: run ``card``'s effect (without moving it). Use as
        ``yield from ctx.resolve(card)``."""
        self._state.plays_this_turn += 1
        self._state.played_log.append(card)
        again = citadel_check(self._state, self.player, card)       # Renaissance: Citadel
        before = len(self._me().durations)
        from . import plunder
        snap = plunder.before_play(self._state)
        yield from urchin_steps(self._state, self.player, card)
        apply_play_bonuses(self._state, self.player, card)
        yield from play_effect(self._state, self.player, card, get_card(card).on_play)
        yield from call_steps(self._state, self.player, "after_action", card)
        yield from ally_after_play(self._state, self.player, card)  # Allies: Circle of Witches, League of Shopkeepers, Fellowship of Scribes
        yield from plunder.after_play_steps(self._state, self.player, card, snap)     # Plunder: Harbor Village, Frigate, Flagship, Inspiring
        if again:
            self.log(f"{self._name()}'s Citadel plays {card} again.", "play", 1)
            yield from EffectContext(self._state, self.player, "Citadel").resolve(card)
        # A Throne Room that played a Duration card stays in play as long as that card does.
        if (self.source in DURATION_KEEPERS and not self._kept
                and any(e.source == card for e in self._me().durations[before:])):
            self._kept = True
            self._me().durations.append(DurationEntry(self.source, (self.source,)))

    # ---- Prosperity: VP tokens, costs, Treasures, "when you gain" effects
    def add_vp(self, n: int) -> None:
        """Take VP tokens (Bishop, Monument, Goons, Collection, Investment)."""
        if n > 0:
            self._me().vp_tokens += n
            self.log(f"{self._name()} takes {n} VP token{'s' if n != 1 else ''} ({self._me().vp_tokens} in all).", "gain")

    def reduce_action_costs(self, amount: int) -> None:
        self._state.action_cost_reduction += amount
        self.log(f"Action cards cost ${self._state.action_cost_reduction} less this turn.")

    def treasures_in_play(self) -> int:
        return sum(1 for c in self._me().in_play if _is_treasure(self._state, c))

    def trash_treasures_in_play(self) -> int:
        """Mint: trash every Treasure the player has in play."""
        me = self._me()
        victims = [c for c in me.in_play if _is_treasure(self._state, c)]
        for card in victims:
            me.in_play.remove(card)
            zones.send_to_trash(self._state, self.player, card)
        if victims:
            self.log(f"{self._name()} trashes the Treasures in play: {_tally(victims)}.", "trash")
        return len(victims)

    def left_player(self) -> int:
        return (self.player + 1) % len(self._state.players)

    def ban_card(self, name: str) -> None:
        """Contraband: ``name`` cannot be bought for the rest of this turn."""
        self._state.banned.add(name)
        self.log(f"{self._name(self.left_player())} names {name}: it cannot be bought this turn.", "special", 1)

    def war_chest_names(self) -> tuple:
        return tuple(self._state.war_chest_named)

    def war_chest_name(self, name: str) -> None:
        self._state.war_chest_named.append(name)
        self.log(f"{self._name(self.left_player())} names {name} for War Chest.", "special", 1)

    def trade_route_coins(self) -> int:
        return self._state.trade_mat

    def mat_empty_check(self) -> bool:
        return not self._state.trade_tokens

    def resolve_treasure(self, card: str):
        """Generator: a Treasure that is in play produces its $ / Potions and runs its own effect. Use as
        ``yield from ctx.resolve_treasure(card)``. (Playing a Treasure twice, e.g. with Tiara, calls it twice.)"""
        s = self._state
        definition = get_card(card)
        again = False
        from . import plunder
        snap = plunder.before_play(s)
        reckless = bool(s.traits) and plunder.trait_of(s, card) == "Reckless"      # Plunder: followed twice
        yield from kiln_steps(s, self.player, card)                 # Menagerie: Kiln gains a copy first
        if definition.is_type(CardType.ACTION):                    # Renaissance: Capitalism made this Action a Treasure too
            s.played_log.append(card)
            s.plays_this_turn += 1
            again = citadel_check(s, self.player, card)
        value = definition.coins_fn(s, self.player) if definition.coins_fn is not None else treasure_coins(s, card)
        potions = definition.potions
        note = ""
        blanked = False
        if (s.highwaymen and s.current_player == self.player and not s.turn_counts.get("hw_used")
                and any(t == self.player for _, t in s.highwaymen)):     # Allies: Highwayman stops the first Treasure each turn
            s.turn_counts["hw_used"] = 1
            blanked = True
            value, potions, note = 0, 0, " (Highwayman: it does nothing)"
        if s.envious_turn and card in ("Silver", "Gold") and s.current_player == self.player:
            value = 1                                         # Nocturne: Envious
        if s.midas and value < 3:
            value, potions, note = 3, 0, " as Gold"          # Midas Touch: everything turns to gold
        if reckless and not blanked:
            value, potions, note = value * 2, potions * 2, note + " (Reckless: twice)"
        s.turn_counts[card] = s.turn_counts.get(card, 0) + 1     # (Fool's Gold asks how often it was played before)
        if value > 0:
            value = take_minus_coin(s, value)                     # Adventures: the -$1 token
        s.coins += value
        s.potions += potions
        extra = f", +{potions} Potion" if potions else ""
        self.log(f"{self._name()} plays {card}{note} (+${value}{extra})." if potions
                 else f"{self._name()} plays {card}{note} (+${value}).", "treasure", 0)
        fire_triggers(s, "treasure_played", self.player, card)
        if definition.on_play is not None and not blanked:
            for _ in range(2 if reckless else 1):
                result = definition.on_play(EffectContext(s, self.player, card))
                if inspect.isgenerator(result):
                    yield from result
        if again:
            self.log(f"{self._name()}'s Citadel plays {card} again.", "play", 1)
            yield from EffectContext(s, self.player, "Citadel").resolve(card)
        yield from ally_after_play(s, self.player, card)             # Allies: Circle of Witches, League of Shopkeepers
        yield from plunder.after_play_steps(s, self.player, card, snap)       # Plunder: Inspiring

    def play_treasure(self, card: str, zone: str = "hand"):
        """Generator: play a Treasure from ``zone`` ("in_play" to play a Treasure that is already in play again)."""
        if zone != "in_play":
            zones.move_card(self._state, self.player, card, zone, "in_play")
            self.log(f"{self._name()} plays {card} with {self.source}.")
        yield from self.resolve_treasure(card)

    def gained_card_present(self, event) -> bool:
        return event.zone is not None and event.card in getattr(self._me(), event.zone)

    def put_gained_on_deck(self, event) -> None:
        """Move a card that was just gained (and has not been moved since) onto the top of its owner's deck."""
        me = self._me()
        zone = getattr(me, event.zone)
        index = len(zone) - 1 - zone[::-1].index(event.card)
        zone.pop(index)
        me.deck.append(event.card)
        event.zone = "deck"
        self.log(f"{self._name()} puts the gained {event.card} on top of their deck.")

    def trash_gained(self, event) -> None:
        me = self._me()
        zone = getattr(me, event.zone)
        index = len(zone) - 1 - zone[::-1].index(event.card)
        zone.pop(index)
        zones.send_to_trash(self._state, self.player, event.card)
        event.zone = None
        self.log(f"{self._name()} trashes the gained {event.card}.", "trash")

    # ---- Cornucopia & Guilds: Coffers, piles outside the Supply, Bane and Ferryman
    @property
    def coffers(self) -> int:
        return self._me().coffers

    def add_coffers(self, n: int, player: Optional[int] = None) -> None:
        i = self.player if player is None else player
        if n > 0:
            self._state.players[i].coffers += n
            self.log(f"{self._name(i)} takes {n} Coffers token{'s' if n != 1 else ''} ({self._state.players[i].coffers} in all).", "gain")

    def remove_coffers(self, n: int) -> None:
        self._me().coffers -= n
        if n:
            self.log(f"{self._name()} removes {n} Coffers token{'s' if n != 1 else ''}.")

    def add_extra_draw(self, n: int) -> None:
        """Farrier: draw this many extra cards for the next hand (at the end of this turn)."""
        self._me().extra_draw += n

    def offsupply_names(self) -> tuple:
        return tuple(sorted(n for n, c in self._state.offsupply.items() if c > 0))

    def gain_from_offsupply(self, card: str, player: Optional[int] = None, destination: str = "discard") -> bool:
        i = self.player if player is None else player
        ok = zones.gain_offsupply(self._state, i, card, destination)
        if ok:
            taker = zones.beneficiary(self._state, i)
            where = "" if destination == "discard" or taker != i else f" to their {destination}"
            self.log(f"{self._name(taker)} gains {card}{where}." + (" (Possession)" if taker != i else ""))
        return ok

    @property
    def bane_name(self) -> Optional[str]:
        return self._state.bane

    @property
    def ferryman_name(self) -> Optional[str]:
        return self._state.ferryman

    def buy_phase_gains(self) -> int:
        """Cards this player gained during their Buy phase so far (Merchant Guild)."""
        return self._me().buy_gains

    def differently_named_in_play(self) -> int:
        return len(set(self._me().in_play))

    # ---- Possession
    def queue_extra_turn(self) -> bool:
        """Possession: the player to the left takes an extra turn after this one, controlled by this player.
        Does nothing during a Possession turn, or against a player wearing the Invisibility Cloak."""
        s = self._state
        target = (self.player + 1) % len(s.players)
        if s.possessor is not None:
            self.log("Possession has no effect during a possessed turn.")
            return False
        if s.players[target].invisible:
            self.log(f"{self._name(target)} is invisible and cannot be possessed.", "reveal")
            return False
        s.extra_turns += 1
        s.extra_owner = self.player
        self.log(f"{self._name(target)} will take an extra turn, controlled by {self._name()}.", "skip")
        return True

    # ---- attacks and reactions
    def attack(self, only: Optional[Sequence[int]] = None):
        """Generator for the Reaction step of an Attack. Each other player, in
        turn order, may first reveal Reactions that have an effect (Diplomat), then
        one that blocks Attacks (Moat). Players with protection (Guardian Angel, God Mode, the
        Invisibility Cloak) are skipped, and Catastrophe cards allow no Reactions at all.
        Returns the players the Attack will affect::

            targets = yield from ctx.attack()
            for p in targets: ...
        """
        affected = []
        reactable = not get_card(self.source).is_type(CardType.CATASTROPHE)      # Catastrophes ignore Moat and the like
        for p in (self.other_players() if only is None else list(only)):
            if self.is_protected(p):
                self.log(f"{self.name_of(p)} is protected and unaffected.", "reveal")
                continue
            if not reactable:
                affected.append(p)
                continue
            yield from self._attack_reactions(p)
            blockers = tuple(sorted({
                c for c in self._state.players[p].hand if get_card(c).blocks_attack
            }))
            if blockers:
                chosen = yield self.choose(
                    f"{self.player_name} played {self.source}. You may reveal a Reaction to be unaffected.",
                    blockers, 0, 1, player=p,
                )
                if chosen:
                    self.log(f"{self.name_of(p)} reveals {chosen[0]} and is unaffected.", "reveal")
                    continue
            affected.append(p)
        return affected

    def _attack_reactions(self, p: int):
        """Offer ``p`` each Reaction card (with an effect) in their hand, once each."""
        offered = set()
        while True:
            hand = self._state.players[p].hand
            options = tuple(sorted(
                c for c in set(hand)
                if c not in offered and get_card(c).on_attack is not None
                and len(hand) >= get_card(c).on_attack_min_hand
            ))
            if not options:
                return
            card = options[0]
            offered.add(card)
            chosen = yield self.choose(
                f"{self.player_name} played {self.source}. You may reveal {card} first.",
                (card,), 0, 1, player=p,
            )
            if chosen:
                self.log(f"{self.name_of(p)} reveals {card}.", "reveal")
                result = get_card(card).on_attack(EffectContext(self._state, p, card))
                if inspect.isgenerator(result):
                    yield from result

    # ---- more Special / Catastrophe card helpers
    def random_int(self, n: int) -> int:
        """A random number 0..n-1 from the game's own seeded RNG (so replays and undo stay exact)."""
        return self._state.rng.randrange(n)

    def make_invisible(self) -> None:
        self._me().invisible = True
        self.log(f"{self._name()} puts on the Invisibility Cloak and vanishes.", "reveal")

    def start_midas(self) -> None:
        self._state.midas = True

    def build_walls(self, piles: Sequence[str]) -> None:
        for pile in piles:
            self._state.walls[pile] = self.player
        if piles:
            self.log(f"{self._name()} builds walls around {', '.join(piles)} until the start of their next turn.", "special", 0)

    def wallable(self) -> tuple:
        """Piles Fortnite may wall off: non-empty, not already walled, not a single-use house-rule pile."""
        s = self._state
        return tuple(
            name for name in sorted(s.supply)
            if s.supply[name] > 0 and name not in s.walls and name not in s.catastrophes
        )

    def blind(self, players: Sequence[int], turns: int = 1) -> None:
        for i in players:
            p = self._state.players[i]
            p.blind = max(p.blind, turns)
            self.log(f"{self._name(i)} is blinded: they cannot read cards until the end of their next turn.", "reveal")

    def steal_random_card(self, victim: int) -> Optional[str]:
        card = zones.steal_random_hand_card(self._state, victim, self.player)
        if card is None:
            self.log(f"{self._name(victim)} has no cards in hand to steal.", "reveal")
        else:
            self.log(f"{self._name()} steals a {card} from {self._name(victim)}!", "trash")
        return card

    def take_gold_payment(self, payer: int) -> Optional[str]:
        """Monopoly: ``payer`` hands over a Gold from their hand, else a Silver, else nothing."""
        hand = self._state.players[payer].hand
        for card in ("Gold", "Silver"):
            if card in hand:
                zones.give_to_discard(self._state, card, payer, self.player)
                self.log(f"{self._name(payer)} pays {self._name()} a {card}.", "gain")
                return card
        self.log(f"{self._name(payer)} has no Gold or Silver to pay with.", "reveal")
        return None

    def swap_hands_with(self, other: int) -> None:
        zones.swap_hands(self._state, self.player, other)
        self.log(f"{self._name()} and {self._name(other)} swap hands.")

    def trash_random_from_deck(self, count: int) -> list:
        removed = zones.remove_random_cards(self._state, self.player, ("deck",), count)
        for card in removed:
            zones.send_to_trash(self._state, self.player, card)
        self.log(f"{self._name()} loses {len(removed)} card(s) from their draw pile to the trash: {_tally(removed)}.", "trash")
        return removed

    def all_players(self) -> list:
        return list(range(len(self._state.players)))

    def is_invisible(self, player: int) -> bool:
        return self._state.players[player].invisible

    # ---- protection and gifts (Special cards)
    def is_protected(self, player: int) -> bool:
        p = self._state.players[player]
        lighthouse = any(e.source == "Lighthouse" for e in p.durations)      # Lighthouse protects until your next turn
        champion = "Champion" in p.in_play                                   # Adventures: Champion protects for the rest of the game
        guardian = any(e.source == "Guardian" for e in p.durations)          # Nocturne: Guardian protects until your next turn
        return p.protected_forever or p.protection > 0 or p.invisible or lighthouse or champion or guardian

    def protect(self, turns: int) -> None:
        """Attacks skip this player until the end of their ``turns``-th turn after the current one."""
        me = self._me()
        me.protection = max(me.protection, turns)
        me.protection_fresh = self._state.current_player == self.player
        self.log(f"{self._name()} is protected from Attacks for {turns} turns.", "reveal")

    def protect_forever(self) -> None:
        self._me().protected_forever = True
        self.log(f"{self._name()} is protected from Attacks for the rest of the game.", "reveal")

    def give_coins(self, player: int, amount: int) -> None:
        """+$ now for the player whose turn it is; otherwise stored for the start of that player's next turn."""
        if player == self._state.current_player:
            self.add_coins(amount)
            self.log(f"{self._name(player)} gets +${amount}.", "gain")
        else:
            self._state.players[player].bonus_coins += amount
            self.log(f"{self._name(player)} will get +${amount} at the start of their next turn.", "gain")

    # ---- more card movement used by Intrigue cards
    def trash_top_of_deck(self, player: Optional[int] = None) -> Optional[str]:
        """Trash the top card of a draw pile (reshuffling if needed). Returns its name or None."""
        i = self.player if player is None else player
        cards = zones.take_top_cards(self._state, i, 1)
        if not cards:
            return None
        zones.send_to_trash(self._state, i, cards[0])
        self.log(f"{self._name(i)} trashes {cards[0]} from the top of their deck.", "trash")
        return cards[0]

    def discard_hand(self, player: Optional[int] = None) -> int:
        i = self.player if player is None else player
        p = self._state.players[i]
        count = len(p.hand)
        hooks = [c for c in p.hand if c in ("Tunnel", "Faithful Hound")]
        p.discard.extend(p.hand)
        p.hand.clear()
        self.log(f"{self._name(i)} discards their hand ({count} card(s)).", "discard")
        for card in hooks:
            zones.tunnel_discarded(self._state, i, card)
        return count

    def discard_to_hand(self, card: str) -> None:
        """Mountain Village: put a card from the discard pile into the hand."""
        zones.move_card(self._state, self.player, card, "discard", "hand")
        self.log(f"{self._name()} puts {card} from their discard pile into their hand.")

    def set_aside_to_hand(self, card: str, player: Optional[int] = None) -> None:
        i = self.player if player is None else player
        zones.move_card(self._state, i, card, "set_aside", "hand")

    def gain_from_trash(self, card: str, destination: str = "discard") -> bool:
        ok = zones.gain_from_trash(self._state, self.player, card, destination)
        if ok:
            self.log(f"{self._name()} gains {card} from the trash.", "gain")
        return ok

    def trash_from_supply(self, card: str) -> bool:
        ok = zones.trash_from_supply(self._state, card)
        if ok:
            self.log(f"{self._name()} trashes {card} from the Supply.", "trash")
        return ok

    def put_hand_in_deck(self, card: str, from_top: int) -> None:
        """Put a card from hand into the draw pile with ``from_top`` cards above it."""
        self._me().hand.remove(card)
        zones.insert_into_deck(self._state, self.player, card, from_top)
        self.log(f"{self._name()} puts a card from their hand into their deck.")

    def pass_cards(self, choices: dict) -> None:
        """Masquerade: every player in ``choices`` (player -> card from their hand) passes
        that card to the next player in turn order, all at the same time."""
        n = len(self._state.players)
        players = self._state.players
        receivers = {}
        for p in choices:
            nxt = [(p + k) % n for k in range(1, n) if not players[(p + k) % n].invisible]
            receivers[p] = nxt[0] if nxt else None          # an invisible player is skipped over
        for p, card in choices.items():
            players[p].hand.remove(card)
        for p, card in choices.items():
            target = receivers[p]
            if target is None:                              # nobody to pass to: the card comes back
                players[p].hand.append(card)
                continue
            players[target].hand.append(card)
            self.log(f"{self._name(p)} passes a card to {self._name(target)}.")

    def reduce_costs(self, amount: int) -> None:
        self._state.cost_reduction += amount
        self.log(f"Cards cost ${self._state.cost_reduction} less this turn.")

    # ---- Catastrophe helpers
    def trash_self(self) -> bool:
        """Trash this card from play. False if it is no longer in play (e.g. a
        Throne Room'd card on its second play), in which case the effect must stop."""
        if self.source not in self._me().in_play:
            return False
        zones.move_card(self._state, self.player, self.source, "in_play", "trash")
        self.log(f"{self._name()} trashes {self.source}.")
        return True

    def skip_next_turn(self, player: int) -> bool:
        """Make ``player`` skip their next turn, unless they already will or
        were just skipped (they are protected until they take a turn)."""
        target = self._state.players[player]
        if target.skips > 0 or target.skip_protected:
            self.log(f"{target.name} cannot be skipped right now.")
            return False
        target.skips += 1
        self.log(f"{target.name} will skip their next turn.")
        return True

    def swap_top_cards(self, other: int, limit: int) -> int:
        """Swap the top cards of the draw piles of this player and ``other``:
        the same number each way (the smaller pile, at most ``limit``), order kept."""
        mine, theirs = self._me(), self._state.players[other]
        k = min(len(mine.deck), len(theirs.deck), limit)
        if k:
            mine.deck[-k:], theirs.deck[-k:] = theirs.deck[-k:], mine.deck[-k:]
        return k

    def redistribute_all_cards(self) -> None:
        players = self._state.players
        taking_part = [i for i, p in enumerate(players) if not p.invisible or i == self.player]
        before = {i: self.owned(i) for i in taking_part}
        for i, p in enumerate(players):
            if i not in taking_part:
                self.log(f"{p.name} is invisible and keeps their cards.", "reveal")
        zones.redistribute_all_cards(self._state, no_new_hand_for=self.player)
        self.log("Every deck is combined, shuffled and dealt out again.")
        self.log_card_changes(before)

    def grand_swap_with(self, other: int) -> None:
        before = {i: self.owned(i) for i in (self.player, other)}
        zones.grand_swap(self._state, self.player, other)
        self.log(f"{self._name()} and {self._name(other)} swap their draw and discard piles "
                 "(Victory and Curse cards stay where they are).")
        self.log_card_changes(before)

    def snap(self, players: Sequence[int]) -> None:
        """The Snap: each listed player trashes half (rounded down) of the cards in their
        draw pile, hand and discard pile, chosen at random."""
        for i in players:
            p = self._state.players[i]
            total = len(p.deck) + len(p.hand) + len(p.discard)
            removed = zones.remove_random_cards(self._state, i, ("deck", "hand", "discard"), total // 2)
            self._state.trash.extend(removed)
            self.log(f"{self._name(i)} loses {len(removed)} of {total} cards to the trash: {_tally(removed)}.", "trash")

    def purge(self, players: Sequence[int]) -> None:
        """The Purge: each listed player discards half (rounded down) of their draw pile, at random."""
        for i in players:
            p = self._state.players[i]
            total = len(p.deck)
            removed = zones.remove_random_cards(self._state, i, ("deck",), total // 2)
            p.discard.extend(removed)
            self.log(f"{self._name(i)} discards {len(removed)} of {total} cards from their draw pile: {_tally(removed)}.", "discard")

    def log_card_changes(self, before: dict) -> None:
        """Log, for each player in ``before`` (player -> tally from ``owned``), the cards they
        ended up with and lost compared to before: a 'who got what' summary."""
        for i, old in before.items():
            new = self.owned(i)
            gained = new - old
            lost = old - new
            parts = []
            if gained:
                parts.append("gets " + _tally(gained.elements()))
            if lost:
                parts.append("loses " + _tally(lost.elements()))
            if not parts:
                parts.append("keeps the same cards")
            self.log(f"{self._name(i)} {'; '.join(parts)} (now {sum(new.values())} cards).", "summary", 2)

    def lock_buys(self) -> None:
        self._state.buy_locked = True
        self._state.buys = 0

    # ---- Hinterlands: per-turn tallies, shuffling cards into the deck
    def bump_count(self, key: str) -> int:
        """Add one to this turn's tally for ``key`` and return the tally from BEFORE (0 the first time)."""
        before = self._state.turn_counts.get(key, 0)
        self._state.turn_counts[key] = before + 1
        return before

    def shuffle_into_deck(self, cards: Sequence[str]) -> None:
        """Inn: move these cards from the discard pile into the draw pile and shuffle it."""
        me = self._me()
        for card in cards:
            me.discard.remove(card)
        me.deck.extend(cards)
        self._state.rng.shuffle(me.deck)
        self.log(f"{self._name()} shuffles {len(cards)} Action card(s) from their discard pile into their deck.")

    # ---- Dark Ages: mixed piles, Spoils / Madman / Mercenary, trashing
    def top_of_pile(self, pile: str) -> Optional[str]:
        """The card on top of a mixed pile (Knights, Ruins), or None when it is empty."""
        stack = self._state.stacks.get(pile)
        return stack[0] if stack else None

    def gain_top(self, pile: str, player: Optional[int] = None) -> bool:
        """Gain the top card of a mixed pile (Ruins for the Looters)."""
        card = self.top_of_pile(pile)
        return card is not None and self.gain(card, player)

    def trash_from_discard(self, card: str) -> None:
        zones.move_card(self._state, self.player, card, "discard", "trash")
        self.log(f"{self._name()} trashes {card} from their discard pile.", "trash")

    def trash_in_play(self, card: str) -> bool:
        """Trash a card of yours that is in play (Counterfeit, Procession). False if it is not there any more."""
        if card not in self._me().in_play:
            return False
        zones.move_card(self._state, self.player, card, "in_play", "trash")
        self.log(f"{self._name()} trashes {card}.", "trash")
        return True

    def return_in_play_to_offsupply(self, card: str) -> bool:
        """Spoils and Madman: return this card from play to its pile outside the Supply. False if it is not in play."""
        s = self._state
        if card not in self._me().in_play or card not in s.offsupply:
            return False
        self._me().in_play.remove(card)
        s.offsupply[card] += 1
        self.log(f"{self._name()} returns {card} to its pile.")
        return True

    def trade_in_play_for_offsupply(self, card: str, new: str) -> bool:
        """Hermit: return ``card`` from play to the Supply and gain ``new`` (from a pile outside the Supply) instead."""
        s = self._state
        me = self._me()
        if card not in me.in_play or card not in s.supply or s.offsupply.get(new, 0) <= 0:
            return False
        me.in_play.remove(card)
        s.supply[card] += 1
        self.log(f"{self._name()} trades {card} for {new}.", "gain")
        return zones.gain_offsupply(s, self.player, new)

    def take_trashed_to_hand(self, card: str) -> bool:
        """Fortress: a card that was just trashed goes into its owner's hand instead. False if it is not in the trash."""
        s = self._state
        if card not in s.trash:
            return False
        s.trash.remove(card)
        self._me().hand.append(card)
        self.log(f"{self._name()} puts {card} from the trash into their hand.")
        return True

    def play_as(self, card: str):
        """Generator (Band of Misfits): run ``card``'s effect as if this card were that card. ``yield from ctx.play_as(card)``."""
        self._state.plays_this_turn += 1
        result = get_card(card).on_play(EffectContext(self._state, self.player, self.source))
        if inspect.isgenerator(result):
            yield from result

    def attack_cards_in_play_of(self, player: int) -> int:
        return sum(1 for c in self._state.players[player].in_play if get_card(c).is_type(CardType.ATTACK))

    # ---- Adventures: Journey token, Tavern mat, Traveller exchanges, pile tokens
    def flip_journey(self) -> bool:
        """Turn the Journey token over; returns True if it is now face up."""
        me = self._me()
        me.journey_up = not me.journey_up
        self.log(f"{me.name} turns their Journey token {'face up' if me.journey_up else 'face down'}.")
        return me.journey_up

    def to_tavern(self, source: str = "in_play", card: Optional[str] = None) -> bool:
        """Put this card (or ``card``) on the Tavern mat. False if it is no longer where it was (a Throne Room'd Reserve card)."""
        name = self.source if card is None else card
        if name not in getattr(self._me(), source):
            return False
        zones.move_card(self._state, self.player, name, source, "tavern")
        self.log(f"{self._name()} puts {name} on their Tavern mat.")
        return True

    def action_piles(self, no_token: Optional[str] = None) -> tuple:
        """Action Supply piles (a token can be put on them); with ``no_token`` only piles this player has no token of that kind on."""
        s = self._state
        me = self._me()
        names = [n for n in sorted(s.supply) if n not in s.stack_of and get_card(n).is_type(CardType.ACTION)]
        if "Knights" in s.stacks:
            names.append("Knights")
        if no_token is not None:
            names = [n for n in names if n not in me.tokens.values()]
        return tuple(names)

    def move_token(self, token: str, pile: str) -> None:
        self._me().tokens[token] = pile
        self.log(f"{self._name()} puts their {token} token on the {pile} pile.")

    def exchange_in_play(self, card: str, new: str) -> bool:
        """Traveller: return ``card`` (in play) to its pile and take ``new`` from its pile into the discard pile (not a gain)."""
        s = self._state
        if card not in self._me().in_play or s.offsupply.get(new, 0) <= 0:
            return False
        self._me().in_play.remove(card)
        if card in s.offsupply:
            s.offsupply[card] += 1
        else:
            s.supply[card] = s.supply.get(card, 0) + 1
        s.offsupply[new] -= 1
        self._me().discard.append(new)
        self.log(f"{self._name()} exchanges {card} for {new}.", "gain")
        return True

    def give_minus_coin(self, player: int) -> None:
        """``player`` takes the -$1 token (Bridge Troll, Ball)."""
        p = self._state.players[player]
        if not p.minus_coin:
            p.minus_coin = True
            self.log(f"{p.name} takes the -$1 token.")

    def mark_mission(self) -> bool:
        """Mission: an extra turn follows this one (not directly after another extra Mission turn). False if it has no effect."""
        s = self._state
        if s.mission_turn:
            self.log("Mission has no effect: this is already a Mission turn.")
            return False
        s.mission_flag = True
        self.log(f"{self._name()} will take another turn after this one, without buying cards.")
        return True

    def pile_of(self, card: str) -> str:
        return self._state.stack_of.get(card, card)

    def inherit(self, card: str) -> bool:
        """Inheritance: set a Supply card aside on the Estate mat; the player's Estates now play as it."""
        s = self._state
        me = self._me()
        if me.inherited is not None or s.supply.get(card, 0) <= 0:
            return False
        s.supply[card] -= 1
        me.inherited = card
        self.log(f"{self._name()} sets {card} aside on their Estate mat. Their Estates are now Action cards that play as {card}.", "gain")
        return True

    def duration_entries(self, source: str) -> list:
        return [e for e in self._me().durations if e.source == source]

    def hand_to_set_aside(self, player: int) -> list:
        """Move a player's whole hand to their set-aside zone (Haunted Woods); returns the cards."""
        p = self._state.players[player]
        cards = list(p.hand)
        p.set_aside.extend(cards)
        p.hand.clear()
        return cards

    def take_minus_card(self, player: int) -> bool:
        """Put the -1 Card token on ``player``'s deck (False if it is already there)."""
        p = self._state.players[player]
        if p.minus_card:
            return False
        p.minus_card = True
        self.log(f"{p.name} puts their -1 Card token on their deck.")
        return True

    @property
    def my_turn(self) -> bool:
        return self._state.current_player == self.player

    @property
    def in_buy_phase(self) -> bool:
        return self._state.current_player == self.player and self._state.phase.value == "buy"

    @property
    def in_action_phase(self) -> bool:
        return self._state.phase.value == "action"

    def consume_count(self, key: str) -> bool:
        """Use up one of this turn's tallies (see ``bump_count``). False if there was none."""
        n = self._state.turn_counts.get(key, 0)
        if n <= 0:
            return False
        self._state.turn_counts[key] = n - 1
        return True

    def enchant(self, player: int) -> None:
        self._state.players[player].enchanted += 1
        self.log(f"{self._name(player)} is enchanted: the first Action they play next turn only gives +1 Card and +1 Action.", "reveal")

    def unenchant(self, player: int) -> None:
        p = self._state.players[player]
        p.enchanted = max(0, p.enchanted - 1)

    def gained_this_turn(self) -> tuple:
        return tuple(self._me().gained_turn)

    def supply_pile_names(self) -> tuple:
        """The top card of every Supply pile that can take Debt (Tax): every pile except the house-rule piles."""
        s = self._state
        return tuple(n for n in sorted(s.supply) if n not in s.catastrophes and not is_buried(s, n))

    def add_pile_debt(self, card: str, n: int) -> None:
        pile = self._state.stack_of.get(card, card)
        self._state.pile_debt[pile] = self._state.pile_debt.get(pile, 0) + n
        self.log(f"{self._name()} adds {n} Debt to the {pile} pile ({self._state.pile_debt[pile]} on it).", "info")

    def shuffle_discard_into_deck_except(self, keep: Sequence[str]) -> None:
        """Annex: every card of the discard pile except the ``keep`` ones is shuffled into the draw pile."""
        me = self._me()
        rest = list(me.discard)
        for card in keep:
            rest.remove(card)
        me.discard = list(keep)
        me.deck.extend(rest)
        self._state.rng.shuffle(me.deck)
        self.log(f"{self._name()} shuffles {len(rest)} card(s) from their discard pile into their deck.")

    # ---- Empires: Debt, VP piles, split piles, Villa, Enchantress
    @property
    def debt(self) -> int:
        return self._me().debt

    def add_debt(self, n: int, player: Optional[int] = None) -> None:
        i = self.player if player is None else player
        if n > 0:
            self._state.players[i].debt += n
            self.log(f"{self._name(i)} takes {n} Debt token{'s' if n != 1 else ''} ({self._state.players[i].debt} in all).", "info")

    def pay_off_debt(self, n: int) -> int:
        """Spend up to ``n`` $ (of the $ this turn) to remove Debt tokens. Returns how many were removed."""
        s = self._state
        paid = max(0, min(n, self._me().debt, s.coins))
        if paid:
            self._me().debt -= paid
            s.coins -= paid
            self.log(f"{self._name()} pays off {paid} Debt token{'s' if paid != 1 else ''}.", "treasure")
        return paid

    def pile_of_card(self, card: str) -> str:
        return self._state.stack_of.get(card, card)

    def pile_vp(self, pile: str) -> int:
        return self._state.pile_vp.get(pile, 0)

    def add_pile_vp(self, pile: str, n: int = 1) -> None:
        self._state.pile_vp[pile] = self._state.pile_vp.get(pile, 0) + n
        self.log(f"1 VP is added to the {pile} pile ({self._state.pile_vp[pile]} on it)." if n == 1
                 else f"{n} VP are added to the {pile} pile ({self._state.pile_vp[pile]} on it).", "info")

    def take_pile_vp(self, pile: str) -> int:
        """Take every VP token that lies on a Supply pile."""
        n = self._state.pile_vp.get(pile, 0)
        if n:
            self._state.pile_vp[pile] = 0
            self.add_vp(n)
        return n

    def top_of_deck(self, player: Optional[int] = None) -> Optional[str]:
        """Reveal the top card of a deck without moving it (the discard pile is shuffled into the deck first if needed)."""
        i = self.player if player is None else player
        me = self._state.players[i]
        if not me.deck and me.discard:
            shuffled, me.discard = me.discard, []
            self._state.rng.shuffle(shuffled)
            me.deck = shuffled
        return me.deck[-1] if me.deck else None

    def costs_more(self, a: str, b: str) -> bool:
        return costs_more(self._state, a, b)

    def same_cost_cards(self, card: str) -> tuple:
        """Supply cards that can be gained and cost exactly the same as ``card`` (coins, Potions and Debt), under another name."""
        s = self._state
        target = full_cost(s, card)
        return tuple(n for n in sorted(s.supply)
                     if n != card and s.supply[n] > 0 and not is_walled(s, n, self.player) and not is_buried(s, n)
                     and full_cost(s, n) == target)

    def put_gained_in_hand(self, event) -> bool:
        """Move a card that was just gained (and has not been moved since) into its owner's hand."""
        me = self._me()
        if event.zone is None or event.card not in getattr(me, event.zone):
            return False
        zone = getattr(me, event.zone)
        zone.pop(len(zone) - 1 - zone[::-1].index(event.card))
        me.hand.append(event.card)
        event.zone = "hand"
        self.log(f"{self._name()} puts the gained {event.card} into their hand.")
        return True

    def set_phase_to_action(self) -> None:
        s = self._state
        if s.phase.value == "buy" and s.current_player == self.player:
            from .state import Phase
            s.phase = Phase.ACTION
            self.log(f"{self._name()} returns to their Action phase.", "phase")

    def archive_set_aside(self, count: int) -> list:
        cards = zones.take_top_cards(self._state, self.player, count)
        self._me().archived.extend(cards)
        self.log(f"{self._name()} sets aside the top {len(cards)} card(s) of their deck face down.")
        return cards

    def archive_to_hand(self, card: str) -> None:
        zones.move_card(self._state, self.player, card, "archived", "hand")

    def return_to_pile(self, card: str) -> bool:
        """Encampment: return a card from play to the TOP of its Supply pile."""
        s = self._state
        me = self._me()
        if card not in me.in_play or card not in s.supply:
            return False
        me.in_play.remove(card)
        s.supply[card] += 1
        pile = s.stack_of.get(card)
        if pile is not None:
            s.stacks[pile].insert(0, card)
        self.log(f"{self._name()} returns {card} to the Supply.")
        return True

    def take_landmark_vp(self, landmark: str, n: int) -> int:
        """Take up to ``n`` VP from a Landmark's pool."""
        s = self._state
        got = max(0, min(n, s.landmark_vp.get(landmark, 0)))
        if got:
            s.landmark_vp[landmark] -= got
            self.add_vp(got)
            self.log(f"({landmark}: {s.landmark_vp[landmark]} VP left)", "info", 2)
        return got

    # ---- Renaissance: Villagers, Projects, Artifacts
    def add_villagers(self, n: int, player: Optional[int] = None) -> None:
        i = self.player if player is None else player
        if n > 0:
            self._state.players[i].villagers += n
            self.log(f"{self._name(i)} takes {n} Villager{'s' if n != 1 else ''} ({self._state.players[i].villagers} in all).", "gain")

    @property
    def villagers(self) -> int:
        return self._me().villagers

    def take_project(self) -> None:
        """Buying a Project puts one of the buyer's cubes on it."""
        me = self._me()
        if self.source not in me.projects:
            me.projects.append(self.source)
        self.log(f"{self._name()} puts a cube on {self.source}.", "buy")

    def artifact_owner(self, name: str) -> Optional[int]:
        return self._state.artifacts.get(name)

    def take_artifact(self, name: str) -> None:
        """Take an Artifact, from whoever has it (it is only ever with one player)."""
        s = self._state
        before = s.artifacts.get(name)
        s.artifacts[name] = self.player
        self.log(f"{self._name()} takes the {name}" + (f" from {self._name(before)}." if before is not None and before != self.player else "."), "gain")

    def add_duration_entry(self, handler=None, data=None, cards: Optional[Sequence[str]] = None):
        """Like ``add_duration`` but returns the entry, so later events can fill in its ``data`` (Cargo Ship)."""
        entry = DurationEntry(self.source, tuple(cards) if cards is not None else (self.source,), handler, data)
        self._me().durations.append(entry)
        return entry

    def played_this_turn(self) -> tuple:
        """Names of the Action cards played this turn that are still in play (Scepter may replay one)."""
        s = self._state
        in_play = list(self._me().in_play)
        return tuple(sorted({c for c in s.played_log if c in in_play and get_card(c).is_type(CardType.ACTION)}))

    # ---- Nocturne: Night phase, Boons, Hexes, States, exchanges, playing from the trash
    @property
    def in_night_phase(self) -> bool:
        return self._state.phase.value == "night" and self._state.current_player == self.player

    def draw_boon(self) -> Optional[str]:
        """Take the top Boon (the discard pile is shuffled into the deck first if it is empty). None if there is none."""
        s = self._state
        if not s.boons:
            if not s.boons_discard:
                self.log("There are no Boons left to take.")
                return None
            s.boons, s.boons_discard = list(s.boons_discard), []
            s.rng.shuffle(s.boons)
            self.log("The Boons discard pile is shuffled to form a new Boons deck.", "info")
        return s.boons.pop(0)

    def draw_hex(self) -> Optional[str]:
        s = self._state
        if not s.hexes:
            if not s.hexes_discard:
                self.log("There are no Hexes left to take.")
                return None
            s.hexes, s.hexes_discard = list(s.hexes_discard), []
            s.rng.shuffle(s.hexes)
            self.log("The Hexes discard pile is shuffled to form a new Hexes deck.", "info")
        return s.hexes.pop(0)

    def discard_boon(self, boon: str, received: bool = True) -> None:
        """A Boon that was received goes to the discard pile, except The Field's, Forest's and River's Gifts, which stay in
        front of the turn's player until Clean-up. A Boon that was not received (Pixie) is simply discarded."""
        from ..cards.nocturne import KEPT_BOONS
        s = self._state
        (s.kept_boons if received and boon in KEPT_BOONS else s.boons_discard).append(boon)

    def receive_boon(self, boon: Optional[str] = None, receiver: Optional[int] = None, dispose: bool = True):
        """Generator: ``receiver`` (default: this player) receives ``boon`` (default: the top Boon). Returns the Boon's name
        (None if there was none). With ``dispose=False`` the caller decides where the Boon goes (Druid, Pixie)."""
        from ..cards.nocturne import BOON_FUNCS
        s = self._state
        who = self.player if receiver is None else receiver
        if boon is None:
            boon = self.draw_boon()
            if boon is None:
                return None
        s.log.append(f"{self._name(who)} receives {boon}.", "boon", 1)
        result = BOON_FUNCS[boon](EffectContext(s, who, boon))
        if inspect.isgenerator(result):
            yield from result
        if dispose:
            self.discard_boon(boon)
        return boon

    def receive_hex(self, targets: Optional[Sequence[int]] = None):
        """Generator: the next Hex is turned over and every player in ``targets`` (default: this player) receives it, in turn
        order. Nothing is turned over when there is nobody to receive it. Returns the Hex's name."""
        from ..cards.nocturne import HEX_FUNCS
        s = self._state
        receivers = [self.player] if targets is None else list(targets)
        if not receivers:
            return None
        hex_name = self.draw_hex()
        if hex_name is None:
            return None
        for p in receivers:
            s.log.append(f"{self._name(p)} receives {hex_name}.", "hex", 1)
            result = HEX_FUNCS[hex_name](EffectContext(s, p, hex_name))
            if inspect.isgenerator(result):
                yield from result
        s.hexes_discard.append(hex_name)
        return hex_name

    def hold_boon(self, boon: str) -> None:
        self._me().held_boons.append(boon)
        self.log(f"{self._name()} saves {boon} for the start of their next turn.", "boon")

    @property
    def druid_boons(self) -> tuple:
        return tuple(self._state.druid_boons)

    def add_river_draw(self) -> None:
        """The River's Gift: this player draws a card at the end of this turn (after the turn's player draws their hand)."""
        self._state.river_draws.append(self.player)

    def take_deluded(self) -> bool:
        me = self._me()
        if me.deluded or me.envious:
            return False
        me.deluded = True
        self.log(f"{me.name} takes Deluded.", "hex")
        return True

    def take_envious(self) -> bool:
        me = self._me()
        if me.deluded or me.envious:
            return False
        me.envious = True
        self.log(f"{me.name} takes Envious.", "hex")
        return True

    def take_miserable(self) -> int:
        me = self._me()
        me.miserable = min(2, me.miserable + 1)
        self.log(f"{me.name} is now {'Miserable (-2 VP)' if me.miserable == 1 else 'Twice Miserable (-4 VP)'}.", "hex")
        return me.miserable

    @property
    def lost_in_woods_holder(self) -> Optional[int]:
        return self._state.lost_in_woods

    def take_lost_in_woods(self) -> None:
        s = self._state
        before = s.lost_in_woods
        s.lost_in_woods = self.player
        self.log(f"{self._name()} takes Lost in the Woods" + (f" from {self._name(before)}." if before is not None else "."), "boon")

    def supply_cards_of_type(self, card_type: CardType) -> tuple:
        """Every Supply pile that can be gained right now and whose card has this type, whatever it costs."""
        s = self._state
        return tuple(n for n in sorted(s.supply) if s.supply[n] > 0 and not is_walled(s, n, self.player)
                     and not is_buried(s, n) and has_type(s, n, card_type))

    def cheaper_sharing_type(self, card: str) -> tuple:
        """Locusts: Supply piles that cost less than ``card`` (every part of the cost) and share a type with it."""
        s = self._state
        mine = set(type_values(s, card))
        return tuple(n for n in sorted(s.supply) if s.supply[n] > 0 and not is_walled(s, n, self.player) and not is_buried(s, n)
                     and costs_more(s, card, n) and mine & set(type_values(s, n)))

    def can_return_gained(self, event) -> bool:
        s = self._state
        return (self.gained_card_present(event)
                and (event.card in s.supply or event.card in s.offsupply or event.card in s.stack_of))

    def exchange_gained_for(self, event, new: str) -> bool:
        """Changeling: return the card that was just gained to its pile and take ``new`` from the Supply into the discard pile.
        This is an exchange, not a gain."""
        s = self._state
        me = self._me()
        if not self.can_return_gained(event) or s.supply.get(new, 0) <= 0:
            return False
        zone = getattr(me, event.zone)
        zone.pop(len(zone) - 1 - zone[::-1].index(event.card))
        pile = s.stack_of.get(event.card)
        if event.card in s.supply or pile is not None:
            s.supply[event.card] = s.supply.get(event.card, 0) + 1
            if pile is not None:
                s.stacks[pile].insert(0, event.card)
        else:
            s.offsupply[event.card] += 1
        s.supply[new] -= 1
        me.discard.append(new)
        self.log(f"{self._name()} exchanges the gained {event.card} for {new}.", "gain")
        event.zone = None
        return True

    def exchange_in_play_for(self, card: str, new: str) -> bool:
        """Vampire and Bat: return ``card`` (in play) to its pile and put ``new`` (from the Supply or a pile outside it) into the
        discard pile. Not a gain. Nothing happens if the card is not in play any more or the other pile is empty."""
        s = self._state
        me = self._me()
        in_supply = s.supply.get(new, 0) > 0
        if card not in me.in_play or not (in_supply or s.offsupply.get(new, 0) > 0):
            return False
        me.in_play.remove(card)
        if card in s.offsupply:
            s.offsupply[card] += 1
        else:
            s.supply[card] = s.supply.get(card, 0) + 1
        if in_supply:
            s.supply[new] -= 1
        else:
            s.offsupply[new] -= 1
        me.discard.append(new)
        self.log(f"{self._name()} exchanges {card} for {new}.", "gain")
        return True

    def shuffle_set_aside_into_deck(self, cards: Sequence[str]) -> None:
        """Famine: set-aside cards are shuffled into the draw pile."""
        me = self._me()
        for card in cards:
            me.set_aside.remove(card)
        me.deck.extend(cards)
        self._state.rng.shuffle(me.deck)
        self.log(f"{self._name()} shuffles {len(cards)} card(s) into their deck.")

    def copies_available(self, names: Sequence[str]) -> tuple:
        """Changeling: those of ``names`` that can be gained right now, from the Supply or from a pile outside it."""
        s = self._state
        return tuple(sorted(n for n in set(names) if (s.supply.get(n, 0) > 0 and not is_walled(s, n, self.player) and not is_buried(s, n))
                            or s.offsupply.get(n, 0) > 0))

    def gain_copy(self, card: str) -> bool:
        return self.gain(card) if self._state.supply.get(card, 0) > 0 else self.gain_from_offsupply(card)

    def trash_actions_for_necromancer(self) -> tuple:
        """Face-up, non-Duration Action cards in the trash (a copy already played this turn is face down)."""
        s = self._state
        out = []
        for name in sorted(set(s.trash)):
            card = get_card(name)
            if not card.is_type(CardType.ACTION) or card.is_type(CardType.DURATION):
                continue
            if s.trash.count(name) - s.turn_counts.get("necro:" + name, 0) > 0:
                out.append(name)
        return tuple(out)

    def play_from_trash(self, card: str):
        """Generator (Necromancer): play an Action card from the trash, leaving it there and turning it face down for the turn."""
        s = self._state
        s.turn_counts["necro:" + card] = s.turn_counts.get("necro:" + card, 0) + 1
        s.plays_this_turn += 1
        self.log(f"{self._name()} plays {card} from the trash.", "play")
        yield from urchin_steps(s, self.player, card)
        apply_play_bonuses(s, self.player, card)
        result = get_card(card).on_play(EffectContext(s, self.player, card))
        if inspect.isgenerator(result):
            yield from result
        yield from call_steps(s, self.player, "after_action", card)

    # ---- Menagerie: Exile, Horses, Ways, delayed plays
    def exile_hand_card(self, card: str, player: Optional[int] = None) -> None:
        i = self.player if player is None else player
        zones.move_card(self._state, i, card, "hand", "exile")
        self.log(f"{self._name(i)} Exiles {card}.")

    def exile_in_play(self, card: str) -> bool:
        if card not in self._me().in_play:
            return False
        zones.move_card(self._state, self.player, card, "in_play", "exile")
        self.log(f"{self._name()} Exiles {card}.")
        return True

    def exile_set_aside(self, card: str, player: Optional[int] = None) -> None:
        i = self.player if player is None else player
        zones.move_card(self._state, i, card, "set_aside", "exile")
        self.log(f"{self._name(i)} Exiles {card}.")

    def exile_from_supply(self, card: str, player: Optional[int] = None) -> bool:
        """Put a card from the Supply on a player's Exile mat (not a gain)."""
        i = self.player if player is None else player
        ok = zones.exile_from_supply(self._state, i, card)
        if ok:
            self.log(f"{self._name(i)} Exiles {card} from the Supply.")
        return ok

    def exilable_supply(self, action_only: bool = False, non_victory: bool = False) -> tuple:
        """Supply cards that can be Exiled right now (the top card of a mixed pile only)."""
        s = self._state
        return tuple(n for n in sorted(s.supply)
                     if s.supply[n] > 0 and not is_buried(s, n)
                     and (not action_only or get_card(n).is_type(CardType.ACTION))
                     and (not non_victory or not get_card(n).is_type(CardType.VICTORY)))

    def exile_of(self, player: Optional[int] = None) -> tuple:
        return tuple(self._state.players[self.player if player is None else player].exile)

    def exile_to_deck(self, card: str) -> None:
        zones.move_card(self._state, self.player, card, "exile", "deck")
        self.log(f"{self._name()} puts {card} from their Exile mat onto their deck.")

    def discard_from_exile(self, card: str, player: Optional[int] = None) -> None:
        i = self.player if player is None else player
        zones.move_card(self._state, i, card, "exile", "discard")
        zones.tunnel_discarded(self._state, i, card)

    def invest_in(self, card: str) -> None:
        """Invest: the Exiled copy is remembered; every time another player gains or Invests in a copy, its owner draws 2."""
        s = self._state
        me = self._me()
        for k in range(1, len(s.players)):                 # other players with an Invested copy draw 2 cards per copy
            o = (self.player + k) % len(s.players)
            copies = min(s.players[o].invested.get(card, 0), s.players[o].exile.count(card))
            if copies:
                self.log(f"{s.players[o].name}'s Invest pays off: {self._name()} invests in {card}.")
                EffectContext(s, o, "Invest").draw(2 * copies)
        me.invested[card] = me.invested.get(card, 0) + 1

    def gain_horse(self, player: Optional[int] = None, destination: str = "discard") -> bool:
        return self.gain_from_offsupply("Horse", player, destination)

    def return_to_horse_pile(self, card: str) -> bool:
        """Return a card in play to its pile, whether that pile is in the Supply or outside it (Horse, Way of the Horse / Butterfly)."""
        if card in self._state.offsupply:
            return self.return_in_play_to_offsupply(card)
        return self.return_to_pile(card)

    def set_aside_delayed(self, card: str, source: str = "hand") -> None:
        zones.move_card(self._state, self.player, card, source, "delayed")

    def forbid_more_actions(self) -> None:
        self._state.no_more_actions = True

    def last_gained_name(self) -> Optional[str]:
        return self._state.last_gain

    def mouse_card(self) -> Optional[str]:
        return self._state.mouse

    def turn_order_from_current(self, exclude_self: bool = True) -> list:
        n = len(self._state.players)
        order = [(self._state.current_player + k) % n for k in range(n)]
        return [p for p in order if not (exclude_self and p == self.player)]

    def trashed_by_right_neighbour(self) -> int:
        """Goatherd: cards the player to your right trashed on their last turn."""
        n = len(self._state.players)
        return self._state.players[(self.player - 1) % n].trashed_last

    def add_gatekeeper(self, target: int) -> None:
        self._state.gatekeepers.append((self.player, target))

    def add_delayed_play(self, label: str, handler, data) -> None:
        """Delay, Reap, Way of the Turtle: at the start of this player's next turn ``handler(ctx, entry)`` plays the card set aside."""
        self._me().durations.append(DurationEntry(label, (), handler, data))

    def play_mouse(self):
        """Way of the Mouse: play the set-aside Action, leaving it there (it never moves)."""
        mouse = self._state.mouse
        if mouse is None:
            return
        self.log(f"{self._name()} plays {mouse} from the set-aside pile.", "play")
        result = get_card(mouse).on_play(EffectContext(self._state, self.player, mouse))
        if inspect.isgenerator(result):
            yield from result

    def arm_kiln(self) -> None:
        self._state.turn_counts["kiln"] = self._state.turn_counts.get("kiln", 0) + 1

    def add_monkey(self) -> None:
        self._me().monkey += 1

    def add_squirrel(self, n: int) -> None:
        self._me().squirrel += n

    def frog(self, card: str) -> None:
        self._state.frogged.append(card)

    def populate_cards(self) -> tuple:
        """Populate: the top card of every Action Supply pile that has a card in it (Castles are not Action piles)."""
        s = self._state
        out = []
        for pile in [*s.kingdom, *([s.bane] if s.bane else [])]:
            if pile == "Castles":
                continue
            if pile in s.stacks:
                stack = s.stacks[pile]
                if stack and s.supply.get(stack[0], 0) > 0 and get_card(stack[0]).is_type(CardType.ACTION):
                    out.append(stack[0])
            elif s.supply.get(pile, 0) > 0 and get_card(pile).is_type(CardType.ACTION) and not is_walled(s, pile, self.player):
                out.append(pile)
        return tuple(out)

    def queue_seize_the_day(self) -> None:
        self._me().seize_used = True
        self._state.seize_flag = True
        self.log(f"{self._name()} will take an extra turn after this one.", "skip")

    # ---- Allies: Favors, rotating split piles, extra choices (Elder)
    @property
    def favors(self) -> int:
        return self._me().favors

    def add_favors(self, n: int, player: Optional[int] = None) -> None:
        i = self.player if player is None else player
        self._state.players[i].favors += n
        self.log(f"{self._name(i)} gets +{n} Favor{'s' if n != 1 else ''} ({self._state.players[i].favors} in all).", "info")

    def spend_favors(self, n: int) -> bool:
        me = self._me()
        if me.favors < n:
            return False
        me.favors -= n
        self.log(f"{self._name()} spends {n} Favor{'s' if n != 1 else ''} ({me.favors} left).", "info")
        return True

    def pay_coins(self, n: int) -> bool:
        """Pay $n of the $ you have (Capital City); False if you have less."""
        if self._state.coins < n:
            return False
        self._state.coins -= n
        self.log(f"{self._name()} pays ${n}.", "treasure")
        return True

    def discard_from_play(self, card: str) -> bool:
        if card not in self._me().in_play:
            return False
        zones.move_card(self._state, self.player, card, "in_play", "discard")
        self.log(f"{self._name()} discards {card} from play.")
        return True

    def put_hand_under_deck(self, card: str) -> None:
        me = self._me()
        me.hand.remove(card)
        me.deck.insert(0, card)
        self.log(f"{self._name()} puts a card from their hand on the bottom of their deck.")

    def push_elder(self, card: str) -> None:
        self._state.elder_cards.append(card)

    def pop_elder(self, card: str) -> None:
        if card in self._state.elder_cards:
            self._state.elder_cards.remove(card)

    def trash_to_discard(self, card: str) -> bool:
        """Lich: the card that was just trashed is discarded from the trash (this is not a gain)."""
        s = self._state
        if card not in s.trash:
            return False
        s.trash.remove(card)
        self._me().discard.append(card)
        self.log(f"{self._name()} discards {card} from the trash.")
        return True

    def pile_top(self, pile: str):
        stack = self._state.stacks.get(pile)
        return stack[0] if stack else None

    def take_in_play_to_hand(self, card: str) -> bool:
        if card not in self._me().in_play:
            return False
        zones.move_card(self._state, self.player, card, "in_play", "hand")
        self.log(f"{self._name()} puts {card} into their hand.")
        return True

    def shuffle_count(self) -> int:
        return self._state.shuffles

    def rotate_pile(self, pile: str) -> bool:
        """Rotating a pile: the top card and every copy directly under it go to the bottom."""
        stack = self._state.stacks.get(pile)
        if not stack:
            return False
        top = stack[0]
        k = 0
        while k < len(stack) and stack[k] == top:
            k += 1
        if k == len(stack):
            return False
        stack[:] = stack[k:] + stack[:k]
        self.log(f"{self._name()} rotates the {pile} pile: {stack[0]} is now on top.", "info")
        return True

    def rotatable_piles(self) -> tuple:
        return tuple(p for p, st in self._state.stacks.items() if len(set(st)) > 1)

    def choose_modes(self, prompt: str, options: tuple):
        """Generator for a \"choose one\" ability: yields the decision and returns the options picked, in the order they are listed on
        the card. Elder lets the card Elder is playing pick one extra, different option."""
        extra = bool(self._state.elder_cards) and self.source in self._state.elder_cards
        picked = yield self.choose(prompt + (" (Elder: you may pick a second, different option.)" if extra else ""), tuple(options), 1, 2 if extra else 1)
        return tuple(o for o in options if o in picked)

    def return_hand_card_to_pile(self, card: str) -> bool:
        """Swap: return a card from the hand to the top of its Supply pile (not a trash)."""
        s = self._state
        me = self._me()
        if card not in me.hand or card not in s.supply:
            return False
        me.hand.remove(card)
        s.supply[card] += 1
        pile = s.stack_of.get(card)
        if pile is not None:
            s.stacks[pile].insert(0, card)
        self.log(f"{self._name()} returns {card} to its pile.")
        return True

    def gainable_actions(self, without=()) -> tuple:
        """Action cards of any cost that can be gained from the Supply right now (not those in ``without``)."""
        s = self._state
        return tuple(n for n in sorted(s.supply) if s.supply[n] > 0 and n not in without and get_card(n).is_type(CardType.ACTION)
                     and not is_buried(s, n) and not is_walled(s, n, self.player))

    def deck_to_discard(self) -> int:
        me = self._me()
        n = len(me.deck)
        me.discard.extend(me.deck)
        me.deck.clear()
        self.log(f"{self._name()} puts their deck ({n} cards) into their discard pile.")
        return n

    def add_ally_pair(self, kind: str, target: int) -> None:
        pairs = {"highwayman": self._state.highwaymen, "warlord": self._state.warlords, "skirmisher": self._state.skirmishers}[kind]
        pairs.append((self.player, target))

    def pile_token(self, pile: str) -> None:
        s = self._state
        s.pile_tokens[pile] = s.pile_tokens.get(pile, 0) + 1

    def arm_garrison(self) -> None:
        self._state.turn_counts["Garrison"] = self._state.turn_counts.get("Garrison", 0) + 1

    def take_garrison_tokens(self) -> int:
        me = self._me()
        n, me.garrison_tokens = me.garrison_tokens, 0
        return n

    def queue_own_extra_turn(self, voyage: bool = False) -> None:
        """Voyage, Island Folk: this player takes another turn after this one (never a third in a row; checked in Clean-up)."""
        s = self._state
        s.seize_flag = True
        if voyage:
            s.voyage_flag = True

    def skip_own_turn(self) -> None:
        """Lich: skip a turn (each Lich played skips one more)."""
        self._me().skips += 1

    def look_at_top(self, count: int) -> list:
        return self.take_to_set_aside(count)

    def put_back_in_order(self, cards: list, prompt: str):
        """Generator: put cards that are set aside back onto the deck in an order the player picks (top card chosen first)."""
        order = []
        remaining = list(cards)
        while len(remaining) > 1:
            (pick,) = yield self.choose(prompt, tuple(sorted(set(remaining))))
            order.append(pick)
            remaining.remove(pick)
        order.extend(remaining)
        for card in reversed(order):
            self.put_set_aside_on_deck(card)

    # ---- Plunder: Loot, set-aside cards, Durations that wait for something
    def gain_loot(self, destination: str = "discard", player: Optional[int] = None) -> Optional[str]:
        """Gain the top card of the Loot pile (revealed). Returns its name, or None when the pile is empty."""
        s = self._state
        i = self.player if player is None else player
        if not s.loot:
            return None
        name = s.loot[0]
        if not zones.gain_offsupply(s, i, name, destination):
            return None
        taker = zones.beneficiary(s, i)
        where = "" if destination == "discard" or taker != i else f" to their {destination}"
        self.log(f"{self._name(taker)} gains a Loot: {name}{where}." + (" (Possession)" if taker != i else ""), "gain")
        return name

    def aside(self, card: str, source: str = "hand") -> None:
        """Set a card aside (Cage, Grotto, Quartermaster, Prepare...). It is still its owner's."""
        zones.move_card(self._state, self.player, card, source, "plunder_aside")

    def aside_to(self, card: str, destination: str, player: Optional[int] = None) -> None:
        zones.move_card(self._state, self.player if player is None else player, card, "plunder_aside", destination)

    def aside_cards(self) -> tuple:
        return tuple(self._me().plunder_aside)

    def eot_hand(self, card: str, source: str = "hand", player: Optional[int] = None) -> None:
        """Set a card aside; it goes into its owner's hand at the end of this turn (after the next hand was drawn)."""
        zones.move_card(self._state, self.player if player is None else player, card, source, "eot_hand")

    def gain_aside(self, card: str) -> bool:
        """Gain a card and set it aside at once (Quartermaster). Returns True only if the card really ended up set aside."""
        s = self._state
        if not self.gain(card):
            return False
        me = self._me()
        for event in reversed(s.gain_events):
            if event.card == card and event.player == self.player and event.zone is not None:
                zone = getattr(me, event.zone)
                if card in zone:
                    zone.pop(len(zone) - 1 - zone[::-1].index(card))
                    me.plunder_aside.append(card)
                    event.zone = None
                    return True
                break
        return False

    def add_wait(self, kind: str, data: Optional[dict] = None, cards: Optional[Sequence[str]] = None, handler=None) -> None:
        """A Duration that stays in play until something happens (``kind``); the card's ``wait`` hook then runs. It keeps waiting
        through its owner's start of turn (``persist``)."""
        entry_data = {"wait": kind, "persist": True, **(data or {})}
        self._me().durations.append(DurationEntry(self.source, tuple(cards) if cards is not None else (self.source,), handler, entry_data))

    def end_wait(self, entry) -> None:
        """The waiting is over: the card goes to the discard pile in the Clean-up of that turn (unless something else keeps it)."""
        durations = self._me().durations
        if entry in durations:
            durations.remove(entry)

    def all_in_play(self) -> tuple:
        return tuple(c for p in self._state.players for c in p.in_play)

    def loot_left(self) -> int:
        return len(self._state.loot)

    def trait_of(self, card: str) -> Optional[str]:
        s = self._state
        return s.traits.get(s.stack_of.get(card, card)) if s.traits else None

    def pile_empty_after(self, card: str) -> bool:
        s = self._state
        pile = s.stack_of.get(card)
        return (not s.stacks.get(pile)) if pile is not None else s.supply.get(card, 1) == 0

    def set_count(self, key: str, value: int) -> None:
        self._state.turn_counts[key] = value

    def previous_turn_was_mine(self) -> bool:
        return self._state.prev_turn == self.player

    def queue_journey_turn(self) -> None:
        s = self._state
        s.seize_flag = True
        s.turn_counts["journey_keep"] = 1
        self.log(f"{self._name()} takes an extra turn after this one, and leaves their cards in play.", "skip")

    def deck_to_bottom(self, card: str, source: str = "discard") -> None:
        me = self._me()
        getattr(me, source).remove(card)
        me.deck.insert(0, card)

    # ---- end-of-turn triggers
    def add_trigger(self, event: str, handler: Callable) -> None:
        self._state.triggers.append(Trigger(event, self.source, handler, self.player))

    # ---- decisions
    def choose(
        self,
        prompt: str,
        options: Sequence[str],
        min_choices: int = 1,
        max_choices: int = 1,
        player: Optional[int] = None,
    ) -> Decision:
        """Build a Decision to ``yield``. The yield evaluates to the chosen tuple."""
        i = self.player if player is None else player
        return Decision(i, prompt, tuple(options), min_choices, max_choices, self.source)

    def log(self, message: str, kind: Optional[str] = None, indent: int = 1) -> None:
        self._state.log.append(message, kind, indent)


def ally_after_play(state: GameState, player: int, card: str):
    """Allies: after a Liaison is played (Circle of Witches, League of Shopkeepers) or an Action is played (Fellowship of Scribes)."""
    ally = state.ally
    if ally is None or state.current_player != player or state.status.value != "active":
        return
    me = state.players[player]
    definition = get_card(card)
    liaison = definition.is_type(CardType.LIAISON)
    if ally == "Circle of Witches" and liaison and me.favors >= 3:
        ctx = EffectContext(state, player, ally)
        chosen = yield ctx.choose("Circle of Witches: you may spend 3 Favors to have each other player gain a Curse.", ("Spend 3 Favors",), 0, 1)
        if chosen:
            ctx.spend_favors(3)
            for p in ctx.other_players():
                ctx.gain("Curse", player=p)
    elif ally == "League of Shopkeepers" and liaison:
        ctx = EffectContext(state, player, ally)
        if me.favors >= 5:
            ctx.log(f"League of Shopkeepers: {me.name} has {me.favors} Favors.")
            ctx.add_coins(1)
            if me.favors >= 10:
                ctx.add_actions(1)
                ctx.add_buys(1)
    elif ally == "Fellowship of Scribes" and definition.is_type(CardType.ACTION) and me.favors >= 1 and len(me.hand) <= 4:
        ctx = EffectContext(state, player, ally)
        chosen = yield ctx.choose("Fellowship of Scribes: you have 4 or fewer cards in hand. You may spend a Favor for +1 Card.", ("Spend a Favor",), 0, 1)
        if chosen:
            ctx.spend_favors(1)
            ctx.draw(1)


CHAMELEON = "Way of the Chameleon"


def kiln_steps(state: GameState, player: int, card: str):
    """Menagerie, Kiln: \"the next time you play a card this turn, you may first gain a copy of it\" (before a Way is chosen)."""
    n = state.turn_counts.get("kiln", 0)
    if n <= 0:
        return
    state.turn_counts["kiln"] = 0
    for _ in range(n):
        ctx = EffectContext(state, player, "Kiln")
        if state.supply.get(card, 0) <= 0 or is_walled(state, card, player) or is_buried(state, card):
            continue                                              # only from the Supply
        chosen = yield ctx.choose(f"Kiln: you may gain a copy of {card} before playing it.", (f"Gain a copy of {card}",), 0, 1)
        if chosen:
            ctx.gain(card)


def way_choice(state: GameState, player: int, card: str):
    """Menagerie: with a Way in the game, each Action played may use a Way instead of its own effect. Generator returning the
    chosen Way's name, or None for the card's own effect."""
    if not state.ways:
        return None
    ctx = EffectContext(state, player, card)
    normal = f"Play {card} normally"
    (choice,) = yield ctx.choose(f"You are playing {card}. Play it normally, or use a Way instead?", (normal, *state.ways))
    if choice == normal:
        return None
    ctx.log(f"{ctx._name()} plays {card} using {choice}.", "play")
    return choice


def play_effect(state: GameState, player: int, card: str, on_play):
    """What happens when an Action is played: Kiln (a \"first\" ability), then the choice of a Way, then the Way or the
    card's own effect (Enchantress replaces the card's effect, but not a Way)."""
    yield from kiln_steps(state, player, card)
    way = yield from way_choice(state, player, card)
    if way is not None and way != CHAMELEON:
        result = get_card(way).on_play(EffectContext(state, player, card))
        if inspect.isgenerator(result):
            yield from result
        return
    if enchant_replaces(state, player, card):
        return
    ctx = EffectContext(state, player, card)
    ctx._chameleon = way == CHAMELEON
    result = on_play(ctx)
    if inspect.isgenerator(result):
        yield from result
    if way is None and state.traits and state.traits.get(state.stack_of.get(card, card)) == "Reckless":      # Plunder: Reckless Actions are followed twice
        ctx.log(f"Reckless: {card} is followed a second time.")
        result = on_play(EffectContext(state, player, card))
        if inspect.isgenerator(result):
            yield from result


def urchin_steps(state: GameState, player: int, card: str):
    """Dark Ages, Urchin: when its owner plays another Attack, each Urchin in play may be trashed for a Mercenary."""
    if not get_card(card).is_type(CardType.ATTACK):
        return
    me = state.players[player]
    others = me.in_play.count("Urchin") - (1 if card == "Urchin" else 0)
    for _ in range(max(0, others)):
        if state.offsupply.get("Mercenary", 0) <= 0 or "Urchin" not in me.in_play:
            return
        ctx = EffectContext(state, player, "Urchin")
        chosen = yield ctx.choose(f"You played {card}. You may trash Urchin to gain a Mercenary.", ("Trash Urchin",), 0, 1)
        if chosen and ctx.trash_in_play("Urchin"):
            ctx.gain_from_offsupply("Mercenary")


def enchant_replaces(state: GameState, player: int, card: str) -> bool:
    """Empires, Enchantress: the first Action card an enchanted player plays on their turn only gives +1 Card and +1 Action
    (once for each Enchantress waiting on them) instead of what it says. True if ``card`` was replaced this way."""
    me = state.players[player]
    if me.enchanted <= 0 or state.current_player != player or state.turn_counts.get("enchanted_used"):
        return False
    if not get_card(card).is_type(CardType.ACTION):
        return False
    state.turn_counts["enchanted_used"] = 1
    n = me.enchanted
    ctx = EffectContext(state, player, card)
    ctx.log(f"{me.name} is enchanted: {card} only gives +{n} Card{'s' if n != 1 else ''} and +{n} Action{'s' if n != 1 else ''}.", "reveal")
    ctx.draw(n)
    ctx.add_actions(n)
    return True


def take_minus_coin(state: GameState, amount: int) -> int:
    """Adventures: the player whose turn it is has the -$1 token: the next $ they would get is one smaller; the token is returned."""
    me = state.players[state.current_player]
    if me.minus_coin and amount > 0:
        me.minus_coin = False
        state.log.append(f"{me.name}'s -$1 token is used: $1 less.", "info", 1)
        return amount - 1
    return amount


def apply_play_bonuses(state: GameState, player: int, card: str) -> None:
    """Adventures: Champion (+1 Action per Action played) and the +1 Card / +1 Action / +1 Buy / +$1 tokens on the card's pile."""
    me = state.players[player]
    if not (get_card(card).is_type(CardType.ACTION) or (card == "Estate" and me.inherited)):
        return
    champions = me.in_play.count("Champion") - (1 if card == "Champion" else 0)
    if champions > 0:
        state.actions += champions
        state.log.append(f"Champion gives {champions} extra Action(s).", "info", 1)
    pile = state.stack_of.get(card, card)
    ctx = EffectContext(state, player, card)
    for token, bonus in (("+1 Card", lambda: ctx.draw(1)), ("+1 Action", lambda: ctx.add_actions(1)),
                         ("+1 Buy", lambda: ctx.add_buys(1)), ("+$1", lambda: ctx.add_coins(1))):
        if me.tokens.get(token) == pile:
            state.log.append(f"{me.name} gets the {token} token's bonus from {pile}.", "info", 1)
            bonus()


def call_steps(state: GameState, player: int, when: str, arg=None):
    """Generator (Adventures): offer the player each Reserve card on their Tavern mat that can be called at this moment
    (``when``: "start", "after_action", "gain" or "buy_end"). A called card goes into play (or is discarded, Wine Merchant)."""
    me = state.players[player]
    declined = set()
    while True:
        options = []
        for name in sorted(set(me.tavern)):
            card = get_card(name)
            if card.call_when != when or name in declined:
                continue
            if card.call_cond is not None and not card.call_cond(EffectContext(state, player, name), arg):
                continue
            options.append(name)
        if not options or state.status.value != "active":
            return
        name = options[0]
        card = get_card(name)
        ctx = EffectContext(state, player, name)
        chosen = yield ctx.choose(card.call_prompt or f"You may call {name}.", (f"Call {name}",), 0, 1)
        if not chosen:
            declined.add(name)
            continue
        me.tavern.remove(name)
        if card.call_discards:
            me.discard.append(name)
        else:
            me.in_play.append(name)
        state.log.append(f"{me.name} calls {name}.", "play")
        result = card.call_fn(EffectContext(state, player, name), arg)
        if inspect.isgenerator(result):
            yield from result


def citadel_check(state, player: int, card: str) -> bool:
    """Renaissance: True the first time the owner of Citadel plays an Action card during their turn (that is then used up for the turn)."""
    if (state.current_player == player and "Citadel" in state.players[player].projects
            and not state.turn_counts.get("citadel") and get_card(card).is_type(CardType.ACTION)):
        state.turn_counts["citadel"] = 1
        return True
    return False


def fire_triggers(state: GameState, event: str, player: int, *args) -> None:
    """Run the end-of-turn triggers (Merchant...) that are waiting for ``event``."""
    for trigger in list(state.triggers):
        if trigger.event == event and trigger.owner == player:
            trigger.handler(EffectContext(state, player, trigger.source), trigger, *args)


def _tally(cards) -> str:
    """'3 Copper, 2 Silver' (sorted by name); 'nothing' for an empty collection."""
    counts = Counter(cards)
    if not counts:
        return "nothing"
    return ", ".join(f"{n} {name}" for name, n in sorted(counts.items()))
