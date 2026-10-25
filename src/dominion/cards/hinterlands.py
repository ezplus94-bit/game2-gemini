"""The Hinterlands expansion (2nd edition, 2022): 26 Kingdom cards.

All 17 retained cards from the 1st edition plus the 9 replacement cards added in the 2nd edition
(Berserker, Cauldron, Guard Dog, Nomads, Souk, Trail, Weaver, Wheelwright, Witch's Hut).

What is new in the engine:

  * Discard-outside-cleanup reactions (``CardDef.on_discard``): Tunnel (reveal to gain a Gold),
    Trail and Weaver (play it when discarded outside of Clean-up).
  * Opponent gain reactions (``CardDef.on_other_gain_reaction``): Fool's Gold (trash from hand when
    another player gains a Province to gain a Gold onto your deck) and Guard Dog (play from hand when
    another player gains a card costing $5 or more).
  * Would-gain replacement reaction: Trader (reveal from hand when gaining a card to gain a Silver instead).
  * On-gain triggers (``CardDef.on_gain``): Border Village (gain a cheaper card), Inn (shuffle revealed
    Actions from discard into deck), Nomads (+$2 when gained or trashed), Souk (trash up to 2 cards from
    hand), Trail (may play it), Berserker (if you have an Action in play, play this), Farmland (on buy:
    trash a card from hand and gain one costing exactly $2 more).
  * In-play triggers: Haggler (when you buy a card, gain a cheaper non-Victory card), Cauldron (the 3rd
    time you gain an Action card in a turn, each other player gains a Curse), Highway (cards cost $1 less
    while in play).
  * Cleanup hook: Scheme (put an Action card discarded from play onto your deck).
"""

from __future__ import annotations

from .alchemy import _put_back_in_any_order
from .base import CardType, action, treasure, victory, victory_reaction
from .registry import register

SET = "Hinterlands"
_ATTACK = (CardType.ATTACK,)
_REACTION = (CardType.REACTION,)


# ----------------------------------------------------------------- $2
def _crossroads(ctx):
    hand = ctx.hand
    ctx.log(f"{ctx.player_name} reveals their hand: {', '.join(sorted(hand)) or 'nothing'}.", "reveal")
    victories = sum(1 for c in hand if ctx.is_victory(c))
    if victories:
        ctx.draw(victories)
    if ctx.mark_crossroads() == 1:
        ctx.add_actions(3)


def _fools_gold_coins(state, player: int) -> int:
    return 1 if state.fools_gold_played == 0 else 4


def _fools_gold_play(ctx):
    ctx.mark_fools_gold()


def _fools_gold_reaction(ctx, event):
    if event.card != "Province" or "Fool's Gold" not in ctx.hand:
        return
    chosen = yield ctx.choose(
        f"{ctx.name_of(event.player)} gained a Province. You may trash Fool's Gold from your hand to gain a Gold onto your deck.",
        ("Fool's Gold",), 0, 1,
    )
    if chosen and "Fool's Gold" in ctx.hand:
        ctx.trash("Fool's Gold")
        ctx.gain("Gold", destination="deck")


# ----------------------------------------------------------------- $3
def _develop(ctx):
    hand = ctx.hand
    if not hand:
        return
    (trashed,) = yield ctx.choose("Develop: trash a card from your hand.", hand)
    ctx.trash(trashed)
    if ctx.potion_cost_of(trashed) > 0:
        return
    base_cost = ctx.cost_of(trashed)
    high_cost = base_cost + 1
    low_cost = base_cost - 1
    order = [high_cost, low_cost]
    has_high = bool(ctx.gainable(high_cost, exact=True))
    has_low = low_cost >= 0 and bool(ctx.gainable(low_cost, exact=True))
    if has_high and has_low:
        (first_label,) = yield ctx.choose(
            f"Develop: choose which cost to gain onto your deck first (${high_cost} or ${low_cost}).",
            (f"Gain ${high_cost} card first", f"Gain ${low_cost} card first"),
        )
        if first_label.startswith(f"Gain ${low_cost}"):
            order = [low_cost, high_cost]
    for target in order:
        if target < 0:
            continue
        options = ctx.gainable(target, exact=True)
        if not options:
            continue
        (card,) = yield ctx.choose(f"Develop: gain a card costing exactly ${target} onto your deck.", options)
        ctx.gain(card, destination="deck")


def _guard_dog(ctx):
    ctx.draw(2)
    if ctx.hand_size <= 5:
        ctx.add_actions(2)


def _guard_dog_reaction(ctx, event):
    if ctx.cost_of(event.card) < 5 or "Guard Dog" not in ctx.hand:
        return
    chosen = yield ctx.choose(
        f"{ctx.name_of(event.player)} gained {event.card} (costs ${ctx.cost_of(event.card)}). You may play Guard Dog from your hand.",
        ("Guard Dog",), 0, 1,
    )
    if chosen and "Guard Dog" in ctx.hand:
        yield from ctx.play_from_zone("Guard Dog", "hand")


def _oasis(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.add_coins(1)
    hand = ctx.hand
    if not hand:
        return
    (card,) = yield ctx.choose("Oasis: discard a card from your hand.", hand)
    ctx.discard(card)


def _scheme(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.add_scheme()


def _tunnel_discard(ctx):
    chosen = yield ctx.choose(
        "Tunnel: you discarded Tunnel. You may reveal it to gain a Gold.",
        ("Reveal Tunnel (gain a Gold)",), 0, 1,
    )
    if chosen:
        ctx.log(f"{ctx.player_name} reveals Tunnel.", "reveal")
        ctx.gain("Gold")


# ----------------------------------------------------------------- $4
def _jack_of_all_trades(ctx):
    ctx.gain("Silver")
    cards = ctx.take_to_set_aside(1)
    if cards:
        top = cards[0]
        (mode,) = yield ctx.choose(
            f"Jack of All Trades: the top card of your deck is {top}. Discard it or put it back?",
            ("Discard it", "Put it back"),
        )
        if mode == "Discard it":
            ctx.discard_set_aside(top)
        else:
            ctx.put_set_aside_on_deck(top)
    drawn = 0
    while ctx.hand_size < 5:
        if not ctx.draw(1, quiet=True):
            break
        drawn += 1
    if drawn:
        ctx.log(f"{ctx.player_name} draws {drawn} card(s) with Jack of All Trades.")
    non_treasures = tuple(sorted({c for c in ctx.hand if not ctx.is_treasure(c)}))
    if non_treasures:
        chosen = yield ctx.choose(
            "Jack of All Trades: you may trash a non-Treasure card from your hand.",
            non_treasures, 0, 1,
        )
        if chosen:
            ctx.trash(chosen[0])


def _nomads(ctx):
    ctx.add_buys(1)
    ctx.add_coins(2)


def _nomads_gain(ctx, event):
    ctx.add_coins(2)
    ctx.log(f"{ctx.player_name} gets +$2 from Nomads.")


def _nomads_trash(ctx):
    ctx.add_coins(2)
    ctx.log(f"{ctx.player_name} gets +$2 from trashing Nomads.")


_SPICE_OPTIONS = ("+2 Cards and +1 Action", "+1 Buy and +$2")


def _spice_merchant(ctx):
    treasures = tuple(sorted({c for c in ctx.hand if ctx.is_treasure(c)}))
    if not treasures:
        return
    chosen = yield ctx.choose("Spice Merchant: you may trash a Treasure from your hand.", treasures, 0, 1)
    if not chosen:
        return
    ctx.trash(chosen[0])
    (mode,) = yield ctx.choose("Spice Merchant: choose one.", _SPICE_OPTIONS)
    if mode == "+2 Cards and +1 Action":
        ctx.draw(2)
        ctx.add_actions(1)
    else:
        ctx.add_buys(1)
        ctx.add_coins(2)


def _trader(ctx):
    hand = ctx.hand
    if not hand:
        return
    (trashed,) = yield ctx.choose("Trader: trash a card from your hand.", hand)
    ctx.trash(trashed)
    count = ctx.cost_of(trashed)
    for _ in range(count):
        if not ctx.gain("Silver"):
            break


def _trail(ctx):
    ctx.draw(1)
    ctx.add_actions(1)


def _trail_gain(ctx, event):
    if event.zone is None or not ctx.gained_card_present(event):
        return
    chosen = yield ctx.choose("Trail: you gained Trail. You may play it.", ("Trail",), 0, 1)
    if chosen and ctx.gained_card_present(event):
        zone = event.zone
        event.zone = None
        yield from ctx.play_from_zone("Trail", zone)


def _trail_discard(ctx):
    if "Trail" not in ctx.discard_pile:
        return
    chosen = yield ctx.choose("Trail: you discarded Trail. You may play it.", ("Trail",), 0, 1)
    if chosen and "Trail" in ctx.discard_pile:
        yield from ctx.play_from_zone("Trail", "discard")


def _weaver(ctx):
    options = ctx.gainable(4)
    modes = []
    if ctx.supply_count("Silver") > 0 and not ctx.is_pile_walled("Silver"):
        modes.append("Gain two Silvers")
    if options:
        modes.append("Gain a card costing up to $4")
    if not modes:
        return
    mode = modes[0]
    if len(modes) > 1:
        (mode,) = yield ctx.choose("Weaver: choose one.", tuple(modes))
    if mode == "Gain two Silvers":
        ctx.gain("Silver")
        ctx.gain("Silver")
    else:
        card = options[0]
        if len(options) > 1:
            (card,) = yield ctx.choose("Weaver: gain a card costing up to $4.", options)
        ctx.gain(card)


def _weaver_discard(ctx):
    if "Weaver" not in ctx.discard_pile:
        return
    chosen = yield ctx.choose("Weaver: you discarded Weaver. You may play it.", ("Weaver",), 0, 1)
    if chosen and "Weaver" in ctx.discard_pile:
        yield from ctx.play_from_zone("Weaver", "discard")


# ----------------------------------------------------------------- $5
def _berserker(ctx):
    cost = ctx.cost_of("Berserker")
    if cost > 0:
        options = ctx.gainable(cost - 1)
        if options:
            card = options[0]
            if len(options) > 1:
                (card,) = yield ctx.choose(f"Berserker: gain a card costing up to ${cost - 1}.", options)
            ctx.gain(card)
    targets = yield from ctx.attack()
    for p in targets:
        hand = ctx.hand_of(p)
        excess = len(hand) - 3
        if excess <= 0:
            continue
        chosen = yield ctx.choose(
            f"{ctx.player_name}'s Berserker: discard {excess} card(s) to get down to 3.",
            hand, excess, excess, player=p,
        )
        for card in chosen:
            ctx.discard(card, player=p)


def _berserker_gain(ctx, event):
    if event.zone is None or not ctx.gained_card_present(event):
        return
    if any(ctx.is_action(c) for c in ctx.in_play):
        zone = event.zone
        event.zone = None
        yield from ctx.play_from_zone("Berserker", zone)


def _cartographer(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    looked = ctx.take_to_set_aside(4)
    if not looked:
        return
    to_discard = yield ctx.choose(
        "Cartographer: discard any number of these cards.",
        tuple(looked), 0, len(looked),
    )
    for card in to_discard:
        looked.remove(card)
        ctx.discard_set_aside(card)
    yield from _put_back_in_any_order(ctx, looked)


def _cauldron(ctx):
    ctx.add_buys(1)


def _cauldron_gain(ctx, event):
    if ctx.is_action(event.card) and event.action_gain_number == 3:
        targets = yield from ctx.attack()
        for p in targets:
            ctx.gain("Curse", player=p)


def _haggler(ctx):
    ctx.add_coins(2)


def _haggler_gain(ctx, event):
    if not event.bought:
        return
    max_cost = ctx.cost_of(event.card) - 1
    if max_cost < 0 and ctx.potion_cost_of(event.card) == 0:
        return
    options = tuple(
        c for c in ctx.gainable(max(0, max_cost))
        if not ctx.is_victory(c)
    ) if max_cost >= 0 else ()
    if not options:
        return
    card = options[0]
    if len(options) > 1:
        (card,) = yield ctx.choose(
            f"Haggler: gain a non-Victory card costing less than {event.card} (up to ${max_cost}).",
            options,
        )
    ctx.gain(card)


def _highway(ctx):
    ctx.draw(1)
    ctx.add_actions(1)


def _inn(ctx):
    ctx.draw(2)
    ctx.add_actions(2)
    hand = ctx.hand
    n = min(2, len(hand))
    if n == 0:
        return
    if n == len(hand):
        for card in hand:
            ctx.discard(card)
        return
    chosen = yield ctx.choose(f"Inn: discard {n} card(s).", hand, n, n)
    for card in chosen:
        ctx.discard(card)


def _inn_gain(ctx, event):
    actions_in_discard = tuple(c for c in ctx.discard_pile if ctx.is_action(c))
    if not actions_in_discard:
        return
    chosen = yield ctx.choose(
        "Inn: choose any number of Action cards from your discard pile to shuffle into your deck.",
        actions_in_discard, 0, len(actions_in_discard),
    )
    if chosen:
        ctx.shuffle_from_discard_to_deck(chosen)


def _margrave(ctx):
    ctx.draw(3)
    ctx.add_buys(1)
    targets = yield from ctx.attack()
    for p in targets:
        ctx.draw(1, player=p)
        hand = ctx.hand_of(p)
        excess = len(hand) - 3
        if excess > 0:
            chosen = yield ctx.choose(
                f"{ctx.player_name}'s Margrave: discard {excess} card(s) to get down to 3.",
                hand, excess, excess, player=p,
            )
            for card in chosen:
                ctx.discard(card, player=p)


def _souk(ctx):
    ctx.add_buys(1)
    ctx.add_coins(7)
    loss = ctx.hand_size
    if loss > 0:
        ctx.lose_coins(loss)


def _souk_gain(ctx, event):
    hand = ctx.hand
    if not hand:
        return
    chosen = yield ctx.choose(
        "Souk: you may trash up to 2 cards from your hand.",
        hand, 0, min(2, len(hand)),
    )
    for card in chosen:
        ctx.trash(card)


def _stables(ctx):
    treasures = tuple(sorted({c for c in ctx.hand if ctx.is_treasure(c)}))
    if not treasures:
        return
    chosen = yield ctx.choose(
        "Stables: you may discard a Treasure for +3 Cards and +1 Action.",
        treasures, 0, 1,
    )
    if chosen:
        ctx.discard(chosen[0])
        ctx.draw(3)
        ctx.add_actions(1)


def _wheelwright(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    hand = ctx.hand
    if not hand:
        return
    chosen = yield ctx.choose(
        "Wheelwright: you may discard a card to gain an Action card costing as much as it or less.",
        hand, 0, 1,
    )
    if not chosen:
        return
    discarded = chosen[0]
    ctx.discard(discarded)
    limit = ctx.cost_of(discarded)
    options = ctx.gainable(limit, CardType.ACTION)
    if options:
        card = options[0]
        if len(options) > 1:
            (card,) = yield ctx.choose(
                f"Wheelwright: gain an Action card costing up to ${limit}.",
                options,
            )
        ctx.gain(card)


def _witchs_hut(ctx):
    ctx.draw(4)
    hand = ctx.hand
    n = min(2, len(hand))
    discarded = []
    if n == len(hand) and n > 0:
        discarded = list(hand)
        for card in discarded:
            ctx.discard(card)
    elif n > 0:
        chosen = yield ctx.choose(f"Witch's Hut: discard {n} card(s) (both revealed).", hand, n, n)
        discarded = list(chosen)
        for card in discarded:
            ctx.discard(card)
    if discarded:
        ctx.log(f"{ctx.player_name} reveals the discarded card(s): {', '.join(discarded)}.", "reveal")
    if len(discarded) == 2 and all(ctx.is_action(c) for c in discarded):
        targets = yield from ctx.attack()
        for p in targets:
            ctx.gain("Curse", player=p)


# ----------------------------------------------------------------- $6
def _border_village(ctx):
    ctx.draw(1)
    ctx.add_actions(2)


def _border_village_gain(ctx, event):
    limit = ctx.cost_of("Border Village") - 1
    if limit < 0:
        return
    options = ctx.gainable(limit)
    if not options:
        return
    card = options[0]
    if len(options) > 1:
        (card,) = yield ctx.choose(f"Border Village: gain a card costing up to ${limit}.", options)
    ctx.gain(card)


def _farmland_gain(ctx, event):
    if not event.bought:
        return
    hand = ctx.hand
    if not hand:
        return
    (trashed,) = yield ctx.choose("Farmland: trash a card from your hand.", hand)
    ctx.trash(trashed)
    if ctx.potion_cost_of(trashed) > 0:
        return
    target = ctx.cost_of(trashed) + 2
    options = ctx.gainable(target, exact=True)
    if options:
        card = options[0]
        if len(options) > 1:
            (card,) = yield ctx.choose(f"Farmland: gain a card costing exactly ${target}.", options)
        ctx.gain(card)


# ------------------------------------------------------------ registration
def _reg(name, cost, fn, text, **kw):
    register(action(name, cost, fn, text, expansion=SET, **kw))


# $2
_reg("Crossroads", 2, _crossroads,
     "Reveal your hand. +1 Card per Victory card revealed. If this is the first time you played a Crossroads this turn, +3 Actions.")
register(treasure(
    "Fool's Gold", 2, 1,
    text="Worth $1 if it's the first time you played a Fool's Gold this turn, otherwise worth $4. Reaction: When another player gains a Province, you may trash this from your hand. If you do, gain a Gold onto your deck.",
    coins_fn=_fools_gold_coins, on_play=_fools_gold_play, kingdom=True, expansion=SET,
    extra_types=_REACTION, on_other_gain_reaction=_fools_gold_reaction,
))

# $3
_reg("Develop", 3, _develop,
     "Trash a card from your hand. Gain two cards onto your deck, with one costing exactly $1 more than it, and one costing exactly $1 less than it, in either order.")
_reg("Guard Dog", 3, _guard_dog,
     "+2 Cards. If you have 5 or fewer cards in hand, +2 Actions. Reaction: When another player gains a card costing $5 or more, you may play this from your hand.",
     extra_types=_REACTION, on_other_gain_reaction=_guard_dog_reaction)
_reg("Oasis", 3, _oasis, "+1 Card, +1 Action, +$1. Discard a card.")
_reg("Scheme", 3, _scheme,
     "+1 Card, +1 Action. This turn, you may put one of your Action cards onto your deck when you discard it from play.")
register(victory_reaction(
    "Tunnel", 3, vp=2,
    text="2 VP. Reaction: When you discard this other than during Clean-up, you may reveal it to gain a Gold.",
    kingdom=True, expansion=SET, on_discard=_tunnel_discard,
))

# $4
_reg("Jack of All Trades", 4, _jack_of_all_trades,
     "Gain a Silver. Look at the top card of your deck; you may discard it or put it back. Draw until you have 5 cards in hand. You may trash a non-Treasure card from your hand.")
_reg("Nomads", 4, _nomads,
     "+1 Buy, +$2. When you gain or trash this, +$2.",
     on_gain=_nomads_gain, on_trash=_nomads_trash)
_reg("Spice Merchant", 4, _spice_merchant,
     "You may trash a Treasure from your hand to choose one: +2 Cards and +1 Action; or +1 Buy and +$2.")
_reg("Trader", 4, _trader,
     "Trash a card from your hand. Gain a Silver per $1 it costs. Reaction: When you would gain a card, you may reveal this from your hand, to instead gain a Silver.",
     extra_types=_REACTION)
_reg("Trail", 4, _trail,
     "+1 Card, +1 Action. Reaction: When you gain this or discard this other than during Clean-up, you may play it.",
     extra_types=_REACTION, on_gain=_trail_gain, on_discard=_trail_discard)
_reg("Weaver", 4, _weaver,
     "Gain two Silvers or a card costing up to $4. Reaction: When you discard this other than during Clean-up, you may play it.",
     extra_types=_REACTION, on_discard=_weaver_discard)

# $5
_reg("Berserker", 5, _berserker,
     "Gain a card costing less than this. Each other player discards down to 3 cards in hand. When you gain this, if you have an Action card in play, play this.",
     extra_types=_ATTACK, on_gain=_berserker_gain)
_reg("Cartographer", 5, _cartographer,
     "+1 Card, +1 Action. Look at the top 4 cards of your deck. Discard any number of them, then put the rest back on top in any order.")
register(treasure(
    "Cauldron", 5, 2,
    text="$2, +1 Buy. The third time you gain an Action card in a turn, each other player gains a Curse.",
    on_play=_cauldron, on_gain_in_play=_cauldron_gain, kingdom=True, expansion=SET,
    extra_types=_ATTACK,
))
_reg("Haggler", 5, _haggler,
     "+$2. While this is in play, when you buy a card, gain a non-Victory card costing less than it.",
     on_gain_in_play=_haggler_gain)
_reg("Highway", 5, _highway,
     "+1 Card, +1 Action. While this is in play, cards cost $1 less, but not less than $0.")
_reg("Inn", 5, _inn,
     "+2 Cards, +2 Actions. Discard 2 cards. When you gain this, look through your discard pile, reveal any number of Action cards from it (which can include this), and shuffle them into your deck.",
     on_gain=_inn_gain)
_reg("Margrave", 5, _margrave,
     "+3 Cards, +1 Buy. Each other player draws a card, then discards down to 3 cards in hand.",
     extra_types=_ATTACK)
_reg("Souk", 5, _souk,
     "+1 Buy, +$7. Lose $1 per card in your hand (coins can't go below $0). When you gain this, you may trash up to 2 cards from your hand.",
     on_gain=_souk_gain)
_reg("Stables", 5, _stables,
     "You may discard a Treasure, for +3 Cards and +1 Action.")
_reg("Wheelwright", 5, _wheelwright,
     "+1 Card, +1 Action. You may discard a card to gain an Action card costing as much as it or less.")
_reg("Witch's Hut", 5, _witchs_hut,
     "+4 Cards. Discard 2 cards, both revealed. If they were both Action cards, each other player gains a Curse.",
     extra_types=_ATTACK)

# $6
_reg("Border Village", 6, _border_village,
     "+1 Card, +2 Actions. When you gain this, gain a card costing less than this.",
     on_gain=_border_village_gain)
register(victory(
    "Farmland", 6, vp=2,
    text="2 VP. When you buy this, trash a card from your hand and gain a card costing exactly $2 more than it.",
    kingdom=True, expansion=SET, on_gain=_farmland_gain,
))
