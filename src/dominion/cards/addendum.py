"""Cards added later to complete the sets: Adventures' Treasure Trove, the 2nd-edition Seaside and Hinterlands cards, the retired 1st-edition Base and
Intrigue cards, and the Promos set (Black Market, Church, Dismantle, Envoy, Sauna/Avanto, Walled Village, Governor, Marchland, Stash, Captain, Prince, Summon).

Engine hooks for the ones that react to something are in ``engine/addendum.py`` (gains, Treasure plays, Clean-up); Stash's shuffle choice is in
``engine/plunder.shuffle_steps``; the Black Market deck is ``GameState.black_market`` (its cards are counted in ``offsupply`` too).
"""

from __future__ import annotations

from .base import CardDef, CardType
from .plunder import play_aside_all, play_from_hand
from .registry import get_card, register

T = CardType


def A(name, cost, types, fn, text, expansion, **kw):
    return register(CardDef(name, cost, frozenset(types), on_play=fn, text=text, kingdom=kw.pop("kingdom", True), expansion=expansion, **kw))


def _distinct(cards) -> tuple:
    return tuple(sorted(set(cards)))


def _start(coins=0, cards=0, buys=0):
    def start(ctx, entry):
        if cards:
            ctx.draw(cards)
        if buys:
            ctx.add_buys(buys)
        if coins:
            ctx.add_coins(coins)
    return start


def _discard_down(ctx, p, n, label):
    excess = len(ctx.hand_of(p)) - n
    if excess > 0:
        chosen = yield ctx.choose(f"{ctx.player_name}'s {label}: discard {excess} card(s) to get down to {n}.", ctx.hand_of(p), excess, excess, player=p)
        for c in chosen:
            ctx.discard(c, player=p)


# ================================================================== Adventures
def _treasure_trove(ctx):
    ctx.gain("Gold")
    ctx.gain("Copper")


A("Treasure Trove", 5, (T.TREASURE,), _treasure_trove, "When you play this, gain a Gold and a Copper.", "Adventures", coins=2)


# ================================================================== Seaside, 2nd edition
def _astrolabe(ctx):
    ctx.add_buys(1)
    ctx.add_duration(_start(coins=1, buys=1))


def _monkey(ctx):
    ctx.add_duration(_start(cards=1), {"monkey": True})


def _sea_chart(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    cards = ctx.take_to_set_aside(1, reveal=True)
    if not cards:
        return
    card = cards[0]
    if card in ctx.in_play:
        ctx.log(f"Sea Chart: you have a copy of {card} in play, it goes into your hand.")
        ctx.set_aside_to_hand(card)
    else:
        yield from ctx.put_back_in_order([card], "Sea Chart: put it back on your deck.")


def _blockade(ctx):
    targets = yield from ctx.attack()
    options = ctx.gainable(4)
    card = None
    if options:
        (card,) = yield ctx.choose("Blockade: gain a card costing up to $4, setting it aside.", options)
        if not ctx.gain_aside(card):
            card = None
    ctx.add_duration(_blockade_start, {"blockade": card, "targets": list(targets)})


def _blockade_start(ctx, entry):
    card = entry.data["blockade"]
    if card and card in ctx.aside_cards():
        ctx.log(f"Blockade: {card} goes into your hand.")
        ctx.aside_to(card, "hand")


def _sailor(ctx):
    ctx.add_actions(1)
    ctx.bump_count("sailor")
    ctx.add_duration(_sailor_start)


def _sailor_start(ctx, entry):
    ctx.add_coins(2)
    if ctx.hand:
        chosen = yield ctx.choose("Sailor: you may trash a card from your hand.", _distinct(ctx.hand), 0, 1)
        if chosen:
            ctx.trash(chosen[0])


def _tide_pools(ctx):
    ctx.draw(3)
    ctx.add_actions(1)
    ctx.add_duration(_tide_pools_start)


def _discard_two(ctx):
    n = min(2, len(ctx.hand))
    if n:
        chosen = yield ctx.choose("Discard 2 cards.", tuple(sorted(ctx.hand)), n, n)
        for c in chosen:
            ctx.discard(c)


def _tide_pools_start(ctx, entry):
    yield from _discard_two(ctx)


def _corsair(ctx):
    ctx.add_coins(2)
    targets = yield from ctx.attack()
    ctx.add_duration(_start(cards=1), {"corsair": list(targets)})


def _pirate(ctx):
    ctx.add_duration(_pirate_start)


def _pirate_start(ctx, entry):
    options = ctx.gainable(6, T.TREASURE)
    if options:
        (card,) = yield ctx.choose("Pirate: gain a Treasure costing up to $6 to your hand.", options)
        ctx.gain(card, destination="hand")


def _sea_witch(ctx):
    ctx.draw(2)
    targets = yield from ctx.attack()
    for p in targets:
        ctx.gain("Curse", player=p)
    ctx.add_duration(_sea_witch_start)


def _sea_witch_start(ctx, entry):
    ctx.draw(2)
    yield from _discard_two(ctx)


def _pirate_react(ctx):
    pass


A("Astrolabe", 3, (T.TREASURE, T.DURATION), _astrolabe, "Now and at the start of your next turn: +$1, +1 Buy.", "Seaside", coins=1)
A("Monkey", 3, (T.ACTION, T.DURATION), _monkey, "Until your next turn, when the player to your right gains a card, +1 Card. At the start of your next turn, +1 Card.", "Seaside")
A("Sea Chart", 3, (T.ACTION,), _sea_chart, "+1 Card, +1 Action. Reveal the top card of your deck. If you have a copy of it in play, put it into your hand.", "Seaside")
A("Blockade", 4, (T.ACTION, T.ATTACK, T.DURATION), _blockade, "Gain a card costing up to $4, setting it aside. At the start of your next turn, put it into your hand. While it's set aside, when another player gains a copy of it on their turn, they gain a Curse.", "Seaside")
A("Sailor", 4, (T.ACTION, T.DURATION), _sailor, "+1 Action. Once this turn, when you gain a Duration card, you may play it. At the start of your next turn, +$2 and you may trash a card from your hand.", "Seaside")
A("Tide Pools", 4, (T.ACTION, T.DURATION), _tide_pools, "+3 Cards, +1 Action. At the start of your next turn, discard 2 cards.", "Seaside")
A("Corsair", 5, (T.ACTION, T.ATTACK, T.DURATION), _corsair, "+$2. At the start of your next turn, +1 Card. Until then, each other player trashes the first Silver or Gold they play each turn.", "Seaside")
A("Pirate", 5, (T.ACTION, T.DURATION, T.REACTION), _pirate, "At the start of your next turn, gain a Treasure costing up to $6 to your hand. When any player gains a Treasure, you may play this from your hand.", "Seaside")
A("Sea Witch", 5, (T.ACTION, T.ATTACK, T.DURATION), _sea_witch, "+2 Cards. Each other player gains a Curse. At the start of your next turn, +2 Cards, then discard 2 cards.", "Seaside")


# ================================================================== Hinterlands, 2nd edition
def _guard_dog(ctx):
    ctx.draw(2)
    if len(ctx.hand) <= 5:
        ctx.draw(2)


def _guard_dog_react(ctx):
    ctx.put_in_play("Guard Dog", "hand")
    _guard_dog(ctx)


def _nomads(ctx):
    ctx.add_buys(1)
    ctx.add_coins(2)


def _nomads_gain(ctx, event):
    ctx.log("Nomads: +$2.")
    ctx.add_coins(2)


def _nomads_trash(ctx, event):
    ctx.log("Nomads: +$2.")
    ctx.add_coins(2)


def _trail(ctx):
    ctx.draw(1)
    ctx.add_actions(2)


def _trail_trash(ctx, event):
    chosen = yield ctx.choose("Trail: you trashed it. You may play it (+1 Card, +2 Actions).", ("Play Trail",), 0, 1)
    if chosen:
        ctx.log("Trail is played from the trash.", "play")
        ctx.draw(1)
        ctx.add_actions(2)


def _weaver(ctx):
    silvers, card = "Gain two Silvers", "Gain a card costing up to $4"
    options = [silvers] + ([card] if ctx.gainable(4) else [])
    (mode,) = yield ctx.choose("Weaver: choose one.", tuple(options))
    if mode == silvers:
        ctx.gain("Silver")
        ctx.gain("Silver")
    else:
        (new,) = yield ctx.choose("Weaver: gain a card costing up to $4.", ctx.gainable(4))
        ctx.gain(new)


def _berserker(ctx):
    cost = ctx.cost_of("Berserker")
    options = ctx.gainable(cost - 1)
    if options:
        (card,) = yield ctx.choose("Berserker: gain a card costing less than this.", options)
        ctx.gain(card)
    targets = yield from ctx.attack()
    for p in targets:
        yield from _discard_down(ctx, p, 3, "Berserker")


def _berserker_gain(ctx, event):
    if any(ctx.is_action(c) for c in ctx.in_play) and ctx.gained_card_present(event) and event.zone in ("discard", "hand"):
        ctx.log("Berserker: you have an Action in play, so it is played.")
        ctx.put_in_play("Berserker", event.zone)
        yield from ctx.resolve("Berserker")


def _cauldron(ctx):
    ctx.add_buys(1)
    ctx.bump_count("cauldron")


def _souk(ctx):
    ctx.add_buys(1)
    total = max(0, ctx.coins + 7 - len(ctx.hand))
    ctx.log(f"Souk: +$7, -$1 per card in hand ({len(ctx.hand)}): you have ${total}.")
    ctx.add_coins(total - ctx.coins)


def _souk_gain(ctx, event):
    if ctx.hand:
        chosen = yield ctx.choose("Souk: you may trash up to 2 cards from your hand.", tuple(sorted(ctx.hand)), 0, min(2, len(ctx.hand)))
        for c in chosen:
            ctx.trash(c)


def _wheelwright(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    if ctx.hand:
        chosen = yield ctx.choose("Wheelwright: you may discard a card to gain an Action costing as much as it or less.", _distinct(ctx.hand), 0, 1)
        if chosen:
            cost = ctx.cost_of(chosen[0])
            ctx.discard(chosen[0])
            options = ctx.gainable(cost, T.ACTION)
            if options:
                (card,) = yield ctx.choose("Wheelwright: gain an Action card.", options)
                ctx.gain(card)


def _witchs_hut(ctx):
    ctx.draw(4)
    n = min(2, len(ctx.hand))
    if not n:
        return
    chosen = yield ctx.choose("Witch's Hut: discard 2 cards, revealed.", tuple(sorted(ctx.hand)), n, n)
    ctx.log(f"{ctx.player_name} reveals {', '.join(chosen)}.", "reveal")
    for c in chosen:
        ctx.discard(c)
    if n == 2 and all(ctx.is_action(c) for c in chosen):
        targets = yield from ctx.attack()
        for p in targets:
            ctx.gain("Curse", player=p)


A("Guard Dog", 3, (T.ACTION, T.REACTION), _guard_dog, "+2 Cards. If you have 5 or fewer cards in hand, +2 Cards. When another player plays an Attack, you may first play this from your hand.", "Hinterlands", on_attack=_guard_dog_react)
A("Nomads", 4, (T.ACTION,), _nomads, "+1 Buy, +$2. When you gain or trash this, +$2.", "Hinterlands", on_gain=_nomads_gain, on_trash=_nomads_trash)
A("Trail", 4, (T.ACTION, T.REACTION), _trail, "+1 Card, +2 Actions. When you gain, trash, or discard this other than in Clean-up, you may play it.", "Hinterlands", on_trash=_trail_trash)
A("Weaver", 4, (T.ACTION, T.REACTION), _weaver, "Gain two Silvers or a card costing up to $4. When you discard this other than in Clean-up, you may play it.", "Hinterlands")
A("Berserker", 5, (T.ACTION, T.ATTACK), _berserker, "Gain a card costing less than this. Each other player discards down to 3 cards in hand. When you gain this, if you have an Action in play, play this.", "Hinterlands", on_gain=_berserker_gain)
A("Cauldron", 5, (T.TREASURE, T.ATTACK), _cauldron, "+1 Buy. The third time you gain an Action card in this turn, each other player gains a Curse.", "Hinterlands", coins=2)
A("Souk", 5, (T.ACTION,), _souk, "+1 Buy, +$7. -$1 per card in your hand (you can't go below $0). When you gain this, trash up to 2 cards from your hand.", "Hinterlands", on_gain=_souk_gain)
A("Wheelwright", 5, (T.ACTION,), _wheelwright, "+1 Card, +1 Action. You may discard a card to gain an Action card costing as much as it or less.", "Hinterlands")
A("Witch's Hut", 5, (T.ACTION, T.ATTACK), _witchs_hut, "+4 Cards. Discard 2 cards, revealed. If they were both Actions, each other player gains a Curse.", "Hinterlands")


# ================================================================== Base, 1st edition
def _chancellor(ctx):
    ctx.add_coins(2)
    chosen = yield ctx.choose("Chancellor: you may put your deck into your discard pile.", ("Put my deck into my discard pile",), 0, 1)
    if chosen:
        ctx.put_deck_into_discard()


def _woodcutter(ctx):
    ctx.add_buys(1)
    ctx.add_coins(2)


def _feast(ctx):
    ctx.trash_self()
    options = ctx.gainable(5)
    if options:
        (card,) = yield ctx.choose("Feast: gain a card costing up to $5.", options)
        ctx.gain(card)


def _spy(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    targets = yield from ctx.attack()
    for p in [ctx.player, *targets]:
        cards = ctx.take_to_set_aside(1, player=p, reveal=True)
        if not cards:
            continue
        discard, keep = "Discard it", "Put it back"
        (mode,) = yield ctx.choose(f"Spy: {ctx.name_of(p)}'s top card is {cards[0]}. Discard it or put it back?", (discard, keep))
        if mode == discard:
            ctx.discard_set_aside(cards[0], player=p)
        else:
            ctx.put_set_aside_on_deck(cards[0], player=p)


def _thief(ctx):
    targets = yield from ctx.attack()
    trashed = []
    for p in targets:
        cards = ctx.take_to_set_aside(2, player=p, reveal=True)
        treasures = _distinct(c for c in cards if ctx.is_treasure(c))
        rest = list(cards)
        if treasures:
            (pick,) = yield ctx.choose(f"Thief: trash one of {ctx.name_of(p)}'s revealed Treasures.", treasures)
            rest.remove(pick)
            ctx.trash_set_aside(pick, player=p)
            trashed.append(pick)
        for c in rest:
            ctx.discard_set_aside(c, player=p)
    for card in trashed:
        chosen = yield ctx.choose(f"Thief: you may gain the trashed {card}.", (f"Gain {card}",), 0, 1)
        if chosen:
            ctx.gain_from_trash(card)


def _adventurer(ctx):
    found, missed = [], []
    while len(found) < 2:
        cards = ctx.take_to_set_aside(1, reveal=True)
        if not cards:
            break
        (found if ctx.is_treasure(cards[0]) else missed).append(cards[0])
    for c in found:
        ctx.set_aside_to_hand(c)
    for c in missed:
        ctx.discard_set_aside(c)


A("Chancellor", 3, (T.ACTION,), _chancellor, "+$2. You may immediately put your deck into your discard pile.", "Base")
A("Woodcutter", 3, (T.ACTION,), _woodcutter, "+1 Buy, +$2.", "Base")
A("Feast", 4, (T.ACTION,), _feast, "Trash this card. Gain a card costing up to $5.", "Base")
A("Spy", 4, (T.ACTION, T.ATTACK), _spy, "+1 Card, +1 Action. Each player (including you) reveals the top card of their deck and either discards it or puts it back, your choice.", "Base")
A("Thief", 4, (T.ACTION, T.ATTACK), _thief, "Each other player reveals the top 2 cards of their deck. If they revealed any Treasure cards, they trash one of them that you choose. You may gain any or all of these trashed cards. They discard the other revealed cards.", "Base")
A("Adventurer", 6, (T.ACTION,), _adventurer, "Reveal cards from your deck until you reveal 2 Treasure cards. Put those Treasure cards into your hand and discard the other revealed cards.", "Base")


# ================================================================== Intrigue, 1st edition
def _secret_chamber(ctx):
    if not ctx.hand:
        return
    chosen = yield ctx.choose("Secret Chamber: discard any number of cards for +$1 each.", tuple(sorted(ctx.hand)), 0, len(ctx.hand))
    for c in chosen:
        ctx.discard(c)
    ctx.add_coins(len(chosen))


def _secret_chamber_react(ctx):
    ctx.draw(2)
    n = min(2, len(ctx.hand))
    if n:
        chosen = yield ctx.choose("Secret Chamber: put 2 cards from your hand on top of your deck.", tuple(sorted(ctx.hand)), n, n)
        for c in chosen:
            ctx.put_hand_on_deck(c)


def _great_hall(ctx):
    ctx.draw(1)
    ctx.add_actions(1)


def _coppersmith(ctx):
    ctx.bump_count("coppersmith")


def _scout(ctx):
    ctx.add_actions(1)
    cards = ctx.take_to_set_aside(4, reveal=True)
    rest = []
    for c in cards:
        if ctx.is_victory(c):
            ctx.set_aside_to_hand(c)
        else:
            rest.append(c)
    yield from ctx.put_back_in_order(rest, "Scout: put the next card back on your deck (top card first).")


def _saboteur(ctx):
    targets = yield from ctx.attack()
    for p in targets:
        missed = []
        found = None
        while True:
            cards = ctx.take_to_set_aside(1, player=p, reveal=True)
            if not cards:
                break
            if ctx.cost_of(cards[0]) >= 3:
                found = cards[0]
                break
            missed.append(cards[0])
        for c in missed:
            ctx.discard_set_aside(c, player=p)
        if found is None:
            continue
        cost = ctx.cost_of(found)
        ctx.trash_set_aside(found, player=p)
        options = ctx.gainable(cost - 2)
        if options:
            chosen = yield ctx.choose(f"Saboteur: {ctx.name_of(p)} may gain a card costing at most $2 less than {found}.", options, 0, 1, player=p)
            if chosen:
                ctx.gain(chosen[0], player=p)


def _tribute(ctx):
    left = ctx.left_player()
    cards = ctx.take_to_set_aside(2, player=left, reveal=True)
    names = _distinct(cards)
    for c in cards:
        ctx.discard_set_aside(c, player=left)
    for name in names:
        if ctx.is_action(name):
            ctx.add_actions(2)
        if ctx.is_treasure(name):
            ctx.add_coins(2)
        if ctx.is_victory(name):
            ctx.draw(2)


A("Secret Chamber", 2, (T.ACTION, T.REACTION), _secret_chamber, "Discard any number of cards. +$1 per card discarded. When another player plays an Attack card, you may reveal this from your hand. If you do, +2 Cards, then put 2 cards from your hand on top of your deck.", "Intrigue", on_attack=_secret_chamber_react)
A("Great Hall", 3, (T.ACTION, T.VICTORY), _great_hall, "1 VP. +1 Card, +1 Action.", "Intrigue", vp=1)
A("Coppersmith", 4, (T.ACTION,), _coppersmith, "Copper produces an extra $1 this turn.", "Intrigue")
A("Scout", 4, (T.ACTION,), _scout, "+1 Action. Reveal the top 4 cards of your deck. Put the revealed Victory cards into your hand. Put the other cards on top of your deck in any order.", "Intrigue")
A("Saboteur", 5, (T.ACTION, T.ATTACK), _saboteur, "Each other player reveals cards from the top of their deck until revealing one costing $3 or more. He trashes that card and may gain a card costing at most $2 less than it. He discards the other revealed cards.", "Intrigue")
A("Tribute", 5, (T.ACTION,), _tribute, "The player to your left reveals then discards the top 2 cards of his deck. For each differently named card revealed, if it is an: Action Card, +2 Actions; Treasure Card, +$2; Victory Card, +2 Cards.", "Intrigue")


# ================================================================== Promos
def _black_market(ctx):
    ctx.add_coins(2)
    cards = ctx.black_market_reveal(3)
    if not cards:
        return
    ctx.log(f"Black Market reveals {', '.join(cards)}.", "reveal")
    treasures = _distinct(c for c in ctx.hand if ctx.is_treasure(c) and not get_card(c).is_type(T.ACTION))
    if treasures:
        chosen = yield ctx.choose("Black Market: you may play Treasures from your hand before buying.", ("Play all my Treasures",), 0, 1)
        if chosen:
            for c in [c for c in ctx.hand if ctx.is_treasure(c) and not get_card(c).is_type(T.ACTION)]:
                if c in ctx.hand:
                    ctx.put_in_play(c)
                    yield from ctx.resolve_treasure(c)
    affordable = tuple(c for c in _distinct(cards) if ctx.cost_of(c) <= ctx.coins and not get_card(c).potion_cost and not get_card(c).debt_cost)
    bought = None
    if affordable and ctx.buys_left() >= 1:
        chosen = yield ctx.choose("Black Market: you may buy one of the revealed cards.", affordable, 0, 1)
        if chosen:
            bought = chosen[0]
            ctx.add_coins(-ctx.cost_of(bought))
            ctx.add_buys(-1)
            ctx.log(f"{ctx.player_name} buys {bought} from the Black Market.", "gain")
            ctx.black_market_gain(bought)
    rest = list(cards)
    if bought is not None:
        rest.remove(bought)
    while len(rest) > 1:
        (card,) = yield ctx.choose("Black Market: put the next unbought card on the bottom of the Black Market deck.", tuple(sorted(set(rest))))
        rest.remove(card)
        ctx.black_market_bottom([card])
    ctx.black_market_bottom(rest)


def _church(ctx):
    ctx.add_actions(1)
    hand = ctx.hand
    chosen = ()
    if hand:
        chosen = yield ctx.choose("Church: set aside up to 3 cards from your hand face down.", tuple(sorted(hand)), 0, min(3, len(hand)))
    for c in chosen:
        ctx.aside(c)
    ctx.add_duration(_church_start, {"cards": list(chosen)})


def _church_start(ctx, entry):
    for c in entry.data["cards"]:
        if c in ctx.aside_cards():
            ctx.aside_to(c, "hand")
    if ctx.hand:
        chosen = yield ctx.choose("Church: you may trash a card from your hand.", _distinct(ctx.hand), 0, 1)
        if chosen:
            ctx.trash(chosen[0])


def _dismantle(ctx):
    if not ctx.hand:
        return
    (card,) = yield ctx.choose("Dismantle: trash a card from your hand. If it costs $1 or more, gain a cheaper card and a Gold.", _distinct(ctx.hand))
    cost = ctx.cost_of(card)
    ctx.trash(card)
    if cost >= 1:
        options = ctx.gainable(cost - 1)
        if options:
            (new,) = yield ctx.choose("Dismantle: gain a cheaper card.", options)
            ctx.gain(new)
        ctx.gain("Gold")


def _envoy(ctx):
    cards = ctx.take_to_set_aside(5, reveal=True)
    if not cards:
        return
    left = ctx.left_player()
    (pick,) = yield ctx.choose(f"{ctx.player_name}'s Envoy revealed {', '.join(cards)}. Choose one for them to discard.", tuple(sorted(set(cards))), player=left)
    rest = list(cards)
    rest.remove(pick)
    ctx.discard_set_aside(pick)
    for c in rest:
        ctx.set_aside_to_hand(c)


def _sauna(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    yield from play_from_hand(ctx, "Sauna: you may play an Avanto from your hand.", lambda c: c == "Avanto")


def _avanto(ctx):
    ctx.draw(3)
    yield from play_from_hand(ctx, "Avanto: you may play a Sauna from your hand.", lambda c: c == "Sauna")


def _walled_village(ctx):
    ctx.draw(1)
    ctx.add_actions(2)


def _governor(ctx):
    ctx.add_actions(1)
    cards, silver, trash = "Each player gets +1 Card (you get +3)", "Each player gains a Silver (you gain a Gold)", "Each player may trash a card from their hand and gain one costing exactly $1 more (you, $2 more)"
    (mode,) = yield ctx.choose("Governor: choose one.", (cards, silver, trash))
    order = [ctx.player, *ctx.other_players()]
    for p in order:
        me = p == ctx.player
        if mode == cards:
            ctx.draw(3 if me else 1, player=p)
        elif mode == silver:
            ctx.gain("Gold" if me else "Silver", player=p)
        else:
            hand = ctx.hand_of(p)
            if not hand:
                continue
            chosen = yield ctx.choose("Governor: you may trash a card from your hand and gain one costing exactly $%d more." % (2 if me else 1), _distinct(hand), 0, 1, player=p)
            if chosen:
                cost = ctx.cost_of(chosen[0]) + (2 if me else 1)
                ctx.trash(chosen[0], player=p)
                options = ctx.gainable(cost, exact=True)
                if options:
                    (new,) = yield ctx.choose("Governor: gain a card costing exactly $%d." % cost, options, player=p)
                    ctx.gain(new, player=p)


def _marchland_gain(ctx, event):
    ctx.add_buys(1)
    if ctx.hand:
        chosen = yield ctx.choose("Marchland: you may discard any number of cards for +$1 each.", tuple(sorted(ctx.hand)), 0, len(ctx.hand))
        for c in chosen:
            ctx.discard(c)
        ctx.add_coins(len(chosen))


def _captain_step(ctx):
    options = tuple(c for c in ctx.gainable(4, T.ACTION) if not get_card(c).is_type(T.DURATION) and not get_card(c).is_type(T.COMMAND))
    if options:
        (card,) = yield ctx.choose("Captain: play a non-Duration, non-Command Action card from the Supply costing up to $4, leaving it there.", options)
        ctx.log(f"Captain plays {card} from the Supply.", "play")
        yield from ctx.resolve(card)


def _captain(ctx):
    yield from _captain_step(ctx)
    ctx.add_duration(_captain_start)


def _captain_start(ctx, entry):
    yield from _captain_step(ctx)


def _prince(ctx):
    options = _distinct(c for c in ctx.hand if ctx.is_action(c) and ctx.cost_of(c) <= 4 and not get_card(c).potion_cost and not get_card(c).debt_cost)
    if not options:
        return
    chosen = yield ctx.choose("Prince: you may set this aside, and set aside an Action card from your hand costing up to $4. It is played at the start of each of your turns.", options, 0, 1)
    if not chosen or not ctx.trash_self_to_aside("Prince"):
        return
    ctx.aside(chosen[0])
    ctx.add_wait("never", {"prince": chosen[0], "played": False}, cards=(), handler=_prince_start)


def _prince_start(ctx, entry):
    card = entry.data["prince"]
    if card not in ctx.aside_cards():
        ctx.end_wait(entry)
        return
    ctx.aside_to(card, "in_play")
    entry.data["played"] = True
    ctx.log(f"Prince plays the set-aside {card}.", "play")
    yield from ctx.resolve(card)


def _stash(ctx):
    return None


def _summon(ctx):
    options = ctx.gainable(4, T.ACTION)
    if not options:
        return
    (card,) = yield ctx.choose("Summon: gain an Action card costing up to $4, setting it aside. You play it at the start of your next turn.", options)
    if ctx.gain_aside(card):
        ctx.add_delayed_play("Summon", _summon_start, [card])


def _summon_start(ctx, entry):
    yield from play_aside_all(ctx, entry.data, discard_rest=False)


A("Black Market", 3, (T.ACTION,), _black_market, "+$2. Reveal the top 3 cards of the Black Market deck. You may buy one of them immediately. Put the unbought cards on the bottom of the Black Market deck in any order. (Setup: make a Black Market deck out of 25 unused Kingdom cards.)", "Promos")
A("Church", 3, (T.ACTION, T.DURATION), _church, "+1 Action. Set aside up to 3 cards from your hand face down. At the start of your next turn, put them into your hand, and then you may trash a card from your hand.", "Promos")
A("Dismantle", 4, (T.ACTION,), _dismantle, "Trash a card from your hand. If it costs $1 or more, gain a cheaper card and a Gold.", "Promos")
A("Envoy", 4, (T.ACTION,), _envoy, "Reveal the top 5 cards of your deck. The player to your left chooses one for you to discard. Put the rest into your hand.", "Promos")
A("Sauna", 4, (T.ACTION,), _sauna, "+1 Card, +1 Action. You may play an Avanto from your hand. While this is in play, when you play a Silver, you may trash a card from your hand. (Top half of the Sauna/Avanto pile.)", "Promos")
A("Avanto", 5, (T.ACTION,), _avanto, "+3 Cards. You may play a Sauna from your hand. (Bottom half of the Sauna/Avanto pile.)", "Promos", kingdom=False)
A("Walled Village", 4, (T.ACTION,), _walled_village, "+1 Card, +2 Actions. At the start of Clean-up, if you have this and no more than one other Action card in play, you may put this on top of your deck.", "Promos")
A("Governor", 5, (T.ACTION,), _governor, "+1 Action. Choose one; you get the version in parentheses: Each player gets +1 (+3) Cards; or each player gains a Silver (Gold); or each player may trash a card from their hand and gain a card costing exactly $1 ($2) more.", "Promos")
A("Marchland", 5, (T.VICTORY,), None, "2 VP. When you gain this, +1 Buy, and you may discard any number of cards for +$1 each.", "Promos", vp=2, on_gain=_marchland_gain)
A("Stash", 5, (T.TREASURE,), None, "When you shuffle, you may put this anywhere in your shuffled deck.", "Promos", coins=2)
A("Captain", 6, (T.ACTION, T.DURATION, T.COMMAND), _captain, "Now and at the start of your next turn: Play a non-Duration, non-Command Action card from the Supply costing up to $4, leaving it there.", "Promos")
A("Prince", 8, (T.ACTION,), _prince, "You may set this aside. If you do, set aside an Action card from your hand costing up to $4. At the start of each of your turns, play that Action card, setting it aside again when you discard it from play.", "Promos")
register(CardDef("Summon", 5, frozenset({T.EVENT}), on_play=_summon, text="Gain an Action card costing up to $4. Set it aside. If you did, play it at the start of your next turn.", kingdom=False, expansion="Promos"))
