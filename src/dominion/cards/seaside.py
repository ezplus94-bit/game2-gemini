"""The Seaside expansion (2009): 26 Kingdom cards."""

from __future__ import annotations

from .base import CardType, action, action_victory, duration
from .registry import register

SET = "Seaside"
_ATTACK = (CardType.ATTACK,)


# ----------------------------------------------------------------- $2
def _embargo(ctx):
    ctx.add_coins(2)
    if not ctx.trash_self():
        return
    piles = ctx.supply_names()
    if not piles:
        return
    (pile,) = yield ctx.choose("Embargo: choose a Supply pile to put an Embargo token on.", piles)
    ctx.add_embargo(pile)


def _haven(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    hand = ctx.hand
    if not hand:
        return
    (card,) = yield ctx.choose("Haven: set aside a card from your hand face down for next turn.", hand)
    ctx.set_aside_for_haven(card)


def _haven_next(ctx):
    ctx.return_haven_cards()


def _lighthouse(ctx):
    ctx.add_actions(1)
    ctx.add_coins(1)


def _lighthouse_next(ctx):
    ctx.add_coins(1)


def _native_village(ctx):
    ctx.add_actions(2)
    (choice,) = yield ctx.choose(
        "Native Village: choose one.",
        ("Set aside top card on mat", "Put mat cards into hand"),
    )
    if choice == "Set aside top card on mat":
        ctx.native_village_push()
    else:
        ctx.native_village_take()


def _pearl_diver(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    bottom = ctx.peek_bottom_of_deck()
    if bottom is None:
        return
    (answer,) = yield ctx.choose(
        f"Pearl Diver: the bottom card of your deck is {bottom}. Put it on top?",
        ("Put on top", "Leave on bottom"),
    )
    if answer == "Put on top":
        ctx.move_bottom_to_top()


# ----------------------------------------------------------------- $3
def _ambassador(ctx):
    hand = ctx.hand
    if not hand:
        return
    unique = tuple(sorted(set(hand)))
    (revealed,) = yield ctx.choose("Ambassador: reveal a card from your hand.", unique)
    ctx.log(f"{ctx.player_name} reveals {revealed}.", "reveal")
    if ctx.in_supply(revealed):
        copies = [c for c in ctx.hand if c == revealed][:2]
        chosen = yield ctx.choose(
            f"Ambassador: return up to 2 copies of {revealed} to the Supply.",
            tuple(copies), 0, len(copies),
        )
        for _ in chosen:
            ctx.return_hand_to_supply(revealed)
    targets = yield from ctx.attack()
    for p in targets:
        ctx.gain(revealed, player=p)


def _fishing_village(ctx):
    ctx.add_actions(2)
    ctx.add_coins(1)


def _fishing_village_next(ctx):
    ctx.add_actions(1)
    ctx.add_coins(1)


def _lookout(ctx):
    ctx.add_actions(1)
    cards = ctx.take_to_set_aside(3, reveal=False)
    if not cards:
        return
    if len(cards) == 1:
        ctx.trash_set_aside(cards[0])
        return
    (to_trash,) = yield ctx.choose("Lookout: choose a card to trash.", tuple(cards))
    ctx.trash_set_aside(to_trash)
    rem = list(cards)
    rem.remove(to_trash)
    if len(rem) == 1:
        ctx.discard_set_aside(rem[0])
        return
    (to_discard,) = yield ctx.choose("Lookout: choose a card to discard.", tuple(rem))
    ctx.discard_set_aside(to_discard)
    rem.remove(to_discard)
    ctx.put_set_aside_on_deck(rem[0])


def _smugglers(ctx):
    options = ctx.smuggle_options()
    if not options:
        return
    (card,) = yield ctx.choose(
        "Smugglers: gain a copy of a card costing up to $6 that the player to your right gained on their last turn.",
        options,
    )
    ctx.gain(card)


def _warehouse(ctx):
    ctx.draw(3)
    ctx.add_actions(1)
    hand = ctx.hand
    if not hand:
        return
    need = min(3, len(hand))
    chosen = yield ctx.choose(f"Warehouse: discard {need} card(s).", hand, need, need)
    for card in chosen:
        ctx.discard(card)


# ----------------------------------------------------------------- $4
def _caravan(ctx):
    ctx.draw(1)
    ctx.add_actions(1)


def _caravan_next(ctx):
    ctx.draw(1)


def _cutpurse(ctx):
    ctx.add_coins(2)
    targets = yield from ctx.attack()
    for p in targets:
        if "Copper" in ctx.hand_of(p):
            ctx.discard("Copper", player=p)
        else:
            ctx.reveal_hand(p)


def _island(ctx):
    ctx.move_self_to_island()
    hand = ctx.hand
    if not hand:
        return
    (card,) = yield ctx.choose("Island: set aside a card from your hand onto your Island mat.", hand)
    ctx.move_hand_to_island(card)


def _navigator(ctx):
    ctx.add_coins(2)
    cards = ctx.take_to_set_aside(5, reveal=False)
    if not cards:
        return
    (mode,) = yield ctx.choose(
        f"Navigator: looked at {', '.join(cards)}. Discard all of them, or put them back on top?",
        ("Discard all", "Put back on top"),
    )
    if mode == "Discard all":
        for c in cards:
            ctx.discard_set_aside(c)
    else:
        rest = list(cards)
        order = []
        while len(rest) > 1:
            if len(set(rest)) == 1:
                order.extend(rest)
                rest = []
                break
            (top,) = yield ctx.choose("Navigator: choose the next card to put on top of your deck.", tuple(rest))
            rest.remove(top)
            order.append(top)
        order.extend(rest)
        for c in reversed(order):
            ctx.put_set_aside_on_deck(c)


def _pirate_ship(ctx):
    coins = ctx.pirate_coins
    (mode,) = yield ctx.choose(
        f"Pirate Ship: attack other players for Treasures, or take +${coins}?",
        ("Attack for Treasures", f"Take +${coins}"),
    )
    if mode != "Attack for Treasures":
        ctx.add_coins(coins)
        return
    targets = yield from ctx.attack()
    trashed_any = False
    for p in targets:
        top = ctx.take_to_set_aside(2, player=p, reveal=True)
        treasures = [c for c in top if ctx.is_treasure(c)]
        others = [c for c in top if not ctx.is_treasure(c)]
        for c in others:
            ctx.discard_set_aside(c, player=p)
        if not treasures:
            continue
        if len(set(treasures)) == 1:
            pick = treasures[0]
        else:
            (pick,) = yield ctx.choose(
                f"Pirate Ship: choose one of {ctx.name_of(p)}'s Treasures to trash.",
                tuple(treasures),
            )
        ctx.trash_set_aside(pick, player=p)
        trashed_any = True
        treasures.remove(pick)
        for c in treasures:
            ctx.discard_set_aside(c, player=p)
    if trashed_any:
        ctx.add_pirate_coin()


def _salvager(ctx):
    ctx.add_buys(1)
    hand = ctx.hand
    if not hand:
        return
    (card,) = yield ctx.choose("Salvager: trash a card from your hand for +$ equal to its cost.", hand)
    cost = ctx.cost_of(card)
    ctx.trash(card)
    if cost:
        ctx.add_coins(cost)


def _sea_hag(ctx):
    targets = yield from ctx.attack()
    for p in targets:
        ctx.discard_top_of_deck_for(p)
        ctx.gain("Curse", player=p, destination="deck")


def _treasure_map(ctx):
    if "Treasure Map" not in ctx.hand:
        ctx.trash_self()
        return
    if not ctx.trash_self():
        return
    ctx.trash("Treasure Map")
    for _ in range(4):
        ctx.gain("Gold", destination="deck")


# ----------------------------------------------------------------- $5
def _bazaar(ctx):
    ctx.draw(1)
    ctx.add_actions(2)
    ctx.add_coins(1)


def _explorer(ctx):
    if "Province" in ctx.hand:
        chosen = yield ctx.choose(
            "Explorer: you may reveal a Province from your hand to gain a Gold instead of a Silver.",
            ("Province",), 0, 1,
        )
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
            need = len(ctx.hand_of(p)) - 3
            (card,) = yield ctx.choose(
                f"Ghost Ship: put a card from your hand onto your deck ({need} left).",
                ctx.hand_of(p), 1, 1, player=p,
            )
            ctx.put_hand_on_deck(card, player=p)


def _merchant_ship(ctx):
    ctx.add_coins(2)


def _merchant_ship_next(ctx):
    ctx.add_coins(2)


def _outpost(ctx):
    ctx.queue_outpost_turn()


def _tactician(ctx):
    if ctx.hand:
        ctx.discard_hand()
        ctx.activate_tactician()


def _tactician_next(ctx):
    if ctx.consume_tactician():
        ctx.draw(5)
        ctx.add_buys(1)
        ctx.add_actions(1)


def _treasury(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.add_coins(1)


def _treasury_cleanup(ctx):
    if ctx.bought_victory_this_turn():
        return
    chosen = yield ctx.choose("Treasury: you did not buy a Victory card. Put Treasury onto your deck?", ("Treasury",), 0, 1)
    if chosen:
        ctx.put_in_play_on_deck("Treasury")


def _wharf(ctx):
    ctx.draw(2)
    ctx.add_buys(1)


def _wharf_next(ctx):
    ctx.draw(2)
    ctx.add_buys(1)


# ------------------------------------------------------------ registration
def _reg(name, cost, fn, text, **kw):
    register(action(name, cost, fn, text, expansion=SET, **kw))


def _dur(name, cost, fn, next_fn, text, **kw):
    register(duration(name, cost, fn, next_fn, text, expansion=SET, **kw))


_reg("Embargo", 2, _embargo, "+$2. Trash this card. Put an Embargo token on top of a Supply pile. When a player buys a card, he gains a Curse card per Embargo token on that pile.")
_dur("Haven", 2, _haven, _haven_next, "+1 Card, +1 Action. Set aside a card from your hand face down. At the start of your next turn, put it into your hand.")
_dur("Lighthouse", 2, _lighthouse, _lighthouse_next, "+1 Action. Now and at the start of your next turn: +$1. While this is in play, when another player plays an Attack card, it doesn't affect you.")
_reg("Native Village", 2, _native_village, "+2 Actions. Choose one: Set aside the top card of your deck face down on your Native Village mat; or put all the cards from your mat into your hand.")
_reg("Pearl Diver", 2, _pearl_diver, "+1 Card, +1 Action. Look at the bottom card of your deck. You may put it on top.")

_reg("Ambassador", 3, _ambassador, "Reveal a card from your hand. Return up to 2 copies of it from your hand to the Supply. Then each other player gains a copy of it.", extra_types=_ATTACK)
_dur("Fishing Village", 3, _fishing_village, _fishing_village_next, "+2 Actions, +$1. At the start of your next turn: +1 Action, +$1.")
_reg("Lookout", 3, _lookout, "+1 Action. Look at the top 3 cards of your deck. Trash one of them. Discard one of them. Put the other one on top of your deck.")
_reg("Smugglers", 3, _smugglers, "Gain a copy of a card costing up to $6 that the player to your right gained on their last turn.")
_reg("Warehouse", 3, _warehouse, "+3 Cards, +1 Action. Discard 3 cards.")

_dur("Caravan", 4, _caravan, _caravan_next, "+1 Card, +1 Action. At the start of your next turn, +1 Card.")
_reg("Cutpurse", 4, _cutpurse, "+$2. Each other player discards a Copper card (or reveals a hand with no Copper).", extra_types=_ATTACK)
register(action_victory("Island", 4, _island, vp=2, text="Put this and a card from your hand onto your Island mat. Worth 2 VP.", expansion=SET))
_reg("Navigator", 4, _navigator, "+$2. Look at the top 5 cards of your deck. Either discard all of them, or put them back on top of your deck in any order.")
_reg("Pirate Ship", 4, _pirate_ship, "Choose one: Each other player reveals the top 2 cards of their deck, trashes a revealed Treasure that you choose, discards the rest, and if anyone trashed a Treasure you take a Coin token; or, +$1 per Coin token you have.", extra_types=_ATTACK)
_reg("Salvager", 4, _salvager, "+1 Buy. Trash a card from your hand. +$ equal to its cost.")
_reg("Sea Hag", 4, _sea_hag, "Each other player discards the top card of his deck, then gains a Curse card, putting it on top of his deck.", extra_types=_ATTACK)
_reg("Treasure Map", 4, _treasure_map, "Trash this and another copy of Treasure Map from your hand. If you do, gain 4 Gold cards, putting them on top of your deck.")

_reg("Bazaar", 5, _bazaar, "+1 Card, +2 Actions, +$1.")
_reg("Explorer", 5, _explorer, "You may reveal a Province card from your hand. If you do, gain a Gold card, putting it into your hand. Otherwise, gain a Silver card, putting it into your hand.")
_reg("Ghost Ship", 5, _ghost_ship, "+2 Cards. Each other player with 4 or more cards in hand puts cards from his hand on top of his deck until he has 3 cards in his hand.", extra_types=_ATTACK)
_dur("Merchant Ship", 5, _merchant_ship, _merchant_ship_next, "Now and at the start of your next turn: +$2.")
_dur("Outpost", 5, _outpost, None, "You only draw 3 cards (instead of 5) in this turn's Clean-up phase. Take an extra turn after this one. This can't cause you to take more than two consecutive turns.")
_dur("Tactician", 5, _tactician, _tactician_next, "If you have at least one card in hand: discard your hand, and at the start of your next turn, +5 Cards, +1 Buy, and +1 Action.")
_reg("Treasury", 5, _treasury, "+1 Card, +1 Action, +$1. When you discard this from play, if you didn't buy a Victory card this turn, you may put this on top of your deck.", on_cleanup=_treasury_cleanup, cleanup_order=0)
_dur("Wharf", 5, _wharf, _wharf_next, "Now and at the start of your next turn: +2 Cards, +1 Buy.")
