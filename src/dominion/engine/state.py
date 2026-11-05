"""Plain data describing a game in progress. No rules live here."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from .actions import Decision


class LogLine(str):
    """A log message that remembers when and how it happened.

    It *is* a ``str`` (so ``"text" in log`` and string comparisons keep working);
    ``turn`` is the turn number, ``kind`` a colour class, ``indent`` the nesting depth.
    """

    turn: int = 0
    kind: str = "info"
    indent: int = 0

    def __new__(cls, text: str, turn: int = 0, kind: str = "info", indent: int = 0):
        obj = super().__new__(cls, text)
        obj.turn, obj.kind, obj.indent = turn, kind, indent
        return obj


def classify(text: str) -> str:
    """Best-effort colour class for a plain message (explicit kinds win over this)."""
    t = text
    if t.startswith("Game over") or t.startswith("Winner"):
        return "end"
    if " buys " in t:
        return "buy"
    if " gains " in t:
        return "gain"
    if " trashes " in t or " trash " in t:
        return "trash"
    if " plays " in t:
        return "play"
    if " discards " in t or " discard " in t:
        return "discard"
    if " draws " in t:
        return "draw"
    if "reveals" in t or "unaffected" in t:
        return "reveal"
    if "ends their turn" in t or "moves to the Buy phase" in t or "skipped" in t:
        return "phase"
    return "info"


class GameLog(list):
    """Event history. ``append`` wraps plain strings into ``LogLine`` objects."""

    def __init__(self) -> None:
        super().__init__()
        self.turn_of = lambda: 0           # set by GameState: returns the current turn number

    def append(self, text, kind=None, indent: int = 0) -> None:      # type: ignore[override]
        if isinstance(text, LogLine):
            super().append(text)
            return
        text = str(text)
        super().append(LogLine(text, self.turn_of(), kind or classify(text), indent))


class Phase(str, Enum):
    ACTION = "action"
    BUY = "buy"
    NIGHT = "night"     # Nocturne: only entered when the player has a Night card in hand after the Buy phase
    # Cleanup is automatic unless a card asks the player something (Herbalist, Alchemist), so it is not a phase.


class GameStatus(str, Enum):
    ACTIVE = "active"
    FINISHED = "finished"


@dataclass
class GainEvent:
    """A card that was just gained, waiting for "when you gain" effects to be looked at (see ``Game._settle``).
    ``zone`` is where the card went ("discard", "hand" or "deck"); it is None once the card is gone (trashed)."""
    player: int
    card: str
    zone: Optional[str]
    bought: bool = False
    from_supply: bool = True
    overpaid: int = 0
    nth: int = 0              # Empires: which card gained during its owner's turn this was (1 = the first); 0 if not on their turn
    buy_phase: bool = False   # Empires: it was gained during its owner's Buy phase


@dataclass
class TrashEvent:
    """A card of ``player`` that was just trashed, waiting for \"when you trash this\" effects (see ``Game._settle``)."""
    player: int
    card: str
    priest: int = 0         # Priests played this turn when the card was trashed (Renaissance: +$2 each for a card trashed after them)
    sewers: bool = False    # trashed by Sewers itself (which does not set Sewers off again)


@dataclass
class DurationEntry:
    """Something a Duration card does at the start of its owner's next turn.
    ``handler(ctx, entry)`` runs then (``None`` for a card that merely has to stay in play, e.g. Outpost or a
    Throne Room that played a Duration card). ``cards`` are the cards that stay in play because of this entry."""
    source: str
    cards: tuple
    handler: Any = None
    data: Any = None


@dataclass
class PlayerState:
    """One player's zones. Cards are card *names*.

    The top of the draw pile is the END of ``deck`` (``deck.pop()`` draws).
    """
    name: str
    deck: list = field(default_factory=list)       # draw pile
    hand: list = field(default_factory=list)
    discard: list = field(default_factory=list)
    in_play: list = field(default_factory=list)
    set_aside: list = field(default_factory=list)  # for future cards (Library, Sentry...)
    protection: int = 0                            # Guardian Angel: Attacks skip this player while > 0 (own turns left)
    protection_fresh: bool = False                 # true during the turn protection was gained (that turn is not counted)
    protected_forever: bool = False                # God Mode: protected for the rest of the game
    bonus_coins: int = 0                           # Rosebud gift, added to the coins of this player's next turn
    invisible: bool = False                        # Invisibility Cloak: no other player's card affects this player
    blind: int = 0                                 # Roofie: turns left in which this player cannot read cards
    bought: list = field(default_factory=list)     # every card this player bought (stats)
    gained: list = field(default_factory=list)     # every card this player gained, bought or not (stats)
    island_mat: list = field(default_factory=list)    # Seaside: cards set aside by Island (face up, still yours)
    village_mat: list = field(default_factory=list)   # Seaside: cards set aside by Native Village (face down)
    haven: list = field(default_factory=list)         # Seaside: cards set aside by Haven until the next turn
    durations: list = field(default_factory=list)     # DurationEntry objects waiting for the start of the next turn
    pirate_tokens: int = 0                            # Seaside: coin tokens on the Pirate Ship mat
    vp_tokens: int = 0                                # Prosperity: victory point tokens (worth their number at the end)
    coffers: int = 0                                  # Guilds: coin tokens on the Coffers mat (each is +$1 when spent)
    farmhands: list = field(default_factory=list)     # Cornucopia: cards set aside by Farmhands, played at the start of the next turn
    joust_aside: list = field(default_factory=list)   # Cornucopia: a Province set aside by Joust until cleanup
    extra_draw: int = 0                               # Farrier: extra cards drawn for the next hand
    buy_gains: int = 0                                # cards gained during this player's Buy phase (Merchant Guild)
    gained_turn: list = field(default_factory=list)   # cards gained during this player's current turn (Smugglers)
    last_gained: list = field(default_factory=list)   # ... and during their previous turn
    tavern: list = field(default_factory=list)       # Adventures: the Tavern mat (Reserve cards waiting to be called, Miser's Coppers, Distant Lands)
    saved: list = field(default_factory=list)        # Adventures: the card set aside by the Save event (back in hand after the next draw)
    journey_up: bool = True                          # Adventures: the Journey token (Giant, Ranger, Pilgrimage) starts face up
    minus_card: bool = False                         # Adventures: the -1 Card token is on this player's deck
    minus_coin: bool = False                         # Adventures: this player has the -$1 token
    tokens: dict = field(default_factory=dict)       # Adventures: pile tokens: token name -> the Action pile it sits on
    inherited: Optional[str] = None                  # Adventures: the Action card Inheritance set aside (Estates play as it)
    debt: int = 0                                    # Empires: Debt tokens (no buying cards or Events while this is above 0)
    archived: list = field(default_factory=list)     # Empires: cards set aside face down by Archive (still yours)
    crypt: list = field(default_factory=list)        # Nocturne: Treasures set aside face down under Crypt (still yours)
    cargo_aside: list = field(default_factory=list)  # Renaissance: cards set aside on Cargo Ship (still yours)
    research_aside: list = field(default_factory=list)   # Renaissance: cards set aside face down on Research (still yours)
    villagers: int = 0                               # Renaissance: Villager tokens, each spent for +1 Action in the Action phase
    projects: list = field(default_factory=list)     # Renaissance: the Projects this player has put a cube on
    plot_tokens: int = 0                             # Renaissance: tokens on Sinister Plot
    ghosted: list = field(default_factory=list)      # Nocturne: Action cards set aside by Ghost, to be played twice next turn (still yours)
    hounds: list = field(default_factory=list)       # Nocturne: Faithful Hounds set aside; they return to the hand at end of turn
    held_boons: list = field(default_factory=list)   # Nocturne: Boons taken with Blessed Village, to be received at the start of the next turn
    deluded: bool = False                            # Nocturne: the Deluded state (no Action buys, returned at the start of the Buy phase)
    envious: bool = False                            # Nocturne: the Envious state (Silver and Gold make $1, returned at the start of the Buy phase)
    miserable: int = 0                               # Nocturne: 1 = Miserable (-2 VP), 2 = Twice Miserable (-4 VP)
    enchanted: int = 0                               # Empires: Enchantresses whose effect is waiting for this player's first Action
    exile: list = field(default_factory=list)        # Menagerie: the Exile mat (face up, still yours: it scores)
    invested: dict = field(default_factory=dict)     # Menagerie: card name -> copies on the Exile mat that were put there with Invest
    delayed: list = field(default_factory=list)      # Menagerie: cards set aside by Delay, Reap and Way of the Turtle (played at the start of the next turn)
    monkey: int = 0                                  # Menagerie: Way of the Monkey plays active until this player's next turn
    squirrel: int = 0                                # Menagerie: cards Way of the Squirrel draws at the end of this turn
    favors: int = 0                                  # Allies: Favor tokens
    garrison_tokens: int = 0                         # Allies: tokens on this player's Garrisons in play (drawn as cards next turn)
    plunder_aside: list = field(default_factory=list)  # Plunder: cards set aside on Cage, Grotto, Quartermaster, and by Prepare, Hasty and Patient (still yours)
    eot_hand: list = field(default_factory=list)       # Plunder: cards that go into the hand at the end of this turn (Puzzle Box, Deliver, Cage, Trickster)
    eot_deck: list = field(default_factory=list)       # Plunder: Tireless cards that go onto the deck at the end of this turn
    seize_used: bool = False                         # Menagerie: Seize the Day has been bought (once per game)
    trashed_turn: int = 0                            # Menagerie: cards this player trashed during their current turn (Goatherd)
    trashed_last: int = 0                            # ... and during their previous turn
    turns_taken: int = 0
    skips: int = 0                 # turns this player will skip
    skip_protected: bool = False   # just had a turn skipped: cannot be skipped again until they play one

    def all_cards(self) -> list:
        return [*self.deck, *self.hand, *self.discard, *self.in_play, *self.set_aside,
                *self.island_mat, *self.village_mat, *self.haven, *self.farmhands, *self.joust_aside,
                *self.tavern, *self.saved, *self.archived, *self.crypt, *self.ghosted, *self.hounds,
                *self.cargo_aside, *self.research_aside, *self.exile, *self.delayed, *self.plunder_aside, *self.eot_hand, *self.eot_deck]


@dataclass
class Trigger:
    """A delayed effect that lasts until end of turn (e.g. Merchant's Silver bonus).
    ``handler(ctx, trigger, *event_args)`` runs when ``event`` happens."""
    event: str
    source: str
    handler: Any
    owner: int
    used: bool = False


@dataclass
class PendingEffect:
    """A card effect that is paused, waiting for a player's answer."""
    decision: Decision
    generator: Any    # the suspended effect (a live generator)
    source: str       # name of the card that asked


@dataclass
class GameState:
    players: list
    supply: dict                      # card name -> cards remaining
    kingdom: tuple                    # Kingdom card names (display order)
    rng: random.Random
    trash: list = field(default_factory=list)
    current_player: int = 0
    phase: Phase = Phase.ACTION
    actions: int = 1
    buys: int = 1
    coins: int = 0
    turn_number: int = 1
    status: GameStatus = GameStatus.ACTIVE
    pending: Optional[PendingEffect] = None
    empty_pile_limit: int = 3
    catastrophes: tuple = ()          # names of the Catastrophe piles in this game
    buy_locked: bool = False          # set by Cataclysm: no buying for the rest of this turn
    cost_reduction: int = 0           # Bridge: cards cost this much less this turn
    plays_this_turn: int = 0          # Actions played this turn, Throne Room repeats included (Conspirator)
    triggers: list = field(default_factory=list)  # Trigger objects, cleared at end of turn
    cheats: bool = False              # cheat codes allowed in this game (host's choice)
    walls: dict = field(default_factory=dict)     # Fortnite: pile name -> index of the player who walled it off
    midas: bool = False               # Midas Touch: every Treasure played this turn is worth $3
    potions: int = 0                  # Alchemy: Potions available to spend this turn
    possessor: Optional[int] = None   # Possession: who controls the current (extra) turn, or None
    extra_turns: int = 0              # Possession: extra turns still to be taken after the current turn
    extra_owner: Optional[int] = None  # ... and the player who will control them
    gain_events: list = field(default_factory=list)   # GainEvent objects waiting to be looked at
    trash_events: list = field(default_factory=list)  # TrashEvent objects waiting to be looked at (Dark Ages)
    stacks: dict = field(default_factory=dict)        # Dark Ages: mixed piles (Knights, Ruins): pile name -> card names left, top first
    stack_of: dict = field(default_factory=dict)      # ... and which pile each such card belongs to
    stack_cards: dict = field(default_factory=dict)   # ... every card name a pile started with (for showing an empty pile)
    bought_turn: int = 0                              # cards bought this turn (Hermit)
    overpaid: int = 0                                 # $ overpaid on the card being bought right now
    buying: bool = False                              # the card being gained right now is being bought (Hoard, Goons, Talisman)
    offsupply: dict = field(default_factory=dict)     # piles that are not in the Supply: Prizes, Rewards, the Ferryman pile
    bane: Optional[str] = None                        # Young Witch: the extra Kingdom pile whose cards are Banes
    ferryman: Optional[str] = None                    # Ferryman: the pile (outside the Supply) a Ferryman gains a card from
    turn_counts: dict = field(default_factory=dict)   # per-turn tallies (first Crossroads, Fool's Gold plays, Schemes); cleared in cleanup
    duchess: bool = False                             # Duchess is in the game: gaining a Duchy lets you gain a Duchess
    footpad: bool = False                             # Footpad is in the game: gaining a card in an Action phase draws a card
    curse_treasure: bool = False                      # Charlatan is in the game: Curses are also Treasures worth $1
    trade_tokens: set = field(default_factory=set)    # Trade Route: Victory piles that still carry a token
    trade_mat: int = 0                                # ... and the tokens already moved to the Trade Route mat
    action_cost_reduction: int = 0                    # Quarry: Action cards cost this much less this turn
    banned: set = field(default_factory=set)          # Contraband: cards that cannot be bought this turn
    war_chest_named: list = field(default_factory=list)   # cards named for War Chests this turn
    embargo: dict = field(default_factory=dict)       # Seaside: Supply pile -> number of Embargo tokens on it
    bought_victory: bool = False                      # a Victory card was bought this turn (Treasury)
    outpost_flag: bool = False                        # Outpost was played this turn
    outpost_next: bool = False                        # the next turn is the same player's Outpost turn
    outpost_turn: bool = False                        # the current turn is an Outpost turn (no third turn in a row)
    events: tuple = ()                # Adventures: the Events in this game (bought with a Buy, never gained)
    landmarks: tuple = ()             # Empires: the Landmarks in this game
    landmark_vp: dict = field(default_factory=dict)    # Empires: Landmark name -> VP tokens still on it
    pile_vp: dict = field(default_factory=dict)        # Empires: Supply pile -> VP tokens on it (Gathering cards, Aqueduct, Defiled Shrine)
    pile_debt: dict = field(default_factory=dict)      # Empires: Supply pile -> Debt tokens on it (Tax)
    obelisk: Optional[str] = None                      # Empires: the pile Obelisk scores
    mountain_done: bool = False                        # Empires: Mountain Pass has been triggered
    mountain_next: Optional[int] = None                # ... and this player gained the first Province: bidding comes after their turn
    boons: list = field(default_factory=list)          # Nocturne: the Boons deck (top first)
    boons_discard: list = field(default_factory=list)  # ... its discard pile
    hexes: list = field(default_factory=list)          # Nocturne: the Hexes deck (top first)
    hexes_discard: list = field(default_factory=list)  # ... its discard pile
    druid_boons: list = field(default_factory=list)    # Nocturne: the three Boons set aside face up for Druid
    kept_boons: list = field(default_factory=list)     # Nocturne: Boons "kept until Clean-up" (they go to the discard pile then)
    river_draws: list = field(default_factory=list)    # Nocturne: players who draw a card at the end of this turn (The River's Gift)
    lost_in_woods: Optional[int] = None                # Nocturne: the player holding the Lost in the Woods state
    deluded_turn: bool = False                         # Nocturne: Action cards cannot be bought this turn
    envious_turn: bool = False                         # Nocturne: Silver and Gold make $1 this turn
    changeling: bool = False                           # Nocturne: Changeling is in the game (a gained card costing $3+ may be exchanged for one)
    cleanup_active: bool = False                       # Clean-up is running ("other than during Clean-up" effects stay quiet)
    artifacts: dict = field(default_factory=dict)      # Renaissance: Artifact name -> index of the player holding it (None: nobody); only those in the game
    played_log: list = field(default_factory=list)     # Renaissance: cards played this turn, in order (Scepter replays one of them)
    fleet_queue: Optional[list] = None                 # Renaissance: players still to take their Fleet turn once the game has ended (None: no Fleet round yet)
    star_draws: list = field(default_factory=list)     # Renaissance: [player, cards still to draw] waiting for a Star Chart choice after a shuffle
    reveal_scan: int = 0                               # Renaissance: log lines before this one were already checked for revealed Patrons
    ways: tuple = ()                  # Menagerie: the Ways in this game (each Action played may use one instead of its own effect)
    mouse: Optional[str] = None       # Menagerie: the unused Action card (costing $2 or $3) that Way of the Mouse plays
    last_gain: Optional[str] = None   # Menagerie: the last card (other than a Wayfarer) gained this turn by anyone (Wayfarer's cost)
    no_more_actions: bool = False     # Menagerie: Snowy Village: ignore further +Actions this turn
    frogged: list = field(default_factory=list)       # Menagerie: cards played with Way of the Frog this turn (put onto the deck when discarded from play)
    gatekeepers: list = field(default_factory=list)   # Menagerie: (owner, target) pairs: target is under owner's Gatekeeper until the owner's next turn
    discard_events: list = field(default_factory=list)   # Menagerie: (player, card) Village Greens discarded other than in Clean-up, waiting to be played
    ally: Optional[str] = None        # Allies: the Ally of this game (only when a Liaison is in the Kingdom)
    pile_tokens: dict = field(default_factory=dict)   # Allies: Family of Inventors: pile name -> Favor tokens on it (each makes its cards cost $1 less)
    shuffles: int = 0                 # Allies: how many times a deck was reshuffled (Emissary asks whether its draw made you shuffle)
    highwaymen: list = field(default_factory=list)    # Allies: (owner, target): the target's first Treasure each turn does nothing until the owner's next turn
    warlords: list = field(default_factory=list)      # Allies: (owner, target): the target cannot play an Action they have 2+ copies of in play
    skirmishers: list = field(default_factory=list)   # Allies: (owner, target) for this turn: target discards down to 3 when owner gains an Attack
    voyage_flag: bool = False         # the extra turn that is coming is a Voyage turn (only 3 cards from the hand)
    voyage_turn: bool = False         # the current turn is a Voyage turn
    voyage_next: bool = False         # the next turn (an extra turn that is about to start) is a Voyage turn
    hand_plays: int = 0               # cards played from the hand this turn (Voyage)
    elder_cards: list = field(default_factory=list)   # Allies: cards Elder is playing right now (they get an extra choice)
    traits: dict = field(default_factory=dict)        # Plunder: Kingdom pile -> the Trait lying on it
    loot: list = field(default_factory=list)          # Plunder: the Loot pile, top card first (the counts are also in offsupply)
    shaman: bool = False              # Plunder: Shaman is in the game (everyone gains from the trash at the start of their turn)
    coin_ticks: int = 0               # Plunder: how many times a card gave +$ so far (Harbor Village asks whether an Action did)
    prev_turn: Optional[int] = None   # Plunder: who took the previous turn (Journey)
    seize_flag: bool = False          # Seize the Day was bought this turn
    seize_next: bool = False          # the next turn is the same player's Seize the Day turn
    seize_turn: bool = False          # the current turn is a Seize the Day turn (it does not count as a turn taken, and no third turn in a row)
    mission_flag: bool = False        # Mission was bought this turn
    mission_next: bool = False        # the next turn is the same player's Mission turn
    mission_turn: bool = False        # the current turn is a Mission turn (no third turn in a row)
    possession_aside: list = field(default_factory=list)   # the possessed player's cards trashed this turn (they come back)
    resigned: list = field(default_factory=list)  # players who resigned (they cannot win)
    end_reason: Optional[str] = None  # why the game ended early (resignation / ended by host)
    winners: list = field(default_factory=list)   # player indices, set when finished
    log: GameLog = field(default_factory=GameLog)  # human-readable event history

    def __post_init__(self) -> None:
        self.log.turn_of = lambda: self.turn_number
