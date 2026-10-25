"""The Cornucopia expansion (1st edition): 13 Kingdom cards and 5 Prize cards.

What is new in the engine:

  * Differently named cards matters: Menagerie (hand), Harvest (top 4 of deck), Horn of Plenty (in play),
    Hunting Party (hand + deck search), Fairgrounds (all owned cards at scoring).
  * Prizes (``CardType.PRIZE``): 5 unique non-Supply cards (Bag of Gold, Diadem, Followers, Princess, Trusty Steed)
    placed in ``state.prizes`` when Tournament is in the Kingdom. Gained only via Tournament.
  * Young Witch & Bane pile: Setup adds an extra Kingdom pile costing $2 or $3 (0 Potions) marked as ``state.bane``.
    Defenders may reveal the Bane card from hand when Young Witch attacks to avoid gaining a Curse.
  * Horse Traders: Reaction to an Attack that sets itself aside from hand until the start of its owner's next turn,
    when it returns to hand and draws +1 Card.
"""

from __future__ import annotations

from .base import CardType, action, treasure, victory
from .registry import register

SET = "Cornucopia"
_ATTACK = (CardType.ATTACK,)
_REACTION = (CardType.REACTION,)
_PRIZE = (CardType.PRIZE,)


# ----------------------------------------------------------------- $2
def _hamlet(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    if ctx.hand:
        chosen = yield ctx.choose("Hamlet: you may discard a card for +1 Action.", ctx.hand, 0, 1)
        if chosen:
            ctx.discard(chosen[0])
            ctx.add_actions(1)
    if ctx.hand:
        chosen = yield ctx.choose("Hamlet: you may discard a card for +1 Buy.", ctx.hand, 0, 1)
        if chosen:
            ctx.discard(chosen[0])
            ctx.add_buys(1)


# ----------------------------------------------------------------- $3
def _fortune_teller(ctx):
    ctx.add_coins(2)
    targets = yield from ctx.attack()
    for p in targets:
        others, found = [], None
        while True:
            cards = ctx.take_to_set_aside(1, player=p, reveal=True)
            if not cards:
                break
            card = cards[0]
            if ctx.is_victory(card) or "curse" in ctx.card_types(card):
                found = card
                break
            others.append(card)
        for card in others:
            ctx.discard_set_aside(card, player=p)
        if found is not None:
            ctx.put_set_aside_on_deck(found, player=p)
            ctx.log(f"{ctx.name_of(p)} puts {found} onto their deck.")


def _menagerie(ctx):
    ctx.add_actions(1)
    hand = ctx.hand
    ctx.log(f"{ctx.player_name} reveals their hand: {', '.join(sorted(hand)) or 'nothing'}.", "reveal")
    if len(set(hand)) == len(hand):
        ctx.draw(3)
    else:
        ctx.draw(1)


# ----------------------------------------------------------------- $4
def _farming_village(ctx):
    ctx.add_actions(2)
    others, found = [], None
    while True:
        cards = ctx.take_to_set_aside(1, reveal=True)
        if not cards:
            break
        card = cards[0]
        if ctx.is_action(card) or ctx.is_treasure(card):
            found = card
            break
        others.append(card)
    for card in others:
        ctx.discard_set_aside(card)
    if found is not None:
        ctx.set_aside_to_hand(found)
        ctx.log(f"{ctx.player_name} puts {found} into their hand.")


def _horse_traders(ctx):
    ctx.add_buys(1)
    ctx.add_coins(3)
    hand = ctx.hand
    n = min(2, len(hand))
    if n == 0:
        return
    if n == len(hand):
        for card in hand:
            ctx.discard(card)
        return
    chosen = yield ctx.choose(f"Horse Traders: discard {n} card(s).", hand, n, n)
    for card in chosen:
        ctx.discard(card)


def _horse_traders_reaction(ctx):
    if "Horse Traders" in ctx.hand:
        ctx.put_on_mat("Horse Traders", "horse_traders")
        ctx.log(f"{ctx.player_name} sets aside Horse Traders until the start of their next turn.", "reveal")
    return
    yield


def _remake(ctx):
    for _ in range(2):
        hand = ctx.hand
        if not hand:
            return
        (trashed,) = yield ctx.choose("Remake: trash a card from your hand.", hand)
        ctx.trash(trashed)
        if ctx.potion_cost_of(trashed) == 0:
            target = ctx.cost_of(trashed) + 1
            options = ctx.gainable(target, exact=True)
            if options:
                card = options[0]
                if len(options) > 1:
                    (card,) = yield ctx.choose(f"Remake: gain a card costing exactly ${target}.", options)
                ctx.gain(card)


def _tournament(ctx):
    ctx.add_actions(1)
    revealed = set()
    for p in [ctx.player, *ctx.other_players()]:
        if "Province" in ctx.hand_of(p):
            chosen = yield ctx.choose(
                "Tournament: you may reveal a Province from your hand.",
                ("Province",), 0, 1, player=p,
            )
            if chosen:
                revealed.add(p)
                ctx.log(f"{ctx.name_of(p)} reveals Province.", "reveal")
    if ctx.player in revealed:
        ctx.discard("Province")
        prizes = list(ctx.prize_options())
        options = list(prizes)
        if "Duchy" in ctx.gainable(99) or (ctx.supply_count("Duchy") > 0 and not ctx.is_pile_walled("Duchy")):
            options.append("Duchy")
        if options:
            choice = options[0]
            if len(options) > 1:
                (choice,) = yield ctx.choose(
                    "Tournament: gain a Prize or a Duchy onto your deck.",
                    tuple(options),
                )
            if choice in prizes:
                ctx.gain_prize(choice, destination="deck")
            else:
                ctx.gain("Duchy", destination="deck")
    if not (revealed - {ctx.player}):
        ctx.draw(1)
        ctx.add_coins(1)


def _young_witch(ctx):
    ctx.draw(2)
    hand = ctx.hand
    n = min(2, len(hand))
    if n == len(hand) and n > 0:
        for card in hand:
            ctx.discard(card)
    elif n > 0:
        chosen = yield ctx.choose(f"Young Witch: discard {n} card(s).", hand, n, n)
        for card in chosen:
            ctx.discard(card)
    targets = yield from ctx.attack()
    bane = ctx.bane_card
    for p in targets:
        if bane and bane in ctx.hand_of(p):
            chosen = yield ctx.choose(
                f"{ctx.player_name} played Young Witch. You may reveal {bane} (Bane) to avoid gaining a Curse.",
                (bane,), 0, 1, player=p,
            )
            if chosen:
                ctx.log(f"{ctx.name_of(p)} reveals {bane} (Bane) and is unaffected.", "reveal")
                continue
        ctx.gain("Curse", player=p)


# ----------------------------------------------------------------- $5
def _harvest(ctx):
    cards = ctx.take_to_set_aside(4, reveal=True)
    unique = len(set(cards))
    for card in cards:
        ctx.discard_set_aside(card)
    if unique:
        ctx.add_coins(unique)
        ctx.log(f"Harvest gives +${unique} ({unique} differently named card(s)).")


def _horn_of_plenty(ctx):
    limit = len(set(ctx.in_play))
    options = ctx.gainable(limit)
    if not options:
        return
    card = options[0]
    if len(options) > 1:
        (card,) = yield ctx.choose(f"Horn of Plenty: gain a card costing up to ${limit}.", options)
    if ctx.gain(card) and ctx.is_victory(card):
        ctx.trash_self()


def _hunting_party(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    hand = ctx.hand
    ctx.log(f"{ctx.player_name} reveals their hand: {', '.join(sorted(hand)) or 'nothing'}.", "reveal")
    owned_in_hand = set(hand)
    others, found = [], None
    while True:
        cards = ctx.take_to_set_aside(1, reveal=True)
        if not cards:
            break
        card = cards[0]
        if card not in owned_in_hand:
            found = card
            break
        others.append(card)
    for card in others:
        ctx.discard_set_aside(card)
    if found is not None:
        ctx.set_aside_to_hand(found)
        ctx.log(f"{ctx.player_name} puts {found} into their hand.")


def _jester(ctx):
    ctx.add_coins(2)
    targets = yield from ctx.attack()
    for p in targets:
        card = ctx.discard_top_of_deck(player=p)
        if card is None:
            continue
        if ctx.is_victory(card):
            ctx.gain("Curse", player=p)
        elif ctx.supply_count(card) > 0:
            them = f"{ctx.name_of(p)} gains {card}"
            you = f"You gain {card}"
            (mode,) = yield ctx.choose(
                f"Jester: {ctx.name_of(p)} discarded {card}. Who gains a copy of it?",
                (you, them),
            )
            if mode == you:
                ctx.gain(card)
            else:
                ctx.gain(card, player=p)


# ----------------------------------------------------------------- $6
def _fairgrounds_score(cards) -> int:
    return 2 * (len(set(cards)) // 5)


# ----------------------------------------------------------------- Prizes ($0*)
def _bag_of_gold(ctx):
    ctx.add_actions(1)
    ctx.gain("Gold", destination="deck")


def _diadem(ctx):
    unused = ctx.actions_left
    if unused > 0:
        ctx.add_coins(unused)
        ctx.log(f"Diadem gives +${unused} for {unused} unused Action(s).")


def _followers(ctx):
    ctx.draw(2)
    ctx.gain("Estate")
    targets = yield from ctx.attack()
    for p in targets:
        ctx.gain("Curse", player=p)
        hand = ctx.hand_of(p)
        excess = len(hand) - 3
        if excess > 0:
            chosen = yield ctx.choose(
                f"{ctx.player_name}'s Followers: discard {excess} card(s) to get down to 3.",
                hand, excess, excess, player=p,
            )
            for card in chosen:
                ctx.discard(card, player=p)


def _princess(ctx):
    ctx.add_buys(1)


_STEED_OPTIONS = (
    "+2 Cards",
    "+2 Actions",
    "+$2",
    "Gain 4 Silvers and put your deck into your discard pile",
)


def _trusty_steed(ctx):
    chosen = yield ctx.choose("Trusty Steed: choose two different effects.", _STEED_OPTIONS, 2, 2)
    if "+2 Cards" in chosen:
        ctx.draw(2)
    if "+2 Actions" in chosen:
        ctx.add_actions(2)
    if "+$2" in chosen:
        ctx.add_coins(2)
    if "Gain 4 Silvers and put your deck into your discard pile" in chosen:
        for _ in range(4):
            ctx.gain("Silver")
        ctx.put_deck_in_discard()


# ------------------------------------------------------------ registration
def _reg(name, cost, fn, text, **kw):
    register(action(name, cost, fn, text, expansion=SET, **kw))


_reg("Hamlet", 2, _hamlet, "+1 Card, +1 Action. You may discard a card for +1 Action. You may discard a card for +1 Buy.")
_reg("Fortune Teller", 3, _fortune_teller, "+$2. Each other player reveals cards from the top of their deck until they reveal a Victory card or a Curse. They put it on top and discard the other revealed cards.",
     extra_types=_ATTACK)
_reg("Menagerie", 3, _menagerie, "+1 Action. Reveal your hand. If the revealed hand has no duplicate cards, +3 Cards. Otherwise, +1 Card.")
_reg("Farming Village", 4, _farming_village, "+2 Actions. Reveal cards from the top of your deck until you reveal an Action or Treasure card. Put that card into your hand and discard the other cards.")
_reg("Horse Traders", 4, _horse_traders, "+1 Buy, +$3. Discard 2 cards. Reaction: when another player plays an Attack card, you may first set this aside from your hand. If you do, then at the start of your next turn, +1 Card and return this to your hand.",
     extra_types=_REACTION, on_attack=_horse_traders_reaction)
_reg("Remake", 4, _remake, "Do this twice: Trash a card from your hand, then gain a card costing exactly $1 more than the trashed card.")
_reg("Tournament", 4, _tournament, "+1 Action. Each player may reveal a Province from their hand. If you do, discard it and gain any Prize (from the Prize pile) or a Duchy, onto your deck. If no-one else reveals a Province, +1 Card and +$1.")
_reg("Young Witch", 4, _young_witch, "+2 Cards. Discard 2 cards. Each other player may reveal a Bane card from their hand. If they don't, they gain a Curse. (Setup: an extra Kingdom pile costing $2 or $3 is the Bane pile.)",
     extra_types=_ATTACK)
_reg("Harvest", 5, _harvest, "Reveal the top 4 cards of your deck, then discard them. +$1 per differently named card revealed.")
register(treasure(
    "Horn of Plenty", 5, 0,
    text="$0. When you play this, gain a card costing up to $1 per differently named card you have in play (counting this). If it's a Victory card, trash this.",
    kingdom=True, expansion=SET, on_play=_horn_of_plenty,
))
_reg("Hunting Party", 5, _hunting_party, "+1 Card, +1 Action. Reveal your hand. Reveal cards from your deck until you reveal a card that isn't a duplicate of one in your hand. Put it into your hand and discard the rest.")
_reg("Jester", 5, _jester, "+$2. Each other player discards the top card of their deck. If it's a Victory card they gain a Curse; otherwise they gain a copy of the discarded card or you do, your choice.",
     extra_types=_ATTACK)
register(victory(
    "Fairgrounds", 6, score_fn=_fairgrounds_score,
    text="Worth 2 VP for every 5 differently named cards you have (round down).",
    kingdom=True, expansion=SET,
))

# Non-Supply Prizes (1 of each in the Prize pile when Tournament is in the Kingdom)
register(action(
    "Bag of Gold", 0, _bag_of_gold,
    "+1 Action. Gain a Gold onto your deck. (Not in the Supply.)",
    kingdom=False, extra_types=_PRIZE, expansion=SET,
))
register(treasure(
    "Diadem", 0, 2,
    text="$2. When you play this, +$1 per unused Action you have (Action, not Action card). (Not in the Supply.)",
    kingdom=False, expansion=SET, on_play=_diadem, extra_types=_PRIZE,
))
register(action(
    "Followers", 0, _followers,
    "+2 Cards. Gain an Estate. Each other player gains a Curse and discards down to 3 cards in hand. (Not in the Supply.)",
    kingdom=False, extra_types=(CardType.ATTACK, CardType.PRIZE), expansion=SET,
))
register(action(
    "Princess", 0, _princess,
    "+1 Buy. While this is in play, cards cost $2 less, but not less than $0. (Not in the Supply.)",
    kingdom=False, extra_types=_PRIZE, expansion=SET,
))
register(action(
    "Trusty Steed", 0, _trusty_steed,
    "Choose two: +2 Cards; +2 Actions; +$2; gain 4 Silvers and put your deck into your discard pile. (Not in the Supply.)",
    kingdom=False, extra_types=_PRIZE, expansion=SET,
))
