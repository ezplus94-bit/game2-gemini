"""Creating games: validation of the configuration and initial supply."""

from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from typing import Optional

from ..cards import CardType, UnknownCardError, expansions as all_expansions, get_card, kingdom_cards, prize_cards
from . import zones
from .constants import (
    CATASTROPHE_PILE_SIZE, EMPTY_PILE_LIMIT, HAND_SIZE, KINGDOM_SIZE, MAX_PLAYERS, MIN_PLAYERS, PLATINUM_PILE_SIZE,
    POTION_PILE_SIZE,
    STARTING_COPPERS, STARTING_ESTATES,
)
from .game import Game
from .state import GameState, PlayerState


@dataclass
class GameConfig:
    player_names: list
    kingdom: Optional[list] = None        # None = random selection
    seed: Optional[int] = None            # None = random seed
    supply_overrides: dict = field(default_factory=dict)   # e.g. {"Province": 1} for tests/variants
    random_start: bool = False            # True = a random player (decided by the seed) goes first
    catastrophes: list = field(default_factory=list)   # 0-2 Catastrophe cards to add (optional house rule)
    expansions: Optional[list] = None     # card sets a RANDOM Kingdom is drawn from; None = every set
    cheats: bool = False                  # allow cheat codes (+100 coins / actions / buys) in this game
    colonies: Optional[bool] = None       # Platinum and Colony in the Supply: None = decided by the seed (Prosperity card picked)
    bane: Optional[str] = None            # Cornucopia: Bane pile card name when Young Witch is in the Kingdom


def new_game(config: GameConfig) -> Game:
    names = list(config.player_names)
    if not MIN_PLAYERS <= len(names) <= MAX_PLAYERS:
        raise ValueError(f"A game needs {MIN_PLAYERS} to {MAX_PLAYERS} players.")
    if any(not str(n).strip() for n in names):
        raise ValueError("Player names cannot be blank.")

    seed = config.seed if config.seed is not None else random.SystemRandom().randrange(2**32)
    expansions = _resolve_expansions(config.expansions)
    kingdom = _resolve_kingdom(config.kingdom, seed, expansions)
    bane = _resolve_bane(config.bane, kingdom, seed, expansions)
    catastrophes = _resolve_catastrophes(config.catastrophes, len(names))
    fenced = _with_companions(catastrophes)
    colonies = _resolve_colonies(config.colonies, kingdom, seed)
    supply_kingdom = [*kingdom, bane] if bane is not None else kingdom
    supply = _build_supply(len(names), supply_kingdom, fenced, config.supply_overrides, colonies)

    rng = random.Random(seed)
    starting_coffers = 1 if "Baker" in supply_kingdom else 0
    players = []
    for name in names:
        deck = ["Copper"] * STARTING_COPPERS + ["Estate"] * STARTING_ESTATES
        rng.shuffle(deck)
        players.append(PlayerState(name=name, deck=deck, coffers=starting_coffers))

    prizes = prize_cards() if "Tournament" in supply_kingdom else []
    state = GameState(
        players=players, supply=supply, kingdom=tuple(supply_kingdom), rng=rng,
        empty_pile_limit=EMPTY_PILE_LIMIT, catastrophes=tuple(fenced), cheats=bool(config.cheats),
        curse_treasure="Charlatan" in supply_kingdom,           # Charlatan turns Curses into Treasures for the whole game
        prizes=prizes, bane=bane,
    )
    if "Trade Route" in kingdom:                                # a token on every Victory pile in the Supply
        state.trade_tokens = {name for name in supply if get_card(name).is_type(CardType.VICTORY)}
    for i in range(len(players)):
        zones.draw_cards(state, i, HAND_SIZE)
    if config.random_start:
        # its own RNG, so turning this on never changes anyone's shuffled deck
        state.current_player = random.Random(seed ^ 0x5EED).randrange(len(players))
    state.log.append(f"Game started. Kingdom: {', '.join(kingdom)}.", "system")
    state.log.append(f"{players[state.current_player].name} goes first.", "system")
    state.log.append(f"Turn 1 - {players[state.current_player].name}", "turn")

    resolved = replace(config, seed=seed, kingdom=list(kingdom), catastrophes=list(catastrophes), expansions=expansions,
                       colonies=colonies, bane=bane)
    return Game(state, resolved)


def replay(config: GameConfig, history: list) -> Game:
    """Rebuild a game from its (resolved) config and action history."""
    game = new_game(config)
    for player, action in history:
        game.apply(player, action)
    return game


def _resolve_expansions(requested) -> Optional[list]:
    if requested is None:
        return None
    picked = list(requested)
    known = all_expansions()
    if not picked or len(set(picked)) != len(picked) or not set(picked) <= set(known):
        raise ValueError("Choose one or more of these card sets: " + ", ".join(known) + ".")
    return picked


def _resolve_kingdom(requested: Optional[list], seed: int, expansions: Optional[list] = None) -> list:
    available = kingdom_cards(expansions)
    if requested is None:
        picked = random.Random(seed).sample(available, min(KINGDOM_SIZE, len(available)))
    else:
        picked = list(requested)
        if not 1 <= len(picked) <= KINGDOM_SIZE:
            raise ValueError(f"Choose between 1 and {KINGDOM_SIZE} Kingdom cards.")
        if len(set(picked)) != len(picked):
            raise ValueError("Kingdom cards must be unique.")
        for name in picked:
            try:
                card = get_card(name)
            except UnknownCardError:
                raise ValueError(f"Unknown card: {name}") from None
            if not card.kingdom:
                raise ValueError(f"{name} cannot be used as a Kingdom card.")
    return sorted(picked, key=lambda n: (get_card(n).cost, n))


def _resolve_bane(requested: Optional[str], kingdom: list, seed: int, expansions: Optional[list] = None) -> Optional[str]:
    """Young Witch needs an extra Kingdom pile costing $2 or $3 (and 0 Potions) as the Bane pile."""
    if "Young Witch" not in kingdom:
        return None
    if requested is not None:
        try:
            card = get_card(requested)
        except UnknownCardError:
            raise ValueError(f"Unknown Bane card: {requested}") from None
        if not card.kingdom or requested in kingdom or card.cost not in (2, 3) or card.potion_cost != 0:
            raise ValueError(f"{requested} cannot be used as a Bane card (must be an unused $2-$3 Kingdom card).")
        return requested
    pool = [
        c for c in kingdom_cards(expansions)
        if c not in kingdom and get_card(c).cost in (2, 3) and get_card(c).potion_cost == 0
    ]
    if not pool:
        pool = [
            c for c in kingdom_cards()
            if c not in kingdom and get_card(c).cost in (2, 3) and get_card(c).potion_cost == 0
        ]
    if not pool:
        return None
    return random.Random(seed ^ 0xBA4E).choice(pool)


def _resolve_colonies(requested: Optional[bool], kingdom: list, seed: int) -> bool:
    """Platinum and Colony are used together. Automatic rule: pick one Kingdom card at random (from the seed);
    if it is a Prosperity card, use them."""
    if requested is not None:
        return bool(requested)
    pick = random.Random(seed ^ 0xC0107).choice(kingdom)
    return get_card(pick).expansion == "Prosperity"


def _resolve_catastrophes(requested, num_players: int) -> list:
    picked = list(requested or [])
    if len(set(picked)) != len(picked):
        raise ValueError("Catastrophe and Special cards must be unique.")
    for name in picked:
        try:
            card = get_card(name)
        except UnknownCardError:
            raise ValueError(f"Unknown card: {name}") from None
        if CardType.CATASTROPHE not in card.types and CardType.SPECIAL not in card.types:
            raise ValueError(f"{name} is not a Catastrophe or Special card.")
        if card.companion_of is not None:
            raise ValueError(f"{name} comes with {card.companion_of} and cannot be picked on its own.")
        if num_players < card.min_players:
            raise ValueError(f"{name} needs at least {card.min_players} players.")
    return picked


def _with_companions(picked: list) -> list:
    """The picked cards plus the extra piles that come with them (Exodia's four other pieces)."""
    out = list(picked)
    for name in picked:
        out.extend(c for c in get_card(name).companions if c not in out)
    return out


def _build_supply(num_players: int, kingdom: list, catastrophes: list, overrides: dict, colonies: bool = False) -> dict:
    victory_count = 8 if num_players == 2 else 12
    supply = {
        "Copper": 60 - STARTING_COPPERS * num_players,
        "Silver": 40,
        "Gold": 30,
        "Estate": victory_count,
        "Duchy": victory_count,
        "Province": victory_count,
        "Curse": 10 * (num_players - 1),
    }
    if colonies:
        supply["Platinum"] = PLATINUM_PILE_SIZE
        supply["Colony"] = victory_count if num_players > 2 else 8
    for name in kingdom:
        is_victory = get_card(name).is_type(CardType.VICTORY)
        supply[name] = victory_count if is_victory else 10
    if any(get_card(name).potion_cost > 0 for name in kingdom):
        supply["Potion"] = POTION_PILE_SIZE              # Alchemy: the Potion pile joins the Supply
    for name in catastrophes:
        supply[name] = CATASTROPHE_PILE_SIZE
    for name, count in overrides.items():
        if name not in supply:
            raise ValueError(f"Cannot override unknown pile: {name}")
        if not isinstance(count, int) or count < 0:
            raise ValueError(f"Pile size for {name} must be a non-negative integer.")
        supply[name] = count
    return supply
