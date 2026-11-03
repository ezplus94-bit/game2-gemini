"""The Allies expansion (2022): 25 Kingdom piles, 6 split piles of 4 cards (16 cards each), 23 Allies, Favors and Liaisons.

  * Favors (``PlayerState.favors``): every player starts with 1 when an Ally is in the game (5 with Importer). Liaison cards give them out.
  * An Ally (``CardType.ALLY``, ``GameState.ally``) is picked at random when a Liaison is in the Kingdom (or set with ``GameConfig.ally``).
    What each one does is in ``engine/allies.py`` (the time it triggers) -- the card list here only has the texts.
  * Split piles (Augurs, Clashes, Forts, Odysseys, Townsfolk, Wizards): like the Castles, a placeholder card is the Kingdom card and the pile is
    ``GameState.stacks[pile]``: 4 copies each of 4 cards, only the top one can be gained or bought. "Rotate" moves the top card (and its
    copies) to the bottom (``EffectContext.rotate_pile``).
  * Elder and "choose one": cards here use ``EffectContext.choose_modes`` so Elder can give them an extra option. Older cards from other sets that
    say "choose" do not (see the README).

Known simplifications: Warlord's restriction is checked when an Action is played from the hand directly (not for cards like Throne Room
that play one); gaining a card with an effect that "gains" and then moves it (Hill Fort) moves it before the on-gain effects run.
"""

from __future__ import annotations

from .base import CardDef, CardType, victory
from .registry import get_card, register

SET = "Allies"
T = CardType


def K(name, cost, types, fn, text, kingdom=True, **kw):
    return register(CardDef(name, cost, frozenset(types), on_play=fn, text=text, kingdom=kingdom, expansion=SET, **kw))


def _hand_names(ctx, test=None) -> tuple:
    return tuple(sorted({c for c in ctx.hand if test is None or test(c)}))


def _delayed_play(ctx, entry):
    """Royal Galley, Contract: the card set aside is played at the start of the turn (no Action is used)."""
    card = entry.data
    if card in ctx.mat_cards("delayed"):
        ctx.put_in_play(card, "delayed")
        yield from ctx.resolve(card)


def _play_from_hand(ctx, card: str):
    ctx.put_in_play(card)
    if ctx.is_action(card):
        yield from ctx.resolve(card)
    else:
        yield from ctx.resolve_treasure(card)


# ================================================================ single Kingdom piles
def _barbarian(ctx):
    ctx.add_coins(2)
    targets = yield from ctx.attack()
    for p in targets:
        card = ctx.trash_top_of_deck(player=p)
        if card is None:
            continue
        cost = ctx.cost_of(card)
        if cost >= 3:
            mine = set(ctx.card_types(card))
            options = tuple(n for n in ctx.gainable(cost - 1, gainer=p) if mine & set(ctx.card_types(n)))
            if options:
                (new,) = yield ctx.choose(f"Barbarian: gain a cheaper card that shares a type with the trashed {card}.", options, player=p)
                ctx.gain(new, player=p)
        else:
            ctx.gain("Curse", player=p)


BAUBLE = ("+1 Buy", "+$1", "+1 Favor", "This turn, when you gain a card, you may put it onto your deck")


def _bauble(ctx):
    picked = yield ctx.choose("Bauble: choose two different options.", BAUBLE, 2, 2)
    for option in BAUBLE:
        if option not in picked:
            continue
        if option == "+1 Buy":
            ctx.add_buys(1)
        elif option == "+$1":
            ctx.add_coins(1)
        elif option == "+1 Favor":
            ctx.add_favors(1)
        else:
            ctx.bump_count("Bauble")


def _broker(ctx):
    if not ctx.hand:
        return
    (card,) = yield ctx.choose("Broker: trash a card from your hand.", _hand_names(ctx))
    n = ctx.cost_of(card)
    ctx.trash(card)
    if n <= 0:
        return
    modes = (f"+{n} Card{'s' if n != 1 else ''}", f"+{n} Action{'s' if n != 1 else ''}", f"+${n}", f"+{n} Favor{'s' if n != 1 else ''}")
    picked = yield from ctx.choose_modes("Broker: choose one.", modes)
    for index, mode in enumerate(modes):
        if mode not in picked:
            continue
        if index == 0:
            ctx.draw(n)
        elif index == 1:
            ctx.add_actions(n)
        elif index == 2:
            ctx.add_coins(n)
        else:
            ctx.add_favors(n)


def _capital_city(ctx):
    ctx.draw(1)
    ctx.add_actions(2)
    if len(ctx.hand) >= 2:
        chosen = yield ctx.choose("Capital City: you may discard 2 cards for +$2.", ("Discard 2 cards",), 0, 1)
        if chosen:
            picks = yield ctx.choose("Capital City: discard 2 cards.", tuple(ctx.hand), 2, 2)
            for card in picks:
                ctx.discard(card)
            ctx.add_coins(2)
    if ctx.coins >= 2:
        chosen = yield ctx.choose("Capital City: you may pay $2 for +2 Cards.", ("Pay $2",), 0, 1)
        if chosen and ctx.pay_coins(2):
            ctx.draw(2)


def _carpenter(ctx):
    if ctx.empty_piles() == 0:
        ctx.add_actions(1)
        options = ctx.gainable(4)
        if options:
            (card,) = yield ctx.choose("Carpenter: gain a card costing up to $4.", options)
            ctx.gain(card)
    elif ctx.hand:
        (card,) = yield ctx.choose("Carpenter: trash a card from your hand.", _hand_names(ctx))
        cost = ctx.cost_of(card)
        ctx.trash(card)
        options = ctx.gainable(cost + 2)
        if options:
            (new,) = yield ctx.choose(f"Carpenter: gain a card costing up to ${cost + 2}.", options)
            ctx.gain(new)


def _contract(ctx):
    ctx.add_favors(1)
    options = _hand_names(ctx, ctx.is_action)
    if not options:
        return
    chosen = yield ctx.choose("Contract: you may set aside an Action from your hand to play it at the start of your next turn.", options, 0, 1)
    if chosen:
        ctx.set_aside_delayed(chosen[0])
        ctx.log(f"{ctx.player_name} sets {chosen[0]} aside with Contract.")
        ctx.add_duration(_delayed_play, chosen[0])


def _courier(ctx):
    ctx.add_coins(1)
    ctx.discard_top_of_deck()
    options = tuple(sorted({c for c in ctx.discard_pile if ctx.is_action(c) or ctx.is_treasure(c)}))
    if not options:
        return
    chosen = yield ctx.choose("Courier: you may play an Action or Treasure from your discard pile.", options, 0, 1)
    if chosen:
        card = chosen[0]
        if ctx.is_action(card):
            ctx.put_in_play(card, "discard")
            yield from ctx.resolve(card)
        else:
            yield from ctx.play_treasure(card, zone="discard")


def _emissary(ctx):
    before = ctx.shuffle_count()
    ctx.draw(3)
    if ctx.shuffle_count() > before:
        ctx.add_actions(1)
        ctx.add_favors(2)


def _galleria(ctx):
    ctx.add_coins(3)
    ctx.bump_count("Galleria")


def _guildmaster(ctx):
    ctx.add_coins(3)
    ctx.bump_count("Guildmaster")


def _highwayman(ctx):
    targets = yield from ctx.attack()
    for p in targets:
        ctx.add_ally_pair("highwayman", p)
    ctx.add_duration(_highwayman_start)


def _highwayman_start(ctx, entry):
    ctx.discard_from_play("Highwayman")
    ctx.draw(3)


def _hunter(ctx):
    ctx.add_actions(1)
    cards = ctx.take_to_set_aside(3, reveal=True)
    for label, test in (("an Action", ctx.is_action), ("a Treasure", ctx.is_treasure), ("a Victory card", lambda c: "victory" in ctx.card_types(c))):
        options = tuple(sorted({c for c in cards if test(c)}))
        if options:
            (card,) = yield ctx.choose(f"Hunter: put {label} into your hand.", options)
            cards.remove(card)
            ctx.set_aside_to_hand(card)
    for card in cards:
        ctx.discard_set_aside(card)


def _importer(ctx):
    ctx.add_duration(_importer_start)


def _importer_start(ctx, entry):
    options = ctx.gainable(5)
    if options:
        (card,) = yield ctx.choose("Importer: gain a card costing up to $5.", options)
        ctx.gain(card)


def _innkeeper(ctx):
    ctx.add_actions(1)
    modes = ("+1 Card", "+3 Cards, discard 3 cards", "+5 Cards, discard 6 cards")
    picked = yield from ctx.choose_modes("Innkeeper: choose one.", modes)
    for mode in modes:
        if mode not in picked:
            continue
        n = {"+1 Card": 1, modes[1]: 3, modes[2]: 5}[mode]
        ctx.draw(n)
        gone = 0 if mode == "+1 Card" else (3 if n == 3 else 6)
        gone = min(gone, len(ctx.hand))
        if gone:
            chosen = yield ctx.choose(f"Innkeeper: discard {gone} card{'s' if gone != 1 else ''}.", tuple(ctx.hand), gone, gone)
            for card in chosen:
                ctx.discard(card)


def _marquis(ctx):
    ctx.add_buys(1)
    ctx.draw(len(ctx.hand))
    extra = len(ctx.hand) - 10
    if extra > 0:
        chosen = yield ctx.choose("Marquis: discard down to 10 cards in hand.", tuple(ctx.hand), extra, extra)
        for card in chosen:
            ctx.discard(card)


def _merchant_camp(ctx):
    ctx.add_actions(2)
    ctx.add_coins(1)


def _put_on_deck_cleanup(name: str):
    def cleanup(ctx):
        chosen = yield ctx.choose(f"{name}: you may put this onto your deck.", (name,), 0, 1)
        if chosen:
            ctx.put_in_play_on_deck(name)
    cleanup.__name__ = f"_cleanup_{name.replace(' ', '_')}"
    return cleanup


def _modify(ctx):
    cost = None
    if ctx.hand:
        (card,) = yield ctx.choose("Modify: trash a card from your hand.", _hand_names(ctx))
        cost = ctx.cost_of(card)
        ctx.trash(card)
    modes = ("+1 Card and +1 Action", "Gain a card costing up to $2 more than the trashed card")
    picked = yield from ctx.choose_modes("Modify: choose one.", modes if cost is not None else modes[:1])
    for mode in picked:
        if mode == modes[0]:
            ctx.draw(1)
            ctx.add_actions(1)
        else:
            options = ctx.gainable(cost + 2)
            if options:
                (new,) = yield ctx.choose(f"Modify: gain a card costing up to ${cost + 2}.", options)
                ctx.gain(new)


def _royal_galley(ctx):
    ctx.draw(1)
    options = _hand_names(ctx, lambda c: ctx.is_action(c) and "duration" not in ctx.card_types(c))
    if not options:
        return
    chosen = yield ctx.choose("Royal Galley: you may play a non-Duration Action card from your hand.", options, 0, 1)
    if not chosen:
        return
    card = chosen[0]
    ctx.put_in_play(card)
    yield from ctx.resolve(card)
    if card in ctx.in_play:
        ctx.set_aside_delayed(card, "in_play")
        ctx.log(f"{ctx.player_name} sets {card} aside with Royal Galley; it will be played again next turn.")
        ctx.add_duration(_delayed_play, card)


def _sentinel(ctx):
    cards = ctx.take_to_set_aside(5)
    ctx.log(f"{ctx.player_name} looks at the top {len(cards)} cards of their deck.")
    if not cards:
        return
    chosen = yield ctx.choose(f"Sentinel: you looked at {', '.join(cards)}. Trash up to 2 of them.", tuple(cards), 0, min(2, len(cards)))
    for card in chosen:
        ctx.trash_set_aside(card)
        cards.remove(card)
    yield from ctx.put_back_in_order(cards, "Sentinel: put the rest back (choose the top card first).")


def _skirmisher(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.add_coins(1)
    targets = yield from ctx.attack()
    for p in targets:
        ctx.add_ally_pair("skirmisher", p)


def _specialist(ctx):
    options = _hand_names(ctx, lambda c: ctx.is_action(c) or ctx.is_treasure(c))
    if not options:
        return
    chosen = yield ctx.choose("Specialist: you may play an Action or Treasure from your hand.", options, 0, 1)
    if not chosen:
        return
    card = chosen[0]
    yield from _play_from_hand(ctx, card)
    modes = ("Play it again", f"Gain a copy of {card}")
    picked = yield from ctx.choose_modes("Specialist: choose one.", modes)
    for mode in picked:
        if mode == modes[0]:
            if ctx.is_action(card):
                yield from ctx.resolve(card)
            else:
                yield from ctx.resolve_treasure(card)
        elif card in ctx.exilable_supply():
            ctx.gain(card)


def _swap(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    options = tuple(c for c in _hand_names(ctx, ctx.is_action) if ctx.supply_count(c) >= 0 and c in ctx.supply_names())
    if not options:
        return
    chosen = yield ctx.choose("Swap: you may return an Action card from your hand to its pile.", options, 0, 1)
    if not chosen or not ctx.return_hand_card_to_pile(chosen[0]):
        return
    gains = tuple(n for n in ctx.gainable(5, CardType.ACTION) if n != chosen[0])
    if gains:
        (new,) = yield ctx.choose("Swap: gain a different Action card costing up to $5 to your hand.", gains)
        ctx.gain(new, destination="hand")


def _sycophant(ctx):
    ctx.add_actions(1)
    k = min(3, len(ctx.hand))
    if k:
        chosen = yield ctx.choose("Sycophant: discard 3 cards.", tuple(ctx.hand), k, k)
        for card in chosen:
            ctx.discard(card)
        ctx.add_coins(3)


def _sycophant_favors(ctx, event):
    ctx.add_favors(2)


def _town(ctx):
    modes = ("+1 Card and +2 Actions", "+1 Buy and +$2")
    picked = yield from ctx.choose_modes("Town: choose one.", modes)
    for mode in picked:
        if mode == modes[0]:
            ctx.draw(1)
            ctx.add_actions(2)
        else:
            ctx.add_buys(1)
            ctx.add_coins(2)


def _underling(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.add_favors(1)


register(CardDef("Bauble", 2, frozenset({T.TREASURE, T.LIAISON}), coins=0, on_play=_bauble, kingdom=True, expansion=SET,
                 text="Choose two different options: +1 Buy; +$1; +1 Favor; this turn, when you gain a card, you may put it onto your deck."))
register(CardDef("Contract", 5, frozenset({T.TREASURE, T.DURATION, T.LIAISON}), coins=2, on_play=_contract, kingdom=True, expansion=SET,
                 text="$2. +1 Favor. You may set aside an Action from your hand to play it at the start of your next turn."))
K("Sycophant", 2, {T.ACTION, T.LIAISON}, _sycophant, "+1 Action. Discard 3 cards. If you discarded at least one, +$3. | When you gain or trash this, +2 Favors.",
  on_gain=_sycophant_favors, on_trash=_sycophant_favors)
K("Importer", 3, {T.ACTION, T.DURATION, T.LIAISON}, _importer, "At the start of your next turn, gain a card costing up to $5. | Setup: Each player gets +4 Favors.")
K("Merchant Camp", 3, {T.ACTION}, _merchant_camp, "+2 Actions, +$1. When you discard this from play, you may put it onto your deck.", on_cleanup=_put_on_deck_cleanup("Merchant Camp"))
K("Sentinel", 3, {T.ACTION}, _sentinel, "Look at the top 5 cards of your deck. Trash up to 2 of them. Put the rest back in any order.")
K("Underling", 3, {T.ACTION, T.LIAISON}, _underling, "+1 Card, +1 Action, +1 Favor.")
K("Broker", 4, {T.ACTION, T.LIAISON}, _broker, "Trash a card from your hand and choose one: +1 Card per $1 it costs; or +1 Action per $1 it costs; or +$1 per $1 it costs; or +1 Favor per $1 it costs.")
K("Carpenter", 4, {T.ACTION}, _carpenter, "If no Supply piles are empty, +1 Action and gain a card costing up to $4. Otherwise, trash a card from your hand and gain a card costing up to $2 more than it.")
K("Courier", 4, {T.ACTION}, _courier, "+$1. Discard the top card of your deck. Look through your discard pile; you may play an Action or Treasure from it.")
K("Innkeeper", 4, {T.ACTION}, _innkeeper, "+1 Action. Choose one: +1 Card; or +3 Cards, discard 3 cards; or +5 Cards, discard 6 cards.")
K("Royal Galley", 4, {T.ACTION, T.DURATION}, _royal_galley, "+1 Card. You may play a non-Duration Action card from your hand. Set it aside; if you did, at the start of your next turn play it.")
K("Town", 4, {T.ACTION}, _town, "Choose one: +1 Card and +2 Actions; or +1 Buy and +$2.")
K("Barbarian", 5, {T.ACTION, T.ATTACK}, _barbarian, "+$2. Each other player trashes the top card of their deck. If it costs $3 or more they gain a cheaper card that shares a type with it; otherwise they gain a Curse.")
K("Capital City", 5, {T.ACTION}, _capital_city, "+1 Card, +2 Actions. You may discard 2 cards for +$2. You may pay $2 for +2 Cards.")
K("Emissary", 5, {T.ACTION, T.LIAISON}, _emissary, "+3 Cards. If this made you shuffle (at least one card), +1 Action and +2 Favors.")
K("Galleria", 5, {T.ACTION}, _galleria, "+$3. This turn, when you gain a card costing $3 or $4, +1 Buy.")
K("Guildmaster", 5, {T.ACTION, T.LIAISON}, _guildmaster, "+$3. This turn, when you gain a card, +1 Favor.")
K("Highwayman", 5, {T.ACTION, T.DURATION, T.ATTACK}, _highwayman, "At the start of your next turn, discard this from play and +3 Cards. Until then, the first Treasure each other player plays each turn does nothing.")
K("Hunter", 5, {T.ACTION}, _hunter, "+1 Action. Reveal the top 3 cards of your deck. From those cards, put an Action, a Treasure, and a Victory card into your hand. Discard the rest.")
K("Modify", 5, {T.ACTION}, _modify, "Trash a card from your hand. Choose one: +1 Card and +1 Action; or gain a card costing up to $2 more than the trashed card.")
K("Skirmisher", 5, {T.ACTION, T.ATTACK}, _skirmisher, "+1 Card, +1 Action, +$1. This turn, when you gain an Attack card, each other player discards down to 3 cards in hand.")
K("Specialist", 5, {T.ACTION}, _specialist, "You may play an Action or Treasure from your hand. Choose one: play it again; or gain a copy of it.")
K("Swap", 5, {T.ACTION}, _swap, "+1 Card, +1 Action. You may return an Action card from your hand to its pile, to gain to your hand a different Action card costing up to $5.")
K("Marquis", 6, {T.ACTION}, _marquis, "+1 Buy. +1 Card per card in your hand. Discard down to 10 cards in hand.")


# ================================================================ split piles (member cards are not Kingdom cards on their own)
def _rotate_option(ctx, pile: str, label: str = None):
    chosen = yield ctx.choose(f"You may rotate the {pile}.", (f"Rotate the {pile}",), 0, 1)
    if chosen:
        ctx.rotate_pile(pile)


# -- Augurs
def _herb_gatherer(ctx):
    ctx.add_buys(1)
    ctx.deck_to_discard()
    options = tuple(sorted({c for c in ctx.discard_pile if ctx.is_treasure(c)}))
    if options:
        chosen = yield ctx.choose("Herb Gatherer: you may play a Treasure from your discard pile.", options, 0, 1)
        if chosen:
            yield from ctx.play_treasure(chosen[0], zone="discard")
    yield from _rotate_option(ctx, "Augurs")


def _acolyte(ctx):
    options = _hand_names(ctx, lambda c: ctx.is_action(c) or "victory" in ctx.card_types(c))
    if options:
        chosen = yield ctx.choose("Acolyte: you may trash an Action or Victory card from your hand to gain a Gold.", options, 0, 1)
        if chosen:
            ctx.trash(chosen[0])
            ctx.gain("Gold")
    if ctx.source in ctx.in_play and ctx.pile_top("Augurs") is not None:
        chosen = yield ctx.choose("Acolyte: you may trash this to gain an Augur.", ("Trash Acolyte",), 0, 1)
        if chosen and ctx.trash_self():
            ctx.gain_top("Augurs")


def _sorceress(ctx):
    ctx.add_actions(1)
    targets = yield from ctx.attack()
    names = tuple(sorted(set(ctx.supply_names()) | set(ctx.owned(ctx.player))))
    (named,) = yield ctx.choose("Sorceress: name a card.", names)
    ctx.log(f"{ctx.player_name} names {named}.")
    cards = ctx.take_to_set_aside(1, reveal=True)
    if cards:
        ctx.set_aside_to_hand(cards[0])
        if cards[0] == named:
            for p in targets:
                ctx.gain("Curse", player=p)


def _sibyl(ctx):
    ctx.draw(4)
    ctx.add_actions(1)
    if ctx.hand:
        (top,) = yield ctx.choose("Sibyl: put a card from your hand on top of your deck.", _hand_names(ctx))
        ctx.put_hand_on_deck(top)
    if ctx.hand:
        (bottom,) = yield ctx.choose("Sibyl: put another card from your hand on the bottom of your deck.", _hand_names(ctx))
        ctx.put_hand_under_deck(bottom)


# -- Clashes
def _battle_plan(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    attacks = _hand_names(ctx, lambda c: "attack" in ctx.card_types(c))
    if attacks:
        chosen = yield ctx.choose("Battle Plan: you may reveal an Attack card from your hand for +1 Card.", attacks, 0, 1)
        if chosen:
            ctx.log(f"{ctx.player_name} reveals {chosen[0]}.")
            ctx.draw(1)
    piles = ctx.rotatable_piles()
    if piles:
        chosen = yield ctx.choose("Battle Plan: you may rotate any Supply pile.", piles, 0, 1)
        if chosen:
            ctx.rotate_pile(chosen[0])


def _archer(ctx):
    ctx.add_coins(2)
    targets = yield from ctx.attack()
    for p in targets:
        hand = list(ctx.hand_of(p))
        if len(hand) < 5:
            continue
        (keep,) = yield ctx.choose("Archer: reveal all but one card of your hand (choose the one to keep hidden).", tuple(sorted(set(hand))), player=p)
        hand.remove(keep)
        ctx.log(f"{ctx.name_of(p)} reveals {', '.join(sorted(hand))}.")
        (gone,) = yield ctx.choose(f"Archer: choose a card of {ctx.name_of(p)}'s to discard.", tuple(sorted(set(hand))))
        ctx.discard(gone, player=p)


def _warlord(ctx):
    ctx.add_actions(1)
    targets = yield from ctx.attack()
    for p in targets:
        ctx.add_ally_pair("warlord", p)
    ctx.add_duration(_warlord_start)


def _warlord_start(ctx, entry):
    ctx.draw(2)


def _territory_score(cards) -> int:
    return len({c for c in cards if get_card(c).is_type(CardType.VICTORY)})


def _territory_gain(ctx, event):
    for _ in range(ctx.empty_piles()):
        ctx.gain("Gold")


def _noop(ctx):
    return None


# -- Forts
def _tent(ctx):
    ctx.add_coins(2)
    yield from _rotate_option(ctx, "Forts")


def _garrison(ctx):
    ctx.add_coins(2)
    ctx.arm_garrison()
    ctx.add_duration(_garrison_start)


def _garrison_start(ctx, entry):
    n = ctx.take_garrison_tokens()
    if n:
        ctx.log(f"{ctx.player_name} removes {n} token(s) from Garrison.")
        ctx.draw(n)


def _hill_fort(ctx):
    options = ctx.gainable(4)
    if not options:
        return
    (card,) = yield ctx.choose("Hill Fort: gain a card costing up to $4.", options)
    gained = ctx.gain(card)
    modes = ("Put it into your hand", "+1 Card and +1 Action")
    picked = yield from ctx.choose_modes("Hill Fort: choose one.", modes)
    for mode in picked:
        if mode == modes[0]:
            if gained and card in ctx.discard_pile:
                ctx.take_from_discard(card)
        else:
            ctx.draw(1)
            ctx.add_actions(1)


def _stronghold(ctx):
    modes = ("+$3", "At the start of your next turn, +3 Cards")
    picked = yield from ctx.choose_modes("Stronghold: choose one.", modes)
    for mode in picked:
        if mode == modes[0]:
            ctx.add_coins(3)
        else:
            ctx.add_duration(_stronghold_start)


def _stronghold_start(ctx, entry):
    ctx.draw(3)


# -- Odysseys
def _old_map(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    if ctx.hand:
        (card,) = yield ctx.choose("Old Map: discard a card.", _hand_names(ctx))
        ctx.discard(card)
    ctx.draw(1)
    yield from _rotate_option(ctx, "Odysseys")


def _voyage(ctx):
    ctx.add_actions(1)
    ctx.queue_own_extra_turn(voyage=True)
    ctx.add_duration(_voyage_start)


def _voyage_start(ctx, entry):
    return None


def _sunken_treasure(ctx):
    in_play = set(ctx.in_play)
    options = ctx.gainable_actions(without=in_play)
    if options:
        (card,) = yield ctx.choose("Sunken Treasure: gain an Action card you don't have a copy of in play.", options)
        ctx.gain(card)


def _distant_shore(ctx):
    ctx.draw(2)
    ctx.add_actions(1)
    ctx.gain("Estate")


# -- Townsfolk
def _town_crier(ctx):
    modes = ("+$2", "Gain a Silver", "+1 Card and +1 Action")
    picked = yield from ctx.choose_modes("Town Crier: choose one.", modes)
    for mode in picked:
        if mode == modes[0]:
            ctx.add_coins(2)
        elif mode == modes[1]:
            ctx.gain("Silver")
        else:
            ctx.draw(1)
            ctx.add_actions(1)
    yield from _rotate_option(ctx, "Townsfolk")


def _blacksmith(ctx):
    modes = ("Draw until you have 6 cards in hand", "+2 Cards", "+1 Card and +1 Action")
    picked = yield from ctx.choose_modes("Blacksmith: choose one.", modes)
    for mode in picked:
        if mode == modes[0]:
            n = 6 - len(ctx.hand)
            if n > 0:
                ctx.draw(n)
        elif mode == modes[1]:
            ctx.draw(2)
        else:
            ctx.draw(1)
            ctx.add_actions(1)
    yield from _rotate_option(ctx, "Townsfolk")


def _miller(ctx):
    ctx.add_actions(1)
    cards = ctx.take_to_set_aside(4)
    ctx.log(f"{ctx.player_name} looks at the top {len(cards)} cards of their deck.")
    if not cards:
        return
    (pick,) = yield ctx.choose(f"Miller: you looked at {', '.join(cards)}. Put one into your hand.", tuple(sorted(set(cards))))
    cards.remove(pick)
    ctx.set_aside_to_hand(pick)
    for card in cards:
        ctx.discard_set_aside(card)


def _elder(ctx):
    ctx.add_coins(2)
    options = _hand_names(ctx, ctx.is_action)
    if not options:
        return
    chosen = yield ctx.choose("Elder: you may play an Action card from your hand.", options, 0, 1)
    if chosen:
        card = chosen[0]
        ctx.put_in_play(card)
        ctx.push_elder(card)
        try:
            yield from ctx.resolve(card)
        finally:
            ctx.pop_elder(card)


# -- Wizards
def _student(ctx):
    ctx.add_actions(1)
    yield from _rotate_option(ctx, "Wizards")
    if ctx.hand:
        (card,) = yield ctx.choose("Student: trash a card from your hand.", _hand_names(ctx))
        treasure = ctx.is_treasure(card)
        ctx.trash(card)
        if treasure:
            ctx.add_favors(1)
            if ctx.source in ctx.in_play:
                ctx.put_in_play_on_deck(ctx.source)


def _conjurer(ctx):
    options = ctx.gainable(4)
    if options:
        (card,) = yield ctx.choose("Conjurer: gain a card costing up to $4.", options)
        ctx.gain(card)
    ctx.add_duration(_conjurer_start)


def _conjurer_start(ctx, entry):
    if "Conjurer" in ctx.in_play:
        ctx.take_in_play_to_hand("Conjurer")


def _sorcerer(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    targets = yield from ctx.attack()
    for p in targets:
        names = tuple(sorted(set(ctx.supply_names()) | set(ctx.owned(p))))
        (named,) = yield ctx.choose("Sorcerer: name a card.", names, player=p)
        cards = ctx.take_to_set_aside(1, player=p, reveal=True)
        if not cards:
            continue
        ctx.put_set_aside_on_deck(cards[0], player=p)
        if cards[0] != named:
            ctx.gain("Curse", player=p)


def _lich(ctx):
    ctx.draw(6)
    ctx.add_actions(2)
    ctx.skip_own_turn()


def _lich_trash(ctx, event):
    if not ctx.trash_to_discard("Lich"):
        return
    options = tuple(sorted({c for c in ctx.trash_pile() if ctx.cost_of(c) < ctx.cost_of("Lich") and not ctx.potion_cost_of(c)
                            and not get_card(c).debt_cost}))
    if options:
        (card,) = yield ctx.choose("Lich: gain a cheaper card from the trash.", options)
        ctx.gain_from_trash(card)


def _member(name, cost, types, fn, text, **kw):
    return K(name, cost, types, fn, text, kingdom=False, **kw)


_member("Herb Gatherer", 3, {T.ACTION, T.AUGUR}, _herb_gatherer, "+1 Buy. Put your deck into your discard pile. Look through it and you may play a Treasure from it. You may rotate the Augurs.")
_member("Acolyte", 4, {T.ACTION, T.AUGUR}, _acolyte, "You may trash an Action or Victory card from your hand to gain a Gold. You may trash this to gain an Augur.")
_member("Sorceress", 5, {T.ACTION, T.ATTACK, T.AUGUR}, _sorceress, "+1 Action. Name a card. Reveal the top card of your deck and put it into your hand. If it's the named card, each other player gains a Curse.")
_member("Sibyl", 6, {T.ACTION, T.AUGUR}, _sibyl, "+4 Cards, +1 Action. Put a card from your hand on top of your deck, and another on the bottom.")
_member("Battle Plan", 3, {T.ACTION, T.CLASH}, _battle_plan, "+1 Card, +1 Action. You may reveal an Attack card from your hand for +1 Card. You may rotate any Supply pile.")
_member("Archer", 4, {T.ACTION, T.ATTACK, T.CLASH}, _archer, "+$2. Each other player with 5 or more cards in hand reveals all but one, and discards one of those cards that you choose.")
_member("Warlord", 5, {T.ACTION, T.DURATION, T.ATTACK, T.CLASH}, _warlord,
        "+1 Action. At the start of your next turn, +2 Cards. Until then, other players can't play an Action from their hand that they have 2 or more copies of in play.")
register(CardDef("Territory", 6, frozenset({T.VICTORY, T.CLASH}), score_fn=_territory_score, on_gain=_territory_gain, kingdom=False, expansion=SET,
                 text="Worth 1 VP per differently named Victory card you have. | When you gain this, gain a Gold per empty Supply pile."))
_member("Tent", 3, {T.ACTION, T.FORT}, _tent, "+$2. You may rotate the Forts. When you discard this from play, you may put it onto your deck.", on_cleanup=_put_on_deck_cleanup("Tent"))
_member("Garrison", 4, {T.ACTION, T.DURATION, T.FORT}, _garrison, "+$2. This turn, when you gain a card, add a token here. At the start of your next turn, remove them for +1 Card each.")
_member("Hill Fort", 5, {T.ACTION, T.FORT}, _hill_fort, "Gain a card costing up to $4. Choose one: put it into your hand; or +1 Card and +1 Action.")
register(CardDef("Stronghold", 6, frozenset({T.ACTION, T.VICTORY, T.DURATION, T.FORT}), vp=2, on_play=_stronghold, kingdom=False, expansion=SET,
                 text="Choose one: +$3; or at the start of your next turn, +3 Cards. | 2 VP."))
_member("Old Map", 3, {T.ACTION, T.ODYSSEY}, _old_map, "+1 Card, +1 Action. Discard a card. +1 Card. You may rotate the Odysseys.")
_member("Voyage", 4, {T.ACTION, T.DURATION, T.ODYSSEY}, _voyage, "+1 Action. Take an extra turn after this one (but not a 3rd turn in a row), during which you can only play 3 cards from your hand.")
register(CardDef("Sunken Treasure", 5, frozenset({T.TREASURE, T.ODYSSEY}), coins=0, on_play=_sunken_treasure, kingdom=False, expansion=SET,
                 text="Gain an Action card you don't have a copy of in play."))
register(CardDef("Distant Shore", 6, frozenset({T.ACTION, T.VICTORY, T.ODYSSEY}), vp=2, on_play=_distant_shore, kingdom=False, expansion=SET,
                 text="+2 Cards, +1 Action. Gain an Estate. | 2 VP."))
_member("Town Crier", 2, {T.ACTION, T.TOWNSFOLK}, _town_crier, "Choose one: +$2; or gain a Silver; or +1 Card and +1 Action. You may rotate the Townsfolk.")
_member("Blacksmith", 3, {T.ACTION, T.TOWNSFOLK}, _blacksmith, "Choose one: draw until you have 6 cards in hand; or +2 Cards; or +1 Card and +1 Action. You may rotate the Townsfolk.")
_member("Miller", 4, {T.ACTION, T.TOWNSFOLK}, _miller, "+1 Action. Look at the top 4 cards of your deck. Put one into your hand and discard the rest.")
_member("Elder", 5, {T.ACTION, T.TOWNSFOLK}, _elder,
        "+$2. You may play an Action card from your hand. When it gives you a choice of abilities (e.g. \"choose one\") this turn, you may choose an extra (different) option.")
_member("Student", 3, {T.ACTION, T.WIZARD, T.LIAISON}, _student, "+1 Action. You may rotate the Wizards. Trash a card from your hand. If it's a Treasure, +1 Favor and put this onto your deck.")
_member("Conjurer", 4, {T.ACTION, T.DURATION, T.WIZARD}, _conjurer, "Gain a card costing up to $4. At the start of your next turn, put this into your hand.")
_member("Sorcerer", 5, {T.ACTION, T.ATTACK, T.WIZARD}, _sorcerer, "+1 Card, +1 Action. Each other player names a card, then reveals the top card of their deck. If wrong, they gain a Curse.")
_member("Lich", 6, {T.ACTION, T.WIZARD}, _lich, "+6 Cards, +2 Actions. Skip a turn. | When you trash this, discard it and gain a cheaper card from the trash.", on_trash=_lich_trash)


def _pile(name: str, cost: int, kind, members: str):
    return K(name, cost, {T.ACTION, kind}, _noop,
             f"This pile starts the game with 4 copies each of {members}, in that order. Only the top card can be gained or bought. (Rotating moves the top card, with its copies, to the bottom.)")


_pile("Townsfolk", 2, T.TOWNSFOLK, "Town Crier, Blacksmith, Miller, and Elder")
_pile("Augurs", 3, T.AUGUR, "Herb Gatherer, Acolyte, Sorceress, and Sibyl")
_pile("Clashes", 3, T.CLASH, "Battle Plan, Archer, Warlord, and Territory")
_pile("Forts", 3, T.FORT, "Tent, Garrison, Hill Fort, and Stronghold")
_pile("Odysseys", 3, T.ODYSSEY, "Old Map, Voyage, Sunken Treasure, and Distant Shore")
_pile("Wizards", 3, T.WIZARD, "Student, Conjurer, Sorcerer, and Lich")


# ================================================================ Allies (landscape cards; the engine side is engine/allies.py)
def _ally(name: str, text: str):
    return register(CardDef(name, 0, frozenset({T.ALLY}), kingdom=False, expansion=SET, text=text))


_ally("Architects' Guild", "When you gain a card, you may spend 2 Favors to gain a cheaper non-Victory card.")
_ally("Band of Nomads", "When you gain a card costing $5 or more, you may spend a Favor, for +1 Card, or +1 Action, or +1 Buy.")
_ally("Cave Dwellers", "At the start of your turn, you may spend a Favor, to discard a card then draw a card. Repeat as desired.")
_ally("Circle of Witches", "After playing a Liaison, you may spend 3 Favors to have each other player gain a Curse.")
_ally("City-state", "When you gain an Action card during your turn, you may spend 2 Favors to play it.")
_ally("Coastal Haven", "When discarding your hand in Clean-up, you may spend any number of Favors, to keep that many cards in hand for next turn (you still draw 5).")
_ally("Crafters' Guild", "At the start of your turn, you may spend 2 Favors to gain a card costing up to $4 onto your deck.")
_ally("Desert Guides", "At the start of your turn, you may spend a Favor, to discard your hand and draw 5 cards. Repeat as desired.")
_ally("Family of Inventors", "At the start of your Buy phase, you may spend a Favor, to put a Favor token on a non-Victory Supply pile (cards from that pile cost $1 less per Favor token on it).")
_ally("Fellowship of Scribes", "After playing an Action, if you have 4 or fewer cards in hand, you may spend a Favor for +1 Card.")
_ally("Forest Dwellers", "At the start of your turn, you may spend a Favor, to look at the top 3 cards of your deck. Discard any number of them and put the rest back in any order.")
_ally("Gang of Pickpockets", "At the start of your turn, discard down to 4 cards in hand unless you spend a Favor.")
_ally("Island Folk", "At the end of your turn, you may spend 5 Favors, to take an extra turn after this one (but not a 3rd turn in a row).")
_ally("League of Bankers", "At the start of your Buy phase, +$1 per 4 Favors you have (round down).")
_ally("League of Shopkeepers", "After playing a Liaison, if you have at least 5 Favors, +$1; at least 10, +1 Action and +1 Buy.")
_ally("Market Towns", "At the start of your Buy phase, you may spend a Favor, to play an Action card from your hand. Repeat as desired.")
_ally("Mountain Folk", "At the start of your turn, you may spend 5 Favors, for +3 Cards.")
_ally("Order of Astrologers", "When shuffling, you may pick one of the cards being shuffled per Favor you spend, to put on top of your deck.")
_ally("Order of Masons", "When shuffling, you may pick up to 2 of the cards being shuffled per Favor you spend, to put into your discard pile instead.")
_ally("Peaceful Cult", "At the start of your Buy phase, you may spend any number of Favors, to trash that many cards from your hand.")
_ally("Plateau Shepherds", "At the end of the game, pair up Favors with cards you have costing $2: 2 VP per pair.")
_ally("Trappers' Lodge", "When you gain a card, you may spend a Favor, to put it onto your deck.")
_ally("Woodworkers' Guild", "At the start of your Buy phase, you may spend a Favor, to trash an Action card from your hand. If you did, gain an Action card.")
