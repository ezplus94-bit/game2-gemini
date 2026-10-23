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
from .actions import Decision
from .costs import card_cost, is_walled
from .state import GameState, Trigger


class EffectContext:
    def __init__(self, state: GameState, player: int, source: str) -> None:
        self._state = state
        self.player = player      # index of the player who played the card
        self.source = source      # name of the card being resolved

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
        return get_card(card).is_type(CardType.TREASURE)

    def is_curse(self, card: str) -> bool:
        return get_card(card).is_type(CardType.CURSE)

    @property
    def unused_actions(self) -> int:
        return self._state.actions

    @property
    def coffers(self) -> int:
        return self._me().coffers

    def add_coffers(self, n: int, player: Optional[int] = None) -> None:
        i = self.player if player is None else player
        self._state.players[i].coffers += n
        self.log(f"{self._name(i)} gets +{n} Coffer(s) (now {self._state.players[i].coffers}).", "gain")

    def remove_coffers(self, n: int) -> None:
        self._me().coffers -= n
        self.log(f"{self._name()} spends {n} Coffer(s) (now {self._me().coffers}).")

    @property
    def bane_card(self) -> Optional[str]:
        return self._state.bane_card

    @property
    def available_prizes(self) -> tuple:
        return tuple(self._state.prizes)

    def gain_prize(self, card: str, destination: str = "deck") -> bool:
        ok = zones.gain_prize(self._state, self.player, card, destination)
        if ok:
            taker = zones.beneficiary(self._state, self.player)
            if taker != self.player:
                self.log(f"{self._name(taker)} gains Prize {card} (Possession).", "gain")
            else:
                where = "" if destination == "discard" else f" to their {destination}"
                self.log(f"{self._name()} gains Prize {card}{where}.", "gain")
        return ok

    def set_aside_horse_traders(self) -> None:
        if "Horse Traders" in self._me().hand:
            zones.move_card(self._state, self.player, "Horse Traders", "hand", "horse_traders_aside")
            self.log(f"{self._name()} sets Horse Traders aside.")

    def put_deck_into_discard(self) -> None:
        me = self._me()
        count = len(me.deck)
        me.discard.extend(me.deck)
        me.deck.clear()
        self.log(f"{self._name()} puts their deck ({count} card(s)) into their discard pile.", "discard")

    def gainable(self, max_cost: int, card_type: Optional[CardType] = None, exact: bool = False,
                 gainer: Optional[int] = None) -> tuple:
        """Supply piles that are non-empty, not walled off against ``gainer`` (default: this player), cost at
        most ``max_cost`` (exactly ``max_cost`` with ``exact=True``) and (optionally) have the given type.
        Cards that cost a Potion are never offered: "costing up to $4" does not include a card costing $3 and a Potion."""
        s = self._state
        who = self.player if gainer is None else gainer
        return tuple(
            name for name in sorted(s.supply)
            if s.supply[name] > 0 and not is_walled(s, name, who)
            and get_card(name).potion_cost == 0
            and (self.cost_of(name) == max_cost if exact else self.cost_of(name) <= max_cost)
            and (card_type is None or get_card(name).is_type(card_type))
        )

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
        return tuple(sorted(t.value for t in get_card(card).types))

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
        return sum(1 for count in self._state.supply.values() if count == 0)

    # ---- turn resources (always the current player's turn)
    def add_actions(self, n: int) -> None:
        self._state.actions += n

    def add_buys(self, n: int) -> None:
        self._state.buys += n

    def add_coins(self, n: int) -> None:
        self._state.coins += n

    # ---- card movement
    def draw(self, count: int, player: Optional[int] = None, quiet: bool = False) -> list:
        i = self.player if player is None else player
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

    def put_in_play_on_deck(self, card: str) -> None:
        """Put a card that is in play onto the top of the deck (Herbalist, Alchemist at cleanup)."""
        zones.move_card(self._state, self.player, card, "in_play", "deck")
        self.log(f"{self._name()} puts {card} from play onto their deck.")

    def discard_top_of_deck(self) -> Optional[str]:
        """Discard the top card of the deck (revealed). Returns its name or None."""
        cards = zones.take_top_cards(self._state, self.player, 1)
        if not cards:
            return None
        self._me().discard.append(cards[0])
        self.log(f"{self._name()} discards {cards[0]} from the top of their deck.")
        return cards[0]

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
        self.log(f"{self._name()} plays {card} with {self.source}.")

    def resolve(self, card: str):
        """Generator: run ``card``'s effect (without moving it). Use as
        ``yield from ctx.resolve(card)``."""
        self._state.plays_this_turn += 1
        result = get_card(card).on_play(EffectContext(self._state, self.player, card))
        if get_card(card).on_next_turn is not None and card != "Tactician":
            self._me().duration_effects.append(card)
        if inspect.isgenerator(result):
            yield from result

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
        if "Lighthouse" in p.in_play or "Lighthouse" in p.duration:
            return True
        return p.protected_forever or p.protection > 0 or p.invisible

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
        p.discard.extend(p.hand)
        p.hand.clear()
        self.log(f"{self._name(i)} discards their hand ({count} card(s)).", "discard")
        return count

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

    # ---- Seaside helpers
    def add_embargo(self, pile: str) -> None:
        self._state.embargo_tokens[pile] = self._state.embargo_tokens.get(pile, 0) + 1
        self.log(f"{self._name()} puts an Embargo token on {pile} (now {self._state.embargo_tokens[pile]}).")

    def set_aside_for_haven(self, card: str) -> None:
        zones.move_card(self._state, self.player, card, "hand", "haven_aside")
        self.log(f"{self._name()} sets a card aside with Haven.")

    def return_haven_cards(self) -> None:
        me = self._me()
        if me.haven_aside:
            count = len(me.haven_aside)
            me.hand.extend(me.haven_aside)
            me.haven_aside.clear()
            self.log(f"{self._name()} puts {count} Haven card(s) into their hand.", "draw")

    def native_village_push(self) -> None:
        cards = zones.take_top_cards(self._state, self.player, 1)
        if cards:
            self._me().native_village_mat.append(cards[0])
            self.log(f"{self._name()} sets the top card of their deck aside on their Native Village mat.")

    def native_village_take(self) -> None:
        me = self._me()
        if me.native_village_mat:
            count = len(me.native_village_mat)
            me.hand.extend(me.native_village_mat)
            me.native_village_mat.clear()
            self.log(f"{self._name()} puts {count} card(s) from their Native Village mat into their hand.", "draw")

    def peek_bottom_of_deck(self) -> Optional[str]:
        me = self._me()
        if not me.deck and me.discard:
            shuffled, me.discard = me.discard, []
            self._state.rng.shuffle(shuffled)
            me.deck = shuffled
        return me.deck[0] if me.deck else None

    def move_bottom_to_top(self) -> None:
        me = self._me()
        if me.deck:
            card = me.deck.pop(0)
            me.deck.append(card)
            self.log(f"{self._name()} puts the bottom card of their deck on top.")

    def in_supply(self, card: str) -> bool:
        return card in self._state.supply

    def return_hand_to_supply(self, card: str) -> None:
        me = self._me()
        me.hand.remove(card)
        self._state.supply[card] += 1
        self.log(f"{self._name()} returns {card} to the Supply.")

    def smuggle_options(self) -> tuple:
        n = len(self._state.players)
        right = (self.player - 1) % n
        gained = set(self._state.players[right].last_turn_gained)
        return tuple(
            name for name in sorted(gained)
            if self._state.supply.get(name, 0) > 0
            and not is_walled(self._state, name, self.player)
            and get_card(name).potion_cost == 0
            and self.cost_of(name) <= 6
        )

    def reveal_hand(self, player: int) -> None:
        cards = self._state.players[player].hand
        text = ", ".join(cards) if cards else "an empty hand"
        self.log(f"{self._name(player)} reveals {text}.", "reveal")

    def move_self_to_island(self) -> None:
        me = self._me()
        if self.source in me.in_play:
            zones.move_card(self._state, self.player, self.source, "in_play", "island_mat")
            self.log(f"{self._name()} puts {self.source} onto their Island mat.")

    def move_hand_to_island(self, card: str) -> None:
        zones.move_card(self._state, self.player, card, "hand", "island_mat")
        self.log(f"{self._name()} puts {card} onto their Island mat.")

    @property
    def pirate_coins(self) -> int:
        return self._me().pirate_coins

    def add_pirate_coin(self) -> None:
        self._me().pirate_coins += 1
        self.log(f"{self._name()} takes a Coin token on Pirate Ship (now {self._me().pirate_coins}).", "gain")

    def discard_top_of_deck_for(self, player: int) -> Optional[str]:
        cards = zones.take_top_cards(self._state, player, 1)
        if not cards:
            return None
        self._state.players[player].discard.append(cards[0])
        self.log(f"{self._name(player)} discards {cards[0]} from the top of their deck.", "discard")
        return cards[0]

    def queue_outpost_turn(self) -> None:
        if not self._state.outpost_turn and self._state.possessor is None:
            self._state.outpost_queued = True
            self.log(f"{self._name()} will take an Outpost extra turn (3-card hand) after this one.", "skip")

    def activate_tactician(self) -> None:
        self._me().tactician_active += 1
        self._me().duration_effects.append("Tactician")

    def consume_tactician(self) -> bool:
        me = self._me()
        if me.tactician_active > 0:
            me.tactician_active -= 1
            return True
        return False

    def bought_victory_this_turn(self) -> bool:
        return any(get_card(c).is_type(CardType.VICTORY) for c in self._state.bought_this_turn)

    # ---- Prosperity helpers
    def add_vp_tokens(self, n: int, player: Optional[int] = None) -> None:
        i = self.player if player is None else player
        self._state.players[i].vp_tokens += n
        self.log(f"{self._name(i)} gets +{n} VP token(s) (now {self._state.players[i].vp_tokens}).", "gain")

    @property
    def trade_route_tokens(self) -> int:
        return len(self._state.trade_route_piles)

    def ban_contraband(self, card: str) -> None:
        if card not in self._state.contraband_banned:
            self._state.contraband_banned.append(card)
        self.log(f"{self._name()} cannot buy {card} this turn (Contraband).", "reveal")

    def take_discard_to_hand(self, card: str) -> None:
        zones.move_card(self._state, self.player, card, "discard", "hand")
        self.log(f"{self._name()} puts {card} from their discard pile into their hand.", "draw")

    def play_set_aside_treasure(self, card: str):
        s = self._state
        me = self._me()
        zones.move_card(s, self.player, card, "set_aside", "in_play")
        definition = get_card(card)
        value = definition.coins_fn(s, self.player) if definition.coins_fn is not None else definition.coins
        potions = definition.potions
        note = ""
        if s.midas and value < 3:
            value, potions, note = 3, 0, " as Gold"
        s.coins += value
        s.potions += potions
        extra = f", +{potions} Potion" if potions else ""
        self.log(f"{me.name} plays {card}{note} with {self.source} (+${value}{extra})." if potions
                 else f"{me.name} plays {card}{note} with {self.source} (+${value}).", "treasure")
        for trigger in list(s.triggers):
            if trigger.event == "treasure_played" and trigger.owner == self.player:
                trigger.handler(EffectContext(s, self.player, trigger.source), trigger, card)
        if definition.on_play is not None:
            res = definition.on_play(EffectContext(s, self.player, card))
            if inspect.isgenerator(res):
                yield from res

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


def _tally(cards) -> str:
    """'3 Copper, 2 Silver' (sorted by name); 'nothing' for an empty collection."""
    counts = Counter(cards)
    if not counts:
        return "nothing"
    return ", ".join(f"{n} {name}" for name, n in sorted(counts.items()))
