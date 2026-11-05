"""Creating games: validation of the configuration and initial supply."""

from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from typing import Optional

from ..cards import CardType, UnknownCardError, event_cards, expansions as all_expansions, get_card, kingdom_cards, landmark_cards, project_cards, trait_cards, way_cards
from . import allies as ally_rules, landmarks as landmark_rules, menagerie as menagerie_rules, nocturne as nocturne_rules, plunder as plunder_rules, renaissance as renaissance_rules, risingsun as risingsun_rules, zones
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
    bane: Optional[str] = None            # Young Witch's Bane pile (None = chosen by the seed when Young Witch is in the Kingdom)
    ferryman: Optional[str] = None        # Ferryman's pile (None = chosen by the seed when Ferryman is in the Kingdom)
    events: Optional[list] = None         # Adventures: Events to use (0-2). None = decided by the seed when an Adventures card is in the Kingdom
    shelters: Optional[bool] = None       # Dark Ages: Hovel, Necropolis and Overgrown Estate instead of 3 Estates: None = decided by the seed
    ally: Optional[str] = None            # Allies: the Ally to use. None = decided by the seed when a Liaison is in the Kingdom


def new_game(config: GameConfig) -> Game:
    names = list(config.player_names)
    if not MIN_PLAYERS <= len(names) <= MAX_PLAYERS:
        raise ValueError(f"A game needs {MIN_PLAYERS} to {MAX_PLAYERS} players.")
    if any(not str(n).strip() for n in names):
        raise ValueError("Player names cannot be blank.")

    seed = config.seed if config.seed is not None else random.SystemRandom().randrange(2**32)
    expansions = _resolve_expansions(config.expansions)
    kingdom = _resolve_kingdom(config.kingdom, seed, expansions)
    base_kingdom = list(kingdom)                                                  # (what the host chose: Approaching Army's extra pile is added from the seed)
    requested_events = [n for n in (config.events or []) if CardType.PROPHECY not in get_card(n).types] if config.events is not None else None
    prophecy = risingsun_rules.pick_prophecy(config.events, kingdom, seed)        # Rising Sun: one Prophecy whenever an Omen is in the Kingdom
    if prophecy == "Approaching Army":                                            # ... which adds an Attack pile to the Supply
        kingdom = [*kingdom, risingsun_rules.pick_attack_pile(kingdom, seed, expansions, MULTI_PILES)]
    catastrophes = _resolve_catastrophes(config.catastrophes, len(names))
    fenced = _with_companions(catastrophes)
    colonies = _resolve_colonies(config.colonies, kingdom, seed)
    bane = _resolve_extra_pile(config.bane, "Young Witch", kingdom, seed, (2, 3), expansions)
    taken = [*kingdom, *([bane] if bane else [])]
    ferryman = _resolve_extra_pile(config.ferryman, "Ferryman", taken, seed, (3, 4), expansions)
    chosen_extras = _resolve_events(requested_events, kingdom, seed)
    events = [n for n in chosen_extras if CardType.EVENT in get_card(n).types or CardType.PROJECT in get_card(n).types]     # (Projects are bought like Events)
    landmark_names = [n for n in chosen_extras if CardType.LANDMARK in get_card(n).types]
    way_names = [n for n in chosen_extras if CardType.WAY in get_card(n).types]
    trait_names = [n for n in chosen_extras if CardType.TRAIT in get_card(n).types]
    mouse = menagerie_rules.pick_mouse_card(taken, seed, expansions, MULTI_PILES) if "Way of the Mouse" in way_names else None
    piles_used = [card for pile in taken if pile in ALLIES_SPLITS for card in ALLIES_SPLITS[pile]]      # Allies: the cards inside the split piles
    used = [*taken, *piles_used, *([ferryman] if ferryman else []), *([mouse] if mouse else [])]
    ally = ally_rules.pick_ally(config.ally, used, seed)     # every card whose rules are in force in this game
    shelters = _resolve_shelters(config.shelters, kingdom, seed)
    heirlooms = [get_card(n).heirloom for n in used if get_card(n).heirloom]       # Nocturne: each replaces one starting Copper
    supply = _build_supply(len(names), kingdom, fenced, config.supply_overrides, colonies, bane, len(heirlooms))
    stacks = _build_stacks(len(names), kingdom, used, supply, random.Random(seed ^ 0xD4A6))
    offsupply = _build_offsupply(len(names), used)
    if any(get_card(n).expansion == "Menagerie" for n in [*used, *chosen_extras]):
        offsupply["Horse"] = 30                                  # Menagerie: the Horse pile (not in the Supply)
    if ferryman:
        offsupply[ferryman] = (8 if len(names) == 2 else 12) if get_card(ferryman).is_type(CardType.VICTORY) else 10

    rng = random.Random(seed)
    players = []
    for name in names:
        deck = ["Copper"] * (STARTING_COPPERS - len(heirlooms)) + heirlooms + (list(SHELTERS) if shelters else ["Estate"] * STARTING_ESTATES)
        rng.shuffle(deck)
        players.append(PlayerState(name=name, deck=deck))

    state = GameState(
        players=players, supply=supply, kingdom=tuple(kingdom), rng=rng,
        empty_pile_limit=EMPTY_PILE_LIMIT, catastrophes=tuple(fenced), cheats=bool(config.cheats),
        curse_treasure="Charlatan" in used, events=tuple(events),                     # Charlatan turns Curses into Treasures for the whole game
        changeling="Changeling" in used, offsupply=offsupply, stacks=stacks, bane=bane, ferryman=ferryman, footpad="Footpad" in used, duchess="Duchess" in used,
    )
    state.landmarks = tuple(landmark_names)
    state.ways = tuple(way_names)
    state.ally = ally
    state.shaman = "Shaman" in used                            # Plunder
    state.card_sets = expansions                               # Rising Sun: Divine Wind deals new piles from these sets
    if prophecy:
        state.prophecy, state.suns = prophecy, risingsun_rules.SUNS[min(max(len(names), 2), 6)]
    if "Riverboat" in used:                                    # Rising Sun: Riverboat's setup
        state.riverboat = risingsun_rules.pick_riverboat(used, seed, expansions, MULTI_PILES)
    if trait_names:                                            # Plunder: each Trait lies on a random Action or Treasure Kingdom pile
        state.traits = plunder_rules.pick_trait_piles(trait_names, list(kingdom), MULTI_PILES, seed)
    if any(n in plunder_rules.LOOT_USERS for n in [*used, *chosen_extras]):
        plunder_rules.build_loot(state, seed)                  # Plunder: the shuffled Loot pile
    if ally is not None:                                       # Allies: Favors (one each, five each with Importer)
        for p in state.players:
            p.favors = 5 if "Importer" in used else 1
    state.mouse = mouse
    state.stack_of = {card: pile for pile, cards in stacks.items() for card in cards}
    state.stack_cards = {pile: tuple(cards) for pile, cards in stacks.items()}
    landmark_rules.setup(state, random.Random(seed ^ 0x1A4D))
    nocturne_rules.setup(state, used, random.Random(seed ^ 0xB00F))
    renaissance_rules.setup(state, used)
    if "Tax" in events:                                         # Empires: Tax puts a Debt token on every Supply pile
        state.pile_debt = {state.stack_of.get(n, n): 1 for n in supply if n not in fenced}
    if "Baker" in used:                                         # Baker's setup: every player starts with a Coffers token
        for player in players:
            player.coffers = 1
    if "Trade Route" in used:                                   # a token on every Victory pile in the Supply
        state.trade_tokens = {name for name in supply if get_card(name).is_type(CardType.VICTORY)}
    for i in range(len(players)):
        zones.draw_cards(state, i, HAND_SIZE)
    if config.random_start:
        # its own RNG, so turning this on never changes anyone's shuffled deck
        state.current_player = random.Random(seed ^ 0x5EED).randrange(len(players))
    state.log.append(f"Game started. Kingdom: {', '.join(kingdom)}.", "system")
    state.log.append(f"{players[state.current_player].name} goes first.", "system")
    state.log.append(f"Turn 1 - {players[state.current_player].name}", "turn")

    resolved = replace(config, seed=seed, kingdom=list(base_kingdom), catastrophes=list(catastrophes), expansions=expansions,
                       colonies=colonies, bane=bane, ferryman=ferryman, shelters=shelters, events=[*events, *landmark_names, *way_names, *trait_names, *([prophecy] if prophecy else [])], ally=ally)
    game = Game(state, resolved)
    inherited = [pile for pile, name in state.traits.items() if name == "Inherited"]
    if inherited:                                              # Plunder: Inherited: everybody picks a starting card to swap, in turn order
        game._advance(plunder_rules.inherited_steps(state, inherited[0]), None, "Inherited")
    return game


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


def _resolve_colonies(requested: Optional[bool], kingdom: list, seed: int) -> bool:
    """Platinum and Colony are used together. Automatic rule: pick one Kingdom card at random (from the seed);
    if it is a Prosperity card, use them."""
    if requested is not None:
        return bool(requested)
    pick = random.Random(seed ^ 0xC0107).choice(kingdom)
    return get_card(pick).expansion == "Prosperity"


def _resolve_events(requested: Optional[list], kingdom: list, seed: int) -> list:
    """Events, Landmarks, Projects and Ways together (at most two, in any mix, and at most one Way). Automatic rule: when an Adventures card is in the Kingdom the
    pool holds the Adventures Events, when an Empires card is in it the pool also holds the Empires Events and Landmarks, when a
    Renaissance card is in it the pool also holds the Projects;
    two are picked from the seed. No such card means none. An empty list means none."""
    everything = [*event_cards(), *landmark_cards(), *project_cards(), *way_cards(), *trait_cards()]
    if requested is not None:
        picked = list(requested)
        if len(picked) > 2 or len(set(picked)) != len(picked):
            raise ValueError("Choose up to 2 different Events, Landmarks, Projects and Ways.")
        for name in picked:
            if name not in everything:
                raise ValueError(f"Unknown Event, Landmark, Project or Way: {name}")
        return sorted(picked, key=lambda n: (get_card(n).cost, n))
    sets = {get_card(n).expansion for n in kingdom}
    pool = [*event_cards([e for e in ("Adventures", "Empires", "Menagerie", "Plunder", "Rising Sun") if e in sets]),
            *(trait_cards(["Plunder"]) if "Plunder" in sets else []),
            *(landmark_cards(["Empires"]) if "Empires" in sets else []),
            *(project_cards(["Renaissance"]) if "Renaissance" in sets else []),
            *(way_cards(["Menagerie"]) if "Menagerie" in sets else [])]
    if not pool:
        return []
    rng = random.Random(seed ^ 0xE7E47)
    picked = rng.sample(pool, 2)
    if all(CardType.WAY in get_card(n).types for n in picked):              # at most one Way per game
        picked[1] = rng.choice([n for n in pool if CardType.WAY not in get_card(n).types])
    return sorted(picked, key=lambda n: (get_card(n).cost, n))


def _resolve_shelters(requested: Optional[bool], kingdom: list, seed: int) -> bool:
    """Shelters replace the three starting Estates. Automatic rule: pick one Kingdom card at random (from the seed);
    if it is a Dark Ages card, use them."""
    if requested is not None:
        return bool(requested)
    pick = random.Random(seed ^ 0x5E17).choice(kingdom)
    return get_card(pick).expansion == "Dark Ages"


SHELTERS = ("Hovel", "Necropolis", "Overgrown Estate")
KNIGHTS = ("Dame Anna", "Dame Josephine", "Dame Molly", "Dame Natalie", "Dame Sylvia",
           "Sir Bailey", "Sir Destry", "Sir Martin", "Sir Michael", "Sir Vander")
SPLIT_PILES = {"Settlers": "Bustling Village", "Catapult": "Rocks", "Encampment": "Plunder",
               "Gladiator": "Fortune", "Patrician": "Emporium"}                       # Empires: top half -> bottom half
CASTLES = ("Humble Castle", "Crumbling Castle", "Small Castle", "Haunted Castle",
           "Opulent Castle", "Sprawling Castle", "Grand Castle", "King's Castle")
DOUBLE_CASTLES = ("Humble Castle", "Small Castle", "Opulent Castle", "King's Castle")      # two copies each with 3 or 4 players
ALLIES_SPLITS = {"Augurs": ("Herb Gatherer", "Acolyte", "Sorceress", "Sibyl"),          # Allies: four cards of four copies each, cheapest on top
                 "Clashes": ("Battle Plan", "Archer", "Warlord", "Territory"),
                 "Forts": ("Tent", "Garrison", "Hill Fort", "Stronghold"),
                 "Odysseys": ("Old Map", "Voyage", "Sunken Treasure", "Distant Shore"),
                 "Townsfolk": ("Town Crier", "Blacksmith", "Miller", "Elder"),
                 "Wizards": ("Student", "Conjurer", "Sorcerer", "Lich")}
MULTI_PILES = (*SPLIT_PILES, *ALLIES_SPLITS, "Castles", "Knights")                                       # piles made of more than one card
RUINS = ("Abandoned Mine", "Ruined Library", "Ruined Market", "Ruined Village", "Survivors")


def _build_stacks(num_players: int, kingdom: list, used: list, supply: dict, rng: random.Random) -> dict:
    """Dark Ages mixed piles. They live in the Supply under each card's own name, but only the top card of the pile can
    be bought or gained: the Knights (when "Knights" is a Kingdom card) and the Ruins (when a Looter is in the game).
    The Kingdom card "Knights" itself is only a placeholder name and never enters the Supply."""
    stacks: dict = {}
    for top, bottom in SPLIT_PILES.items():                  # Empires: five cards of each half, the top half first
        if top in kingdom:
            stacks[top] = [top] * 5 + [bottom] * 5
            supply.update({top: 5, bottom: 5})
    for pile, members in ALLIES_SPLITS.items():              # Allies: four copies of each of the four cards, cheapest on top
        if pile in kingdom:
            supply.pop(pile, None)
            stacks[pile] = [card for card in members for _ in range(4)]
            supply.update({card: 4 for card in members})
    if "Castles" in kingdom:                                  # Empires: the Castles, cheapest on top
        supply.pop("Castles", None)
        copies = {c: (2 if num_players > 2 and c in DOUBLE_CASTLES else 1) for c in CASTLES}
        stacks["Castles"] = [c for c in CASTLES for _ in range(copies[c])]
        supply.update(copies)
    if "Knights" in kingdom:
        supply.pop("Knights", None)
        cards = list(KNIGHTS)
        rng.shuffle(cards)
        stacks["Knights"] = cards
        supply.update({name: 1 for name in cards})
    if any(get_card(name).is_type(CardType.LOOTER) for name in used):
        each = 2 * (num_players - 1)                         # 10 Ruins per opponent: 2 of each of the five kinds
        cards = [name for name in RUINS for _ in range(each)]
        rng.shuffle(cards)
        stacks["Ruins"] = cards
        supply.update({name: each for name in RUINS})
    return stacks


def _resolve_extra_pile(requested: Optional[str], needs: str, taken: list, seed: int, costs: tuple, expansions) -> Optional[str]:
    """The extra Kingdom pile some cards bring along (Young Witch's Bane, Ferryman's pile): a card costing $2 or $3 (or
    $3 or $4) that is not already in the game. Only used when ``needs`` is in the game."""
    if needs not in taken:
        return None
    if requested is not None:
        card = get_card(requested)
        if not card.kingdom or requested in taken or card.potion_cost or card.cost not in costs or requested in MULTI_PILES:
            raise ValueError(f"{requested} cannot be the extra pile for {needs}.")
        return requested
    candidates = [
        name for name in kingdom_cards(expansions)
        if name not in taken and name not in ("Young Witch", "Ferryman")
        and get_card(name).cost in costs and not get_card(name).potion_cost and name not in MULTI_PILES
    ]
    if not candidates:
        return None
    return random.Random(seed ^ (0xBA4E if needs == "Young Witch" else 0xFE44)).choice(candidates)


def _build_offsupply(num_players: int, used: list) -> dict:
    """Piles that are not in the Supply: the Prizes (Tournament), the Rewards (Joust) and the Ferryman pile."""
    piles: dict = {}
    if "Tournament" in used:
        piles.update({name: 1 for name in PRIZES})
    if "Joust" in used:
        piles.update({name: 1 if num_players == 2 else 2 for name in REWARDS})
    if any(name in used for name in ("Bandit Camp", "Marauder", "Pillage")):
        piles["Spoils"] = 15
    if "Hermit" in used:
        piles["Madman"] = 10
    if "Urchin" in used:
        piles["Mercenary"] = 10
    if any(CardType.FATE in get_card(n).types for n in used) or "Exorcist" in used:     # Nocturne: Spirits and other extra piles
        piles["Will-o'-Wisp"] = 12
    if any(n in used for n in ("Devil's Workshop", "Tormentor", "Exorcist")):
        piles["Imp"] = 13
    if any(n in used for n in ("Cemetery", "Exorcist")):
        piles["Ghost"] = 6
    if any(n in used for n in ("Leprechaun", "Secret Cave")):
        piles["Wish"] = 12
    if "Vampire" in used:
        piles["Bat"] = 10
    if "Page" in used:
        piles.update({name: 5 for name in PAGE_LINE})
    if "Peasant" in used:
        piles.update({name: 5 for name in PEASANT_LINE})
    return piles


PAGE_LINE = ("Treasure Hunter", "Warrior", "Hero", "Champion")          # Page -> Treasure Hunter -> Warrior -> Hero -> Champion
PEASANT_LINE = ("Soldier", "Fugitive", "Disciple", "Teacher")           # Peasant -> Soldier -> Fugitive -> Disciple -> Teacher
PRIZES = ("Bag of Gold", "Diadem", "Followers", "Princess", "Trusty Steed")
REWARDS = ("Coronet", "Courser", "Demesne", "Housecarl", "Huge Turnip", "Renown")


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


def _build_supply(num_players: int, kingdom: list, catastrophes: list, overrides: dict, colonies: bool = False,
                  bane: Optional[str] = None, heirlooms: int = 0) -> dict:
    victory_count = 8 if num_players == 2 else 12
    supply = {
        "Copper": 60 - (STARTING_COPPERS - heirlooms) * num_players,       # Heirlooms replace starting Coppers, which go back to the pile
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
    piles = [*kingdom, *([bane] if bane else [])]
    for name in piles:
        is_victory = get_card(name).is_type(CardType.VICTORY)
        supply[name] = 20 if name == "Rats" else (victory_count if is_victory else 10)
    if any(get_card(name).potion_cost > 0 for name in piles):
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
