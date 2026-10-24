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
    DURATION = "duration"            # Seaside: stays in play until the start of its owner's next turn
    CATASTROPHE = "catastrophe"      # optional high-impact house-rule cards
    SPECIAL = "special"              # optional single-use house-rule cards that help a player
    # Future: DURATION ...


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

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("A card needs a name.")
        if self.cost < 0:
            raise ValueError(f"{self.name}: cost cannot be negative.")
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
) -> CardDef:
    """A Treasure. ``on_play`` is a Treasure's extra effect (run when it is played in the Buy phase)."""
    return CardDef(
        name, cost, frozenset({CardType.TREASURE}), coins=coins, on_play=on_play,
        text=f"${coins}" if text is None else text,
        potion_cost=potion_cost, potions=potions, coins_fn=coins_fn, kingdom=kingdom, expansion=expansion,
        on_gain=on_gain, on_gain_in_play=on_gain_in_play, can_buy_fn=can_buy_fn,
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
