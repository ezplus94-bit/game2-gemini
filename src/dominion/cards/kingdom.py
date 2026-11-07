"""A small starter set of Kingdom cards (Dominion, 2nd edition).

Three kinds of effect are shown here:
  * simple      - plain functions (Village, Smithy, Market, ...)
  * interactive - generators that ``yield`` a Decision and receive the
                  player's answer (Cellar, Chapel, Workshop, Remodel, Moneylender)
  * scoring     - a Victory card with a score function (Gardens)

Each effect receives an ``EffectContext``; it never touches game state directly.
"""

from __future__ import annotations

from .base import CardType, action, victory
from .registry import register


# ----------------------------------------------------------------- simple
def _village(ctx):
    ctx.draw(1)
    ctx.add_actions(2)


def _smithy(ctx):
    ctx.draw(3)


def _market(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.add_buys(1)
    ctx.add_coins(1)


def _festival(ctx):
    ctx.add_actions(2)
    ctx.add_buys(1)
    ctx.add_coins(2)


def _laboratory(ctx):
    ctx.draw(2)
    ctx.add_actions(1)


# ------------------------------------------------------------ interactive
def _cellar(ctx):
    ctx.add_actions(1)
    hand = ctx.hand
    if not hand:
        return
    chosen = yield ctx.choose(
        "Discard any number of cards, then draw that many.", hand, 0, len(hand)
    )
    for card in chosen:
        ctx.discard(card)
    ctx.draw(len(chosen))


def _chapel(ctx):
    hand = ctx.hand
    if not hand:
        return
    chosen = yield ctx.choose("Trash up to 4 cards from your hand.", hand, 0, min(4, len(hand)))
    for card in chosen:
        ctx.trash(card)


def _workshop(ctx):
    options = ctx.gainable(max_cost=4)
    if not options:
        return
    (card,) = yield ctx.choose("Gain a card costing up to $4.", options)
    ctx.gain(card)


def _remodel(ctx):
    hand = ctx.hand
    if not hand:
        return
    (trashed,) = yield ctx.choose("Trash a card from your hand.", hand)
    ctx.trash(trashed)
    limit = ctx.cost_of(trashed) + 2
    options = ctx.gainable(max_cost=limit)
    if not options:
        return
    (card,) = yield ctx.choose(f"Gain a card costing up to ${limit}.", options)
    ctx.gain(card)


def _moneylender(ctx):
    if "Copper" not in ctx.hand:
        return
    chosen = yield ctx.choose("You may trash a Copper for +$3.", ("Copper",), 0, 1)
    if chosen:
        ctx.trash("Copper")
        ctx.add_coins(3)


# ---------------------------------------------- more cards (non-attack)
def _harbinger(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    options = tuple(sorted(set(ctx.discard_pile)))
    if not options:
        return
    chosen = yield ctx.choose(
        "You may put a card from your discard pile onto your deck.", options, 0, 1
    )
    if chosen:
        ctx.put_discard_on_deck(chosen[0])


def _merchant_bonus(ctx, trigger, card):
    """Trigger: the first Silver played this turn gives +$1 (once per Merchant)."""
    if trigger.used or card != "Silver":
        return
    trigger.used = True
    ctx.add_coins(1)
    ctx.log("Merchant gives +$1.")


def _merchant(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.add_trigger("treasure_played", _merchant_bonus)


def _vassal(ctx):
    ctx.add_coins(2)
    card = ctx.discard_top_of_deck()
    if card is None or not ctx.is_action(card):
        return
    chosen = yield ctx.choose(f"You discarded {card}. You may play it.", (card,), 0, 1)
    if chosen:
        ctx.put_in_play(card, "discard")
        yield from ctx.resolve(card)


def _poacher(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.add_coins(1)
    n = min(ctx.empty_piles(), ctx.hand_size)
    if n == 0:
        return
    if n == ctx.hand_size:                  # must discard everything: nothing to decide
        for card in ctx.hand:
            ctx.discard(card)
        return
    chosen = yield ctx.choose(f"Discard {n} card(s) (one per empty Supply pile).", ctx.hand, n, n)
    for card in chosen:
        ctx.discard(card)


def _mine(ctx):
    options = tuple(c for c in ctx.hand if ctx.is_treasure(c))
    if not options:
        return
    chosen = yield ctx.choose("You may trash a Treasure from your hand.", options, 0, 1)
    if not chosen:
        return
    trashed = chosen[0]
    ctx.trash(trashed)
    limit = ctx.cost_of(trashed) + 3
    gains = ctx.gainable(limit, CardType.TREASURE)
    if not gains:
        return
    (card,) = yield ctx.choose(f"Gain a Treasure costing up to ${limit} to your hand.", gains)
    ctx.gain(card, destination="hand")


def _library(ctx):
    set_aside = []
    drawn_count = 0
    while ctx.hand_size < 7:
        drawn = ctx.draw(1, quiet=True)
        if not drawn:
            break
        drawn_count += 1
        card = drawn[0]
        if ctx.is_action(card):
            chosen = yield ctx.choose(
                f"You drew {card}. Select it to set it aside, or select nothing to keep it.",
                (card,), 0, 1,
            )
            if chosen:
                ctx.set_aside_from_hand(card)
                set_aside.append(card)
    ctx.log(f"{ctx.player_name} draws {drawn_count} card(s) with Library.")
    for card in set_aside:
        ctx.discard_set_aside(card)


def _sentry(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    looked = ctx.take_to_set_aside(2)       # top card first
    if not looked:
        return
    to_trash = yield ctx.choose("Trash any number of these cards.", tuple(looked), 0, len(looked))
    for card in to_trash:
        looked.remove(card)
        ctx.trash_set_aside(card)
    if looked:
        to_discard = yield ctx.choose(
            "Discard any number of the remaining cards.", tuple(looked), 0, len(looked)
        )
        for card in to_discard:
            looked.remove(card)
            ctx.discard_set_aside(card)
    order = list(reversed(looked))          # bottom ... top; default keeps the original order
    if len(looked) == 2 and looked[0] != looked[1]:
        (top,) = yield ctx.choose(
            "Choose the card to put back on TOP of your deck (the other goes beneath it).",
            tuple(looked), 1, 1,
        )
        other = looked[0] if looked[1] == top else looked[1]
        order = [other, top]
    for card in order:
        ctx.put_set_aside_on_deck(card)
    if order:
        ctx.log(f"{ctx.player_name} puts {len(order)} card(s) back on their deck.")


def _artisan(ctx):
    options = ctx.gainable(max_cost=5)
    if options:
        (card,) = yield ctx.choose("Gain a card costing up to $5 to your hand.", options)
        ctx.gain(card, destination="hand")
    hand = ctx.hand
    if hand:
        (card,) = yield ctx.choose("Put a card from your hand onto your deck.", hand)
        ctx.put_hand_on_deck(card)


def _council_room(ctx):
    ctx.draw(4)
    ctx.add_buys(1)
    for other in ctx.other_players():
        ctx.draw(1, player=other)


def _throne_room(ctx):
    options = tuple(sorted({c for c in ctx.hand if ctx.is_action(c)}))
    if not options:
        return
    chosen = yield ctx.choose("You may play an Action card from your hand twice.", options, 0, 1)
    if not chosen:
        return
    card = chosen[0]
    ctx.put_in_play(card, "hand")
    yield from ctx.resolve(card)
    yield from ctx.resolve(card)


# ------------------------------------------------ attacks and reactions
def _moat(ctx):
    ctx.draw(2)


def _militia(ctx):
    ctx.add_coins(2)
    targets = yield from ctx.attack()
    for p in targets:
        hand = ctx.hand_of(p)
        excess = len(hand) - 3
        if excess <= 0:
            continue
        chosen = yield ctx.choose(
            f"{ctx.player_name}'s Militia: discard {excess} card(s) to get down to 3.",
            hand, excess, excess, player=p,
        )
        for card in chosen:
            ctx.discard(card, player=p)


def _witch(ctx):
    ctx.draw(2)
    targets = yield from ctx.attack()
    for p in targets:
        ctx.gain("Curse", player=p)


def _bandit(ctx):
    ctx.gain("Gold")
    targets = yield from ctx.attack()
    for p in targets:
        revealed = ctx.take_to_set_aside(2, player=p, reveal=True)
        if not revealed:
            continue
        eligible = sorted({c for c in revealed if ctx.is_treasure(c) and c != "Copper"})
        victim = None
        if len(eligible) == 1:
            victim = eligible[0]
        elif len(eligible) > 1:
            (victim,) = yield ctx.choose(
                f"{ctx.player_name}'s Bandit: choose a revealed Treasure (not Copper) to trash.",
                tuple(eligible), 1, 1, player=p,
            )
        if victim:
            revealed.remove(victim)
            ctx.trash_set_aside(victim, player=p)
        for card in revealed:
            ctx.discard_set_aside(card, player=p)


def _bureaucrat(ctx):
    ctx.gain("Silver", destination="deck")
    targets = yield from ctx.attack()
    for p in targets:
        hand = ctx.hand_of(p)
        victories = sorted({c for c in hand if ctx.is_victory(c)})
        if not victories:
            ctx.log(f"{ctx.name_of(p)} reveals a hand with no Victory cards: "
                    f"{', '.join(sorted(hand)) or 'nothing'}.")
            continue
        card = victories[0]
        if len(victories) > 1:
            (card,) = yield ctx.choose(
                f"{ctx.player_name}'s Bureaucrat: reveal a Victory card to put onto your deck.",
                tuple(victories), 1, 1, player=p,
            )
        ctx.put_hand_on_deck(card, player=p, reveal=True)


# ------------------------------------------------------------ registration
register(action("Cellar", 2, _cellar, "+1 Action. Discard any number of cards, then draw that many."))
register(action("Chapel", 2, _chapel, "Trash up to 4 cards from your hand."))
register(action("Village", 3, _village, "+1 Card, +2 Actions."))
register(action("Workshop", 3, _workshop, "Gain a card costing up to $4."))
register(action("Smithy", 4, _smithy, "+3 Cards."))
register(action("Remodel", 4, _remodel, "Trash a card from your hand. Gain a card costing up to $2 more."))
register(action("Moneylender", 4, _moneylender, "You may trash a Copper from your hand for +$3."))
register(action("Market", 5, _market, "+1 Card, +1 Action, +1 Buy, +$1."))
register(action("Festival", 5, _festival, "+2 Actions, +1 Buy, +$2."))
register(action("Laboratory", 5, _laboratory, "+2 Cards, +1 Action."))
register(action("Harbinger", 3, _harbinger, "+1 Card, +1 Action. Look through your discard pile. You may put a card from it onto your deck."))
register(action("Merchant", 3, _merchant, "+1 Card, +1 Action. The first time you play a Silver this turn, +$1."))
register(action("Vassal", 3, _vassal, "+$2. Discard the top card of your deck. If it's an Action card, you may play it."))
register(action("Poacher", 4, _poacher, "+1 Card, +1 Action, +$1. Discard a card per empty Supply pile."))
register(action("Throne Room", 4, _throne_room, "You may play an Action card from your hand twice."))
register(action("Mine", 5, _mine, "You may trash a Treasure from your hand. Gain a Treasure to your hand costing up to $3 more."))
register(action("Library", 5, _library, "Draw until you have 7 cards in hand, skipping any Action cards you choose to; set those aside, discarding them afterwards."))
register(action("Sentry", 5, _sentry, "+1 Card, +1 Action. Look at the top 2 cards of your deck. Trash and/or discard any number of them. Put the rest back on top in any order."))
register(action("Council Room", 5, _council_room, "+4 Cards, +1 Buy. Each other player draws a card."))
register(action("Artisan", 6, _artisan, "Gain a card to your hand costing up to $5. Put a card from your hand onto your deck."))
register(action("Moat", 2, _moat, "+2 Cards. When another player plays an Attack, you may first reveal this from your hand, to be unaffected by it.",
                extra_types=(CardType.REACTION,), blocks_attack=True))
register(action("Bureaucrat", 4, _bureaucrat, "Gain a Silver onto your deck. Each other player reveals a Victory card from their hand and puts it onto their deck (or reveals a hand with no Victory cards).",
                extra_types=(CardType.ATTACK,)))
register(action("Militia", 4, _militia, "+$2. Each other player discards down to 3 cards in hand.",
                extra_types=(CardType.ATTACK,)))
register(action("Witch", 5, _witch, "+2 Cards. Each other player gains a Curse.",
                extra_types=(CardType.ATTACK,)))
register(action("Bandit", 5, _bandit, "Gain a Gold. Each other player reveals the top 2 cards of their deck, trashes a revealed Treasure other than Copper, and discards the rest.",
                extra_types=(CardType.ATTACK,)))
register(
    victory(
        "Gardens", 4,
        score_fn=lambda cards: len(cards) // 10,
        text="Worth 1 VP per 10 cards you have (rounded down).",
        kingdom=True,
    )
)


from . import intrigue  # noqa: E402,F401  (registers the Intrigue expansion)
from . import catastrophe  # noqa: E402,F401  (registers the optional Catastrophe cards)
from . import special  # noqa: E402,F401  (registers the optional Special cards)
