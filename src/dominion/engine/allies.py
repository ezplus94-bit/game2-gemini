"""Allies rules that live in the engine: what each Ally does when it triggers, and the shuffle pause for Order of Astrologers / Masons.

The cards (and the Allies themselves) are in ``cards/allies.py``. What is here:

  * Favors: ``PlayerState.favors``. Spending them is always optional and is a Decision asked at the moment an Ally triggers.
  * One function per time an Ally can trigger: the start of the turn, the start of the Buy phase, a gain, the end of the turn (Island Folk),
    Clean-up (Coastal Haven) and a shuffle (the two Orders; ``zones.take_top_cards`` stops the draw before the shuffle and queues it in
    ``GameState.star_draws`` with the marker ``"ally"``). "After playing" abilities are ``effects.ally_after_play``.
  * Standing effects of Kingdom cards: Guildmaster, Skirmisher and Garrison (a gain this turn), Highwayman and Warlord
    (``GameState.highwaymen`` / ``warlords``, until the owner's next turn), Voyage's three-card limit (``voyage_turn``, ``hand_plays``).
"""

from __future__ import annotations

import random

from ..cards import CardType, ally_cards, get_card
from .costs import card_cost, is_buried, is_walled
from .effects import EffectContext
from .state import GameState


def liaison_in_game(names) -> bool:
    return any(get_card(n).is_type(CardType.LIAISON) for n in names)


def pick_ally(requested, used, seed: int):
    """The Ally of this game: the requested one, or a random one (by the seed) when a Liaison is in the Kingdom."""
    if requested:
        if requested not in ally_cards():
            raise ValueError(f"Unknown Ally: {requested}")
        return requested
    if not liaison_in_game(used):
        return None
    return random.Random(seed ^ 0xA11E5).choice(ally_cards())


def start_of_turn(state: GameState, player: int) -> None:
    """The owner's next turn begins: their Highwaymen and Warlords stop."""
    state.highwaymen[:] = [(o, t) for o, t in state.highwaymen if o != player]
    state.warlords[:] = [(o, t) for o, t in state.warlords if o != player]


def _spend(ctx, n: int, prompt: str, label: str = None):
    """Generator returning True if the player chose to spend n Favors on this (and does it)."""
    if ctx.favors < n:
        return False
    chosen = yield ctx.choose(prompt, (label or f"Spend {n} Favor{'s' if n != 1 else ''}",), 0, 1)
    if not chosen:
        return False
    return ctx.spend_favors(n)


# ------------------------------------------------------------------ start of the turn
def start_of_turn_steps(state: GameState, player: int):
    ally = state.ally
    if ally is None or state.status.value != "active":
        return
    me = state.players[player]
    ctx = EffectContext(state, player, ally)
    if ally == "Cave Dwellers":
        while (yield from _spend(ctx, 1, "Cave Dwellers: you may spend a Favor to discard a card, then draw a card.")):
            if me.hand:
                (card,) = yield ctx.choose("Cave Dwellers: discard a card.", tuple(sorted(set(me.hand))))
                ctx.discard(card)
            ctx.draw(1)
    elif ally == "Crafters' Guild":
        options = ctx.gainable(4)
        if options and (yield from _spend(ctx, 2, "Crafters' Guild: you may spend 2 Favors to gain a card costing up to $4 onto your deck.")):
            (card,) = yield ctx.choose("Crafters' Guild: gain a card costing up to $4 onto your deck.", options)
            ctx.gain(card, destination="deck")
    elif ally == "Desert Guides":
        while (yield from _spend(ctx, 1, "Desert Guides: you may spend a Favor to discard your hand and draw 5 cards.")):
            ctx.discard_hand()
            ctx.draw(5)
    elif ally == "Forest Dwellers":
        if (yield from _spend(ctx, 1, "Forest Dwellers: you may spend a Favor to look at the top 3 cards of your deck.")):
            cards = ctx.take_to_set_aside(3)
            ctx.log(f"{me.name} looks at the top {len(cards)} cards of their deck.")
            if cards:
                gone = yield ctx.choose(f"Forest Dwellers: you looked at {', '.join(cards)}. Discard any number of them.", tuple(cards), 0, len(cards))
                for card in gone:
                    ctx.discard_set_aside(card)
                    cards.remove(card)
                yield from ctx.put_back_in_order(cards, "Forest Dwellers: put the rest back (choose the top card first).")
    elif ally == "Gang of Pickpockets":
        if not (yield from _spend(ctx, 1, "Gang of Pickpockets: spend a Favor, or discard down to 4 cards in hand.", "Spend a Favor to keep your hand")):
            extra = len(me.hand) - 4
            if extra > 0:
                chosen = yield ctx.choose("Gang of Pickpockets: discard down to 4 cards in hand.", tuple(me.hand), extra, extra)
                for card in chosen:
                    ctx.discard(card)
    elif ally == "Mountain Folk":
        if (yield from _spend(ctx, 5, "Mountain Folk: you may spend 5 Favors for +3 Cards.")):
            ctx.draw(3)


# ------------------------------------------------------------------ start of the Buy phase
def start_of_buy_steps(state: GameState, player: int):
    ally = state.ally
    if ally is None or state.status.value != "active":
        return
    me = state.players[player]
    ctx = EffectContext(state, player, ally)
    if ally == "Family of Inventors":
        piles = []
        for name in [*state.kingdom, *([state.bane] if state.bane else []), "Copper", "Silver", "Gold", "Curse"]:
            top = state.stacks[name][0] if state.stacks.get(name) else name
            if name in state.stacks and not state.stacks[name]:
                continue
            if top in state.supply and not get_card(top).is_type(CardType.VICTORY) and name not in piles and name != "Castles":
                piles.append(name)
        if piles and (yield from _spend(ctx, 1, "Family of Inventors: you may put a Favor on a non-Victory Supply pile (its cards cost $1 less).", "Put a Favor on a pile")):
            (pile,) = yield ctx.choose("Family of Inventors: put the Favor on which pile?", tuple(piles))
            ctx.pile_token(pile)
            ctx.log(f"{me.name} puts a Favor on the {pile} pile: its cards cost $1 less per Favor on it.")
    elif ally == "League of Bankers":
        n = me.favors // 4
        if n:
            ctx.log(f"League of Bankers: {me.name} has {me.favors} Favors.")
            ctx.add_coins(n)
    elif ally == "Market Towns":
        while any(get_card(c).is_type(CardType.ACTION) for c in me.hand):
            if not (yield from _spend(ctx, 1, "Market Towns: you may spend a Favor to play an Action card from your hand.")):
                break
            options = tuple(sorted({c for c in me.hand if get_card(c).is_type(CardType.ACTION)}))
            (card,) = yield ctx.choose("Market Towns: play an Action card from your hand.", options)
            ctx.put_in_play(card)
            yield from ctx.resolve(card)
    elif ally == "Peaceful Cult":
        if me.favors >= 1 and me.hand:
            k = min(me.favors, len(me.hand))
            chosen = yield ctx.choose(f"Peaceful Cult: you may spend a Favor per card to trash cards from your hand (up to {k}).", tuple(me.hand), 0, k)
            if chosen:
                ctx.spend_favors(len(chosen))
                for card in chosen:
                    ctx.trash(card)
    elif ally == "Woodworkers' Guild":
        if any(get_card(c).is_type(CardType.ACTION) for c in me.hand):
            if (yield from _spend(ctx, 1, "Woodworkers' Guild: you may spend a Favor to trash an Action card from your hand.")):
                options = tuple(sorted({c for c in me.hand if get_card(c).is_type(CardType.ACTION)}))
                (card,) = yield ctx.choose("Woodworkers' Guild: trash an Action card from your hand.", options)
                ctx.trash(card)
                gains = ctx.gainable_actions()
                if gains:
                    (new,) = yield ctx.choose("Woodworkers' Guild: gain an Action card.", gains)
                    ctx.gain(new)


# ------------------------------------------------------------------ gains
def after_gain_steps(state: GameState, event):
    gainer = event.player
    me = state.players[gainer]
    card = get_card(event.card)
    own_turn = state.current_player == gainer
    if own_turn:
        for _ in range(state.turn_counts.get("Guildmaster", 0)):            # Guildmaster: this turn, +1 Favor per card gained
            EffectContext(state, gainer, "Guildmaster").add_favors(1)
        plays = state.turn_counts.get("Garrison", 0)                         # Garrison: a token per gain for each Garrison played
        if plays:
            me.garrison_tokens += plays
        cost = card_cost(state, event.card)
        for _ in range(state.turn_counts.get("Galleria", 0)):               # Galleria: this turn, a card costing $3 or $4 gives +1 Buy
            if cost in (3, 4):
                EffectContext(state, gainer, "Galleria").add_buys(1)
        for _ in range(state.turn_counts.get("Bauble", 0)):                 # Bauble: this turn, a gained card may go onto the deck
            bctx = EffectContext(state, gainer, "Bauble")
            if bctx.gained_card_present(event):
                chosen = yield bctx.choose(f"Bauble: you gained {event.card}. You may put it onto your deck.", ("Put it onto your deck",), 0, 1)
                if chosen:
                    bctx.put_gained_on_deck(event)
        if card.is_type(CardType.ATTACK):                                    # Skirmisher
            for owner, target in list(state.skirmishers):
                if owner == gainer:
                    yield from _discard_down(state, target, 3, "Skirmisher")
    ally = state.ally
    if ally is None or state.status.value != "active":
        return
    ctx = EffectContext(state, gainer, ally)
    present = lambda: ctx.gained_card_present(event)                         # noqa: E731
    if ally == "Architects' Guild":
        cheaper = tuple(n for n in ctx.gainable(card_cost(state, event.card) - 1) if "victory" not in ctx.card_types(n)) if card_cost(state, event.card) > 0 else ()
        if cheaper and (yield from _spend(ctx, 2, f"Architects' Guild: you gained {event.card}. You may spend 2 Favors to gain a cheaper non-Victory card.")):
            (new,) = yield ctx.choose("Architects' Guild: gain a cheaper non-Victory card.", cheaper)
            ctx.gain(new)
    elif ally == "Band of Nomads":
        if card_cost(state, event.card) >= 5:
            if (yield from _spend(ctx, 1, f"Band of Nomads: you gained {event.card}. You may spend a Favor for +1 Card, +1 Action or +1 Buy.")):
                (mode,) = yield ctx.choose("Band of Nomads: choose one.", ("+1 Card", "+1 Action", "+1 Buy"))
                if mode == "+1 Card":
                    ctx.draw(1)
                elif mode == "+1 Action":
                    ctx.add_actions(1)
                else:
                    ctx.add_buys(1)
    elif ally == "City-state":
        if own_turn and card.is_type(CardType.ACTION) and present():
            if (yield from _spend(ctx, 2, f"City-state: you gained {event.card}. You may spend 2 Favors to play it.")):
                if present():
                    zone = event.zone
                    ctx.put_in_play(event.card, zone)
                    event.zone = None
                    yield from ctx.resolve(event.card)
    elif ally == "Trappers' Lodge":
        if present() and (yield from _spend(ctx, 1, f"Trappers' Lodge: you gained {event.card}. You may spend a Favor to put it onto your deck.")):
            ctx.put_gained_on_deck(event)


def _discard_down(state: GameState, target: int, size: int, source: str):
    me = state.players[target]
    extra = len(me.hand) - size
    if extra > 0:
        ctx = EffectContext(state, target, source)
        chosen = yield ctx.choose(f"{source}: discard down to {size} cards in hand.", tuple(me.hand), extra, extra, player=target)
        for card in chosen:
            ctx.discard(card)


# ------------------------------------------------------------------ end of turn and Clean-up
def end_of_turn_steps(state: GameState, player: int, was_extra: bool):
    """Island Folk: at the end of your turn, 5 Favors for another turn (never a third in a row)."""
    if state.ally != "Island Folk" or was_extra or state.current_player != player or state.possessor is not None:
        return
    me = state.players[player]
    ctx = EffectContext(state, player, "Island Folk")
    if (yield from _spend(ctx, 5, "Island Folk: you may spend 5 Favors to take another turn after this one.")):
        ctx.queue_own_extra_turn()
        ctx.log(f"{me.name} will take another turn (Island Folk).", "skip")


def coastal_haven_steps(state: GameState, player: int):
    """Coastal Haven: when discarding your hand in Clean-up, keep that many cards for next turn per Favor spent."""
    if state.ally != "Coastal Haven":
        return
    me = state.players[player]
    if me.favors < 1 or not me.hand:
        return
    ctx = EffectContext(state, player, "Coastal Haven")
    k = min(me.favors, len(me.hand))
    chosen = yield ctx.choose(f"Coastal Haven: you may spend a Favor per card to keep up to {k} cards in hand for next turn.", tuple(me.hand), 0, k)
    if chosen:
        ctx.spend_favors(len(chosen))
        for card in chosen:
            me.hand.remove(card)
            me.saved.append(card)
        ctx.log(f"{me.name} keeps {len(chosen)} card(s) in hand for next turn (Coastal Haven).")


# ------------------------------------------------------------------ shuffles
def shuffle_steps(state: GameState, player: int):
    """Order of Astrologers / Order of Masons: a draw reached the end of the deck. The owner may spend Favors to look through the cards that
    are about to be shuffled; then the shuffle is made. (Everything but the picked cards is shuffled normally.)"""
    me = state.players[player]
    ctx = EffectContext(state, player, state.ally)
    picks: list = []
    pool = list(me.discard)
    masons = state.ally == "Order of Masons"
    while me.favors >= 1 and pool:
        label = "Spend a Favor" 
        text = ("Order of Masons: you may spend a Favor to pick up to 2 of the cards about to be shuffled to go to your discard pile instead."
                if masons else "Order of Astrologers: you may spend a Favor to pick a card of those about to be shuffled to go on top of your deck.")
        chosen = yield ctx.choose(text, (label,), 0, 1)
        if not chosen:
            break
        ctx.spend_favors(1)
        if masons:
            got = yield ctx.choose("Order of Masons: pick up to 2 cards to keep out of the shuffle (they stay in your discard pile).", tuple(sorted(pool)), 0, min(2, len(pool)))
        else:
            got = yield ctx.choose("Order of Astrologers: pick a card to go on top of your deck.", tuple(sorted(set(pool))), 1, 1)
        for card in got:
            pool.remove(card)
            picks.append(card)
    me.discard = list(pool)
    shuffled, me.discard = me.discard, []
    state.rng.shuffle(shuffled)
    if masons:
        me.deck = shuffled
        me.discard = picks
    else:
        me.deck = shuffled + list(reversed(picks))           # the first card picked is the top one
    if picks:
        ctx.log(f"{me.name} picks {len(picks)} card(s) while shuffling ({state.ally}).")
