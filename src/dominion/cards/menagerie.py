"""The Menagerie expansion (2020): 30 Kingdom cards, 20 Events, 20 Ways, the Horse pile and the Exile mat.

  * Exile: every player has an Exile mat (``PlayerState.exile``, face up, it scores). Exiling a card from the Supply is not gaining it.
    Gaining a card lets you discard the other copies of it from your mat (``engine/menagerie.py``).
  * Horses: a pile outside the Supply (``GameState.offsupply["Horse"]``). A Horse gives +2 Cards and +1 Action and goes back to its pile.
  * Ways (``CardType.WAY``, listed in ``GameState.ways``): with a Way in the game, each Action you play may do the Way's text instead of
    its own (the choice is a Decision asked by ``effects.way_choice``). Way of the Chameleon runs the card with +Cards and +$ swapped
    (``EffectContext._chameleon``); Way of the Mouse plays an Action that was set aside at setup (``GameState.mouse``).
  * Events (``CardType.EVENT``) are bought with a Buy like the Adventures ones; Menagerie ones that need a condition use ``can_buy_fn``.
  * Reactions played at unusual times (Sheepdog, Sleigh, Falconer, Black Cat, Village Green) are in ``engine/menagerie.py``.
  * Costs that change during the turn: Destrier and Fisherman use ``cost_mod``; Wayfarer is special-cased in ``engine/costs.py``.

Known simplifications: Wayfarer copies only the coin part of the last gained card's cost; Goatherd counts the cards its right-hand
neighbour trashed from their own cards during their own last turn.
"""

from __future__ import annotations

from .base import CardDef, CardType, treasure
from .registry import get_card, register

SET = "Menagerie"
T = CardType


def K(name, cost, types, fn, text, **kw):
    return register(CardDef(name, cost, frozenset(types), on_play=fn, text=text, kingdom=True, expansion=SET, **kw))


def _cost_between(ctx, card: str, low: int, high: int) -> bool:
    return low <= ctx.cost_of(card) <= high and not ctx.potion_cost_of(card) and not get_card(card).debt_cost


def _hand_names(ctx, test=None) -> tuple:
    return tuple(sorted({c for c in ctx.hand if test is None or test(c)}))


def _plain(ctx, card: str):
    """Play an Action from the hand without using an Action."""
    ctx.put_in_play(card, "hand")
    yield from ctx.resolve(card)


# ================================================================ Horse (not in the Supply)
def _horse(ctx):
    ctx.draw(2)
    ctx.add_actions(1)
    ctx.return_to_horse_pile(ctx.source)


register(CardDef("Horse", 3, frozenset({T.ACTION}), on_play=_horse, kingdom=False, expansion=SET,
                 text="+2 Cards, +1 Action. Return this to the Horse pile. (Not in the Supply.)"))


# ================================================================ Kingdom cards
def _animal_fair(ctx):
    ctx.add_coins(4)
    ctx.add_buys(ctx.empty_piles())


def _barge(ctx):
    now, later = "+3 Cards and +1 Buy now", "+3 Cards and +1 Buy at the start of your next turn"
    (mode,) = yield ctx.choose("Barge: choose one.", (now, later))
    if mode == now:
        ctx.draw(3)
        ctx.add_buys(1)
    else:
        ctx.add_duration(_barge_start)


def _barge_start(ctx, entry):
    ctx.log(f"{ctx.player_name}'s Barge gives +3 Cards and +1 Buy.")
    ctx.draw(3)
    ctx.add_buys(1)


def _black_cat(ctx):
    ctx.draw(2)
    if ctx.my_turn:
        return
    targets = yield from ctx.attack(only=ctx.turn_order_from_current())
    for p in targets:
        ctx.gain("Curse", player=p)


def _bounty_hunter(ctx):
    ctx.add_actions(1)
    if not ctx.hand:
        return
    (card,) = yield ctx.choose("Bounty Hunter: Exile a card from your hand.", _hand_names(ctx))
    had_copy = card in ctx.exile_of()
    ctx.exile_hand_card(card)
    if not had_copy:
        ctx.add_coins(3)


def _camel_train(ctx):
    options = ctx.exilable_supply(non_victory=True)
    if not options:
        return
    (card,) = yield ctx.choose("Camel Train: Exile a non-Victory card from the Supply.", options)
    ctx.exile_from_supply(card)


def _camel_train_gain(ctx, event):
    ctx.exile_from_supply("Gold")


def _cardinal(ctx):
    ctx.add_coins(2)
    targets = yield from ctx.attack()
    for p in targets:
        cards = ctx.take_to_set_aside(2, player=p, reveal=True)
        ok = tuple(sorted({c for c in cards if _cost_between(ctx, c, 3, 6)}))
        if ok:
            if len(ok) == 1:
                pick = ok[0]
            else:
                (pick,) = yield ctx.choose("Cardinal: Exile one of them (costing $3 to $6).", ok, player=p)
            ctx.exile_set_aside(pick, player=p)
            cards.remove(pick)
        for card in cards:
            ctx.discard_set_aside(card, player=p)


def _cavalry(ctx):
    ctx.gain_horse()
    ctx.gain_horse()


def _cavalry_gain(ctx, event):
    ctx.draw(2)
    ctx.add_buys(1)
    if ctx.in_buy_phase:
        ctx.set_phase_to_action()


def _coven(ctx):
    ctx.add_actions(1)
    ctx.add_coins(2)
    targets = yield from ctx.attack()
    for p in targets:
        if ctx.exile_from_supply("Curse", player=p):
            continue
        curses = [c for c in ctx.exile_of(p) if c == "Curse"]
        for _ in curses:
            ctx.discard_from_exile("Curse", player=p)
        if curses:
            ctx.log(f"{ctx.name_of(p)} discards {len(curses)} Curse(s) from their Exile mat.")


def _destrier(ctx):
    ctx.draw(2)
    ctx.add_actions(1)


def _displace(ctx):
    if not ctx.hand:
        return
    (card,) = yield ctx.choose("Displace: Exile a card from your hand.", _hand_names(ctx))
    cost = ctx.cost_of(card)
    ctx.exile_hand_card(card)
    options = tuple(n for n in ctx.gainable(cost + 2) if n != card)
    if options:
        (new,) = yield ctx.choose(f"Displace: gain a differently named card costing up to ${cost + 2}.", options)
        ctx.gain(new)


def _falconer(ctx):
    cost = ctx.cost_of(ctx.source) - 1
    options = ctx.gainable(cost) if cost >= 0 else ()
    if not options:
        return
    (card,) = yield ctx.choose("Falconer: gain a card to your hand costing less than this.", options)
    ctx.gain(card, destination="hand")


def _fisherman(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.add_coins(1)


def _gatekeeper(ctx):
    targets = yield from ctx.attack()
    for p in targets:
        ctx.add_gatekeeper(p)
        ctx.log(f"{ctx.name_of(p)} is under the Gatekeeper's watch.")
    ctx.add_duration(_gatekeeper_start)


def _gatekeeper_start(ctx, entry):
    ctx.log(f"{ctx.player_name}'s Gatekeeper gives +$3.")
    ctx.add_coins(3)


def _goatherd(ctx):
    n = ctx.trashed_by_right_neighbour()
    if ctx.hand:
        chosen = yield ctx.choose("Goatherd: you may trash a card from your hand.", _hand_names(ctx), 0, 1)
        if chosen:
            ctx.trash(chosen[0])
    if n:
        ctx.draw(n)


def _groom(ctx):
    options = ctx.gainable(4)
    if not options:
        return
    (card,) = yield ctx.choose("Groom: gain a card costing up to $4.", options)
    ctx.gain(card)
    types = ctx.card_types(card)
    if "action" in types:
        ctx.gain_horse()
    if "treasure" in types:
        ctx.gain("Silver")
    if "victory" in types:
        ctx.draw(1)
        ctx.add_actions(1)


def _hostelry(ctx):
    ctx.draw(1)
    ctx.add_actions(2)


def _hostelry_gain(ctx, event):
    treasures = tuple(c for c in ctx.hand if ctx.is_treasure(c))
    if not treasures:
        return
    chosen = yield ctx.choose("Hostelry: you may discard any number of Treasures, revealed, to gain that many Horses.", treasures, 0, len(treasures))
    if not chosen:
        return
    ctx.log(f"{ctx.player_name} reveals {' and '.join(chosen)}.")
    for card in chosen:
        ctx.discard(card)
    for _ in chosen:
        ctx.gain_horse()


def _hunting_lodge(ctx):
    ctx.draw(1)
    ctx.add_actions(2)
    chosen = yield ctx.choose("Hunting Lodge: you may discard your hand for +5 Cards.", ("Discard your hand",), 0, 1)
    if chosen:
        ctx.discard_hand()
        ctx.draw(5)


def _kiln(ctx):
    ctx.add_coins(2)
    ctx.arm_kiln()


def _livery(ctx):
    ctx.add_coins(3)
    ctx.bump_count("Livery")


def _mastermind(ctx):
    ctx.add_duration(_mastermind_start)
    return
    yield  # (makes this a generator for uniformity)


def _mastermind_start(ctx, entry):
    options = _hand_names(ctx, ctx.is_action)
    if not options:
        return
    chosen = yield ctx.choose("Mastermind: you may play an Action card from your hand three times.", options, 0, 1)
    if not chosen:
        return
    card = chosen[0]
    ctx.put_in_play(card, "hand")
    for _ in range(3):
        yield from ctx.resolve(card)


def _paddock(ctx):
    ctx.add_coins(2)
    ctx.gain_horse()
    ctx.gain_horse()
    ctx.add_actions(ctx.empty_piles())


def _sanctuary(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.add_buys(1)
    if ctx.hand:
        chosen = yield ctx.choose("Sanctuary: you may Exile a card from your hand.", _hand_names(ctx), 0, 1)
        if chosen:
            ctx.exile_hand_card(chosen[0])


SCRAP_OPTIONS = ("+1 Card", "+1 Action", "+1 Buy", "+$1", "Gain a Silver", "Gain a Horse")


def _scrap(ctx):
    if not ctx.hand:
        return
    (card,) = yield ctx.choose("Scrap: trash a card from your hand.", _hand_names(ctx))
    n = min(ctx.cost_of(card), len(SCRAP_OPTIONS))
    ctx.trash(card)
    if n <= 0:
        return
    picked = yield ctx.choose(f"Scrap: choose {n} different bonus{'es' if n != 1 else ''}.", SCRAP_OPTIONS, n, n)
    for option in SCRAP_OPTIONS:                                  # done in the order listed on the card
        if option not in picked:
            continue
        if option == "+1 Card":
            ctx.draw(1)
        elif option == "+1 Action":
            ctx.add_actions(1)
        elif option == "+1 Buy":
            ctx.add_buys(1)
        elif option == "+$1":
            ctx.add_coins(1)
        elif option == "Gain a Silver":
            ctx.gain("Silver")
        else:
            ctx.gain_horse()


def _sheepdog(ctx):
    ctx.draw(2)


def _sleigh(ctx):
    ctx.gain_horse()
    ctx.gain_horse()


def _snowy_village(ctx):
    ctx.draw(1)
    ctx.add_actions(4)
    ctx.add_buys(1)
    ctx.forbid_more_actions()


def _stockpile(ctx):
    ctx.add_buys(1)
    ctx.exile_in_play(ctx.source)


def _supplies(ctx):
    ctx.gain_horse(destination="deck")


def _village_green(ctx):
    now, later = "+1 Card and +2 Actions now", "+1 Card and +2 Actions at the start of your next turn"
    (mode,) = yield ctx.choose("Village Green: choose one.", (now, later))
    if mode == now:
        ctx.draw(1)
        ctx.add_actions(2)
    else:
        ctx.add_duration(_village_green_start)


def _village_green_start(ctx, entry):
    ctx.log(f"{ctx.player_name}'s Village Green gives +1 Card and +2 Actions.")
    ctx.draw(1)
    ctx.add_actions(2)


def _wayfarer(ctx):
    ctx.draw(3)
    if ctx.supply_count("Silver") > 0:
        chosen = yield ctx.choose("Wayfarer: you may gain a Silver.", ("Gain a Silver",), 0, 1)
        if chosen:
            ctx.gain("Silver")


def _fisherman_discount(state) -> int:
    return 3 if not state.players[state.current_player].discard else 0


def _destrier_discount(state) -> int:
    return len(state.players[state.current_player].gained_turn)


K("Black Cat", 2, {T.ACTION, T.ATTACK, T.REACTION}, _black_cat,
  "+2 Cards. If it isn't your turn, each other player gains a Curse. | When another player gains a Victory card, you may play this from your hand.")
K("Sleigh", 2, {T.ACTION, T.REACTION}, _sleigh,
  "Gain 2 Horses. | When you gain a card, you may discard this from your hand, to put that card into your hand or onto your deck.")
register(treasure("Supplies", 2, 1, text="$1. When you play this, gain a Horse onto your deck.", kingdom=True, expansion=SET, on_play=_supplies))
K("Camel Train", 3, {T.ACTION}, _camel_train, "Exile a non-Victory card from the Supply. | When you gain this, Exile a Gold from the Supply.", on_gain=_camel_train_gain)
K("Goatherd", 3, {T.ACTION}, _goatherd, "You may trash a card from your hand. +1 Card per card the player to your right trashed on their last turn.")
K("Scrap", 3, {T.ACTION}, _scrap, "Trash a card from your hand. Choose a different thing per $1 it costs: +1 Card; +1 Action; +1 Buy; +$1; gain a Silver; gain a Horse.")
K("Sheepdog", 3, {T.ACTION, T.REACTION}, _sheepdog, "+2 Cards. | When you gain a card, you may play this from your hand.")
K("Snowy Village", 3, {T.ACTION}, _snowy_village, "+1 Card, +4 Actions, +1 Buy. Ignore any further +Actions you would get this turn.")
register(treasure("Stockpile", 3, 3, text="$3. +1 Buy. When you play this, Exile it.", kingdom=True, expansion=SET, on_play=_stockpile))
K("Bounty Hunter", 4, {T.ACTION}, _bounty_hunter, "+1 Action. Exile a card from your hand. If you didn't have a copy of it in Exile, +$3.")
K("Cardinal", 4, {T.ACTION, T.ATTACK}, _cardinal, "+$2. Each other player reveals the top 2 cards of their deck, Exiles one costing from $3 to $6, and discards the rest.")
K("Cavalry", 4, {T.ACTION}, _cavalry, "Gain 2 Horses. | When you gain this, +2 Cards, +1 Buy, and if it's your Buy phase, return to your Action phase.", on_gain=_cavalry_gain)
K("Groom", 4, {T.ACTION}, _groom, "Gain a card costing up to $4. If it's an Action card, gain a Horse; a Treasure card, gain a Silver; a Victory card, +1 Card and +1 Action.")
K("Hostelry", 4, {T.ACTION}, _hostelry, "+1 Card, +2 Actions. | When you gain this, you may discard any number of Treasures, revealed, to gain that many Horses.", on_gain=_hostelry_gain)
K("Village Green", 4, {T.ACTION, T.DURATION, T.REACTION}, _village_green,
  "Now or at the start of your next turn, +1 Card and +2 Actions. | When you discard this other than in Clean-up, you may play it.")
K("Barge", 5, {T.ACTION, T.DURATION}, _barge, "Choose one: +3 Cards and +1 Buy now; or at the start of your next turn, +3 Cards and +1 Buy.")
K("Coven", 5, {T.ACTION, T.ATTACK}, _coven, "+1 Action, +$2. Each other player Exiles a Curse from the Supply. If they can't, they discard their Curses from Exile.")
K("Displace", 5, {T.ACTION}, _displace, "Exile a card from your hand. Gain a differently named card costing up to $2 more than it.")
K("Falconer", 5, {T.ACTION, T.REACTION}, _falconer,
  "Gain a card to your hand costing less than this. | When any player gains a card with 2 or more types (Action, Attack, etc.), you may play this from your hand.")
K("Fisherman", 5, {T.ACTION}, _fisherman, "+1 Card, +1 Action, +$1. During your turns, this costs $3 less if your discard pile is empty. (Costs $5*.)", cost_mod=_fisherman_discount)
K("Gatekeeper", 5, {T.ACTION, T.DURATION, T.ATTACK}, _gatekeeper,
  "At the start of your next turn, +$3. Until then, when another player gains an Action or Treasure card that they don't have a copy of in Exile, they Exile it.")
K("Hunting Lodge", 5, {T.ACTION}, _hunting_lodge, "+1 Card, +2 Actions. You may discard your hand for +5 Cards.")
K("Kiln", 5, {T.ACTION}, _kiln, "+$2. The next time you play a card this turn, you may first gain a copy of it.")
K("Livery", 5, {T.ACTION}, _livery, "+$3. This turn, when you gain a card costing $4 or more, gain a Horse.")
K("Mastermind", 5, {T.ACTION, T.DURATION}, _mastermind, "At the start of your next turn, you may play an Action card from your hand three times.")
K("Paddock", 5, {T.ACTION}, _paddock, "+$2. Gain 2 Horses. +1 Action per empty Supply pile.")
K("Sanctuary", 5, {T.ACTION}, _sanctuary, "+1 Card, +1 Action, +1 Buy. You may Exile a card from your hand.")
K("Destrier", 6, {T.ACTION}, _destrier, "+2 Cards, +1 Action. During your turns, this costs $1 less per card you've gained this turn. (Costs $6*.)", cost_mod=_destrier_discount)
K("Wayfarer", 6, {T.ACTION}, _wayfarer, "+3 Cards. You may gain a Silver. This has the same cost as the last other card gained this turn, if any. (Costs $6*.)")
K("Animal Fair", 7, {T.ACTION}, _animal_fair,
  "+$4. +1 Buy per empty Supply pile. | Instead of paying this card's cost, you may trash an Action card from your hand. (Costs $7*.)")


# ================================================================ Ways
def _way(name: str, text: str, fn):
    return register(CardDef(name, 0, frozenset({T.WAY}), on_play=fn, text=text, kingdom=False, expansion=SET))


def _w_butterfly(ctx):
    card = ctx.source
    if card not in ctx.in_play:
        return
    target = ctx.cost_of(card) + 1
    if not ctx.gainable(target, exact=True):
        return
    chosen = yield ctx.choose(f"Way of the Butterfly: return {card} to its pile to gain a card costing exactly ${target}?", (f"Return {card}",), 0, 1)
    if not chosen or not ctx.return_to_horse_pile(card):
        return
    options = ctx.gainable(target, exact=True)
    if options:
        (new,) = yield ctx.choose(f"Way of the Butterfly: gain a card costing exactly ${target}.", options)
        ctx.gain(new)


def _w_camel(ctx):
    ctx.exile_from_supply("Gold")


def _w_chameleon(ctx):
    return None          # never called: the card's own effect runs with +Cards and +$ swapped (effects.play_effect)


def _w_frog(ctx):
    ctx.add_actions(1)
    ctx.frog(ctx.source)


def _w_goat(ctx):
    if ctx.hand:
        (card,) = yield ctx.choose("Way of the Goat: trash a card from your hand.", _hand_names(ctx))
        ctx.trash(card)


def _w_horse(ctx):
    ctx.draw(2)
    ctx.add_actions(1)
    ctx.return_to_horse_pile(ctx.source)


def _w_mole(ctx):
    ctx.add_actions(1)
    ctx.discard_hand()
    ctx.draw(3)


def _w_monkey(ctx):
    ctx.add_monkey()


def _w_mouse(ctx):
    yield from ctx.play_mouse()


def _w_mule(ctx):
    ctx.add_actions(1)
    ctx.add_coins(1)


def _w_otter(ctx):
    ctx.draw(2)


def _w_owl(ctx):
    n = 6 - len(ctx.hand)
    if n > 0:
        ctx.draw(n)


def _w_ox(ctx):
    ctx.add_actions(2)


def _w_pig(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.add_buys(1)


def _w_rat(ctx):
    card = ctx.source
    treasures = _hand_names(ctx, ctx.is_treasure)
    if not treasures or card not in ctx.exilable_supply():
        return
    chosen = yield ctx.choose(f"Way of the Rat: you may discard a Treasure to gain a copy of {card}.", treasures, 0, 1)
    if chosen:
        ctx.discard(chosen[0])
        ctx.gain(card)


def _w_seal(ctx):
    ctx.bump_count(f"seal:{ctx.player}")


def _w_sheep(ctx):
    ctx.add_coins(2)


def _w_squirrel(ctx):
    ctx.add_squirrel(2)


def _w_turtle(ctx):
    card = ctx.source
    if card not in ctx.in_play:
        return
    ctx.set_aside_delayed(card, "in_play")
    ctx.log(f"{ctx.player_name} sets {card} aside; it will be played at the start of their next turn.")
    ctx.add_delayed_play("Way of the Turtle", _delayed_play, card)


def _w_worm(ctx):
    ctx.exile_from_supply("Estate")


def _delayed_play(ctx, entry):
    """Delay and Way of the Turtle: the set-aside Action is played at the start of the turn (no Action is used)."""
    card = entry.data
    if card in ctx.mat_cards("delayed"):
        ctx.put_in_play(card, "delayed")
        yield from ctx.resolve(card)


_way("Way of the Butterfly", "You may return this to its pile to gain a card costing exactly $1 more than it.", _w_butterfly)
_way("Way of the Camel", "Exile a Gold from the Supply.", _w_camel)
_way("Way of the Chameleon", "Follow this card's instructions; each time that would give you +Cards this turn, you get +$ instead, and vice-versa.", _w_chameleon)
_way("Way of the Frog", "+1 Action. When you discard this from play this turn, put it onto your deck.", _w_frog)
_way("Way of the Goat", "Trash a card from your hand.", _w_goat)
_way("Way of the Horse", "+2 Cards, +1 Action. Return this to its pile.", _w_horse)
_way("Way of the Mole", "+1 Action. Discard your hand. +3 Cards.", _w_mole)
_way("Way of the Monkey", "Until your next turn, when the player to your right gains a card, +1 Card.", _w_monkey)
_way("Way of the Mouse", "Play the set-aside card, leaving it there. (Setup: set aside an unused Action Kingdom card costing $2 or $3.)", _w_mouse)
_way("Way of the Mule", "+1 Action, +$1.", _w_mule)
_way("Way of the Otter", "Draw 2 cards.", _w_otter)
_way("Way of the Owl", "Draw until you have 6 cards in hand.", _w_owl)
_way("Way of the Ox", "+2 Actions.", _w_ox)
_way("Way of the Pig", "+1 Card, +1 Action, +1 Buy.", _w_pig)
_way("Way of the Rat", "You may discard a Treasure to gain a copy of this.", _w_rat)
_way("Way of the Seal", "This turn, when you gain a card, you may put it onto your deck.", _w_seal)
_way("Way of the Sheep", "+$2.", _w_sheep)
_way("Way of the Squirrel", "+2 Cards at the end of this turn.", _w_squirrel)
_way("Way of the Turtle", "Set this aside. If you did, play it at the start of your next turn.", _w_turtle)
_way("Way of the Worm", "Exile an Estate from the Supply.", _w_worm)


# ================================================================ Events
def _event(name: str, cost: int, text: str, fn, once: bool = False, can_buy=None):
    return register(CardDef(name, cost, frozenset({T.EVENT}), on_play=fn, text=text, kingdom=False, expansion=SET,
                            once_per_turn=once, can_buy_fn=can_buy))


def _alliance(ctx):
    for name in ("Province", "Duchy", "Estate", "Gold", "Silver", "Copper"):
        if ctx.supply_count(name) > 0:
            ctx.gain(name)


def _banish(ctx):
    names = _hand_names(ctx)
    if not names:
        return
    picked = yield ctx.choose("Banish: you may Exile any number of cards with the same name from your hand. Pick the name.", names, 0, 1)
    if not picked:
        return
    name = picked[0]
    copies = tuple(c for c in ctx.hand if c == name)
    chosen = yield ctx.choose(f"Banish: how many {name} do you Exile?", copies, 0, len(copies))
    for card in chosen:
        ctx.exile_hand_card(card)


def _bargain(ctx):
    options = tuple(n for n in ctx.gainable(5) if "victory" not in ctx.card_types(n))
    if options:
        (card,) = yield ctx.choose("Bargain: gain a non-Victory card costing up to $5.", options)
        ctx.gain(card)
    for p in ctx.other_players():
        ctx.gain_horse(player=p)


def _commerce(ctx):
    for _ in range(len(set(ctx.gained_this_turn()))):
        ctx.gain("Gold")


def _delay(ctx):
    options = _hand_names(ctx, ctx.is_action)
    if not options:
        return
    chosen = yield ctx.choose("Delay: you may set aside an Action card from your hand; you will play it at the start of your next turn.", options, 0, 1)
    if chosen:
        ctx.set_aside_delayed(chosen[0])
        ctx.log(f"{ctx.player_name} sets {chosen[0]} aside with Delay.")
        ctx.add_delayed_play("Delay", _delayed_play, chosen[0])


def _demand(ctx):
    ctx.gain_horse(destination="deck")
    options = ctx.gainable(4)
    if options:
        (card,) = yield ctx.choose("Demand: gain a card costing up to $4 onto your deck.", options)
        ctx.gain(card, destination="deck")


def _desperation(ctx):
    if ctx.supply_count("Curse") <= 0:
        return
    chosen = yield ctx.choose("Desperation: you may gain a Curse for +1 Buy and +$2.", ("Gain a Curse",), 0, 1)
    if chosen and ctx.gain("Curse"):
        ctx.add_buys(1)
        ctx.add_coins(2)


def _enclave(ctx):
    ctx.gain("Gold")
    ctx.exile_from_supply("Duchy")


def _enhance(ctx):
    options = _hand_names(ctx, lambda c: ctx.is_action(c) or ctx.is_treasure(c))
    if not options:
        return
    chosen = yield ctx.choose("Enhance: you may trash an Action or Treasure from your hand.", options, 0, 1)
    if not chosen:
        return
    cost = ctx.cost_of(chosen[0])
    ctx.trash(chosen[0])
    gains = ctx.gainable(cost + 2)
    if gains:
        (card,) = yield ctx.choose(f"Enhance: gain a card costing up to ${cost + 2}.", gains)
        ctx.gain(card)


def _gamble(ctx):
    ctx.add_buys(1)
    cards = ctx.take_to_set_aside(1, reveal=True)
    if not cards:
        return
    card = cards[0]
    if ctx.is_treasure(card) or ctx.is_action(card):
        chosen = yield ctx.choose(f"Gamble: you revealed {card}. You may play it.", (f"Play {card}",), 0, 1)
        if chosen:
            if ctx.is_treasure(card):
                yield from ctx.play_treasure(card, zone="set_aside")
            else:
                ctx.put_in_play(card, "set_aside")
                yield from ctx.resolve(card)
            return
    ctx.discard_set_aside(card)


def _invest(ctx):
    options = ctx.exilable_supply(action_only=True)
    if not options:
        return
    (card,) = yield ctx.choose("Invest: Exile an Action from the Supply.", options)
    ctx.exile_from_supply(card)
    ctx.invest_in(card)


def _march(ctx):
    options = tuple(sorted({c for c in ctx.discard_pile if ctx.is_action(c)}))
    if not options:
        return
    chosen = yield ctx.choose("March: you may play an Action card from your discard pile.", options, 0, 1)
    if chosen:
        yield from _plain_from(ctx, chosen[0], "discard")


def _plain_from(ctx, card: str, zone: str):
    ctx.put_in_play(card, zone)
    yield from ctx.resolve(card)


def _populate(ctx):
    remaining = list(ctx.populate_cards())
    while remaining:
        if len(remaining) == 1:
            card = remaining[0]
        else:
            (card,) = yield ctx.choose("Populate: gain one card from each Action Supply pile. Choose the next one.", tuple(remaining))
        remaining.remove(card)
        ctx.gain(card)


def _pursue(ctx):
    names = tuple(sorted(set(ctx.supply_names()) | set(ctx.offsupply_names()) | set(ctx.owned(ctx.player))))
    (name,) = yield ctx.choose("Pursue: name a card.", names)
    ctx.log(f"{ctx.player_name} names {name}.")
    for card in ctx.take_to_set_aside(4, reveal=True):
        if card == name:
            ctx.put_set_aside_on_deck(card)
        else:
            ctx.discard_set_aside(card)


def _reap(ctx):
    if ctx.gain("Gold") and "Gold" in ctx.discard_pile:
        ctx.set_aside_delayed("Gold", "discard")
        ctx.add_delayed_play("Reap", _reap_start, "Gold")


def _reap_start(ctx, entry):
    if entry.data in ctx.mat_cards("delayed"):
        yield from ctx.play_treasure(entry.data, zone="delayed")


def _ride(ctx):
    ctx.gain_horse()


def _seize_the_day(ctx):
    ctx.queue_seize_the_day()


def _stampede(ctx):
    for _ in range(5):
        ctx.gain_horse(destination="deck")


def _toil(ctx):
    ctx.add_buys(1)
    options = _hand_names(ctx, ctx.is_action)
    if options:
        chosen = yield ctx.choose("Toil: you may play an Action card from your hand.", options, 0, 1)
        if chosen:
            yield from _plain(ctx, chosen[0])


def _transport(ctx):
    exile_opt, deck_opt = "Exile an Action from the Supply", "Put an Action from your Exile mat onto your deck"
    modes = []
    if ctx.exilable_supply(action_only=True):
        modes.append(exile_opt)
    if any(ctx.is_action(c) for c in ctx.exile_of()):
        modes.append(deck_opt)
    if not modes:
        return
    (mode,) = yield ctx.choose("Transport: choose one.", tuple(modes))
    if mode == exile_opt:
        (card,) = yield ctx.choose("Transport: Exile an Action from the Supply.", ctx.exilable_supply(action_only=True))
        ctx.exile_from_supply(card)
    else:
        (card,) = yield ctx.choose("Transport: put an Action from your Exile mat onto your deck.", tuple(sorted({c for c in ctx.exile_of() if ctx.is_action(c)})))
        ctx.exile_to_deck(card)


def _seize_check(state):
    return "You can only buy Seize the Day once per game." if state.players[state.current_player].seize_used else None


def _stampede_check(state):
    return "Stampede: you can only buy it with 5 or fewer cards in play." if len(state.players[state.current_player].in_play) > 5 else None


_event("Delay", 0, "You may set aside an Action card from your hand. At the start of your next turn, play it.", _delay)
_event("Desperation", 0, "Once per turn: You may gain a Curse. If you do, +1 Buy and +$2.", _desperation, once=True)
_event("Gamble", 2, "+1 Buy. Reveal the top card of your deck. If it's a Treasure or Action, you may play it. Otherwise, discard it.", _gamble)
_event("Invest", 2, "Exile an Action from the Supply. While it's in Exile, when another player gains or Invests in a copy of it, +2 Cards.", _invest)
_event("Pursue", 2, "Name a card. Reveal the top 4 cards of your deck. Put the ones matching the named card back and discard the rest.", _pursue)
_event("Ride", 2, "Gain a Horse.", _ride)
_event("Toil", 2, "+1 Buy. You may play an Action card from your hand.", _toil)
_event("Enhance", 3, "You may trash an Action or Treasure from your hand. Gain a card costing up to $2 more than it.", _enhance)
_event("March", 3, "Look through your discard pile. You may play an Action from it.", _march)
_event("Transport", 3, "Choose one: Exile an Action from the Supply; or put an Action card from your Exile mat onto your deck.", _transport)
_event("Banish", 4, "Exile any number of cards with the same name from your hand.", _banish)
_event("Bargain", 4, "Gain a non-Victory card costing up to $5. Each other player gains a Horse.", _bargain)
_event("Seize the Day", 4, "Once per game: Take an extra turn after this one (but not a 3rd turn in a row).", _seize_the_day, can_buy=_seize_check)
_event("Commerce", 5, "Gain a Gold per differently named card you've gained this turn.", _commerce)
_event("Demand", 5, "Gain a Horse and a card costing up to $4, both onto your deck.", _demand)
_event("Stampede", 5, "You can only buy this if you have 5 or fewer cards in play. Gain 5 Horses onto your deck.", _stampede, can_buy=_stampede_check)
_event("Reap", 7, "Gain a Gold. Set it aside, and play it at the start of your next turn.", _reap)
_event("Enclave", 8, "Gain a Gold. Exile a Duchy from the Supply.", _enclave)
_event("Alliance", 10, "Gain a Province, a Duchy, an Estate, a Gold, a Silver, and a Copper.", _alliance)
_event("Populate", 10, "Gain one card from each Action Supply pile.", _populate)
