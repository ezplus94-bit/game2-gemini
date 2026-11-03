"""The Adventures expansion (2015): 27 Kingdom piles, the two Traveller lines (10 cards) and 20 Events.

What is new compared with the earlier card sets, and where the engine supports it:

  * Reserve cards (``CardType.RESERVE``): when played they go to the Tavern mat (``PlayerState.tavern``, face up). Later
    the owner may *call* them at the moment printed on the card (``CardDef.call_when``): at the start of the turn
    (Guide, Ratcatcher, Transmogrify, Teacher), after playing an Action (Royal Carriage, Coin of the Realm), when
    gaining a card (Duplicate) or at the end of the Buy phase (Wine Merchant). ``effects.call_steps`` asks the player.
  * Travellers: Page and Peasant start a line of cards. When a Traveller is discarded from play its owner may exchange it
    for the next card of the line (``CardDef.exchange``); the upgrade piles are outside the Supply (5 cards each).
  * Tokens: the Journey token, the -1 Card token (the next draw is one card smaller), the -$1 token (the next $ is one
    smaller) and the pile tokens (+1 Card, +1 Action, +1 Buy, +$1, -$2 Cost, Trashing) that Teacher and the Events move
    onto Action piles (``PlayerState.tokens``).
  * Events (``CardType.EVENT``): bought with a Buy and their cost in $, never gained. At most two are in a game
    (``GameConfig.events``); see ``EVENTS`` below.
  * Duration cards that stay in play forever (Champion, Hireling), Haunted Woods and Swamp Hag (``on_buy_by_other``),
    Caravan Guard (a Duration that is also a Reaction) and Inheritance (Estates become Actions).
"""

from __future__ import annotations

from dataclasses import replace

from .alchemy import _put_back_in_any_order
from .base import CardDef, CardType, action
from .registry import register

SET = "Adventures"
_DURATION = (CardType.DURATION,)
_RESERVE = (CardType.RESERVE,)
_TRAVELLER = (CardType.TRAVELLER,)
_ATTACK = (CardType.ATTACK,)


def _plus_coins(n):
    def start(ctx, entry):
        ctx.add_coins(n)
        ctx.log(f"{entry.source} gives +${n}.")
    start.__name__ = f"_plus_{n}_coins"
    return start


def _cost_between(ctx, card: str, low: int, high: int) -> bool:
    return low <= ctx.cost_of(card) <= high and ctx.potion_cost_of(card) == 0


def _trash_one(ctx, prompt: str, optional: bool = False):
    """Generator: the player trashes a card from their hand. Returns it (or None)."""
    hand = ctx.hand
    if not hand:
        return None
    chosen = yield ctx.choose(prompt, tuple(sorted(set(hand))), 0 if optional else 1, 1)
    if not chosen:
        return None
    ctx.trash(chosen[0])
    return chosen[0]


# ----------------------------------------------------------------- Amulet, Artificer, Bridge Troll, Caravan Guard
def _amulet_mode(ctx):
    modes = ["+$1"]
    if ctx.hand:
        modes.append("Trash a card from your hand")
    modes.append("Gain a Silver")
    (mode,) = yield ctx.choose("Amulet: choose one.", modes)
    if mode == "+$1":
        ctx.add_coins(1)
    elif mode.startswith("Trash"):
        yield from _trash_one(ctx, "Amulet: trash a card from your hand.")
    else:
        ctx.gain("Silver")


def _amulet(ctx):
    yield from _amulet_mode(ctx)
    ctx.add_duration(_amulet_start)


def _amulet_start(ctx, entry):
    yield from _amulet_mode(ctx)


def _artificer(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.add_coins(1)
    hand = ctx.hand
    if not hand:
        return
    chosen = yield ctx.choose("Artificer: discard any number of cards. You may then gain a card costing exactly $1 per card discarded, onto your deck.",
                              hand, 0, len(hand))
    for card in chosen:
        ctx.discard(card)
    options = ctx.gainable(len(chosen), exact=True)
    if not options:
        return
    pick = yield ctx.choose(f"Artificer: you may gain a card costing exactly ${len(chosen)} onto your deck.", options, 0, 1)
    if pick:
        ctx.gain(pick[0], destination="deck")


def _bridge_troll(ctx):
    targets = yield from ctx.attack()
    for p in targets:
        ctx.give_minus_coin(p)
    ctx.add_buys(1)
    ctx.add_duration(_bridge_troll_start)


def _bridge_troll_start(ctx, entry):
    ctx.add_buys(1)
    ctx.log("Bridge Troll gives +1 Buy.")


def _caravan_guard(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.add_duration(_plus_coins(1))


def _caravan_guard_react(ctx):
    """Another player played an Attack: play this from your hand (its +1 Action is lost, it is not your turn)."""
    ctx.put_in_play("Caravan Guard", "hand")
    ctx.draw(1)
    ctx.add_duration(_plus_coins(1))


def _champion(ctx):
    ctx.add_actions(1)
    ctx.add_duration(_champion_keep)


def _champion_keep(ctx, entry):
    ctx.add_duration(_champion_keep)                     # stays in play for the rest of the game


# ----------------------------------------------------------------- Coin of the Realm, Disciple, Distant Lands, Dungeon
def _coin_of_the_realm(ctx):
    ctx.to_tavern()


def _plus_two_actions(ctx, arg):
    ctx.add_actions(2)


def _disciple(ctx):
    options = tuple(sorted({c for c in ctx.hand if ctx.is_action(c)}))
    if not options:
        return
    chosen = yield ctx.choose("Disciple: you may play an Action card from your hand twice. Gain a copy of it.", options, 0, 1)
    if not chosen:
        return
    card = chosen[0]
    ctx.put_in_play(card, "hand")
    yield from ctx.resolve(card)
    yield from ctx.resolve(card)
    ctx.gain(card)


def _to_tavern(ctx):
    ctx.to_tavern()


def _dungeon_effect(ctx):
    ctx.draw(2)
    hand = ctx.hand
    n = min(2, len(hand))
    if n:
        chosen = yield ctx.choose("Dungeon: discard 2 cards.", hand, n, n)
        for card in chosen:
            ctx.discard(card)


def _dungeon(ctx):
    ctx.add_actions(1)
    yield from _dungeon_effect(ctx)
    ctx.add_duration(_dungeon_start)


def _dungeon_start(ctx, entry):
    yield from _dungeon_effect(ctx)


def _duplicate_cond(ctx, event):
    return ctx.supply_count(event.card) > 0 and ctx.cost_of(event.card) <= 6 and ctx.potion_cost_of(event.card) == 0


def _duplicate_call(ctx, event):
    ctx.gain(event.card)


def _fugitive(ctx):
    ctx.draw(2)
    ctx.add_actions(1)
    hand = ctx.hand
    if hand:
        (card,) = yield ctx.choose("Fugitive: discard a card.", tuple(sorted(set(hand))))
        ctx.discard(card)


# ----------------------------------------------------------------- Gear, Giant, Guide, Haunted Woods, Hero, Hireling
def _gear(ctx):
    ctx.draw(2)
    hand = ctx.hand
    if not hand:
        return
    chosen = yield ctx.choose("Gear: set aside up to 2 cards from your hand, face down. They return to your hand next turn.",
                              hand, 0, min(2, len(hand)))
    if not chosen:
        return
    for card in chosen:
        ctx.put_on_mat(card, "haven")
    ctx.log(f"{ctx.player_name} sets {len(chosen)} card(s) aside with Gear.")
    ctx.add_duration(_gear_start, tuple(chosen))


def _gear_start(ctx, entry):
    for card in entry.data:
        if card in ctx.mat_cards("haven"):
            ctx.put_on_mat(card, "hand", source="haven")
    ctx.log(f"{ctx.player_name} takes the cards set aside by Gear into their hand.")


def _giant(ctx):
    if not ctx.flip_journey():                              # it was face up: now face down
        ctx.add_coins(1)
        return
    ctx.add_coins(5)
    targets = yield from ctx.attack()
    for p in targets:
        cards = ctx.take_to_set_aside(1, p, reveal=True)
        if not cards:
            continue
        card = cards[0]
        if _cost_between(ctx, card, 3, 6):
            ctx.trash_set_aside(card, p)
        else:
            ctx.discard_set_aside(card, p)
            ctx.gain("Curse", player=p)


def _guide(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.to_tavern()


def _guide_call(ctx, arg):
    ctx.discard_hand()
    ctx.draw(5)


def _haunted_woods(ctx):
    targets = yield from ctx.attack()
    ctx.add_duration(_plus_cards(3), tuple(targets))


def _plus_cards(n):
    def start(ctx, entry):
        ctx.draw(n)
    start.__name__ = f"_plus_{n}_cards"
    return start


def _haunted_woods_buy(ctx, event):
    for entry in ctx.duration_entries("Haunted Woods"):
        if event.player in (entry.data or ()):
            rest = ctx.hand_to_set_aside(event.player)
            ctx.log(f"Haunted Woods: {ctx.name_of(event.player)} puts their hand onto their deck.")
            yield from _put_back_in_any_order(ctx, rest, player=event.player)


def _hero(ctx):
    ctx.add_coins(2)
    options = ctx.gainable(1000, CardType.TREASURE)
    if options:
        (card,) = yield ctx.choose("Hero: gain a Treasure.", options)
        ctx.gain(card)


def _hireling(ctx):
    ctx.add_duration(_hireling_start)


def _hireling_start(ctx, entry):
    ctx.draw(1)
    ctx.add_duration(_hireling_start)                       # every turn for the rest of the game


# ----------------------------------------------------------------- Lost City, Magpie, Messenger, Miser, Page, Peasant
def _lost_city(ctx):
    ctx.draw(2)
    ctx.add_actions(2)


def _lost_city_gain(ctx, event):
    for p in ctx.other_players():
        ctx.draw(1, player=p)


def _magpie(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    cards = ctx.take_to_set_aside(1, reveal=True)
    if not cards:
        return
    card = cards[0]
    if ctx.is_treasure(card):
        ctx.set_aside_to_hand(card)
        ctx.log(f"{ctx.player_name} puts {card} into their hand.")
    else:
        ctx.put_set_aside_on_deck(card)
    if ctx.is_action(card) or ctx.is_victory(card):
        ctx.gain("Magpie")


def _messenger(ctx):
    ctx.add_buys(1)
    ctx.add_coins(2)
    if ctx.deck_size or ctx.discard_pile:
        (answer,) = yield ctx.choose("Messenger: you may put your deck into your discard pile.",
                                     ("Put my deck into my discard pile", "Keep my deck"))
        if answer.startswith("Put"):
            ctx.put_deck_into_discard()


def _messenger_gain(ctx, event):
    if not event.bought or ctx.bought_this_turn != 1:
        return
    options = ctx.gainable(4)
    if not options:
        return
    (card,) = yield ctx.choose("Messenger (first buy of your turn): gain a card costing up to $4. Each other player gains a copy.", options)
    ctx.gain(card)
    for p in ctx.other_players():
        ctx.gain(card, player=p)


def _miser(ctx):
    copper = ctx.mat_cards("tavern").count("Copper")
    modes = []
    if "Copper" in ctx.hand:
        modes.append("Put a Copper from your hand onto your Tavern mat")
    modes.append(f"+${copper} (one for each Copper on your Tavern mat)")
    (mode,) = yield ctx.choose("Miser: choose one.", modes)
    if mode.startswith("Put"):
        ctx.put_on_mat("Copper", "tavern")
        ctx.log(f"{ctx.player_name} puts a Copper on their Tavern mat.")
    else:
        ctx.add_coins(copper)


def _page(ctx):
    ctx.draw(1)
    ctx.add_actions(1)


def _peasant(ctx):
    ctx.add_buys(1)
    ctx.add_coins(1)


# ----------------------------------------------------------------- Port, Ranger, Ratcatcher, Raze, Relic
def _port(ctx):
    ctx.draw(1)
    ctx.add_actions(2)


def _port_gain(ctx, event):
    if event.bought:
        ctx.gain("Port")


def _ranger(ctx):
    ctx.add_buys(1)
    if ctx.flip_journey():
        ctx.draw(5)


def _ratcatcher(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.to_tavern()


def _ratcatcher_call(ctx, arg):
    yield from _trash_one(ctx, "Ratcatcher: trash a card from your hand.")


def _raze(ctx):
    ctx.add_actions(1)
    options = list(sorted(set(ctx.hand)))
    if ctx.source in ctx.in_play:
        options.append("Trash this Raze")
    if not options:
        return
    (pick,) = yield ctx.choose("Raze: trash this or a card from your hand.", options)
    if pick == "Trash this Raze":
        cost = ctx.cost_of("Raze")
        ctx.trash_self()
    else:
        cost = ctx.cost_of(pick)
        ctx.trash(pick)
    if cost <= 0:
        return
    cards = ctx.take_to_set_aside(cost)
    if not cards:
        return
    (keep,) = yield ctx.choose(f"Raze: put one of the top {len(cards)} card(s) into your hand. The rest are discarded.", tuple(cards))
    ctx.set_aside_to_hand(keep)
    rest = list(cards)
    rest.remove(keep)
    for card in rest:
        ctx.discard_set_aside(card)


def _relic(ctx):
    targets = yield from ctx.attack()
    for p in targets:
        ctx.take_minus_card(p)


# ----------------------------------------------------------------- Royal Carriage, Storyteller, Swamp Hag, Teacher, Transmogrify
def _royal_carriage(ctx):
    ctx.add_actions(1)
    ctx.to_tavern()


def _royal_carriage_cond(ctx, played):
    return played in ctx.in_play and ctx.is_action(played)


def _royal_carriage_call(ctx, played):
    ctx.log(f"{ctx.player_name} replays {played}.")
    yield from ctx.resolve(played)


def _storyteller(ctx):
    ctx.add_actions(1)
    for _ in range(3):
        treasures = tuple(sorted({c for c in ctx.hand if ctx.is_treasure(c)}))
        if not treasures:
            break
        chosen = yield ctx.choose("Storyteller: you may play a Treasure from your hand (up to 3 in all).", treasures, 0, 1)
        if not chosen:
            break
        yield from ctx.play_treasure(chosen[0])
    paid = ctx.coins
    if paid > 0:
        ctx.add_coins(-paid)
        ctx.log(f"{ctx.player_name} pays ${paid} and draws {paid} card(s).")
        ctx.draw(paid)


def _swamp_hag(ctx):
    targets = yield from ctx.attack()
    ctx.add_duration(_swamp_hag_start, tuple(targets))


def _swamp_hag_start(ctx, entry):
    ctx.add_coins(3)
    ctx.log("Swamp Hag gives +$3.")


def _swamp_hag_buy(ctx, event):
    for entry in ctx.duration_entries("Swamp Hag"):
        if event.player in (entry.data or ()):
            ctx.log(f"Swamp Hag curses {ctx.name_of(event.player)}.")
            ctx.gain("Curse", player=event.player)


TOKENS = ("+1 Card", "+1 Action", "+1 Buy", "+$1")


def _move_token_to_pile(ctx, token: str, prompt: str, new_pile_only: bool = False):
    piles = ctx.action_piles("any" if new_pile_only else None)
    if not piles:
        return
    (pile,) = yield ctx.choose(prompt, piles)
    ctx.move_token(token, pile)


def _teacher_cond(ctx, arg):
    return bool(ctx.action_piles("any"))


def _teacher_call(ctx, arg):
    (token,) = yield ctx.choose("Teacher: move your +1 Card, +1 Action, +1 Buy or +$1 token to an Action pile.", TOKENS)
    yield from _move_token_to_pile(ctx, token, f"Teacher: put your {token} token on an Action pile you have no token on.", True)


def _transmogrify(ctx):
    ctx.add_actions(1)
    ctx.to_tavern()


def _transmogrify_cond(ctx, arg):
    return bool(ctx.hand)


def _transmogrify_call(ctx, arg):
    (card,) = yield ctx.choose("Transmogrify: trash a card from your hand.", tuple(sorted(set(ctx.hand))))
    cost = ctx.cost_of(card)
    ctx.trash(card)
    options = ctx.gainable(cost + 1)
    if options:
        (new,) = yield ctx.choose(f"Transmogrify: gain a card costing up to ${cost + 1} into your hand.", options)
        ctx.gain(new, destination="hand")


def _treasure_hunter(ctx):
    ctx.add_actions(1)
    ctx.add_coins(1)
    right = (ctx.player - 1) % len(ctx.all_players())
    for _ in ctx.last_gained_by(right):
        ctx.gain("Silver")


def _warrior(ctx):
    ctx.draw(2)
    travellers = sum(1 for c in ctx.in_play if "traveller" in ctx.card_types(c))
    for _ in range(travellers):
        targets = yield from ctx.attack()
        for p in targets:
            cards = ctx.take_to_set_aside(1, p, reveal=True)
            if not cards:
                continue
            if ctx.cost_of(cards[0]) in (3, 4) and ctx.potion_cost_of(cards[0]) == 0:
                ctx.trash_set_aside(cards[0], p)
            else:
                ctx.discard_set_aside(cards[0], p)


def _soldier(ctx):
    ctx.add_coins(2)
    others = max(0, ctx.attack_cards_in_play_of(ctx.player) - 1)
    if others:
        ctx.add_coins(others)
        ctx.log(f"{ctx.player_name} gets +${others} (other Attacks in play).")
    targets = yield from ctx.attack()
    for p in targets:
        hand = ctx.hand_of(p)
        if len(hand) >= 4:
            (card,) = yield ctx.choose(f"{ctx.player_name} played Soldier. Discard a card.", hand, player=p)
            ctx.discard(card, player=p)


def _wine_merchant(ctx):
    ctx.add_coins(4)
    ctx.add_buys(1)
    ctx.to_tavern()


def _always(ctx, arg):
    return True


def _wine_merchant_cond(ctx, arg):
    return ctx.coins >= 2


def _wine_merchant_call(ctx, arg):
    ctx.log(f"{ctx.player_name} discards Wine Merchant from their Tavern mat.")


# ----------------------------------------------------------------- Traveller exchange (when discarded from play)
def _exchange(name: str, new: str):
    def on_cleanup(ctx):
        if new in ctx.offsupply_names():
            chosen = yield ctx.choose(f"You discard {name} from play. You may exchange it for a {new}.", (f"Exchange for {new}",), 0, 1)
            if chosen:
                ctx.exchange_in_play(name, new)
    on_cleanup.__name__ = f"_exchange_{name.replace(' ', '_')}"
    return on_cleanup


def _card(base: CardDef, **changes) -> CardDef:
    return register(replace(base, expansion=SET, **changes))


def _act(name, cost, fn, text, types=(), kingdom=True, **changes):
    return _card(action(name, cost, fn, text, kingdom=kingdom, extra_types=types), **changes)


# ----------------------------------------------------------------- registration

register(CardDef(
    "Coin of the Realm", 2, frozenset({CardType.TREASURE, CardType.RESERVE}), coins=1, on_play=_coin_of_the_realm,
    text="$1. When you play this, put it on your Tavern mat. Call: when you finish playing an Action card, you may call this for +2 Actions.",
    kingdom=True, expansion=SET, call_when="after_action", call_fn=_plus_two_actions,
    call_prompt="You finished playing an Action. You may call Coin of the Realm for +2 Actions."))

_act("Page", 2, _page, "+1 Card, +1 Action. When you discard this from play, you may exchange it for a Treasure Hunter.", _TRAVELLER,
     on_cleanup=_exchange("Page", "Treasure Hunter"), exchange="Treasure Hunter")
_act("Peasant", 2, _peasant, "+1 Buy, +$1. When you discard this from play, you may exchange it for a Soldier.", _TRAVELLER,
     on_cleanup=_exchange("Peasant", "Soldier"), exchange="Soldier")
_act("Ratcatcher", 2, _ratcatcher, "+1 Card, +1 Action. Put this on your Tavern mat. Call: at the start of your turn, you may call this to trash a card from your hand.",
     _RESERVE, call_when="start", call_cond=lambda ctx, arg: bool(ctx.hand), call_fn=_ratcatcher_call,
     call_prompt="Start of your turn: you may call Ratcatcher to trash a card from your hand.")
_act("Raze", 2, _raze, "+1 Action. Trash this or a card from your hand. Look at the top cards of your deck equal to the cost in $ of the trashed card. Put one into your hand and discard the rest.")

_act("Amulet", 3, _amulet, "Now and at the start of your next turn, choose one: +$1; or trash a card from your hand; or gain a Silver.", _DURATION)
_act("Caravan Guard", 3, _caravan_guard, "+1 Card, +1 Action. At the start of your next turn, +$1. When another player plays an Attack card, you may first play this from your hand.",
     (CardType.DURATION, CardType.REACTION), on_attack=_caravan_guard_react)
_act("Dungeon", 3, _dungeon, "+1 Action. Now and at the start of your next turn: +2 Cards, then discard 2 cards.", _DURATION)
_act("Gear", 3, _gear, "+2 Cards. Set aside up to 2 cards from your hand face down. At the start of your next turn, put them into your hand.", _DURATION)
_act("Guide", 3, _guide, "+1 Card, +1 Action. Put this on your Tavern mat. Call: at the start of your turn, you may call this to discard your hand and draw 5 cards.",
     _RESERVE, call_when="start", call_cond=_always, call_fn=_guide_call,
     call_prompt="Start of your turn: you may call Guide to discard your hand and draw 5 cards.")
_act("Soldier", 3, _soldier, "+$2. +$1 per other Attack you have in play. Each other player with 4 or more cards in hand discards a card. When you discard this from play, you may exchange it for a Fugitive.",
     (CardType.ATTACK, CardType.TRAVELLER), kingdom=False, on_cleanup=_exchange("Soldier", "Fugitive"), exchange="Fugitive")
_act("Treasure Hunter", 3, _treasure_hunter, "+1 Action, +$1. Gain a Silver per card the player to your right gained on their last turn. When you discard this from play, you may exchange it for a Warrior.",
     _TRAVELLER, kingdom=False, on_cleanup=_exchange("Treasure Hunter", "Warrior"), exchange="Warrior")

_act("Distant Lands", 5, _to_tavern, "Put this on your Tavern mat. Worth 4 VP if this is on your Tavern mat at the end of the game (otherwise worth 0 VP).",
     (CardType.RESERVE, CardType.VICTORY))
_act("Fugitive", 4, _fugitive, "+2 Cards, +1 Action. Discard a card. When you discard this from play, you may exchange it for a Disciple.",
     _TRAVELLER, kingdom=False, on_cleanup=_exchange("Fugitive", "Disciple"), exchange="Disciple")
_act("Duplicate", 4, _to_tavern, "Put this on your Tavern mat. Call: when you gain a card costing up to $6, you may call this to gain a copy of that card.",
     _RESERVE, call_when="gain", call_cond=_duplicate_cond, call_fn=_duplicate_call,
     call_prompt="You gained a card. You may call Duplicate to gain a copy of it.")
_act("Magpie", 4, _magpie, "+1 Card, +1 Action. Reveal the top card of your deck. If it is a Treasure, put it into your hand. If it is an Action or Victory card, gain a Magpie.")
_act("Messenger", 4, _messenger, "+1 Buy, +$2. You may put your deck into your discard pile. When this is your first buy of your turn, gain a card costing up to $4, and each other player gains a copy of it.",
     on_gain=_messenger_gain)
_act("Miser", 4, _miser, "Choose one: put a Copper from your hand onto your Tavern mat; or +$1 per Copper on your Tavern mat.")
_act("Port", 4, _port, "+1 Card, +2 Actions. When you buy this, gain another Port.", on_gain=_port_gain)
_act("Ranger", 4, _ranger, "+1 Buy. Turn your Journey token over (it starts face up). If it is face up, +5 Cards.")
_act("Transmogrify", 4, _transmogrify, "+1 Action. Put this on your Tavern mat. Call: at the start of your turn, you may call this to trash a card from your hand and gain a card costing up to $1 more into your hand.",
     _RESERVE, call_when="start", call_cond=_transmogrify_cond, call_fn=_transmogrify_call,
     call_prompt="Start of your turn: you may call Transmogrify.")
_act("Warrior", 4, _warrior, "+2 Cards. For each Traveller you have in play (including this), each other player discards the top card of their deck and trashes it if it costs $3 or $4. When you discard this from play, you may exchange it for a Hero.",
     (CardType.ATTACK, CardType.TRAVELLER), kingdom=False, on_cleanup=_exchange("Warrior", "Hero"), exchange="Hero")

_act("Artificer", 5, _artificer, "+1 Card, +1 Action, +$1. Discard any number of cards. You may gain a card costing exactly $1 per card discarded, putting it onto your deck.")
_act("Bridge Troll", 5, _bridge_troll, "Each other player takes their -$1 token. Now and at the start of your next turn: +1 Buy. While this is in play, cards cost $1 less on your turn.",
     (CardType.DURATION, CardType.ATTACK), cost_aura=1)
_act("Disciple", 5, _disciple, "You may play an Action card from your hand twice. Gain a copy of it. When you discard this from play, you may exchange it for a Teacher.",
     _TRAVELLER, kingdom=False, on_cleanup=_exchange("Disciple", "Teacher"), exchange="Teacher")
_act("Giant", 5, _giant, "Turn your Journey token over (it starts face up). If it is face down, +$1. If it is face up, +$5 and each other player reveals the top card of their deck; if it costs $3 to $6 they trash it, otherwise they discard it and gain a Curse.",
     _ATTACK)
_act("Haunted Woods", 5, _haunted_woods, "At the start of your next turn, +3 Cards. Until then, when any other player buys a card, they put their hand onto their deck in any order.",
     (CardType.DURATION, CardType.ATTACK), on_buy_by_other=_haunted_woods_buy)
_act("Hero", 5, _hero, "+$2. Gain a Treasure. When you discard this from play, you may exchange it for a Champion.",
     _TRAVELLER, kingdom=False, on_cleanup=_exchange("Hero", "Champion"), exchange="Champion")
_act("Lost City", 5, _lost_city, "+2 Cards, +2 Actions. When you gain this, each other player draws a card.", on_gain=_lost_city_gain)
register(CardDef(
    "Relic", 5, frozenset({CardType.TREASURE, CardType.ATTACK}), coins=2, on_play=_relic,
    text="$2. When you play this, each other player puts their -1 Card token on their deck.", kingdom=True, expansion=SET))
_act("Royal Carriage", 5, _royal_carriage, "+1 Action. Put this on your Tavern mat. Call: when you finish playing an Action card, if it is still in play, you may call this to replay that Action.",
     _RESERVE, call_when="after_action", call_cond=_royal_carriage_cond, call_fn=_royal_carriage_call,
     call_prompt="You finished playing an Action. You may call Royal Carriage to replay it.")
_act("Storyteller", 5, _storyteller, "+1 Action. Play up to 3 Treasures from your hand. Pay all of your $ and draw a card per $ you paid.")
_act("Swamp Hag", 5, _swamp_hag, "At the start of your next turn, +$3. Until then, when any other player buys a card, they gain a Curse.",
     (CardType.DURATION, CardType.ATTACK), on_buy_by_other=_swamp_hag_buy)
_act("Wine Merchant", 5, _wine_merchant, "+$4, +1 Buy. Put this on your Tavern mat. Call: at the end of your Buy phase, if you have at least $2 unspent, you may discard this from your Tavern mat.",
     _RESERVE, call_when="buy_end", call_cond=_wine_merchant_cond, call_fn=_wine_merchant_call, call_discards=True,
     call_prompt="End of your Buy phase: you may discard Wine Merchant from your Tavern mat.")

_act("Champion", 6, _champion, "+1 Action. For the rest of the game, when another player plays an Attack card, it does not affect you, and when you play an Action card, +1 Action.",
     (CardType.DURATION, CardType.TRAVELLER), kingdom=False)
_act("Hireling", 6, _hireling, "At the start of each of your turns for the rest of the game: +1 Card. (This stays in play.)", _DURATION)
_act("Teacher", 6, _to_tavern, "Put this on your Tavern mat. Call: at the start of your turn, you may call this to move your +1 Card, +1 Action, +1 Buy or +$1 token to an Action Supply pile you have no tokens on.",
     (CardType.RESERVE, CardType.TRAVELLER), kingdom=False, call_when="start", call_cond=_teacher_cond, call_fn=_teacher_call,
     call_prompt="Start of your turn: you may call Teacher to move a token.")


# ----------------------------------------------------------------- Events
def _event(name: str, cost: int, text: str, fn, once: bool = False) -> CardDef:
    return register(CardDef(name, cost, frozenset({CardType.EVENT}), on_play=fn, text=text, kingdom=False,
                            expansion=SET, once_per_turn=once))


def _gain_up_to(ctx, prompt: str, cost: int, card_type=None, destination: str = "discard"):
    options = ctx.gainable(cost, card_type)
    if not options:
        return None
    (card,) = yield ctx.choose(prompt, options)
    ctx.gain(card, destination=destination)
    return card


def _alms(ctx):
    if any(ctx.is_treasure(c) for c in ctx.in_play):
        ctx.log("Alms has no effect: you have a Treasure in play.")
        return
    yield from _gain_up_to(ctx, "Alms: gain a card costing up to $4.", 4)


def _borrow(ctx):
    ctx.add_buys(1)
    if ctx.take_minus_card(ctx.player):
        ctx.add_coins(1)


def _quest(ctx):
    hand = ctx.hand
    attacks = tuple(sorted({c for c in hand if "attack" in ctx.card_types(c)}))
    modes = []
    if attacks:
        modes.append("Discard an Attack")
    if hand.count("Curse") >= 2:
        modes.append("Discard two Curses")
    if len(hand) >= 6:
        modes.append("Discard six cards")
    if not modes:
        ctx.log("Quest: nothing to discard.")
        return
    (mode,) = yield ctx.choose("Quest: you may discard an Attack, two Curses or six cards to gain a Gold.", (*modes, "Do nothing"))
    if mode == "Do nothing":
        return
    if mode == "Discard an Attack":
        (card,) = yield ctx.choose("Quest: discard an Attack.", attacks)
        ctx.discard(card)
    elif mode == "Discard two Curses":
        ctx.discard("Curse")
        ctx.discard("Curse")
    else:
        chosen = yield ctx.choose("Quest: discard six cards.", hand, 6, 6)
        for card in chosen:
            ctx.discard(card)
    ctx.gain("Gold")


def _save(ctx):
    ctx.add_buys(1)
    hand = ctx.hand
    if hand:
        (card,) = yield ctx.choose("Save: set aside a card from your hand. It returns to your hand after you draw your next hand.", tuple(sorted(set(hand))))
        ctx.put_on_mat(card, "saved")
        ctx.log(f"{ctx.player_name} sets a card aside with Save.")


def _scouting_party(ctx):
    ctx.add_buys(1)
    cards = ctx.take_to_set_aside(5, reveal=False)
    if not cards:
        return
    n = min(3, len(cards))
    chosen = yield ctx.choose(f"Scouting Party: look at the top {len(cards)} cards of your deck. Discard {n}; the rest go back in any order.",
                              tuple(cards), n, n)
    rest = list(cards)
    for card in chosen:
        rest.remove(card)
        ctx.discard_set_aside(card)
    yield from _put_back_in_any_order(ctx, rest)


def _travelling_fair(ctx):
    ctx.add_buys(2)
    ctx.bump_count("Travelling Fair")


def _bonfire(ctx):
    options = ctx.in_play
    if not options:
        return
    chosen = yield ctx.choose("Bonfire: you may trash up to 2 cards you have in play.", options, 0, min(2, len(options)))
    for card in chosen:
        ctx.trash_in_play(card)


def _expedition(ctx):
    ctx.add_extra_draw(2)
    ctx.log(f"{ctx.player_name} will draw 2 extra cards for their next hand.")


def _token_event(token: str, text: str):
    def effect(ctx):
        piles = ctx.action_piles()
        if piles:
            (pile,) = yield ctx.choose(f"Put your {token} token on an Action pile. {text}", piles)
            ctx.move_token(token, pile)
    effect.__name__ = "_token_" + token
    return effect


def _mission(ctx):
    ctx.mark_mission()


def _pilgrimage(ctx):
    if not ctx.flip_journey():
        return
    options = tuple(sorted(set(ctx.in_play)))
    if not options:
        return
    chosen = yield ctx.choose("Pilgrimage: choose up to 3 differently named cards you have in play. Gain a copy of each.",
                              options, 0, min(3, len(options)))
    for card in chosen:
        ctx.gain(card)


def _ball(ctx):
    ctx.give_minus_coin(ctx.player)
    for _ in range(2):
        yield from _gain_up_to(ctx, "Ball: gain a card costing up to $4.", 4)


def _raid(ctx):
    for _ in range(ctx.in_play.count("Silver")):
        ctx.gain("Silver")
    for p in ctx.other_players():
        ctx.take_minus_card(p)


def _seaway(ctx):
    card = yield from _gain_up_to(ctx, "Seaway: gain an Action card costing up to $4. Your +1 Buy token moves to its pile.", 4, CardType.ACTION)
    if card is not None:
        ctx.move_token("+1 Buy", ctx.pile_of(card))


def _trade(ctx):
    hand = ctx.hand
    if not hand:
        return
    chosen = yield ctx.choose("Trade: trash up to 2 cards from your hand. Gain a Silver per card trashed.", hand, 0, min(2, len(hand)))
    for card in chosen:
        ctx.trash(card)
    for _ in chosen:
        ctx.gain("Silver")


def _inheritance(ctx):
    options = tuple(c for c in ctx.gainable(4, CardType.ACTION)
                    if not ctx.is_victory(c) and not {"duration", "reserve", "traveller"} & set(ctx.card_types(c)))
    if not options:
        ctx.log("Inheritance: there is no card to set aside.")
        return
    (card,) = yield ctx.choose("Inheritance: set aside a non-Victory Action card costing up to $4. Your Estates become Actions that play as it.", options)
    if not ctx.inherit(card):
        ctx.log("Inheritance has no effect: an Action is already set aside.")


_event("Alms", 0, "Once per turn: if you have no Treasures in play, gain a card costing up to $4.", _alms, True)
_event("Borrow", 0, "Once per turn: +1 Buy. If your -1 Card token is not on your deck, put it there and +$1.", _borrow, True)
_event("Quest", 0, "You may discard an Attack, two Curses, or six cards. If you did, gain a Gold.", _quest)
_event("Save", 1, "Once per turn: +1 Buy. Set aside a card from your hand, and put it into your hand at end of turn (after drawing).", _save, True)
_event("Scouting Party", 2, "+1 Buy. Look at the top 5 cards of your deck. Discard 3 of them and put the rest back in any order.", _scouting_party)
_event("Travelling Fair", 2, "+2 Buys. When you gain a card this turn, you may put it onto your deck.", _travelling_fair)
_event("Bonfire", 3, "Trash up to 2 cards you have in play.", _bonfire)
_event("Expedition", 3, "Draw 2 extra cards for your next hand.", _expedition)
_event("Ferry", 3, "Move your -$2 cost token to an Action Supply pile (cards from that pile cost $2 less on your turn).", _token_event("-$2 Cost", "Cards from it cost $2 less on your turn."))
_event("Plan", 3, "Move your Trashing token to an Action Supply pile (when you buy a card from that pile, you may trash a card from your hand).", _token_event("Trashing", "When you buy from it, you may trash a card from your hand."))
_event("Mission", 4, "Once per turn: take another turn after this one (not directly after another extra turn), in which you cannot buy cards.", _mission, True)
_event("Pilgrimage", 4, "Once per turn: turn your Journey token over (it starts face up). If it is face up, choose up to 3 differently named cards you have in play and gain a copy of each.", _pilgrimage, True)
_event("Ball", 5, "Take your -$1 token. Gain 2 cards each costing up to $4.", _ball)
_event("Raid", 5, "Gain a Silver per Silver you have in play. Each other player puts their -1 Card token on their deck.", _raid)
_event("Seaway", 5, "Gain an Action card costing up to $4. Move your +1 Buy token to its pile.", _seaway)
_event("Trade", 5, "Trash up to 2 cards from your hand. Gain a Silver per card you trashed.", _trade)
_event("Lost Arts", 6, "Move your +1 Action token to an Action Supply pile (when you play a card from it, +1 Action).", _token_event("+1 Action", "When you play a card from it, +1 Action."))
_event("Training", 6, "Move your +$1 token to an Action Supply pile (when you play a card from it, +$1).", _token_event("+$1", "When you play a card from it, +$1."))
_event("Inheritance", 7, "Set aside a non-Victory Action card from the Supply costing up to $4. Your Estates become Actions that play as that card.", _inheritance)
_event("Pathfinding", 8, "Move your +1 Card token to an Action Supply pile (when you play a card from it, +1 Card).", _token_event("+1 Card", "When you play a card from it, +1 Card."))
