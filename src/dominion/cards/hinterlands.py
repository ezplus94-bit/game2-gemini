"""The Hinterlands expansion (2011, first edition): 26 Kingdom cards.

What is new compared with the earlier card sets, and where the engine supports it:

  * "When you gain this" effects on cards that were never bought (Border Village, Cache, Embassy, Ill-Gotten Gains,
    Inn, Mandarin, Nomad Camp) use ``CardDef.on_gain``; Noble Brigand and Farmland only act when *bought*
    (``event.bought``); Haggler is an ``on_gain_in_play`` hook.
  * Trader: ``CardDef.gain_replacement``. A Reaction in hand lets its owner gain a Silver *instead of* any card they would
    gain (``Game._gain_replacement``). The card is put back where it came from, so nothing that happens "when you gain"
    it happens.
  * Fool's Gold: ``CardDef.on_other_gain``, a Reaction to ANOTHER player's gain (a Province); it is also a Treasure whose
    value depends on how often it was played this turn (``GameState.turn_counts``).
  * Tunnel: discarding it other than in Clean-up gains a Gold (``zones.tunnel_discarded``; the reveal is automatic).
  * Scheme: at the start of Clean-up its owner may pick an Action card in play that goes onto the deck when discarded.
  * Duchess: when it is in the game, gaining a Duchy offers a Duchess (``GameState.duchess``).
  * Highway: ``CardDef.cost_aura`` (like Princess). Crossroads: ``ctx.bump_count`` (first play each turn).
  * New Attacks: Oracle, Noble Brigand, Margrave.
"""

from __future__ import annotations

from dataclasses import replace

from .alchemy import _put_back_in_any_order
from .base import CardDef, CardType, action, treasure, victory
from .registry import get_card, register

SET = "Hinterlands"
_ATTACK = (CardType.ATTACK,)


def _pick_discards(ctx, prompt: str, count: int):
    """Generator: the player discards exactly ``count`` cards (or their whole hand if smaller)."""
    hand = ctx.hand
    n = min(count, len(hand))
    if n:
        chosen = yield ctx.choose(prompt, hand, n, n)
        for card in chosen:
            ctx.discard(card)


def _draw_up_to(ctx, size: int) -> None:
    drawn = 0
    while ctx.hand_size < size:
        if not ctx.draw(1, quiet=True):
            break
        drawn += 1
    ctx.log(f"{ctx.player_name} draws {drawn} card(s).")


# ----------------------------------------------------------------- $2
def _crossroads(ctx):
    hand = ctx.hand
    ctx.log(f"{ctx.player_name} reveals their hand: {', '.join(sorted(hand)) or 'nothing'}.", "reveal")
    victories = sum(1 for c in hand if ctx.is_victory(c))
    if victories:
        ctx.draw(victories)
    if ctx.bump_count("Crossroads") == 0:
        ctx.add_actions(3)
        ctx.log(f"{ctx.player_name} gets +3 Actions (first Crossroads this turn).")


def _duchess(ctx):
    ctx.add_coins(2)
    for p in [ctx.player, *[o for o in ctx.other_players() if not ctx.is_invisible(o)]]:
        cards = ctx.take_to_set_aside(1, player=p)
        if not cards:
            continue
        card = cards[0]
        (mode,) = yield ctx.choose(f"Duchess: the top card of your deck is {card}. Discard it, or put it back?",
                                   ("Discard it", "Put it back"), player=p)
        if mode == "Discard it":
            ctx.discard_set_aside(card, player=p)
        else:
            ctx.put_set_aside_on_deck(card, player=p)


def _fools_gold_coins(state, player: int) -> int:
    return 4 if state.turn_counts.get("Fool's Gold", 0) else 1


def _fools_gold_react(ctx, event):
    if event.card != "Province":
        return
    chosen = yield ctx.choose(
        f"{ctx.name_of(event.player)} gained a Province. You may trash Fool's Gold from your hand to gain a Gold onto your deck.",
        ("Trash Fool's Gold",), 0, 1)
    if chosen:
        ctx.log(f"{ctx.player_name} reveals Fool's Gold.", "reveal")
        ctx.trash("Fool's Gold")
        ctx.gain("Gold", destination="deck")


# ----------------------------------------------------------------- $3
def _develop(ctx):
    hand = ctx.hand
    if not hand:
        return
    (card,) = yield ctx.choose("Develop: trash a card from your hand.", hand)
    cost = ctx.cost_of(card)
    ctx.trash(card)
    gains = []
    up = ctx.gainable(cost + 1, exact=True)
    if up:
        (c,) = yield ctx.choose(f"Develop: gain a card costing exactly ${cost + 1}.", up)
        gains.append(c)
    down = ctx.gainable(cost - 1, exact=True) if cost >= 1 else ()
    if down:
        (c,) = yield ctx.choose(f"Develop: gain a card costing exactly ${cost - 1}.", down)
        gains.append(c)
    if len(gains) == 2:
        (top,) = yield ctx.choose("Develop: which card goes on top of your deck?", tuple(gains))
        gains.remove(top)
        gains.append(top)                                   # gained last = on top
    for c in gains:
        ctx.gain(c, destination="deck")


def _oasis(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.add_coins(1)
    yield from _pick_discards(ctx, "Oasis: discard a card.", 1)


def _oracle(ctx):
    targets = yield from ctx.attack()
    for p in [ctx.player, *targets]:
        cards = ctx.take_to_set_aside(2, player=p, reveal=True)
        if not cards:
            continue
        whose = "your" if p == ctx.player else f"{ctx.name_of(p)}'s"
        (mode,) = yield ctx.choose(f"Oracle: {whose} top cards are {' and '.join(cards)}. Discard them, or put them back?",
                                   ("Discard them", "Put them back"))
        if mode == "Discard them":
            for card in cards:
                ctx.discard_set_aside(card, player=p)
        else:
            yield from _put_back_in_any_order(ctx, cards, player=p)
    ctx.draw(2)


def _scheme(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.bump_count("Scheme")            # Game._cleanup_steps asks once per Scheme played this turn


# ----------------------------------------------------------------- $4
def _jack_of_all_trades(ctx):
    ctx.gain("Silver")
    cards = ctx.take_to_set_aside(1)
    if cards:
        (mode,) = yield ctx.choose(f"Jack of All Trades: the top card of your deck is {cards[0]}. Discard it, or put it back?",
                                   ("Discard it", "Put it back"))
        if mode == "Discard it":
            ctx.discard_set_aside(cards[0])
        else:
            ctx.put_set_aside_on_deck(cards[0])
    _draw_up_to(ctx, 5)
    options = tuple(sorted({c for c in ctx.hand if not ctx.is_treasure(c)}))
    if options:
        chosen = yield ctx.choose("Jack of All Trades: you may trash a card from your hand that is not a Treasure.", options, 0, 1)
        if chosen:
            ctx.trash(chosen[0])


def _brigand_attack(ctx):
    targets = yield from ctx.attack()
    for p in targets:
        revealed = ctx.take_to_set_aside(2, player=p, reveal=True)
        had_treasure = any(ctx.is_treasure(c) for c in revealed)
        stealable = sorted({c for c in revealed if c in ("Silver", "Gold")})
        victim = None
        if len(stealable) == 1:
            victim = stealable[0]
        elif stealable:
            (victim,) = yield ctx.choose(f"Noble Brigand: trash one of {ctx.name_of(p)}'s revealed Treasures.", tuple(stealable))
        if victim is not None:
            revealed.remove(victim)
            ctx.trash_set_aside(victim, player=p)
            ctx.gain_from_trash(victim)
        for card in revealed:
            ctx.discard_set_aside(card, player=p)
        if not had_treasure:
            ctx.gain("Copper", player=p)


def _noble_brigand(ctx):
    ctx.add_coins(1)
    yield from _brigand_attack(ctx)


def _noble_brigand_gain(ctx, event):
    if event.bought:
        yield from _brigand_attack(ctx)


def _nomad_camp(ctx):
    ctx.add_buys(1)
    ctx.add_coins(2)


def _nomad_camp_gain(ctx, event):
    if event.zone is not None and event.zone != "deck" and ctx.gained_card_present(event):
        ctx.put_gained_on_deck(event)


def _spice_merchant(ctx):
    treasures = tuple(sorted({c for c in ctx.hand if ctx.is_treasure(c)}))
    if not treasures:
        return
    chosen = yield ctx.choose("Spice Merchant: you may trash a Treasure from your hand.", treasures, 0, 1)
    if not chosen:
        return
    ctx.trash(chosen[0])
    (mode,) = yield ctx.choose("Spice Merchant: choose one.", ("+2 Cards and +1 Action", "+$2 and +1 Buy"))
    if mode.startswith("+2 Cards"):
        ctx.draw(2)
        ctx.add_actions(1)
    else:
        ctx.add_coins(2)
        ctx.add_buys(1)


def _trader(ctx):
    hand = ctx.hand
    if not hand:
        return
    (card,) = yield ctx.choose("Trader: trash a card from your hand. You gain a Silver per $1 it costs.", hand)
    cost = ctx.cost_of(card)
    ctx.trash(card)
    for _ in range(cost):
        ctx.gain("Silver")


# ----------------------------------------------------------------- $5
def _cache_gain(ctx, event):
    ctx.gain("Copper")
    ctx.gain("Copper")


def _cartographer(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    cards = ctx.take_to_set_aside(4)
    if not cards:
        return
    chosen = yield ctx.choose("Cartographer: discard any number of these cards. The rest go back on your deck.",
                              tuple(cards), 0, len(cards))
    for card in chosen:
        cards.remove(card)
        ctx.discard_set_aside(card)
    yield from _put_back_in_any_order(ctx, cards)


def _embassy(ctx):
    ctx.draw(5)
    yield from _pick_discards(ctx, "Embassy: discard 3 cards.", 3)


def _embassy_gain(ctx, event):
    for p in ctx.other_players():
        if not ctx.is_invisible(p):
            ctx.gain("Silver", player=p)


def _haggler(ctx):
    ctx.add_coins(2)


def _haggler_gain(ctx, event):
    if not event.bought:
        return
    options = tuple(c for c in ctx.gainable(ctx.cost_of(event.card) - 1) if not ctx.is_victory(c))
    if options:
        (card,) = yield ctx.choose(f"Haggler: gain a card costing less than the {event.card} you bought that is not a Victory card.", options)
        ctx.gain(card)


def _highway(ctx):
    ctx.draw(1)
    ctx.add_actions(1)


def _ill_gotten_gains_play(ctx):
    if ctx.supply_count("Copper") > 0:
        chosen = yield ctx.choose("Ill-Gotten Gains: you may gain a Copper, putting it into your hand.", ("Gain a Copper",), 0, 1)
        if chosen:
            ctx.gain("Copper", destination="hand")


def _ill_gotten_gains_gain(ctx, event):
    for p in ctx.other_players():
        if not ctx.is_invisible(p):
            ctx.gain("Curse", player=p)


def _inn(ctx):
    ctx.draw(2)
    ctx.add_actions(2)
    yield from _pick_discards(ctx, "Inn: discard 2 cards.", 2)


def _inn_gain(ctx, event):
    actions = tuple(c for c in ctx.discard_pile if ctx.is_action(c))
    if not actions:
        return
    chosen = yield ctx.choose("Inn: reveal any number of Action cards from your discard pile (this Inn included) to shuffle into your deck.",
                              actions, 0, len(actions))
    if chosen:
        ctx.shuffle_into_deck(chosen)


def _mandarin(ctx):
    ctx.add_coins(3)
    hand = ctx.hand
    if hand:
        (card,) = yield ctx.choose("Mandarin: put a card from your hand onto your deck.", hand)
        ctx.put_hand_on_deck(card)


def _mandarin_gain(ctx, event):
    left = [c for c in ctx.in_play if ctx.is_treasure(c)]
    while left:
        if len(set(left)) == 1:
            pick = left[0]
        else:
            (pick,) = yield ctx.choose("Mandarin: put a Treasure you have in play onto your deck (the last one you choose ends up on top).",
                                       tuple(sorted(set(left))))
        left.remove(pick)
        ctx.put_in_play_on_deck(pick)


def _margrave(ctx):
    ctx.draw(3)
    ctx.add_buys(1)
    targets = yield from ctx.attack()
    for p in targets:
        ctx.draw(1, player=p)
        hand = ctx.hand_of(p)
        n = len(hand) - 3
        if n > 0:
            chosen = yield ctx.choose("Margrave: discard down to 3 cards in hand.", hand, n, n, player=p)
            for card in chosen:
                ctx.discard(card, player=p)


def _stables(ctx):
    treasures = tuple(sorted({c for c in ctx.hand if ctx.is_treasure(c)}))
    if not treasures:
        return
    chosen = yield ctx.choose("Stables: you may discard a Treasure for +3 Cards and +1 Action.", treasures, 0, 1)
    if chosen:
        ctx.discard(chosen[0])
        ctx.draw(3)
        ctx.add_actions(1)


# ----------------------------------------------------------------- $6
def _border_village(ctx):
    ctx.draw(1)
    ctx.add_actions(2)


def _border_village_gain(ctx, event):
    options = ctx.gainable(ctx.cost_of(event.card) - 1)
    if options:
        (card,) = yield ctx.choose("Border Village: gain a card costing less than it.", options)
        ctx.gain(card)


def _farmland_gain(ctx, event):
    if not event.bought:
        return
    hand = ctx.hand
    if not hand:
        return
    (card,) = yield ctx.choose("Farmland: trash a card from your hand. Then gain a card costing exactly $2 more.", hand)
    cost = ctx.cost_of(card)
    ctx.trash(card)
    options = ctx.gainable(cost + 2, exact=True)
    if options:
        (gained,) = yield ctx.choose(f"Farmland: gain a card costing exactly ${cost + 2}.", options)
        ctx.gain(gained)


def _silk_road_vp(cards) -> int:
    return sum(1 for c in cards if get_card(c).is_type(CardType.VICTORY)) // 4


# ------------------------------------------------------------ registration
def _reg(name, cost, fn, text, **kw):
    register(action(name, cost, fn, text, expansion=SET, **kw))


# $2
_reg("Crossroads", 2, _crossroads, "Reveal your hand. +1 Card per Victory card revealed. If this is the first time you played a Crossroads this turn, +3 Actions.")
_reg("Duchess", 2, _duchess, "+$2. Each player (including you) looks at the top card of their deck and may discard it or put it back. In games using this, when you gain a Duchy, you may gain a Duchess.")
register(CardDef("Fool's Gold", 2, frozenset({CardType.TREASURE, CardType.REACTION}), coins=1, coins_fn=_fools_gold_coins,
                 text="Worth $1 if it's the first time you played Fool's Gold this turn, otherwise worth $4. When another player gains a Province, you may trash this from your hand. If you do, gain a Gold, putting it onto your deck.",
                 kingdom=True, expansion=SET, on_other_gain=_fools_gold_react))
# $3
_reg("Develop", 3, _develop, "Trash a card from your hand. Gain a card costing exactly $1 more than it and a card costing exactly $1 less than it, in either order, putting them on top of your deck.")
_reg("Oasis", 3, _oasis, "+1 Card, +1 Action, +$1. Discard a card.")
_reg("Oracle", 3, _oracle, "Each player (including you) reveals the top 2 cards of their deck, and you choose one: either they discard them, or they put them back on top in an order they choose. +2 Cards.", extra_types=_ATTACK)
_reg("Scheme", 3, _scheme, "+1 Card, +1 Action. At the start of Clean-up this turn, you may choose an Action card you have in play. If you discard it from play this turn, put it onto your deck.")
register(CardDef("Tunnel", 3, frozenset({CardType.VICTORY, CardType.REACTION}), vp=2,
                 text="2 VP. When you discard this other than during Clean-up, you may reveal it. If you do, gain a Gold.",
                 kingdom=True, expansion=SET))
# $4
_reg("Jack of All Trades", 4, _jack_of_all_trades, "Gain a Silver. Look at the top card of your deck; discard it or put it back. Draw until you have 5 cards in hand. You may trash a card from your hand that is not a Treasure.")
_reg("Noble Brigand", 4, _noble_brigand, "+$1. When you buy this or play it, each other player reveals the top 2 cards of their deck, trashes a revealed Silver or Gold you choose, and discards the rest. If they didn't reveal a Treasure, they gain a Copper. You gain the trashed cards.",
     extra_types=_ATTACK, on_gain=_noble_brigand_gain)
_reg("Nomad Camp", 4, _nomad_camp, "+1 Buy, +$2. When you gain this, put it onto your deck.", on_gain=_nomad_camp_gain)
register(victory("Silk Road", 4, score_fn=_silk_road_vp, text="Worth 1 VP for every 4 Victory cards in your deck (round down).", kingdom=True, expansion=SET))
_reg("Spice Merchant", 4, _spice_merchant, "You may trash a Treasure from your hand. If you do, choose one: +2 Cards and +1 Action; or +$2 and +1 Buy.")
register(replace(action("Trader", 4, _trader, "Trash a card from your hand. Gain a number of Silvers equal to its cost in coins. When you would gain a card, you may reveal this from your hand. If you do, instead, gain a Silver.",
                        expansion=SET, extra_types=(CardType.REACTION,)), gain_replacement="Silver"))
# $5
register(treasure("Cache", 5, 3, text="$3. When you gain this, gain two Coppers.", kingdom=True, expansion=SET, on_gain=_cache_gain))
_reg("Cartographer", 5, _cartographer, "+1 Card, +1 Action. Look at the top 4 cards of your deck. Discard any number of them. Put the rest back on top in any order.")
_reg("Embassy", 5, _embassy, "+5 Cards, then discard 3 cards. When you gain this, each other player gains a Silver.", on_gain=_embassy_gain)
_reg("Haggler", 5, _haggler, "+$2. While this is in play, when you buy a card, gain a card costing less than it that is not a Victory card.", on_gain_in_play=_haggler_gain)
register(replace(action("Highway", 5, _highway, "+1 Card, +1 Action. While this is in play, cards cost $1 less, but not less than $0.", expansion=SET), cost_aura=1))
register(treasure("Ill-Gotten Gains", 5, 1, text="$1. When you play this, you may gain a Copper, putting it into your hand. When you gain this, each other player gains a Curse.",
                  kingdom=True, expansion=SET, on_play=_ill_gotten_gains_play, on_gain=_ill_gotten_gains_gain))
_reg("Inn", 5, _inn, "+2 Cards, +2 Actions. Discard 2 cards. When you gain this, look through your discard pile (including this), reveal any number of Action cards from it, and shuffle them into your deck.", on_gain=_inn_gain)
_reg("Mandarin", 5, _mandarin, "+$3. Put a card from your hand onto your deck. When you gain this, put all Treasures you have in play onto your deck in any order.", on_gain=_mandarin_gain)
_reg("Margrave", 5, _margrave, "+3 Cards, +1 Buy. Each other player draws a card, then discards down to 3 cards in hand.", extra_types=_ATTACK)
_reg("Stables", 5, _stables, "You may discard a Treasure. If you do, +3 Cards and +1 Action.")
# $6
_reg("Border Village", 6, _border_village, "+1 Card, +2 Actions. When you gain this, gain a card costing less than it.", on_gain=_border_village_gain)
register(replace(victory("Farmland", 6, vp=2, text="2 VP. When you buy this, trash a card from your hand. Gain a card costing exactly $2 more than the trashed card.",
                         kingdom=True, expansion=SET), on_gain=_farmland_gain))
