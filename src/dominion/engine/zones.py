"""Low-level card movement. The only code that shuffles or moves cards."""

from __future__ import annotations

from typing import Optional

from ..cards import CardType, get_card
from .constants import HAND_SIZE
from .costs import is_walled
from .state import GainEvent, GameState

# Zones a card can be moved between. "trash" is shared; the rest are per player.
PLAYER_ZONES = ("hand", "deck", "discard", "in_play", "set_aside", "island_mat", "village_mat", "haven")


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


def return_possession_cards(state: GameState) -> int:
    """End of a Possession turn: the possessed player's 'trashed' cards go back to their discard pile."""
    count = len(state.possession_aside)
    if count:
        state.players[state.current_player].discard.extend(state.possession_aside)
        state.possession_aside.clear()
    return count


def take_top_cards(state: GameState, player_index: int, count: int) -> list:
    """Remove up to ``count`` cards from the top of the deck (top first),
    reshuffling the discard pile when the deck runs out. The cards are returned,
    not placed anywhere: the caller must put them somewhere."""
    player = state.players[player_index]
    taken = []
    for _ in range(count):
        if not player.deck:
            if not player.discard:
                break
            shuffled, player.discard = player.discard, []
            state.rng.shuffle(shuffled)
            player.deck = shuffled
        taken.append(player.deck.pop())
    return taken


def draw_cards(state: GameState, player_index: int, count: int) -> list:
    """Draw up to ``count`` cards into the hand. Returns the cards drawn."""
    drawn = take_top_cards(state, player_index, count)
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


def gain_card(state: GameState, player_index: int, card: str, destination: str = "discard") -> bool:
    """Move a card from the supply to a player's zone. False if the pile is empty or walled off (Fortnite).
    During a Possession turn a card the possessed player would gain goes to the possessor's discard pile."""
    taker = beneficiary(state, player_index)
    if taker != player_index:
        player_index, destination = taker, "discard"
    if state.supply.get(card, 0) <= 0 or is_walled(state, card, player_index):
        return False
    if destination not in ("discard", "hand", "deck"):
        raise ValueError(f"Unknown destination: {destination}")
    state.supply[card] -= 1
    player = state.players[player_index]
    getattr(player, destination).append(card)
    player.gained.append(card)
    if state.current_player == player_index:
        player.gained_turn.append(card)              # what Smugglers may copy on the next player's turn
    if card in state.trade_tokens:                   # Trade Route: the pile's token moves to the mat
        state.trade_tokens.discard(card)
        state.trade_mat += 1
    state.gain_events.append(GainEvent(player_index, card, destination, bought=state.buying))
    state.buying = False                             # only the first gain of a purchase is the bought card
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
    player = state.players[player_index]
    getattr(player, destination).append(card)
    player.gained.append(card)
    if state.current_player == player_index:
        player.gained_turn.append(card)
    state.gain_events.append(GainEvent(player_index, card, destination, from_supply=False))
    return True


def return_to_supply(state: GameState, player_index: int, card: str) -> bool:
    """Move a card from a player's hand back to its Supply pile (Ambassador). False if the game has no such pile."""
    if card not in state.supply:
        return False
    state.players[player_index].hand.remove(card)
    state.supply[card] += 1
    return True


def trash_from_supply(state: GameState, card: str) -> bool:
    """Move a card from a supply pile to the trash. False if the pile is empty."""
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
