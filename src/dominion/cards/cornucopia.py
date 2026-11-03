"""Cornucopia & Guilds: the second edition (2024) and the cards it replaced, 34 Kingdom cards in all.

The 2024 edition combines Cornucopia (2011) and Guilds (2012). It removed eight cards (Fortune Teller, Farming Village, Horse
Traders, Tournament, Harvest from Cornucopia; Doctor, Masterpiece, Taxman from Guilds) and added eight (Carnival, Farmhands,
Farrier, Ferryman, Footpad, Infirmary, Joust, Shop). All 34 are available; cards in both editions use the 2024 wording.
The five Prizes (for Tournament) and the six Rewards (for Joust) are not in the Supply.

What is new in the engine:

  * Coffers (``PlayerState.coffers``): coin tokens, spent for +$1 each with the ``SpendCoffers`` action.
  * Overpay: a card marked ``overpay`` may be bought for more than it costs (``Buy(card, overpay)``); its ``on_overpay``
    effect runs when it is gained (Stonemason, Doctor, Masterpiece, Herald, Farrier, Infirmary).
  * Piles outside the Supply (``GameState.offsupply``): Prizes, Rewards and Ferryman's pile; ``ctx.gain_from_offsupply``.
  * Young Witch's Bane: an extra Kingdom pile (``GameState.bane``) picked from the seed; Ferryman's extra pile likewise.
  * Cards that wait for the next turn without being in play: Farmhands, Horse Traders (``DurationEntry`` with no card).
  * Footpad: while it is in the game, gaining a card in an Action phase draws a card (``GameState.footpad``).
  * Princess: ``CardDef.cost_aura``. Merchant Guild: a trigger at the end of the Buy phase.
"""

from __future__ import annotations

from .alchemy import _put_back_in_any_order
from .base import CardDef, CardType, action, treasure
from .registry import get_card, register

SET = "Cornucopia & Guilds"
_ATTACK = (CardType.ATTACK,)


def _discard_exactly(ctx, n, prompt):
    hand = ctx.hand
    n = min(n, len(hand))
    if n:
        chosen = yield ctx.choose(prompt, hand, n, n)
        for card in chosen:
            ctx.discard(card)


# ================================================================== Actions of the second edition
def _advisor(ctx):
    ctx.add_actions(1)
    cards = ctx.take_to_set_aside(3, reveal=True)
    if not cards:
        return
    left = ctx.left_player()
    (card,) = yield ctx.choose(f"Advisor ({ctx.player_name}): choose one of the revealed cards to discard.", tuple(cards), player=left)
    cards.remove(card)
    ctx.discard_set_aside(card)
    for other in cards:
        ctx.set_aside_to_hand(other)


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
    ctx.trash(trashed)
    tokens = ctx.coffers
    spend = 0
    if tokens:
        options = tuple(f"Remove {n} Coffers token(s)" for n in range(0, tokens + 1))
        (answer,) = yield ctx.choose("Butcher: remove Coffers tokens to gain a more expensive card?", options)
        spend = int(answer.split()[1])
        ctx.remove_coffers(spend)
    limit = ctx.cost_of(trashed) + spend
    gains = ctx.gainable(limit)
    if gains:
        (card,) = yield ctx.choose(f"Butcher: gain a card costing up to ${limit}.", gains)
        ctx.gain(card)


def _candlestick_maker(ctx):
    ctx.add_actions(1)
    ctx.add_buys(1)
    ctx.add_coffers(1)


def _carnival(ctx):
    cards = ctx.take_to_set_aside(4, reveal=True)
    seen = set()
    for card in cards:
        if card not in seen:
            seen.add(card)
            ctx.set_aside_to_hand(card)
        else:
            ctx.discard_set_aside(card)
    return
    yield


def _farmhands(ctx):
    ctx.draw(1)
    ctx.add_actions(2)
    return
    yield


def _farmhands_gain(ctx, event):
    options = tuple(sorted({c for c in ctx.hand if ctx.is_action(c) or ctx.is_treasure(c)}))
    if not options:
        return
    chosen = yield ctx.choose("Farmhands: you may set aside an Action or Treasure from your hand to play at the start of your next turn.",
                              options, 0, 1)
    if chosen:
        ctx.put_on_mat(chosen[0], "farmhands")
        ctx.log(f"{ctx.player_name} sets a card aside with Farmhands.")
        ctx.add_duration(_farmhands_start, chosen[0], cards=())


def _farmhands_start(ctx, entry):
    card = entry.data
    if card not in ctx.mat_cards("farmhands"):
        return
    ctx.put_on_mat(card, "in_play", source="farmhands")
    ctx.log(f"{ctx.player_name} plays {card} (set aside by Farmhands).")
    if ctx.is_action(card):
        yield from ctx.resolve(card)
    else:
        yield from ctx.resolve_treasure(card)


def _farrier(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.add_buys(1)


def _farrier_overpay(ctx, event):
    ctx.add_extra_draw(event.overpaid)
    ctx.log(f"Farrier: {ctx.player_name} will draw {event.overpaid} extra card(s) at the end of this turn.")


def _ferryman(ctx):
    ctx.draw(2)
    ctx.add_actions(1)
    yield from _discard_exactly(ctx, 1, "Ferryman: discard a card.")


def _ferryman_gain(ctx, event):
    pile = ctx.ferryman_name
    if pile and ctx.gain_from_offsupply(pile):
        return
    return
    yield


def _footpad(ctx):
    ctx.add_coffers(2)
    targets = yield from ctx.attack()
    for p in targets:
        hand = ctx.hand_of(p)
        excess = len(hand) - 3
        if excess > 0:
            chosen = yield ctx.choose(f"{ctx.player_name}'s Footpad: discard {excess} card(s) to get down to 3.", hand, excess, excess, player=p)
            for card in chosen:
                ctx.discard(card, player=p)


def _hamlet(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    hand = ctx.hand
    if hand:
        chosen = yield ctx.choose("Hamlet: you may discard a card for +1 Action.", hand, 0, 1)
        if chosen:
            ctx.discard(chosen[0])
            ctx.add_actions(1)
    hand = ctx.hand
    if hand:
        chosen = yield ctx.choose("Hamlet: you may discard a card for +1 Buy.", hand, 0, 1)
        if chosen:
            ctx.discard(chosen[0])
            ctx.add_buys(1)


def _herald(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    cards = ctx.take_to_set_aside(1, reveal=True)
    if not cards:
        return
    card = cards[0]
    if ctx.is_action(card):
        ctx.put_in_play(card, "set_aside")
        yield from ctx.resolve(card)
    else:
        ctx.put_set_aside_on_deck(card)
    return


def _herald_overpay(ctx, event):
    for _ in range(event.overpaid):
        options = tuple(sorted(set(ctx.discard_pile)))
        if not options:
            break
        (card,) = yield ctx.choose("Herald: put a card from your discard pile onto your deck.", options)
        ctx.put_discard_on_deck(card)


def _infirmary(ctx):
    ctx.draw(1)
    hand = ctx.hand
    if hand:
        chosen = yield ctx.choose("Infirmary: you may trash a card from your hand.", hand, 0, 1)
        if chosen:
            ctx.trash(chosen[0])


def _infirmary_overpay(ctx, event):
    if event.zone is None or "Infirmary" not in getattr(ctx._me(), event.zone):
        return
    ctx.put_on_mat("Infirmary", "in_play", source=event.zone)
    ctx.log(f"{ctx.player_name} plays Infirmary once per $1 overpaid.")
    for _ in range(event.overpaid):
        yield from ctx.resolve("Infirmary")


def _jester(ctx):
    ctx.add_coins(2)
    targets = yield from ctx.attack()
    for p in targets:
        card = ctx.discard_top_of_deck(player=p)
        if card is None:
            continue
        if ctx.is_victory(card):
            ctx.gain("Curse", player=p)
            continue
        if ctx.supply_count(card) <= 0:
            continue
        (mode,) = yield ctx.choose(f"Jester: {ctx.name_of(p)} discarded {card}. Who gains a copy?",
                                   (f"{ctx.name_of(p)} gains a copy", "You gain a copy"))
        ctx.gain(card, player=p if mode != "You gain a copy" else None)


def _journeyman(ctx):
    (name,) = yield ctx.choose("Journeyman: name a card.", ctx.supply_names())
    ctx.log(f"{ctx.player_name} names {name}.")
    kept, others = [], []
    while len(kept) < 3:
        cards = ctx.take_to_set_aside(1, reveal=True)
        if not cards:
            break
        if cards[0] == name:
            others.append(cards[0])
        else:
            kept.append(cards[0])
    for card in kept:
        ctx.set_aside_to_hand(card)
    for card in others:
        ctx.discard_set_aside(card)


def _joust(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.add_coins(1)
    rewards = ctx.offsupply_names()
    rewards = tuple(r for r in rewards if get_card(r).is_type(CardType.REWARD))
    if "Province" not in ctx.hand or not rewards:
        return
    chosen = yield ctx.choose("Joust: you may set aside a Province from your hand to gain a Reward to your hand.", ("Province",), 0, 1)
    if not chosen:
        return
    ctx.put_on_mat("Province", "joust_aside")
    ctx.log(f"{ctx.player_name} sets aside a Province (discarded at the end of the turn).", "reveal")
    (reward,) = yield ctx.choose("Joust: choose a Reward to gain to your hand.", rewards)
    ctx.gain_from_offsupply(reward, destination="hand")


def _menagerie(ctx):
    ctx.add_actions(1)
    hand = ctx.hand
    ctx.log(f"{ctx.player_name} reveals their hand: {', '.join(sorted(hand)) or 'nothing'}.", "reveal")
    ctx.draw(3 if len(set(hand)) == len(hand) else 1)
    return
    yield


def _merchant_guild(ctx):
    ctx.add_buys(1)
    ctx.add_coins(1)
    ctx.add_trigger("buy_phase_end", _merchant_guild_end)
    return
    yield


def _merchant_guild_end(ctx, trigger):
    n = ctx.buy_phase_gains()
    if n:
        ctx.log(f"Merchant Guild: {n} card(s) gained this Buy phase.")
        ctx.add_coffers(n)


def _plaza(ctx):
    ctx.draw(1)
    ctx.add_actions(2)
    treasures = tuple(sorted({c for c in ctx.hand if ctx.is_treasure(c)}))
    if not treasures:
        return
    chosen = yield ctx.choose("Plaza: you may discard a Treasure for +1 Coffers.", treasures, 0, 1)
    if chosen:
        ctx.discard(chosen[0])
        ctx.add_coffers(1)


def _remake(ctx):
    for _ in range(2):
        hand = ctx.hand
        if not hand:
            return
        (trashed,) = yield ctx.choose("Remake: trash a card from your hand.", hand)
        ctx.trash(trashed)
        target = ctx.cost_of(trashed) + 1
        options = ctx.gainable(target, exact=True)
        if options:
            (card,) = yield ctx.choose(f"Remake: gain a card costing exactly ${target}.", options)
            ctx.gain(card)


def _shop(ctx):
    ctx.draw(1)
    ctx.add_coins(1)
    options = tuple(sorted({c for c in ctx.hand if ctx.is_action(c) and c not in ctx.in_play}))
    if not options:
        return
    chosen = yield ctx.choose("Shop: you may play an Action card from your hand that you don't have a copy of in play.", options, 0, 1)
    if chosen:
        ctx.put_in_play(chosen[0], "hand")
        yield from ctx.resolve(chosen[0])


def _soothsayer(ctx):
    ctx.gain("Gold")
    targets = yield from ctx.attack()
    for p in targets:
        if ctx.gain("Curse", player=p):
            ctx.draw(1, player=p)


def _stonemason(ctx):
    hand = ctx.hand
    if not hand:
        return
    (trashed,) = yield ctx.choose("Stonemason: trash a card from your hand.", hand)
    ctx.trash(trashed)
    limit = ctx.cost_of(trashed) - 1
    for _ in range(2):
        options = ctx.gainable(limit) if limit >= 0 else ()
        if not options:
            return
        (card,) = yield ctx.choose(f"Stonemason: gain a card costing less than the trashed card (up to ${limit}).", options)
        ctx.gain(card)


def _stonemason_overpay(ctx, event):
    for _ in range(2):
        options = ctx.gainable(event.overpaid, CardType.ACTION, exact=True)
        if not options:
            return
        (card,) = yield ctx.choose(f"Stonemason overpay: gain an Action card costing exactly ${event.overpaid}.", options)
        ctx.gain(card)


def _young_witch(ctx):
    ctx.draw(2)
    yield from _discard_exactly(ctx, 2, "Young Witch: discard 2 cards.")
    targets = yield from ctx.attack()
    bane = ctx.bane_name
    for p in targets:
        if bane and bane in ctx.hand_of(p):
            chosen = yield ctx.choose(f"{ctx.player_name}'s Young Witch: you may reveal the Bane card ({bane}) to be unaffected.",
                                      (bane,), 0, 1, player=p)
            if chosen:
                ctx.log(f"{ctx.name_of(p)} reveals the Bane card, {bane}, and is unaffected.", "reveal")
                continue
        ctx.gain("Curse", player=p)


def _hunting_party(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    hand = ctx.hand
    ctx.log(f"{ctx.player_name} reveals their hand: {', '.join(sorted(hand)) or 'nothing'}.", "reveal")
    others = []
    while True:
        cards = ctx.take_to_set_aside(1, reveal=True)
        if not cards:
            break
        if cards[0] in hand:
            others.append(cards[0])
        else:
            ctx.set_aside_to_hand(cards[0])
            break
    for card in others:
        ctx.discard_set_aside(card)
    return
    yield


# ================================================================== Treasures and Victory
def _horn_of_plenty(ctx):
    n = ctx.differently_named_in_play()
    options = ctx.gainable(n)
    if not options:
        return
    (card,) = yield ctx.choose(f"Horn of Plenty: gain a card costing up to ${n} (one per differently named card in play).", options)
    ctx.gain(card)
    if ctx.is_victory(card):
        ctx.trash_self()


def _fairgrounds_score(cards) -> int:
    return 2 * (len(set(cards)) // 5)


# ================================================================== First edition cards that the second edition removed
def _farming_village(ctx):
    ctx.add_actions(2)
    others = []
    while True:
        cards = ctx.take_to_set_aside(1, reveal=True)
        if not cards:
            break
        if ctx.is_action(cards[0]) or ctx.is_treasure(cards[0]):
            ctx.set_aside_to_hand(cards[0])
            break
        others.append(cards[0])
    for card in others:
        ctx.discard_set_aside(card)
    return
    yield


def _fortune_teller(ctx):
    ctx.add_coins(2)
    targets = yield from ctx.attack()
    for p in targets:
        others, found = [], None
        while True:
            cards = ctx.take_to_set_aside(1, player=p, reveal=True)
            if not cards:
                break
            if ctx.is_victory(cards[0]) or "curse" in ctx.card_types(cards[0]):
                found = cards[0]
                break
            others.append(cards[0])
        for card in others:
            ctx.discard_set_aside(card, player=p)
        if found:
            ctx.put_set_aside_on_deck(found, player=p)


def _harvest(ctx):
    cards = ctx.take_to_set_aside(4, reveal=True)
    for card in cards:
        ctx.discard_set_aside(card)
    ctx.add_coins(len(set(cards)))
    return
    yield


def _horse_traders(ctx):
    ctx.add_buys(1)
    ctx.add_coins(3)
    yield from _discard_exactly(ctx, 2, "Horse Traders: discard 2 cards.")


def _horse_traders_reaction(ctx):
    ctx.put_on_mat("Horse Traders", "haven")
    ctx.log(f"{ctx.player_name} sets Horse Traders aside.", "reveal")
    ctx.add_duration(_horse_traders_return, None, cards=())
    return
    yield


def _horse_traders_return(ctx, entry):
    if "Horse Traders" in ctx.mat_cards("haven"):
        ctx.put_on_mat("Horse Traders", "hand", source="haven")
        ctx.log(f"{ctx.player_name} gets Horse Traders back and draws a card.")
        ctx.draw(1)


def _tournament(ctx):
    ctx.add_actions(1)
    revealed = []
    for p in [ctx.player, *ctx.other_players()]:
        if "Province" in ctx.hand_of(p):
            chosen = yield ctx.choose(f"{ctx.player_name}'s Tournament: you may reveal a Province from your hand.",
                                      ("Province",), 0, 1, player=p)
            if chosen:
                ctx.log(f"{ctx.name_of(p)} reveals a Province.", "reveal")
                revealed.append(p)
    if ctx.player in revealed:
        ctx.discard("Province")
        prizes = tuple(n for n in ctx.offsupply_names() if get_card(n).is_type(CardType.PRIZE))
        options = (*prizes, "Duchy") if ctx.supply_count("Duchy") > 0 else prizes
        if options:
            (card,) = yield ctx.choose("Tournament: gain a Prize, or a Duchy onto your deck.", options)
            if card == "Duchy":
                ctx.gain("Duchy", destination="deck")
            else:
                ctx.gain_from_offsupply(card, destination="deck")
    if not any(p != ctx.player for p in revealed):
        ctx.draw(1)
        ctx.add_coins(1)


def _doctor(ctx):
    (name,) = yield ctx.choose("Doctor: name a card.", ctx.supply_names())
    ctx.log(f"{ctx.player_name} names {name}.")
    cards = ctx.take_to_set_aside(3, reveal=True)
    rest = []
    for card in cards:
        if card == name:
            ctx.trash_set_aside(card)
        else:
            rest.append(card)
    yield from _put_back_in_any_order(ctx, rest)


def _doctor_overpay(ctx, event):
    for _ in range(event.overpaid):
        cards = ctx.take_to_set_aside(1)
        if not cards:
            return
        (mode,) = yield ctx.choose(f"Doctor overpay: the top card of your deck is {cards[0]}.", ("Trash it", "Discard it", "Put it back"))
        if mode == "Trash it":
            ctx.trash_set_aside(cards[0])
        elif mode == "Discard it":
            ctx.discard_set_aside(cards[0])
        else:
            ctx.put_set_aside_on_deck(cards[0])


def _masterpiece_overpay(ctx, event):
    for _ in range(event.overpaid):
        ctx.gain("Silver")
    return
    yield


def _taxman(ctx):
    treasures = tuple(sorted({c for c in ctx.hand if ctx.is_treasure(c)}))
    if not treasures:
        return
    chosen = yield ctx.choose("Taxman: you may trash a Treasure from your hand.", treasures, 0, 1)
    if not chosen:
        return
    trashed = chosen[0]
    ctx.trash(trashed)
    targets = yield from ctx.attack()
    for p in targets:
        hand = ctx.hand_of(p)
        if len(hand) < 5:
            continue
        if trashed in hand:
            ctx.discard(trashed, player=p)
        else:
            ctx.log(f"{ctx.name_of(p)} reveals a hand without {trashed}: {', '.join(sorted(hand))}.", "reveal")
    limit = ctx.cost_of(trashed) + 3
    options = ctx.gainable(limit, CardType.TREASURE)
    if options:
        (card,) = yield ctx.choose(f"Taxman: gain a Treasure costing up to ${limit} onto your deck.", options)
        ctx.gain(card, destination="deck")


# ================================================================== Prizes (first edition)
def _bag_of_gold(ctx):
    ctx.add_actions(1)
    ctx.gain("Gold", destination="deck")


def _diadem_coins(state, player):
    return 2 + state.actions                         # $2, and +$1 per unused Action


def _followers(ctx):
    ctx.draw(2)
    ctx.gain("Estate")
    targets = yield from ctx.attack()
    for p in targets:
        ctx.gain("Curse", player=p)
        hand = ctx.hand_of(p)
        excess = len(hand) - 3
        if excess > 0:
            chosen = yield ctx.choose(f"{ctx.player_name}'s Followers: discard {excess} card(s) to get down to 3.", hand, excess, excess, player=p)
            for card in chosen:
                ctx.discard(card, player=p)


def _princess(ctx):
    ctx.add_buys(1)


def _trusty_steed(ctx):
    options = ("+2 Cards", "+2 Actions", "+$2", "Gain 4 Silvers and put your deck into your discard pile")
    chosen = yield ctx.choose("Trusty Steed: choose two.", options, 2, 2)
    if "+2 Cards" in chosen:
        ctx.draw(2)
    if "+2 Actions" in chosen:
        ctx.add_actions(2)
    if "+$2" in chosen:
        ctx.add_coins(2)
    if options[3] in chosen:
        for _ in range(4):
            ctx.gain("Silver")
        ctx.put_deck_into_discard()


# ================================================================== Rewards (second edition)
def _coronet(ctx):
    actions = tuple(sorted({c for c in ctx.hand if ctx.is_action(c) and not get_card(c).is_type(CardType.REWARD)}))
    if actions:
        chosen = yield ctx.choose("Coronet: you may play a non-Reward Action from your hand twice.", actions, 0, 1)
        if chosen:
            ctx.put_in_play(chosen[0], "hand")
            yield from ctx.resolve(chosen[0])
            yield from ctx.resolve(chosen[0])
    treasures = tuple(sorted({c for c in ctx.hand if ctx.is_treasure(c) and not get_card(c).is_type(CardType.REWARD)}))
    if treasures:
        chosen = yield ctx.choose("Coronet: you may play a non-Reward Treasure from your hand twice.", treasures, 0, 1)
        if chosen:
            yield from ctx.play_treasure(chosen[0], "hand")
            yield from ctx.play_treasure(chosen[0], "in_play")


def _courser(ctx):
    options = ("+2 Cards", "+2 Actions", "+$2", "Gain 4 Silvers")
    chosen = yield ctx.choose("Courser: choose two different things.", options, 2, 2)
    if "+2 Cards" in chosen:
        ctx.draw(2)
    if "+2 Actions" in chosen:
        ctx.add_actions(2)
    if "+$2" in chosen:
        ctx.add_coins(2)
    if "Gain 4 Silvers" in chosen:
        for _ in range(4):
            ctx.gain("Silver")


def _demesne(ctx):
    ctx.add_actions(2)
    ctx.add_buys(2)
    ctx.gain("Gold")
    return
    yield


def _housecarl(ctx):
    n = len({c for c in ctx.in_play if ctx.is_action(c)})
    if n:
        ctx.draw(n)
    return
    yield


def _huge_turnip(ctx):
    ctx.add_coffers(2)
    ctx.add_coins(ctx.coffers)
    ctx.log(f"Huge Turnip gives +${ctx.coffers} (one per Coffers token).")
    return
    yield


def _renown(ctx):
    ctx.add_buys(1)
    ctx.reduce_costs(1)
    return
    yield


# ------------------------------------------------------------ registration
def _reg(name, cost, fn, text, **kw):
    register(action(name, cost, fn, text, expansion=SET, **kw))


# $2
_reg("Candlestick Maker", 2, _candlestick_maker, "+1 Action, +1 Buy, +1 Coffers.")
_reg("Hamlet", 2, _hamlet, "+1 Card, +1 Action. You may discard a card for +1 Action. You may discard a card for +1 Buy.")
_reg("Farrier", 2, _farrier, "+1 Card, +1 Action, +1 Buy. Overpay: +1 Card at the end of this turn per $1 you overpaid.", overpay=True, on_overpay=_farrier_overpay)
_reg("Stonemason", 2, _stonemason, "Trash a card from your hand. Gain 2 cards each costing less than it. Overpay: gain 2 Action cards each costing exactly the amount you overpaid.",
     overpay=True, on_overpay=_stonemason_overpay)
# $3
_reg("Menagerie", 3, _menagerie, "+1 Action. Reveal your hand. If there are no duplicate cards in it, +3 Cards. Otherwise, +1 Card.")
_reg("Shop", 3, _shop, "+1 Card, +$1. You may play an Action card from your hand that you don't have a copy of in play.")
_reg("Infirmary", 3, _infirmary, "+1 Card. You may trash a card from your hand. Overpay: play this once per $1 you overpaid.", overpay=True, on_overpay=_infirmary_overpay)
_reg("Fortune Teller", 3, _fortune_teller, "+$2. Each other player reveals cards from the top of their deck until they reveal a Victory or Curse card. They put it on top and discard the rest.", extra_types=_ATTACK)
register(treasure("Masterpiece", 3, 1, text="$1. Overpay: when you buy this, gain a Silver per $1 you overpaid.", kingdom=True, expansion=SET,
                  overpay=True, on_overpay=_masterpiece_overpay))
_reg("Doctor", 3, _doctor, "Name a card. Reveal the top 3 cards of your deck. Trash the matches. Put the rest back on top in any order. Overpay: for each $1 you overpaid, look at the top card of your deck; trash it, discard it or put it back.",
     overpay=True, on_overpay=_doctor_overpay)
# $4
_reg("Advisor", 4, _advisor, "+1 Action. Reveal the top 3 cards of your deck. The player to your left chooses one of them. Discard that card and put the rest into your hand.")
_reg("Farmhands", 4, _farmhands, "+1 Card, +2 Actions. When you gain this, you may set aside an Action or Treasure card from your hand. At the start of your next turn, play it.", on_gain=_farmhands_gain)
_reg("Plaza", 4, _plaza, "+1 Card, +2 Actions. You may discard a Treasure for +1 Coffers.")
_reg("Remake", 4, _remake, "Do this twice: trash a card from your hand, then gain a card costing exactly $1 more than the trashed card.")
_reg("Young Witch", 4, _young_witch, "+2 Cards. Discard 2 cards. Each other player may reveal a Bane card from their hand; if they don't, they gain a Curse. (Setup: add an extra Kingdom pile costing $2 or $3 as the Bane.)", extra_types=_ATTACK)
_reg("Herald", 4, _herald, "+1 Card, +1 Action. Reveal the top card of your deck. If it's an Action, play it. Overpay: for each $1 you overpaid, put a card from your discard pile onto your deck.", overpay=True, on_overpay=_herald_overpay)
_reg("Horse Traders", 4, _horse_traders, "+1 Buy, +$3. Discard 2 cards. When another player plays an Attack card, you may set this aside from your hand. At the start of your next turn, +1 Card and return this to your hand.",
     extra_types=(CardType.REACTION,), on_attack=_horse_traders_reaction)
_reg("Tournament", 4, _tournament, "+1 Action. Each player may reveal a Province from their hand. If you do, discard it and gain a Prize (from the Prize pile) or a Duchy onto your deck. If no other player does, +1 Card and +$1.")
_reg("Taxman", 4, _taxman, "You may trash a Treasure from your hand. Each other player with 5 or more cards in hand discards a copy of it (or reveals a hand without it). Gain a Treasure costing up to $3 more than the trashed one onto your deck.", extra_types=_ATTACK)
_reg("Farming Village", 4, _farming_village, "+2 Actions. Reveal cards from your deck until you reveal an Action or Treasure. Put it into your hand and discard the other cards.")
# $5
_reg("Baker", 5, _baker, "+1 Card, +1 Action, +1 Coffers. Setup: each player takes +1 Coffers.")
_reg("Butcher", 5, _butcher, "+2 Coffers. You may trash a card from your hand and remove any number of Coffers tokens. Gain a card costing up to the trashed card's cost plus the tokens you removed.")
_reg("Carnival", 5, _carnival, "Reveal the top 4 cards of your deck. Put a copy of each differently named card into your hand and discard the rest.")
_reg("Ferryman", 5, _ferryman, "+2 Cards, +1 Action. Discard a card. When you gain this, gain a card from the Ferryman pile. (Setup: add an extra pile of a card costing $3 or $4, outside the Supply.)", on_gain=_ferryman_gain)
_reg("Footpad", 5, _footpad, "+2 Coffers. Each other player discards down to 3 cards in hand. In games using this, when you gain a card in an Action phase, +1 Card.", extra_types=_ATTACK)
register(treasure("Horn of Plenty", 5, 0, text="Gain a card costing up to $1 per differently named card you have in play (counting this). If it's a Victory card, trash this.",
                  kingdom=True, expansion=SET, on_play=_horn_of_plenty))
_reg("Hunting Party", 5, _hunting_party, "+1 Card, +1 Action. Reveal your hand. Reveal cards from your deck until you reveal one that isn't a copy of a card in your hand. Put it into your hand and discard the rest.")
_reg("Jester", 5, _jester, "+$2. Each other player discards the top card of their deck. If it's a Victory card they gain a Curse. Otherwise they gain a copy of the discarded card or you do, your choice.", extra_types=_ATTACK)
_reg("Journeyman", 5, _journeyman, "Name a card. Reveal cards from your deck until you reveal 3 cards that are not the named card. Put those into your hand and discard the rest.")
_reg("Joust", 5, _joust, "+1 Card, +1 Action, +$1. You may set aside a Province from your hand to gain a Reward to your hand. Discard the Province at the end of the turn. (Setup: the Rewards are not in the Supply.)")
_reg("Merchant Guild", 5, _merchant_guild, "+1 Buy, +$1. At the end of your Buy phase this turn, +1 Coffers per card you gained during it.")
_reg("Soothsayer", 5, _soothsayer, "Gain a Gold. Each other player gains a Curse. Each player who did draws a card.", extra_types=_ATTACK)
_reg("Harvest", 5, _harvest, "Reveal the top 4 cards of your deck, then discard them. +$1 per differently named card revealed.")
# $6
register(CardDef("Fairgrounds", 6, frozenset({CardType.VICTORY}), score_fn=_fairgrounds_score, kingdom=True, expansion=SET,
                 text="Worth 2 VP per 5 differently named cards you have (round down)."))

# ---- Prizes and Rewards (not in the Supply)
def _prize(name, types, fn, text, **kw):
    register(CardDef(name, 0, frozenset(types), on_play=fn, text=text, kingdom=False, expansion=SET, **kw))


_prize("Bag of Gold", (CardType.ACTION, CardType.PRIZE), _bag_of_gold, "+1 Action. Gain a Gold onto your deck.")
register(CardDef("Diadem", 0, frozenset({CardType.TREASURE, CardType.PRIZE}), coins_fn=_diadem_coins, kingdom=False, expansion=SET,
                 text="$2. +$1 per unused Action you have (Action, not Action card)."))
_prize("Followers", (CardType.ACTION, CardType.ATTACK, CardType.PRIZE), _followers, "+2 Cards. Gain an Estate. Each other player gains a Curse and discards down to 3 cards in hand.")
_prize("Princess", (CardType.ACTION, CardType.PRIZE), _princess, "+1 Buy. While this is in play, cards cost $2 less, but not less than $0.", cost_aura=2)
_prize("Trusty Steed", (CardType.ACTION, CardType.PRIZE), _trusty_steed, "Choose two: +2 Cards; +2 Actions; +$2; gain 4 Silvers and put your deck into your discard pile.")
register(CardDef("Coronet", 0, frozenset({CardType.ACTION, CardType.TREASURE, CardType.REWARD}), on_play=_coronet, kingdom=False, expansion=SET,
                 text="You may play a non-Reward Action card from your hand twice. You may play a non-Reward Treasure card from your hand twice."))
_prize("Courser", (CardType.ACTION, CardType.REWARD), _courser, "Choose two different: +2 Cards; +2 Actions; +$2; gain 4 Silvers.")
register(CardDef("Demesne", 0, frozenset({CardType.ACTION, CardType.VICTORY, CardType.REWARD}), on_play=_demesne, kingdom=False, expansion=SET,
                 score_fn=lambda cards: list(cards).count("Gold"), text="+2 Actions, +2 Buys. Gain a Gold. Worth 1 VP per Gold you have."))
_prize("Housecarl", (CardType.ACTION, CardType.REWARD), _housecarl, "+1 Card per differently named Action card you have in play (counting this).")
register(CardDef("Huge Turnip", 0, frozenset({CardType.TREASURE, CardType.REWARD}), on_play=_huge_turnip, kingdom=False, expansion=SET,
                 text="+2 Coffers. +$1 per Coffers token you have."))
_prize("Renown", (CardType.ACTION, CardType.REWARD), _renown, "+1 Buy. This turn, cards cost $1 less, but not less than $0.")
