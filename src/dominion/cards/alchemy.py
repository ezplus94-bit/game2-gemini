"""The Alchemy expansion (2nd edition): 12 Kingdom cards.

What is new compared with the base set and Intrigue, and where the engine supports it:

  * Potions: a new kind of cost. ``CardDef.potion_cost`` says how many Potions a card needs on top of its coins; the
    Potion Treasure (``cards/basic.py``) produces one. ``GameState.potions`` is spent when buying, reset in cleanup.
    The Potion pile (16 cards) joins the Supply when a Kingdom card costs a Potion. Effects such as "gain a card
    costing up to $4" never offer cards that cost a Potion.
  * "When you discard this from play" (Herbalist, Alchemist): ``CardDef.on_cleanup`` runs while the turn is cleaned up,
    so it may ask its owner a question (cleanup is a generator in ``Game``).
  * Treasures worth a computed amount: Philosopher's Stone (``CardDef.coins_fn``).
  * Possession: an extra turn for the player on your left, which you control (``state.possessor``). Cards the possessed
    player would gain go to you instead; their trashed cards are set aside and come back at the end of the turn.
  * Scoring by what you own: Vineyard (1 VP per 3 Action cards).
  * New Attacks: Scrying Pool, Familiar.
"""

from __future__ import annotations

from .base import CardType, action, treasure, victory
from .registry import get_card, register

SET = "Alchemy"
_ATTACK = (CardType.ATTACK,)


def _put_back_in_any_order(ctx, rest, player=None):
    """Generator: a player (default: the one who played the card) puts the cards in ``rest`` (set aside) back on
    their deck in an order they choose."""
    who = ctx.player if player is None else player
    rest = list(rest)
    order = []                                       # top of the deck first
    while len(rest) > 1:
        if len(set(rest)) == 1:
            order.extend(rest)
            rest = []
            break
        (top,) = yield ctx.choose("Choose the next card to put back, from the top down.", tuple(rest), player=who)
        rest.remove(top)
        order.append(top)
    order.extend(rest)
    for card in reversed(order):
        ctx.put_set_aside_on_deck(card, player=who)
    if order:
        ctx.log(f"{ctx.name_of(who)} puts {len(order)} card(s) back on their deck.")


# ----------------------------------------------------------------- $0 + Potion
def _transmute(ctx):
    hand = ctx.hand
    if not hand:
        return
    (card,) = yield ctx.choose("Transmute: trash a card from your hand.", hand)
    ctx.trash(card)
    if ctx.is_action(card):
        ctx.gain("Duchy")
    if ctx.is_treasure(card):
        ctx.gain("Transmute")
    if ctx.is_victory(card):
        ctx.gain("Gold")


def _vineyard_score(cards) -> int:
    return sum(1 for c in cards if get_card(c).is_type(CardType.ACTION)) // 3


# ----------------------------------------------------------------- $2
def _herbalist(ctx):
    ctx.add_buys(1)
    ctx.add_coins(1)


def _herbalist_cleanup(ctx):
    treasures = tuple(sorted({c for c in ctx.in_play if ctx.is_treasure(c)}))
    if not treasures:
        return
    chosen = yield ctx.choose("Herbalist: you may put one of your Treasures from play onto your deck.", treasures, 0, 1)
    if chosen:
        ctx.put_in_play_on_deck(chosen[0])


# ----------------------------------------------------------------- $2 + Potion
def _apothecary(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    cards = ctx.take_to_set_aside(4, reveal=True)
    rest = []
    for card in cards:
        if card in ("Copper", "Potion"):
            ctx.set_aside_to_hand(card)
        else:
            rest.append(card)
    yield from _put_back_in_any_order(ctx, rest)


def _scrying_pool(ctx):
    ctx.add_actions(1)
    targets = yield from ctx.attack()
    for p in [ctx.player, *targets]:
        cards = ctx.take_to_set_aside(1, player=p, reveal=True)
        if not cards:
            continue
        card = cards[0]
        whose = "your" if p == ctx.player else f"{ctx.name_of(p)}'s"
        (mode,) = yield ctx.choose(
            f"Scrying Pool: {whose} top card is {card}. Discard it, or put it back?",
            ("Discard it", "Put it back"),
        )
        if mode == "Discard it":
            ctx.discard_set_aside(card, player=p)
        else:
            ctx.put_set_aside_on_deck(card, player=p)
    while True:                                       # reveal until a card that is not an Action
        cards = ctx.take_to_set_aside(1, reveal=True)
        if not cards:
            break
        ctx.set_aside_to_hand(cards[0])
        if not ctx.is_action(cards[0]):
            break


def _university(ctx):
    ctx.add_actions(2)
    options = ctx.gainable(5, CardType.ACTION)
    if not options:
        return
    chosen = yield ctx.choose("University: you may gain an Action card costing up to $5.", options, 0, 1)
    if chosen:
        ctx.gain(chosen[0])


# ----------------------------------------------------------------- $3 + Potion
def _alchemist(ctx):
    ctx.draw(2)
    ctx.add_actions(1)


def _alchemist_cleanup(ctx):
    if "Potion" not in ctx.in_play:
        return
    chosen = yield ctx.choose("Alchemist: you may put this onto your deck (you have a Potion in play).",
                              ("Alchemist",), 0, 1)
    if chosen:
        ctx.put_in_play_on_deck("Alchemist")


def _familiar(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    targets = yield from ctx.attack()
    for p in targets:
        ctx.gain("Curse", player=p)


def _stone_coins(state, player: int) -> int:
    p = state.players[player]
    return (len(p.deck) + len(p.discard)) // 5


# ----------------------------------------------------------------- $4 + Potion
def _golem(ctx):
    found, others = [], []
    while len(found) < 2:
        cards = ctx.take_to_set_aside(1, reveal=True)
        if not cards:
            break
        card = cards[0]
        if ctx.is_action(card) and card != "Golem":
            found.append(card)
        else:
            others.append(card)              # stays set aside until the end, so it cannot be reshuffled and drawn again
    for card in others:
        ctx.discard_set_aside(card)
    if not found:
        return
    order = found
    if len(found) == 2 and found[0] != found[1]:
        (first,) = yield ctx.choose("Golem: choose the Action to play first.", tuple(found))
        order = [first, found[1] if found[0] == first else found[0]]
    for card in order:
        ctx.put_in_play(card, "set_aside")
        yield from ctx.resolve(card)


# ----------------------------------------------------------------- $5
def _apprentice(ctx):
    ctx.add_actions(1)
    hand = ctx.hand
    if not hand:
        return
    (card,) = yield ctx.choose("Apprentice: trash a card from your hand.", hand)
    ctx.trash(card)
    count = ctx.cost_of(card) + 2 * ctx.potion_cost_of(card)
    if count:
        ctx.draw(count)


# ----------------------------------------------------------------- $6 + Potion
def _possession(ctx):
    ctx.queue_extra_turn()


# ------------------------------------------------------------ registration
def _reg(name, cost, fn, text, potion=0, **kw):
    register(action(name, cost, fn, text, expansion=SET, potion_cost=potion, **kw))


_reg("Transmute", 0, _transmute, "Trash a card from your hand. If it is an Action card, gain a Duchy; a Treasure card, gain a Transmute; a Victory card, gain a Gold.", potion=1)
register(victory("Vineyard", 0, score_fn=_vineyard_score, text="Worth 1 VP per 3 Action cards you have (round down).",
                 kingdom=True, expansion=SET, potion_cost=1))
_reg("Herbalist", 2, _herbalist, "+1 Buy, +$1. When you discard this from play, you may put one of your Treasures from play onto your deck.",
     on_cleanup=_herbalist_cleanup, cleanup_order=1)
_reg("Apothecary", 2, _apothecary, "+1 Card, +1 Action. Reveal the top 4 cards of your deck. Put the Coppers and Potions into your hand. Put the other cards back in any order.", potion=1)
_reg("Scrying Pool", 2, _scrying_pool, "+1 Action. Each player (including you) reveals the top card of their deck and either discards it or puts it back, your choice. Then reveal cards from your deck until you reveal one that is not an Action. Put all of your revealed cards into your hand.",
     potion=1, extra_types=_ATTACK)
_reg("University", 2, _university, "+2 Actions. You may gain an Action card costing up to $5.", potion=1)
_reg("Alchemist", 3, _alchemist, "+2 Cards, +1 Action. When you discard this from play, you may put this onto your deck if you have a Potion in play.", potion=1,
     on_cleanup=_alchemist_cleanup, cleanup_order=0)
_reg("Familiar", 3, _familiar, "+1 Card, +1 Action. Each other player gains a Curse.", potion=1, extra_types=_ATTACK)
register(treasure("Philosopher's Stone", 3, 0, potion_cost=1,
                  text="When you play this, count your draw pile and discard pile together: it is worth $1 per 5 cards (round down).",
                  coins_fn=_stone_coins, kingdom=True, expansion=SET))
_reg("Golem", 4, _golem, "Reveal cards from your deck until you reveal 2 Action cards other than Golem. Discard the other cards, then play the Action cards in either order.", potion=1)
_reg("Apprentice", 5, _apprentice, "+1 Action. Trash a card from your hand. +1 Card per $1 it costs. +2 Cards if it has a Potion in its cost.")
_reg("Possession", 6, _possession, "The player to your left takes an extra turn after this one, in which you can see all cards they can and make all decisions for them. Any cards they would gain on that turn, you gain instead; any cards of theirs that are trashed are set aside and returned to their discard pile at end of turn.", potion=1)
