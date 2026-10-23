"""The Prosperity expansion (2010): 25 Kingdom cards (plus Platinum and Colony in basic.py).

What is new compared with earlier sets, and where the engine supports it:
  * Platinum ($9, worth $5) and Colony ($11, worth 10 VP): join the Basic Supply when any Kingdom card
    is from Prosperity; Colony emptying also ends the game.
  * Victory Point tokens (``player.vp_tokens``): earned from Bishop, Monument, and Goons; added to final scores.
  * Trade Route mat tokens (``state.trade_route_piles``): tracks Victory piles from which a card has been gained.
  * Treasures with ``on_play`` effects (Loan, Contraband, Venture) and passive in-play abilities
    (Quarry, Talisman, Royal Seal, Hoard, Bank).
  * On-gain reactions: Watchtower (from hand) and Royal Seal (while in play).
  * Dynamic cost reductions: Quarry (Actions cost $2 less) and Peddler ($2 less per Action in play during Buy phase).
"""

from __future__ import annotations

from .base import CardType, action, treasure
from .registry import register

SET = "Prosperity"
_ATTACK = (CardType.ATTACK,)
_REACTION = (CardType.REACTION,)


# ----------------------------------------------------------------- $3
def _loan(ctx):
    others = []
    found = None
    while True:
        cards = ctx.take_to_set_aside(1, reveal=True)
        if not cards:
            break
        card = cards[0]
        if ctx.is_treasure(card):
            found = card
            break
        others.append(card)
    if found is not None:
        (choice,) = yield ctx.choose(
            f"Loan: you revealed {found}. Discard it or trash it?",
            ("Discard it", "Trash it"),
        )
        if choice == "Trash it":
            ctx.trash_set_aside(found)
        else:
            ctx.discard_set_aside(found)
    for c in others:
        ctx.discard_set_aside(c)


def _trade_route(ctx):
    ctx.add_buys(1)
    tokens = ctx.trade_route_tokens
    if tokens:
        ctx.add_coins(tokens)
    hand = ctx.hand
    if not hand:
        return
    (card,) = yield ctx.choose("Trade Route: trash a card from your hand.", hand)
    ctx.trash(card)


def _watchtower(ctx):
    drawn = 0
    while ctx.hand_size < 6:
        cards = ctx.draw(1, quiet=True)
        if not cards:
            break
        drawn += 1
    ctx.log(f"{ctx.player_name} draws {drawn} card(s) with Watchtower.")


# ----------------------------------------------------------------- $4
def _bishop(ctx):
    ctx.add_coins(1)
    ctx.add_vp_tokens(1)
    hand = ctx.hand
    if hand:
        (card,) = yield ctx.choose("Bishop: trash a card from your hand.", hand)
        cost = ctx.cost_of(card)
        ctx.trash(card)
        if cost // 2 > 0:
            ctx.add_vp_tokens(cost // 2)
    for p in ctx.other_players():
        if ctx.is_invisible(p):
            continue
        p_hand = ctx.hand_of(p)
        if not p_hand:
            continue
        chosen = yield ctx.choose(
            f"{ctx.player_name}'s Bishop: you may trash a card from your hand.",
            p_hand, 0, 1, player=p,
        )
        if chosen:
            ctx.trash(chosen[0], player=p)


def _monument(ctx):
    ctx.add_coins(2)
    ctx.add_vp_tokens(1)


def _workers_village(ctx):
    ctx.draw(1)
    ctx.add_actions(2)
    ctx.add_buys(1)


# ----------------------------------------------------------------- $5
def _city(ctx):
    ctx.draw(1)
    ctx.add_actions(2)
    empty = ctx.empty_piles()
    if empty >= 1:
        ctx.draw(1)
    if empty >= 2:
        ctx.add_coins(1)
        ctx.add_buys(1)


def _contraband(ctx):
    ctx.add_buys(1)
    others = ctx.other_players()
    if not others:
        return
    left = others[0]
    piles = ctx.supply_names()
    if not piles:
        return
    (banned,) = yield ctx.choose(
        f"Contraband: choose a card that {ctx.player_name} cannot buy this turn.",
        piles, 1, 1, player=left,
    )
    ctx.ban_contraband(banned)


def _counting_house(ctx):
    coppers = tuple(c for c in ctx.discard_pile if c == "Copper")
    if not coppers:
        return
    chosen = yield ctx.choose(
        f"Counting House: put any number of Coppers ({len(coppers)} available) from your discard pile into your hand.",
        coppers, 0, len(coppers),
    )
    for _ in chosen:
        ctx.take_discard_to_hand("Copper")


def _mint(ctx):
    treasures = tuple(sorted({c for c in ctx.hand if ctx.is_treasure(c)}))
    if not treasures:
        return
    chosen = yield ctx.choose("Mint: you may reveal a Treasure from your hand to gain a copy of it.", treasures, 0, 1)
    if chosen:
        ctx.log(f"{ctx.player_name} reveals {chosen[0]}.", "reveal")
        ctx.gain(chosen[0])


def _mountebank(ctx):
    ctx.add_coins(2)
    targets = yield from ctx.attack()
    for p in targets:
        if "Curse" in ctx.hand_of(p):
            chosen = yield ctx.choose(
                f"{ctx.player_name}'s Mountebank: you may discard a Curse to avoid gaining a Curse and a Copper.",
                ("Curse",), 0, 1, player=p,
            )
            if chosen:
                ctx.discard("Curse", player=p)
                continue
        ctx.gain("Curse", player=p)
        ctx.gain("Copper", player=p)


def _rabble(ctx):
    ctx.draw(3)
    targets = yield from ctx.attack()
    for p in targets:
        revealed = ctx.take_to_set_aside(3, player=p, reveal=True)
        rest = []
        for c in revealed:
            if ctx.is_action(c) or ctx.is_treasure(c):
                ctx.discard_set_aside(c, player=p)
            else:
                rest.append(c)
        order = []
        while len(rest) > 1:
            if len(set(rest)) == 1:
                order.extend(rest)
                rest = []
                break
            (top,) = yield ctx.choose(
                "Rabble: choose the next card to put back on top of your deck.",
                tuple(rest), 1, 1, player=p,
            )
            rest.remove(top)
            order.append(top)
        order.extend(rest)
        for c in reversed(order):
            ctx.put_set_aside_on_deck(c, player=p)


def _vault(ctx):
    ctx.draw(2)
    hand = ctx.hand
    if hand:
        chosen = yield ctx.choose("Vault: discard any number of cards for +$1 each.", hand, 0, len(hand))
        for c in chosen:
            ctx.discard(c)
        if chosen:
            ctx.add_coins(len(chosen))
    for p in ctx.other_players():
        if ctx.is_invisible(p):
            continue
        p_hand = ctx.hand_of(p)
        if len(p_hand) < 2:
            continue
        want = yield ctx.choose(
            f"{ctx.player_name}'s Vault: you may discard 2 cards to draw 1 card.",
            ("Discard 2 cards", "Do nothing"), 1, 1, player=p,
        )
        if want and want[0] == "Discard 2 cards":
            picks = yield ctx.choose("Vault: choose 2 cards to discard.", p_hand, 2, 2, player=p)
            for c in picks:
                ctx.discard(c, player=p)
            ctx.draw(1, player=p)


def _venture(ctx):
    others = []
    found = None
    while True:
        cards = ctx.take_to_set_aside(1, reveal=True)
        if not cards:
            break
        card = cards[0]
        if ctx.is_treasure(card):
            found = card
            break
        others.append(card)
    for c in others:
        ctx.discard_set_aside(c)
    if found is not None:
        yield from ctx.play_set_aside_treasure(found)


# ----------------------------------------------------------------- $6
def _goons(ctx):
    ctx.add_buys(1)
    ctx.add_coins(2)
    targets = yield from ctx.attack()
    for p in targets:
        hand = ctx.hand_of(p)
        excess = len(hand) - 3
        if excess <= 0:
            continue
        chosen = yield ctx.choose(
            f"{ctx.player_name}'s Goons: discard {excess} card(s) to get down to 3.",
            hand, excess, excess, player=p,
        )
        for c in chosen:
            ctx.discard(c, player=p)


def _grand_market(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.add_buys(1)
    ctx.add_coins(2)


# ----------------------------------------------------------------- $7
def _bank_coins(state, player: int) -> int:
    return sum(1 for c in state.players[player].in_play if ctx_is_treasure(c))


def ctx_is_treasure(card: str) -> bool:
    from .registry import get_card
    return get_card(card).is_type(CardType.TREASURE)


def _expand(ctx):
    hand = ctx.hand
    if not hand:
        return
    (trashed,) = yield ctx.choose("Expand: trash a card from your hand.", hand)
    limit = ctx.cost_of(trashed) + 3
    ctx.trash(trashed)
    options = ctx.gainable(max_cost=limit)
    if not options:
        return
    (gained,) = yield ctx.choose(f"Expand: gain a card costing up to ${limit}.", options)
    ctx.gain(gained)


def _forge(ctx):
    hand = ctx.hand
    total_cost = 0
    if hand:
        chosen = yield ctx.choose("Forge: trash any number of cards from your hand.", hand, 0, len(hand))
        for c in chosen:
            total_cost += ctx.cost_of(c)
            ctx.trash(c)
    options = ctx.gainable(total_cost, exact=True)
    if not options:
        return
    (gained,) = yield ctx.choose(f"Forge: gain a card costing exactly ${total_cost}.", options)
    ctx.gain(gained)


def _kings_court(ctx):
    options = tuple(sorted({c for c in ctx.hand if ctx.is_action(c)}))
    if not options:
        return
    chosen = yield ctx.choose("King's Court: you may play an Action card from your hand three times.", options, 0, 1)
    if not chosen:
        return
    card = chosen[0]
    ctx.put_in_play(card, "hand")
    yield from ctx.resolve(card)
    yield from ctx.resolve(card)
    yield from ctx.resolve(card)


# ----------------------------------------------------------------- $8
def _peddler(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.add_coins(1)


# ------------------------------------------------------------ registration
def _reg_action(name, cost, fn, text, **kw):
    register(action(name, cost, fn, text, expansion=SET, **kw))


def _reg_treasure(name, cost, coins, text, on_play=None, coins_fn=None):
    register(treasure(
        name, cost, coins, text=text, on_play=on_play, coins_fn=coins_fn,
        kingdom=True, expansion=SET,
    ))


_reg_treasure("Loan", 3, 1, "$1. When you play this, reveal cards from your deck until you reveal a Treasure. Discard it or trash it. Discard the other cards.", on_play=_loan)
_reg_action("Trade Route", 3, _trade_route, "+1 Buy, +$1 per Coin token on the Trade Route mat. Trash a card from your hand. Setup: Add a token to the mat the first time a card is gained from each Victory pile.")
_reg_action("Watchtower", 3, _watchtower, "Draw until you have 6 cards in your hand. When you gain a card, you may reveal this from your hand, to either trash that card or put it on top of your deck.", extra_types=_REACTION)

_reg_action("Bishop", 4, _bishop, "+$1, +1 VP token. Trash a card from your hand. +1 VP token per $2 it costs (round down). Each other player may trash a card from their hand.")
_reg_action("Monument", 4, _monument, "+$2, +1 VP token.")
_reg_treasure("Quarry", 4, 1, "$1. While this is in play, Action cards cost $2 less, but not less than $0.")
_reg_treasure("Talisman", 4, 1, "$1. While this is in play, when you buy a non-Victory card costing $4 or less, gain a copy of it.")
_reg_action("Workers' Village", 4, _workers_village, "+1 Card, +2 Actions, +1 Buy.")

_reg_action("City", 5, _city, "+1 Card, +2 Actions. If there are one or more empty Supply piles, +1 Card. If there are two or more, +$1 and +1 Buy.")
_reg_treasure("Contraband", 5, 3, "$3, +1 Buy. When you play this, the player to your left names a card. You can't buy that card this turn.", on_play=_contraband)
_reg_action("Counting House", 5, _counting_house, "Look through your discard pile, reveal any number of Copper cards from it, and put them into your hand.")
_reg_action("Mint", 5, _mint, "You may reveal a Treasure card from your hand. Gain a copy of it. When you buy this, trash all Treasures you have in play.")
_reg_action("Mountebank", 5, _mountebank, "+$2. Each other player may discard a Curse. If they don't, they gain a Curse and a Copper.", extra_types=_ATTACK)
_reg_action("Rabble", 5, _rabble, "+3 Cards. Each other player reveals the top 3 cards of their deck, discards the revealed Actions and Treasures, and puts the rest back on top in any order they choose.", extra_types=_ATTACK)
_reg_treasure("Royal Seal", 5, 2, "$2. While this is in play, when you gain a card, you may put that card on top of your deck.")
_reg_action("Vault", 5, _vault, "+2 Cards. Discard any number of cards for +$1 each. Each other player may discard 2 cards, to draw a card.")
_reg_treasure("Venture", 5, 1, "$1. When you play this, reveal cards from your deck until you reveal a Treasure. Discard the other cards. Play that Treasure.", on_play=_venture)

_reg_action("Goons", 6, _goons, "+1 Buy, +$2. Each other player discards down to 3 cards in hand. While this is in play, when you buy a card, +1 VP token.", extra_types=_ATTACK)
_reg_action("Grand Market", 6, _grand_market, "+1 Card, +1 Action, +1 Buy, +$2. You can't buy this if you have any Copper in play.")
_reg_treasure("Hoard", 6, 2, "$2. While this is in play, when you buy a Victory card, gain a Gold.")

_reg_treasure("Bank", 7, 0, "When you play this, it's worth $1 per Treasure card you have in play (counting this).", coins_fn=_bank_coins)
_reg_action("Expand", 7, _expand, "Trash a card from your hand. Gain a card costing up to $3 more than it.")
_reg_action("Forge", 7, _forge, "Trash any number of cards from your hand. Gain a card with cost exactly equal to the total cost in coins of the trashed cards.")
_reg_action("King's Court", 7, _kings_court, "You may play an Action card from your hand three times.")

_reg_action("Peddler", 8, _peddler, "+1 Card, +1 Action, +$1. During your Buy phase, this costs $2 less per Action card you have in play, but not less than $0.")
