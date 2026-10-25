"""The Guilds expansion: 13 Kingdom cards.

What is new in the engine:

  * Coffers (``PlayerState.coffers``): persistent coin tokens that stay between turns and can be spent for +$1 each
    via ``SpendCoffers`` (or removed directly by Butcher). Baker also gives every player 1 Coffers at game setup.
  * Villagers (``PlayerState.villagers``): persistent action tokens that stay between turns and can be spent for
    +1 Action each via ``SpendVillagers``.
  * Overpay (``CardDef.overpay`` / ``CardDef.on_overpay``): Stonemason, Doctor, Masterpiece, and Herald allow paying
    any additional amount of coins when bought to trigger an overpay effect per $1 overpaid (or at the overpaid cost).
  * "While this is in play, when you buy a card": Merchant Guild (``CardDef.on_buy_in_play``) grants +1 Coffers per copy
    in play whenever you buy a card.
"""

from __future__ import annotations

from .alchemy import _put_back_in_any_order
from .base import CardType, action, treasure
from .registry import register

SET = "Guilds"
_ATTACK = (CardType.ATTACK,)


# ----------------------------------------------------------------- $2
def _candlestick_maker(ctx):
    ctx.add_actions(1)
    ctx.add_buys(1)
    ctx.add_coffers(1)


def _stonemason(ctx):
    hand = ctx.hand
    if not hand:
        return
    (trashed,) = yield ctx.choose("Stonemason: trash a card from your hand.", hand)
    ctx.trash(trashed)
    cost = ctx.cost_of(trashed)
    if cost <= 0 and ctx.potion_cost_of(trashed) == 0:
        return
    max_cost = cost - 1 if ctx.potion_cost_of(trashed) == 0 else cost
    for _ in range(2):
        options = ctx.gainable(max_cost) if max_cost >= 0 else ()
        if not options:
            break
        card = options[0]
        if len(options) > 1:
            (card,) = yield ctx.choose(f"Stonemason: gain a card costing less than {trashed} (up to ${max_cost}).", options)
        ctx.gain(card)


def _stonemason_overpay(ctx, amount: int):
    for _ in range(2):
        options = ctx.gainable(amount, CardType.ACTION, exact=True)
        if not options:
            break
        card = options[0]
        if len(options) > 1:
            (card,) = yield ctx.choose(f"Stonemason (overpaid ${amount}): gain an Action card costing ${amount}.", options)
        ctx.gain(card)


# ----------------------------------------------------------------- $3
def _doctor(ctx):
    (named,) = yield ctx.choose("Doctor: name a card.", ctx.namable_cards())
    ctx.log(f"{ctx.player_name} names {named}.")
    cards = ctx.take_to_set_aside(3, reveal=True)
    rest = []
    for card in cards:
        if card == named:
            ctx.trash_set_aside(card)
        else:
            rest.append(card)
    yield from _put_back_in_any_order(ctx, rest)


def _doctor_overpay(ctx, amount: int):
    for _ in range(amount):
        cards = ctx.take_to_set_aside(1)
        if not cards:
            break
        card = cards[0]
        (mode,) = yield ctx.choose(
            f"Doctor (overpay): the top card of your deck is {card}. Trash it, discard it, or put it back?",
            ("Trash it", "Discard it", "Put it back"),
        )
        if mode == "Trash it":
            ctx.trash_set_aside(card)
        elif mode == "Discard it":
            ctx.discard_set_aside(card)
        else:
            ctx.put_set_aside_on_deck(card)


def _masterpiece_overpay(ctx, amount: int):
    for _ in range(amount):
        if not ctx.gain("Silver"):
            break
    return
    yield


# ----------------------------------------------------------------- $4
def _advisor(ctx):
    ctx.add_actions(1)
    cards = ctx.take_to_set_aside(3, reveal=True)
    if not cards:
        return
    left = ctx.left_player()
    unique = tuple(sorted(set(cards)))
    if len(unique) == 1:
        discarded = unique[0]
    else:
        (discarded,) = yield ctx.choose(
            f"Advisor ({ctx.player_name}): choose one revealed card for them to discard.",
            unique, player=left,
        )
    cards.remove(discarded)
    ctx.discard_set_aside(discarded)
    for card in cards:
        ctx.set_aside_to_hand(card)
    if cards:
        ctx.log(f"{ctx.player_name} puts the remaining {len(cards)} card(s) into their hand.")


def _herald(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    cards = ctx.take_to_set_aside(1, reveal=True)
    if not cards:
        return
    card = cards[0]
    if ctx.is_action(card):
        ctx.put_in_play(card, "set_aside")
        yield from ctx.resolve(card)
    else:
        ctx.put_set_aside_on_deck(card)


def _herald_overpay(ctx, amount: int):
    for _ in range(amount):
        options = tuple(sorted(set(ctx.discard_pile)))
        if not options:
            break
        (card,) = yield ctx.choose("Herald (overpay): put a card from your discard pile onto your deck.", options)
        ctx.put_discard_on_deck(card)


def _plaza(ctx):
    ctx.draw(1)
    ctx.add_actions(2)
    treasures = tuple(sorted({c for c in ctx.hand if ctx.is_treasure(c)}))
    if not treasures:
        return
    chosen = yield ctx.choose("Plaza: you may discard a Treasure for +1 Coffers.", treasures, 0, 1)
    if chosen:
        ctx.discard(chosen[0])
        ctx.add_coffers(1)


def _taxman(ctx):
    treasures = tuple(sorted({c for c in ctx.hand if ctx.is_treasure(c)}))
    if not treasures:
        return
    chosen = yield ctx.choose("Taxman: you may trash a Treasure from your hand.", treasures, 0, 1)
    if not chosen:
        return
    trashed = chosen[0]
    ctx.trash(trashed)
    targets = yield from ctx.attack()
    for p in targets:
        hand = ctx.hand_of(p)
        if len(hand) >= 5:
            if trashed in hand:
                ctx.discard(trashed, player=p)
            else:
                ctx.log(f"{ctx.name_of(p)} reveals a hand without {trashed}: {', '.join(sorted(hand))}.", "reveal")
    limit = ctx.cost_of(trashed) + 3
    gains = ctx.gainable(limit, CardType.TREASURE)
    if gains:
        card = gains[0]
        if len(gains) > 1:
            (card,) = yield ctx.choose(f"Taxman: gain a Treasure costing up to ${limit} onto your deck.", gains)
        ctx.gain(card, destination="deck")


# ----------------------------------------------------------------- $5
def _baker(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.add_coffers(1)


def _butcher(ctx):
    ctx.add_coffers(2)
    hand = ctx.hand
    if not hand:
        return
    chosen = yield ctx.choose("Butcher: you may trash a card from your hand.", hand, 0, 1)
    if not chosen:
        return
    trashed = chosen[0]
    ctx.trash(trashed)
    spent = 0
    if ctx.coffers > 0:
        opts = tuple(f"Remove {n} Coffers" for n in range(ctx.coffers + 1))
        (ans,) = yield ctx.choose("Butcher: how many tokens do you remove from your Coffers?", opts)
        spent = int(ans.split()[1])
        if spent > 0:
            ctx.remove_coffers(spent)
    if ctx.potion_cost_of(trashed) > 0:
        return
    limit = ctx.cost_of(trashed) + spent
    options = ctx.gainable(limit)
    if options:
        card = options[0]
        if len(options) > 1:
            (card,) = yield ctx.choose(f"Butcher: gain a card costing up to ${limit}.", options)
        ctx.gain(card)


def _journeyman(ctx):
    (named,) = yield ctx.choose("Journeyman: name a card.", ctx.namable_cards())
    ctx.log(f"{ctx.player_name} names {named}.")
    kept, discarded = [], []
    while len(kept) < 3:
        cards = ctx.take_to_set_aside(1, reveal=True)
        if not cards:
            break
        card = cards[0]
        if card == named:
            discarded.append(card)
        else:
            kept.append(card)
    for card in discarded:
        ctx.discard_set_aside(card)
    for card in kept:
        ctx.set_aside_to_hand(card)
    if kept:
        ctx.log(f"{ctx.player_name} puts {len(kept)} card(s) into their hand.")


def _merchant_guild(ctx):
    ctx.add_buys(1)
    ctx.add_coins(1)


def _merchant_guild_buy(ctx, card_name: str):
    ctx.add_coffers(1)


def _soothsayer(ctx):
    ctx.gain("Gold")
    targets = yield from ctx.attack()
    for p in targets:
        if ctx.gain("Curse", player=p):
            ctx.draw(1, player=p)


# ------------------------------------------------------------ registration
def _reg(name, cost, fn, text, **kw):
    register(action(name, cost, fn, text, expansion=SET, **kw))


_reg("Candlestick Maker", 2, _candlestick_maker, "+1 Action, +1 Buy. Take a Coffers.")
_reg("Stonemason", 2, _stonemason,
     "Trash a card from your hand. Gain 2 cards each costing less than it. When you buy this, you may overpay for it. If you do, gain 2 Action cards each costing the amount you overpaid.",
     overpay=True, on_overpay=_stonemason_overpay)
_reg("Doctor", 3, _doctor,
     "Name a card. Reveal the top 3 cards of your deck. Trash the matches. Put the rest back in any order. When you buy this, you may overpay for it. For each $1 you overpaid, look at the top card of your deck; trash it, discard it, or put it back.",
     overpay=True, on_overpay=_doctor_overpay)
register(treasure(
    "Masterpiece", 3, 1,
    text="$1. When you buy this, you may overpay for it. For each $1 you overpaid, gain a Silver.",
    kingdom=True, expansion=SET, overpay=True, on_overpay=_masterpiece_overpay,
))
_reg("Advisor", 4, _advisor, "+1 Action. Reveal the top 3 cards of your deck. The player to your left chooses one of them. Discard that card and put the rest into your hand.")
_reg("Herald", 4, _herald,
     "+1 Card, +1 Action. Reveal the top card of your deck. If it is an Action, play it. When you buy this, you may overpay for it. For each $1 you overpaid, look through your discard pile and put a card from it onto your deck.",
     overpay=True, on_overpay=_herald_overpay)
_reg("Plaza", 4, _plaza, "+1 Card, +2 Actions. You may discard a Treasure for +1 Coffers.")
_reg("Taxman", 4, _taxman,
     "You may trash a Treasure from your hand. Each other player with 5 or more cards in hand discards a copy of it (or reveals they can't). Gain a Treasure onto your deck costing up to $3 more than it.",
     extra_types=_ATTACK)
_reg("Baker", 5, _baker, "+1 Card, +1 Action. Take a Coffers. (Setup: each player takes 1 Coffers at the start of the game.)")
_reg("Butcher", 5, _butcher, "Take 2 Coffers. You may trash a card from your hand. If you do, remove any number of tokens from your Coffers and gain a card costing up to the cost of the trashed card plus $1 per token removed.")
_reg("Journeyman", 5, _journeyman, "Name a card. Reveal cards from your deck until you reveal 3 cards that are not the named card. Put those cards into your hand and discard the rest.")
_reg("Merchant Guild", 5, _merchant_guild, "+1 Buy, +$1. While this is in play, when you buy a card, take a Coffers.",
     on_buy_in_play=_merchant_guild_buy)
_reg("Soothsayer", 5, _soothsayer, "Gain a Gold. Each other player gains a Curse, and if they did, draws a card.",
     extra_types=_ATTACK)
