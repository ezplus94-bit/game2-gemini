"""The Rising Sun expansion (2024): 25 Kingdom cards, 10 Events and 15 Prophecies.

  * Shadow cards (Alley, Fishmonger, Ninja, Ronin, Tanuki) can also be played from the deck during the Action phase (``PlayAction(card, from_deck=True)``)
    and go to the bottom of the deck when it is shuffled.
  * Omens ("+1 Sun" first): ``yield from ctx.remove_sun()``. A game with an Omen in the Kingdom has one Prophecy with Sun tokens on it; when the last one
    is removed the Prophecy's rule is in force (``GameState.prophecy_on``). The Prophecies themselves are in ``engine/risingsun.py``.
  * Debt (Empires) comes back: Artist, Daimyo, Mountain Shrine and the Event Continue cost only Debt; Craftsman, Gold Mine, Imperial Envoy, Litter and
    Root Cellar give Debt when played.
"""

from __future__ import annotations

from collections import Counter

from .base import CardDef, CardType
from .registry import get_card, register

SET = "Rising Sun"
T = CardType


def K(name, cost, types, fn, text, debt=0, **kw):
    return register(CardDef(name, cost, frozenset(types), on_play=fn, text=text, kingdom=kw.pop("kingdom", True), expansion=SET, debt_cost=debt, **kw))


def _distinct(cards) -> tuple:
    return tuple(sorted(set(cards)))


# ------------------------------------------------------------------ Shadows
def _alley(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    if ctx.hand:
        (card,) = yield ctx.choose("Alley: discard a card.", _distinct(ctx.hand))
        ctx.discard(card)


def _fishmonger(ctx):
    ctx.add_buys(1)
    ctx.add_coins(1)


def _ninja(ctx):
    ctx.draw(1)
    targets = yield from ctx.attack()
    for p in targets:
        excess = len(ctx.hand_of(p)) - 3
        if excess > 0:
            chosen = yield ctx.choose(f"{ctx.player_name}'s Ninja: discard {excess} card(s) to get down to 3.", ctx.hand_of(p), excess, excess, player=p)
            for c in chosen:
                ctx.discard(c, player=p)


def _ronin(ctx):
    n = 7 - len(ctx.hand)
    if n > 0:
        ctx.draw(n)


def _tanuki(ctx):
    if not ctx.hand:
        return
    (card,) = yield ctx.choose("Tanuki: trash a card from your hand. Gain a card costing up to $2 more than it.", _distinct(ctx.hand))
    coin, debt = ctx.cost_of(card), get_card(card).debt_cost
    ctx.trash(card)
    options = ctx.gainable_with_debt(coin + 2, debt)
    if options:
        (new,) = yield ctx.choose("Tanuki: gain a card costing up to $2 more.", options)
        ctx.gain(new)


# ------------------------------------------------------------------ Omens
def _kitsune(ctx):
    yield from ctx.remove_sun()
    listed = ("+2 Actions", "+$2", "Each other player gains a Curse", "Gain a Silver")
    chosen = yield ctx.choose("Kitsune: choose two different options.", listed, 2, 2)
    for option in listed:
        if option not in chosen:
            continue
        if option == listed[0]:
            ctx.add_actions(2)
        elif option == listed[1]:
            ctx.add_coins(2)
        elif option == listed[2]:
            targets = yield from ctx.attack()
            for p in targets:
                ctx.gain("Curse", player=p)
        else:
            ctx.gain("Silver")


def _mountain_shrine(ctx):
    yield from ctx.remove_sun()
    ctx.add_coins(2)
    if ctx.hand:
        chosen = yield ctx.choose("Mountain Shrine: you may trash a card from your hand.", _distinct(ctx.hand), 0, 1)
        if chosen:
            ctx.trash(chosen[0])
    if any(ctx.is_action(c) for c in ctx.trash_pile()):
        ctx.log("Mountain Shrine: there is an Action in the trash, +2 Cards.")
        ctx.draw(2)


def _poet(ctx):
    yield from ctx.remove_sun()
    ctx.draw(1)
    ctx.add_actions(1)
    cards = ctx.take_to_set_aside(1, reveal=True)
    if not cards:
        return
    card = cards[0]
    if ctx.cost_of(card) <= 3 and not get_card(card).potion_cost and not get_card(card).debt_cost:
        ctx.log(f"Poet: {card} costs $3 or less, it goes into your hand.")
        ctx.set_aside_to_hand(card)
    else:
        yield from ctx.put_back_in_order([card], "Poet: put it back on your deck.")


def _river_shrine(ctx):
    yield from ctx.remove_sun()
    if ctx.hand:
        chosen = yield ctx.choose("River Shrine: you may trash up to 2 cards from your hand.", tuple(sorted(ctx.hand)), 0, min(2, len(ctx.hand)))
        for c in chosen:
            ctx.trash(c)
    ctx.bump_count("river_shrine")


def _rustic_village(ctx):
    yield from ctx.remove_sun()
    ctx.draw(1)
    ctx.add_actions(2)
    if len(ctx.hand) >= 2:
        yes, no = "Discard 2 cards for +1 Card", "Don't"
        (mode,) = yield ctx.choose("Rustic Village: you may discard 2 cards for +1 Card.", (yes, no))
        if mode == yes:
            chosen = yield ctx.choose("Rustic Village: discard 2 cards.", tuple(sorted(ctx.hand)), 2, 2)
            for c in chosen:
                ctx.discard(c)
            ctx.draw(1)


def _tea_house(ctx):
    yield from ctx.remove_sun()
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.add_coins(2)


# ------------------------------------------------------------------ the rest
def _aristocrat(ctx):
    n = ctx.in_play.count("Aristocrat")
    ctx.log(f"Aristocrat: {n} in play.")
    if n in (1, 5):
        ctx.add_actions(3)
    elif n in (2, 6):
        ctx.draw(3)
    elif n in (3, 7):
        ctx.add_coins(3)
    elif n in (4, 8):
        ctx.add_buys(3)


def _artist(ctx):
    ctx.add_actions(1)
    counts = Counter(ctx.in_play)
    n = sum(1 for c in counts.values() if c == 1)
    ctx.log(f"Artist: {n} card(s) with exactly one copy in play.")
    ctx.draw(n)


def _change(ctx):
    if ctx.debt > 0:
        ctx.add_coins(3)
        return
    if not ctx.hand:
        return
    (card,) = yield ctx.choose("Change: trash a card from your hand, and gain a card costing more than it. +Debt equal to the difference.", _distinct(ctx.hand))
    cost = ctx.cost_of(card)
    ctx.trash(card)
    options = tuple(c for c in ctx.gainable(99) if ctx.cost_of(c) > cost)
    if options:
        (new,) = yield ctx.choose("Change: gain a card costing more.", options)
        if ctx.gain(new):
            ctx.add_debt(ctx.cost_of(new) - cost)


def _craftsman(ctx):
    ctx.add_debt(2)
    options = ctx.gainable(5)
    if options:
        (card,) = yield ctx.choose("Craftsman: gain a card costing up to $5.", options)
        ctx.gain(card)


def _daimyo(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.bump_count("daimyo")


def _gold_mine(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.add_buys(1)
    chosen = yield ctx.choose("Gold Mine: you may gain a Gold and take 4 Debt.", ("Gain a Gold and take 4 Debt",), 0, 1)
    if chosen:
        ctx.gain("Gold")
        ctx.add_debt(4)


def _imperial_envoy(ctx):
    ctx.draw(5)
    ctx.add_buys(1)
    ctx.add_debt(2)


def _litter(ctx):
    ctx.draw(2)
    ctx.add_actions(2)
    ctx.add_debt(1)


def _rice(ctx):
    ctx.add_buys(1)
    types = {t for c in ctx.in_play for t in ctx.card_types(c)}
    ctx.log(f"Rice: {len(types)} different type(s) in play ({', '.join(sorted(types))}), +${len(types)}.")
    ctx.add_coins(len(types))


def _rice_broker(ctx):
    ctx.add_actions(1)
    if not ctx.hand:
        return
    (card,) = yield ctx.choose("Rice Broker: trash a card from your hand. A Treasure gives +2 Cards, an Action +5 Cards.", _distinct(ctx.hand))
    treasure, action = ctx.is_treasure(card), ctx.is_action(card)
    ctx.trash(card)
    if treasure:
        ctx.draw(2)
    if action:
        ctx.draw(5)


def _riverboat(ctx):
    ctx.add_duration(_riverboat_start)


def _riverboat_start(ctx, entry):
    card = ctx.riverboat_card()
    if card:
        ctx.log(f"Riverboat plays the set-aside {card}.", "play")
        yield from ctx.resolve(card)


def _root_cellar(ctx):
    ctx.draw(3)
    ctx.add_actions(1)
    ctx.add_debt(3)


def _samurai(ctx):
    targets = yield from ctx.attack()
    for p in targets:
        excess = len(ctx.hand_of(p)) - 3
        if excess > 0:
            chosen = yield ctx.choose(f"{ctx.player_name}'s Samurai: discard {excess} card(s) to get down to 3.", ctx.hand_of(p), excess, excess, player=p)
            for c in chosen:
                ctx.discard(c, player=p)
    ctx.add_wait("never", handler=_samurai_start)


def _samurai_start(ctx, entry):
    ctx.log("Samurai: +$1.")
    ctx.add_coins(1)


def _snake_witch(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    hand = ctx.hand
    if len(set(hand)) != len(hand):
        return
    chosen = yield ctx.choose("Snake Witch: your hand has no duplicates. You may reveal it and return Snake Witch to its pile.", ("Reveal and return Snake Witch",), 0, 1)
    if not chosen:
        return
    ctx.log(f"{ctx.player_name} reveals {', '.join(sorted(hand)) or 'an empty hand'}.", "reveal")
    if ctx.return_to_pile("Snake Witch"):
        targets = yield from ctx.attack()
        for p in targets:
            ctx.gain("Curse", player=p)


K("Fishmonger", 2, (T.ACTION, T.SHADOW), _fishmonger, "+1 Buy. +$1. You can play this from your deck as if in your hand.")
K("Snake Witch", 2, (T.ACTION, T.ATTACK), _snake_witch, "+1 Card, +1 Action. If your hand has no duplicate cards, you may reveal it and return this to its pile, to have each other player gain a Curse.")
K("Aristocrat", 3, (T.ACTION,), _aristocrat, "If the number of Aristocrats you have in play is: 1 or 5: +3 Actions; 2 or 6: +3 Cards; 3 or 7: +$3; 4 or 8: +3 Buys.")
K("Craftsman", 3, (T.ACTION,), _craftsman, "+2 Debt. Gain a card costing up to $5.")
K("Riverboat", 3, (T.ACTION, T.DURATION), _riverboat, "At the start of your next turn, play the set aside card, leaving it there. Setup: Set aside an unused non-Duration Action card costing $5.")
K("Root Cellar", 3, (T.ACTION,), _root_cellar, "+3 Cards, +1 Action, +3 Debt.")
K("Alley", 4, (T.ACTION, T.SHADOW), _alley, "+1 Card, +1 Action. Discard a card. You can play this from your deck as if in your hand.")
K("Change", 4, (T.ACTION,), _change, "If you have any Debt, +$3. Otherwise, trash a card from your hand, and gain a card costing more than it. +Debt equal to the difference in $.")
K("Ninja", 4, (T.ACTION, T.ATTACK, T.SHADOW), _ninja, "+1 Card. Each other player discards down to 3 cards in hand. You can play this from your deck as if in your hand.")
K("Poet", 4, (T.ACTION, T.OMEN), _poet, "+1 Sun. +1 Card, +1 Action. Reveal the top card of your deck. If it costs $3 or less, put it into your hand.")
K("River Shrine", 4, (T.ACTION, T.OMEN), _river_shrine, "+1 Sun. Trash up to 2 cards from your hand. At the start of Clean-up, if you didn't gain any cards in your Buy phase this turn, gain a card costing up to $4.")
K("Rustic Village", 4, (T.ACTION, T.OMEN), _rustic_village, "+1 Sun. +1 Card, +2 Actions. You may discard 2 cards for +1 Card.")
K("Gold Mine", 5, (T.ACTION,), _gold_mine, "+1 Card, +1 Action, +1 Buy. You may gain a Gold and get +4 Debt.")
K("Imperial Envoy", 5, (T.ACTION,), _imperial_envoy, "+5 Cards, +1 Buy, +2 Debt.")
K("Kitsune", 5, (T.ACTION, T.ATTACK, T.OMEN), _kitsune, "+1 Sun. Choose two different options: +2 Actions; +$2; each other player gains a Curse; gain a Silver.")
K("Litter", 5, (T.ACTION,), _litter, "+2 Cards, +2 Actions, +1 Debt.")
K("Rice Broker", 5, (T.ACTION,), _rice_broker, "+1 Action. Trash a card from your hand. If it's a Treasure, +2 Cards. If it's an Action, +5 Cards.")
K("Ronin", 5, (T.ACTION, T.SHADOW), _ronin, "Draw until you have 7 cards in hand. You can play this from your deck as if in your hand.")
K("Tanuki", 5, (T.ACTION, T.SHADOW), _tanuki, "Trash a card from your hand. Gain a card costing up to $2 more than it. You can play this from your deck as if in your hand.")
K("Tea House", 5, (T.ACTION, T.OMEN), _tea_house, "+1 Sun. +1 Card, +1 Action, +$2.")
K("Samurai", 6, (T.ACTION, T.DURATION, T.ATTACK), _samurai, "Each other player discards down to 3 cards in hand (once). At the start of each of your turns this game, +$1. (This stays in play.)")
register(CardDef("Rice", 7, frozenset({T.TREASURE}), on_play=_rice, text="+1 Buy. +$1 per different type among cards you have in play.", kingdom=True, expansion=SET))
K("Mountain Shrine", 0, (T.ACTION, T.OMEN), _mountain_shrine, "+1 Sun. +$2. You may trash a card from your hand. Then if there are any Action cards in the trash, +2 Cards.", debt=5)
K("Daimyo", 0, (T.ACTION, T.COMMAND), _daimyo, "+1 Card, +1 Action. The next time you play a non-Command Action card this turn, replay it afterwards.", debt=6)
K("Artist", 0, (T.ACTION,), _artist, "+1 Action. +1 Card per card you have exactly one copy of in play.", debt=8)


# ================================================================== Events
def _event(name: str, cost: int, text: str, fn, once: bool = False, debt: int = 0):
    return register(CardDef(name, cost, frozenset({T.EVENT}), on_play=fn, text=text, kingdom=False, expansion=SET, once_per_turn=once, debt_cost=debt))


def _amass(ctx):
    if any(ctx.is_action(c) for c in ctx.in_play):
        ctx.log("Amass: you have Action cards in play, nothing happens.")
        return
    options = ctx.gainable(5, T.ACTION)
    if options:
        (card,) = yield ctx.choose("Amass: gain an Action card costing up to $5.", options)
        ctx.gain(card)


def _asceticism(ctx):
    top = min(ctx.coins, len(ctx.hand))
    if top <= 0:
        return
    options = tuple(f"Pay ${k}, trash {k} card{'s' if k > 1 else ''}" for k in range(1, top + 1))
    chosen = yield ctx.choose("Asceticism: pay any amount of $ to trash that many cards from your hand.", options, 0, 1)
    if not chosen:
        return
    k = int(chosen[0].split("$")[1].split(",")[0])
    ctx.add_coins(-k)
    cards = yield ctx.choose(f"Asceticism: trash {k} card(s) from your hand.", tuple(sorted(ctx.hand)), k, k)
    for c in cards:
        ctx.trash(c)


def _continue(ctx):
    options = tuple(c for c in ctx.gainable(4, T.ACTION) if not get_card(c).is_type(T.ATTACK))
    card = None
    if options:
        (card,) = yield ctx.choose("Continue: gain a non-Attack Action card costing up to $4, then play it.", options)
        ctx.gain(card)
    ctx.set_phase_to_action()
    ctx.add_actions(1)
    ctx.add_buys(1)
    if card is not None and card in ctx.discard_pile:
        ctx.put_in_play(card, "discard")
        yield from ctx.resolve(card)


def _credit(ctx):
    options = tuple(sorted(set(ctx.gainable(8, T.ACTION)) | set(ctx.gainable(8, T.TREASURE))))
    if options:
        (card,) = yield ctx.choose("Credit: gain an Action or Treasure costing up to $8. You take Debt equal to its cost.", options)
        cost = ctx.cost_of(card)
        if ctx.gain(card):
            ctx.add_debt(cost)


def _foresight(ctx):
    while True:
        cards = ctx.take_to_set_aside(1, reveal=True)
        if not cards:
            return
        card = cards[0]
        if ctx.is_action(card):
            ctx.eot_hand(card, "set_aside")
            ctx.log(f"Foresight: {card} is set aside; it goes into your hand at end of turn.")
            return
        ctx.discard_set_aside(card)


def _gather(ctx):
    for n in (3, 4, 5):
        options = ctx.gainable(n, exact=True)
        if options:
            (card,) = yield ctx.choose(f"Gather: gain a card costing exactly ${n}.", options)
            ctx.gain(card)


def _kintsugi(ctx):
    if not ctx.hand:
        return
    (card,) = yield ctx.choose("Kintsugi: trash a card from your hand.", _distinct(ctx.hand))
    coin, debt = ctx.cost_of(card), get_card(card).debt_cost
    ctx.trash(card)
    if ctx.gold_gained_ever():
        options = ctx.gainable_with_debt(coin + 2, debt)
        if options:
            (new,) = yield ctx.choose("Kintsugi: you have gained a Gold this game. Gain a card costing up to $2 more.", options)
            ctx.gain(new)


def _practice(ctx):
    options = _distinct(c for c in ctx.hand if ctx.is_action(c))
    if not options:
        return
    chosen = yield ctx.choose("Practice: you may play an Action card from your hand twice.", options, 0, 1)
    if chosen:
        card = chosen[0]
        ctx.put_in_play(card)
        yield from ctx.resolve(card)
        yield from ctx.resolve(card)


def _receive_tribute(ctx):
    if ctx.gained_this_turn_count() < 3:
        ctx.log("Receive Tribute: you haven't gained 3 cards this turn.")
        return
    taken = []
    for _ in range(3):
        options = tuple(c for c in ctx.gainable(99, T.ACTION) if c not in taken and c not in ctx.in_play)
        if not options:
            return
        chosen = yield ctx.choose("Receive Tribute: gain a differently named Action card you don't have a copy of in play.", options, 0, 1)
        if not chosen:
            return
        taken.append(chosen[0])
        ctx.gain(chosen[0])


def _sea_trade(ctx):
    n = sum(1 for c in ctx.in_play if ctx.is_action(c))
    ctx.log(f"Sea Trade: {n} Action card(s) in play, +{n} Card(s).")
    ctx.draw(n)
    if n and ctx.hand:
        chosen = yield ctx.choose(f"Sea Trade: trash up to {n} cards from your hand.", tuple(sorted(ctx.hand)), 0, min(n, len(ctx.hand)))
        for c in chosen:
            ctx.trash(c)


_event("Amass", 2, "If you have no Action cards in play, gain an Action card costing up to $5.", _amass)
_event("Asceticism", 2, "Pay any amount of $ to trash that many cards from your hand.", _asceticism)
_event("Credit", 2, "Gain an Action or Treasure costing up to $8. +Debt equal to its cost.", _credit)
_event("Foresight", 2, "Reveal cards from your deck until revealing an Action. Set it aside and discard the rest. Put it into your hand at end of turn.", _foresight)
_event("Kintsugi", 3, "Trash a card from your hand. If you've gained a Gold this game, gain a card costing up to $2 more than the trashed card.", _kintsugi)
_event("Practice", 3, "You may play an Action card from your hand twice.", _practice)
_event("Sea Trade", 4, "+1 Card per Action card you have in play. Trash up to that many cards from your hand.", _sea_trade)
_event("Receive Tribute", 5, "If you've gained at least 3 cards this turn, gain up to 3 differently named Action cards you don't have copies of in play.", _receive_tribute)
_event("Gather", 7, "Gain a card costing exactly $3, a card costing exactly $4, and a card costing exactly $5.", _gather)
_event("Continue", 0, "Once per turn: Gain a non-Attack Action card costing up to $4. Return to your Action phase and play it. +1 Action and +1 Buy.", _continue, once=True, debt=8)


# ================================================================== Prophecies (their rules are applied by engine/risingsun.py)
def _prophecy(name: str, text: str):
    return register(CardDef(name, 0, frozenset({T.PROPHECY}), text=text, kingdom=False, expansion=SET))


_prophecy("Approaching Army", "After you play an Attack card, +$1. Setup: Add an Attack Kingdom card pile to the Supply.")
_prophecy("Biding Time", "At the start of your Clean-up, set aside your hand face down. At the start of your next turn, put those cards into your hand.")
_prophecy("Bureaucracy", "When you gain a card that doesn't cost $0, gain a Copper.")
_prophecy("Divine Wind", "When you remove the last Sun, remove all Kingdom card piles from the Supply, and set up 10 new random piles.")
_prophecy("Enlightenment", "Treasures are also Actions. When you play a Treasure in an Action phase, instead of following its instructions, +1 Card and +1 Action.")
_prophecy("Flourishing Trade", "Cards cost $1 less. You may use Action plays as Buys.")
_prophecy("Good Harvest", "The first time you play each differently named Treasure each turn, first, +1 Buy and +$1.")
_prophecy("Great Leader", "After each Action card you play, +1 Action.")
_prophecy("Growth", "When you gain a Treasure, gain a cheaper card.")
_prophecy("Harsh Winter", "When you gain a card on your turn, if there's Debt on its pile, take it; otherwise put 2 Debt on its pile.")
_prophecy("Kind Emperor", "At the start of your turn, and when you remove the last Sun: Gain an Action to your hand.")
_prophecy("Panic", "When you play a Treasure, +2 Buys, and when you discard one from play, return it to its pile.")
_prophecy("Progress", "When you gain a card, put it onto your deck.")
_prophecy("Rapid Expansion", "When you gain an Action or Treasure, set it aside, and play it at the start of your next turn.")
_prophecy("Sickness", "At the start of your turn, choose one: Gain a Curse onto your deck; or discard 3 cards.")
