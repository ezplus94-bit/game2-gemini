"""The Nocturne expansion (2017): 33 Kingdom cards, 12 Boons, 12 Hexes, the States, 7 Heirlooms and the extra cards.

What is new, and where the engine supports it:

  * Night cards (``CardType.NIGHT``) are played in the new Night phase (Action, Buy, **Night**, Clean-up), for no Action.
    The phase is only entered when the player holds a Night card after the Buy phase. Night cards are played with the same
    ``PlayAction`` as Actions; Werewolf is both and works in either phase.
  * Fate and Doom cards hand out Boons and Hexes: decks of 12 kept in ``GameState`` (``boons``, ``hexes`` and their discard
    piles), received through ``ctx.receive_boon()`` / ``ctx.receive_hex()``. The Field's, Forest's and River's Gifts are kept
    until Clean-up. Each Boon and Hex is a plain function below (``BOON_FUNCS`` / ``HEX_FUNCS``); they are not cards.
  * States: Deluded, Envious, Miserable / Twice Miserable (per player) and Lost in the Woods (one holder).
  * Heirlooms replace one starting Copper (``CardDef.heirloom``); Durations are the Seaside ones; "gained to your hand"
    is ``CardDef.gains_to_hand``; exchanges (Changeling, Vampire, Bat) are not gains.
"""

from __future__ import annotations

from collections import Counter

from .adventures import _gain_up_to
from .alchemy import _put_back_in_any_order
from .base import CardDef, CardType
from .registry import get_card, register

SET = "Nocturne"
T = CardType

# ---------------------------------------------------------------- Boons, Hexes, States (text)
BOONS = {
    "The Earth's Gift": "You may discard a Treasure to gain a card costing up to $4.",
    "The Field's Gift": "+1 Action, +$1. (Keep this until Clean-up.)",
    "The Flame's Gift": "You may trash a card from your hand.",
    "The Forest's Gift": "+1 Buy, +$1. (Keep this until Clean-up.)",
    "The Moon's Gift": "Look through your discard pile. You may put a card from it onto your deck.",
    "The Mountain's Gift": "Gain a Silver.",
    "The River's Gift": "+1 Card at the end of this turn. (Keep this until Clean-up.)",
    "The Sea's Gift": "+1 Card.",
    "The Sky's Gift": "You may discard 3 cards to gain a Gold.",
    "The Sun's Gift": "Look at the top 4 cards of your deck. Discard any number of them and put the rest back in any order.",
    "The Swamp's Gift": "Gain a Will-o'-Wisp from its pile.",
    "The Wind's Gift": "+2 Cards, then discard 2 cards.",
}
HEXES = {
    "Bad Omens": "Put your deck into your discard pile. Look through it and put 2 Coppers from it onto your deck (or reveal you can't).",
    "Delusion": "If you don't have Deluded or Envious, take Deluded.",
    "Envy": "If you don't have Deluded or Envious, take Envious.",
    "Famine": "Reveal the top 3 cards of your deck. Discard the Actions. Shuffle the rest into your deck.",
    "Fear": "If you have at least 5 cards in hand, discard an Action or Treasure (or reveal you can't).",
    "Greed": "Gain a Copper onto your deck.",
    "Haunting": "If you have at least 4 cards in hand, put one of them onto your deck.",
    "Locusts": "Trash the top card of your deck. If it's Copper or Estate, gain a Curse. Otherwise, gain a cheaper card that shares a type with it.",
    "Misery": "If this is your first Misery this game, take Miserable. Otherwise, flip it over to Twice Miserable.",
    "Plague": "Gain a Curse to your hand.",
    "Poverty": "Discard down to 3 cards in hand.",
    "War": "Reveal cards from your deck until revealing one costing $3 or $4. Trash it and discard the rest.",
}
STATES = {
    "Deluded": "At the start of your Buy phase, return this, and you can't buy Actions this turn.",
    "Envious": "At the start of your Buy phase, return this, and Silver and Gold make $1 this turn.",
    "Miserable": "When scoring, -2 VP.",
    "Twice Miserable": "When scoring, -4 VP.",
    "Lost in the Woods": "At the start of your turn, you may discard a card to receive a Boon.",
}
BOON_NAMES = tuple(BOONS)
HEX_NAMES = tuple(HEXES)
KEPT_BOONS = ("The Field's Gift", "The Forest's Gift", "The River's Gift")
ZOMBIES = ("Zombie Apprentice", "Zombie Mason", "Zombie Spy")
SPIRITS = ("Will-o'-Wisp", "Imp", "Ghost")


def _exact_cost(ctx, card: str, *costs: int) -> bool:
    """Does the card cost exactly $n (n in costs) with no Potion or Debt in the cost?"""
    return ctx.cost_of(card) in costs and not ctx.potion_cost_of(card) and not get_card(card).debt_cost


def _discard_down_to(ctx, n: int, prompt: str):
    excess = len(ctx.hand) - n
    if excess > 0:
        chosen = yield ctx.choose(prompt, ctx.hand, excess, excess)
        for card in chosen:
            ctx.discard(card)


# ---------------------------------------------------------------- Boons
def _earth(ctx):
    treasures = tuple(sorted({c for c in ctx.hand if ctx.is_treasure(c)}))
    if not treasures:
        return
    chosen = yield ctx.choose("You may discard a Treasure to gain a card costing up to $4.", treasures, 0, 1)
    if chosen:
        ctx.discard(chosen[0])
        yield from _gain_up_to(ctx, "Gain a card costing up to $4.", 4)


def _field(ctx):
    if ctx.my_turn:
        ctx.add_actions(1)
        ctx.add_coins(1)


def _flame(ctx):
    if ctx.hand:
        chosen = yield ctx.choose("You may trash a card from your hand.", tuple(sorted(set(ctx.hand))), 0, 1)
        if chosen:
            ctx.trash(chosen[0])


def _forest(ctx):
    if ctx.my_turn:
        ctx.add_buys(1)
        ctx.add_coins(1)


def _moon(ctx):
    options = tuple(sorted(set(ctx.discard_pile)))
    if not options:
        return
    chosen = yield ctx.choose("Look through your discard pile. You may put a card from it onto your deck.", options, 0, 1)
    if chosen:
        ctx.put_discard_on_deck(chosen[0])


def _mountain(ctx):
    ctx.gain("Silver")


def _river(ctx):
    ctx.add_river_draw()


def _sea(ctx):
    ctx.draw(1)


def _sky(ctx):
    hand = ctx.hand
    if not hand:
        return
    n = min(3, len(hand))
    chosen = yield ctx.choose("You may discard 3 cards to gain a Gold.", ("Discard 3 cards" if n == 3 else f"Discard your {n} card(s)",), 0, 1)
    if not chosen:
        return
    picked = yield ctx.choose("Discard 3 cards.", hand, n, n)
    for card in picked:
        ctx.discard(card)
    if n == 3:
        ctx.gain("Gold")


def _sun(ctx):
    cards = ctx.take_to_set_aside(4)
    if not cards:
        return
    chosen = yield ctx.choose(f"The top {len(cards)} cards of your deck: discard any number; the rest go back in any order.", tuple(cards), 0, len(cards))
    rest = list(cards)
    for card in chosen:
        rest.remove(card)
        ctx.discard_set_aside(card)
    yield from _put_back_in_any_order(ctx, rest)


def _swamp(ctx):
    ctx.gain_from_offsupply("Will-o'-Wisp")


def _wind(ctx):
    ctx.draw(2)
    yield from _discard_down_to(ctx, len(ctx.hand) - min(2, len(ctx.hand)), "Discard 2 cards.")


BOON_FUNCS = {
    "The Earth's Gift": _earth, "The Field's Gift": _field, "The Flame's Gift": _flame, "The Forest's Gift": _forest,
    "The Moon's Gift": _moon, "The Mountain's Gift": _mountain, "The River's Gift": _river, "The Sea's Gift": _sea,
    "The Sky's Gift": _sky, "The Sun's Gift": _sun, "The Swamp's Gift": _swamp, "The Wind's Gift": _wind,
}


# ---------------------------------------------------------------- Hexes
def _bad_omens(ctx):
    ctx.put_deck_into_discard()
    n = min(2, ctx.discard_pile.count("Copper"))
    for _ in range(n):
        ctx.put_discard_on_deck("Copper")
    if n < 2:
        ctx.log(f"{ctx.player_name} reveals their deck: there were only {n} Copper(s).", "reveal")


def _delusion(ctx):
    ctx.take_deluded()


def _envy(ctx):
    ctx.take_envious()


def _famine(ctx):
    cards = ctx.take_to_set_aside(3, reveal=True)
    rest = []
    for card in cards:
        if ctx.is_action(card):
            ctx.discard_set_aside(card)
        else:
            rest.append(card)
    if rest:
        ctx.shuffle_set_aside_into_deck(rest)


def _fear(ctx):
    if len(ctx.hand) < 5:
        return
    options = tuple(sorted({c for c in ctx.hand if ctx.is_action(c) or ctx.is_treasure(c)}))
    if not options:
        ctx.log(f"{ctx.player_name} reveals their hand: no Actions or Treasures.", "reveal")
        return
    (card,) = yield ctx.choose("Fear: discard an Action or Treasure.", options)
    ctx.discard(card)


def _greed(ctx):
    ctx.gain("Copper", destination="deck")


def _haunting(ctx):
    if len(ctx.hand) >= 4:
        (card,) = yield ctx.choose("Haunting: put a card from your hand onto your deck.", tuple(sorted(set(ctx.hand))))
        ctx.put_hand_on_deck(card)


def _locusts(ctx):
    card = ctx.trash_top_of_deck()
    if card is None:
        return
    if card in ("Copper", "Estate"):
        ctx.gain("Curse")
        return
    options = ctx.cheaper_sharing_type(card)
    if options:
        (new,) = yield ctx.choose(f"Locusts: gain a card costing less than {card} that shares a type with it.", options)
        ctx.gain(new)


def _misery(ctx):
    ctx.take_miserable()


def _plague(ctx):
    ctx.gain("Curse", destination="hand")


def _poverty(ctx):
    yield from _discard_down_to(ctx, 3, "Poverty: discard down to 3 cards in hand.")


def _war(ctx):
    revealed = []
    while True:
        cards = ctx.take_to_set_aside(1, reveal=True)
        if not cards:
            break
        card = cards[0]
        if _exact_cost(ctx, card, 3, 4):
            ctx.trash_set_aside(card)
            break
        revealed.append(card)
    for card in revealed:
        ctx.discard_set_aside(card)


HEX_FUNCS = {
    "Bad Omens": _bad_omens, "Delusion": _delusion, "Envy": _envy, "Famine": _famine, "Fear": _fear, "Greed": _greed,
    "Haunting": _haunting, "Locusts": _locusts, "Misery": _misery, "Plague": _plague, "Poverty": _poverty, "War": _war,
}


# ---------------------------------------------------------------- shared card helpers
def _play_new_action(ctx, prompt: str):
    """Conclave and Imp: play an Action card from the hand that you do not have a copy of in play. True if one was played."""
    options = tuple(sorted({c for c in ctx.hand if ctx.is_action(c) and c not in ctx.in_play}))
    if not options:
        return False
    chosen = yield ctx.choose(prompt, options, 0, 1)
    if not chosen:
        return False
    ctx.put_in_play(chosen[0], "hand")
    yield from ctx.resolve(chosen[0])
    return True


def _hex_others(ctx):
    """Attack step shared by Skulk, Tormentor, Vampire and Werewolf: each other player (not blocked) receives the next Hex."""
    targets = yield from ctx.attack()
    yield from ctx.receive_hex(targets)


def K(name, cost, types, fn, text, **kw):
    return register(CardDef(name, cost, frozenset(types), on_play=fn, text=text, kingdom=True, expansion=SET, **kw))


def X(name, cost, types, fn, text, **kw):
    """A card of the set that is never a Kingdom pile."""
    return register(CardDef(name, cost, frozenset(types), on_play=fn, text=text, kingdom=False, expansion=SET, **kw))


# ---------------------------------------------------------------- Kingdom cards
def _bard(ctx):
    ctx.add_coins(2)
    yield from ctx.receive_boon()


def _blessed_village(ctx):
    ctx.draw(1)
    ctx.add_actions(2)


def _blessed_village_gain(ctx, event):
    boon = ctx.draw_boon()
    if boon is None:
        return
    ctx.log(f"{ctx.player_name} takes {boon}.", "boon")
    now, later = "Receive it now", "Receive it at the start of your next turn"
    (mode,) = yield ctx.choose(f"Blessed Village: you took {boon} ({BOONS[boon]}) Receive it now, or at the start of your next turn?", (now, later))
    if mode == now:
        yield from ctx.receive_boon(boon)
    else:
        ctx.hold_boon(boon)


def _cemetery_gain(ctx, event):
    if ctx.hand:
        chosen = yield ctx.choose("Cemetery: you may trash up to 4 cards from your hand.", ctx.hand, 0, min(4, len(ctx.hand)))
        for card in chosen:
            ctx.trash(card)


def _changeling(ctx):
    if not ctx.trash_self():
        return
    options = ctx.copies_available(ctx.in_play)
    if not options:
        ctx.log("Changeling: there is no card in play to copy.")
        return
    (card,) = yield ctx.choose("Changeling: gain a copy of a card you have in play.", options)
    ctx.gain_copy(card)


def _cobbler(ctx):
    ctx.add_duration(_cobbler_start)
    return None


def _cobbler_start(ctx, entry):
    yield from _gain_up_to(ctx, "Cobbler: gain a card to your hand costing up to $4.", 4, destination="hand")


def _conclave(ctx):
    ctx.add_coins(2)
    if (yield from _play_new_action(ctx, "Conclave: you may play an Action card from your hand that you don't have a copy of in play.")):
        ctx.add_actions(1)


def _crypt(ctx):
    treasures = tuple(c for c in ctx.in_play if ctx.is_treasure(c))
    if not treasures:
        return
    chosen = yield ctx.choose("Crypt: set aside any number of Treasures you have in play, face down.", treasures, 0, len(treasures))
    for card in chosen:
        ctx.put_on_mat(card, "crypt", source="in_play")
    if chosen:
        ctx.log(f"{ctx.player_name} sets aside {len(chosen)} Treasure(s) under Crypt.")
        ctx.add_duration(_crypt_start, len(chosen))


def _crypt_start(ctx, entry):
    pool = ctx.mat_cards("crypt")
    if not pool or entry.data <= 0:
        return
    (card,) = yield ctx.choose("Crypt: put one of the set-aside Treasures into your hand.", tuple(sorted(set(pool))))
    ctx.put_on_mat(card, "hand", source="crypt")
    ctx.log(f"{ctx.player_name} puts {card} from under Crypt into their hand.")
    if entry.data > 1:
        ctx.add_duration(_crypt_start, entry.data - 1)


def _cursed_village(ctx):
    ctx.add_actions(2)
    missing = 6 - len(ctx.hand)
    if missing > 0:
        ctx.draw(missing)


def _cursed_village_gain(ctx, event):
    yield from ctx.receive_hex()


def _den_of_sin(ctx):
    ctx.add_duration(_den_start)


def _den_start(ctx, entry):
    ctx.draw(2)


def _devils_workshop(ctx):
    n = len(ctx.gained_this_turn())
    if n >= 2:
        ctx.gain_from_offsupply("Imp")
    elif n == 1:
        yield from _gain_up_to(ctx, "Devil's Workshop: gain a card costing up to $4.", 4)
    else:
        ctx.gain("Gold")


def _druid(ctx):
    ctx.add_buys(1)
    options = ctx.druid_boons
    if options:
        (boon,) = yield ctx.choose("Druid: receive one of the set-aside Boons (it stays there).", options)
        yield from ctx.receive_boon(boon, dispose=False)


def _exorcist(ctx):
    if not ctx.hand:
        return
    (card,) = yield ctx.choose("Exorcist: trash a card from your hand.", tuple(sorted(set(ctx.hand))))
    ctx.trash(card)
    spirits = tuple(s for s in ("Ghost", "Imp", "Will-o'-Wisp") if s in ctx.offsupply_names() and ctx.costs_more(card, s))
    if spirits:
        (spirit,) = yield ctx.choose(f"Exorcist: gain a Spirit costing less than {card}.", spirits)
        ctx.gain_from_offsupply(spirit)


def _faithful_hound(ctx):
    ctx.draw(2)


def _fool(ctx):
    if ctx.lost_in_woods_holder == ctx.player:
        ctx.log("Fool does nothing: you already have Lost in the Woods.")
        return
    ctx.take_lost_in_woods()
    boons = [b for b in (ctx.draw_boon() for _ in range(3)) if b]
    if boons:
        ctx.log(f"{ctx.player_name} takes {', '.join(boons)}.", "boon")
    while boons:
        if len(set(boons)) == 1:
            boon = boons.pop()
        else:
            (boon,) = yield ctx.choose("Fool: choose the next Boon to receive.", tuple(boons))
            boons.remove(boon)
        yield from ctx.receive_boon(boon)


def _ghost_town(ctx):
    ctx.add_duration(_ghost_town_start)


def _ghost_town_start(ctx, entry):
    ctx.draw(1)
    ctx.add_actions(1)


def _guardian(ctx):
    ctx.add_duration(_guardian_start)
    ctx.log(f"{ctx.player_name} is protected from Attacks until their next turn.", "reveal")


def _guardian_start(ctx, entry):
    ctx.add_coins(1)


def _idol(ctx):
    if ctx.in_play.count("Idol") % 2 == 1:
        yield from ctx.receive_boon()
    else:
        targets = yield from ctx.attack()
        for p in targets:
            ctx.gain("Curse", p)


def _leprechaun(ctx):
    ctx.gain("Gold")
    if len(ctx.in_play) == 7:
        ctx.gain_from_offsupply("Wish")
    else:
        yield from ctx.receive_hex()


def _monastery(ctx):
    n = len(ctx.gained_this_turn())
    for left in range(n, 0, -1):
        options = tuple(sorted(set(ctx.hand))) + (("Copper (in play)",) if "Copper" in ctx.in_play else ())
        if not options:
            return
        chosen = yield ctx.choose(f"Monastery: you may trash a card from your hand or a Copper you have in play ({left} left).", options, 0, 1)
        if not chosen:
            return
        if chosen[0] == "Copper (in play)":
            ctx.trash_in_play("Copper")
        else:
            ctx.trash(chosen[0])


def _necromancer(ctx):
    options = ctx.trash_actions_for_necromancer()
    if not options:
        ctx.log("Necromancer: there is no Action card in the trash to play.")
        return
    (card,) = yield ctx.choose("Necromancer: play a non-Duration Action card from the trash (it stays there, face down for the turn).", options)
    yield from ctx.play_from_trash(card)


def _night_watchman(ctx):
    cards = ctx.take_to_set_aside(5)
    if not cards:
        return
    chosen = yield ctx.choose(f"Night Watchman: the top {len(cards)} cards of your deck. Discard any number; the rest go back in any order.",
                              tuple(cards), 0, len(cards))
    rest = list(cards)
    for card in chosen:
        rest.remove(card)
        ctx.discard_set_aside(card)
    yield from _put_back_in_any_order(ctx, rest)


def _pixie(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    boon = ctx.draw_boon()
    if boon is None:
        return
    chosen = ()
    if ctx.source in ctx.in_play:
        chosen = yield ctx.choose(f"Pixie: the top Boon is {boon} ({BOONS[boon]}) You may trash Pixie to receive it twice.",
                                  ("Trash Pixie to receive it twice",), 0, 1)
    if chosen and ctx.trash_self():
        for _ in range(2):
            yield from ctx.receive_boon(boon, dispose=False)
        ctx.discard_boon(boon)
    else:
        ctx.discard_boon(boon, received=False)


def _pooka(ctx):
    options = tuple(sorted({c for c in ctx.hand if ctx.is_treasure(c) and c != "Cursed Gold"}))
    if not options:
        return
    chosen = yield ctx.choose("Pooka: you may trash a Treasure other than Cursed Gold from your hand, for +4 Cards.", options, 0, 1)
    if chosen:
        ctx.trash(chosen[0])
        ctx.draw(4)


def _raider(ctx):
    targets = yield from ctx.attack()
    mine = set(ctx.in_play)
    for p in targets:
        hand = ctx.hand_of(p)
        if len(hand) < 5:
            continue
        options = tuple(sorted(set(hand) & mine))
        if options:
            (card,) = yield ctx.choose(f"Raider: discard a copy of a card {ctx.player_name} has in play.", options, player=p)
            ctx.discard(card, player=p)
        else:
            ctx.log(f"{ctx.name_of(p)} reveals their hand: no copy of a card in play.", "reveal")
    ctx.add_duration(_raider_start)


def _raider_start(ctx, entry):
    ctx.add_coins(3)


def _sacred_grove(ctx):
    ctx.add_buys(1)
    ctx.add_coins(3)
    boon = yield from ctx.receive_boon()
    if boon is None or boon in ("The Field's Gift", "The Forest's Gift"):
        return
    for p in ctx.other_players():
        chosen = yield ctx.choose(f"{ctx.player_name}'s Sacred Grove gave them {boon} ({BOONS[boon]}) You may receive it too.",
                                  (f"Receive {boon}",), 0, 1, player=p)
        if chosen:
            yield from ctx.receive_boon(boon, receiver=p, dispose=False)


def _secret_cave(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    hand = ctx.hand
    if not hand:
        return
    n = min(3, len(hand))
    chosen = yield ctx.choose("Secret Cave: you may discard 3 cards. If you do, +$3 at the start of your next turn.",
                              ("Discard 3 cards" if n == 3 else f"Discard your {n} card(s)",), 0, 1)
    if not chosen:
        return
    picked = yield ctx.choose("Secret Cave: discard 3 cards.", hand, n, n)
    for card in picked:
        ctx.discard(card)
    if n == 3:
        ctx.add_duration(_secret_cave_start)


def _secret_cave_start(ctx, entry):
    ctx.add_coins(3)


def _shepherd(ctx):
    ctx.add_actions(1)
    victories = tuple(c for c in ctx.hand if ctx.is_victory(c))
    if not victories:
        return
    chosen = yield ctx.choose("Shepherd: discard any number of Victory cards, revealing them. +2 Cards per card discarded.", victories, 0, len(victories))
    for card in chosen:
        ctx.discard(card)
    if chosen:
        ctx.draw(2 * len(chosen))


def _skulk(ctx):
    ctx.add_buys(1)
    yield from _hex_others(ctx)


def _skulk_gain(ctx, event):
    ctx.gain("Gold")


def _tormentor(ctx):
    ctx.add_coins(2)
    others = len(ctx.in_play) - (1 if ctx.source in ctx.in_play else 0)
    if others == 0:
        ctx.gain_from_offsupply("Imp")
    else:
        yield from _hex_others(ctx)


def _tracker(ctx):
    ctx.add_coins(1)
    yield from ctx.receive_boon()


def _tracker_gain(ctx, event):
    if ctx.gained_card_present(event) and event.zone != "deck":
        chosen = yield ctx.choose(f"Tracker: you may put the gained {event.card} onto your deck.", ("Put it onto your deck",), 0, 1)
        if chosen:
            ctx.put_gained_on_deck(event)


def _tragic_hero(ctx):
    ctx.draw(3)
    ctx.add_buys(1)
    if len(ctx.hand) >= 8:
        ctx.trash_self()                      # (if it cannot be trashed any more you still gain the Treasure)
        options = ctx.supply_cards_of_type(T.TREASURE)
        if options:
            (card,) = yield ctx.choose("Tragic Hero: gain a Treasure.", options)
            ctx.gain(card)


def _vampire(ctx):
    yield from _hex_others(ctx)
    options = tuple(c for c in ctx.gainable(5) if c != "Vampire")
    if options:
        (card,) = yield ctx.choose("Vampire: gain a card costing up to $5 other than a Vampire.", options)
        ctx.gain(card)
    ctx.exchange_in_play_for("Vampire", "Bat")


def _werewolf(ctx):
    if ctx.in_night_phase:
        yield from _hex_others(ctx)
    else:
        ctx.draw(3)


K("Druid", 2, {T.ACTION, T.FATE}, _druid, "+1 Buy. Receive one of the set-aside Boons (leaving it there). Setup: set aside the top 3 Boons face up.")
K("Faithful Hound", 2, {T.ACTION, T.REACTION}, _faithful_hound, "+2 Cards. When you discard this other than during Clean-up, you may set it aside, and put it into your hand at end of turn.")
K("Guardian", 2, {T.NIGHT, T.DURATION}, _guardian, "This is gained to your hand (instead of your discard pile). Until your next turn, when another player plays an Attack card, it doesn't affect you. At the start of your next turn, +$1.", gains_to_hand=True)
K("Monastery", 2, {T.NIGHT}, _monastery, "For each card you've gained this turn, you may trash a card from your hand or a Copper you have in play.")
K("Pixie", 2, {T.ACTION, T.FATE}, _pixie, "+1 Card, +1 Action. Discard the top Boon. You may trash this to receive that Boon twice. Heirloom: Goat.", heirloom="Goat")
K("Tracker", 2, {T.ACTION, T.FATE}, _tracker, "+$1. Receive a Boon. While this is in play, when you gain a card, you may put that card onto your deck. Heirloom: Pouch.", heirloom="Pouch", on_gain_in_play=_tracker_gain)
K("Changeling", 3, {T.NIGHT}, _changeling, "Trash this. Gain a copy of a card you have in play. In games using this, when you gain a card costing $3 or more, you may exchange it for a Changeling.")
K("Fool", 3, {T.ACTION, T.FATE}, _fool, "If you aren't the player with Lost in the Woods, take it, take 3 Boons, and receive the Boons in any order. Heirloom: Lucky Coin.", heirloom="Lucky Coin")
K("Ghost Town", 3, {T.NIGHT, T.DURATION}, _ghost_town, "At the start of your next turn, +1 Card and +1 Action. This is gained to your hand (instead of your discard pile).", gains_to_hand=True)
K("Leprechaun", 3, {T.ACTION, T.DOOM}, _leprechaun, "Gain a Gold. If you have exactly 7 cards in play, gain a Wish from its pile. Otherwise, receive a Hex.")
K("Night Watchman", 3, {T.NIGHT}, _night_watchman, "Look at the top 5 cards of your deck, discard any number, and put the rest back in any order. This is gained to your hand (instead of your discard pile).", gains_to_hand=True)
K("Secret Cave", 3, {T.ACTION, T.DURATION}, _secret_cave, "+1 Card, +1 Action. You may discard 3 cards. If you did, then at the start of your next turn, +$3. Heirloom: Magic Lamp.", heirloom="Magic Lamp")
K("Bard", 4, {T.ACTION, T.FATE}, _bard, "+$2. Receive a Boon.")
K("Blessed Village", 4, {T.ACTION, T.FATE}, _blessed_village, "+1 Card, +2 Actions. When you gain this, take a Boon. Receive it now or at the start of your next turn.", on_gain=_blessed_village_gain)
register(CardDef("Cemetery", 4, frozenset({T.VICTORY}), vp=2, text="2 VP. When you gain this, trash up to 4 cards from your hand. Heirloom: Haunted Mirror.", kingdom=True,
                 expansion=SET, heirloom="Haunted Mirror", on_gain=_cemetery_gain))
K("Conclave", 4, {T.ACTION}, _conclave, "+$2. You may play an Action card from your hand that you don't have a copy of in play. If you do, +1 Action.")
K("Devil's Workshop", 4, {T.NIGHT}, _devils_workshop, "If the number of cards you've gained this turn is: 2 or more, gain an Imp from its pile; 1, gain a card costing up to $4; 0, gain a Gold.")
K("Exorcist", 4, {T.NIGHT}, _exorcist, "Trash a card from your hand. Gain a cheaper Spirit from one of the Spirit piles.")
K("Necromancer", 4, {T.ACTION}, _necromancer, "Play a face up, non-Duration Action card from the trash, leaving it there and turning it face down for the turn. Setup: put the 3 Zombies into the trash.")
K("Shepherd", 4, {T.ACTION}, _shepherd, "+1 Action. Discard any number of Victory cards, revealing them. +2 Cards per card discarded. Heirloom: Pasture.", heirloom="Pasture")
K("Skulk", 4, {T.ACTION, T.ATTACK, T.DOOM}, _skulk, "+1 Buy. Each other player receives the next Hex. When you gain this, gain a Gold.", on_gain=_skulk_gain)
K("Cobbler", 5, {T.NIGHT, T.DURATION}, _cobbler, "At the start of your next turn, gain a card to your hand costing up to $4.")
K("Crypt", 5, {T.NIGHT, T.DURATION}, _crypt, "Set aside any number of Treasures you have in play, face down (under this). While any remain, at the start of each of your turns, put one of them into your hand.")
K("Cursed Village", 5, {T.ACTION, T.DOOM}, _cursed_village, "+2 Actions. Draw until you have 6 cards in hand. When you gain this, receive a Hex.", on_gain=_cursed_village_gain)
K("Den of Sin", 5, {T.NIGHT, T.DURATION}, _den_of_sin, "At the start of your next turn, +2 Cards. This is gained to your hand (instead of your discard pile).", gains_to_hand=True)
register(CardDef("Idol", 5, frozenset({T.TREASURE, T.ATTACK, T.FATE}), coins=2, on_play=_idol, kingdom=True, expansion=SET,
                 text="$2. When you play this, if you then have an odd number of Idols in play, receive a Boon; if an even number, each other player gains a Curse."))
K("Pooka", 5, {T.ACTION}, _pooka, "You may trash a Treasure other than Cursed Gold from your hand, for +4 Cards. Heirloom: Cursed Gold.", heirloom="Cursed Gold")
K("Sacred Grove", 5, {T.ACTION, T.FATE}, _sacred_grove, "+1 Buy, +$3. Receive a Boon. If it doesn't give +$1, each other player may receive it.")
K("Tormentor", 5, {T.ACTION, T.ATTACK, T.DOOM}, _tormentor, "+$2. If you have no other cards in play, gain an Imp from its pile. Otherwise, each other player receives the next Hex.")
K("Tragic Hero", 5, {T.ACTION}, _tragic_hero, "+3 Cards, +1 Buy. If you have 8 or more cards in hand (after drawing), trash this and gain a Treasure.")
K("Vampire", 5, {T.NIGHT, T.ATTACK, T.DOOM}, _vampire, "Each other player receives the next Hex. Gain a card costing up to $5 other than a Vampire. Exchange this for a Bat.")
K("Werewolf", 5, {T.ACTION, T.NIGHT, T.ATTACK, T.DOOM}, _werewolf, "If it's your Night phase, each other player receives the next Hex. Otherwise, +3 Cards.")
K("Raider", 6, {T.NIGHT, T.DURATION, T.ATTACK}, _raider, "Each other player with 5 or more cards in hand discards a copy of a card you have in play (or reveals they can't). At the start of your next turn, +$3.")


# ---------------------------------------------------------------- Heirlooms
def _lucky_coin(ctx):
    ctx.gain("Silver")


def _cursed_gold(ctx):
    ctx.gain("Curse")


def _goat(ctx):
    if ctx.hand:
        chosen = yield ctx.choose("Goat: you may trash a card from your hand.", tuple(sorted(set(ctx.hand))), 0, 1)
        if chosen:
            ctx.trash(chosen[0])


def _magic_lamp(ctx):
    if sum(1 for n in Counter(ctx.in_play).values() if n == 1) >= 6 and ctx.trash_in_play("Magic Lamp"):
        for _ in range(3):
            ctx.gain_from_offsupply("Wish")


def _pouch(ctx):
    ctx.add_buys(1)


def _haunted_mirror_trash(ctx, event):
    options = tuple(sorted({c for c in ctx.hand if ctx.is_action(c)}))
    if not options or "Ghost" not in ctx.offsupply_names():
        return
    chosen = yield ctx.choose("Haunted Mirror: you may discard an Action card to gain a Ghost.", options, 0, 1)
    if chosen:
        ctx.discard(chosen[0])
        ctx.gain_from_offsupply("Ghost")


def _heirloom(name, cost, coins, text, fn=None, extra=(), **kw):
    return register(CardDef(name, cost, frozenset({T.TREASURE, T.HEIRLOOM, *extra}), coins=coins, on_play=fn, text=text, kingdom=False, expansion=SET, **kw))


_heirloom("Haunted Mirror", 0, 1, "$1. When you trash this, you may discard an Action card, to gain a Ghost.", on_trash=_haunted_mirror_trash)
_heirloom("Magic Lamp", 0, 1, "$1. When you play this, if there are at least 6 cards that you have exactly 1 copy of in play, trash this. If you do, gain 3 Wishes from their pile.", _magic_lamp)
_heirloom("Goat", 2, 1, "$1. When you play this, you may trash a card from your hand.", _goat)
_heirloom("Pasture", 2, 1, "$1. Worth 1 VP per Estate you have.", None, extra=(T.VICTORY,), score_fn=lambda cards: sum(1 for c in cards if c == "Estate"))
_heirloom("Pouch", 2, 1, "$1. +1 Buy.", _pouch)
_heirloom("Cursed Gold", 4, 3, "$3. When you play this, gain a Curse.", _cursed_gold)
_heirloom("Lucky Coin", 4, 1, "$1. When you play this, gain a Silver.", _lucky_coin)




# ---------------------------------------------------------------- Spirits, Bat, Wish, Zombies
def _will_o_wisp(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    top = ctx.top_of_deck()
    if top is None:
        return
    ctx.log(f"{ctx.player_name} reveals {top}.", "reveal")
    if _exact_cost(ctx, top, 0, 1, 2):
        ctx.draw(1, quiet=True)
        ctx.log(f"{ctx.player_name} puts {top} into their hand.")


def _imp(ctx):
    ctx.draw(2)
    yield from _play_new_action(ctx, "Imp: you may play an Action card from your hand that you don't have a copy of in play.")


def _ghost(ctx):
    revealed, found = [], None
    while True:
        cards = ctx.take_to_set_aside(1, reveal=True)
        if not cards:
            break
        if ctx.is_action(cards[0]):
            found = cards[0]
            break
        revealed.append(cards[0])
    for card in revealed:                                  # (the revealed cards are only discarded at the end, so they are not reshuffled)
        ctx.discard_set_aside(card)
    if found is None:
        ctx.log("Ghost: no Action card was found.")
        return
    ctx.put_on_mat(found, "ghosted", source="set_aside")
    ctx.add_duration(_ghost_start, found)


def _ghost_start(ctx, entry):
    card = entry.data
    if card not in ctx.mat_cards("ghosted"):
        return
    ctx.put_in_play(card, zone="ghosted")
    yield from ctx.resolve(card)
    yield from ctx.resolve(card)


def _bat(ctx):
    if not ctx.hand:
        return
    chosen = yield ctx.choose("Bat: trash up to 2 cards from your hand. If you trashed at least one, exchange this for a Vampire.",
                              ctx.hand, 0, min(2, len(ctx.hand)))
    for card in chosen:
        ctx.trash(card)
    if chosen:
        ctx.exchange_in_play_for("Bat", "Vampire")


def _wish(ctx):
    ctx.add_actions(1)
    if ctx.return_in_play_to_offsupply("Wish"):
        yield from _gain_up_to(ctx, "Wish: gain a card to your hand costing up to $6.", 6, destination="hand")


def _zombie_apprentice(ctx):
    options = tuple(sorted({c for c in ctx.hand if ctx.is_action(c)}))
    if not options:
        return
    chosen = yield ctx.choose("Zombie Apprentice: you may trash an Action card from your hand for +3 Cards and +1 Action.", options, 0, 1)
    if chosen:
        ctx.trash(chosen[0])
        ctx.draw(3)
        ctx.add_actions(1)


def _zombie_mason(ctx):
    card = ctx.trash_top_of_deck()
    if card is None:
        return
    yield from _gain_up_to(ctx, f"Zombie Mason: you may gain a card costing up to $1 more than {card}.", ctx.cost_of(card) + 1)


def _zombie_spy(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    top = ctx.top_of_deck()
    if top is None:
        return
    (mode,) = yield ctx.choose(f"Zombie Spy: the top card of your deck is {top}. Discard it, or put it back?", ("Discard it", "Put it back"))
    if mode == "Discard it":
        ctx.discard_top_of_deck()


X("Will-o'-Wisp", 0, {T.ACTION, T.SPIRIT}, _will_o_wisp, "+1 Card, +1 Action. Reveal the top card of your deck. If it costs $2 or less, put it into your hand. (This is not in the Supply.)")
X("Imp", 2, {T.ACTION, T.SPIRIT}, _imp, "+2 Cards. You may play an Action card from your hand that you don't have a copy of in play. (This is not in the Supply.)")
X("Ghost", 4, {T.NIGHT, T.DURATION, T.SPIRIT}, _ghost, "Reveal cards from your deck until you reveal an Action. Discard the other cards and set aside the Action. At the start of your next turn, play it twice. (This is not in the Supply.)")
X("Bat", 2, {T.NIGHT}, _bat, "Trash up to 2 cards from your hand. If you trashed at least one, exchange this for a Vampire. (This is not in the Supply.)")
X("Wish", 0, {T.ACTION}, _wish, "+1 Action. Return this to its pile. If you did, gain a card to your hand costing up to $6. (This is not in the Supply.)")
X("Zombie Apprentice", 3, {T.ACTION, T.ZOMBIE}, _zombie_apprentice, "You may trash an Action card from your hand for +3 Cards and +1 Action. (Starts in the trash; only Necromancer can play it.)")
X("Zombie Mason", 3, {T.ACTION, T.ZOMBIE}, _zombie_mason, "Trash the top card of your deck. You may gain a card costing up to $1 more than it. (Starts in the trash; only Necromancer can play it.)")
X("Zombie Spy", 3, {T.ACTION, T.ZOMBIE}, _zombie_spy, "+1 Card, +1 Action. Look at the top card of your deck. Discard it or put it back. (Starts in the trash; only Necromancer can play it.)")
