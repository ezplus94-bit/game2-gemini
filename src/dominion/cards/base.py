"""Card definitions: pure data plus an optional effect function.

A card definition knows nothing about the engine. Action effects receive an
``EffectContext`` (see ``dominion.engine.effects``) and talk to the game only
through it. Cards are referenced everywhere else by *name* (a string).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional, Sequence


class CardType(str, Enum):
    ACTION = "action"
    TREASURE = "treasure"
    VICTORY = "victory"
    CURSE = "curse"
    ATTACK = "attack"
    REACTION = "reaction"
    PRIZE = "prize"                  # Cornucopia (first edition): not in the Supply, gained with Tournament
    REWARD = "reward"                # Cornucopia & Guilds: not in the Supply, gained with Joust
    DURATION = "duration"            # Seaside: stays in play until the start of its owner's next turn
    CATASTROPHE = "catastrophe"      # optional high-impact house-rule cards
    SPECIAL = "special"              # optional single-use house-rule cards that help a player
    RUINS = "ruins"                  # Dark Ages: the mixed Ruins pile
    LOOTER = "looter"                # Dark Ages: Death Cart, Marauder, Cultist (their Attacks give out Ruins)
    KNIGHT = "knight"                # Dark Ages: the ten Knights share one pile
    SHELTER = "shelter"              # Dark Ages: Hovel, Necropolis, Overgrown Estate replace the starting Estates
    RESERVE = "reserve"              # Adventures: goes to the Tavern mat when played; may be called later
    TRAVELLER = "traveller"          # Adventures: may be exchanged for the next card of its line when discarded from play
    EVENT = "event"                  # Adventures & Empires: bought with a Buy, never gained
    LANDMARK = "landmark"            # Empires: a standing rule for the whole game (VP pools, end-of-game scoring)
    COMMAND = "command"              # Empires: Overlord plays another Action from the Supply
    GATHERING = "gathering"          # Empires: puts VP tokens on its own Supply pile (Temple, Wild Hunt, Farmers' Market)
    CASTLE = "castle"                # Empires: the eight Castles share one pile
    NIGHT = "night"                  # Nocturne: played in the Night phase (after the Buy phase), not in the Action phase
    FATE = "fate"                    # Nocturne: gives out Boons (the Boons are shuffled when a Fate card is in the game)
    DOOM = "doom"                    # Nocturne: gives out Hexes
    SPIRIT = "spirit"                # Nocturne: Will-o'-Wisp, Imp, Ghost (piles outside the Supply)
    ZOMBIE = "zombie"                # Nocturne: the three Zombies that Necromancer plays from the trash
    HEIRLOOM = "heirloom"            # Nocturne: replaces a starting Copper (Haunted Mirror, Goat, Lucky Coin...)
    PROJECT = "project"              # Renaissance: bought with a Buy and its cost in $, a permanent ability for the buyer
    WAY = "way"                      # Menagerie: a standing option for every Action you play (do the Way instead of what the card says)
    ALLY = "ally"                    # Allies: one per game when a Liaison is in the Kingdom; says what Favors can be spent on
    LIAISON = "liaison"              # Allies: gives Favor tokens
    AUGUR = "augur"                  # Allies: the four cards of the Augurs split pile
    CLASH = "clash"                  # Allies: the Clashes
    FORT = "fort"                    # Allies: the Forts
    ODYSSEY = "odyssey"              # Allies: the Odysseys
    TOWNSFOLK = "townsfolk"          # Allies: the Townsfolk
    WIZARD = "wizard"                # Allies: the Wizards
    SHADOW = "shadow"                # Rising Sun: can also be played from the deck during the Action phase; goes to the bottom when shuffled
    OMEN = "omen"                    # Rising Sun: its first line is "+1 Sun"
    PROPHECY = "prophecy"            # Rising Sun: a landscape card with Sun tokens; its rule starts when the last one is gone
    LOOT = "loot"                    # Plunder: the 15 Loot Treasures (a shuffled pile outside the Supply, gained only with cards that say so)
    TRAIT = "trait"                  # Plunder: a landscape card laid on one Action or Treasure Kingdom pile for the whole game


# An effect takes an EffectContext. It is either a plain function (no player
# decisions) or a generator that ``yield``s Decisions and receives the answers.
EffectFn = Callable[[Any], Any]
# A score function receives every card name the player owns.
ScoreFn = Callable[[Sequence[str]], int]
# A coin function receives (GameState, player index) and returns the $ a Treasure is worth when played.
CoinsFn = Callable[[Any, int], int]


@dataclass(frozen=True)
class CardDef:
    name: str
    cost: int
    types: frozenset
    coins: int = 0                       # value when played as a Treasure
    vp: int = 0                          # fixed victory points
    score_fn: Optional[ScoreFn] = None   # variable VP (e.g. Gardens)
    on_play: Optional[EffectFn] = None   # Action effect
    text: str = ""
    kingdom: bool = False                # may be chosen as a Kingdom card
    blocks_attack: bool = False          # Reaction: revealing it makes you unaffected by an Attack
    min_players: int = 1                 # needs at least this many players in the game
    expansion: str = "Base"              # which card set it belongs to (Base, Intrigue, Catastrophe, ...)
    on_attack: Optional[EffectFn] = None  # Reaction with an effect (Diplomat): runs for its owner when revealed
    on_attack_min_hand: int = 0          # ... but only offered when the owner holds at least this many cards
    companions: tuple = ()               # extra piles that come into the game with this card (Exodia's other pieces)
    companion_of: Optional[str] = None   # set on those extra cards: they cannot be picked on their own
    potion_cost: int = 0                 # Alchemy: needs this many Potions on top of the coin cost
    potions: int = 0                     # Potions produced when played as a Treasure (the Potion card)
    coins_fn: Optional[CoinsFn] = None   # Treasure worth a computed number of $ (Philosopher's Stone)
    on_cleanup: Optional[EffectFn] = None  # "when you discard this from play": a generator run during cleanup
    cleanup_order: int = 0               # lower numbers are resolved first when several cards act at cleanup
    on_gain: Optional[EffectFn] = None   # "when you gain this": runs for the gaining player, ``fn(ctx, event)``
    on_gain_in_play: Optional[EffectFn] = None   # "while this is in play, when you gain a card": ``fn(ctx, event)``, once per copy in play
    on_gain_reaction: Optional[EffectFn] = None  # Reaction in hand to a gain (Watchtower): ``fn(ctx, event)``
    can_buy_fn: Optional[Callable] = None        # ``fn(state) -> reason or None``: why this card cannot be bought right now
    cost_mod: Optional[Callable] = None          # ``fn(state) -> int``: coins this card costs less right now (Peddler)
    play_at_turn_start: bool = False             # may be played from the hand at the start of its owner's turn (Clerk)
    overpay: bool = False                        # may be overpaid for when bought (Guilds); the "+" in its cost
    on_overpay: Optional[EffectFn] = None        # "Overpay:" effect, runs when the card is gained after an overpayment: ``fn(ctx, event)``
    cost_aura: int = 0                           # while this is in play, ALL cards cost this many coins less (Princess)
    on_other_gain: Optional[EffectFn] = None     # Reaction in hand to ANOTHER player's gain (Fool's Gold): ``fn(ctx, event)``, ctx.player = the reactor
    gain_replacement: str = ""                   # Reaction in hand: "when you would gain a card", gain this card instead (Trader: Silver)
    on_trash: Optional[EffectFn] = None          # "when you trash this": ``fn(ctx, event)``, ctx.player = the card's owner (Dark Ages)
    on_trash_reaction: Optional[EffectFn] = None  # Reaction in hand to one of its owner's cards being trashed (Market Square): ``fn(ctx, event)``

    call_when: str = ""                          # Adventures Reserve: "start" (of turn), "after_action", "gain" or "buy_end"
    call_cond: Optional[Callable] = None         # ``fn(ctx, arg) -> bool``: may it be called right now?
    call_fn: Optional[EffectFn] = None           # what calling it does: ``fn(ctx, arg)`` (``arg``: the Action just played / the gain event)
    call_prompt: str = ""                        # question shown to the player
    call_discards: bool = False                  # calling it discards it from the mat instead of putting it into play (Wine Merchant)
    on_buy_by_other: Optional[EffectFn] = None   # while in play: when another player buys a card, ``fn(ctx, event)`` (Haunted Woods, Swamp Hag)
    exchange: str = ""                           # Traveller: the card it may be exchanged for when discarded from play
    once_per_turn: bool = False                  # Event: may be bought only once each turn
    debt_cost: int = 0                           # Empires: Debt tokens taken when this is bought (the "D" in a cost)
    heirloom: str = ""                           # Nocturne: the Heirloom that replaces one starting Copper in games using this card
    gains_to_hand: bool = False                  # Nocturne: "this is gained to your hand (instead of your discard pile)"
    hooks: tuple = ()                            # Plunder: (key, fn) pairs, e.g. ("wait", fn): what a Duration waiting for something does when it happens

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("A card needs a name.")
        if self.cost < 0:
            raise ValueError(f"{self.name}: cost cannot be negative.")
        if self.debt_cost < 0:
            raise ValueError(f"{self.name}: debt cost cannot be negative.")
        if self.potion_cost < 0:
            raise ValueError(f"{self.name}: potion cost cannot be negative.")
        if CardType.ACTION in self.types and self.on_play is None:
            raise ValueError(f"{self.name}: Action cards need an on_play effect.")

    def is_type(self, card_type: CardType) -> bool:
        return card_type in self.types

    def victory_points(self, all_cards: Sequence[str]) -> int:
        total = self.vp
        if self.score_fn is not None:
            total += self.score_fn(all_cards)
        return total


def treasure(
    name: str,
    cost: int,
    coins: int,
    potion_cost: int = 0,
    potions: int = 0,
    text: Optional[str] = None,
    coins_fn: Optional[CoinsFn] = None,
    kingdom: bool = False,
    expansion: str = "Base",
    on_play: Optional[EffectFn] = None,
    on_gain: Optional[EffectFn] = None,
    on_gain_in_play: Optional[EffectFn] = None,
    can_buy_fn: Optional[Callable] = None,
    overpay: bool = False,
    on_overpay: Optional[EffectFn] = None,
) -> CardDef:
    """A Treasure. ``on_play`` is a Treasure's extra effect (run when it is played in the Buy phase)."""
    return CardDef(
        name, cost, frozenset({CardType.TREASURE}), coins=coins, on_play=on_play,
        text=f"${coins}" if text is None else text,
        potion_cost=potion_cost, potions=potions, coins_fn=coins_fn, kingdom=kingdom, expansion=expansion,
        on_gain=on_gain, on_gain_in_play=on_gain_in_play, can_buy_fn=can_buy_fn,
        overpay=overpay, on_overpay=on_overpay,
    )


def victory(
    name: str,
    cost: int,
    vp: int = 0,
    score_fn: Optional[ScoreFn] = None,
    text: str = "",
    kingdom: bool = False,
    expansion: str = "Base",
    potion_cost: int = 0,
) -> CardDef:
    return CardDef(
        name, cost, frozenset({CardType.VICTORY}),
        vp=vp, score_fn=score_fn, text=text or f"{vp} VP", kingdom=kingdom, expansion=expansion,
        potion_cost=potion_cost,
    )


def action(
    name: str,
    cost: int,
    on_play: EffectFn,
    text: str = "",
    kingdom: bool = True,
    extra_types: tuple = (),
    blocks_attack: bool = False,
    min_players: int = 1,
    expansion: str = "Base",
    on_attack: Optional[EffectFn] = None,
    on_attack_min_hand: int = 0,
    potion_cost: int = 0,
    on_cleanup: Optional[EffectFn] = None,
    cleanup_order: int = 0,
    on_gain: Optional[EffectFn] = None,
    on_gain_reaction: Optional[EffectFn] = None,
    can_buy_fn: Optional[Callable] = None,
    cost_mod: Optional[Callable] = None,
    play_at_turn_start: bool = False,
    on_gain_in_play: Optional[EffectFn] = None,
    overpay: bool = False,
    on_overpay: Optional[EffectFn] = None,
    on_trash: Optional[EffectFn] = None,
    on_trash_reaction: Optional[EffectFn] = None,
) -> CardDef:
    """An Action card. ``extra_types`` adds e.g. CardType.ATTACK / REACTION."""
    return CardDef(
        name, cost, frozenset({CardType.ACTION, *extra_types}),
        on_play=on_play, text=text, kingdom=kingdom, blocks_attack=blocks_attack,
        min_players=min_players, expansion=expansion,
        on_attack=on_attack, on_attack_min_hand=on_attack_min_hand,
        potion_cost=potion_cost, on_cleanup=on_cleanup, cleanup_order=cleanup_order,
        on_gain=on_gain, on_gain_reaction=on_gain_reaction, can_buy_fn=can_buy_fn, cost_mod=cost_mod,
        play_at_turn_start=play_at_turn_start, on_gain_in_play=on_gain_in_play,
        overpay=overpay, on_overpay=on_overpay, on_trash=on_trash, on_trash_reaction=on_trash_reaction,
    )


def action_victory(
    name: str, cost: int, on_play: EffectFn, vp: int, text: str = "", expansion: str = "Base",
) -> CardDef:
    """A card that is both an Action and a Victory card (Nobles, Mill)."""
    return CardDef(
        name, cost, frozenset({CardType.ACTION, CardType.VICTORY}),
        vp=vp, on_play=on_play, text=text, kingdom=True, expansion=expansion,
    )


def treasure_victory(name: str, cost: int, coins: int, vp: int, text: str = "", expansion: str = "Base") -> CardDef:
    """A card that is both a Treasure and a Victory card (Harem)."""
    return CardDef(
        name, cost, frozenset({CardType.TREASURE, CardType.VICTORY}),
        coins=coins, vp=vp, text=text, kingdom=True, expansion=expansion,
    )
