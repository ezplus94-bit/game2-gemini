"""Catastrophe cards: an optional house-rule category of game-changing cards.

They are NOT part of the normal Kingdom. A host adds up to two of them to a game.
Fairness rules built into every one of them:

  * Scarce and expensive: each pile has only 2 cards ($7-$10) and never counts
    toward the "three empty piles" game ending.
  * Single use: the card trashes itself when played (a Throne Room'd copy does
    nothing the second time).
  * Counterplay: protection (Guardian Angel, God Mode, Invisibility Cloak) skips you, but Moat and other Reactions
    do NOT work against a Catastrophe.
  * Limits: nobody can be skipped twice in a row, Fate Swap trades equal-sized
    piles, Cataclysm costs you your buys, and the two "half your cards" cards
    (The Snap, The Purge) always hit the player who plays them as well.
  * Open book: every card that moves cards between players logs who got what.
"""

from __future__ import annotations

from .base import CardType, action
from .registry import register

SWAP_LIMIT = 7              # Fate Swap moves at most this many cards each way
_ATTACK = (CardType.ATTACK, CardType.CATASTROPHE)


def _skip_next(ctx, count: int):
    """The next ``count`` players in turn order skip their next turn (unless protected)."""
    order = ctx.other_players()[:count]
    affected = yield from ctx.attack(only=order)
    for player in order:
        if player in affected:
            ctx.skip_next_turn(player)


def _time_stop(ctx):
    if not ctx.trash_self():
        return
    yield from _skip_next(ctx, 1)


def _long_night(ctx):
    if not ctx.trash_self():
        return
    yield from _skip_next(ctx, 2)


def _fate_swap(ctx):
    if not ctx.trash_self():
        return
    others = ctx.other_players()
    names = tuple(ctx.name_of(p) for p in others)
    (chosen,) = yield ctx.choose("Fate Swap: choose a player to swap the tops of your decks with.", names)
    target = others[names.index(chosen)]
    affected = yield from ctx.attack(only=[target])
    if target not in affected:
        return
    moved = ctx.swap_top_cards(target, SWAP_LIMIT)
    if moved:
        ctx.log(f"FATE SWAP! {ctx.player_name} and {chosen} swap the top {moved} cards of their decks.", "catastrophe")
    else:
        ctx.log("One of the draw piles is empty, so nothing is swapped.")


def _cataclysm(ctx):
    if not ctx.trash_self():
        return
    ctx.log("CATACLYSM! Every deck is thrown into one pile.", "catastrophe", 0)
    ctx.redistribute_all_cards()
    ctx.lock_buys()


def _grand_swap(ctx):
    if not ctx.trash_self():
        return
    others = ctx.other_players()
    names = tuple(ctx.name_of(p) for p in others)
    (chosen,) = yield ctx.choose("Grand Swap: choose a player to swap whole decks with.", names)
    target = others[names.index(chosen)]
    affected = yield from ctx.attack(only=[target])
    if target not in affected:
        return
    ctx.log(f"GRAND SWAP! {ctx.player_name} and {chosen} trade decks.", "catastrophe", 0)
    ctx.grand_swap_with(target)


def _snap(ctx):
    if not ctx.trash_self():
        return
    affected = yield from ctx.attack()
    ctx.log("THE SNAP! Half of the cards turn to dust.", "catastrophe", 0)
    ctx.snap([ctx.player, *[p for p in ctx.other_players() if p in affected]])


def _purge(ctx):
    if not ctx.trash_self():
        return
    affected = yield from ctx.attack()
    ctx.log("THE PURGE! Half of every draw pile is thrown away.", "catastrophe", 0)
    ctx.purge([ctx.player, *[p for p in ctx.other_players() if p in affected]])


register(action(
    "Time Stop", 8, _time_stop,
    "Trash this. The next player skips their next turn. (Nobody can be skipped twice in a row.)",
    kingdom=False, extra_types=_ATTACK, expansion="Catastrophe",
))
register(action(
    "Long Night", 10, _long_night,
    "Trash this. The next two players each skip their next turn. (3+ players.)",
    kingdom=False, extra_types=_ATTACK, min_players=3, expansion="Catastrophe",
))
register(action(
    "Fate Swap", 8, _fate_swap,
    f"Trash this. Choose another player. You each take the top X cards of your draw piles "
    f"(X = the smaller pile, at most {SWAP_LIMIT}) and put them on top of the other's draw pile.",
    kingdom=False, extra_types=_ATTACK, expansion="Catastrophe",
))
register(action(
    "Cataclysm", 9, _cataclysm,
    "Trash this. Pool every player's deck, hand and discard pile, shuffle, and deal them back so "
    "everyone has as many cards as before; the others draw a new hand of 5. Your hand is part of "
    "the pool. You may not buy cards this turn.",
    kingdom=False, extra_types=(CardType.CATASTROPHE,), expansion="Catastrophe",
))
register(action(
    "Grand Swap", 9, _grand_swap,
    "Trash this. Choose another player. You trade your whole draw piles and discard piles with them "
    "(hands stay put) - except Victory and Curse cards, which stay with their owner. Both draw piles are reshuffled. "
    "Risky: you get whatever they had, good or bad.",
    kingdom=False, extra_types=_ATTACK, expansion="Catastrophe",
))
register(action(
    "The Snap", 10, _snap,
    "Trash this. Every player, you included, trashes half (rounded down) of the cards in their draw pile, "
    "hand and discard pile, chosen at random. Only protection (not Moat) spares the other players; you are never spared.",
    kingdom=False, extra_types=_ATTACK, expansion="Catastrophe",
))
register(action(
    "The Purge", 7, _purge,
    "Trash this. Every player, you included, discards half (rounded down) of their draw pile, chosen at random. "
    "Only protection (not Moat) spares the other players; you are never spared.",
    kingdom=False, extra_types=_ATTACK, expansion="Catastrophe",
))


# ----------------------------------------------------------------- Monopoly, Grand Theft Auto, Roofie, Fortnite
def _monopoly(ctx):
    if not ctx.trash_self():
        return
    affected = yield from ctx.attack()
    ctx.log("MONOPOLY! Everybody pays up.", "catastrophe", 0)
    for p in affected:
        ctx.take_gold_payment(p)


def _grand_theft_auto(ctx):
    if not ctx.trash_self():
        return
    others = ctx.other_players()
    names = tuple(ctx.name_of(p) for p in others)
    chosen = yield ctx.choose("Grand Theft Auto: choose 1 or 2 players to rob.", names, 1, min(2, len(names)))
    targets = [others[names.index(n)] for n in chosen]
    affected = yield from ctx.attack(only=targets)
    ctx.log("GRAND THEFT AUTO! Somebody's pockets are lighter.", "catastrophe", 0)
    for p in affected:
        ctx.steal_random_card(p)


def _roofie(ctx):
    if not ctx.trash_self():
        return
    affected = yield from ctx.attack()
    ctx.log("ROOFIE! The room starts to spin.", "catastrophe", 0)
    ctx.blind(affected)


def _fortnite(ctx):
    if not ctx.trash_self():
        return
    options = ctx.wallable()
    if not options:
        return
    chosen = yield ctx.choose("Fortnite: choose up to 3 piles to build walls around.", options, 0, 3)
    ctx.build_walls(list(chosen))


register(action(
    "Monopoly", 6, _monopoly,
    "Trash this. Each other player pays you: they put a Gold from their hand into your discard pile "
    "(a Silver if they have no Gold, nothing if they have neither).",
    kingdom=False, extra_types=_ATTACK, expansion="Catastrophe",
))
register(action(
    "Grand Theft Auto", 7, _grand_theft_auto,
    "Trash this. Choose 1 or 2 other players: you steal a random card from each one's hand into your discard pile.",
    kingdom=False, extra_types=_ATTACK, expansion="Catastrophe",
))
register(action(
    "Roofie", 6, _roofie,
    "Trash this. Each other player is blinded until the end of their next turn: they can see what type each card "
    "is (Action, Treasure, Victory...), but not its name, cost or text.",
    kingdom=False, extra_types=_ATTACK, expansion="Catastrophe",
))
register(action(
    "Fortnite", 6, _fortnite,
    "Trash this. Choose up to 3 Supply piles (not Catastrophe or Special piles) and build walls around them: "
    "nobody else can buy or gain cards from those piles until the start of your next turn.",
    kingdom=False, extra_types=(CardType.CATASTROPHE,), expansion="Catastrophe",
))
