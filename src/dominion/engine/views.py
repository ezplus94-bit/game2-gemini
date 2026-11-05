"""Per-player projection of a game: what ONE player is allowed to see.

The full ``GameState`` contains every player's hand and deck. Anything sent to
a client must come from ``build_view`` so hidden information never leaks. The
result is plain JSON-serializable data.

Visible to everyone: supply, trash, in-play cards, turn resources, each
player's card counts and the top card of their discard pile, the event log.
Visible only to the owner: their own hand. A pending decision's prompt and options go only to the
player who must answer. During a Possession turn the possessor also sees the possessed player's hand
(``view["possession"]["hand"]``) and answers that player's questions.
"""

from __future__ import annotations

from ..cards import get_card
from ..cards.nocturne import BOONS, HEXES, STATES
from ..cards.renaissance import ARTIFACTS
from ..cards import CardType
from .actions import Choose
from .codec import action_to_dict
from .rules import legal_actions
from .cardtypes import type_values
from .costs import card_cost
from .scoring import final_scores, final_stats, score_player
from .state import GameStatus

BASIC_PILES = ("Copper", "Silver", "Gold", "Platinum", "Estate", "Duchy", "Province", "Colony", "Curse", "Potion")
LOG_LINES = 200
from .plunder import LOOT_NAMES as LOOT_CARDS    # noqa: E402


def card_info(name: str, state=None) -> dict:
    card = get_card(name)
    return {
        "name": name,
        "cost": card.cost,
        "potion_cost": card.potion_cost,
        "debt_cost": card.debt_cost,
        "overpay": card.overpay,
        "types": type_values(state, name) if state is not None else sorted(t.value for t in card.types),
        "text": card.text,
        "min_players": card.min_players,
        "expansion": card.expansion,
        "companions": list(card.companions),
    }


def build_view(game, player: int) -> dict:
    s = game.state
    me = s.players[player]
    viewer_blind = me.blind > 0              # Roofie: this viewer cannot read card names, costs or texts
    acting = game.acting_player              # whoever the game waits for (the possessor, under Possession)

    piles = []
    for name in [*BASIC_PILES, *s.kingdom, *([s.bane] if s.bane else []), *s.catastrophes, *(["Ruins"] if "Ruins" in s.stacks else [])]:
        stack = s.stacks.get(name)
        shown = name
        if stack is not None:                          # Knights / Ruins: one pile that shows its top card
            shown = stack[0] if stack else s.stack_cards[name][0]
        if shown in s.supply:
            info = card_info(shown, s)
            info["count"] = len(stack) if stack is not None else s.supply[name]
            info["stack"] = name if stack is not None else None
            info["price"] = card_cost(s, shown)       # what it costs right now (Bridge)
            info["kingdom"] = name in s.kingdom or name == s.bane
            info["bane"] = name == s.bane
            info["catastrophe"] = name in s.catastrophes
            info["embargo"] = s.embargo.get(shown, 0)         # Embargo tokens on this pile
            info["favor_tokens"] = s.pile_tokens.get(name, 0)         # Allies: Family of Inventors
            info["pile_vp"] = s.pile_vp.get(name, 0)                 # Empires: VP tokens on this pile
            info["pile_debt"] = s.pile_debt.get(name, 0)             # Empires: Debt tokens on this pile (Tax)
            info["split"] = ({n: s.supply.get(n, 0) for n in dict.fromkeys(s.stack_cards[name])}
                             if name in s.stack_cards and name not in ("Knights", "Ruins") else None)
            info["walled_by"] = s.walls.get(shown)     # Fortnite: index of the player whose wall stands here, or None
            info["trait"] = s.traits.get(name)         # Plunder: the Trait lying on this pile
            piles.append(info)

    players = []
    for i, p in enumerate(s.players):
        players.append({
            "name": p.name,
            "hand_count": len(p.hand),
            "deck_count": len(p.deck),
            "discard_top": p.discard[-1] if p.discard else None,
            "in_play": list(p.in_play),
            "turns_taken": p.turns_taken,
            "skip_pending": p.skips > 0,
            "protection": "forever" if p.protected_forever else p.protection,
            "bonus_coins": p.bonus_coins,
            "invisible": p.invisible,
            "blind": p.blind,
            "island_mat": list(p.island_mat),             # the Island mat is face up
            "village_mat": len(p.village_mat),            # the Native Village mat is face down: only the count shows
            "haven": len(p.haven),
            "tavern": list(p.tavern),                    # Adventures: the Tavern mat is face up
            "journey_up": p.journey_up,
            "minus_card": p.minus_card,
            "minus_coin": p.minus_coin,
            "tokens": dict(p.tokens),                    # pile tokens: token name -> pile
            "inherited": p.inherited,
            "pirate_tokens": p.pirate_tokens,
            "vp_tokens": p.vp_tokens,
            "debt": p.debt,
            "archived": len(p.archived),
            "enchanted": p.enchanted,
            "states": [n for n, on in (("Deluded", p.deluded), ("Envious", p.envious), ("Miserable", p.miserable == 1),
                                      ("Twice Miserable", p.miserable == 2), ("Lost in the Woods", s.lost_in_woods == i)) if on],
            "held_boons": list(p.held_boons),             # Blessed Village: the Boons are face up
            "crypt": len(p.crypt),                        # face down: only the count shows
            "ghosted": list(p.ghosted),                   # Ghost's Actions are revealed
            "villagers": p.villagers,                     # Renaissance
            "projects": list(p.projects),
            "plot_tokens": p.plot_tokens,
            "favors": p.favors,
            "garrison_tokens": p.garrison_tokens,
            "exile": list(p.exile),                        # Menagerie: the Exile mat is face up
            "invested": {k: min(v, p.exile.count(k)) for k, v in p.invested.items() if p.exile.count(k)},
            "delayed": list(p.delayed),                   # set aside by Delay, Reap or Way of the Turtle (face up)
            "cargo_aside": list(p.cargo_aside),           # set aside face up on Cargo Ship
            "plunder_aside": list(p.plunder_aside) if i == player else len(p.plunder_aside),    # Plunder: set aside on Cage, Grotto, Quartermaster... (only the owner sees them)
            "plunder_aside_n": len(p.plunder_aside),
            "research_aside": len(p.research_aside),      # face down on Research: only the count shows
            "coffers": p.coffers,
            "possessed_by": s.possessor if (s.possessor is not None and i == s.current_player) else None,
            "vp": score_player(p, s),            # deliberately public: players asked to see each other's VP
        })

    pending = None
    if s.pending is not None:
        d = s.pending.decision
        pending = {"player": acting, "source": d.source or s.pending.source}
        if acting == player:            # prompt/options may reveal a hand: only the one who answers sees them
            pending.update(
                prompt=d.prompt, options=list(d.options), min=d.min_choices, max=d.max_choices
            )

    possession = None
    if s.possessor is not None:
        possession = {"possessor": s.possessor, "possessed": s.current_player}
        if player == s.possessor:       # "you can see all cards they can": the possessor sees the possessed hand
            possession["hand"] = sorted(s.players[s.current_player].hand)

    # Free-form answers to a pending decision are described by `pending`, not
    # enumerated (that list can be huge), so Choose actions are not listed here.
    if s.pending is not None:
        legal = []
    else:
        legal = [action_to_dict(a) for a in legal_actions(s, player) if not isinstance(a, Choose)]

    names = {name for name in s.supply} | set(s.offsupply) | set(s.events) | set(s.landmarks) | set(s.ways) | ({s.ally} if s.ally else set()) | set(s.traits.values())
    names |= {c for p in s.players for c in (*p.exile, *p.delayed)}
    names |= set(s.trash) | set(me.hand) | {c for p in s.players for c in (*p.in_play, *p.tavern, *p.ghosted)}
    names |= {get_card(n).heirloom for n in (*s.kingdom, *([s.bane] if s.bane else [])) if get_card(n).heirloom}
    names |= set(me.plunder_aside)
    cards = {n: card_info(n, s) for n in sorted(names)}
    if s.loot or any(s.offsupply.get(n, 0) for n in LOOT_CARDS):
        cards["Loot"] = {"name": "Loot", "cost": 7, "potion_cost": 0, "debt_cost": 0, "overpay": False, "types": ["loot"], "min_players": 1, "expansion": "Plunder",
                         "companions": [], "text": "The Loot pile is shuffled and not in the Supply. Cards that say \"gain a Loot\" gain its top card (revealed). Each Loot is a Treasure costing $7."}
    pseudo = {}                                   # Boons, Hexes and States are not cards but are shown like them
    if s.boons or s.boons_discard or s.druid_boons or s.kept_boons:
        pseudo.update({n: ("boon", t) for n, t in BOONS.items()})
    if s.hexes or s.hexes_discard:
        pseudo.update({n: ("hex", t) for n, t in HEXES.items()})
        pseudo.update({n: ("state", t) for n, t in STATES.items() if n != "Lost in the Woods"})
    if s.lost_in_woods is not None or any(get_card(n).name == "Fool" for n in s.kingdom):
        pseudo["Lost in the Woods"] = ("state", STATES["Lost in the Woods"])
    has_nocturne = bool(pseudo or s.druid_boons)
    pseudo.update({n: ("artifact", t) for n, t in ARTIFACTS.items() if n in s.artifacts})
    for n, (kind, text) in pseudo.items():
        cards[n] = {"name": n, "cost": 0, "potion_cost": 0, "debt_cost": 0, "overpay": False, "types": [kind], "text": text,
                    "min_players": 1, "expansion": "Nocturne", "companions": []}
    view = {
        "status": s.status.value,
        "version": len(game.history),     # increases with every applied action
        "you": player,
        "players": players,
        "piles": piles,
        "trash": list(s.trash),
        "cost_reduction": s.cost_reduction,
        "midas": s.midas,
        "potions": s.potions,
        "trade_mat": s.trade_mat,
        "coffers": s.players[s.current_player].coffers,       # the tokens of whoever's turn it is
        "villagers": s.players[s.current_player].villagers,
        "offsupply": [{"name": n, "count": c, "ferryman": n == s.ferryman} for n, c in sorted(s.offsupply.items()) if n not in LOOT_CARDS]
                     + ([{"name": "Loot", "count": len(s.loot), "ferryman": False}] if s.loot or any(s.offsupply.get(n, 0) for n in LOOT_CARDS) else []),
        "traits": [{**card_info(n, s), "pile": pile} for pile, n in s.traits.items()],
        "bane": s.bane,
        "events": [{**card_info(n, s), "once": get_card(n).once_per_turn, "used": bool(s.turn_counts.get("event:" + n)),
                    "owners": [i for i, p in enumerate(s.players) if n in p.projects]} for n in s.events],
        "mission_turn": s.mission_turn,
        "ways": [card_info(n, s) for n in s.ways],
        "ally": card_info(s.ally, s) if s.ally else None,
        "mouse": s.mouse,
        "landmarks": [{**card_info(n, s), "vp": s.landmark_vp.get(n), "obelisk": s.obelisk if n == "Obelisk" else None} for n in s.landmarks],
        "debt": s.players[player].debt,
        "banned": sorted(s.banned),
        "has_potions": "Potion" in s.supply,
        "possession": possession,
        "controller": s.possessor if s.possessor is not None else s.current_player,
        "blind": viewer_blind,
        "cheats": s.cheats,
        "resigned": list(s.resigned),
        "end_reason": s.end_reason,
        "current_player": s.current_player,
        "acting_player": acting,
        "phase": s.phase.value,
        "actions": s.actions,
        "buys": s.buys,
        "coins": s.coins,
        "turn_number": s.turn_number,
        "hand": sorted(me.hand),
        "pending": pending,
        "legal_actions": legal,
        "log": _log_view(s.log),
        "cards": cards,
        "nocturne": ({"boons_left": len(s.boons), "boons_discard": list(s.boons_discard), "hexes_left": len(s.hexes),
                      "hexes_discard": list(s.hexes_discard), "druid_boons": list(s.druid_boons), "kept_boons": list(s.kept_boons),
                      "deluded_turn": s.deluded_turn, "envious_turn": s.envious_turn}
                     if has_nocturne else None),
        "artifacts": {n: s.artifacts[n] for n in ARTIFACTS if n in s.artifacts},
        "has_night": any(get_card(n).is_type(CardType.NIGHT) for n in s.kingdom),
    }
    if s.status is GameStatus.FINISHED:
        view["final_scores"] = final_scores(s)
        view["winners"] = list(s.winners)
        view["stats"] = final_stats(s)
    return view


def _log_view(log) -> list:
    """The last LOG_LINES entries as plain data. ``i`` is the entry's position in the whole
    log, so a client can tell which entries are new."""
    first = max(0, len(log) - LOG_LINES)
    return [
        {"i": first + n, "turn": line.turn, "kind": line.kind, "indent": line.indent, "text": str(line)}
        for n, line in enumerate(log[first:])
    ]
