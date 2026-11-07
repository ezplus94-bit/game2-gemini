"""The Prosperity expansion: all 25 cards of the first edition (2010) plus the 9 new cards of the second edition (2022).

The second edition removed nine cards (Loan, Trade Route, Talisman, Contraband, Counting House, Mountebank, Royal Seal,
Venture, Goons) and added nine (Anvil, Clerk, Investment, Tiara, Charlatan, Collection, Crystal Ball, Magnate, War Chest).
Every card of both editions is available (34 in all); cards that exist in both use the second-edition wording.

What is new in the engine:

  * Platinum and Colony: two more basic cards (``cards/basic.py``), used together when ``GameConfig.colonies`` says so
    (by default when a randomly chosen Kingdom card is a Prosperity card). An empty Colony pile ends the game.
  * VP tokens (``PlayerState.vp_tokens``): Bishop, Monument, Goons, Collection, Investment. They count at the end.
  * Treasures with effects: a Treasure may have ``on_play`` (Anvil, Crystal Ball, Venture, Loan, Contraband, War Chest,
    Tiara, Investment, Collection, Quarry). Playing all Treasures stops at the first one that asks a question.
  * "When you gain" effects (``CardDef.on_gain`` / ``on_gain_in_play`` / ``on_gain_reaction``): every gain is queued as a
    ``GainEvent`` and looked at once nothing is waiting for an answer (``Game._settle``): Hoard, Collection, Goons,
    Talisman, Mint, Royal Seal, Tiara and the Watchtower Reaction.
  * Costs that change: Quarry (Actions cost $2 less this turn), Peddler (``CardDef.cost_mod``, cheaper in the Buy phase).
  * Buying restrictions: Grand Market (no Coppers in play) and Contraband (a named card) via ``CardDef.can_buy_fn``.
  * Clerk may be played from the hand at the start of its owner's turn (``CardDef.play_at_turn_start``).
  * Charlatan makes Curses Treasures worth $1 for the whole game (``GameState.curse_treasure``).
  * Trade Route: a token on every Victory pile that moves to a mat when a card is gained from it.
"""

from __future__ import annotations

from .alchemy import _put_back_in_any_order
from .base import CardDef, CardType, action, treasure
from .registry import get_card, register

SET = "Prosperity"
_ATTACK = (CardType.ATTACK,)


def _offer_topdeck(ctx, event):
    """Royal Seal / Tiara: the player may put the card they just gained onto their deck."""
    if event.zone is None or event.zone == "deck" or not ctx.gained_card_present(event):
        return
    chosen = yield ctx.choose(f"{ctx.source}: you may put the {event.card} you gained on top of your deck.",
                              ("Put it on top of your deck",), 0, 1)
    if chosen:
        ctx.put_gained_on_deck(event)


# ----------------------------------------------------------------- Treasures
def _anvil(ctx):
    treasures = tuple(sorted({c for c in ctx.hand if ctx.is_treasure(c)}))
    if not treasures:
        return
    chosen = yield ctx.choose("Anvil: you may discard a Treasure to gain a card costing up to $4.", treasures, 0, 1)
    if not chosen:
        return
    ctx.discard(chosen[0])
    options = ctx.gainable(4)
    if options:
        (card,) = yield ctx.choose("Anvil: gain a card costing up to $4.", options)
        ctx.gain(card)


def _bank_coins(state, player: int) -> int:
    from ..engine.cardtypes import is_treasure
    return sum(1 for c in state.players[player].in_play if is_treasure(state, c))


def _collection(ctx):
    ctx.add_buys(1)


def _collection_gain(ctx, event):
    if ctx.is_action(event.card):
        ctx.add_vp(1)


def _crystal_ball(ctx):
    cards = ctx.take_to_set_aside(1)
    if not cards:
        return
    card = cards[0]
    options = ["Trash it", "Discard it"]
    if ctx.is_action(card) or ctx.is_treasure(card):
        options.append("Play it")
    options.append("Leave it on your deck")
    (mode,) = yield ctx.choose(f"Crystal Ball: the top card of your deck is {card}.", tuple(options))
    if mode == "Trash it":
        ctx.trash_set_aside(card)
    elif mode == "Discard it":
        ctx.discard_set_aside(card)
    elif mode == "Play it":
        if ctx.is_action(card):
            ctx.put_in_play(card, "set_aside")
            yield from ctx.resolve(card)
        else:
            yield from ctx.play_treasure(card, "set_aside")
    else:
        ctx.put_set_aside_on_deck(card)


def _hoard_gain(ctx, event):
    if event.bought and ctx.is_victory(event.card):
        ctx.gain("Gold")


def _investment(ctx):
    hand = ctx.hand
    if hand:
        (card,) = yield ctx.choose("Investment: trash a card from your hand.", hand)
        ctx.trash(card)
    (mode,) = yield ctx.choose("Investment: choose one.", ("+$1", "Trash this and reveal your hand for VP"))
    if mode == "+$1":
        ctx.add_coins(1)
    elif ctx.trash_self():
        hand = ctx.hand
        ctx.log(f"{ctx.player_name} reveals their hand: {', '.join(sorted(hand)) or 'nothing'}.", "reveal")
        ctx.add_vp(len({c for c in hand if ctx.is_treasure(c)}))


def _quarry(ctx):
    ctx.reduce_action_costs(2)


def _tiara(ctx):
    ctx.add_buys(1)
    treasures = tuple(sorted({c for c in ctx.hand if ctx.is_treasure(c)}))
    if not treasures:
        return
    chosen = yield ctx.choose("Tiara: you may play a Treasure from your hand twice.", treasures, 0, 1)
    if chosen:
        yield from ctx.play_treasure(chosen[0], "hand")
        yield from ctx.play_treasure(chosen[0], "in_play")


def _war_chest(ctx):
    left = ctx.left_player()
    (name,) = yield ctx.choose(f"War Chest ({ctx.player_name}): name a card. They cannot gain it with a War Chest this turn.",
                               ctx.supply_names(), player=left)
    ctx.war_chest_name(name)
    options = tuple(c for c in ctx.gainable(5) if c not in ctx.war_chest_names())
    if not options:
        return
    (card,) = yield ctx.choose("War Chest: gain a card costing up to $5 that has not been named for a War Chest this turn.", options)
    ctx.gain(card)


def _grand_market_restriction(state):
    if "Copper" in state.players[state.current_player].in_play:
        return "You can't buy Grand Market while you have a Copper in play."
    return None


# --- first edition only
def _loan(ctx):
    others, found = [], None
    while True:
        cards = ctx.take_to_set_aside(1, reveal=True)
        if not cards:
            break
        if ctx.is_treasure(cards[0]):
            found = cards[0]
            break
        others.append(cards[0])
    for card in others:
        ctx.discard_set_aside(card)
    if found is None:
        return
    (mode,) = yield ctx.choose(f"Loan: you revealed {found}. Discard it or trash it?", ("Discard it", "Trash it"))
    if mode == "Trash it":
        ctx.trash_set_aside(found)
    else:
        ctx.discard_set_aside(found)


def _talisman_gain(ctx, event):
    if (event.bought and ctx.cost_of(event.card) <= 4 and ctx.potion_cost_of(event.card) == 0
            and not ctx.is_victory(event.card)):
        ctx.gain(event.card)


def _contraband(ctx):
    ctx.add_buys(1)
    left = ctx.left_player()
    (name,) = yield ctx.choose(f"Contraband ({ctx.player_name}): name a card. They cannot buy it this turn.",
                               ctx.supply_names(), player=left)
    ctx.ban_card(name)


def _royal_seal_gain(ctx, event):
    yield from _offer_topdeck(ctx, event)


def _tiara_gain(ctx, event):
    yield from _offer_topdeck(ctx, event)


def _venture(ctx):
    others, found = [], None
    while True:
        cards = ctx.take_to_set_aside(1, reveal=True)
        if not cards:
            break
        if ctx.is_treasure(cards[0]):
            found = cards[0]
            break
        others.append(cards[0])
    for card in others:
        ctx.discard_set_aside(card)
    if found is not None:
        yield from ctx.play_treasure(found, "set_aside")


# ----------------------------------------------------------------- Actions
def _bishop(ctx):
    ctx.add_coins(1)
    ctx.add_vp(1)
    hand = ctx.hand
    if hand:
        (card,) = yield ctx.choose("Bishop: trash a card from your hand.", hand)
        ctx.trash(card)
        ctx.add_vp(ctx.cost_of(card) // 2)
    for p in ctx.other_players():
        theirs = ctx.hand_of(p)
        if not theirs:
            continue
        chosen = yield ctx.choose(f"{ctx.player_name}'s Bishop: you may trash a card from your hand.", theirs, 0, 1, player=p)
        if chosen:
            ctx.trash(chosen[0], player=p)


def _charlatan(ctx):
    ctx.add_coins(3)
    targets = yield from ctx.attack()
    for p in targets:
        ctx.gain("Curse", player=p)


def _city(ctx):
    ctx.draw(1)
    ctx.add_actions(2)
    empty = ctx.empty_piles()
    if empty >= 1:
        ctx.draw(1)
    if empty >= 2:
        ctx.add_buys(1)
        ctx.add_coins(1)


def _clerk(ctx):
    ctx.add_coins(2)
    targets = yield from ctx.attack()
    for p in targets:
        hand = ctx.hand_of(p)
        if len(hand) >= 5:
            (card,) = yield ctx.choose(f"{ctx.player_name}'s Clerk: put a card from your hand onto your deck.", hand, player=p)
            ctx.put_hand_on_deck(card, player=p)


def _counting_house(ctx):
    coppers = ctx.discard_pile.count("Copper")
    if not coppers:
        return
    options = tuple(f"Take {n} Copper{'s' if n != 1 else ''}" for n in range(0, coppers + 1))
    (answer,) = yield ctx.choose("Counting House: how many Coppers from your discard pile go into your hand?", options)
    n = int(answer.split()[1]) if answer[5].isdigit() else 0
    ctx.log(f"{ctx.player_name} reveals {coppers} Copper(s) in their discard pile and takes {n} into their hand.", "reveal")
    for _ in range(n):
        ctx.take_from_discard("Copper")


def _expand(ctx):
    hand = ctx.hand
    if not hand:
        return
    (trashed,) = yield ctx.choose("Expand: trash a card from your hand.", hand)
    ctx.trash(trashed)
    limit = ctx.cost_of(trashed) + 3
    options = ctx.gainable(limit)
    if options:
        (card,) = yield ctx.choose(f"Expand: gain a card costing up to ${limit}.", options)
        ctx.gain(card)


def _forge(ctx):
    hand = ctx.hand
    chosen = ()
    if hand:
        chosen = yield ctx.choose("Forge: trash any number of cards from your hand.", hand, 0, len(hand))
    total = sum(ctx.cost_of(c) for c in chosen)
    for card in chosen:
        ctx.trash(card)
    options = ctx.gainable(total, exact=True)
    if options:
        (card,) = yield ctx.choose(f"Forge: gain a card costing exactly ${total}.", options)
        ctx.gain(card)


def _goons(ctx):
    ctx.add_buys(1)
    ctx.add_coins(2)
    targets = yield from ctx.attack()
    for p in targets:
        hand = ctx.hand_of(p)
        excess = len(hand) - 3
        if excess > 0:
            chosen = yield ctx.choose(f"{ctx.player_name}'s Goons: discard {excess} card(s) to get down to 3.", hand, excess, excess, player=p)
            for card in chosen:
                ctx.discard(card, player=p)


def _goons_gain(ctx, event):
    if event.bought:
        ctx.add_vp(1)


def _grand_market(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.add_buys(1)
    ctx.add_coins(2)


def _kings_court(ctx):
    options = tuple(sorted({c for c in ctx.hand if ctx.is_action(c)}))
    if not options:
        return
    chosen = yield ctx.choose("You may play an Action card from your hand three times.", options, 0, 1)
    if not chosen:
        return
    card = chosen[0]
    ctx.put_in_play(card, "hand")
    for _ in range(3):
        yield from ctx.resolve(card)


def _magnate(ctx):
    hand = ctx.hand
    ctx.log(f"{ctx.player_name} reveals their hand: {', '.join(sorted(hand)) or 'nothing'}.", "reveal")
    n = sum(1 for c in hand if ctx.is_treasure(c))
    if n:
        ctx.draw(n)


def _mint(ctx):
    treasures = tuple(sorted({c for c in ctx.hand if ctx.is_treasure(c)}))
    if not treasures:
        return
    chosen = yield ctx.choose("Mint: you may reveal a Treasure from your hand to gain a copy of it.", treasures, 0, 1)
    if chosen:
        ctx.log(f"{ctx.player_name} reveals {chosen[0]}.", "reveal")
        ctx.gain(chosen[0])


def _mint_gain(ctx, event):
    ctx.trash_treasures_in_play()


def _monument(ctx):
    ctx.add_coins(2)
    ctx.add_vp(1)


def _mountebank(ctx):
    ctx.add_coins(2)
    targets = yield from ctx.attack()
    for p in targets:
        if "Curse" in ctx.hand_of(p):
            (mode,) = yield ctx.choose(f"{ctx.player_name}'s Mountebank: discard a Curse, or gain a Curse and a Copper?",
                                       ("Discard a Curse", "Gain a Curse and a Copper"), player=p)
            if mode == "Discard a Curse":
                ctx.discard("Curse", player=p)
                continue
        ctx.gain("Curse", player=p)
        ctx.gain("Copper", player=p)


def _peddler(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.add_coins(1)


def _peddler_discount(state) -> int:
    """$2 less per Action card the current player has in play, but only during their Buy phase."""
    from ..engine.state import Phase
    if state.phase is not Phase.BUY:
        return 0
    me = state.players[state.current_player]
    return 2 * sum(1 for c in me.in_play if get_card(c).is_type(CardType.ACTION))


def _rabble(ctx):
    ctx.draw(3)
    targets = yield from ctx.attack()
    for p in targets:
        revealed = ctx.take_to_set_aside(3, player=p, reveal=True)
        rest = []
        for card in revealed:
            if ctx.is_action(card) or ctx.is_treasure(card):
                ctx.discard_set_aside(card, player=p)
            else:
                rest.append(card)
        yield from _put_back_in_any_order(ctx, rest, player=p)


def _trade_route(ctx):
    ctx.add_buys(1)
    coins = ctx.trade_route_coins()
    ctx.add_coins(coins)
    hand = ctx.hand
    if hand:
        (card,) = yield ctx.choose(f"Trade Route (+${coins}): trash a card from your hand.", hand)
        ctx.trash(card)


def _vault(ctx):
    ctx.draw(2)
    hand = ctx.hand
    if hand:
        chosen = yield ctx.choose("Vault: discard any number of cards for +$1 each.", hand, 0, len(hand))
        for card in chosen:
            ctx.discard(card)
        ctx.add_coins(len(chosen))
    for p in ctx.other_players():
        theirs = ctx.hand_of(p)
        if not theirs:
            continue
        (mode,) = yield ctx.choose(f"{ctx.player_name}'s Vault: you may discard 2 cards to draw a card.",
                                   ("Discard 2 cards to draw a card", "Do nothing"), player=p)
        if mode.startswith("Discard"):
            n = min(2, len(theirs))
            chosen = yield ctx.choose(f"Vault: choose {n} card(s) to discard.", theirs, n, n, player=p)
            for card in chosen:
                ctx.discard(card, player=p)
            if len(chosen) == 2:
                ctx.draw(1, player=p)


def _watchtower(ctx):
    drawn = 0
    while ctx.hand_size < 6:
        if not ctx.draw(1, quiet=True):
            break
        drawn += 1
    ctx.log(f"{ctx.player_name} draws {drawn} card(s) with Watchtower.")
    return
    yield


def _watchtower_gain(ctx, event):
    if event.zone is None or not ctx.gained_card_present(event):
        return
    chosen = yield ctx.choose(
        f"You gained {event.card}. You may reveal Watchtower to trash it or put it on top of your deck.",
        ("Trash it", "Put it on top of your deck"), 0, 1)
    if not chosen:
        return
    ctx.log(f"{ctx.player_name} reveals Watchtower.", "reveal")
    if chosen[0] == "Trash it":
        ctx.trash_gained(event)
    else:
        ctx.put_gained_on_deck(event)


def _workers_village(ctx):
    ctx.draw(1)
    ctx.add_actions(2)
    ctx.add_buys(1)


# ------------------------------------------------------------ registration
def _reg(name, cost, fn, text, **kw):
    register(action(name, cost, fn, text, expansion=SET, **kw))


def _treasure(name, cost, coins, text, **kw):
    register(treasure(name, cost, coins, text=text, kingdom=True, expansion=SET, **kw))


# $3
_treasure("Anvil", 3, 1, "$1. You may discard a Treasure to gain a card costing up to $4.", on_play=_anvil)
_treasure("Loan", 3, 1, "$1. When you play this, reveal cards from your deck until you reveal a Treasure. Discard it or trash it. Discard the other cards.", on_play=_loan)
_reg("Trade Route", 3, _trade_route, "+1 Buy. +$1 per token on the Trade Route mat. Trash a card from your hand. (Setup: a token on each Victory Supply pile; when a card is gained from such a pile, move its token to the mat.)")
_reg("Watchtower", 3, _watchtower, "Draw until you have 6 cards in hand. When you gain a card, you may reveal this from your hand, to either trash that card or put it onto your deck.",
     extra_types=(CardType.REACTION,), on_gain_reaction=_watchtower_gain)
# $4
_reg("Bishop", 4, _bishop, "+$1, +1 VP token. Trash a card from your hand. +1 VP token per $2 it costs (round down). Each other player may trash a card from their hand.")
_reg("Clerk", 4, _clerk, "+$2. Each other player with 5 or more cards in hand puts one onto their deck. At the start of your turn, you may play this from your hand.",
     extra_types=(CardType.REACTION, CardType.ATTACK), play_at_turn_start=True)
register(treasure("Investment", 4, 0, text="Trash a card from your hand. Choose one: +$1; or trash this to reveal your hand for +1 VP token per differently named Treasure there.",
                  kingdom=True, expansion=SET, on_play=_investment))
_reg("Monument", 4, _monument, "+$2, +1 VP token.")
_treasure("Quarry", 4, 1, "$1. This turn, Action cards cost $2 less.", on_play=_quarry)
_treasure("Talisman", 4, 1, "$1. While this is in play, when you buy a card costing $4 or less that is not a Victory card, gain a copy of it.", on_gain_in_play=_talisman_gain)
register(treasure("Tiara", 4, 0, text="+1 Buy. This turn, when you gain a card, you may put it onto your deck. You may play a Treasure from your hand twice.",
                  kingdom=True, expansion=SET, on_play=_tiara, on_gain_in_play=_tiara_gain))
_reg("Workers' Village", 4, _workers_village, "+1 Card, +2 Actions, +1 Buy.")
# $5
_reg("Charlatan", 5, _charlatan, "+$3. Each other player gains a Curse. In games using this, Curse is also a Treasure worth $1.", extra_types=_ATTACK)
_reg("City", 5, _city, "+1 Card, +2 Actions. If there are one or more empty Supply piles, +1 Card. If there are two or more, +1 Buy and +$1.")
_treasure("Collection", 5, 2, "$2, +1 Buy. This turn, when you gain an Action card, +1 VP token.", on_play=_collection, on_gain_in_play=_collection_gain)
_treasure("Contraband", 5, 3, "$3, +1 Buy. When you play this, the player to your left names a card. You can't buy that card this turn.", on_play=_contraband)
_reg("Counting House", 5, _counting_house, "Look through your discard pile, reveal any number of Coppers from it, and put them into your hand.")
_treasure("Crystal Ball", 5, 1, "$1. Look at the top card of your deck. You may trash it, discard it, or, if it's an Action or Treasure, play it.", on_play=_crystal_ball)
_reg("Magnate", 5, _magnate, "Reveal your hand. +1 Card per Treasure in it.")
register(action("Mint", 5, _mint, "You may reveal a Treasure card from your hand. Gain a copy of it. When you gain this, trash all non-Duration Treasures you have in play.",
                expansion=SET, on_gain=_mint_gain))
_reg("Mountebank", 5, _mountebank, "+$2. Each other player may discard a Curse. If they don't, they gain a Curse and a Copper.", extra_types=_ATTACK)
_reg("Rabble", 5, _rabble, "+3 Cards. Each other player reveals the top 3 cards of their deck, discards the Actions and Treasures, and puts the rest back in any order they choose.", extra_types=_ATTACK)
_treasure("Royal Seal", 5, 2, "$2. While this is in play, when you gain a card, you may put that card onto your deck.", on_gain_in_play=_royal_seal_gain)
_reg("Vault", 5, _vault, "+2 Cards. Discard any number of cards for +$1 each. Each other player may discard 2 cards, to draw a card.")
_treasure("Venture", 5, 1, "$1. When you play this, reveal cards from your deck until you reveal a Treasure. Discard the other cards. Play that Treasure.", on_play=_venture)
_treasure("War Chest", 5, 0, "The player to your left names a card. Gain a card costing up to $5 that hasn't been named for War Chests this turn.", on_play=_war_chest)
# $6
_reg("Goons", 6, _goons, "+1 Buy, +$2. Each other player discards down to 3 cards in hand. While this is in play, when you buy a card, +1 VP token.",
     extra_types=_ATTACK, on_gain_in_play=_goons_gain)
_treasure("Hoard", 6, 2, "$2. This turn, when you gain a Victory card, if you bought it, gain a Gold.", on_gain_in_play=_hoard_gain)
_reg("Grand Market", 6, _grand_market, "+1 Card, +1 Action, +1 Buy, +$2. You can't buy this if you have any Coppers in play.", can_buy_fn=_grand_market_restriction)
# $7
_treasure("Bank", 7, 0, "$1 per Treasure card you have in play (counting this).", coins_fn=_bank_coins)
_reg("Expand", 7, _expand, "Trash a card from your hand. Gain a card costing up to $3 more than it.")
_reg("Forge", 7, _forge, "Trash any number of cards from your hand. Gain a card with cost exactly equal to the total cost in coins of the trashed cards.")
_reg("King's Court", 7, _kings_court, "You may play an Action card from your hand three times.")
# $8
_reg("Peddler", 8, _peddler, "+1 Card, +1 Action, +$1. During your Buy phase, this costs $2 less per Action card you have in play, but not less than $0.", cost_mod=_peddler_discount)
