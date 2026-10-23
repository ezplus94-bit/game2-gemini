"""The Cornucopia & Guilds expansion (2011 / 2013): 26 Kingdom cards and 5 Prizes.

What is new compared with earlier sets, and where the engine supports it:
  * Prizes (Bag of Gold, Diadem, Followers, Princess, Trusty Steed): 5 non-supply cards created when
    Tournament is in the Kingdom (`state.prizes`), gained via Tournament when revealing a Province.
  * Bane pile (`state.bane_card`): an extra $2 or $3 Kingdom pile added to the Supply when Young Witch
    is in the Kingdom; revealing it from hand counters Young Witch's Attack.
  * Variety / unique-name rewards: Menagerie, Harvest, Horn of Plenty, Hunting Party, Fairgrounds.
  * Horse Traders: Reaction that sets itself aside from hand against an Attack and returns at the start
    of your next turn with +1 Card (`player.horse_traders_aside`).
  * Coffers (`player.coffers` and `SpendCoffer`): coin tokens on your mat that can be spent during the
    Buy phase for +$1 each (Candlestick Maker, Plaza, Baker, Butcher, Merchant Guild).
  * Overpay (`CardDef.on_overpay`): Stonemason, Doctor, Masterpiece, and Herald allow paying extra
    coins when bought for scaling bonus effects.
"""

from __future__ import annotations

from .base import CardDef, CardType, action, treasure, victory
from .registry import register

SET = "Cornucopia"
_ATTACK = (CardType.ATTACK,)
_REACTION = (CardType.REACTION,)

PRIZES = ("Bag of Gold", "Diadem", "Followers", "Princess", "Trusty Steed")


def _put_back_in_any_order(ctx, rest, source_name: str = "Doctor"):
    """Generator: put `rest` (in set_aside) back onto the deck in the player's chosen order."""
    rest = list(rest)
    order = []
    while len(rest) > 1:
        if len(set(rest)) == 1:
            order.extend(rest)
            rest = []
            break
        (top,) = yield ctx.choose(
            f"{source_name}: choose the next card to put back on top of your deck.",
            tuple(rest),
        )
        rest.remove(top)
        order.append(top)
    order.extend(rest)
    for card in reversed(order):
        ctx.put_set_aside_on_deck(card)
    if order:
        ctx.log(f"{ctx.player_name} puts {len(order)} card(s) back on their deck.")


# ===================================================================== Prizes ($0, non-Supply)
def _bag_of_gold(ctx):
    ctx.add_actions(1)
    ctx.gain("Gold", destination="deck")


def _diadem(ctx):
    if ctx.unused_actions > 0:
        ctx.add_coins(ctx.unused_actions)


def _followers(ctx):
    ctx.draw(2)
    ctx.gain("Estate")
    targets = yield from ctx.attack()
    for p in targets:
        ctx.gain("Curse", player=p)
        hand = ctx.hand_of(p)
        excess = len(hand) - 3
        if excess <= 0:
            continue
        chosen = yield ctx.choose(
            f"{ctx.player_name}'s Followers: discard {excess} card(s) to get down to 3.",
            hand, excess, excess, player=p,
        )
        for c in chosen:
            ctx.discard(c, player=p)


def _princess(ctx):
    ctx.add_buys(1)


_STEED_OPTIONS = (
    "+2 Cards",
    "+2 Actions",
    "+$2",
    "Gain 4 Silvers and discard deck",
)


def _trusty_steed(ctx):
    chosen = yield ctx.choose("Trusty Steed: choose two different options.", _STEED_OPTIONS, 2, 2)
    if "+2 Cards" in chosen:
        ctx.draw(2)
    if "+2 Actions" in chosen:
        ctx.add_actions(2)
    if "+$2" in chosen:
        ctx.add_coins(2)
    if "Gain 4 Silvers and discard deck" in chosen:
        for _ in range(4):
            ctx.gain("Silver")
        ctx.put_deck_into_discard()


register(CardDef(
    "Bag of Gold", 0, frozenset({CardType.ACTION}),
    on_play=_bag_of_gold,
    text="+1 Action. Gain a Gold, putting it on top of your deck. (Prize)",
    kingdom=False, expansion=SET,
))
register(CardDef(
    "Diadem", 0, frozenset({CardType.TREASURE}),
    coins=2, on_play=_diadem,
    text="$2. When you play this, +$1 per unused Action you have (Action, not Action card). (Prize)",
    kingdom=False, expansion=SET,
))
register(CardDef(
    "Followers", 0, frozenset({CardType.ACTION, CardType.ATTACK}),
    on_play=_followers,
    text="+2 Cards. Gain an Estate. Each other player gains a Curse and discards down to 3 cards in hand. (Prize)",
    kingdom=False, expansion=SET,
))
register(CardDef(
    "Princess", 0, frozenset({CardType.ACTION}),
    on_play=_princess,
    text="+1 Buy. While this is in play, cards cost $2 less, but not less than $0. (Prize)",
    kingdom=False, expansion=SET,
))
register(CardDef(
    "Trusty Steed", 0, frozenset({CardType.ACTION}),
    on_play=_trusty_steed,
    text="Choose two: +2 Cards; +2 Actions; +$2; gain 4 Silvers and put your deck into your discard pile. (Prize)",
    kingdom=False, expansion=SET,
))


# ===================================================================== Cornucopia Kingdom cards
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
        others = []
        found = None
        while True:
            cards = ctx.take_to_set_aside(1, player=p, reveal=True)
            if not cards:
                break
            card = cards[0]
            if ctx.is_victory(card) or ctx.is_curse(card):
                found = card
                break
            others.append(card)
        for c in others:
            ctx.discard_set_aside(c, player=p)
        if found is not None:
            ctx.put_set_aside_on_deck(found, player=p)


def _menagerie(ctx):
    ctx.add_actions(1)
    ctx.reveal_hand(ctx.player)
    hand = ctx.hand
    if len(set(hand)) == len(hand):
        ctx.draw(3)
    else:
        ctx.draw(1)


# ----------------------------------------------------------------- $4
def _farming_village(ctx):
    ctx.add_actions(2)
    others = []
    found = None
    while True:
        cards = ctx.take_to_set_aside(1, reveal=True)
        if not cards:
            break
        card = cards[0]
        if ctx.is_action(card) or ctx.is_treasure(card):
            found = card
            break
        others.append(card)
    if found is not None:
        ctx.set_aside_to_hand(found)
    for c in others:
        ctx.discard_set_aside(c)


def _horse_traders(ctx):
    ctx.add_buys(1)
    ctx.add_coins(3)
    hand = ctx.hand
    if not hand:
        return
    need = min(2, len(hand))
    chosen = yield ctx.choose(f"Horse Traders: discard {need} card(s).", hand, need, need)
    for c in chosen:
        ctx.discard(c)


def _horse_traders_reaction(ctx):
    ctx.set_aside_horse_traders()


def _remake(ctx):
    for _ in range(2):
        hand = ctx.hand
        if not hand:
            return
        (trashed,) = yield ctx.choose("Remake: trash a card from your hand.", hand)
        target = ctx.cost_of(trashed) + 1
        ctx.trash(trashed)
        options = ctx.gainable(target, exact=True)
        if options:
            (gained,) = yield ctx.choose(f"Remake: gain a card costing exactly ${target}.", options)
            ctx.gain(gained)


def _tournament(ctx):
    ctx.add_actions(1)
    me_revealed = False
    others_revealed = False
    if "Province" in ctx.hand:
        chosen = yield ctx.choose("Tournament: you may reveal a Province from your hand.", ("Province",), 0, 1)
        if chosen:
            ctx.log(f"{ctx.player_name} reveals Province.", "reveal")
            me_revealed = True
    for p in ctx.other_players():
        if ctx.is_invisible(p):
            continue
        if "Province" in ctx.hand_of(p):
            chosen = yield ctx.choose(
                "Tournament: you may reveal a Province from your hand.",
                ("Province",), 0, 1, player=p,
            )
            if chosen:
                ctx.log(f"{ctx.name_of(p)} reveals Province.", "reveal")
                others_revealed = True
    if me_revealed:
        ctx.discard("Province")
        options = list(ctx.available_prizes)
        if "Duchy" in ctx.gainable(max_cost=99):
            options.append("Duchy")
        if options:
            (pick,) = yield ctx.choose(
                "Tournament: gain a Prize or a Duchy onto your deck.",
                tuple(options),
            )
            if pick == "Duchy":
                ctx.gain("Duchy", destination="deck")
            else:
                ctx.gain_prize(pick, destination="deck")
    if not others_revealed:
        ctx.draw(1)
        ctx.add_coins(1)


def _young_witch(ctx):
    ctx.draw(2)
    hand = ctx.hand
    if hand:
        need = min(2, len(hand))
        chosen = yield ctx.choose(f"Young Witch: discard {need} card(s).", hand, need, need)
        for c in chosen:
            ctx.discard(c)
    targets = yield from ctx.attack()
    bane = ctx.bane_card
    for p in targets:
        if bane and bane in ctx.hand_of(p):
            chosen = yield ctx.choose(
                f"{ctx.player_name}'s Young Witch: you may reveal {bane} (Bane) to avoid gaining a Curse.",
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
    for c in cards:
        ctx.discard_set_aside(c)
    if unique:
        ctx.add_coins(unique)


def _horn_of_plenty(ctx):
    limit = len(set(ctx.in_play))
    options = ctx.gainable(max_cost=limit)
    if not options:
        return
    (gained,) = yield ctx.choose(f"Horn of Plenty: gain a card costing up to ${limit}.", options)
    ctx.gain(gained)
    if ctx.is_victory(gained):
        ctx.trash_self()


def _hunting_party(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.reveal_hand(ctx.player)
    hand_names = set(ctx.hand)
    others = []
    found = None
    while True:
        cards = ctx.take_to_set_aside(1, reveal=True)
        if not cards:
            break
        card = cards[0]
        if card not in hand_names:
            found = card
            break
        others.append(card)
    if found is not None:
        ctx.set_aside_to_hand(found)
    for c in others:
        ctx.discard_set_aside(c)


def _jester(ctx):
    ctx.add_coins(2)
    targets = yield from ctx.attack()
    for p in targets:
        discarded = ctx.discard_top_of_deck_for(p)
        if discarded is None:
            continue
        if ctx.is_victory(discarded):
            ctx.gain("Curse", player=p)
        elif ctx.supply_count(discarded) > 0:
            (who,) = yield ctx.choose(
                f"Jester: {ctx.name_of(p)} discarded {discarded}. Who gains a copy?",
                (f"You ({ctx.player_name})", ctx.name_of(p)),
            )
            if who.startswith("You"):
                ctx.gain(discarded)
            else:
                ctx.gain(discarded, player=p)


# ----------------------------------------------------------------- $6
def _fairgrounds_score(cards) -> int:
    return 2 * (len(set(cards)) // 5)


# ===================================================================== Guilds Kingdom cards
# ----------------------------------------------------------------- $2
def _candlestick_maker(ctx):
    ctx.add_actions(1)
    ctx.add_buys(1)
    ctx.add_coffers(1)


def _stonemason(ctx):
    hand = ctx.hand
    if not hand:
        return
    (trashed,) = yield ctx.choose("Stonemason: trash a card from your hand.", hand)
    cost = ctx.cost_of(trashed)
    ctx.trash(trashed)
    if cost < 1:
        return
    for _ in range(2):
        options = ctx.gainable(max_cost=cost - 1)
        if not options:
            break
        (gained,) = yield ctx.choose(f"Stonemason: gain a card costing up to ${cost - 1}.", options)
        ctx.gain(gained)


def _stonemason_overpay(ctx, amount: int):
    for _ in range(2):
        options = ctx.gainable(amount, card_type=CardType.ACTION, exact=True)
        if not options:
            break
        (gained,) = yield ctx.choose(
            f"Stonemason (overpay): gain an Action card costing exactly ${amount}.",
            options,
        )
        ctx.gain(gained)


# ----------------------------------------------------------------- $3
def _doctor(ctx):
    (named,) = yield ctx.choose("Doctor: name a card.", ctx.supply_names())
    ctx.log(f"{ctx.player_name} names {named}.")
    cards = ctx.take_to_set_aside(3, reveal=True)
    rest = []
    for c in cards:
        if c == named:
            ctx.trash_set_aside(c)
        else:
            rest.append(c)
    yield from _put_back_in_any_order(ctx, rest, "Doctor")


def _doctor_overpay(ctx, amount: int):
    for _ in range(amount):
        cards = ctx.take_to_set_aside(1, reveal=False)
        if not cards:
            break
        top = cards[0]
        (mode,) = yield ctx.choose(
            f"Doctor (overpay): top card is {top}. Trash it, discard it, or put it back?",
            ("Trash it", "Discard it", "Put it back"),
        )
        if mode == "Trash it":
            ctx.trash_set_aside(top)
        elif mode == "Discard it":
            ctx.discard_set_aside(top)
        else:
            ctx.put_set_aside_on_deck(top)


def _masterpiece_overpay(ctx, amount: int):
    for _ in range(amount):
        if not ctx.gain("Silver"):
            break


# ----------------------------------------------------------------- $4
def _advisor(ctx):
    ctx.add_actions(1)
    cards = ctx.take_to_set_aside(3, reveal=True)
    if not cards:
        return
    others = [p for p in ctx.other_players() if not ctx.is_invisible(p)]
    chooser = others[0] if others else ctx.player
    if len(set(cards)) == 1:
        discarded = cards[0]
    else:
        (discarded,) = yield ctx.choose(
            f"Advisor: choose one of {ctx.player_name}'s revealed cards to discard.",
            tuple(cards), 1, 1, player=chooser,
        )
    cards.remove(discarded)
    ctx.discard_set_aside(discarded)
    for c in cards:
        ctx.set_aside_to_hand(c)


def _herald(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    cards = ctx.take_to_set_aside(1, reveal=True)
    if not cards:
        return
    top = cards[0]
    if ctx.is_action(top):
        ctx.put_in_play(top, "set_aside")
        yield from ctx.resolve(top)
    else:
        ctx.put_set_aside_on_deck(top)


def _herald_overpay(ctx, amount: int):
    for _ in range(amount):
        options = tuple(sorted(set(ctx.discard_pile)))
        if not options:
            break
        (card,) = yield ctx.choose(
            "Herald (overpay): put a card from your discard pile onto your deck.",
            options,
        )
        ctx.put_discard_on_deck(card)


def _plaza(ctx):
    ctx.draw(1)
    ctx.add_actions(2)
    treasures = tuple(sorted({c for c in ctx.hand if ctx.is_treasure(c)}))
    if not treasures:
        return
    chosen = yield ctx.choose("Plaza: you may discard a Treasure card for +1 Coffer.", treasures, 0, 1)
    if chosen:
        ctx.discard(chosen[0])
        ctx.add_coffers(1)


def _taxman(ctx):
    treasures = tuple(sorted({c for c in ctx.hand if ctx.is_treasure(c)}))
    if not treasures:
        return
    chosen = yield ctx.choose("Taxman: you may trash a Treasure from your hand.", treasures, 0, 1)
    if not chosen:
        return
    trashed = chosen[0]
    limit = ctx.cost_of(trashed) + 3
    ctx.trash(trashed)
    targets = yield from ctx.attack()
    for p in targets:
        if len(ctx.hand_of(p)) >= 5:
            if trashed in ctx.hand_of(p):
                ctx.discard(trashed, player=p)
            else:
                ctx.reveal_hand(p)
    gains = ctx.gainable(limit, CardType.TREASURE)
    if gains:
        (gained,) = yield ctx.choose(
            f"Taxman: gain a Treasure costing up to ${limit} onto your deck.",
            gains,
        )
        ctx.gain(gained, destination="deck")


# ----------------------------------------------------------------- $5
def _baker(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.add_coffers(1)


def _butcher(ctx):
    ctx.add_coffers(2)
    hand = ctx.hand
    if not hand:
        return
    chosen = yield ctx.choose("Butcher: you may trash a card from your hand.", hand, 0, 1)
    if not chosen:
        return
    trashed = chosen[0]
    base_cost = ctx.cost_of(trashed)
    ctx.trash(trashed)
    spent = 0
    if ctx.coffers > 0:
        opts = tuple(str(n) for n in range(ctx.coffers + 1))
        (pick,) = yield ctx.choose(
            f"Butcher: choose how many Coffers to spend (up to {ctx.coffers}).",
            opts,
        )
        spent = int(pick)
        if spent > 0:
            ctx.remove_coffers(spent)
    limit = base_cost + spent
    options = ctx.gainable(max_cost=limit)
    if options:
        (gained,) = yield ctx.choose(f"Butcher: gain a card costing up to ${limit}.", options)
        ctx.gain(gained)


def _journeyman(ctx):
    (named,) = yield ctx.choose("Journeyman: name a card.", ctx.supply_names())
    ctx.log(f"{ctx.player_name} names {named}.")
    found, others = [], []
    while len(found) < 3:
        cards = ctx.take_to_set_aside(1, reveal=True)
        if not cards:
            break
        card = cards[0]
        if card == named:
            others.append(card)
        else:
            found.append(card)
    for c in found:
        ctx.set_aside_to_hand(c)
    for c in others:
        ctx.discard_set_aside(c)


def _merchant_guild(ctx):
    ctx.add_buys(1)
    ctx.add_coins(1)


def _soothsayer(ctx):
    ctx.gain("Gold")
    targets = yield from ctx.attack()
    for p in targets:
        if ctx.gain("Curse", player=p):
            ctx.draw(1, player=p)


# ------------------------------------------------------------ registration
def _reg(name, cost, fn, text, **kw):
    register(action(name, cost, fn, text, expansion=SET, **kw))


# Cornucopia (13)
_reg("Hamlet", 2, _hamlet, "+1 Card, +1 Action. You may discard a card for +1 Action. You may discard a card for +1 Buy.")
_reg("Fortune Teller", 3, _fortune_teller, "+$2. Each other player reveals cards from the top of their deck until they reveal a Victory card or a Curse. They put it on top and discard the rest.", extra_types=_ATTACK)
_reg("Menagerie", 3, _menagerie, "+1 Action. Reveal your hand. If the revealed cards all have different names, +3 Cards. Otherwise, +1 Card.")
_reg("Farming Village", 4, _farming_village, "+2 Actions. Reveal cards from the top of your deck until you reveal an Action or Treasure card. Put that card into your hand and discard the rest.")
_reg("Horse Traders", 4, _horse_traders, "+1 Buy, +$3. Discard 2 cards. When another player plays an Attack card, you may first set this aside from your hand. If you do, then at the start of your next turn, +1 Card and return this to your hand.", extra_types=_REACTION, on_attack=_horse_traders_reaction)
_reg("Remake", 4, _remake, "Do this twice: Trash a card from your hand, then gain a card costing exactly $1 more than it.")
_reg("Tournament", 4, _tournament, "+1 Action. Each player may reveal a Province from their hand. If you do, discard it and gain a Prize (from the Prize pile) or a Duchy, onto your deck. If no one else does, +1 Card and +$1.")
_reg("Young Witch", 4, _young_witch, "+2 Cards. Discard 2 cards. Each other player may reveal a Bane card from their hand; if they don't, they gain a Curse. Setup: Add an extra Kingdom card pile costing $2 or $3 to the Supply. Cards from that pile are Bane cards.", extra_types=_ATTACK)
_reg("Harvest", 5, _harvest, "Reveal the top 4 cards of your deck, then discard them. +$1 per differently named card revealed.")
register(treasure(
    "Horn of Plenty", 5, 0,
    text="$0. When you play this, gain a card costing up to $1 per differently named card you have in play (counting this). If it's a Victory card, trash this.",
    on_play=_horn_of_plenty, kingdom=True, expansion=SET,
))
_reg("Hunting Party", 5, _hunting_party, "+1 Card, +1 Action. Reveal your hand. Reveal cards from your deck until you reveal a card that isn't a duplicate of one in your hand. Put it into your hand and discard the rest.")
_reg("Jester", 5, _jester, "+$2. Each other player discards the top card of their deck. If it's a Victory card, they gain a Curse. Otherwise, they gain a copy of the discarded card or you do, your choice.", extra_types=_ATTACK)
register(victory(
    "Fairgrounds", 6, score_fn=_fairgrounds_score,
    text="Worth 2 VP for every 5 differently named cards in your deck (round down).",
    kingdom=True, expansion=SET,
))

# Guilds (13)
_reg("Candlestick Maker", 2, _candlestick_maker, "+1 Action, +1 Buy, +1 Coffer.")
_reg("Stonemason", 2, _stonemason, "Trash a card from your hand. Gain 2 cards each costing less than it. When you buy this, you may overpay for it. If you do, gain 2 Action cards each costing the amount you overpaid.", on_overpay=_stonemason_overpay)
_reg("Doctor", 3, _doctor, "Name a card. Reveal the top 3 cards of your deck. Trash the matches. Put the rest back in any order. When you buy this, you may overpay for it. For each $1 you overpaid, look at the top card of your deck; trash it, discard it, or put it back.", on_overpay=_doctor_overpay)
register(treasure(
    "Masterpiece", 3, 1,
    text="$1. When you buy this, you may overpay for it. For each $1 you overpaid, gain a Silver.",
    kingdom=True, expansion=SET, on_overpay=_masterpiece_overpay,
))
_reg("Advisor", 4, _advisor, "+1 Action. Reveal the top 3 cards of your deck. The player to your left chooses one of them. Discard that card and put the rest into your hand.")
_reg("Herald", 4, _herald, "+1 Card, +1 Action. Reveal the top card of your deck. If it is an Action, play it. When you buy this, you may overpay for it. For each $1 you overpaid, look through your discard pile and put a card from it onto your deck.", on_overpay=_herald_overpay)
_reg("Plaza", 4, _plaza, "+1 Card, +2 Actions. You may discard a Treasure card for +1 Coffer.")
_reg("Taxman", 4, _taxman, "You may trash a Treasure from your hand. Each other player with 5 or more cards in hand discards a copy of it (or reveals a hand without it). Gain a Treasure onto your deck costing up to $3 more than it.", extra_types=_ATTACK)
_reg("Baker", 5, _baker, "+1 Card, +1 Action, +1 Coffer. Setup: Each player takes 1 Coffer.")
_reg("Butcher", 5, _butcher, "+2 Coffers. You may trash a card from your hand. If you do, remove any number of tokens from your Coffers and gain a card costing up to the cost of the trashed card plus $1 per token removed.")
_reg("Journeyman", 5, _journeyman, "Name a card. Reveal cards from your deck until you reveal 3 cards that are not the named card. Put those cards into your hand and discard the rest.")
_reg("Merchant Guild", 5, _merchant_guild, "+1 Buy, +$1. While this is in play, when you buy a card, +1 Coffer.")
_reg("Soothsayer", 5, _soothsayer, "Gain a Gold. Each other player gains a Curse, and if they did, draws a card.", extra_types=_ATTACK)
