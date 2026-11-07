"""The Empires expansion (2016): 24 Kingdom piles (five split piles and the Castles), 13 Events and 21 Landmarks.

New engine features used here:

  * Debt (``CardDef.debt_cost``, ``PlayerState.debt``): buying a card or Event with Debt in its cost makes you take the
    tokens; while you owe any you cannot buy. ``PayDebt`` spends $ to remove them (Buy phase).
  * Split piles: five cards of each half, the top half first (``setup.SPLIT_PILES``); only the top card can be bought or
    gained. They use the same ``GameState.stacks`` mechanism as the Knights. The Castles are one pile of 8 (12) cards.
  * VP on piles (``GameState.pile_vp``: Temple, Wild Hunt, Farmers' Market, and the Landmarks Aqueduct and Defiled
    Shrine) and Debt on piles (Tax).
  * Landmarks (``CardType.LANDMARK``): standing rules, handled in ``engine/landmarks.py``. Events and Landmarks together
    number at most two per game.
"""

from __future__ import annotations

from dataclasses import replace

from .adventures import _gain_up_to
from .base import CardDef, CardType, action, treasure
from .registry import register

SET = "Empires"
_ATTACK = (CardType.ATTACK,)
CASTLES = ("Humble Castle", "Crumbling Castle", "Small Castle", "Haunted Castle",
           "Opulent Castle", "Sprawling Castle", "Grand Castle", "King's Castle")


def R(card: CardDef) -> CardDef:
    return register(card)


def _debt(card: CardDef, n: int) -> CardDef:
    return replace(card, debt_cost=n)


def _discard_down_to(ctx, p: int, n: int, who: str):
    hand = ctx.hand_of(p)
    excess = len(hand) - n
    if excess > 0:
        chosen = yield ctx.choose(f"{ctx.player_name}'s {who}: discard {excess} card(s) to get down to {n}.", hand, excess, excess, player=p)
        for card in chosen:
            ctx.discard(card, player=p)


# ---------------------------------------------------------------- split piles
def _settlers(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    if "Copper" in ctx.discard_pile:
        chosen = yield ctx.choose("Settlers: you may reveal a Copper from your discard pile and put it into your hand.", ("Copper",), 0, 1)
        if chosen:
            ctx.take_from_discard("Copper")
            ctx.log(f"{ctx.player_name} puts a Copper from their discard pile into their hand.")


def _bustling_village(ctx):
    ctx.draw(1)
    ctx.add_actions(3)
    if "Settlers" in ctx.discard_pile:
        chosen = yield ctx.choose("Bustling Village: you may reveal a Settlers from your discard pile and put it into your hand.", ("Settlers",), 0, 1)
        if chosen:
            ctx.take_from_discard("Settlers")
            ctx.log(f"{ctx.player_name} puts a Settlers from their discard pile into their hand.")


def _catapult(ctx):
    ctx.add_coins(1)
    targets = yield from ctx.attack()
    hand = ctx.hand
    if not hand:
        return
    (card,) = yield ctx.choose("Catapult: trash a card from your hand.", tuple(sorted(set(hand))))
    cost, treasure_ = ctx.cost_of(card), ctx.is_treasure(card)
    ctx.trash(card)
    if cost >= 3:
        for p in targets:
            ctx.gain("Curse", p)
    if treasure_:
        for p in targets:
            yield from _discard_down_to(ctx, p, 3, "Catapult")


def _rocks_silver(ctx):
    ctx.gain("Silver", destination="deck" if ctx.in_buy_phase else "hand")


def _rocks_gain(ctx, event):
    _rocks_silver(ctx)


def _rocks_trash(ctx, event):
    _rocks_silver(ctx)


def _encampment(ctx):
    ctx.draw(2)
    ctx.add_actions(2)
    options = tuple(c for c in ("Gold", "Plunder") if c in ctx.hand)
    if options:
        chosen = yield ctx.choose("Encampment: you may reveal a Gold or Plunder from your hand. If you do not, Encampment is set aside "
                                  "and returns to the Supply at the start of Clean-up.", options, 0, 1)
        if chosen:
            ctx.log(f"{ctx.player_name} reveals {chosen[0]}.", "reveal")
            return
    if ctx.source == "Encampment":
        ctx.bump_count("Encampment")


def _encampment_cleanup(ctx):
    if ctx.consume_count("Encampment"):
        ctx.return_to_pile("Encampment")


def _plunder(ctx):
    ctx.add_coins(2)
    ctx.add_vp(1)


def _gladiator(ctx):
    ctx.add_coins(2)
    hand = ctx.hand
    if not hand:
        return
    (card,) = yield ctx.choose("Gladiator: reveal a card from your hand.", tuple(sorted(set(hand))))
    left = ctx.left_player()
    ctx.log(f"{ctx.player_name} reveals {card}.", "reveal")
    if card in ctx.hand_of(left):
        chosen = yield ctx.choose(f"{ctx.player_name} revealed {card} with Gladiator. You may reveal a copy from your hand.", (f"Reveal {card}",), 0, 1, player=left)
        if chosen:
            ctx.log(f"{ctx.name_of(left)} reveals {card}.", "reveal")
            return
    ctx.add_coins(1)
    ctx.trash_from_supply("Gladiator")


def _fortune_play(ctx):
    ctx.add_buys(1)
    if ctx.bump_count("Fortune doubled") == 0:
        ctx.log(f"{ctx.player_name}'s Fortune doubles their $.")
        ctx.add_coins(ctx.coins)


def _fortune_gain(ctx, event):
    for _ in range(ctx.in_play.count("Gladiator")):
        ctx.gain("Gold")


def _patrician(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    top = ctx.top_of_deck()
    if top is None:
        return
    ctx.log(f"{ctx.player_name} reveals {top}.", "reveal")
    if ctx.cost_of(top) >= 5:
        ctx.draw(1, quiet=True)
        ctx.log(f"{ctx.player_name} puts {top} into their hand.")


def _emporium(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.add_coins(1)


def _emporium_gain(ctx, event):
    if sum(1 for c in ctx.in_play if ctx.is_action(c)) >= 5:
        ctx.add_vp(2)


# ---------------------------------------------------------------- Castles
def _castle_count(cards) -> int:
    return sum(1 for c in cards if c in CASTLES)


def _crumbling_bonus(ctx, event):
    ctx.add_vp(1)
    ctx.gain("Silver")


def _small_castle(ctx):
    options = []
    if ctx.source in ctx.in_play:
        options.append("This Small Castle")
    options.extend(sorted({c for c in ctx.hand if c in CASTLES}))
    if not options:
        return
    chosen = yield ctx.choose("Small Castle: trash this or a Castle from your hand to gain a Castle.", tuple(options), 0, 1)
    if not chosen:
        return
    pick = chosen[0]
    done = ctx.trash_in_play(ctx.source) if pick == "This Small Castle" else (ctx.trash(pick) or True)
    if done:
        ctx.gain_top("Castles")


def _haunted_gain(ctx, event):
    if not ctx.my_turn:
        return
    ctx.gain("Gold")
    for p in ctx.other_players():
        if len(ctx.hand_of(p)) >= 5:
            chosen = yield ctx.choose(f"{ctx.player_name} gained Haunted Castle. Put 2 cards from your hand onto your deck.", ctx.hand_of(p), 2, 2, player=p)
            for card in chosen:
                ctx.put_hand_on_deck(card, p)


def _opulent(ctx):
    options = tuple(c for c in ctx.hand if ctx.is_victory(c))
    if not options:
        return
    chosen = yield ctx.choose("Opulent Castle: discard any number of Victory cards for +$2 each.", options, 0, len(options))
    for card in chosen:
        ctx.discard(card)
    ctx.add_coins(2 * len(chosen))


def _sprawling_gain(ctx, event):
    (pick,) = yield ctx.choose("Sprawling Castle: gain a Duchy or 3 Estates.", ("Gain a Duchy", "Gain 3 Estates"))
    if pick == "Gain a Duchy":
        ctx.gain("Duchy")
    else:
        for _ in range(3):
            ctx.gain("Estate")


def _grand_gain(ctx, event):
    n = sum(1 for c in (*ctx.hand, *ctx.in_play) if ctx.is_victory(c))
    ctx.log(f"{ctx.player_name} reveals their hand: {n} Victory card(s) in hand and in play.", "reveal")
    ctx.add_vp(n)


# ---------------------------------------------------------------- single cards
def _chariot_race(ctx):
    ctx.add_actions(1)
    mine = ctx.top_of_deck()
    if mine is None:
        return
    ctx.draw(1, quiet=True)
    ctx.log(f"{ctx.player_name} reveals {mine} and puts it into their hand.", "reveal")
    left = ctx.left_player()
    theirs = ctx.top_of_deck(left)
    if theirs is None:
        return
    ctx.log(f"{ctx.name_of(left)} reveals {theirs}.", "reveal")
    if ctx.costs_more(mine, theirs):
        ctx.log(f"{mine} costs more than {theirs}: +$1 and +1 VP.")
        ctx.add_coins(1)
        ctx.add_vp(1)


def _enchantress(ctx):
    targets = yield from ctx.attack()
    for p in targets:
        ctx.enchant(p)
    ctx.add_duration(_enchantress_start, tuple(targets))


def _enchantress_start(ctx, entry):
    for p in entry.data:
        ctx.unenchant(p)
    ctx.draw(2)


def _farmers_market(ctx):
    ctx.add_buys(1)
    pile = "Farmers' Market"
    if ctx.pile_vp(pile) >= 4:
        ctx.take_pile_vp(pile)
        ctx.trash_self()
    else:
        ctx.add_pile_vp(pile)
        ctx.add_coins(ctx.pile_vp(pile))


def _sacrifice(ctx):
    hand = ctx.hand
    if not hand:
        return
    (card,) = yield ctx.choose("Sacrifice: trash a card from your hand.", tuple(sorted(set(hand))))
    types = ctx.card_types(card)
    ctx.trash(card)
    if "action" in types:
        ctx.draw(2)
        ctx.add_actions(2)
    if "treasure" in types:
        ctx.add_coins(2)
    if "victory" in types:
        ctx.add_vp(2)


def _temple(ctx):
    ctx.add_vp(1)
    options = tuple(sorted(set(ctx.hand)))
    if options:
        chosen = yield ctx.choose("Temple: trash from 1 to 3 differently named cards from your hand.", options, 1, min(3, len(options)))
        for card in chosen:
            ctx.trash(card)
    ctx.add_pile_vp("Temple")


def _temple_gain(ctx, event):
    ctx.take_pile_vp("Temple")


def _villa(ctx):
    ctx.add_actions(2)
    ctx.add_buys(1)
    ctx.add_coins(1)


def _villa_gain(ctx, event):
    if ctx.put_gained_in_hand(event) and ctx.my_turn:
        ctx.add_actions(1)
        ctx.set_phase_to_action()


def _archive_take(ctx, data):
    (card,) = yield ctx.choose("Archive: put one of the cards set aside by Archive into your hand.", tuple(sorted(set(data["cards"]))))
    data["cards"].remove(card)
    ctx.archive_to_hand(card)


def _archive(ctx):
    ctx.add_actions(1)
    cards = ctx.archive_set_aside(3)
    if not cards:
        return
    data = {"cards": list(cards)}
    yield from _archive_take(ctx, data)
    if data["cards"]:
        ctx.add_duration(_archive_start, data)


def _archive_start(ctx, entry):
    yield from _archive_take(ctx, entry.data)
    if entry.data["cards"]:
        ctx.add_duration(_archive_start, entry.data)


def _capital_cleanup(ctx):
    ctx.add_debt(6)
    ctx.pay_off_debt(ctx.coins)


def _charm(ctx):
    (pick,) = yield ctx.choose("Charm: choose one.", ("+1 Buy and +$2", "The next time you buy a card this turn, also gain a differently named card with the same cost"))
    if pick.startswith("+1 Buy"):
        ctx.add_buys(1)
        ctx.add_coins(2)
    else:
        ctx.bump_count("Charm")


def _crown(ctx):
    if ctx.in_action_phase:
        options = tuple(sorted({c for c in ctx.hand if ctx.is_action(c)}))
        if not options:
            return
        chosen = yield ctx.choose("Crown: you may play an Action card from your hand twice.", options, 0, 1)
        if not chosen:
            return
        card = chosen[0]
        ctx.put_in_play(card, "hand")
        yield from ctx.resolve(card)
        yield from ctx.resolve(card)
    else:
        options = tuple(sorted({c for c in ctx.hand if ctx.is_treasure(c)}))
        if not options:
            return
        chosen = yield ctx.choose("Crown: you may play a Treasure from your hand twice.", options, 0, 1)
        if not chosen:
            return
        card = chosen[0]
        yield from ctx.play_treasure(card, "hand")
        yield from ctx.play_treasure(card, "in_play")


def _forum(ctx):
    ctx.draw(3)
    ctx.add_actions(1)
    hand = ctx.hand
    n = min(2, len(hand))
    if n:
        chosen = yield ctx.choose("Forum: discard 2 cards.", hand, n, n)
        for card in chosen:
            ctx.discard(card)


def _forum_gain(ctx, event):
    if event.bought and ctx.my_turn:
        ctx.add_buys(1)


def _groundskeeper(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.bump_count("Groundskeeper")


def _legionary(ctx):
    ctx.add_coins(3)
    targets = yield from ctx.attack()
    if "Gold" not in ctx.hand:
        return
    chosen = yield ctx.choose("Legionary: you may reveal a Gold from your hand. If you do, each other player discards down to 2 cards, then draws a card.", ("Reveal Gold",), 0, 1)
    if not chosen:
        return
    ctx.log(f"{ctx.player_name} reveals Gold.", "reveal")
    for p in targets:
        yield from _discard_down_to(ctx, p, 2, "Legionary")
        ctx.draw(1, player=p)


def _wild_hunt(ctx):
    (pick,) = yield ctx.choose("Wild Hunt: choose one.", ("+3 Cards and add 1 VP to the Wild Hunt pile", "Gain an Estate and, if you do, take the VP from the Wild Hunt pile"))
    if pick.startswith("+3"):
        ctx.draw(3)
        ctx.add_pile_vp("Wild Hunt")
    elif ctx.gain("Estate"):
        ctx.take_pile_vp("Wild Hunt")


def _city_quarter(ctx):
    ctx.add_actions(2)
    n = sum(1 for c in ctx.hand if ctx.is_action(c))
    ctx.log(f"{ctx.player_name} reveals their hand: {n} Action card(s).", "reveal")
    ctx.draw(n)


def _engineer(ctx):
    yield from _gain_up_to(ctx, "Engineer: gain a card costing up to $4.", 4)
    if ctx.source in ctx.in_play:
        chosen = yield ctx.choose("Engineer: you may trash this to gain another card costing up to $4.", ("Trash Engineer",), 0, 1)
        if chosen and ctx.trash_in_play(ctx.source):
            yield from _gain_up_to(ctx, "Engineer: gain a card costing up to $4.", 4)


def _overlord(ctx):
    options = tuple(n for n in ctx.gainable(5, CardType.ACTION) if CardType.COMMAND not in _types(n))
    if not options:
        return
    (card,) = yield ctx.choose("Overlord: play a non-Command Action card from the Supply costing up to $5, leaving it there.", options)
    ctx.log(f"{ctx.player_name}'s Overlord plays {card}.")
    yield from ctx.play_as(card)


def _types(name):
    from .registry import get_card
    return get_card(name).types


def _royal_blacksmith(ctx):
    ctx.draw(5)
    n = ctx.hand.count("Copper")
    ctx.log(f"{ctx.player_name} reveals their hand and discards {n} Copper(s).", "reveal")
    for _ in range(n):
        ctx.discard("Copper")


# ---------------------------------------------------------------- register the cards
R(action("Settlers", 2, _settlers, "+1 Card, +1 Action. Look through your discard pile. You may reveal a Copper from it and put it into your hand. (Top half of the Settlers/Bustling Village pile.)", expansion=SET))
R(action("Bustling Village", 5, _bustling_village, "+1 Card, +3 Actions. Look through your discard pile. You may reveal a Settlers from it and put it into your hand. (Bottom half of the Settlers/Bustling Village pile.)", kingdom=False, expansion=SET))
R(action("Catapult", 3, _catapult, "+$1. Trash a card from your hand. If it costs $3 or more, each other player gains a Curse. If it is a Treasure, each other player discards down to 3 cards in hand. (Top half of the Catapult/Rocks pile.)", extra_types=_ATTACK, expansion=SET))
R(replace(treasure("Rocks", 4, 1, text="$1. When you gain or trash this, gain a Silver; if it is your Buy phase, put the Silver on your deck, otherwise into your hand. (Bottom half of the Catapult/Rocks pile.)", expansion=SET, on_gain=_rocks_gain), on_trash=_rocks_trash))
R(replace(action("Encampment", 2, _encampment, "+2 Cards, +2 Actions. You may reveal a Gold or Plunder from your hand. If you do not, set this aside and return it to the Supply at the start of Clean-up. (Top half of the Encampment/Plunder pile.)", expansion=SET), on_cleanup=_encampment_cleanup))
R(action("Plunder", 5, _plunder, "+$2, +1 VP. (Bottom half of the Encampment/Plunder pile.)", kingdom=False, expansion=SET))
R(action("Gladiator", 3, _gladiator, "+$2. Reveal a card from your hand. The player to your left may reveal a copy from their hand. If they do not, +$1 and trash a Gladiator from the Supply. (Top half of the Gladiator/Fortune pile.)", expansion=SET))
R(_debt(treasure("Fortune", 8, 0, text="+1 Buy. When you play this, double your $ if you have not yet this turn. When you gain this, gain a Gold per Gladiator you have in play. Costs $8 and 8 Debt. (Bottom half of the Gladiator/Fortune pile.)", expansion=SET, on_play=_fortune_play, on_gain=_fortune_gain), 8))
R(action("Patrician", 2, _patrician, "+1 Card, +1 Action. Reveal the top card of your deck. If it costs $5 or more, put it into your hand. (Top half of the Patrician/Emporium pile.)", expansion=SET))
R(action("Emporium", 5, _emporium, "+1 Card, +1 Action, +$1. When you gain this, if you have at least 5 Action cards in play, +2 VP. (Bottom half of the Patrician/Emporium pile.)", kingdom=False, expansion=SET, on_gain=_emporium_gain))

# Castles
R(CardDef("Castles", 3, frozenset({CardType.CASTLE}), kingdom=True, expansion=SET,
          text="A pile of the 8 different Castles (12 cards with 3 or 4 players), cheapest on top; only the top Castle can be bought or gained. "
               "Humble, Crumbling, Small, Haunted, Opulent, Sprawling, Grand and King's Castle."))
R(CardDef("Humble Castle", 3, frozenset({CardType.TREASURE, CardType.VICTORY, CardType.CASTLE}), coins=1, score_fn=_castle_count,
          text="$1. Worth 1 VP per Castle you have.", expansion=SET))
R(CardDef("Crumbling Castle", 4, frozenset({CardType.VICTORY, CardType.CASTLE}), vp=1, on_gain=_crumbling_bonus, on_trash=_crumbling_bonus,
          text="1 VP. When you gain or trash this, +1 VP and gain a Silver.", expansion=SET))
R(CardDef("Small Castle", 5, frozenset({CardType.ACTION, CardType.VICTORY, CardType.CASTLE}), vp=2, on_play=_small_castle,
          text="Trash this or a Castle from your hand. If you do, gain a Castle. 2 VP.", expansion=SET))
R(CardDef("Haunted Castle", 6, frozenset({CardType.VICTORY, CardType.CASTLE}), vp=2, on_gain=_haunted_gain,
          text="2 VP. When you gain this during your turn, gain a Gold, and each other player with 5 or more cards in hand puts 2 cards from their hand onto their deck.", expansion=SET))
R(CardDef("Opulent Castle", 7, frozenset({CardType.ACTION, CardType.VICTORY, CardType.CASTLE}), vp=3, on_play=_opulent,
          text="Discard any number of Victory cards. +$2 per card discarded. 3 VP.", expansion=SET))
R(CardDef("Sprawling Castle", 8, frozenset({CardType.VICTORY, CardType.CASTLE}), vp=4, on_gain=_sprawling_gain,
          text="4 VP. When you gain this, gain a Duchy or 3 Estates.", expansion=SET))
R(CardDef("Grand Castle", 9, frozenset({CardType.VICTORY, CardType.CASTLE}), vp=5, on_gain=_grand_gain,
          text="5 VP. When you gain this, reveal your hand. +1 VP per Victory card in your hand and in play.", expansion=SET))
R(CardDef("King's Castle", 10, frozenset({CardType.VICTORY, CardType.CASTLE}), score_fn=lambda cards: 2 * _castle_count(cards),
          text="Worth 2 VP per Castle you have.", expansion=SET))

R(action("Chariot Race", 3, _chariot_race, "+1 Action. Reveal the top card of your deck and put it into your hand. The player to your left reveals the top card of their deck. If your card costs more, +$1 and +1 VP.", expansion=SET))
R(action("Enchantress", 3, _enchantress, "Until your next turn, the first time each other player plays an Action card on their turn, they get +1 Card and +1 Action instead of following its instructions. At the start of your next turn: +2 Cards.", extra_types=(CardType.ATTACK, CardType.DURATION), expansion=SET))
R(action("Farmers' Market", 3, _farmers_market, "+1 Buy. If there are 4 VP or more on the Farmers' Market pile, take them and trash this. Otherwise add 1 VP to the pile and then +$1 per 1 VP on the pile.", extra_types=(CardType.GATHERING,), expansion=SET))
R(action("Sacrifice", 4, _sacrifice, "Trash a card from your hand. If it is an Action card: +2 Cards, +2 Actions. A Treasure card: +$2. A Victory card: +2 VP.", expansion=SET))
R(action("Temple", 4, _temple, "+1 VP. Trash from 1 to 3 differently named cards from your hand. Add 1 VP to the Temple pile. When you gain this, take the VP from the Temple pile.", extra_types=(CardType.GATHERING,), expansion=SET, on_gain=_temple_gain))
R(action("Villa", 4, _villa, "+2 Actions, +1 Buy, +$1. When you gain this, put it into your hand, +1 Action, and if it is your Buy phase, return to your Action phase.", expansion=SET, on_gain=_villa_gain))
R(action("Archive", 5, _archive, "+1 Action. Set aside the top 3 cards of your deck face down (you may look at them). Now and at the start of your next two turns, put one of them into your hand.", extra_types=(CardType.DURATION,), expansion=SET))
R(replace(treasure("Capital", 5, 6, text="$6, +1 Buy. When you discard this from play, take 6 Debt, and then you may pay off Debt.", expansion=SET, kingdom=True, on_play=lambda ctx: ctx.add_buys(1)), on_cleanup=_capital_cleanup))
R(treasure("Charm", 5, 0, text="When you play this, choose one: +1 Buy and +$2; or the next time you buy a card this turn, you may also gain a differently named card with the same cost.", expansion=SET, kingdom=True, on_play=_charm))
R(CardDef("Crown", 5, frozenset({CardType.ACTION, CardType.TREASURE}), on_play=_crown, kingdom=True, expansion=SET,
          text="If it is your Action phase, you may play an Action card from your hand twice. If it is your Buy phase, you may play a Treasure from your hand twice."))
R(action("Forum", 5, _forum, "+3 Cards, +1 Action. Discard 2 cards. When you buy this, +1 Buy.", expansion=SET, on_gain=_forum_gain))
R(action("Groundskeeper", 5, _groundskeeper, "+1 Card, +1 Action. This turn, when you gain a Victory card, +1 VP.", expansion=SET))
R(action("Legionary", 5, _legionary, "+$3. You may reveal a Gold from your hand. If you do, each other player discards down to 2 cards in hand, then draws a card.", extra_types=_ATTACK, expansion=SET))
R(action("Wild Hunt", 5, _wild_hunt, "Choose one: +3 Cards and add 1 VP to the Wild Hunt pile; or gain an Estate, and if you do, take the VP from the pile.", extra_types=(CardType.GATHERING,), expansion=SET))
R(_debt(action("City Quarter", 0, _city_quarter, "+2 Actions. Reveal your hand. +1 Card per Action card revealed. Costs 8 Debt.", expansion=SET), 8))
R(_debt(action("Engineer", 0, _engineer, "Gain a card costing up to $4. You may trash this. If you do, gain a card costing up to $4. Costs 4 Debt.", expansion=SET), 4))
R(_debt(action("Overlord", 0, _overlord, "Play a non-Command Action card from the Supply costing up to $5, leaving it there. Costs 8 Debt.", extra_types=(CardType.COMMAND,), expansion=SET), 8))
R(_debt(action("Royal Blacksmith", 0, _royal_blacksmith, "+5 Cards. Reveal your hand; discard the Coppers. Costs 8 Debt.", expansion=SET), 8))


# ---------------------------------------------------------------- Events
def _event(name: str, cost: int, text: str, fn, debt: int = 0) -> CardDef:
    return register(CardDef(name, cost, frozenset({CardType.EVENT}), on_play=fn, text=text + (f" (Costs ${cost} and {debt} Debt.)" if debt and cost else
                                                                                           f" (Costs {debt} Debt.)" if debt else ""),
                            kingdom=False, expansion=SET, debt_cost=debt))


def _advance(ctx):
    options = tuple(sorted({c for c in ctx.hand if ctx.is_action(c)}))
    if not options:
        return
    chosen = yield ctx.choose("Advance: you may trash an Action card from your hand to gain an Action card costing up to $6.", options, 0, 1)
    if chosen:
        ctx.trash(chosen[0])
        yield from _gain_up_to(ctx, "Advance: gain an Action card costing up to $6.", 6, CardType.ACTION)


def _annex(ctx):
    discard = ctx.discard_pile
    if discard:
        chosen = yield ctx.choose("Annex: choose up to 5 cards to leave in your discard pile; the rest are shuffled into your deck.",
                                  tuple(sorted(discard)), 0, min(5, len(discard)))
        ctx.shuffle_discard_into_deck_except(chosen)
    ctx.gain("Duchy")


def _banquet(ctx):
    ctx.gain("Copper")
    ctx.gain("Copper")
    options = tuple(c for c in ctx.gainable(5) if not ctx.is_victory(c))
    if options:
        (card,) = yield ctx.choose("Banquet: gain a non-Victory card costing up to $5.", options)
        ctx.gain(card)


def _conquest(ctx):
    ctx.gain("Silver")
    ctx.gain("Silver")
    n = ctx.gained_this_turn().count("Silver")
    ctx.log(f"{ctx.player_name} has gained {n} Silver this turn.")
    ctx.add_vp(n)


def _delve(ctx):
    ctx.add_buys(1)
    ctx.gain("Silver")


def _dominate(ctx):
    if ctx.gain("Province"):
        ctx.add_vp(9)


def _donate(ctx):
    ctx.bump_count("Donate")
    ctx.log(f"{ctx.player_name} will donate after this turn.")


def _ritual(ctx):
    if ctx.gain("Curse") and ctx.hand:
        (card,) = yield ctx.choose("Ritual: trash a card from your hand for +1 VP per $1 it costs.", tuple(sorted(set(ctx.hand))))
        cost = ctx.cost_of(card)
        ctx.trash(card)
        ctx.add_vp(cost)


def _salt_the_earth(ctx):
    ctx.add_vp(1)
    options = ctx.gainable(99, CardType.VICTORY)
    if options:
        (card,) = yield ctx.choose("Salt the Earth: trash a Victory card from the Supply.", options)
        ctx.trash_from_supply(card)


def _tax(ctx):
    options = ctx.supply_pile_names()
    (card,) = yield ctx.choose("Tax: add 2 Debt to a Supply pile (whoever buys from it takes the Debt).", options)
    ctx.add_pile_debt(card, 2)


def _triumph(ctx):
    if ctx.gain("Estate"):
        ctx.add_vp(len(ctx.gained_this_turn()))


def _wedding(ctx):
    ctx.add_vp(1)
    ctx.gain("Gold")


def _windfall(ctx):
    if ctx.deck_size == 0 and not ctx.discard_pile:
        for _ in range(3):
            ctx.gain("Gold")
    else:
        ctx.log("Windfall has no effect: your deck or discard pile is not empty.")


_event("Advance", 0, "You may trash an Action card from your hand. If you do, gain an Action card costing up to $6.", _advance)
_event("Annex", 0, "Look through your discard pile. Choose up to 5 cards from it and shuffle the rest into your deck. Gain a Duchy.", _annex, debt=8)
_event("Banquet", 3, "Gain two Coppers and a non-Victory card costing up to $5.", _banquet)
_event("Conquest", 6, "Gain 2 Silvers. +1 VP per Silver you have gained this turn.", _conquest)
_event("Delve", 2, "+1 Buy. Gain a Silver.", _delve)
_event("Dominate", 14, "Gain a Province. If you do, +9 VP.", _dominate)
_event("Donate", 0, "After this turn, put all cards from your deck and discard pile into your hand, trash any number of them, shuffle the rest into your deck, then draw 5 cards.", _donate, debt=8)
_event("Ritual", 4, "Gain a Curse. If you do, trash a card from your hand. +1 VP per $1 it costs.", _ritual)
_event("Salt the Earth", 4, "+1 VP. Trash a Victory card from the Supply.", _salt_the_earth)
_event("Tax", 2, "Add 2 Debt to a Supply pile. (Setup: add 1 Debt to each Supply pile.) When a player buys a card, they take the Debt from its pile.", _tax)
_event("Triumph", 0, "Gain an Estate. If you did, +1 VP per card you have gained this turn.", _triumph, debt=5)
_event("Wedding", 4, "+1 VP. Gain a Gold.", _wedding, debt=3)
_event("Windfall", 5, "If your deck and discard pile are empty, gain 3 Golds.", _windfall)

# ---------------------------------------------------------------- Landmarks
LANDMARKS = {
    "Aqueduct": "When you gain a Treasure, move 1 VP from its pile to this. When you gain a Victory card, take the VP from this. Setup: put 8 VP on the Silver and Gold piles.",
    "Arena": "At the start of your Buy phase, you may discard an Action card. If you do, take 2 VP from here. Setup: 6 VP here per player.",
    "Bandit Fort": "When scoring, -2 VP for each Silver and each Gold you have.",
    "Basilica": "When you buy a card, if you have $2 or more left, take 2 VP from here. Setup: 6 VP here per player.",
    "Baths": "When you end your turn without having gained a card, take 2 VP from here. Setup: 6 VP here per player.",
    "Battlefield": "When you gain a Victory card, take 2 VP from here. Setup: 6 VP here per player.",
    "Colonnade": "When you gain an Action card in your Buy phase, if you have a copy of it in play, take 2 VP from here. Setup: 6 VP here per player.",
    "Defiled Shrine": "When you gain an Action, move 1 VP from its pile to this. When you buy a Curse, take the VP from this. Setup: put 2 VP on each non-Gathering Action Supply pile.",
    "Fountain": "When scoring, 15 VP if you have at least 10 Coppers.",
    "Keep": "When scoring, 5 VP per differently named Treasure you have that you have more copies of than each other player, or tied for most.",
    "Labyrinth": "When you gain a 2nd card in one of your turns, take 2 VP from here. Setup: 6 VP here per player.",
    "Mountain Pass": "When you are the first player to gain a Province, after that turn, each player bids once, up to 40 Debt, ending with you. The high bidder gets +8 VP and takes the Debt they bid.",
    "Museum": "When scoring, 2 VP per differently named card you have.",
    "Obelisk": "When scoring, 2 VP per card you have from the chosen pile. Setup: choose a random Action Supply pile.",
    "Orchard": "When scoring, 4 VP per differently named Action card you have 3 or more copies of.",
    "Palace": "When scoring, 3 VP per set you have of Copper-Silver-Gold.",
    "Tomb": "When you trash a card, +1 VP.",
    "Tower": "When scoring, 1 VP per non-Victory card you have from an empty Supply pile.",
    "Triumphal Arch": "When scoring, 3 VP per copy you have of the 2nd most common Action card among your cards (if it is a tie, count either).",
    "Wall": "When scoring, -1 VP per card you have after the first 15.",
    "Wolf Den": "When scoring, -3 VP per card you have exactly one copy of.",
}
for _name, _text in LANDMARKS.items():
    register(CardDef(_name, 0, frozenset({CardType.LANDMARK}), text=_text, kingdom=False, expansion=SET))
