"""The Renaissance expansion (2018): 25 Kingdom cards, 20 Projects, 5 Artifacts, and Villagers.

  * Villagers (``PlayerState.villagers``): tokens spent for +1 Action each in the Action phase (``SpendVillager``).
    Coffers are the Guilds ones (``SpendCoffers``).
  * Projects are ``CardDef`` objects of type PROJECT sitting in ``GameState.events``: buying one (``BuyEvent``) uses a Buy and its cost in $
    and puts a cube on it (``PlayerState.projects``). The Projects' effects are hooked into the turn by ``engine/renaissance.py``,
    ``Game`` and a few engine helpers (Canal in ``card_cost``, Capitalism in ``has_type``, Citadel in ``resolve``, Star Chart in ``take_top_cards``).
  * Artifacts (``ARTIFACTS``) are not cards: ``GameState.artifacts`` says who holds each one.
"""

from __future__ import annotations

from .adventures import _gain_up_to
from .alchemy import _put_back_in_any_order
from .base import CardDef, CardType
from .registry import get_card, register

SET = "Renaissance"
T = CardType

ARTIFACTS = {
    "Flag": "When drawing your hand, +1 Card.",
    "Horn": "Once per turn, when you discard a Border Guard from play, you may put it onto your deck.",
    "Key": "At the start of your turn, +$1.",
    "Lantern": "Your Border Guards reveal 3 cards and discard 2. (It takes all 3 being Actions to take the Horn.)",
    "Treasure Chest": "At the start of your Buy phase, gain a Gold.",
}


def _cost_between(ctx, card: str, low: int, high: int) -> bool:
    """Does the card cost from $low to $high, with no Potion or Debt in the cost?"""
    return low <= ctx.cost_of(card) <= high and not ctx.potion_cost_of(card) and not get_card(card).debt_cost


def K(name, cost, types, fn, text, **kw):
    return register(CardDef(name, cost, frozenset(types), on_play=fn, text=text, kingdom=True, expansion=SET, **kw))


# ---------------------------------------------------------------- Kingdom cards
def _acting_troupe(ctx):
    ctx.add_villagers(4)
    ctx.trash_self()                         # (even if it cannot be trashed, e.g. played twice, the Villagers are kept)


def _border_guard(ctx):
    ctx.add_actions(1)
    lantern = ctx.artifact_owner("Lantern") == ctx.player
    n = 3 if lantern else 2
    cards = ctx.take_to_set_aside(n, reveal=True)
    if not cards:
        return
    (keep,) = yield ctx.choose(f"Border Guard: put one of the {len(cards)} revealed cards into your hand and discard the rest.", tuple(sorted(set(cards))))
    rest = list(cards)
    rest.remove(keep)
    ctx.set_aside_to_hand(keep)
    for card in rest:
        ctx.discard_set_aside(card)
    if len(cards) == n and all(get_card(c).is_type(T.ACTION) for c in cards):
        if lantern:
            chosen = yield ctx.choose("Border Guard: all three were Actions. You may take the Horn.", ("Take the Horn",), 0, 1)
            if chosen:
                ctx.take_artifact("Horn")
        else:
            (artifact,) = yield ctx.choose("Border Guard: both were Actions. Take the Lantern or the Horn.", ("Lantern", "Horn"))
            ctx.take_artifact(artifact)


def _cargo_ship(ctx):
    ctx.add_coins(2)
    ctx.add_duration_entry(_cargo_ship_start, {"cards": []})      # the entry also records the card that gets set aside on it


def _cargo_ship_start(ctx, entry):
    for card in entry.data["cards"]:
        ctx.put_on_mat(card, "hand", source="cargo_aside")
    if entry.data["cards"]:
        ctx.log(f"{ctx.player_name} puts {', '.join(entry.data['cards'])} from Cargo Ship into their hand.")


def _ducat(ctx):
    ctx.add_coffers(1)
    ctx.add_buys(1)


def _ducat_gain(ctx, event):
    if "Copper" in ctx.hand:
        chosen = yield ctx.choose("Ducat: you may trash a Copper from your hand.", ("Trash a Copper",), 0, 1)
        if chosen:
            ctx.trash("Copper")


def _experiment(ctx):
    ctx.draw(2)
    ctx.add_actions(1)
    ctx.return_to_pile(ctx.source)                         # (fails quietly if it is not in play any more)


def _experiment_gain(ctx, event):
    if ctx.consume_count("exp_skip"):                     # this is the extra copy, which does not bring another
        return
    ctx.bump_count("exp_skip")
    if not ctx.gain("Experiment"):
        ctx.consume_count("exp_skip")


def _flag_bearer(ctx):
    ctx.add_coins(2)


def _take_flag(ctx, event):
    ctx.take_artifact("Flag")


def _hideout(ctx):
    ctx.draw(1)
    ctx.add_actions(2)
    if ctx.hand:
        (card,) = yield ctx.choose("Hideout: trash a card from your hand. If it's a Victory card, gain a Curse.", tuple(sorted(set(ctx.hand))))
        ctx.trash(card)
        if ctx.is_victory(card):
            ctx.gain("Curse")


def _improve(ctx):
    ctx.add_coins(2)
    ctx.bump_count("ren:improve")                         # at the start of Clean-up, see engine/renaissance.py


def _inventor(ctx):
    yield from _gain_up_to(ctx, "Inventor: gain a card costing up to $4.", 4)
    ctx.reduce_costs(1)


def _lackeys(ctx):
    ctx.draw(2)


def _lackeys_gain(ctx, event):
    ctx.add_villagers(2)


def _mountain_village(ctx):
    ctx.add_actions(2)
    options = tuple(sorted(set(ctx.discard_pile)))
    if not options:
        ctx.draw(1)
        return
    (card,) = yield ctx.choose("Mountain Village: look through your discard pile and put a card from it into your hand.", options)
    ctx.discard_to_hand(card)


def _old_witch(ctx):
    ctx.draw(3)
    targets = yield from ctx.attack()
    for p in targets:
        ctx.gain("Curse", p)
        if "Curse" in ctx.hand_of(p):
            chosen = yield ctx.choose("Old Witch: you may trash a Curse from your hand.", ("Trash a Curse",), 0, 1, player=p)
            if chosen:
                ctx.trash("Curse", player=p)


def _patron(ctx):
    ctx.add_villagers(1)
    ctx.add_coins(2)


def _priest(ctx):
    ctx.add_coins(2)
    if ctx.hand:
        (card,) = yield ctx.choose("Priest: trash a card from your hand.", tuple(sorted(set(ctx.hand))))
        ctx.trash(card)
    ctx.bump_count("ren:priest")                          # from now on, +$2 whenever you trash a card this turn


def _recruiter(ctx):
    ctx.draw(2)
    if ctx.hand:
        (card,) = yield ctx.choose("Recruiter: trash a card from your hand. +1 Villager per $1 it costs.", tuple(sorted(set(ctx.hand))))
        cost = ctx.cost_of(card)
        ctx.trash(card)
        ctx.add_villagers(cost)


def _research(ctx):
    ctx.add_actions(1)
    if not ctx.hand:
        return
    (card,) = yield ctx.choose("Research: trash a card from your hand. Per $1 it costs, set aside a card from your deck.", tuple(sorted(set(ctx.hand))))
    cost = ctx.cost_of(card)
    ctx.trash(card)
    if cost <= 0:
        return
    cards = ctx.take_to_set_aside(cost)
    for c in cards:
        ctx.put_on_mat(c, "research_aside", source="set_aside")
    if cards:
        ctx.add_duration(_research_start, list(cards))


def _research_start(ctx, entry):
    for card in entry.data:
        ctx.put_on_mat(card, "hand", source="research_aside")
    ctx.log(f"{ctx.player_name} puts {len(entry.data)} card(s) set aside by Research into their hand.")


def _scepter(ctx):
    options = ctx.played_this_turn()
    plus, replay = "+$2", "Replay an Action card"
    modes = (plus, replay) if options else (plus,)
    (mode,) = yield ctx.choose("Scepter: choose one: +$2; or replay an Action card you played this turn that's still in play.", modes)
    if mode == plus:
        ctx.add_coins(2)
        return
    (card,) = yield ctx.choose("Scepter: replay which Action card?", options)
    yield from ctx.resolve(card)


def _scholar(ctx):
    ctx.discard_hand()
    ctx.draw(7)


def _sculptor(ctx):
    gained = yield from _gain_up_to(ctx, "Sculptor: gain a card to your hand costing up to $4.", 4, destination="hand")
    if gained and ctx.is_treasure(gained):
        ctx.add_villagers(1)


def _seer(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    cards = ctx.take_to_set_aside(3, reveal=True)
    rest = []
    for card in cards:
        if _cost_between(ctx, card, 2, 4):
            ctx.set_aside_to_hand(card)
        else:
            rest.append(card)
    yield from _put_back_in_any_order(ctx, rest)


def _silk_merchant(ctx):
    ctx.draw(2)
    ctx.add_buys(1)


def _silk_merchant_both(ctx, event):
    ctx.add_coffers(1)
    ctx.add_villagers(1)


def _spices(ctx):
    ctx.add_buys(1)


def _spices_gain(ctx, event):
    ctx.add_coffers(2)


def _swashbuckler(ctx):
    ctx.draw(3)
    if ctx.discard_pile:
        ctx.add_coffers(1)
        if ctx.coffers >= 4:
            ctx.take_artifact("Treasure Chest")


def _treasurer(ctx):
    ctx.add_coins(3)
    trash_opt, gain_opt, key_opt = "Trash a Treasure from your hand", "Gain a Treasure from the trash to your hand", "Take the Key"
    options = []
    if any(ctx.is_treasure(c) for c in ctx.hand):
        options.append(trash_opt)
    if any(ctx.is_treasure(c) for c in ctx.trash_pile()):
        options.append(gain_opt)
    options.append(key_opt)
    (mode,) = yield ctx.choose("Treasurer: choose one.", tuple(options))
    if mode == trash_opt:
        (card,) = yield ctx.choose("Treasurer: trash a Treasure from your hand.", tuple(sorted({c for c in ctx.hand if ctx.is_treasure(c)})))
        ctx.trash(card)
    elif mode == gain_opt:
        (card,) = yield ctx.choose("Treasurer: gain a Treasure from the trash to your hand.", tuple(sorted({c for c in ctx.trash_pile() if ctx.is_treasure(c)})))
        ctx.gain_from_trash(card, destination="hand")
    else:
        ctx.take_artifact("Key")


def _villain(ctx):
    ctx.add_coffers(2)
    targets = yield from ctx.attack()
    for p in targets:
        hand = ctx.hand_of(p)
        if len(hand) < 5:
            continue
        options = tuple(sorted({c for c in hand if ctx.cost_of(c) >= 2}))
        if options:
            (card,) = yield ctx.choose("Villain: discard a card costing $2 or more.", options, player=p)
            ctx.discard(card, player=p)
        else:
            ctx.log(f"{ctx.name_of(p)} reveals their hand: no card costing $2 or more.", "reveal")


K("Border Guard", 2, {T.ACTION}, _border_guard, "+1 Action. Reveal the top 2 cards of your deck. Put one into your hand and discard the other. If both were Actions, take the Lantern or Horn.")
K("Ducat", 2, {T.TREASURE}, _ducat, "+1 Coffers, +1 Buy. When you gain this, you may trash a Copper from your hand.", on_gain=_ducat_gain)
K("Lackeys", 2, {T.ACTION}, _lackeys, "+2 Cards. When you gain this, +2 Villagers.", on_gain=_lackeys_gain)
K("Acting Troupe", 3, {T.ACTION}, _acting_troupe, "+4 Villagers. Trash this.")
K("Cargo Ship", 3, {T.ACTION, T.DURATION}, _cargo_ship, "+$2. Once this turn, when you gain a card, you may set it aside face up (on this). At the start of your next turn, put it into your hand.")
K("Experiment", 3, {T.ACTION}, _experiment, "+2 Cards, +1 Action. Return this to the Supply. When you gain this, gain another Experiment (that doesn't come with another).", on_gain=_experiment_gain)
K("Improve", 3, {T.ACTION}, _improve, "+$2. At the start of Clean-up, you may trash an Action card you would discard from play this turn, to gain a card costing exactly $1 more than it.")
K("Flag Bearer", 4, {T.ACTION}, _flag_bearer, "+$2. When you gain or trash this, take the Flag.", on_gain=_take_flag, on_trash=_take_flag)
K("Hideout", 4, {T.ACTION}, _hideout, "+1 Card, +2 Actions. Trash a card from your hand. If it's a Victory card, gain a Curse.")
K("Inventor", 4, {T.ACTION}, _inventor, "Gain a card costing up to $4, then cards cost $1 less this turn (but not less than $0).")
K("Mountain Village", 4, {T.ACTION}, _mountain_village, "+2 Actions. Look through your discard pile and put a card from it into your hand; if you can't, +1 Card.")
K("Patron", 4, {T.ACTION, T.REACTION}, _patron, "+1 Villager, +$2. When something causes you to reveal this (using the word \"reveal\"), +1 Coffers.")
K("Priest", 4, {T.ACTION}, _priest, "+$2. Trash a card from your hand. For the rest of this turn, when you trash a card, +$2.")
K("Research", 4, {T.ACTION, T.DURATION}, _research, "+1 Action. Trash a card from your hand. Per $1 it costs, set aside a card from your deck face down (on this). At the start of your next turn, put those cards into your hand.")
K("Silk Merchant", 4, {T.ACTION}, _silk_merchant, "+2 Cards, +1 Buy. When you gain or trash this, +1 Coffers and +1 Villager.", on_gain=_silk_merchant_both, on_trash=_silk_merchant_both)
K("Old Witch", 5, {T.ACTION, T.ATTACK}, _old_witch, "+3 Cards. Each other player gains a Curse and may trash a Curse from their hand.")
K("Recruiter", 5, {T.ACTION}, _recruiter, "+2 Cards. Trash a card from your hand. +1 Villager per $1 it costs.")
K("Scepter", 5, {T.TREASURE}, _scepter, "When you play this, choose one: +$2; or replay an Action card you played this turn that's still in play.")
K("Scholar", 5, {T.ACTION}, _scholar, "Discard your hand. +7 Cards.")
K("Sculptor", 5, {T.ACTION}, _sculptor, "Gain a card to your hand costing up to $4. If it's a Treasure, +1 Villager.")
K("Seer", 5, {T.ACTION}, _seer, "+1 Card, +1 Action. Reveal the top 3 cards of your deck. Put the ones costing from $2 to $4 into your hand. Put the rest back in any order.")
K("Spices", 5, {T.TREASURE}, _spices, "$2. +1 Buy. When you gain this, +2 Coffers.", coins=2, on_gain=_spices_gain)
K("Swashbuckler", 5, {T.ACTION}, _swashbuckler, "+3 Cards. If your discard pile has any cards in it: +1 Coffers, then if you have at least 4 Coffers tokens, take the Treasure Chest.")
K("Treasurer", 5, {T.ACTION}, _treasurer, "+$3. Choose one: Trash a Treasure from your hand; or gain a Treasure from the trash to your hand; or take the Key.")
K("Villain", 5, {T.ACTION, T.ATTACK}, _villain, "+2 Coffers. Each other player with 5 or more cards in hand discards one costing $2 or more (or reveals they can't).")


# ---------------------------------------------------------------- Projects
def _project(name, cost, text):
    def take(ctx):
        ctx.take_project()
    return register(CardDef(name, cost, frozenset({T.PROJECT}), on_play=take, text=text, kingdom=False, expansion=SET))


_project("Cathedral", 3, "At the start of your turn, trash a card from your hand.")
_project("City Gate", 3, "At the start of your turn, +1 Card, then put a card from your hand onto your deck.")
_project("Pageant", 3, "At the end of your Buy phase, you may pay $1 for +1 Coffers.")
_project("Star Chart", 3, "When you shuffle, you may pick one of the cards to go on top.")
_project("Exploration", 4, "At the end of your Buy phase, if you didn't buy any cards, +1 Coffers and +1 Villager.")
_project("Fair", 4, "At the start of your turn, +1 Buy.")
_project("Silos", 4, "At the start of your turn, discard any number of Coppers, revealed, and draw that many cards.")
_project("Sinister Plot", 4, "At the start of your turn, add a token here, or remove your tokens here for +1 Card each.")
_project("Sewers", 4, "When you trash a card other than with this, you may trash a card from your hand.")
_project("Academy", 5, "When you gain an Action card, +1 Villager.")
_project("Capitalism", 5, "During your turns, Actions with + amounts in their text are also Treasures.")
_project("Fleet", 5, "After the game ends, there's an extra round of turns just for players with this.")
_project("Guildhall", 5, "When you gain a Treasure, +1 Coffers.")
_project("Piazza", 5, "At the start of your turn, reveal the top card of your deck. If it's an Action, play it.")
_project("Road Network", 5, "When another player gains a Victory card, +1 Card.")
_project("Barracks", 6, "At the start of your turn, +1 Action.")
_project("Crop Rotation", 6, "At the start of your turn, you may discard a Victory card for +2 Cards.")
_project("Innovation", 6, "The first time you gain an Action card in each of your turns, you may set it aside. If you do, play it.")
_project("Canal", 7, "During your turns, cards cost $1 less, but not less than $0.")
_project("Citadel", 8, "The first time you play an Action card during each of your turns, play it again afterwards.")
