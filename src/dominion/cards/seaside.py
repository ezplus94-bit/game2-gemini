"""The Seaside expansion (2009, first edition): 26 Kingdom cards.

What is new compared with the earlier card sets, and where the engine supports it:

  * Duration cards (``CardType.DURATION``): an effect now and another at the start of the owner's next turn. A card calls
    ``ctx.add_duration(handler)``; the card stays in play through cleanup and the handler runs when the owner's next turn
    begins (``Game._start_of_turn``). A Throne Room that played a Duration card stays in play with it.
  * Mats: Island mat and Native Village mat (``PlayerState.island_mat`` / ``village_mat``), Haven's set-aside card
    (``PlayerState.haven``). Cards on them are still yours (they count for Gardens, Island's 2 VP...).
  * Tokens: the Pirate Ship's coin tokens (``PlayerState.pirate_tokens``) and Embargo tokens on Supply piles
    (``GameState.embargo``; buying a card from such a pile gains a Curse per token).
  * Lighthouse protects its owner from Attacks until their next turn (checked in ``EffectContext.is_protected``).
  * Outpost: an extra turn with a 3-card hand (``GameState.outpost_*``).
  * "When you discard this from play": Treasury (``CardDef.on_cleanup``).
  * Smugglers looks at what the player on your right gained during their last turn (``PlayerState.last_gained``).
  * New Attacks: Cutpurse, Ghost Ship, Pirate Ship, Sea Hag, Ambassador.
"""

from __future__ import annotations

from .alchemy import _put_back_in_any_order
from .base import CardType, action, action_victory
from .registry import get_card, register

SET = "Seaside"
_ATTACK = (CardType.ATTACK,)
_DURATION = (CardType.DURATION,)


# ----------------------------------------------------------------- $2
def _embargo(ctx):
    ctx.add_coins(2)
    if not ctx.trash_self():
        return
    (pile,) = yield ctx.choose("Embargo: choose a Supply pile to put an Embargo token on.", ctx.supply_names())
    ctx.add_embargo(pile)


def _haven(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    hand = ctx.hand
    if not hand:
        return
    (card,) = yield ctx.choose("Haven: set aside a card from your hand until the start of your next turn.", hand)
    ctx.put_on_mat(card, "haven")
    ctx.log(f"{ctx.player_name} sets a card aside with Haven.")
    ctx.add_duration(_haven_start, card)


def _haven_start(ctx, entry):
    me_haven = ctx.mat_cards("haven")
    if entry.data in me_haven:
        ctx.put_on_mat(entry.data, "hand", source="haven")
        ctx.log(f"{ctx.player_name} takes the card set aside by Haven into their hand.")


def _lighthouse(ctx):
    ctx.add_actions(1)
    ctx.add_coins(1)
    ctx.add_duration(_plus_coins(1))


def _plus_coins(n):
    def start(ctx, entry):
        ctx.add_coins(n)
        ctx.log(f"{entry.source} gives +${n}.")
    start.__name__ = f"_plus_{n}_coins"
    return start


def _native_village(ctx):
    ctx.add_actions(2)
    modes = []
    if ctx.deck_size or ctx.discard_pile:
        modes.append("Set aside the top card of your deck")
    if ctx.mat_cards("village_mat"):
        modes.append("Take all the cards from your mat")
    if not modes:
        return
    mode = modes[0]
    if len(modes) > 1:
        (mode,) = yield ctx.choose("Native Village: choose one.", modes)
    if mode.startswith("Set aside"):
        ctx.top_card_to_village_mat()
    else:
        n = ctx.mat_to_hand("village_mat")
        ctx.log(f"{ctx.player_name} takes {n} card(s) from their Native Village mat into their hand.")


def _pearl_diver(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    bottom = ctx.deck_bottom()
    if bottom is None:
        return
    (answer,) = yield ctx.choose(f"Pearl Diver: the bottom card of your deck is {bottom}.",
                                 ("Put it on top of your deck", "Leave it at the bottom"))
    if answer.startswith("Put"):
        ctx.move_bottom_to_top()
        ctx.log(f"{ctx.player_name} puts the bottom card of their deck on top.")


# ----------------------------------------------------------------- $3
def _ambassador(ctx):
    hand = ctx.hand
    if not hand:
        return
    (card,) = yield ctx.choose("Ambassador: reveal a card from your hand.", tuple(sorted(set(hand))))
    ctx.log(f"{ctx.player_name} reveals {card}.", "reveal")
    copies = min(2, hand.count(card))
    if card in ctx.supply_names() and copies:
        chosen = yield ctx.choose(f"Ambassador: return up to 2 copies of {card} to the Supply.", (card,) * copies, 0, copies)
        for _ in chosen:
            ctx.return_to_supply(card)
    targets = yield from ctx.attack()
    for p in targets:
        ctx.gain(card, player=p)


def _fishing_village(ctx):
    ctx.add_actions(2)
    ctx.add_coins(1)
    ctx.add_duration(_fishing_village_start)


def _fishing_village_start(ctx, entry):
    ctx.add_actions(1)
    ctx.add_coins(1)
    ctx.log("Fishing Village gives +1 Action, +$1.")


def _lookout(ctx):
    ctx.add_actions(1)
    cards = ctx.take_to_set_aside(3)
    if not cards:
        return
    (trashed,) = yield ctx.choose("Lookout: trash one of these cards.", tuple(cards))
    cards.remove(trashed)
    ctx.trash_set_aside(trashed)
    if cards:
        (discarded,) = yield ctx.choose("Lookout: discard one of these cards.", tuple(cards))
        cards.remove(discarded)
        ctx.discard_set_aside(discarded)
    for card in cards:
        ctx.put_set_aside_on_deck(card)
    if cards:
        ctx.log(f"{ctx.player_name} puts the other card back on their deck.")


def _smugglers(ctx):
    right = (ctx.player - 1) % len(ctx.all_players())
    options = tuple(sorted({
        c for c in ctx.last_gained_by(right)
        if c in ctx.supply_names() and ctx.supply_count(c) > 0
        and ctx.potion_cost_of(c) == 0 and ctx.cost_of(c) <= 6
        and c in ctx.gainable(6)
    }))
    if not options:
        return
    card = options[0]
    if len(options) > 1:
        (card,) = yield ctx.choose("Smugglers: gain a copy of a card the player on your right gained last turn.", options)
    ctx.gain(card)


def _warehouse(ctx):
    ctx.draw(3)
    ctx.add_actions(1)
    hand = ctx.hand
    n = min(3, len(hand))
    if n == 0:
        return
    chosen = yield ctx.choose(f"Warehouse: discard {n} card(s).", hand, n, n)
    for card in chosen:
        ctx.discard(card)


# ----------------------------------------------------------------- $4
def _caravan(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.add_duration(_caravan_start)


def _caravan_start(ctx, entry):
    ctx.log("Caravan gives +1 Card.")
    ctx.draw(1)


def _cutpurse(ctx):
    ctx.add_coins(2)
    targets = yield from ctx.attack()
    for p in targets:
        if "Copper" in ctx.hand_of(p):
            ctx.discard("Copper", player=p)
        else:
            hand = ctx.hand_of(p)
            ctx.log(f"{ctx.name_of(p)} reveals a hand with no Copper: {', '.join(sorted(hand)) or 'nothing'}.", "reveal")


def _island(ctx):
    if ctx.source in ctx.in_play:
        ctx.put_on_mat(ctx.source, "island_mat", source="in_play")
        ctx.log(f"{ctx.player_name} puts Island on their Island mat.")
    hand = ctx.hand
    if hand:
        (card,) = yield ctx.choose("Island: choose a card from your hand to put on your Island mat.", hand)
        ctx.put_on_mat(card, "island_mat")
        ctx.log(f"{ctx.player_name} puts a card from their hand on their Island mat.")


def _navigator(ctx):
    ctx.add_coins(2)
    cards = ctx.take_to_set_aside(5)
    if not cards:
        return
    (mode,) = yield ctx.choose("Navigator: discard all five cards, or put them back on your deck in any order.",
                               ("Discard them all", "Put them back"))
    if mode == "Discard them all":
        for card in cards:
            ctx.discard_set_aside(card)
    else:
        yield from _put_back_in_any_order(ctx, cards)


def _pirate_ship(ctx):
    tokens = ctx.pirate_tokens()
    (mode,) = yield ctx.choose(
        "Pirate Ship: choose one.",
        (f"+$1 per token ({tokens} now)", "Attack: trash a revealed Treasure"),
    )
    if not mode.startswith("Attack"):
        ctx.add_coins(tokens)
        ctx.log(f"Pirate Ship gives +${tokens}.")
        return
    targets = yield from ctx.attack()
    trashed_any = False
    for p in targets:
        revealed = ctx.take_to_set_aside(2, player=p, reveal=True)
        treasures = sorted({c for c in revealed if ctx.is_treasure(c)})
        victim = None
        if len(treasures) == 1:
            victim = treasures[0]
        elif len(treasures) > 1:
            (victim,) = yield ctx.choose(f"Pirate Ship: choose a revealed Treasure of {ctx.name_of(p)} to trash.",
                                         tuple(treasures))
        if victim:
            revealed.remove(victim)
            ctx.trash_set_aside(victim, player=p)
            trashed_any = True
        for card in revealed:
            ctx.discard_set_aside(card, player=p)
    if trashed_any:
        ctx.add_pirate_token()


def _salvager(ctx):
    ctx.add_buys(1)
    hand = ctx.hand
    if not hand:
        return
    (card,) = yield ctx.choose("Salvager: trash a card from your hand for +$ equal to its cost.", hand)
    ctx.trash(card)
    ctx.add_coins(ctx.cost_of(card))


def _sea_hag(ctx):
    targets = yield from ctx.attack()
    for p in targets:
        ctx.discard_top_of_deck(player=p)
        ctx.gain("Curse", player=p, destination="deck")


def _treasure_map(ctx):
    trashed_self = ctx.trash_self()
    from_hand = "Treasure Map" in ctx.hand
    if from_hand:
        ctx.trash("Treasure Map")
    if trashed_self and from_hand:
        ctx.log("Two Treasure Maps: the treasure is found!", "gain")
        for _ in range(4):
            ctx.gain("Gold", destination="deck")
    return
    yield                                            # (makes this a generator like the other cards)


# ----------------------------------------------------------------- $5
def _bazaar(ctx):
    ctx.draw(1)
    ctx.add_actions(2)
    ctx.add_coins(1)


def _explorer(ctx):
    if "Province" in ctx.hand:
        chosen = yield ctx.choose("Explorer: you may reveal a Province from your hand to gain a Gold instead of a Silver.",
                                  ("Province",), 0, 1)
        if chosen:
            ctx.log(f"{ctx.player_name} reveals Province.", "reveal")
            ctx.gain("Gold", destination="hand")
            return
    ctx.gain("Silver", destination="hand")


def _ghost_ship(ctx):
    ctx.draw(2)
    targets = yield from ctx.attack()
    for p in targets:
        while len(ctx.hand_of(p)) > 3:
            (card,) = yield ctx.choose(
                f"{ctx.player_name}'s Ghost Ship: put a card from your hand on top of your deck "
                f"({len(ctx.hand_of(p)) - 3} to go).", ctx.hand_of(p), player=p)
            ctx.put_hand_on_deck(card, player=p)


def _merchant_ship(ctx):
    ctx.add_coins(2)
    ctx.add_duration(_plus_coins(2))


def _outpost(ctx):
    ctx.mark_outpost()
    ctx.add_duration()                               # it only has to stay in play


def _tactician(ctx):
    if ctx.discard_hand():
        ctx.add_duration(_tactician_start)


def _tactician_start(ctx, entry):
    ctx.log("Tactician gives +5 Cards, +1 Action, +1 Buy.")
    ctx.draw(5)
    ctx.add_actions(1)
    ctx.add_buys(1)


def _treasury(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.add_coins(1)


def _treasury_cleanup(ctx):
    if ctx.victory_bought:
        return
    chosen = yield ctx.choose("Treasury: you may put this onto your deck (you bought no Victory card this turn).",
                              ("Treasury",), 0, 1)
    if chosen:
        ctx.put_in_play_on_deck("Treasury")


def _wharf(ctx):
    ctx.draw(2)
    ctx.add_buys(1)
    ctx.add_duration(_wharf_start)


def _wharf_start(ctx, entry):
    ctx.log("Wharf gives +2 Cards, +1 Buy.")
    ctx.draw(2)
    ctx.add_buys(1)


# ------------------------------------------------------------ registration
def _reg(name, cost, fn, text, **kw):
    register(action(name, cost, fn, text, expansion=SET, **kw))


_reg("Embargo", 2, _embargo, "+$2. Trash this: put an Embargo token on a Supply pile. When a player buys a card from that pile, they gain a Curse for each token on it.")
_reg("Haven", 2, _haven, "+1 Card, +1 Action. Set aside a card from your hand face down. At the start of your next turn, put it into your hand.", extra_types=_DURATION)
_reg("Lighthouse", 2, _lighthouse, "+1 Action, +$1. At the start of your next turn: +$1. Until then, when another player plays an Attack card, it doesn't affect you.", extra_types=_DURATION)
_reg("Native Village", 2, _native_village, "+2 Actions. Choose one: set aside the top card of your deck face down on your Native Village mat; or put all the cards from your mat into your hand.")
_reg("Pearl Diver", 2, _pearl_diver, "+1 Card, +1 Action. Look at the bottom card of your deck. You may put it on top.")
_reg("Ambassador", 3, _ambassador, "Reveal a card from your hand. Return up to 2 copies of it from your hand to the Supply. Then each other player gains a copy of it.", extra_types=_ATTACK)
_reg("Fishing Village", 3, _fishing_village, "+2 Actions, +$1. At the start of your next turn: +1 Action, +$1.", extra_types=_DURATION)
_reg("Lookout", 3, _lookout, "+1 Action. Look at the top 3 cards of your deck. Trash one of them. Discard one of them. Put the other one back on top of your deck.")
_reg("Smugglers", 3, _smugglers, "Gain a copy of a card costing up to $6 that the player to your right gained on their last turn.")
_reg("Warehouse", 3, _warehouse, "+3 Cards, +1 Action. Discard 3 cards.")
_reg("Caravan", 4, _caravan, "+1 Card, +1 Action. At the start of your next turn: +1 Card.", extra_types=_DURATION)
_reg("Cutpurse", 4, _cutpurse, "+$2. Each other player discards a Copper (or reveals a hand with no Copper).", extra_types=_ATTACK)
register(action_victory("Island", 4, _island, 2, "2 VP. Put this and a card from your hand onto your Island mat.", SET))
_reg("Navigator", 4, _navigator, "+$2. Look at the top 5 cards of your deck. Either discard all of them, or put them back on top of your deck in any order.")
_reg("Pirate Ship", 4, _pirate_ship, "Choose one: each other player reveals the top 2 cards of their deck, trashes a revealed Treasure that you choose, and discards the rest; if anyone trashed a Treasure, you take a coin token. Or +$1 per coin token you have taken with Pirate Ships this game.", extra_types=_ATTACK)
_reg("Salvager", 4, _salvager, "+1 Buy. Trash a card from your hand. +$ equal to its cost.")
_reg("Sea Hag", 4, _sea_hag, "Each other player discards the top card of their deck, then gains a Curse onto their deck.", extra_types=_ATTACK)
_reg("Treasure Map", 4, _treasure_map, "Trash this and a Treasure Map from your hand. If you trashed two Treasure Maps, gain 4 Golds onto your deck.")
_reg("Bazaar", 5, _bazaar, "+1 Card, +2 Actions, +$1.")
_reg("Explorer", 5, _explorer, "You may reveal a Province from your hand. If you do, gain a Gold to your hand. If you don't, gain a Silver to your hand.")
_reg("Ghost Ship", 5, _ghost_ship, "+2 Cards. Each other player with 4 or more cards in hand puts cards from their hand onto their deck until they have 3 cards in hand.", extra_types=_ATTACK)
_reg("Merchant Ship", 5, _merchant_ship, "+$2. At the start of your next turn: +$2.", extra_types=_DURATION)
_reg("Outpost", 5, _outpost, "You only draw 3 cards for your next hand. Take an extra turn after this one (but not a 3rd turn in a row).", extra_types=_DURATION)
_reg("Tactician", 5, _tactician, "Discard your hand. If you discarded any cards this way, then at the start of your next turn: +5 Cards, +1 Action, +1 Buy.", extra_types=_DURATION)
_reg("Treasury", 5, _treasury, "+1 Card, +1 Action, +$1. When you discard this from play, if you didn't buy a Victory card this turn, you may put this onto your deck.",
     on_cleanup=_treasury_cleanup)
_reg("Wharf", 5, _wharf, "+2 Cards, +1 Buy. At the start of your next turn: +2 Cards, +1 Buy.", extra_types=_DURATION)
