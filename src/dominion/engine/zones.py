"""Low-level card movement. The only code that shuffles or moves cards."""

from __future__ import annotations

from typing import Optional

from ..cards import CardType, get_card
from .constants import HAND_SIZE
from .costs import is_buried, is_walled
from .state import GainEvent, GameState, TrashEvent

# Zones a card can be moved between. "trash" is shared; the rest are per player.
PLAYER_ZONES = ("hand", "deck", "discard", "in_play", "set_aside", "island_mat", "village_mat", "haven", "farmhands", "joust_aside", "tavern", "saved", "archived", "crypt", "ghosted", "hounds", "cargo_aside", "research_aside", "exile", "delayed")


def beneficiary(state: GameState, player_index: int) -> int:
    """Who really receives what ``player_index`` gains: normally the same player, but during a Possession turn
    everything the possessed player would gain goes to the player controlling the turn."""
    if state.possessor is not None and player_index == state.current_player:
        return state.possessor
    return player_index


def send_to_trash(state: GameState, player_index: int, card: str) -> None:
    """Put a card of ``player_index`` into the trash. During a Possession turn the possessed player's
    cards are set aside instead and come back to their discard pile at the end of the turn."""
    if state.possessor is not None and player_index == state.current_player:
        state.possession_aside.append(card)
    else:
        state.trash.append(card)
        if player_index == state.current_player:
            state.players[player_index].trashed_turn += 1         # Menagerie: Goatherd counts what the player on its owner's right trashed
        priest = state.turn_counts.get("ren:priest", 0) if player_index == state.current_player else 0        # Renaissance: Priest
        state.trash_events.append(TrashEvent(player_index, card, priest))       # "when you trash this" (Dark Ages)


def return_possession_cards(state: GameState) -> int:
    """End of a Possession turn: the possessed player's 'trashed' cards go back to their discard pile."""
    count = len(state.possession_aside)
    if count:
        state.players[state.current_player].discard.extend(state.possession_aside)
        state.possession_aside.clear()
    return count


def take_top_cards(state: GameState, player_index: int, count: int, star: bool = False) -> list:
    """Remove up to ``count`` cards from the top of the deck (top first),
    reshuffling the discard pile when the deck runs out. The cards are returned,
    not placed anywhere: the caller must put them somewhere."""
    player = state.players[player_index]
    taken = []
    for _ in range(count):
        if not player.deck:
            if not player.discard:
                break
            state.shuffles += 1
            if star and state.ally in ("Order of Astrologers", "Order of Masons") and player.favors > 0:      # Allies: stop BEFORE the shuffle
                state.star_draws.append([player_index, count - len(taken), "ally"])
                break
            shuffled, player.discard = player.discard, []
            state.rng.shuffle(shuffled)
            player.deck = shuffled
            if star and "Star Chart" in player.projects:       # Renaissance: stop to let the owner pick the top card, then finish the draw
                state.star_draws.append([player_index, count - len(taken)])
                break
        taken.append(player.deck.pop())
    return taken


def draw_cards(state: GameState, player_index: int, count: int) -> list:
    """Draw up to ``count`` cards into the hand. Returns the cards drawn."""
    player = state.players[player_index]
    if count >= 1 and player.minus_card:              # Adventures: the -1 Card token makes the next draw one card smaller
        player.minus_card = False
        count -= 1
        state.log.append(f"{player.name}'s -1 Card token is used: one card fewer is drawn.", "info", 1)
    drawn = take_top_cards(state, player_index, count, star=True)
    state.players[player_index].hand.extend(drawn)
    return drawn


def move_card(state: GameState, player_index: int, card: str, source: str, destination: str) -> None:
    """Move one named card between zones. Top of the deck is the END of the list.
    Raises ValueError if the card is not in the source zone."""
    if source not in PLAYER_ZONES or source == "deck":
        raise ValueError(f"Cannot move a card out of '{source}'.")
    if destination not in (*PLAYER_ZONES, "trash"):
        raise ValueError(f"Unknown destination: {destination}")
    player = state.players[player_index]
    getattr(player, source).remove(card)
    if destination == "trash":
        send_to_trash(state, player_index, card)
    else:
        getattr(player, destination).append(card)


def note_gain(state: GameState, card: str) -> None:
    """Menagerie: Wayfarer costs the same as the last OTHER card gained this turn (by any player)."""
    if card != "Wayfarer":
        state.last_gain = card


def exile_from_supply(state: GameState, player_index: int, card: str) -> bool:
    """Menagerie: put a card from a Supply pile onto a player's Exile mat. This is not gaining it. False if the pile is empty
    or the card is buried in a mixed pile (only the top card of Knights / Castles / split piles can be taken)."""
    if state.supply.get(card, 0) <= 0 or is_buried(state, card):
        return False
    state.supply[card] -= 1
    if card in state.stack_of:
        state.stacks[state.stack_of[card]].pop(0)
    state.players[player_index].exile.append(card)
    return True


def gain_card(state: GameState, player_index: int, card: str, destination: str = "discard") -> bool:
    """Move a card from the supply to a player's zone. False if the pile is empty or walled off (Fortnite).
    During a Possession turn a card the possessed player would gain goes to the possessor's discard pile."""
    taker = beneficiary(state, player_index)
    to_hand = destination == "discard" and taker == player_index and get_card(card).gains_to_hand     # Nocturne: "this is gained to your hand"
    if taker != player_index:
        player_index, destination = taker, "discard"
    if state.supply.get(card, 0) <= 0 or is_walled(state, card, player_index) or is_buried(state, card):
        return False
    if to_hand:
        destination = "hand"
    if destination not in ("discard", "hand", "deck"):
        raise ValueError(f"Unknown destination: {destination}")
    state.supply[card] -= 1
    note_gain(state, card)
    if card in state.stack_of:                       # Knights / Ruins: the top card of the mixed pile leaves it
        state.stacks[state.stack_of[card]].pop(0)
    player = state.players[player_index]
    getattr(player, destination).append(card)
    player.gained.append(card)
    if state.current_player == player_index:
        player.gained_turn.append(card)              # what Smugglers may copy on the next player's turn
    if card in state.trade_tokens:                   # Trade Route: the pile's token moves to the mat
        state.trade_tokens.discard(card)
        state.trade_mat += 1
    if state.phase.value == "buy" and state.current_player == player_index:
        player.buy_gains += 1                        # Merchant Guild counts what is gained in the Buy phase
    state.gain_events.append(GainEvent(player_index, card, destination, bought=state.buying, overpaid=state.overpaid,
                                       nth=len(player.gained_turn) if state.current_player == player_index else 0,
                                       buy_phase=state.phase.value == "buy" and state.current_player == player_index))
    state.buying = False                             # only the first gain of a purchase is the bought card
    state.overpaid = 0
    return True


def gain_offsupply(state: GameState, player_index: int, card: str, destination: str = "discard") -> bool:
    """Gain a card from a pile that is not in the Supply (Prizes, Rewards, the Ferryman pile). False if it is empty."""
    taker = beneficiary(state, player_index)
    if taker != player_index:
        player_index, destination = taker, "discard"
    if state.offsupply.get(card, 0) <= 0:
        return False
    if destination not in ("discard", "hand", "deck"):
        raise ValueError(f"Unknown destination: {destination}")
    state.offsupply[card] -= 1
    note_gain(state, card)
    player = state.players[player_index]
    getattr(player, destination).append(card)
    player.gained.append(card)
    if state.current_player == player_index:
        player.gained_turn.append(card)
    if state.phase.value == "buy" and state.current_player == player_index:
        player.buy_gains += 1
    state.gain_events.append(GainEvent(player_index, card, destination, from_supply=False,
                                       nth=len(player.gained_turn) if state.current_player == player_index else 0,
                                       buy_phase=state.phase.value == "buy" and state.current_player == player_index))
    return True


def gain_from_trash(state: GameState, player_index: int, card: str, destination: str = "discard") -> bool:
    """Move a card from the trash pile to a player's zone. False if it is not in the trash."""
    if card not in state.trash:
        return False
    taker = beneficiary(state, player_index)
    if taker != player_index:
        player_index, destination = taker, "discard"
    if destination not in ("discard", "hand", "deck"):
        raise ValueError(f"Unknown destination: {destination}")
    state.trash.remove(card)
    note_gain(state, card)
    player = state.players[player_index]
    getattr(player, destination).append(card)
    player.gained.append(card)
    if state.current_player == player_index:
        player.gained_turn.append(card)
    state.gain_events.append(GainEvent(player_index, card, destination, from_supply=False,
                                       nth=len(player.gained_turn) if state.current_player == player_index else 0,
                                       buy_phase=state.phase.value == "buy" and state.current_player == player_index))
    return True


def return_to_supply(state: GameState, player_index: int, card: str) -> bool:
    """Move a card from a player's hand back to its Supply pile (Ambassador). False if the game has no such pile."""
    if card not in state.supply or card in state.stack_of:
        return False
    state.players[player_index].hand.remove(card)
    state.supply[card] += 1
    return True


def trash_from_supply(state: GameState, card: str) -> bool:
    """Move a card from a supply pile to the trash. False if the pile is empty.
    A card of a split pile or the Castles can be trashed from the Supply only while it is on top of its pile (Gladiator)."""
    if card in state.stack_of:
        pile = state.stack_of[card]
        stack = state.stacks.get(pile) or []
        if pile in state.stacks and pile not in ("Knights", "Ruins") and stack and stack[0] == card and state.supply.get(card, 0) > 0:
            stack.pop(0)
            state.supply[card] -= 1
            state.trash.append(card)
            return True
        return False
    if state.supply.get(card, 0) <= 0:
        return False
    state.supply[card] -= 1
    state.trash.append(card)
    return True


def give_to_discard(state: GameState, card: str, source: int, target: int) -> None:
    """Move one named card from one player's hand to another player's discard pile (Monopoly)."""
    state.players[source].hand.remove(card)
    state.players[target].discard.append(card)
    state.players[target].gained.append(card)


def steal_random_hand_card(state: GameState, victim: int, thief: int) -> Optional[str]:
    """The thief takes one random card from the victim's hand into their own discard pile (Grand Theft Auto)."""
    hand = state.players[victim].hand
    if not hand:
        return None
    card = hand.pop(state.rng.randrange(len(hand)))
    state.players[thief].discard.append(card)
    state.players[thief].gained.append(card)
    return card


def swap_hands(state: GameState, a: int, b: int) -> None:
    pa, pb = state.players[a], state.players[b]
    pa.hand, pb.hand = pb.hand, pa.hand


def give_card(state: GameState, card: str, source: int, target: int) -> None:
    """Move one named card from one player's hand to another player's hand."""
    state.players[source].hand.remove(card)
    state.players[target].hand.append(card)


def discard_from_hand(state: GameState, player_index: int, card: str) -> None:
    move_card(state, player_index, card, "hand", "discard")
    tunnel_discarded(state, player_index, card)


def tunnel_discarded(state: GameState, player_index: int, card: str) -> None:
    """\"When you discard this other than during Clean-up\" effects that need no decision. Cleanup discards never come through here.

    Hinterlands: a Tunnel may be revealed to gain a Gold (always worth it, so it is revealed automatically).
    Nocturne: a Faithful Hound may be set aside and put into its owner's hand at end of turn (never worse than leaving it
    in the discard pile, so it is set aside automatically). The card has just been put on top of the discard pile."""
    if state.status.value != "active":
        return
    if card == "Tunnel":
        state.log.append(f"{state.players[player_index].name} reveals Tunnel.", "reveal", 1)
        if gain_card(state, player_index, "Gold"):
            state.log.append(f"{state.players[beneficiary(state, player_index)].name} gains Gold.", "gain", 1)
    elif card == "Village Green" and not state.cleanup_active:
        state.discard_events.append((player_index, card))      # Menagerie: Village Green may be played when discarded (asked in Game._settle)
    elif card == "Faithful Hound" and not state.cleanup_active:
        player = state.players[player_index]
        if "Faithful Hound" in player.discard:
            player.discard.pop(len(player.discard) - 1 - player.discard[::-1].index("Faithful Hound"))
            player.hounds.append("Faithful Hound")
            state.log.append(f"{player.name} sets Faithful Hound aside; it returns to their hand at end of turn.", "reveal", 1)


def trash_from_hand(state: GameState, player_index: int, card: str) -> None:
    move_card(state, player_index, card, "hand", "trash")


def redistribute_all_cards(state: GameState, no_new_hand_for: int) -> list:
    """Pool every player's deck, hand and discard pile, shuffle, and deal them
    back so each player owns as many cards as before. Cards in play and set
    aside are not pooled. Everyone except ``no_new_hand_for`` (the player whose
    turn it is, who draws at cleanup) draws a fresh hand. Players wearing the
    Invisibility Cloak keep their own cards and take no part, unless they are
    ``no_new_hand_for`` (they chose to play it). Returns the sizes (0 for those left out)."""
    taking_part = [
        i for i, p in enumerate(state.players) if not p.invisible or i == no_new_hand_for
    ]
    sizes, pool = [0] * len(state.players), []
    for i in taking_part:
        player = state.players[i]
        cards = player.deck + player.hand + player.discard
        sizes[i] = len(cards)
        pool.extend(cards)
        player.deck, player.hand, player.discard = [], [], []
    state.rng.shuffle(pool)
    start = 0
    for i in taking_part:
        state.players[i].deck = pool[start:start + sizes[i]]
        start += sizes[i]
    for index in taking_part:
        if index != no_new_hand_for:
            draw_cards(state, index, HAND_SIZE)
    return sizes


def insert_into_deck(state: GameState, player_index: int, card: str, from_top: int) -> None:
    """Put ``card`` (already removed from wherever it was) into the draw pile so that
    ``from_top`` cards lie above it (0 = on top). Clamped to the pile size."""
    deck = state.players[player_index].deck
    from_top = max(0, min(from_top, len(deck)))
    deck.insert(len(deck) - from_top, card)


def remove_random_cards(state: GameState, player_index: int, zone_names: tuple, count: int) -> list:
    """Remove ``count`` cards chosen uniformly at random from the given zones of one
    player (using the game's own seeded RNG) and return their names. The caller
    must put them somewhere."""
    player = state.players[player_index]
    slots = [(z, i) for z in zone_names for i in range(len(getattr(player, z)))]
    count = max(0, min(count, len(slots)))
    chosen = state.rng.sample(slots, count)
    removed = []
    for zone in zone_names:
        indices = sorted((i for z, i in chosen if z == zone), reverse=True)
        cards = getattr(player, zone)
        for i in indices:
            removed.append(cards.pop(i))
    state.rng.shuffle(removed)
    return removed


def is_swap_exempt(card: str) -> bool:
    """Victory and Curse cards never move in a Grand Swap."""
    definition = get_card(card)
    return definition.is_type(CardType.VICTORY) or definition.is_type(CardType.CURSE)


def grand_swap(state: GameState, a: int, b: int) -> None:
    """Two players swap everything in their draw piles and discard piles, except
    Victory and Curse cards, which stay with their owner. Hands are not touched.
    Each draw pile is reshuffled afterwards."""
    pa, pb = state.players[a], state.players[b]
    for zone in ("deck", "discard"):
        cards_a, cards_b = getattr(pa, zone), getattr(pb, zone)
        keep_a = [c for c in cards_a if is_swap_exempt(c)]
        keep_b = [c for c in cards_b if is_swap_exempt(c)]
        move_a = [c for c in cards_a if not is_swap_exempt(c)]
        move_b = [c for c in cards_b if not is_swap_exempt(c)]
        setattr(pa, zone, keep_a + move_b)
        setattr(pb, zone, keep_b + move_a)
    state.rng.shuffle(pa.deck)
    state.rng.shuffle(pb.deck)
