"""The Dark Ages expansion (2012, first edition): 35 Kingdom piles (Knights are one pile of ten different cards).

What is new compared with the earlier card sets, and where the engine supports it:

  * "When you trash this" effects (Squire, Catacombs, Fortress, Hunting Grounds, Feodum, Cultist, Rats, Sir Vander,
    Overgrown Estate) use ``CardDef.on_trash``; Market Square is a Reaction to a trash (``on_trash_reaction``).
    The engine queues a ``TrashEvent`` for every card that goes to the trash and settles them after the card effect.
  * Mixed piles (Knights, Ruins): ``GameState.stacks``. Each card sits in the Supply under its own name, but only the top
    card of the pile can be bought or gained (``costs.is_buried``). A mixed pile is one pile for the end-of-game rule.
  * Looters (Death Cart, Marauder, Cultist) put Ruins into the game; Spoils (Bandit Camp, Marauder, Pillage), Madman (Hermit)
    and Mercenary (Urchin) are piles outside the Supply (``GameState.offsupply``).
  * Shelters (Hovel, Necropolis, Overgrown Estate) replace the three starting Estates (``GameConfig.shelters``).
  * Band of Misfits plays another Action "as if it were that card" (``ctx.play_as``); Urchin reacts to Attacks being played
    (``effects.urchin_steps``); Procession plays an Action twice and trashes it.
"""

from __future__ import annotations

import inspect
from dataclasses import replace

from .alchemy import _put_back_in_any_order
from .base import CardDef, CardType, action, treasure, victory
from .registry import register

SET = "Dark Ages"
_ATTACK = (CardType.ATTACK,)
_LOOTER = (CardType.ATTACK, CardType.LOOTER)


def _run(result):
    """Generator: run an effect's result if it is a generator."""
    if inspect.isgenerator(result):
        yield from result


def _pick(ctx, prompt: str, options, player=None):
    """Generator returning one of ``options``; with only one possible answer nobody is asked."""
    options = tuple(options)
    if len(options) == 1:
        return options[0]
    (card,) = yield ctx.choose(prompt, options, player=player)
    return card


def _in_range(ctx, card: str) -> bool:
    """Costs from $3 to $6 (a card that also costs a Potion does not count)."""
    return 3 <= ctx.cost_of(card) <= 6 and ctx.potion_cost_of(card) == 0


def _discard_down_to(ctx, targets, size: int):
    for p in targets:
        hand = ctx.hand_of(p)
        excess = len(hand) - size
        if excess > 0:
            chosen = yield ctx.choose(f"{ctx.player_name} played {ctx.source}. Discard down to {size} cards in hand.",
                                      hand, excess, excess, player=p)
            for card in chosen:
                ctx.discard(card, player=p)


# ----------------------------------------------------------------- $1 and $2
def _poor_house(ctx):
    ctx.add_coins(4)
    hand = ctx.hand
    ctx.log(f"{ctx.player_name} reveals their hand: {', '.join(sorted(hand)) or 'nothing'}.", "reveal")
    lost = min(sum(1 for c in hand if ctx.is_treasure(c)), ctx.coins)
    if lost:
        ctx.add_coins(-lost)
        ctx.log(f"{ctx.player_name} loses ${lost} (Treasures in hand).")


def _beggar(ctx):
    for _ in range(3):
        ctx.gain("Copper", destination="hand")


def _beggar_react(ctx):
    ctx.discard("Beggar")
    ctx.gain("Silver", destination="deck")
    ctx.gain("Silver")


def _squire(ctx):
    ctx.add_coins(1)
    (mode,) = yield ctx.choose("Squire: choose one.", ("+2 Actions", "+2 Buys", "Gain a Silver"))
    if mode == "+2 Actions":
        ctx.add_actions(2)
    elif mode == "+2 Buys":
        ctx.add_buys(2)
    else:
        ctx.gain("Silver")


def _squire_trash(ctx, event):
    options = ctx.gainable(1000, CardType.ATTACK)
    if options:
        (card,) = yield ctx.choose("You trashed Squire. Gain an Attack card.", options)
        ctx.gain(card)


def _vagrant(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    cards = ctx.take_to_set_aside(1, reveal=True)
    if not cards:
        return
    card = cards[0]
    if {"curse", "ruins", "shelter", "victory"} & set(ctx.card_types(card)):
        ctx.set_aside_to_hand(card)
        ctx.log(f"{ctx.player_name} puts {card} into their hand.")
    else:
        ctx.put_set_aside_on_deck(card)


# ----------------------------------------------------------------- $3
def _forager(ctx):
    ctx.add_actions(1)
    ctx.add_buys(1)
    hand = ctx.hand
    if hand:
        (card,) = yield ctx.choose("Forager: trash a card from your hand.", hand)
        ctx.trash(card)
    kinds = sum(1 for c in set(ctx.trash_pile()) if ctx.is_treasure(c))
    if kinds:
        ctx.add_coins(kinds)
        ctx.log(f"{ctx.player_name} gets +${kinds} (differently named Treasures in the trash).")


def _hermit(ctx):
    ctx.log(f"{ctx.player_name} looks through their discard pile.")
    from_hand = tuple(sorted({c for c in ctx.hand if not ctx.is_treasure(c)}))
    from_discard = tuple(sorted({c for c in ctx.discard_pile if not ctx.is_treasure(c)}))
    modes = []
    if from_discard:
        modes.append("Trash a card from your discard pile")
    if from_hand:
        modes.append("Trash a card from your hand")
    if modes:
        (mode,) = yield ctx.choose("Hermit: you may trash a card that is not a Treasure.", (*modes, "Trash nothing"))
        if mode == "Trash a card from your discard pile":
            (card,) = yield ctx.choose("Hermit: trash a card from your discard pile.", from_discard)
            ctx.trash_from_discard(card)
        elif mode == "Trash a card from your hand":
            (card,) = yield ctx.choose("Hermit: trash a card from your hand.", from_hand)
            ctx.trash(card)
    options = ctx.gainable(3)
    if options:
        (card,) = yield ctx.choose("Hermit: gain a card costing up to $3.", options)
        ctx.gain(card)


def _hermit_cleanup(ctx):
    if ctx.bought_this_turn == 0:
        ctx.trade_in_play_for_offsupply("Hermit", "Madman")


def _market_square_react(ctx, event):
    chosen = yield ctx.choose("One of your cards was trashed. You may discard Market Square to gain a Gold.",
                              ("Discard Market Square",), 0, 1)
    if chosen:
        ctx.log(f"{ctx.player_name} reveals Market Square.", "reveal")
        ctx.discard("Market Square")
        ctx.gain("Gold")


def _sage(ctx):
    ctx.add_actions(1)
    passed = []
    while True:
        cards = ctx.take_to_set_aside(1, reveal=True)
        if not cards:
            break
        if ctx.cost_of(cards[0]) >= 3:
            ctx.set_aside_to_hand(cards[0])
            ctx.log(f"{ctx.player_name} puts {cards[0]} into their hand.")
            break
        passed.append(cards[0])
    for card in passed:
        ctx.discard_set_aside(card)


def _storeroom(ctx):
    ctx.add_buys(1)
    hand = ctx.hand
    if hand:
        chosen = yield ctx.choose("Storeroom: discard any number of cards, then draw that many.", hand, 0, len(hand))
        for card in chosen:
            ctx.discard(card)
        ctx.draw(len(chosen))
    hand = ctx.hand
    if hand:
        chosen = yield ctx.choose("Storeroom: discard any number of cards for +$1 each.", hand, 0, len(hand))
        for card in chosen:
            ctx.discard(card)
        ctx.add_coins(len(chosen))


def _urchin(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    targets = yield from ctx.attack()
    yield from _discard_down_to(ctx, targets, 4)


# ----------------------------------------------------------------- $4
def _armory(ctx):
    options = ctx.gainable(4)
    if options:
        (card,) = yield ctx.choose("Armory: gain a card costing up to $4 onto your deck.", options)
        ctx.gain(card, destination="deck")


_DEATH_CART_SELF = "Trash Death Cart itself"


def _death_cart(ctx):
    actions = tuple(sorted({c for c in ctx.hand if ctx.is_action(c)}))
    if actions:
        (card,) = yield ctx.choose("Death Cart: trash an Action card from your hand, or Death Cart itself.",
                                   (*actions, _DEATH_CART_SELF))
        if card == _DEATH_CART_SELF:
            ctx.trash_self()
        else:
            ctx.trash(card)
    else:
        ctx.trash_self()
    ctx.add_coins(5)


def _death_cart_gain(ctx, event):
    ctx.gain_top("Ruins")
    ctx.gain_top("Ruins")


def _feodum_trash(ctx, event):
    for _ in range(3):
        ctx.gain("Silver")


def _fortress(ctx):
    ctx.draw(1)
    ctx.add_actions(2)


def _fortress_trash(ctx, event):
    ctx.take_trashed_to_hand(event.card)


def _ironmonger(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    cards = ctx.take_to_set_aside(1, reveal=True)
    if not cards:
        return
    card = cards[0]
    (mode,) = yield ctx.choose(f"Ironmonger: the top card of your deck is {card}. Discard it, or put it back?",
                               ("Discard it", "Put it back"))
    if mode == "Discard it":
        ctx.discard_set_aside(card)
    else:
        ctx.put_set_aside_on_deck(card)
    types = ctx.card_types(card)
    if "action" in types:
        ctx.add_actions(1)
    if "treasure" in types:
        ctx.add_coins(1)
    if "victory" in types:
        ctx.draw(1)


def _marauder(ctx):
    ctx.gain_from_offsupply("Spoils")
    targets = yield from ctx.attack()
    for p in targets:
        ctx.gain_top("Ruins", p)


def _scavenger(ctx):
    ctx.add_coins(2)
    if ctx.deck_size:
        chosen = yield ctx.choose("Scavenger: you may put your deck into your discard pile.",
                                  ("Put my deck into my discard pile",), 0, 1)
        if chosen:
            ctx.put_deck_into_discard()
    discard = ctx.discard_pile
    if discard:
        (card,) = yield ctx.choose("Scavenger: put a card from your discard pile onto your deck.", tuple(sorted(set(discard))))
        ctx.put_discard_on_deck(card)


def _wandering_minstrel(ctx):
    ctx.draw(1)
    ctx.add_actions(2)
    cards = ctx.take_to_set_aside(3, reveal=True)
    for card in [c for c in cards if not ctx.is_action(c)]:
        ctx.discard_set_aside(card)
    yield from _put_back_in_any_order(ctx, [c for c in cards if ctx.is_action(c)])


def _procession(ctx):
    options = tuple(sorted({c for c in ctx.hand if ctx.is_action(c) and "duration" not in ctx.card_types(c)}))
    if not options:
        return
    chosen = yield ctx.choose("Procession: you may play an Action card (not a Duration) from your hand twice, then trash it.",
                              options, 0, 1)
    if not chosen:
        return
    card = chosen[0]
    cost = ctx.cost_of(card)
    ctx.put_in_play(card, "hand")
    yield from ctx.resolve(card)
    yield from ctx.resolve(card)
    ctx.trash_in_play(card)
    gains = ctx.gainable(cost + 1, CardType.ACTION, exact=True)
    if gains:
        (gained,) = yield ctx.choose(f"Procession: gain an Action card costing exactly ${cost + 1}.", gains)
        ctx.gain(gained)


def _rats(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.gain("Rats")
    options = tuple(sorted({c for c in ctx.hand if c != "Rats"}))
    if options:
        (card,) = yield ctx.choose("Rats: trash a card from your hand other than Rats.", options)
        ctx.trash(card)
    else:
        ctx.log(f"{ctx.player_name} reveals a hand of Rats: {', '.join(sorted(ctx.hand)) or 'nothing'}.", "reveal")


def _draw_one_on_trash(ctx, event):
    ctx.draw(1)


# ----------------------------------------------------------------- $5
def _band_of_misfits(ctx):
    options = ctx.gainable(ctx.cost_of("Band of Misfits") - 1, CardType.ACTION)
    if not options:
        return
    chosen = yield ctx.choose("Band of Misfits: you may play an Action card from the Supply costing less, leaving it there.",
                              options, 0, 1)
    if chosen:
        ctx.log(f"{ctx.player_name}'s Band of Misfits acts as {chosen[0]}.", "play")
        yield from ctx.play_as(chosen[0])


def _bandit_camp(ctx):
    ctx.draw(1)
    ctx.add_actions(2)
    ctx.gain_from_offsupply("Spoils")


def _catacombs(ctx):
    cards = ctx.take_to_set_aside(3)
    if not cards:
        return
    (mode,) = yield ctx.choose(f"Catacombs: the top cards of your deck are {', '.join(cards)}. Put them into your hand, "
                               "or discard them and draw 3 cards?", ("Put them into my hand", "Discard them and draw 3 cards"))
    for card in cards:
        if mode == "Put them into my hand":
            ctx.set_aside_to_hand(card)
        else:
            ctx.discard_set_aside(card)
    if mode != "Put them into my hand":
        ctx.draw(3)


def _catacombs_trash(ctx, event):
    options = ctx.gainable(ctx.cost_of("Catacombs") - 1)
    if options:
        (card,) = yield ctx.choose("You trashed Catacombs. Gain a cheaper card.", options)
        ctx.gain(card)


def _count(ctx):
    first = ("Discard 2 cards", "Put a card from your hand onto your deck", "Gain a Copper")
    (mode,) = yield ctx.choose("Count: choose one.", first)
    hand = ctx.hand
    if mode == "Discard 2 cards":
        n = min(2, len(hand))
        if n:
            chosen = yield ctx.choose("Count: discard 2 cards.", hand, n, n)
            for card in chosen:
                ctx.discard(card)
    elif mode == "Gain a Copper":
        ctx.gain("Copper")
    elif hand:
        (card,) = yield ctx.choose("Count: put a card from your hand onto your deck.", hand)
        ctx.put_hand_on_deck(card)
    (mode,) = yield ctx.choose("Count: choose one.", ("+$3", "Trash your hand", "Gain a Duchy"))
    if mode == "+$3":
        ctx.add_coins(3)
    elif mode == "Gain a Duchy":
        ctx.gain("Duchy")
    else:
        for card in ctx.hand:
            ctx.trash(card)


def _counterfeit(ctx):
    ctx.add_buys(1)
    options = tuple(sorted({c for c in ctx.hand if ctx.is_treasure(c)}))
    if not options:
        return
    chosen = yield ctx.choose("Counterfeit: you may play a Treasure from your hand twice. If you do, trash it.", options, 0, 1)
    if not chosen:
        return
    card = chosen[0]
    yield from ctx.play_treasure(card, "hand")
    yield from ctx.play_treasure(card, "in_play")
    ctx.trash_in_play(card)


def _cultist(ctx):
    ctx.draw(2)
    targets = yield from ctx.attack()
    for p in targets:
        ctx.gain_top("Ruins", p)
    if "Cultist" in ctx.hand:
        chosen = yield ctx.choose("Cultist: you may play a Cultist from your hand.", ("Cultist",), 0, 1)
        if chosen:
            ctx.put_in_play("Cultist", "hand")
            yield from ctx.resolve("Cultist")


def _graverobber(ctx):
    from_trash = tuple(sorted({c for c in ctx.trash_pile() if _in_range(ctx, c)}))
    actions = tuple(sorted({c for c in ctx.hand if ctx.is_action(c)}))
    modes = []
    if from_trash:
        modes.append("Gain a card from the trash onto your deck")
    if actions:
        modes.append("Trash an Action card from your hand and gain a card")
    if not modes:
        return
    mode = yield from _pick(ctx, "Graverobber: choose one.", modes)
    if mode == "Gain a card from the trash onto your deck":
        (card,) = yield ctx.choose("Graverobber: gain a card costing $3 to $6 from the trash onto your deck.", from_trash)
        ctx.gain_from_trash(card, destination="deck")
    else:
        (card,) = yield ctx.choose("Graverobber: trash an Action card from your hand.", actions)
        cost = ctx.cost_of(card)
        ctx.trash(card)
        options = ctx.gainable(cost + 3)
        if options:
            (gained,) = yield ctx.choose(f"Graverobber: gain a card costing up to ${cost + 3}.", options)
            ctx.gain(gained)


def _junk_dealer(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.add_coins(1)
    hand = ctx.hand
    if hand:
        (card,) = yield ctx.choose("Junk Dealer: trash a card from your hand.", hand)
        ctx.trash(card)


def _all_names(ctx) -> tuple:
    return tuple(sorted(set(ctx.supply_names()) | set(ctx.offsupply_names())))


def _mystic(ctx):
    ctx.add_actions(1)
    ctx.add_coins(2)
    (named,) = yield ctx.choose("Mystic: name a card.", _all_names(ctx))
    ctx.log(f"{ctx.player_name} names {named}.", "special", 1)
    cards = ctx.take_to_set_aside(1, reveal=True)
    if cards:
        if cards[0] == named:
            ctx.set_aside_to_hand(cards[0])
            ctx.log(f"{ctx.player_name} puts {named} into their hand.")
        else:
            ctx.put_set_aside_on_deck(cards[0])


def _pillage(ctx):
    ctx.trash_self()
    targets = yield from ctx.attack()
    for p in targets:
        hand = ctx.hand_of(p)
        if len(hand) < 5:
            continue
        ctx.log(f"{ctx.name_of(p)} reveals their hand: {', '.join(sorted(hand))}.", "reveal")
        (card,) = yield ctx.choose(f"Pillage: choose a card for {ctx.name_of(p)} to discard.", tuple(sorted(set(hand))))
        ctx.discard(card, player=p)
    ctx.gain_from_offsupply("Spoils")
    ctx.gain_from_offsupply("Spoils")


def _rebuild(ctx):
    ctx.add_actions(1)
    (named,) = yield ctx.choose("Rebuild: name a card.", _all_names(ctx))
    ctx.log(f"{ctx.player_name} names {named}.", "special", 1)
    passed, found = [], None
    while True:
        cards = ctx.take_to_set_aside(1, reveal=True)
        if not cards:
            break
        if ctx.is_victory(cards[0]) and cards[0] != named:
            found = cards[0]
            break
        passed.append(cards[0])
    for card in passed:
        ctx.discard_set_aside(card)
    if found is None:
        return
    cost = ctx.cost_of(found)
    ctx.trash_set_aside(found)
    options = ctx.gainable(cost + 3, CardType.VICTORY)
    if options:
        (gained,) = yield ctx.choose(f"Rebuild: gain a Victory card costing up to ${cost + 3}.", options)
        ctx.gain(gained)


def _rogue(ctx):
    ctx.add_coins(2)
    from_trash = tuple(sorted({c for c in ctx.trash_pile() if _in_range(ctx, c)}))
    if from_trash:
        (card,) = yield ctx.choose("Rogue: gain a card costing $3 to $6 from the trash.", from_trash)
        ctx.gain_from_trash(card)
        return
    targets = yield from ctx.attack()
    for p in targets:
        cards = ctx.take_to_set_aside(2, player=p, reveal=True)
        eligible = tuple(sorted({c for c in cards if _in_range(ctx, c)}))
        rest = list(cards)
        if eligible:
            card = yield from _pick(ctx, "Rogue: trash one of the revealed cards costing $3 to $6.", eligible, p)
            ctx.trash_set_aside(card, player=p)
            rest.remove(card)
        for card in rest:
            ctx.discard_set_aside(card, player=p)


# ----------------------------------------------------------------- $6
def _altar(ctx):
    hand = ctx.hand
    if hand:
        (card,) = yield ctx.choose("Altar: trash a card from your hand.", hand)
        ctx.trash(card)
    options = ctx.gainable(5)
    if options:
        (gained,) = yield ctx.choose("Altar: gain a card costing up to $5.", options)
        ctx.gain(gained)


def _hunting_grounds_trash(ctx, event):
    options = []
    if ctx.supply_count("Duchy") > 0:
        options.append("Gain a Duchy")
    if ctx.supply_count("Estate") > 0:
        options.append("Gain 3 Estates")
    if not options:
        return
    (mode,) = yield ctx.choose("You trashed Hunting Grounds. Gain a Duchy or 3 Estates.", options)
    for _ in range(1 if mode == "Gain a Duchy" else 3):
        ctx.gain("Duchy" if mode == "Gain a Duchy" else "Estate")


# ----------------------------------------------------------------- Knights
def _knight(extra=None, per_target=None):
    """Every Knight: its own text first, then "each other player reveals the top 2 cards of their deck, trashes one
    costing $3 to $6 and discards the rest. If a Knight was trashed, trash this card"."""
    def play(ctx):
        if extra is not None:
            yield from _run(extra(ctx))
        targets = yield from ctx.attack()
        if per_target is not None:
            yield from per_target(ctx, targets)
        trashed_knight = False
        for p in targets:
            cards = ctx.take_to_set_aside(2, player=p, reveal=True)
            eligible = tuple(sorted({c for c in cards if _in_range(ctx, c)}))
            rest = list(cards)
            if eligible:
                card = yield from _pick(ctx, "Knight: trash one of the revealed cards costing $3 to $6.", eligible, p)
                ctx.trash_set_aside(card, player=p)
                rest.remove(card)
                if "knight" in ctx.card_types(card):
                    trashed_knight = True
            for card in rest:
                ctx.discard_set_aside(card, player=p)
        if trashed_knight:
            ctx.trash_self()
    return play


def _anna(ctx):
    hand = ctx.hand
    if hand:
        chosen = yield ctx.choose("Dame Anna: you may trash up to 2 cards from your hand.", hand, 0, min(2, len(hand)))
        for card in chosen:
            ctx.trash(card)


def _natalie(ctx):
    options = ctx.gainable(3)
    if options:
        chosen = yield ctx.choose("Dame Natalie: you may gain a card costing up to $3.", options, 0, 1)
        if chosen:
            ctx.gain(chosen[0])


def _vander_trash(ctx, event):
    ctx.gain("Gold")


def _market_square(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.add_buys(1)


def _plus_actions(n):
    return lambda ctx: ctx.add_actions(n)


def _plus_coins(n):
    return lambda ctx: ctx.add_coins(n)


def _plus_cards(n):
    return lambda ctx: ctx.draw(n)


def _bailey(ctx):
    ctx.draw(1)
    ctx.add_actions(1)


def _martin(ctx):
    ctx.add_buys(2)


_KNIGHT_TEXT = "Each other player reveals the top 2 cards of their deck, trashes one costing from $3 to $6, and discards the rest. If a Knight was trashed, trash this."


def _register_knights() -> None:
    specs = [
        ("Dame Anna", 5, _anna, "You may trash up to 2 cards from your hand. ", None, 0),
        ("Dame Josephine", 5, None, "", None, 2),
        ("Dame Molly", 5, _plus_actions(2), "+2 Actions. ", None, 0),
        ("Dame Natalie", 5, _natalie, "You may gain a card costing up to $3. ", None, 0),
        ("Dame Sylvia", 5, _plus_coins(2), "+$2. ", None, 0),
        ("Sir Bailey", 5, _bailey, "+1 Card, +1 Action. ", None, 0),
        ("Sir Destry", 5, _plus_cards(2), "+2 Cards. ", None, 0),
        ("Sir Martin", 4, _martin, "+2 Buys. ", None, 0),
        ("Sir Michael", 5, None, "", "michael", 0),
        ("Sir Vander", 5, None, "", "vander", 0),
    ]
    for name, cost, extra, prefix, special, vp in specs:
        if special == "michael":
            play = _knight(None, lambda ctx, targets: _discard_down_to(ctx, targets, 3))
            body = "Each other player discards down to 3 cards in hand. " + _KNIGHT_TEXT
        else:
            play = _knight(extra)
            body = prefix + _KNIGHT_TEXT
        types = {CardType.ACTION, CardType.ATTACK, CardType.KNIGHT}
        if vp:
            types.add(CardType.VICTORY)
            body = "2 VP. " + body
        text = body
        if name == "Sir Vander":
            text += " When you trash this, gain a Gold."
        register(CardDef(name, cost, frozenset(types), vp=vp, on_play=play, text=text, expansion=SET,
                         on_trash=_vander_trash if name == "Sir Vander" else None))


# ----------------------------------------------------------------- Ruins
def _ruins_effect(name: str):
    def survivors(ctx):
        cards = ctx.take_to_set_aside(2)
        if not cards:
            return
        (mode,) = yield ctx.choose(f"Survivors: the top cards of your deck are {', '.join(cards)}. Discard them, or put them back?",
                                   ("Discard them", "Put them back"))
        if mode == "Discard them":
            for card in cards:
                ctx.discard_set_aside(card)
        else:
            yield from _put_back_in_any_order(ctx, cards)
    return {
        "Abandoned Mine": lambda ctx: ctx.add_coins(1),
        "Ruined Library": lambda ctx: ctx.draw(1),
        "Ruined Market": lambda ctx: ctx.add_buys(1),
        "Ruined Village": lambda ctx: ctx.add_actions(1),
        "Survivors": survivors,
    }[name]


_RUINS_TEXT = {
    "Abandoned Mine": "+$1",
    "Ruined Library": "+1 Card",
    "Ruined Market": "+1 Buy",
    "Ruined Village": "+1 Action",
    "Survivors": "Look at the top 2 cards of your deck. Discard them or put them back in any order.",
}


# ----------------------------------------------------------------- Shelters, Spoils, Madman, Mercenary
def _hovel_react(ctx, event):
    if not event.bought or not ctx.is_victory(event.card):
        return
    chosen = yield ctx.choose(f"You bought {event.card}. You may trash Hovel from your hand.", ("Trash Hovel",), 0, 1)
    if chosen:
        ctx.log(f"{ctx.player_name} reveals Hovel.", "reveal")
        ctx.trash("Hovel")


def _madman(ctx):
    ctx.add_actions(2)
    if ctx.return_in_play_to_offsupply("Madman"):
        ctx.draw(ctx.hand_size)


def _mercenary(ctx):
    if ctx.hand_size < 2:
        return
    go = yield ctx.choose("Mercenary: you may trash 2 cards from your hand. If you do, +2 Cards, +$2 and each other player discards down to 3 cards.",
                          ("Trash 2 cards",), 0, 1)
    if not go:
        return
    chosen = yield ctx.choose("Mercenary: trash 2 cards from your hand.", ctx.hand, 2, 2)
    for card in chosen:
        ctx.trash(card)
    ctx.draw(2)
    ctx.add_coins(2)
    targets = yield from ctx.attack()
    yield from _discard_down_to(ctx, targets, 3)


# ================================================================= registration
def _register_all() -> None:
    R = register
    R(action("Poor House", 1, _poor_house, "+$4. Reveal your hand. -$1 per Treasure card in your hand (you can't go below $0).", expansion=SET))
    R(action("Beggar", 2, _beggar, "Gain 3 Coppers into your hand. When another player plays an Attack, you may first discard this to gain 2 Silvers, putting one on your deck.",
             extra_types=(CardType.REACTION,), on_attack=_beggar_react, expansion=SET))
    R(action("Squire", 2, _squire, "+$1. Choose one: +2 Actions; or +2 Buys; or gain a Silver. When you trash this, gain an Attack card.",
             on_trash=_squire_trash, expansion=SET))
    R(action("Vagrant", 2, _vagrant, "+1 Card, +1 Action. Reveal the top card of your deck. If it's a Curse, Ruins, Shelter or Victory card, put it into your hand.", expansion=SET))
    R(action("Forager", 3, _forager, "+1 Action, +1 Buy. Trash a card from your hand. +$1 per differently named Treasure in the trash.", expansion=SET))
    R(action("Hermit", 3, _hermit, "Look through your discard pile. You may trash a card from it or from your hand that is not a Treasure. Gain a card costing up to $3. "
             "When you discard this from play, if you did not buy any cards this turn, trade it for a Madman.", on_cleanup=_hermit_cleanup, expansion=SET))
    R(action("Market Square", 3, _market_square,
             "+1 Card, +1 Action, +1 Buy. When one of your cards is trashed, you may discard this from your hand to gain a Gold.",
             extra_types=(CardType.REACTION,), on_trash_reaction=_market_square_react, expansion=SET))
    R(action("Sage", 3, _sage, "+1 Action. Reveal cards from the top of your deck until you reveal one costing $3 or more. Put it into your hand and discard the rest.", expansion=SET))
    R(action("Storeroom", 3, _storeroom, "+1 Buy. Discard any number of cards, then draw that many. Then discard any number of cards for +$1 each.", expansion=SET))
    R(action("Urchin", 3, _urchin, "+1 Card, +1 Action. Each other player discards down to 4 cards in hand. When you play another Attack card with this in play, "
             "you may trash this. If you do, gain a Mercenary.", extra_types=_ATTACK, expansion=SET))
    R(action("Armory", 4, _armory, "Gain a card costing up to $4 onto your deck.", expansion=SET))
    R(action("Death Cart", 4, _death_cart, "You may trash an Action card from your hand. If you don't, trash this. +$5. When you gain this, gain 2 Ruins.",
             extra_types=(CardType.LOOTER,), on_gain=_death_cart_gain, expansion=SET))
    R(replace(victory("Feodum", 4, score_fn=lambda cards: sum(1 for c in cards if c == "Silver") // 3,
                      text="Worth 1 VP per 3 Silvers you have (round down). When you trash this, gain 3 Silvers.", kingdom=True, expansion=SET),
              on_trash=_feodum_trash))
    R(action("Fortress", 4, _fortress, "+1 Card, +2 Actions. When you trash this, put it into your hand.", on_trash=_fortress_trash, expansion=SET))
    R(action("Ironmonger", 4, _ironmonger, "+1 Card, +1 Action. Reveal the top card of your deck; you may discard it. Either way, if it is an Action card, +1 Action; "
             "a Treasure card, +$1; a Victory card, +1 Card.", expansion=SET))
    R(action("Marauder", 4, _marauder, "Gain a Spoils from the Spoils pile. Each other player gains a Ruins.", extra_types=_LOOTER, expansion=SET))
    R(action("Scavenger", 4, _scavenger, "+$2. You may put your deck into your discard pile. Look through your discard pile and put one card from it onto your deck.", expansion=SET))
    R(action("Wandering Minstrel", 4, _wandering_minstrel, "+1 Card, +2 Actions. Reveal the top 3 cards of your deck. Put the Actions back in any order and discard the rest.", expansion=SET))
    R(action("Procession", 4, _procession, "You may play an Action card from your hand twice. Trash it. Gain an Action card costing exactly $1 more than it. "
             "(Duration cards cannot be chosen.)", expansion=SET))
    R(action("Rats", 4, _rats, "+1 Card, +1 Action. Gain a Rats. Trash a card from your hand other than a Rats (or reveal a hand of all Rats). "
             "When you trash this, +1 Card. (The pile has 20 cards.)", on_trash=_draw_one_on_trash, expansion=SET))
    R(action("Band of Misfits", 5, _band_of_misfits, "Play this as if it were an Action card in the Supply costing less than it that you choose, leaving that card there.", expansion=SET))
    R(action("Bandit Camp", 5, _bandit_camp, "+1 Card, +2 Actions. Gain a Spoils from the Spoils pile.", expansion=SET))
    R(action("Catacombs", 5, _catacombs, "Look at the top 3 cards of your deck. Choose one: put them into your hand; or discard them and +3 Cards. "
             "When you trash this, gain a cheaper card.", on_trash=_catacombs_trash, expansion=SET))
    R(action("Count", 5, _count, "Choose one: discard 2 cards; or put a card from your hand onto your deck; or gain a Copper. Then choose one: +$3; or trash your hand; or gain a Duchy.", expansion=SET))
    R(treasure("Counterfeit", 5, 1, text="$1, +1 Buy. When you play this, you may play a Treasure from your hand twice. If you do, trash that Treasure.",
               kingdom=True, expansion=SET, on_play=_counterfeit))
    R(action("Cultist", 5, _cultist, "+2 Cards. Each other player gains a Ruins. You may play a Cultist from your hand. When you trash this, +3 Cards.",
             extra_types=_LOOTER, on_trash=lambda ctx, event: ctx.draw(3), expansion=SET))
    R(action("Graverobber", 5, _graverobber, "Choose one: gain a card from the trash costing from $3 to $6 onto your deck; or trash an Action card from your hand "
             "and gain a card costing up to $3 more than it.", expansion=SET))
    R(action("Junk Dealer", 5, _junk_dealer, "+1 Card, +1 Action, +$1. Trash a card from your hand.", expansion=SET))
    R(action("Mystic", 5, _mystic, "+1 Action, +$2. Name a card. Reveal the top card of your deck. If it's the named card, put it into your hand.", expansion=SET))
    R(action("Pillage", 5, _pillage, "Trash this. Each other player with 5 or more cards in hand reveals their hand and discards a card that you choose. Gain 2 Spoils.",
             extra_types=_ATTACK, expansion=SET))
    R(action("Rebuild", 5, _rebuild, "+1 Action. Name a card. Reveal cards from the top of your deck until you reveal a Victory card that is not the named card. "
             "Discard the rest, trash the Victory card, and gain a Victory card costing up to $3 more than it.", expansion=SET))
    R(action("Rogue", 5, _rogue, "+$2. If there are any cards in the trash costing from $3 to $6, gain one of them. Otherwise, each other player reveals the top 2 cards "
             "of their deck, trashes one of them costing from $3 to $6, and discards the rest.", extra_types=_ATTACK, expansion=SET))
    R(action("Altar", 6, _altar, "Trash a card from your hand. Gain a card costing up to $5.", expansion=SET))
    R(action("Hunting Grounds", 6, lambda ctx: ctx.draw(4), "+4 Cards. When you trash this, gain a Duchy or 3 Estates.",
             on_trash=_hunting_grounds_trash, expansion=SET))
    R(CardDef("Knights", 5, frozenset({CardType.KNIGHT}), kingdom=True, expansion=SET,
              text="A pile of 10 different Knights (Dame Anna, Dame Josephine, Dame Molly, Dame Natalie, Dame Sylvia, Sir Bailey, Sir Destry, Sir Martin, Sir Michael, "
                   "Sir Vander), shuffled; only the top Knight can be bought or gained. Each is an Action - Attack that makes the others trash a card costing $3 to $6."))
    _register_knights()
    for name in ("Abandoned Mine", "Ruined Library", "Ruined Market", "Ruined Village", "Survivors"):
        R(CardDef(name, 0, frozenset({CardType.ACTION, CardType.RUINS}), on_play=_ruins_effect(name), text=_RUINS_TEXT[name], expansion=SET))
    R(treasure("Spoils", 0, 3, text="$3. When you play this, return it to the Spoils pile.",
               expansion=SET, on_play=lambda ctx: ctx.return_in_play_to_offsupply("Spoils")))
    R(action("Madman", 0, _madman, "+2 Actions. Return this to the Madman pile. If you do, +1 Card per card in your hand.", kingdom=False, expansion=SET))
    R(action("Mercenary", 0, _mercenary, "You may trash 2 cards from your hand. If you do, +2 Cards, +$2, and each other player discards down to 3 cards in hand.",
             kingdom=False, extra_types=_ATTACK, expansion=SET))
    R(CardDef("Hovel", 1, frozenset({CardType.REACTION, CardType.SHELTER}), on_gain_reaction=_hovel_react, expansion=SET,
              text="When you buy a Victory card, you may trash this from your hand."))
    R(action("Necropolis", 1, lambda ctx: ctx.add_actions(2), "+2 Actions", kingdom=False, extra_types=(CardType.SHELTER,), expansion=SET))
    R(CardDef("Overgrown Estate", 1, frozenset({CardType.VICTORY, CardType.SHELTER}), vp=0, on_trash=_draw_one_on_trash, expansion=SET,
              text="0 VP. When you trash this, +1 Card."))


_register_all()
