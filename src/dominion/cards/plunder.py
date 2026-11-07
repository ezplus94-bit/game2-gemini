"""The Plunder expansion (2022): 40 Kingdom cards, 15 Loot cards (2 of each, a shuffled pile outside the Supply), 15 Events and 15 Traits.

  * Many cards are Treasure-Durations. A Treasure that stays in play is simply a Treasure whose effect calls ``ctx.add_duration`` /
    ``ctx.add_wait`` (the same machinery as every Duration card).
  * \"The next time ...\" cards (Abundance, Cage, Cutthroat, Search, Secluded Shrine, Landing Party, Flagship, Taskmaster) are Durations that
    ``ctx.add_wait(kind)``: they stay in play, through their owner's start of turn, until ``engine/plunder.py`` sees the event and calls the card's
    ``wait`` hook (a ``(\"wait\", fn)`` pair in ``CardDef.hooks``; ``fn(ctx, entry, arg)``).
  * Loot: ``GameState.loot`` is the shuffled pile (top first); ``ctx.gain_loot()`` gains the top card.
  * Traits (``CardType.TRAIT``) only have a text here; each one is applied by ``engine/plunder.py`` at the moment it matters.
"""

from __future__ import annotations

from .base import CardDef, CardType
from .registry import get_card, register

SET = "Plunder"
T = CardType
DUR = (T.DURATION,)


def K(name, cost, types, fn, text, **kw):
    return register(CardDef(name, cost, frozenset(types), on_play=fn, text=text, kingdom=kw.pop("kingdom", True), expansion=SET, **kw))


def _names(cards, test=None) -> tuple:
    return tuple(sorted({c for c in cards if test is None or test(c)}))


def _distinct_treasures(ctx) -> int:
    return len({c for c in ctx.in_play if ctx.is_treasure(c)})


def play_from_hand(ctx, prompt: str, test):
    """Generator: the player may play one card of their hand that passes ``test`` (no Action is used). Returns the card or None."""
    options = _names(ctx.hand, test)
    if not options:
        return None
    chosen = yield ctx.choose(prompt, options, 0, 1)
    if not chosen:
        return None
    card = chosen[0]
    ctx.put_in_play(card)
    if ctx.is_action(card):
        yield from ctx.resolve(card)
    else:
        yield from ctx.resolve_treasure(card)
    return card


def play_aside_all(ctx, cards, discard_rest: bool = False):
    """Generator: play the set-aside ``cards`` (Prepare, Hasty, Patient): every Action and Treasure among them, in any order."""
    todo = list(cards)
    while True:
        todo = [c for c in todo if c in ctx.aside_cards()]
        playable = _names(todo, lambda c: ctx.is_action(c) or ctx.is_treasure(c))
        if not playable:
            break
        pick = playable[0] if len(playable) == 1 else (yield ctx.choose(f"{ctx.source}: play the set-aside cards in any order. Play which first?", playable))[0]
        todo.remove(pick)
        ctx.aside_to(pick, "in_play")
        ctx.log(f"{ctx.player_name} plays {pick} from the set-aside cards.", "play")
        if ctx.is_action(pick):
            yield from ctx.resolve(pick)
        else:
            yield from ctx.resolve_treasure(pick)
    for c in todo:
        if c in ctx.aside_cards():
            if discard_rest:
                ctx.aside_to(c, "discard")
            else:                                         # (Hasty / Patient cards that cannot be played go into play and do nothing)
                ctx.aside_to(c, "in_play")


def _plus_start(coins=0, cards=0, buys=0):
    def start(ctx, entry):
        ctx.log(f"{entry.source} gives " + ", ".join(x for x in ((f"+${coins}" if coins else ""), (f"+{cards} Card{'s' if cards != 1 else ''}" if cards else ""), (f"+{buys} Buy" if buys else "")) if x) + ".")
        if cards:
            ctx.draw(cards)
        if buys:
            ctx.add_buys(buys)
        if coins:
            ctx.add_coins(coins)
    return start


# ================================================================== $2
def _abundance_wait(ctx, entry, event):
    ctx.log("Abundance: +1 Buy and +$3.")
    ctx.add_buys(1)
    ctx.add_coins(3)
    ctx.end_wait(entry)


def _abundance(ctx):
    ctx.add_wait("gain_action")


def _cage(ctx):
    hand = ctx.hand
    chosen = ()
    if hand:
        chosen = yield ctx.choose("Cage: set aside up to 4 cards from your hand, face down.", tuple(sorted(hand)), 0, min(4, len(hand)))
    for c in chosen:
        ctx.aside(c)
    ctx.log(f"{ctx.player_name} sets {len(chosen)} card(s) aside on Cage.")
    ctx.add_wait("gain_victory", {"cards": list(chosen)})


def _cage_wait(ctx, entry, event):
    ctx.log("Cage: a Victory card was gained. Trash Cage; the set-aside cards go into the hand at end of turn.")
    ctx.trash_in_play("Cage")
    for c in entry.data["cards"]:
        if c in ctx.aside_cards():
            ctx.aside_to(c, "eot_hand")
    ctx.end_wait(entry)


def _grotto(ctx):
    ctx.add_actions(1)
    hand = ctx.hand
    chosen = ()
    if hand:
        chosen = yield ctx.choose("Grotto: set aside up to 4 cards from your hand, face down. At the start of your next turn you discard them, then draw as many.",
                                  tuple(sorted(hand)), 0, min(4, len(hand)))
    for c in chosen:
        ctx.aside(c)
    ctx.add_duration(_grotto_start, {"cards": list(chosen)})


def _grotto_start(ctx, entry):
    n = 0
    for c in entry.data["cards"]:
        if c in ctx.aside_cards():
            ctx.aside_to(c, "discard")
            n += 1
    ctx.log(f"Grotto: {ctx.player_name} discards {n} card(s) and draws {n}.")
    ctx.draw(n)


def _jewelled_egg_trash(ctx, event):
    ctx.log("Jewelled Egg was trashed: gain a Loot.")
    ctx.gain_loot()


def _search_wait(ctx, entry, event):
    ctx.log("Search: a Supply pile emptied. Trash Search and gain a Loot.")
    ctx.trash_in_play("Search")
    ctx.gain_loot()
    ctx.end_wait(entry)


def _search(ctx):
    ctx.add_coins(2)
    ctx.add_wait("pile_empty")


def _shaman(ctx):
    ctx.add_actions(1)
    ctx.add_coins(1)
    if ctx.hand:
        chosen = yield ctx.choose("Shaman: you may trash a card from your hand.", tuple(sorted(set(ctx.hand))), 0, 1)
        if chosen:
            ctx.trash(chosen[0])


def _crucible(ctx):
    if not ctx.hand:
        return
    (card,) = yield ctx.choose("Crucible: trash a card from your hand for +$1 per $1 it costs.", tuple(sorted(set(ctx.hand))))
    ctx.trash(card)
    ctx.add_coins(ctx.cost_of(card))


# ================================================================== $3
def _secluded_shrine_wait(ctx, entry, event):
    ctx.end_wait(entry)
    hand = ctx.hand
    if hand:
        chosen = yield ctx.choose("Secluded Shrine: you gained a Treasure. You may trash up to 2 cards from your hand.", tuple(sorted(hand)), 0, min(2, len(hand)))
        for c in chosen:
            ctx.trash(c)


def _secluded_shrine(ctx):
    ctx.add_coins(1)
    ctx.add_wait("gain_treasure")


def _siren(ctx):
    targets = yield from ctx.attack()
    for p in targets:
        ctx.gain("Curse", player=p)
    ctx.add_duration(_siren_start)


def _siren_start(ctx, entry):
    n = 8 - len(ctx.hand)
    if n > 0:
        ctx.log("Siren: draw until you have 8 cards in hand.")
        ctx.draw(n)


def _siren_gain(ctx, event):
    actions = _names(ctx.hand, ctx.is_action)
    if actions:
        chosen = yield ctx.choose("Siren: you gained it. Trash an Action card from your hand, or Siren is trashed.", actions, 0, 1)
        if chosen:
            ctx.trash(chosen[0])
            return
    if ctx.gained_card_present(event):
        ctx.log("Siren is trashed.")
        ctx.trash_gained(event)


def _stowaway(ctx):
    ctx.add_duration(_plus_start(cards=2))


def _taskmaster_wait(ctx, entry, event):
    entry.data["armed"] = True
    ctx.log("Taskmaster: it will repeat next turn.")


def _taskmaster(ctx):
    ctx.add_actions(1)
    ctx.add_coins(1)
    ctx.add_duration(_taskmaster_start, {"wait": "gain_exact5", "expires": True, "armed": False})


def _taskmaster_start(ctx, entry):
    ctx.log("Taskmaster repeats: +1 Action, +$1.")
    ctx.add_actions(1)
    ctx.add_coins(1)
    ctx.add_duration(_taskmaster_start, {"wait": "gain_exact5", "expires": True, "armed": False})


# ================================================================== $4
def _buried_treasure(ctx):
    ctx.add_duration(_plus_start(coins=3, buys=1))


def _buried_treasure_gain(ctx, event):
    if ctx.gained_card_present(event) and event.zone in ("discard", "hand"):
        ctx.log("Buried Treasure: it is played when gained.")
        yield from ctx.play_treasure("Buried Treasure", event.zone)


def _cabin_boy(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.add_duration(_cabin_boy_start)


def _cabin_boy_start(ctx, entry):
    coins = "+$2"
    trash = "Trash this to gain a Duration card"
    modes = [coins]
    if "Cabin Boy" in ctx.in_play and ctx.supply_cards_of_type(T.DURATION):
        modes.append(trash)
    (mode,) = yield ctx.choose("Cabin Boy: choose one.", tuple(modes))
    if mode == coins:
        ctx.add_coins(2)
    elif ctx.trash_in_play("Cabin Boy"):
        (card,) = yield ctx.choose("Cabin Boy: gain a Duration card.", ctx.supply_cards_of_type(T.DURATION))
        ctx.gain(card)


def _enlarge_step(ctx):
    if not ctx.hand:
        return
    (card,) = yield ctx.choose("Enlarge: trash a card from your hand. Then gain a card costing up to $2 more.", tuple(sorted(set(ctx.hand))))
    ctx.trash(card)
    options = ctx.gainable(ctx.cost_of(card) + 2)
    if options:
        (new,) = yield ctx.choose("Enlarge: gain a card costing up to $2 more.", options)
        ctx.gain(new)


def _enlarge(ctx):
    yield from _enlarge_step(ctx)
    ctx.add_duration(_enlarge_start)


def _enlarge_start(ctx, entry):
    yield from _enlarge_step(ctx)


def _flagship(ctx):
    ctx.add_coins(2)
    ctx.add_wait("play_action")


def _fortune_hunter(ctx):
    ctx.add_coins(2)
    cards = ctx.take_to_set_aside(3)
    if not cards:
        return
    options = _names(cards, ctx.is_treasure)
    played = None
    if options:
        chosen = yield ctx.choose("Fortune Hunter: you may play a Treasure from the top 3 cards of your deck.", options, 0, 1)
        if chosen:
            played = chosen[0]
            ctx.put_in_play(played, "set_aside")
            yield from ctx.resolve_treasure(played)
    rest = list(cards)
    if played is not None:
        rest.remove(played)
    yield from ctx.put_back_in_order(rest, "Fortune Hunter: put the next card back on your deck (top card first).")


def _gondola(ctx):
    now, later = "+$2 now", "+$2 at the start of your next turn"
    (mode,) = yield ctx.choose("Gondola: when do you want the +$2?", (now, later))
    if mode == now:
        ctx.add_coins(2)
    else:
        ctx.add_duration(_plus_start(coins=2))


def _gondola_gain(ctx, event):
    yield from play_from_hand(ctx, "Gondola: you may play an Action card from your hand.", ctx.is_action)


def _harbor_village(ctx):
    ctx.draw(1)
    ctx.add_actions(2)
    ctx.bump_count("hv_armed")


def _landing_party(ctx):
    ctx.draw(2)
    ctx.add_actions(2)
    ctx.add_wait("first_play_treasure")


def _landing_party_wait(ctx, entry, arg):
    ctx.end_wait(entry)
    if "Landing Party" in ctx.in_play:
        ctx.log("Landing Party: your first card played was a Treasure, so Landing Party goes onto your deck.")
        ctx.put_in_play_on_deck("Landing Party")


def _mapmaker(ctx):
    cards = ctx.take_to_set_aside(4)
    if not cards:
        return
    keep = min(2, len(cards))
    chosen = yield ctx.choose("Mapmaker: put 2 of these cards into your hand; the rest are discarded.", tuple(cards), keep, keep)
    rest = list(cards)
    for c in chosen:
        rest.remove(c)
        ctx.set_aside_to_hand(c)
    for c in rest:
        ctx.discard_set_aside(c)


def _maroon(ctx):
    if not ctx.hand:
        return
    (card,) = yield ctx.choose("Maroon: trash a card from your hand. +2 Cards per type it has.", tuple(sorted(set(ctx.hand))))
    n = len(ctx.card_types(card))
    ctx.trash(card)
    ctx.log(f"{card} has {n} type(s): +{2 * n} Cards.")
    ctx.draw(2 * n)


def _swamp_shacks(ctx):
    ctx.add_actions(2)
    n = len(ctx.in_play) // 3
    ctx.log(f"{ctx.player_name} has {len(ctx.in_play)} cards in play: +{n} Card(s).")
    ctx.draw(n)


def _rope(ctx):
    ctx.add_buys(1)
    ctx.add_duration(_rope_start)


def _rope_start(ctx, entry):
    ctx.draw(1)
    if ctx.hand:
        chosen = yield ctx.choose("Rope: you may trash a card from your hand.", tuple(sorted(set(ctx.hand))), 0, 1)
        if chosen:
            ctx.trash(chosen[0])


def _tools(ctx):
    options = tuple(c for c in ctx.copies_available(ctx.all_in_play()) if not get_card(c).is_type(T.LOOT))
    if not options:
        return
    (card,) = yield ctx.choose("Tools: gain a copy of a card anyone has in play.", options)
    ctx.gain_copy(card)


def _figurine(ctx):
    ctx.draw(2)
    actions = _names(ctx.hand, ctx.is_action)
    if actions:
        chosen = yield ctx.choose("Figurine: you may discard an Action card for +1 Buy and +$1.", actions, 0, 1)
        if chosen:
            ctx.discard(chosen[0])
            ctx.add_buys(1)
            ctx.add_coins(1)


# ================================================================== $5
def _crew(ctx):
    ctx.draw(3)
    ctx.add_duration(_crew_start)


def _crew_start(ctx, entry):
    if "Crew" in ctx.in_play:
        ctx.log("Crew goes onto your deck.")
        ctx.put_in_play_on_deck("Crew")


def _cutthroat(ctx):
    targets = yield from ctx.attack()
    for p in targets:
        excess = len(ctx.hand_of(p)) - 3
        if excess > 0:
            chosen = yield ctx.choose(f"{ctx.player_name}'s Cutthroat: discard {excess} card(s) to get down to 3.", ctx.hand_of(p), excess, excess, player=p)
            for c in chosen:
                ctx.discard(c, player=p)
    ctx.add_wait("gain_treasure5")


def _cutthroat_wait(ctx, entry, event):
    ctx.log("Cutthroat: a Treasure costing $5 or more was gained. Its owner gains a Loot.")
    ctx.gain_loot()
    ctx.end_wait(entry)


def _first_mate(ctx):
    names = _names(ctx.hand, ctx.is_action)
    if names:
        chosen = yield ctx.choose("First Mate: you may play any number of Action cards with the same name from your hand. Which card?", names, 0, 1)
        if chosen:
            name = chosen[0]
            copies = ctx.hand.count(name)
            options = tuple(f"Play {k}" for k in range(1, copies + 1))
            (mode,) = yield ctx.choose(f"First Mate: how many {name} do you play?", options)
            for _ in range(int(mode.split()[1])):
                if name not in ctx.hand:
                    break
                ctx.put_in_play(name)
                yield from ctx.resolve(name)
    n = 6 - len(ctx.hand)
    if n > 0:
        ctx.draw(n)


def _frigate(ctx):
    ctx.add_coins(3)
    targets = yield from ctx.attack()
    ctx.add_duration(None, {"frigate": list(targets)})


def _kings_cache(ctx):
    options = _names(ctx.hand, ctx.is_treasure)
    if not options:
        return
    chosen = yield ctx.choose("King's Cache: you may play a Treasure from your hand 3 times.", options, 0, 1)
    if not chosen:
        return
    card = chosen[0]
    before = len(ctx.duration_entries(card))
    ctx.put_in_play(card)
    yield from ctx.resolve_treasure(card)
    for _ in range(2):
        yield from ctx.play_treasure(card, "in_play")
    if len(ctx.duration_entries(card)) > before:
        ctx.add_duration(None)                              # King's Cache stays in play as long as that Duration does


def _longship(ctx):
    ctx.add_actions(2)
    ctx.add_duration(_plus_start(cards=2))


def _mining_road(ctx):
    ctx.add_actions(1)
    ctx.add_buys(1)
    ctx.add_coins(2)
    ctx.bump_count("mining_road")


def _pendant(ctx):
    n = _distinct_treasures(ctx)
    ctx.log(f"Pendant: {n} differently named Treasure(s) in play, +${n}.")
    ctx.add_coins(n)


def _pickaxe(ctx):
    if not ctx.hand:
        return
    (card,) = yield ctx.choose("Pickaxe: trash a card from your hand. If it costs $3 or more, gain a Loot to your hand.", tuple(sorted(set(ctx.hand))))
    cost = ctx.cost_of(card)
    ctx.trash(card)
    if cost >= 3:
        ctx.gain_loot("hand")


def _pilgrim(ctx):
    ctx.draw(4)
    if ctx.hand:
        (card,) = yield ctx.choose("Pilgrim: put a card from your hand onto your deck.", tuple(sorted(set(ctx.hand))))
        ctx.put_hand_on_deck(card)


def _quartermaster(ctx):
    ctx.add_wait("never", {"cards": []}, handler=_quartermaster_start)


def _quartermaster_start(ctx, entry):
    gain = "Gain a card costing up to $4, setting it aside on this"
    take = "Put a card from this into your hand"
    modes = []
    if ctx.gainable(4):
        modes.append(gain)
    if entry.data["cards"]:
        modes.append(take)
    if not modes:
        return
    (mode,) = yield ctx.choose("Quartermaster: choose one.", tuple(modes))
    if mode == gain:
        (card,) = yield ctx.choose("Quartermaster: gain a card costing up to $4 and set it aside.", ctx.gainable(4))
        if ctx.gain_aside(card):
            entry.data["cards"].append(card)
    else:
        (card,) = yield ctx.choose("Quartermaster: put a card from this into your hand.", tuple(sorted(set(entry.data["cards"]))))
        entry.data["cards"].remove(card)
        ctx.aside_to(card, "hand")


def _sack_of_loot(ctx):
    ctx.add_buys(1)
    ctx.gain_loot()


def _silver_mine(ctx):
    options = ctx.gainable(ctx.cost_of("Silver Mine") - 1, T.TREASURE)
    if not options:
        return
    (card,) = yield ctx.choose("Silver Mine: gain a Treasure costing less than this to your hand.", options)
    ctx.gain(card, destination="hand")


def _trickster(ctx):
    targets = yield from ctx.attack()
    for p in targets:
        ctx.gain("Curse", player=p)
    ctx.bump_count("trickster")


def _wealthy_village_gain(ctx, event):
    if _distinct_treasures(ctx) >= 3:
        ctx.log("Wealthy Village: 3 differently named Treasures in play, gain a Loot.")
        ctx.gain_loot()


def _wealthy_village(ctx):
    ctx.draw(1)
    ctx.add_actions(2)


# ------------------------------------------------------------------ registration: Kingdom cards
TREASURE, ACTION = T.TREASURE, T.ACTION
K("Abundance", 4, (TREASURE, T.DURATION), _abundance, "The next time you gain an Action card: +1 Buy and +$3.", hooks=(("wait", _abundance_wait),))
K("Buried Treasure", 5, (TREASURE, T.DURATION), _buried_treasure, "At the start of your next turn, +1 Buy and +$3. When you gain this, play it.", on_gain=_buried_treasure_gain)
K("Cabin Boy", 4, (ACTION, T.DURATION), _cabin_boy, "+1 Card, +1 Action. At the start of your next turn, choose one: +$2; or trash this to gain a Duration card.")
K("Cage", 2, (TREASURE, T.DURATION), _cage, "Set aside up to 4 cards from your hand face down (on this). The next time you gain a Victory card, trash this, and put the set aside cards into your hand at end of turn.", hooks=(("wait", _cage_wait),))
K("Crew", 5, (ACTION, T.DURATION), _crew, "+3 Cards. At the start of your next turn, put this onto your deck.")
K("Crucible", 4, (TREASURE,), _crucible, "Trash a card from your hand. +$1 per $1 it costs. (Worth a variable number of $.)")
K("Cutthroat", 5, (ACTION, T.DURATION, T.ATTACK), _cutthroat, "Each other player discards down to 3 cards in hand. The next time anyone gains a Treasure costing $5 or more, gain a Loot.", hooks=(("wait", _cutthroat_wait),))
K("Enlarge", 5, (ACTION, T.DURATION), _enlarge, "Now and at the start of your next turn: Trash a card from your hand, and gain one costing up to $2 more.")
K("Figurine", 5, (TREASURE,), _figurine, "+2 Cards. You may discard an Action card for +1 Buy and +$1.", coins=2)
K("First Mate", 5, (ACTION,), _first_mate, "Play any number of Action cards with the same name from your hand, then draw until you have 6 cards in hand.")
K("Flagship", 4, (ACTION, T.DURATION, T.COMMAND), _flagship, "+$2. The next time you play a non-Command Action card, replay it.")
K("Fortune Hunter", 4, (ACTION,), _fortune_hunter, "+$2. Look at the top 3 cards of your deck. You may play a Treasure from them. Put the rest back in any order.")
K("Frigate", 5, (ACTION, T.DURATION, T.ATTACK), _frigate, "+$3. Until the start of your next turn, each time another player plays an Action card, they discard down to 4 cards in hand afterwards.")
K("Gondola", 4, (TREASURE, T.DURATION), _gondola, "Either now or at the start of your next turn: +$2. When you gain this, you may play an Action card from your hand.", on_gain=_gondola_gain)
K("Grotto", 2, (ACTION, T.DURATION), _grotto, "+1 Action. Set aside up to 4 cards from your hand face down (on this). At the start of your next turn, discard them, then draw as many.")
K("Harbor Village", 4, (ACTION,), _harbor_village, "+1 Card, +2 Actions. After the next Action you play this turn, if it gave you +$, +$1.")
K("Jewelled Egg", 2, (TREASURE,), lambda ctx: ctx.add_buys(1), "+1 Buy. When you trash this, gain a Loot.", coins=1, on_trash=_jewelled_egg_trash)
K("King's Cache", 7, (TREASURE,), _kings_cache, "You may play a Treasure from your hand 3 times.")
K("Landing Party", 4, (ACTION, T.DURATION), _landing_party, "+2 Cards, +2 Actions. The next time the first card you play on a turn is a Treasure, put this onto your deck afterwards.", hooks=(("wait", _landing_party_wait),))
K("Longship", 5, (ACTION, T.DURATION), _longship, "+2 Actions. At the start of your next turn, +2 Cards.")
K("Mapmaker", 4, (ACTION, T.REACTION), _mapmaker, "Look at the top 4 cards of your deck. Put 2 into your hand and discard the rest. When any player gains a Victory card, you may play this from your hand.")
K("Maroon", 4, (ACTION,), _maroon, "Trash a card from your hand. +2 Cards per type it has (Action, Attack, etc.).")
K("Mining Road", 5, (ACTION,), _mining_road, "+1 Action, +1 Buy, +$2. Once this turn, when you gain a Treasure, you may play it.")
K("Pendant", 5, (TREASURE,), _pendant, "+$1 per differently named Treasure you have in play.", coins=2)
K("Pickaxe", 5, (TREASURE,), _pickaxe, "Trash a card from your hand. If it costs $3 or more, gain a Loot to your hand.", coins=1)
K("Pilgrim", 5, (ACTION,), _pilgrim, "+4 Cards. Put a card from your hand onto your deck.")
K("Quartermaster", 5, (ACTION, T.DURATION), _quartermaster, "At the start of each of your turns for the rest of the game, choose one: Gain a card costing up to $4, setting it aside on this; or put a card from this into your hand.")
K("Rope", 4, (TREASURE, T.DURATION), _rope, "+1 Buy. At the start of your next turn, +1 Card and you may trash a card from your hand.", coins=1)
K("Sack of Loot", 6, (TREASURE,), _sack_of_loot, "+1 Buy. Gain a Loot.", coins=1)
K("Search", 2, (ACTION, T.DURATION), _search, "+$2. The next time a Supply pile empties, trash this and gain a Loot.", hooks=(("wait", _search_wait),))
K("Secluded Shrine", 3, (ACTION, T.DURATION), _secluded_shrine, "+$1. The next time you gain a Treasure, trash up to 2 cards from your hand.", hooks=(("wait", _secluded_shrine_wait),))
K("Shaman", 2, (ACTION,), _shaman, "+1 Action, +$1. You may trash a card from your hand. In games using this, at the start of your turn, gain a card from the trash costing up to $6.")
K("Silver Mine", 5, (TREASURE,), _silver_mine, "Gain a Treasure costing less than this to your hand.")
K("Siren", 3, (ACTION, T.DURATION, T.ATTACK), _siren, "Each other player gains a Curse. At the start of your next turn, draw until you have 8 cards in hand. When you gain this, trash it unless you trash an Action from your hand.", on_gain=_siren_gain)
K("Stowaway", 3, (ACTION, T.DURATION, T.REACTION), _stowaway, "At the start of your next turn, +2 Cards. When anyone gains a Duration card, you may play this from your hand.")
K("Swamp Shacks", 4, (ACTION,), _swamp_shacks, "+2 Actions. +1 Card per 3 cards you have in play (round down).")
K("Taskmaster", 3, (ACTION, T.DURATION), _taskmaster, "+1 Action, +$1, and if you gain a card costing exactly $5 this turn, then at the start of your next turn, repeat this ability.", hooks=(("wait", _taskmaster_wait),))
K("Tools", 4, (TREASURE,), _tools, "Gain a copy of a card anyone has in play.")
K("Trickster", 5, (ACTION, T.ATTACK), _trickster, "Each other player gains a Curse. Once this turn, when you discard a Treasure from play, you may set it aside. Put it in your hand at end of turn.")
K("Wealthy Village", 5, (ACTION,), _wealthy_village, "+1 Card, +2 Actions. When you gain this, if you have at least 3 differently named Treasures in play, gain a Loot.", on_gain=_wealthy_village_gain)


# ================================================================== Loot (not in the Supply)
def L(name, types, fn, text, coins=0, **kw):
    return register(CardDef(name, 7, frozenset({TREASURE, T.LOOT, *types}), coins=coins, on_play=fn, text=text, kingdom=False, expansion=SET, **kw))


def _amphora(ctx):
    now, later = "+1 Buy and +$3 now", "+1 Buy and +$3 at the start of your next turn"
    (mode,) = yield ctx.choose("Amphora: when do you want +1 Buy and +$3?", (now, later))
    if mode == now:
        ctx.add_buys(1)
        ctx.add_coins(3)
    else:
        ctx.add_duration(_plus_start(coins=3, buys=1))


def _doubloons_gain(ctx, event):
    ctx.gain("Gold")


def _chalice_start(ctx, entry):
    ctx.log("Endless Chalice: +1 Buy.")
    ctx.add_buys(1)


def _endless_chalice(ctx):
    ctx.add_buys(1)
    ctx.add_wait("never", handler=_chalice_start)


def _figurehead(ctx):
    ctx.add_duration(_plus_start(cards=2))


def _hammer(ctx):
    options = ctx.gainable(4)
    if options:
        (card,) = yield ctx.choose("Hammer: gain a card costing up to $4.", options)
        ctx.gain(card)


def _insignia(ctx):
    ctx.bump_count("insignia")


def _jewels_start(ctx, entry):
    if "Jewels" in ctx.in_play:
        ctx.log("Jewels goes to the bottom of your deck.")
        ctx.deck_to_bottom("Jewels", "in_play")


def _jewels(ctx):
    ctx.add_buys(1)
    ctx.add_duration(_jewels_start)


def _orb(ctx):
    play = "Play an Action or Treasure from your discard pile"
    bonus = "+1 Buy and +$3"
    playable = _names(ctx.discard_pile, lambda c: ctx.is_action(c) or ctx.is_treasure(c))
    modes = ((play,) if playable else ()) + (bonus,)
    (mode,) = yield ctx.choose("Orb: you look through your discard pile. Choose one.", modes)
    if mode == bonus:
        ctx.add_buys(1)
        ctx.add_coins(3)
        return
    (card,) = yield ctx.choose("Orb: play an Action or Treasure from your discard pile.", playable)
    ctx.put_in_play(card, "discard")
    if ctx.is_action(card):
        yield from ctx.resolve(card)
    else:
        yield from ctx.resolve_treasure(card)


def _prize_goat(ctx):
    ctx.add_buys(1)
    if ctx.hand:
        chosen = yield ctx.choose("Prize Goat: you may trash a card from your hand.", tuple(sorted(set(ctx.hand))), 0, 1)
        if chosen:
            ctx.trash(chosen[0])


def _puzzle_box(ctx):
    ctx.add_buys(1)
    if ctx.hand:
        chosen = yield ctx.choose("Puzzle Box: you may set aside a card from your hand face down. It goes back into your hand at end of turn.", tuple(sorted(set(ctx.hand))), 0, 1)
        if chosen:
            ctx.eot_hand(chosen[0])


def _sextant(ctx):
    ctx.add_buys(1)
    cards = ctx.take_to_set_aside(5)
    if not cards:
        return
    chosen = yield ctx.choose("Sextant: discard any number of these cards. The rest go back on your deck.", tuple(cards), 0, len(cards))
    rest = list(cards)
    for c in chosen:
        rest.remove(c)
        ctx.discard_set_aside(c)
    yield from ctx.put_back_in_order(rest, "Sextant: put the next card back on your deck (top card first).")


def _shield(ctx):
    ctx.add_buys(1)


def _spell_scroll(ctx):
    cost = ctx.cost_of("Spell Scroll")
    if not ctx.trash_in_play("Spell Scroll"):
        return
    options = ctx.gainable(cost - 1)
    if not options:
        return
    (card,) = yield ctx.choose("Spell Scroll: gain a cheaper card. If it is an Action or Treasure you may play it.", options)
    ctx.gain(card)
    if (ctx.is_action(card) or ctx.is_treasure(card)) and card in ctx.discard_pile:
        chosen = yield ctx.choose(f"Spell Scroll: you may play {card}.", (f"Play {card}",), 0, 1)
        if chosen and card in ctx.discard_pile:
            ctx.put_in_play(card, "discard")
            if ctx.is_action(card):
                yield from ctx.resolve(card)
            else:
                yield from ctx.resolve_treasure(card)


def _staff(ctx):
    ctx.add_buys(1)
    yield from play_from_hand(ctx, "Staff: you may play an Action card from your hand.", ctx.is_action)


def _sword(ctx):
    ctx.add_buys(1)
    targets = yield from ctx.attack()
    for p in targets:
        excess = len(ctx.hand_of(p)) - 4
        if excess > 0:
            chosen = yield ctx.choose(f"{ctx.player_name}'s Sword: discard {excess} card(s) to get down to 4.", ctx.hand_of(p), excess, excess, player=p)
            for c in chosen:
                ctx.discard(c, player=p)


L("Amphora", (T.DURATION,), _amphora, "Either now or at the start of your next turn: +1 Buy and +$3.")
L("Doubloons", (), None, "$3. When you gain this, gain a Gold.", coins=3, on_gain=_doubloons_gain)
L("Endless Chalice", (T.DURATION,), _endless_chalice, "Now and at the start of each of your turns for the rest of the game: +1 Buy.", coins=1)
L("Figurehead", (T.DURATION,), _figurehead, "At the start of your next turn, +2 Cards.", coins=3)
L("Hammer", (), _hammer, "Gain a card costing up to $4.", coins=3)
L("Insignia", (), _insignia, "This turn, when you gain a card, you may put it onto your deck.", coins=3)
L("Jewels", (T.DURATION,), _jewels, "+1 Buy. At the start of your next turn, put this on the bottom of your deck.", coins=3)
L("Orb", (), _orb, "Look through your discard pile. Choose one: Play an Action or Treasure from it; or +1 Buy and +$3.")
L("Prize Goat", (), _prize_goat, "+1 Buy. You may trash a card from your hand.", coins=3)
L("Puzzle Box", (), _puzzle_box, "+1 Buy. You may set aside a card from your hand face down. Put it into your hand at end of turn.", coins=3)
L("Sextant", (), _sextant, "+1 Buy. Look at the top 5 cards of your deck. Discard any number. Put the rest back in any order.", coins=3)
L("Shield", (T.REACTION,), _shield, "+1 Buy. When another player plays an Attack, you may first reveal this from your hand to be unaffected.", coins=3, blocks_attack=True)
register(CardDef("Spell Scroll", 7, frozenset({T.ACTION, TREASURE, T.LOOT}), on_play=_spell_scroll, text="Trash this to gain a cheaper card. If it's an Action or Treasure, you may play it.",
                 kingdom=False, expansion=SET))
L("Staff", (), _staff, "+1 Buy. You may play an Action from your hand.", coins=3)
L("Sword", (T.ATTACK,), _sword, "+1 Buy. Each other player discards down to 4 cards in hand.", coins=3)


# ================================================================== Events
def _event(name: str, cost: int, text: str, fn, once: bool = False):
    return register(CardDef(name, cost, frozenset({T.EVENT}), on_play=fn, text=text, kingdom=False, expansion=SET, once_per_turn=once))


def _avoid(ctx):
    ctx.add_buys(1)
    ctx.bump_count("avoid")


def _bury(ctx):
    ctx.add_buys(1)
    if ctx.discard_pile:
        (card,) = yield ctx.choose("Bury: put any card from your discard pile on the bottom of your deck.", tuple(sorted(set(ctx.discard_pile))))
        ctx.deck_to_bottom(card)
        ctx.log(f"{ctx.player_name} puts {card} on the bottom of their deck.")


def _deliver(ctx):
    ctx.add_buys(1)
    ctx.set_count("deliver", 1)


def _foray(ctx):
    n = min(3, len(ctx.hand))
    if n == 0:
        return
    chosen = yield ctx.choose("Foray: discard 3 cards, revealing them.", tuple(sorted(ctx.hand)), n, n)
    ctx.log(f"{ctx.player_name} reveals {', '.join(chosen)}.", "reveal")
    for c in chosen:
        ctx.discard(c)
    if n == 3 and len(set(chosen)) == 3:
        ctx.gain_loot()


def _invasion(ctx):
    attacks = _names(ctx.hand, lambda c: get_card(c).is_type(T.ATTACK))
    if attacks:
        chosen = yield ctx.choose("Invasion: you may play an Attack from your hand.", attacks, 0, 1)
        if chosen:
            ctx.put_in_play(chosen[0])
            yield from ctx.resolve(chosen[0])
    ctx.gain("Duchy")
    options = ctx.gainable_actions()
    if options:
        (card,) = yield ctx.choose("Invasion: gain an Action card onto your deck.", options)
        ctx.gain(card, destination="deck")
    name = ctx.gain_loot()
    if name and name in ctx.discard_pile:
        ctx.log(f"Invasion: {ctx.player_name} plays the Loot.")
        ctx.put_in_play(name, "discard")
        if ctx.is_action(name):
            yield from ctx.resolve(name)
        else:
            yield from ctx.resolve_treasure(name)


def _journey(ctx):
    if ctx.previous_turn_was_mine():
        ctx.log("Journey: the previous turn was yours, so nothing happens.")
        return
    ctx.queue_journey_turn()


def _launch(ctx):
    ctx.set_phase_to_action()
    ctx.draw(1)
    ctx.add_actions(1)
    ctx.add_buys(1)


def _looting(ctx):
    ctx.gain_loot()


def _maelstrom(ctx):
    n = min(3, len(ctx.hand))
    if n:
        chosen = yield ctx.choose("Maelstrom: trash 3 cards from your hand.", tuple(sorted(ctx.hand)), n, n)
        for c in chosen:
            ctx.trash(c)
    for p in ctx.other_players():
        hand = ctx.hand_of(p)
        if len(hand) >= 5:
            (card,) = yield ctx.choose(f"{ctx.player_name}'s Maelstrom: trash a card from your hand.", tuple(sorted(set(hand))), player=p)
            ctx.trash(card, player=p)


def _mirror(ctx):
    ctx.add_buys(1)
    ctx.bump_count("mirror")


def _peril(ctx):
    actions = _names(ctx.hand, ctx.is_action)
    if actions:
        chosen = yield ctx.choose("Peril: you may trash an Action card from your hand to gain a Loot.", actions, 0, 1)
        if chosen:
            ctx.trash(chosen[0])
            ctx.gain_loot()


def _prepare(ctx):
    cards = list(ctx.hand)
    for c in cards:
        ctx.aside(c)
    ctx.log(f"{ctx.player_name} sets aside their hand: {', '.join(sorted(cards)) or 'nothing'}.", "reveal")
    if cards:
        ctx.add_delayed_play("Prepare", _prepare_start, cards)


def _prepare_start(ctx, entry):
    yield from play_aside_all(ctx, entry.data, discard_rest=True)


def _prosper(ctx):
    ctx.gain_loot()
    taken = []
    while True:
        options = tuple(c for c in ctx.supply_cards_of_type(T.TREASURE) if c not in taken)
        if not options:
            return
        chosen = yield ctx.choose("Prosper: you may gain a Treasure with a different name than the others.", options, 0, 1)
        if not chosen:
            return
        taken.append(chosen[0])
        ctx.gain(chosen[0])


def _rush(ctx):
    ctx.add_buys(1)
    ctx.set_count("rush", 1)


def _scrounge(ctx):
    trash, estate = "Trash a card from your hand", "Gain an Estate from the trash"
    modes = []
    if ctx.hand:
        modes.append(trash)
    if "Estate" in ctx.trash_pile():
        modes.append(estate)
    if not modes:
        return
    (mode,) = yield ctx.choose("Scrounge: choose one.", tuple(modes))
    if mode == trash:
        (card,) = yield ctx.choose("Scrounge: trash a card from your hand.", tuple(sorted(set(ctx.hand))))
        ctx.trash(card)
    elif ctx.gain_from_trash("Estate"):
        options = ctx.gainable(5)
        if options:
            (card,) = yield ctx.choose("Scrounge: gain a card costing up to $5.", options)
            ctx.gain(card)


_event("Bury", 1, "+1 Buy. Put any card from your discard pile on the bottom of your deck.", _bury)
_event("Avoid", 2, "+1 Buy. The next time you shuffle this turn, pick up to 3 of those cards to put into your discard pile.", _avoid)
_event("Deliver", 2, "+1 Buy. This turn, each time you gain a card, set it aside, and put it into your hand at end of turn.", _deliver)
_event("Peril", 2, "You may trash an Action card from your hand to gain a Loot.", _peril)
_event("Rush", 2, "+1 Buy. The next time you gain an Action card this turn, play it.", _rush)
_event("Foray", 3, "Discard 3 cards, revealing them. If they have 3 different names, gain a Loot.", _foray)
_event("Journey", 3, "Once per turn: If the previous turn wasn't yours, you don't discard cards from play in Clean-up this turn, and take an extra turn after this one.", _journey, once=True)
_event("Launch", 3, "Once per turn: Return to your Action phase. +1 Card, +1 Action, and +1 Buy.", _launch, once=True)
_event("Maelstrom", 3, "Trash 3 cards from your hand. Each other player with 5 or more cards in hand trashes one of them.", _maelstrom)
_event("Mirror", 3, "+1 Buy. The next time you gain an Action card this turn, gain a copy of it.", _mirror)
_event("Prepare", 3, "Set aside your hand face up. At the start of your next turn, play those Actions and Treasures in any order, then discard the rest.", _prepare)
_event("Scrounge", 3, "Choose one: Trash a card from your hand; or gain an Estate from the trash, and if you did, gain a card costing up to $5.", _scrounge)
_event("Looting", 6, "Gain a Loot.", _looting)
_event("Invasion", 10, "You may play an Attack from your hand. Gain a Duchy. Gain an Action onto your deck. Gain a Loot; play it.", _invasion)
_event("Prosper", 10, "Gain a Loot, plus any number of differently named Treasures.", _prosper)


# ================================================================== Traits
def _trait(name: str, text: str):
    return register(CardDef(name, 0, frozenset({T.TRAIT}), text=text, kingdom=False, expansion=SET))


_trait("Cheap", "Cheap cards cost $1 less.")
_trait("Cursed", "When you gain a Cursed card, gain a Loot and a Curse.")
_trait("Fated", "When shuffling, you may look through the cards and reveal Fated cards to put them on the top or bottom.")
_trait("Fawning", "When you gain a Province, gain a Fawning card.")
_trait("Friendly", "At the start of your Clean-up phase, you may discard a Friendly card to gain a Friendly card.")
_trait("Hasty", "When you gain a Hasty card, set it aside, and play it at the start of your next turn.")
_trait("Inherited", "Setup: You start the game with an Inherited card in place of a starting card you choose.")
_trait("Inspiring", "After playing an Inspiring card on your turn, you may play an Action from your hand that you don't have a copy of in play.")
_trait("Nearby", "When you gain a Nearby card, +1 Buy.")
_trait("Patient", "At the start of your Clean-up phase, you may set aside Patient cards from your hand to play them at the start of your next turn.")
_trait("Pious", "When you gain a Pious card, you may trash a card from your hand.")
_trait("Reckless", "Follow the instructions of played Reckless cards twice. When discarding one from play, return it to its pile.")
_trait("Rich", "When you gain a Rich card, gain a Silver.")
_trait("Shy", "At the start of your turn, you may discard one Shy card for +2 Cards.")
_trait("Tireless", "When you discard a Tireless card from play, set it aside, and put it onto your deck at end of turn.")
