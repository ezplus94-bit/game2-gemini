"""Renaissance rules that live in the engine: Projects and Artifacts that act at fixed moments of the turn.

The cards (and each Project's and Artifact's text) are in ``cards/renaissance.py``. A Project is a ``CardDef`` of type PROJECT
that sits in ``GameState.events`` (it is bought with ``BuyEvent``); owning it is ``name in PlayerState.projects``.
An Artifact is a plain name in ``GameState.artifacts`` mapped to the player who holds it (or None).
"""

from __future__ import annotations

from ..cards import CardType, get_card
from .effects import EffectContext
from .state import GameState


def setup(state: GameState, used: list) -> None:
    """The Artifacts that the Kingdom cards use are put next to the Supply."""
    for card, artifacts in (("Border Guard", ("Horn", "Lantern")), ("Flag Bearer", ("Flag",)),
                            ("Swashbuckler", ("Treasure Chest",)), ("Treasurer", ("Key",))):
        if card in used:
            state.artifacts.update({a: None for a in artifacts})


def start_of_buy_phase(state: GameState, player: int) -> None:
    """Treasure Chest: gain a Gold at the start of the Buy phase (not optional)."""
    if state.artifacts.get("Treasure Chest") == player:
        ctx = EffectContext(state, player, "Treasure Chest")
        ctx.log(f"{state.players[player].name}'s Treasure Chest gains a Gold.", "gain")
        ctx.gain("Gold")


def start_of_turn_steps(state: GameState, player: int):
    """Generator: Barracks, Fair, Key and the Projects that act at the start of the turn. They happen in a fixed order: +Actions, +Buys
    and $ first, then Silos, Crop Rotation, Sinister Plot and City Gate (they draw), then Piazza, and Cathedral last."""
    me = state.players[player]
    projects = me.projects
    if "Barracks" in projects:
        state.actions += 1
        state.log.append(f"{me.name}'s Barracks gives +1 Action.", "info", 1)
    if "Fair" in projects:
        state.buys += 1
        state.log.append(f"{me.name}'s Fair gives +1 Buy.", "info", 1)
    if state.artifacts.get("Key") == player:
        state.coins += 1
        state.log.append(f"{me.name}'s Key gives +$1.", "info", 1)
    if "Silos" in projects:
        ctx = EffectContext(state, player, "Silos")
        coppers = tuple(c for c in me.hand if c == "Copper")
        if coppers:
            chosen = yield ctx.choose("Silos: discard any number of Coppers, revealing them, and draw that many cards.", coppers, 0, len(coppers))
            for card in chosen:
                ctx.discard(card)
            if chosen:
                ctx.log(f"{me.name} reveals {' and '.join(chosen)}.")
                ctx.draw(len(chosen))
    if "Crop Rotation" in projects:
        ctx = EffectContext(state, player, "Crop Rotation")
        victories = tuple(sorted({c for c in me.hand if get_card(c).is_type(CardType.VICTORY)}))
        if victories:
            chosen = yield ctx.choose("Crop Rotation: you may discard a Victory card for +2 Cards.", victories, 0, 1)
            if chosen:
                ctx.discard(chosen[0])
                ctx.draw(2)
    if "Sinister Plot" in projects:
        ctx = EffectContext(state, player, "Sinister Plot")
        add = "Add a token"
        options = (add, f"Remove your {me.plot_tokens} token{'s' if me.plot_tokens != 1 else ''} for +{me.plot_tokens} Card{'s' if me.plot_tokens != 1 else ''}") if me.plot_tokens else (add,)
        (mode,) = yield ctx.choose("Sinister Plot: add a token here, or remove your tokens for +1 Card each.", options)
        if mode == add:
            me.plot_tokens += 1
            ctx.log(f"{me.name} adds a token to Sinister Plot ({me.plot_tokens} there).")
        else:
            n, me.plot_tokens = me.plot_tokens, 0
            ctx.draw(n)
    if "City Gate" in projects:
        ctx = EffectContext(state, player, "City Gate")
        ctx.draw(1)
        if me.hand:
            (card,) = yield ctx.choose("City Gate: put a card from your hand onto your deck.", tuple(sorted(set(me.hand))))
            ctx.put_hand_on_deck(card)
    if "Piazza" in projects:
        ctx = EffectContext(state, player, "Piazza")
        cards = ctx.take_to_set_aside(1, reveal=True)
        if cards:
            if get_card(cards[0]).is_type(CardType.ACTION):
                ctx.put_in_play(cards[0], "set_aside")
                yield from ctx.resolve(cards[0])
            else:
                ctx.put_set_aside_on_deck(cards[0])
    if "Cathedral" in projects and me.hand:
        ctx = EffectContext(state, player, "Cathedral")
        (card,) = yield ctx.choose("Cathedral: trash a card from your hand.", tuple(sorted(set(me.hand))))
        ctx.trash(card)


def end_of_buy_steps(state: GameState, player: int):
    """Generator: Exploration (nothing bought) and Pageant (pay $1 for +1 Coffers), at the end of the Buy phase."""
    me = state.players[player]
    if "Exploration" in me.projects and state.bought_turn == 0:
        ctx = EffectContext(state, player, "Exploration")
        ctx.add_coffers(1)
        ctx.add_villagers(1)
    if "Pageant" in me.projects and state.coins >= 1:
        ctx = EffectContext(state, player, "Pageant")
        chosen = yield ctx.choose("Pageant: you may pay $1 for +1 Coffers.", ("Pay $1 for +1 Coffers",), 0, 1)
        if chosen:
            state.coins -= 1
            ctx.add_coffers(1)


def gain_steps(state: GameState, event):
    """Generator: the Projects and Cargo Ship that care about a card being gained (Academy, Guildhall, Road Network, Cargo Ship, Innovation)."""
    player = event.player
    me = state.players[player]
    card = get_card(event.card)
    if "Academy" in me.projects and card.is_type(CardType.ACTION):
        EffectContext(state, player, "Academy").add_villagers(1)
    if "Guildhall" in me.projects and card.is_type(CardType.TREASURE):
        EffectContext(state, player, "Guildhall").add_coffers(1)
    if card.is_type(CardType.VICTORY):
        for other in range(len(state.players)):
            if other != player and "Road Network" in state.players[other].projects:
                EffectContext(state, other, "Road Network").draw(1)
    if state.current_player != player:
        return
    ctx = EffectContext(state, player, "Cargo Ship")
    if ctx.gained_card_present(event):
        entry = next((e for e in me.durations if e.source == "Cargo Ship" and not e.data["cards"]), None)
        if entry is not None:
            chosen = yield ctx.choose(f"Cargo Ship: you may set {event.card} aside, face up. At the start of your next turn it goes into your hand.",
                                      ("Set it aside",), 0, 1)
            if chosen and ctx.gained_card_present(event):
                zone = getattr(me, event.zone)
                zone.pop(len(zone) - 1 - zone[::-1].index(event.card))
                me.cargo_aside.append(event.card)
                entry.data["cards"].append(event.card)
                event.zone = None
                ctx.log(f"{me.name} sets {event.card} aside on Cargo Ship.", "gain")
    if "Innovation" in me.projects and card.is_type(CardType.ACTION) and not state.turn_counts.get("innovation"):
        state.turn_counts["innovation"] = 1                    # only the first Action gained each turn counts, taken or not
        ctx = EffectContext(state, player, "Innovation")
        if ctx.gained_card_present(event):
            chosen = yield ctx.choose(f"Innovation: you may set {event.card} aside and play it.", ("Play it",), 0, 1)
            if chosen and ctx.gained_card_present(event):
                zone = getattr(me, event.zone)
                zone.pop(len(zone) - 1 - zone[::-1].index(event.card))
                me.in_play.append(event.card)
                event.zone = None
                ctx.log(f"{me.name} plays {event.card} with Innovation.", "play")
                yield from ctx.resolve(event.card)


def trash_steps(state: GameState, event):
    """Generator: Priest's bonus for a card trashed after it was played, and Sewers."""
    player = event.player
    if event.priest:
        state.coins += 2 * event.priest
        state.log.append(f"{state.players[player].name} gets +${2 * event.priest} for trashing {event.card} (Priest).", "info", 1)
    me = state.players[player]
    if "Sewers" in me.projects and not event.sewers and me.hand:
        ctx = EffectContext(state, player, "Sewers")
        chosen = yield ctx.choose("Sewers: you may trash a card from your hand.", tuple(sorted(set(me.hand))), 0, 1)
        if chosen:
            ctx.trash(chosen[0])
            state.trash_events[-1].sewers = True


def cleanup_improve_steps(state: GameState, player: int):
    """Generator: at the start of Clean-up each Improve played this turn may trash an Action card that would be discarded, to gain a
    card costing exactly $1 more."""
    from .costs import card_cost
    me = state.players[player]
    for _ in range(state.turn_counts.get("ren:improve", 0)):
        kept = {n for e in me.durations for n in e.cards}
        options = tuple(sorted({c for c in me.in_play if get_card(c).is_type(CardType.ACTION) and c not in kept}))
        if not options:
            break
        ctx = EffectContext(state, player, "Improve")
        chosen = yield ctx.choose("Improve: you may trash an Action card you would discard from play this turn, to gain a card costing exactly $1 more.",
                                  options, 0, 1)
        if not chosen:
            continue
        cost = card_cost(state, chosen[0])
        ctx.trash_in_play(chosen[0])
        gains = ctx.gainable(cost + 1, exact=True)
        if gains:
            (card,) = yield ctx.choose(f"Improve: gain a card costing exactly ${cost + 1}.", gains)
            ctx.gain(card)


def horn_steps(state: GameState, player: int, remaining: list):
    """Generator: the Horn lets its holder put one Border Guard on their deck instead of discarding it from play (once per turn)."""
    if state.artifacts.get("Horn") == player and "Border Guard" in remaining:
        ctx = EffectContext(state, player, "Horn")
        chosen = yield ctx.choose("Horn: you may put a Border Guard onto your deck instead of discarding it.", ("Put it onto your deck",), 0, 1)
        if chosen:
            remaining.remove("Border Guard")
            state.players[player].deck.append("Border Guard")
            ctx.log(f"{state.players[player].name} puts Border Guard onto their deck (Horn).", "info")


def scan_reveals(state: GameState) -> None:
    """Patron: +1 Coffers each time its owner reveals one. Revealing is not tracked at each place a card does it; instead the log lines
    that say a player reveals cards are looked at after every action, and every Patron named in one is a reveal."""
    start, state.reveal_scan = state.reveal_scan, len(state.log)
    if "Patron" not in state.kingdom:
        return
    for line in list(state.log)[start:]:
        text = str(line)
        if " reveals " not in text or "Patron" not in text:
            continue
        for p in state.players:
            if text.startswith(p.name + " reveals "):
                n = text.count("Patron")
                p.coffers += n
                state.log.append(f"{p.name} gets +{n} Coffers for revealing Patron.", "gain", 1)
                break


def star_chart_steps(state: GameState):
    """Generator: a draw that had to shuffle stopped there for a Star Chart owner; they may put any card of the new deck on top, then
    the rest of the draw is done."""
    from . import zones
    while state.star_draws:
        entry = state.star_draws.pop(0)
        player, remaining = entry[0], entry[1]
        me = state.players[player]
        if len(entry) > 2 and entry[2] == "plunder":            # Plunder: Fated and Avoid act before the shuffle is made
            from . import plunder
            yield from plunder.shuffle_steps(state, player)
        elif len(entry) > 2:                                    # Allies: Order of Astrologers / Masons act before the shuffle is made
            from . import allies
            yield from allies.shuffle_steps(state, player)
        if me.deck and "Star Chart" in me.projects:
            ctx = EffectContext(state, player, "Star Chart")
            chosen = yield ctx.choose("Star Chart: you shuffled. You may pick one card of your deck to go on top.", tuple(sorted(set(me.deck))), 0, 1)
            if chosen:
                me.deck.remove(chosen[0])
                me.deck.append(chosen[0])
                ctx.log(f"{me.name} puts a card on top of their deck (Star Chart).")
        zones.draw_cards(state, player, remaining)
