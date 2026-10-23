"""The Intrigue expansion (2nd edition): 26 Kingdom cards.

What is new compared with the base set, and where the engine supports it:

  * Cards with two types: Nobles and Mill (Action-Victory), Harem (Treasure-Victory).
  * Cost reduction for a turn: Bridge (``ctx.reduce_costs``; every cost check goes
    through ``engine.costs.card_cost``).
  * "Choose one / choose two" cards: Pawn, Steward, Courtier, Minion, Nobles.
  * Everyone answers at once: Masquerade (each player passes a card).
  * Reactions with an effect: Diplomat (``CardDef.on_attack``).
  * Scoring by what you own: Duke (1 VP per Duchy).
  * Playing-count effects: Conspirator (counts Actions played this turn).
  * Using the trash and the Supply: Lurker (trash from the Supply, gain from the trash).
  * New Attacks: Swindler, Torturer, Minion, Replace.
"""

from __future__ import annotations

from .base import CardType, action, action_victory, treasure_victory, victory
from .registry import register

SET = "Intrigue"


def _real_actions(names):
    """Action cards that are not Catastrophe cards (those stay out of Lurker's reach)."""
    from .registry import get_card
    return tuple(sorted(
        c for c in set(names)
        if get_card(c).is_type(CardType.ACTION) and not get_card(c).is_type(CardType.CATASTROPHE)
        and not get_card(c).is_type(CardType.SPECIAL)
    ))


# ----------------------------------------------------------------- $2
def _courtyard(ctx):
    ctx.draw(3)
    hand = ctx.hand
    if hand:
        (card,) = yield ctx.choose("Put a card from your hand onto your deck.", hand)
        ctx.put_hand_on_deck(card)


def _lurker(ctx):
    ctx.add_actions(1)
    from_supply = _real_actions(name for name in ctx.supply_names() if ctx.supply_count(name) > 0)
    from_trash = _real_actions(ctx.trash_pile())
    modes = []
    if from_supply:
        modes.append("Trash an Action card from the Supply")
    if from_trash:
        modes.append("Gain an Action card from the trash")
    if not modes:
        return
    mode = modes[0]
    if len(modes) > 1:
        (mode,) = yield ctx.choose("Lurker: choose one.", modes)
    if mode.startswith("Trash"):
        (card,) = yield ctx.choose("Trash an Action card from the Supply.", from_supply)
        ctx.trash_from_supply(card)
    else:
        (card,) = yield ctx.choose("Gain an Action card from the trash.", from_trash)
        ctx.gain_from_trash(card)


_PAWN_OPTIONS = ("+1 Card", "+1 Action", "+1 Buy", "+$1")


def _pawn(ctx):
    chosen = yield ctx.choose("Pawn: choose two different effects.", _PAWN_OPTIONS, 2, 2)
    if "+1 Card" in chosen:
        ctx.draw(1)
    if "+1 Action" in chosen:
        ctx.add_actions(1)
    if "+1 Buy" in chosen:
        ctx.add_buys(1)
    if "+$1" in chosen:
        ctx.add_coins(1)


# ----------------------------------------------------------------- $3
def _masquerade(ctx):
    ctx.draw(2)
    passes = {}
    for p in [ctx.player, *[q for q in ctx.other_players() if not ctx.is_invisible(q)]]:
        hand = ctx.hand_of(p)
        if hand:
            (card,) = yield ctx.choose(
                "Masquerade: choose a card from your hand to pass to the player on your left.",
                hand, 1, 1, player=p,
            )
            passes[p] = card
    if passes:
        ctx.pass_cards(passes)
    hand = ctx.hand
    if hand:
        chosen = yield ctx.choose("You may trash a card from your hand.", hand, 0, 1)
        if chosen:
            ctx.trash(chosen[0])


def _shanty_town(ctx):
    ctx.add_actions(2)
    hand = ctx.hand
    ctx.log(f"{ctx.player_name} reveals their hand: {', '.join(sorted(hand)) or 'nothing'}.", "reveal")
    if not any(ctx.is_action(c) for c in hand):
        ctx.draw(2)


_STEWARD_OPTIONS = ("+2 Cards", "+$2", "Trash 2 cards from your hand")


def _steward(ctx):
    options = _STEWARD_OPTIONS if ctx.hand else _STEWARD_OPTIONS[:2]
    (mode,) = yield ctx.choose("Steward: choose one.", options)
    if mode == "+2 Cards":
        ctx.draw(2)
    elif mode == "+$2":
        ctx.add_coins(2)
    else:
        hand = ctx.hand
        n = min(2, len(hand))
        chosen = yield ctx.choose(f"Trash {n} card(s) from your hand.", hand, n, n)
        for card in chosen:
            ctx.trash(card)


def _swindler(ctx):
    ctx.add_coins(2)
    targets = yield from ctx.attack()
    for p in targets:
        trashed = ctx.trash_top_of_deck(p)
        if trashed is None:
            continue
        cost = ctx.cost_of(trashed)
        options = ctx.gainable(cost, exact=True, gainer=p)
        if not options:
            continue
        (card,) = yield ctx.choose(
            f"Swindler: choose the card {ctx.name_of(p)} gains (it must cost ${cost}).", options,
        )
        ctx.gain(card, player=p)


def _wishing_well(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    (named,) = yield ctx.choose("Wishing Well: name a card.", ctx.supply_names())
    ctx.log(f"{ctx.player_name} names {named}.")
    cards = ctx.take_to_set_aside(1, reveal=True)
    if not cards:
        return
    card = cards[0]
    if card == named:
        ctx.set_aside_to_hand(card)
        ctx.log(f"It matches! {card} goes into {ctx.player_name}'s hand.")
    else:
        ctx.put_set_aside_on_deck(card)


# ----------------------------------------------------------------- $4
def _baron(ctx):
    ctx.add_buys(1)
    if "Estate" in ctx.hand:
        chosen = yield ctx.choose(
            "You may discard an Estate for +$4. If you don't, you gain an Estate.", ("Estate",), 0, 1,
        )
        if chosen:
            ctx.discard("Estate")
            ctx.add_coins(4)
            return
    ctx.gain("Estate")


def _bridge(ctx):
    ctx.add_buys(1)
    ctx.add_coins(1)
    ctx.reduce_costs(1)


def _conspirator(ctx):
    ctx.add_coins(2)
    if ctx.plays_this_turn >= 3:
        ctx.draw(1)
        ctx.add_actions(1)


def _diplomat(ctx):
    ctx.draw(2)
    if ctx.hand_size <= 5:
        ctx.add_actions(2)


def _diplomat_reaction(ctx):
    ctx.draw(2)
    hand = ctx.hand
    n = min(3, len(hand))
    chosen = yield ctx.choose("Diplomat: discard 3 cards.", hand, n, n)
    for card in chosen:
        ctx.discard(card)


def _ironworks(ctx):
    options = ctx.gainable(max_cost=4)
    if not options:
        return
    (card,) = yield ctx.choose("Gain a card costing up to $4.", options)
    ctx.gain(card)
    if ctx.is_action(card):
        ctx.add_actions(1)
    if ctx.is_treasure(card):
        ctx.add_coins(1)
    if ctx.is_victory(card):
        ctx.draw(1)


def _mill(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    if ctx.hand_size < 2:
        return
    (answer,) = yield ctx.choose("You may discard 2 cards for +$2.", ("Yes", "No"))
    if answer == "Yes":
        chosen = yield ctx.choose("Choose 2 cards to discard.", ctx.hand, 2, 2)
        for card in chosen:
            ctx.discard(card)
        ctx.add_coins(2)


def _mining_village(ctx):
    ctx.draw(1)
    ctx.add_actions(2)
    if ctx.source not in ctx.in_play:
        return
    chosen = yield ctx.choose("You may trash this Mining Village for +$2.", ("Mining Village",), 0, 1)
    if chosen and ctx.trash_self():
        ctx.add_coins(2)


def _secret_passage_spots(deck_size: int) -> dict:
    """label -> number of cards above it. A few handy spots rather than every position."""
    spots = {0: "On top of your deck"}
    for k, label in ((1, "2nd from the top"), (2, "3rd from the top"), (3, "4th from the top"), (4, "5th from the top")):
        if k <= deck_size:
            spots[k] = label
    if deck_size >= 6:
        spots[deck_size // 2] = "In the middle of your deck"
    if deck_size >= 1:
        spots[deck_size] = "On the bottom of your deck"
    return {label: k for k, label in sorted(spots.items())}


def _secret_passage(ctx):
    ctx.draw(2)
    ctx.add_actions(1)
    hand = ctx.hand
    if not hand:
        return
    (card,) = yield ctx.choose("Choose a card from your hand to put into your deck.", hand)
    spots = _secret_passage_spots(ctx.deck_size)
    (where,) = yield ctx.choose(f"Where does {card} go?", tuple(spots))
    ctx.put_hand_in_deck(card, spots[where])


# ----------------------------------------------------------------- $5
_COURTIER_OPTIONS = ("+1 Action", "+1 Buy", "+$3", "Gain a Gold")


def _courtier(ctx):
    hand = ctx.hand
    if not hand:
        return
    (card,) = yield ctx.choose("Courtier: reveal a card from your hand.", hand)
    ctx.log(f"{ctx.player_name} reveals {card}.", "reveal")
    n = min(len(ctx.card_types(card)), len(_COURTIER_OPTIONS))
    chosen = yield ctx.choose(
        f"Courtier: {card} has {n} type(s). Choose {n} different effect(s).", _COURTIER_OPTIONS, n, n,
    )
    if "+1 Action" in chosen:
        ctx.add_actions(1)
    if "+1 Buy" in chosen:
        ctx.add_buys(1)
    if "+$3" in chosen:
        ctx.add_coins(3)
    if "Gain a Gold" in chosen:
        ctx.gain("Gold")


def _minion(ctx):
    ctx.add_actions(1)
    (mode,) = yield ctx.choose(
        "Minion: choose one.", ("+$2", "Discard your hand, +4 Cards, and attack"),
    )
    if mode == "+$2":
        ctx.add_coins(2)
        return
    targets = yield from ctx.attack()
    ctx.discard_hand()
    ctx.draw(4)
    for p in targets:
        if len(ctx.hand_of(p)) >= 5:
            ctx.discard_hand(p)
            ctx.draw(4, player=p)


def _patrol(ctx):
    ctx.draw(3)
    cards = ctx.take_to_set_aside(4, reveal=True)
    rest = []
    for card in cards:
        if ctx.is_victory(card) or "curse" in ctx.card_types(card):
            ctx.set_aside_to_hand(card)
        else:
            rest.append(card)
    order = []                                       # top of the deck first
    while len(rest) > 1:
        if len(set(rest)) == 1:
            order.extend(rest)
            rest = []
            break
        (top,) = yield ctx.choose("Patrol: choose the next card to put back, from the top down.", tuple(rest))
        rest.remove(top)
        order.append(top)
    order.extend(rest)
    for card in reversed(order):
        ctx.put_set_aside_on_deck(card)
    if order:
        ctx.log(f"{ctx.player_name} puts {len(order)} card(s) back on their deck.")


def _replace(ctx):
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
    ctx.gain(card, destination="deck" if (ctx.is_action(card) or ctx.is_treasure(card)) else "discard")
    if ctx.is_victory(card):
        targets = yield from ctx.attack()
        for p in targets:
            ctx.gain("Curse", player=p)


def _torturer(ctx):
    ctx.draw(3)
    targets = yield from ctx.attack()
    for p in targets:
        can_discard = len(ctx.hand_of(p)) >= 2
        can_curse = ctx.supply_count("Curse") > 0
        if not can_discard and not can_curse:
            continue
        if can_discard and can_curse:
            (mode,) = yield ctx.choose(
                f"{ctx.player_name}'s Torturer: discard 2 cards, or gain a Curse into your hand.",
                ("Discard 2 cards", "Gain a Curse"), player=p,
            )
        else:
            mode = "Discard 2 cards" if can_discard else "Gain a Curse"
        if mode == "Gain a Curse":
            ctx.gain("Curse", player=p, destination="hand")
        else:
            chosen = yield ctx.choose("Torturer: choose 2 cards to discard.", ctx.hand_of(p), 2, 2, player=p)
            for card in chosen:
                ctx.discard(card, player=p)


def _trading_post(ctx):
    hand = ctx.hand
    n = min(2, len(hand))
    if n == 0:
        return
    chosen = yield ctx.choose(f"Trash {n} card(s) from your hand.", hand, n, n)
    for card in chosen:
        ctx.trash(card)
    if len(chosen) == 2:
        ctx.gain("Silver", destination="hand")


def _upgrade(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    hand = ctx.hand
    if not hand:
        return
    (trashed,) = yield ctx.choose("Trash a card from your hand.", hand)
    ctx.trash(trashed)
    target = ctx.cost_of(trashed) + 1
    options = ctx.gainable(target, exact=True)
    if not options:
        return
    (card,) = yield ctx.choose(f"Gain a card costing exactly ${target}.", options)
    ctx.gain(card)


# ----------------------------------------------------------------- $6
_NOBLES_OPTIONS = ("+3 Cards", "+2 Actions")


def _nobles(ctx):
    (mode,) = yield ctx.choose("Nobles: choose one.", _NOBLES_OPTIONS)
    if mode == "+3 Cards":
        ctx.draw(3)
    else:
        ctx.add_actions(2)


# ------------------------------------------------------------ registration
def _reg(name, cost, fn, text, **kw):
    register(action(name, cost, fn, text, expansion=SET, **kw))


_reg("Courtyard", 2, _courtyard, "+3 Cards. Put a card from your hand onto your deck.")
_reg("Lurker", 2, _lurker, "+1 Action. Choose one: trash an Action card from the Supply, or gain an Action card from the trash.")
_reg("Pawn", 2, _pawn, "Choose two different: +1 Card; +1 Action; +1 Buy; +$1.")
_reg("Masquerade", 3, _masquerade, "+2 Cards. Each player with any cards in hand passes one to the player on their left, all at once. Then you may trash a card from your hand.")
_reg("Shanty Town", 3, _shanty_town, "+2 Actions. Reveal your hand. If you have no Action cards in hand, +2 Cards.")
_reg("Steward", 3, _steward, "Choose one: +2 Cards; or +$2; or trash 2 cards from your hand.")
_reg("Swindler", 3, _swindler, "+$2. Each other player trashes the top card of their deck and gains a card with the same cost that you choose.",
     extra_types=(CardType.ATTACK,))
_reg("Wishing Well", 3, _wishing_well, "+1 Card, +1 Action. Name a card, then reveal the top card of your deck. If it is the card you named, put it into your hand.")
_reg("Baron", 4, _baron, "+1 Buy. You may discard an Estate for +$4. If you don't, gain an Estate.")
_reg("Bridge", 4, _bridge, "+1 Buy, +$1. This turn, cards (everywhere) cost $1 less, but not less than $0.")
_reg("Conspirator", 4, _conspirator, "+$2. If you have played 3 or more Actions this turn (counting this), +1 Card and +1 Action.")
_reg("Diplomat", 4, _diplomat, "+2 Cards. If you have 5 or fewer cards in hand, +2 Actions. Reaction: when another player plays an Attack, you may first reveal this from a hand of 5 or more cards: draw 2 cards, then discard 3.",
     extra_types=(CardType.REACTION,), on_attack=_diplomat_reaction, on_attack_min_hand=5)
_reg("Ironworks", 4, _ironworks, "Gain a card costing up to $4. If it is an Action, +1 Action. If it is a Treasure, +$1. If it is a Victory card, +1 Card.")
register(action_victory("Mill", 4, _mill, 1, "1 VP. +1 Card, +1 Action. You may discard 2 cards for +$2.", SET))
_reg("Mining Village", 4, _mining_village, "+1 Card, +2 Actions. You may trash this for +$2.")
_reg("Secret Passage", 4, _secret_passage, "+2 Cards, +1 Action. Take a card from your hand and put it into your deck: on top, 2nd to 5th from the top, in the middle or on the bottom.")
_reg("Courtier", 5, _courtier, "Reveal a card from your hand. For each type it has (Action, Attack, Reaction, Treasure, Victory, Curse), choose a different one: +1 Action; +1 Buy; +$3; gain a Gold.")
register(victory("Duke", 5, score_fn=lambda cards: list(cards).count("Duchy"),
                 text="Worth 1 VP per Duchy you have.", kingdom=True, expansion=SET))
_reg("Minion", 5, _minion, "+1 Action. Choose one: +$2; or discard your hand, +4 Cards, and each other player with 5 or more cards in hand discards their hand and draws 4 cards.",
     extra_types=(CardType.ATTACK,))
_reg("Patrol", 5, _patrol, "+3 Cards. Reveal the top 4 cards of your deck. Put the Victory cards and Curses into your hand. Put the rest back in any order.")
_reg("Replace", 5, _replace, "Trash a card from your hand. Gain a card costing up to $2 more. If it is an Action or Treasure, put it onto your deck. If it is a Victory card, each other player gains a Curse.",
     extra_types=(CardType.ATTACK,))
_reg("Torturer", 5, _torturer, "+3 Cards. Each other player chooses: discard 2 cards, or gain a Curse into their hand.",
     extra_types=(CardType.ATTACK,))
_reg("Trading Post", 5, _trading_post, "Trash 2 cards from your hand. If you did, gain a Silver to your hand.")
_reg("Upgrade", 5, _upgrade, "+1 Card, +1 Action. Trash a card from your hand. Gain a card costing exactly $1 more than it.")
register(treasure_victory("Harem", 6, 2, 2, "$2 and 2 VP. A Treasure and a Victory card.", SET))
register(action_victory("Nobles", 6, _nobles, 2, "2 VP. Choose one: +3 Cards; or +2 Actions.", SET))
