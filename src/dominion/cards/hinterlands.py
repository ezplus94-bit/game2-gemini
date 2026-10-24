"""Dominion: Hinterlands (2011 / 2nd Edition 2022) card implementations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


EXPANSION_NAME = "Hinterlands"
EXPANSION_ID = "hinterlands"
EXPANSION_YEAR = "2011 / 2nd Edition 2022"


@dataclass
class HinterlandsCardSpec:
    """Specification and effect handlers for a Hinterlands card."""

    name: str
    cost: int
    types: tuple[str, ...]
    edition: str  # "2E", "1E", or "Both"
    text: str
    vp: int = 0
    coins: int = 0
    cards: int = 0
    actions: int = 0
    buys: int = 0
    pile_size: Optional[int] = None
    on_play: Optional[Callable[[Any, Any], None]] = None
    on_gain: Optional[Callable[[Any, Any, Dict[str, Any]], None]] = None
    on_buy: Optional[Callable[[Any, Any], None]] = None
    on_trash: Optional[Callable[[Any, Any], None]] = None
    on_discard: Optional[Callable[[Any, Any, str], None]] = None
    dynamic_vp: Optional[Callable[[Any], int]] = None

    @property
    def is_victory(self) -> bool:
        return "Victory" in self.types

    @property
    def is_action(self) -> bool:
        return "Action" in self.types

    @property
    def is_treasure(self) -> bool:
        return "Treasure" in self.types

    @property
    def is_reaction(self) -> bool:
        return "Reaction" in self.types

    @property
    def is_attack(self) -> bool:
        return "Attack" in self.types


# ---------------------------------------------------------------------------
# Helper utilities that adapt to the engine's Game / Player / State objects
# ---------------------------------------------------------------------------

def _get_types(card: Any) -> tuple[str, ...]:
    if card is None:
        return ()
    if isinstance(card, str):
        spec = HINTERLANDS_CARDS.get(card)
        if spec:
            return spec.types
        if card in ("Estate", "Duchy", "Province", "Colony", "Farmland", "Tunnel", "Silk Road"):
            return ("Victory",)
        if card in ("Copper", "Silver", "Gold", "Platinum", "Cache", "Fool's Gold", "Ill-Gotten Gains", "Cauldron"):
            return ("Treasure",)
        if card == "Curse":
            return ("Curse",)
        return ("Action",)
    if hasattr(card, "types"):
        t = getattr(card, "types")
        return tuple(t) if isinstance(t, (list, tuple, set)) else (str(t),)
    if hasattr(card, "card_type"):
        return tuple(getattr(card, "card_type"))
    name = getattr(card, "name", str(card))
    return _get_types(name)


def _card_name(card: Any) -> str:
    if isinstance(card, str):
        return card
    return getattr(card, "name", str(card))


def _card_cost(game: Any, card: Any, player: Any = None) -> int:
    if hasattr(game, "get_cost"):
        try:
            return int(game.get_cost(card, player=player))
        except TypeError:
            return int(game.get_cost(card))
    name = _card_name(card)
    base_costs = {
        "Copper": 0, "Curse": 0, "Estate": 2, "Silver": 3, "Duchy": 5, "Gold": 6, "Province": 8, "Platinum": 9, "Colony": 11,
    }
    base = getattr(card, "cost", HINTERLANDS_CARDS[name].cost if name in HINTERLANDS_CARDS else base_costs.get(name, 0))
    discount = 0
    if player is not None:
        in_play = getattr(player, "in_play", getattr(player, "play_area", []))
        discount = sum(1 for c in in_play if _card_name(c) == "Highway")
    elif hasattr(game, "current_player") and game.current_player is not None:
        in_play = getattr(game.current_player, "in_play", getattr(game.current_player, "play_area", []))
        discount = sum(1 for c in in_play if _card_name(c) == "Highway")
    return max(0, int(base) - discount)


def _draw(game: Any, player: Any, count: int = 1) -> List[Any]:
    if hasattr(player, "draw"):
        res = player.draw(count)
        return res if isinstance(res, list) else []
    if hasattr(game, "draw_cards"):
        return game.draw_cards(player, count)
    drawn = []
    deck = getattr(player, "deck", [])
    discard = getattr(player, "discard", getattr(player, "discard_pile", []))
    hand = getattr(player, "hand", [])
    for _ in range(count):
        if not deck and discard:
            deck.extend(discard)
            discard.clear()
        if deck:
            c = deck.pop(0)
            hand.append(c)
            drawn.append(c)
    return drawn


def _add_actions(player: Any, amount: int) -> None:
    if hasattr(player, "actions"):
        player.actions += amount


def _add_buys(player: Any, amount: int) -> None:
    if hasattr(player, "buys"):
        player.buys += amount


def _add_coins(player: Any, amount: int) -> None:
    if hasattr(player, "coins"):
        player.coins = max(0, player.coins + amount)
    elif hasattr(player, "treasure"):
        player.treasure = max(0, player.treasure + amount)


def _other_players(game: Any, player: Any) -> List[Any]:
    players = getattr(game, "players", [])
    return [p for p in players if p is not player]


def _can_be_attacked(game: Any, defender: Any, attacker: Any = None) -> bool:
    """Checks Moat/Lighthouse immunity and triggers Guard Dog reaction if in hand."""
    hand = getattr(defender, "hand", [])
    # Guard Dog reaction: When another player plays an Attack card, you may play this from your hand.
    for idx, c in enumerate(list(hand)):
        if _card_name(c) == "Guard Dog":
            should_play = getattr(defender, "auto_react_guard_dog", True)
            if should_play:
                hand.remove(c)
                in_play = getattr(defender, "in_play", getattr(defender, "play_area", None))
                if isinstance(in_play, list):
                    in_play.append(c)
                play_guard_dog(game, defender)
                break
    # Check standard Attack immunity (e.g. Moat in hand or Lighthouse in play)
    for c in getattr(defender, "hand", []):
        if _card_name(c) == "Moat":
            return False
    for c in getattr(defender, "in_play", getattr(defender, "play_area", [])):
        if _card_name(c) == "Lighthouse":
            return False
    if hasattr(defender, "is_immune_to_attack") and callable(defender.is_immune_to_attack):
        return not defender.is_immune_to_attack()
    return True


def _discard_card(game: Any, player: Any, card: Any, phase: str = "action") -> None:
    """Discards a card from player's hand and fires Hinterlands when-discarded reactions."""
    hand = getattr(player, "hand", [])
    discard = getattr(player, "discard", getattr(player, "discard_pile", []))
    if card in hand:
        hand.remove(card)
    discard.append(card)
    if phase.lower() != "cleanup":
        _trigger_on_discard(game, player, card, phase=phase)


def _trash_card(game: Any, player: Any, card: Any, from_zone: str = "hand") -> None:
    """Trashes a card and triggers Hinterlands when-trashed effects (Nomads, Trail)."""
    zone = getattr(player, from_zone, None)
    if isinstance(zone, list) and card in zone:
        zone.remove(card)
    trash = getattr(game, "trash", getattr(game, "trash_pile", None))
    if isinstance(trash, list):
        trash.append(card)
    _trigger_on_trash(game, player, card)


def _gain_card(
    game: Any,
    player: Any,
    card_name: str,
    destination: str = "discard",
    bought: bool = False,
) -> Optional[Any]:
    """Gains a card from supply, handling Trader replacement, Nomad Camp destination, and on-gain hooks."""
    # 1. Trader Reaction: When you would gain a card, you may reveal Trader from hand to instead gain a Silver.
    if card_name != "Silver":
        hand = getattr(player, "hand", [])
        has_trader = any(_card_name(c) == "Trader" for c in hand)
        if has_trader and getattr(player, "use_trader_reaction", False):
            return _gain_card(game, player, "Silver", destination="discard", bought=False)

    # 2. Check Supply availability
    supply = getattr(game, "supply", {})
    if isinstance(supply, dict):
        if card_name in supply:
            pile = supply[card_name]
            if isinstance(pile, int):
                if pile <= 0:
                    return None
                supply[card_name] = pile - 1
                gained_obj: Any = card_name
            elif isinstance(pile, list):
                if not pile:
                    return None
                gained_obj = pile.pop(0)
            else:
                gained_obj = card_name
        else:
            gained_obj = card_name
    else:
        gained_obj = card_name

    # Nomad Camp is always gained onto deck by default
    if card_name == "Nomad Camp" and destination == "discard":
        destination = "deck"

    # 3. Put card in destination zone
    if destination == "hand":
        getattr(player, "hand", []).append(gained_obj)
    elif destination == "deck":
        getattr(player, "deck", []).insert(0, gained_obj)
    else:
        discard = getattr(player, "discard", getattr(player, "discard_pile", []))
        discard.append(gained_obj)

    # 4. Track turn action gains (for Cauldron)
    if "Action" in _get_types(gained_obj):
        actions_gained = getattr(player, "actions_gained_this_turn", 0) + 1
        player.actions_gained_this_turn = actions_gained
        in_play = getattr(player, "in_play", getattr(player, "play_area", []))
        cauldrons_active = getattr(player, "cauldrons_played_this_turn", sum(1 for c in in_play if _card_name(c) == "Cauldron"))
        if actions_gained == 3 and cauldrons_active > 0:
            for _ in range(cauldrons_active):
                for opp in _other_players(game, player):
                    if _can_be_attacked(game, opp, player):
                        _gain_card(game, opp, "Curse")

    # 5. Trigger on-buy hooks (Haggler, Farmland 1E, Noble Brigand)
    if bought:
        _trigger_on_buy(game, player, gained_obj)

    # 6. Trigger on-gain hooks (card's own + global Duchess / Fool's Gold)
    _trigger_on_gain(game, player, gained_obj, bought=bought)
    return gained_obj


def _play_card_effect(game: Any, player: Any, card: Any, from_zone: Optional[str] = None) -> None:
    """Moves `card` to `player.in_play` (if not already there) and executes its on_play handler."""
    if from_zone == "discard":
        discard = getattr(player, "discard", getattr(player, "discard_pile", []))
        if card in discard:
            discard.remove(card)
    elif from_zone == "trash":
        trash = getattr(game, "trash", getattr(game, "trash_pile", []))
        if card in trash:
            trash.remove(card)
    elif from_zone == "hand":
        hand = getattr(player, "hand", [])
        if card in hand:
            hand.remove(card)

    in_play = getattr(player, "in_play", getattr(player, "play_area", None))
    if isinstance(in_play, list) and card not in in_play:
        in_play.append(card)

    spec = HINTERLANDS_CARDS.get(_card_name(card))
    if spec and spec.on_play:
        spec.on_play(game, player)


def _trigger_on_discard(game: Any, player: Any, card: Any, phase: str = "action") -> None:
    if phase.lower() == "cleanup":
        return
    name = _card_name(card)
    spec = HINTERLANDS_CARDS.get(name)
    if spec and spec.on_discard:
        spec.on_discard(game, player, phase)


def _trigger_on_trash(game: Any, player: Any, card: Any) -> None:
    name = _card_name(card)
    spec = HINTERLANDS_CARDS.get(name)
    if spec and spec.on_trash:
        spec.on_trash(game, player)


def _trigger_on_buy(game: Any, player: Any, card: Any) -> None:
    name = _card_name(card)
    spec = HINTERLANDS_CARDS.get(name)
    if spec and spec.on_buy:
        spec.on_buy(game, player)

    # Haggler in play: While this is in play, when you buy a card, gain a cheaper non-Victory card.
    in_play = getattr(player, "in_play", getattr(player, "play_area", []))
    hagglers = [c for c in in_play if _card_name(c) == "Haggler"]
    if hagglers:
        bought_cost = _card_cost(game, card, player)
        for _ in hagglers:
            choice = getattr(player, "haggler_gain_choice", None)
            if not choice:
                choice = _choose_cheaper_card(game, player, bought_cost, non_victory=True)
            if choice and _card_cost(game, choice, player) < bought_cost and "Victory" not in _get_types(choice):
                _gain_card(game, player, choice)


def _trigger_on_gain(game: Any, player: Any, card: Any, bought: bool = False) -> None:
    name = _card_name(card)
    spec = HINTERLANDS_CARDS.get(name)
    if spec and spec.on_gain:
        spec.on_gain(game, player, {"card": card, "bought": bought})

    # Global trigger: When you gain a Duchy, if Duchess is in the Supply, you may gain a Duchess.
    if name == "Duchy":
        supply = getattr(game, "supply", {})
        if "Duchess" in supply and getattr(player, "gain_duchess_on_duchy", True):
            _gain_card(game, player, "Duchess")

    # Global trigger: When another player gains a Province, players with Fool's Gold in hand may trash it to gain a Gold onto deck.
    if name == "Province":
        for opp in _other_players(game, player):
            hand = getattr(opp, "hand", [])
            fools_golds = [c for c in list(hand) if _card_name(c) == "Fool's Gold"]
            if fools_golds and getattr(opp, "react_fools_gold", True):
                fg = fools_golds[0]
                _trash_card(game, opp, fg, from_zone="hand")
                _gain_card(game, opp, "Gold", destination="deck")


def _choose_cheaper_card(
    game: Any,
    player: Any,
    max_cost_exclusive: int,
    non_victory: bool = False,
    exact_cost: Optional[int] = None,
    action_only: bool = False,
    up_to_inclusive: Optional[int] = None,
    exclude_name: Optional[str] = None,
) -> Optional[str]:
    supply = getattr(game, "supply", {})
    candidates: List[str] = []
    names = list(supply.keys()) if isinstance(supply, dict) and supply else ["Silver", "Copper", "Estate", "Duchy"]
    for cname in names:
        if isinstance(supply, dict) and cname in supply:
            pile = supply[cname]
            if (isinstance(pile, int) and pile <= 0) or (isinstance(pile, list) and not pile):
                continue
        if exclude_name and cname == exclude_name:
            continue
        cost = _card_cost(game, cname, player)
        types = _get_types(cname)
        if non_victory and "Victory" in types:
            continue
        if action_only and "Action" not in types:
            continue
        if exact_cost is not None:
            if cost == exact_cost:
                candidates.append(cname)
        elif up_to_inclusive is not None:
            if cost <= up_to_inclusive:
                candidates.append(cname)
        else:
            if cost < max_cost_exclusive:
                candidates.append(cname)
    if not candidates:
        return None
    candidates.sort(key=lambda c: _card_cost(game, c, player), reverse=True)
    return candidates[0]


# ---------------------------------------------------------------------------
# Individual Card Handlers (26 Second Edition + 9 First Edition = 35 Cards)
# ---------------------------------------------------------------------------

# --- 1. Crossroads ($2, Action) ---
def play_crossroads(game: Any, player: Any) -> None:
    hand = getattr(player, "hand", [])
    victory_count = sum(1 for c in hand if "Victory" in _get_types(c))
    if victory_count > 0:
        _draw(game, player, victory_count)
    played_count = getattr(player, "crossroads_played_this_turn", 0) + 1
    player.crossroads_played_this_turn = played_count
    if played_count == 1:
        _add_actions(player, 3)


# --- 2. Fool's Gold ($2, Treasure - Reaction) ---
def play_fools_gold(game: Any, player: Any) -> None:
    count = getattr(player, "fools_gold_played_this_turn", 0) + 1
    player.fools_gold_played_this_turn = count
    if count == 1:
        _add_coins(player, 1)
    else:
        _add_coins(player, 4)


# --- 3. Develop ($3, Action) ---
def play_develop(game: Any, player: Any) -> None:
    hand = getattr(player, "hand", [])
    if not hand:
        return
    target = getattr(player, "develop_trash_choice", hand[0])
    if target not in hand:
        target = hand[0]
    trashed_cost = _card_cost(game, target, player)
    _trash_card(game, player, target, from_zone="hand")

    higher = getattr(player, "develop_high_choice", None) or _choose_cheaper_card(
        game, player, 99, exact_cost=trashed_cost + 1
    )
    lower = getattr(player, "develop_low_choice", None) or _choose_cheaper_card(
        game, player, 99, exact_cost=max(0, trashed_cost - 1)
    )
    if higher and _card_cost(game, higher, player) == trashed_cost + 1:
        _gain_card(game, player, higher, destination="deck")
    if lower and trashed_cost - 1 >= 0 and _card_cost(game, lower, player) == trashed_cost - 1:
        _gain_card(game, player, lower, destination="deck")


# --- 4. Guard Dog ($3, Action - Reaction, 2E) ---
def play_guard_dog(game: Any, player: Any) -> None:
    _draw(game, player, 2)
    hand = getattr(player, "hand", [])
    if len(hand) <= 5:
        _draw(game, player, 2)


# --- 5. Oasis ($3, Action) ---
def play_oasis(game: Any, player: Any) -> None:
    _draw(game, player, 1)
    _add_actions(player, 1)
    _add_coins(player, 1)
    hand = getattr(player, "hand", [])
    if hand:
        to_discard = getattr(player, "discard_choice", hand[-1])
        if to_discard not in hand:
            to_discard = hand[-1]
        _discard_card(game, player, to_discard, phase="action")


# --- 6. Scheme ($3, Action) ---
def play_scheme(game: Any, player: Any) -> None:
    _draw(game, player, 1)
    _add_actions(player, 1)
    player.schemes_active_this_turn = getattr(player, "schemes_active_this_turn", 0) + 1


# --- 7. Tunnel ($3, Victory - Reaction, 2 VP) ---
def discard_tunnel(game: Any, player: Any, phase: str) -> None:
    if phase.lower() != "cleanup" and getattr(player, "react_tunnel", True):
        _gain_card(game, player, "Gold")


# --- 8. Jack of All Trades ($4, Action) ---
def play_jack_of_all_trades(game: Any, player: Any) -> None:
    _gain_card(game, player, "Silver")
    deck = getattr(player, "deck", [])
    discard = getattr(player, "discard", getattr(player, "discard_pile", []))
    if not deck and discard:
        deck.extend(discard)
        discard.clear()
    if deck:
        top = deck[0]
        if getattr(player, "jack_discard_top", False):
            deck.pop(0)
            discard.append(top)
            _trigger_on_discard(game, player, top, phase="action")
    hand = getattr(player, "hand", [])
    while len(hand) < 5:
        drawn = _draw(game, player, 1)
        if not drawn:
            break
    non_treasures = [c for c in hand if "Treasure" not in _get_types(c)]
    if non_treasures and getattr(player, "jack_trash_non_treasure", True):
        choice = getattr(player, "jack_trash_choice", None)
        if choice not in non_treasures:
            # Prefer trashing Curse or Estate by default
            curses_estates = [c for c in non_treasures if _card_name(c) in ("Curse", "Estate")]
            choice = curses_estates[0] if curses_estates else None
        if choice is not None:
            _trash_card(game, player, choice, from_zone="hand")


# --- 9. Nomads ($4, Action, 2E) ---
def play_nomads(game: Any, player: Any) -> None:
    _add_buys(player, 1)
    _add_coins(player, 2)


def gain_or_trash_nomads(game: Any, player: Any, *_args: Any) -> None:
    _add_coins(player, 2)


# --- 10. Spice Merchant ($4, Action) ---
def play_spice_merchant(game: Any, player: Any) -> None:
    hand = getattr(player, "hand", [])
    treasures = [c for c in hand if "Treasure" in _get_types(c)]
    if not treasures or not getattr(player, "spice_merchant_trash", True):
        return
    target = getattr(player, "spice_merchant_trash_choice", treasures[0])
    if target not in treasures:
        target = treasures[0]
    _trash_card(game, player, target, from_zone="hand")
    mode = getattr(player, "spice_merchant_mode", "cards_action")
    if mode == "buy_coins":
        _add_buys(player, 1)
        _add_coins(player, 2)
    else:
        _draw(game, player, 2)
        _add_actions(player, 1)


# --- 11. Trader ($4, Action - Reaction) ---
def play_trader(game: Any, player: Any) -> None:
    hand = getattr(player, "hand", [])
    if not hand:
        return
    target = getattr(player, "trader_trash_choice", hand[0])
    if target not in hand:
        target = hand[0]
    cost = _card_cost(game, target, player)
    _trash_card(game, player, target, from_zone="hand")
    for _ in range(cost):
        _gain_card(game, player, "Silver")


# --- 12. Trail ($4, Action - Reaction, 2E) ---
def play_trail(game: Any, player: Any) -> None:
    _draw(game, player, 1)
    _add_actions(player, 1)


def react_trail_from_zone(game: Any, player: Any, card: Any, zone: str) -> None:
    if getattr(player, "react_trail", True):
        _play_card_effect(game, player, card, from_zone=zone)


def gain_trail(game: Any, player: Any, ctx: Dict[str, Any]) -> None:
    react_trail_from_zone(game, player, ctx.get("card", "Trail"), "discard")


def trash_trail(game: Any, player: Any) -> None:
    react_trail_from_zone(game, player, "Trail", "trash")


def discard_trail(game: Any, player: Any, phase: str) -> None:
    if phase.lower() != "cleanup":
        react_trail_from_zone(game, player, "Trail", "discard")


# --- 13. Weaver ($4, Action - Reaction, 2E) ---
def play_weaver(game: Any, player: Any) -> None:
    mode = getattr(player, "weaver_mode", "silvers")
    if mode == "card" or getattr(player, "weaver_gain_choice", None):
        choice = getattr(player, "weaver_gain_choice", None) or _choose_cheaper_card(
            game, player, 5, up_to_inclusive=4
        )
        if choice and _card_cost(game, choice, player) <= 4:
            _gain_card(game, player, choice)
            return
    _gain_card(game, player, "Silver")
    _gain_card(game, player, "Silver")


def discard_weaver(game: Any, player: Any, phase: str) -> None:
    if phase.lower() != "cleanup" and getattr(player, "react_weaver", True):
        _play_card_effect(game, player, "Weaver", from_zone="discard")


# --- 14. Berserker ($5, Action - Attack, 2E) ---
def play_berserker(game: Any, player: Any) -> None:
    berserker_cost = _card_cost(game, "Berserker", player)
    choice = getattr(player, "berserker_gain_choice", None) or _choose_cheaper_card(
        game, player, berserker_cost
    )
    if choice and _card_cost(game, choice, player) < berserker_cost:
        _gain_card(game, player, choice)

    for opp in _other_players(game, player):
        if _can_be_attacked(game, opp, player):
            opp_hand = getattr(opp, "hand", [])
            while len(opp_hand) > 3:
                _discard_card(game, opp, opp_hand[-1], phase="attack")


def gain_berserker(game: Any, player: Any, ctx: Dict[str, Any]) -> None:
    in_play = getattr(player, "in_play", getattr(player, "play_area", []))
    has_action_in_play = any("Action" in _get_types(c) for c in in_play)
    if has_action_in_play:
        card_obj = ctx.get("card", "Berserker")
        _play_card_effect(game, player, card_obj, from_zone="discard")


# --- 15. Cartographer ($5, Action) ---
def play_cartographer(game: Any, player: Any) -> None:
    _draw(game, player, 1)
    _add_actions(player, 1)
    deck = getattr(player, "deck", [])
    discard = getattr(player, "discard", getattr(player, "discard_pile", []))
    if len(deck) < 4 and discard:
        deck.extend(discard)
        discard.clear()
    looked = []
    for _ in range(min(4, len(deck))):
        looked.append(deck.pop(0))
    to_discard_names = getattr(player, "cartographer_discard_names", {"Curse", "Estate", "Tunnel", "Trail", "Weaver"})
    kept = []
    for c in looked:
        if _card_name(c) in to_discard_names:
            discard.append(c)
            _trigger_on_discard(game, player, c, phase="action")
        else:
            kept.append(c)
    for c in reversed(kept):
        deck.insert(0, c)


# --- 16. Cauldron ($5, Treasure - Attack, 2E) ---
def play_cauldron(game: Any, player: Any) -> None:
    _add_coins(player, 2)
    _add_buys(player, 1)
    player.cauldrons_played_this_turn = getattr(player, "cauldrons_played_this_turn", 0) + 1


# --- 17. Haggler ($5, Action) ---
def play_haggler(game: Any, player: Any) -> None:
    _add_coins(player, 2)


# --- 18. Highway ($5, Action) ---
def play_highway(game: Any, player: Any) -> None:
    _draw(game, player, 1)
    _add_actions(player, 1)


# --- 19. Inn ($5, Action) ---
def play_inn(game: Any, player: Any) -> None:
    _draw(game, player, 2)
    _add_actions(player, 2)
    hand = getattr(player, "hand", [])
    for _ in range(min(2, len(hand))):
        _discard_card(game, player, hand[-1], phase="action")


def gain_inn(game: Any, player: Any, _ctx: Dict[str, Any]) -> None:
    discard = getattr(player, "discard", getattr(player, "discard_pile", []))
    deck = getattr(player, "deck", [])
    action_cards = [c for c in list(discard) if "Action" in _get_types(c)]
    for c in action_cards:
        discard.remove(c)
        deck.append(c)


# --- 20. Margrave ($5, Action - Attack) ---
def play_margrave(game: Any, player: Any) -> None:
    _draw(game, player, 3)
    _add_buys(player, 1)
    for opp in _other_players(game, player):
        if _can_be_attacked(game, opp, player):
            _draw(game, opp, 1)
            opp_hand = getattr(opp, "hand", [])
            while len(opp_hand) > 3:
                _discard_card(game, opp, opp_hand[-1], phase="attack")


# --- 21. Souk ($5, Action, 2E) ---
def play_souk(game: Any, player: Any) -> None:
    _add_buys(player, 1)
    _add_coins(player, 7)
    hand_size = len(getattr(player, "hand", []))
    _add_coins(player, -hand_size)


def gain_souk(game: Any, player: Any, _ctx: Dict[str, Any]) -> None:
    hand = getattr(player, "hand", [])
    choices = getattr(player, "souk_trash_choices", None)
    if choices is not None:
        for c in list(choices)[:2]:
            if c in hand:
                _trash_card(game, player, c, from_zone="hand")
    else:
        junk = [c for c in list(hand) if _card_name(c) in ("Curse", "Estate", "Copper")][:2]
        for c in junk:
            _trash_card(game, player, c, from_zone="hand")


# --- 22. Stables ($5, Action) ---
def play_stables(game: Any, player: Any) -> None:
    hand = getattr(player, "hand", [])
    treasures = [c for c in hand if "Treasure" in _get_types(c)]
    if treasures and getattr(player, "stables_discard_treasure", True):
        # Prefer discarding fewest-coin treasure (e.g. Copper)
        treasures.sort(key=lambda c: _card_cost(game, c, player))
        chosen = getattr(player, "stables_discard_choice", treasures[0])
        if chosen not in treasures:
            chosen = treasures[0]
        _discard_card(game, player, chosen, phase="action")
        _draw(game, player, 3)
        _add_actions(player, 1)


# --- 23. Wheelwright ($5, Action, 2E) ---
def play_wheelwright(game: Any, player: Any) -> None:
    _draw(game, player, 1)
    _add_actions(player, 1)
    hand = getattr(player, "hand", [])
    if not hand or not getattr(player, "wheelwright_discard", True):
        return
    to_discard = getattr(player, "wheelwright_discard_choice", hand[-1])
    if to_discard not in hand:
        to_discard = hand[-1]
    max_cost = _card_cost(game, to_discard, player)
    _discard_card(game, player, to_discard, phase="action")
    gain_choice = getattr(player, "wheelwright_gain_choice", None) or _choose_cheaper_card(
        game, player, max_cost + 1, action_only=True, up_to_inclusive=max_cost
    )
    if gain_choice and "Action" in _get_types(gain_choice) and _card_cost(game, gain_choice, player) <= max_cost:
        _gain_card(game, player, gain_choice)


# --- 24. Witch's Hut ($5, Action - Attack, 2E) ---
def play_witchs_hut(game: Any, player: Any) -> None:
    _draw(game, player, 4)
    hand = getattr(player, "hand", [])
    discarded: List[Any] = []
    choices = getattr(player, "witchs_hut_discard_choices", None)
    if choices:
        for c in list(choices)[:2]:
            if c in hand:
                discarded.append(c)
                _discard_card(game, player, c, phase="action")
    while len(discarded) < 2 and hand:
        c = hand[-1]
        discarded.append(c)
        _discard_card(game, player, c, phase="action")

    if len(discarded) == 2 and all("Action" in _get_types(c) for c in discarded):
        for opp in _other_players(game, player):
            if _can_be_attacked(game, opp, player):
                _gain_card(game, opp, "Curse")


# --- 25. Border Village ($6, Action) ---
def play_border_village(game: Any, player: Any) -> None:
    _draw(game, player, 1)
    _add_actions(player, 2)


def gain_border_village(game: Any, player: Any, _ctx: Dict[str, Any]) -> None:
    bv_cost = _card_cost(game, "Border Village", player)
    choice = getattr(player, "border_village_gain_choice", None) or _choose_cheaper_card(
        game, player, bv_cost
    )
    if choice and _card_cost(game, choice, player) < bv_cost:
        _gain_card(game, player, choice)


# --- 26. Farmland ($6, Victory, 2 VP) ---
def gain_or_buy_farmland(game: Any, player: Any, _ctx: Optional[Dict[str, Any]] = None) -> None:
    hand = getattr(player, "hand", [])
    if not hand:
        return
    target = getattr(player, "farmland_trash_choice", hand[0])
    if target not in hand:
        target = hand[0]
    exact_target_cost = _card_cost(game, target, player) + 2
    _trash_card(game, player, target, from_zone="hand")
    gain_choice = getattr(player, "farmland_gain_choice", None) or _choose_cheaper_card(
        game, player, 99, exact_cost=exact_target_cost, exclude_name="Farmland"
    )
    if gain_choice and gain_choice != "Farmland" and _card_cost(game, gain_choice, player) == exact_target_cost:
        _gain_card(game, player, gain_choice)


# ---------------------------------------------------------------------------
# First Edition Legacy Cards (9 Cards from 2011)
# ---------------------------------------------------------------------------

# --- 27. Duchess ($2, Action, 1E) ---
def play_duchess(game: Any, player: Any) -> None:
    _add_coins(player, 2)
    for p in [player] + _other_players(game, player):
        deck = getattr(p, "deck", [])
        discard = getattr(p, "discard", getattr(p, "discard_pile", []))
        if not deck and discard:
            deck.extend(discard)
            discard.clear()
        if deck and getattr(p, "duchess_discard_top", False):
            c = deck.pop(0)
            discard.append(c)
            _trigger_on_discard(game, p, c, phase="action")


# --- 28. Oracle ($3, Action - Attack, 1E) ---
def play_oracle(game: Any, player: Any) -> None:
    for p in [player] + _other_players(game, player):
        if p is not player and not _can_be_attacked(game, p, player):
            continue
        deck = getattr(p, "deck", [])
        discard = getattr(p, "discard", getattr(p, "discard_pile", []))
        if len(deck) < 2 and discard:
            deck.extend(discard)
            discard.clear()
        revealed = [deck.pop(0) for _ in range(min(2, len(deck)))]
        should_discard = getattr(player, "oracle_discard_choice", p is not player)
        if should_discard:
            for c in revealed:
                discard.append(c)
                _trigger_on_discard(game, p, c, phase="action")
        else:
            for c in reversed(revealed):
                deck.insert(0, c)
    _draw(game, player, 2)


# --- 29. Noble Brigand ($4, Action - Attack, 1E) ---
def _resolve_noble_brigand_attack(game: Any, player: Any) -> None:
    for opp in _other_players(game, player):
        if not _can_be_attacked(game, opp, player):
            continue
        deck = getattr(opp, "deck", [])
        discard = getattr(opp, "discard", getattr(opp, "discard_pile", []))
        if len(deck) < 2 and discard:
            deck.extend(discard)
            discard.clear()
        revealed = [deck.pop(0) for _ in range(min(2, len(deck)))]
        had_treasure = any("Treasure" in _get_types(c) for c in revealed)
        stealable = [c for c in revealed if _card_name(c) in ("Silver", "Gold")]
        if stealable:
            # Prefer stealing Gold over Silver
            stealable.sort(key=lambda c: 2 if _card_name(c) == "Gold" else 1, reverse=True)
            stolen = stealable[0]
            revealed.remove(stolen)
            _trash_card(game, opp, stolen, from_zone="revealed")
            trash = getattr(game, "trash", getattr(game, "trash_pile", []))
            if stolen in trash:
                trash.remove(stolen)
            getattr(player, "discard", getattr(player, "discard_pile", [])).append(stolen)
        for c in revealed:
            discard.append(c)
            _trigger_on_discard(game, opp, c, phase="attack")
        if not had_treasure:
            _gain_card(game, opp, "Copper")


def play_noble_brigand(game: Any, player: Any) -> None:
    _add_coins(player, 1)
    _resolve_noble_brigand_attack(game, player)


def buy_noble_brigand(game: Any, player: Any) -> None:
    _resolve_noble_brigand_attack(game, player)


# --- 30. Nomad Camp ($4, Action, 1E) ---
def play_nomad_camp(game: Any, player: Any) -> None:
    _add_buys(player, 1)
    _add_coins(player, 2)


# --- 31. Silk Road ($4, Victory, 1E) ---
def score_silk_road(player: Any) -> int:
    all_cards: List[Any] = []
    for zone_name in ("hand", "deck", "discard", "discard_pile", "in_play", "play_area"):
        z = getattr(player, zone_name, None)
        if isinstance(z, list):
            all_cards.extend(z)
    # Deduplicate if discard and discard_pile alias the same list
    seen_ids = set()
    unique_zones: List[Any] = []
    for attr in ("hand", "deck", "discard", "discard_pile", "in_play", "play_area"):
        z = getattr(player, attr, None)
        if isinstance(z, list) and id(z) not in seen_ids:
            seen_ids.add(id(z))
            unique_zones.extend(z)
    victory_cards = sum(1 for c in unique_zones if "Victory" in _get_types(c))
    return victory_cards // 4


# --- 32. Cache ($5, Treasure, 1E) ---
def play_cache(game: Any, player: Any) -> None:
    _add_coins(player, 3)


def gain_cache(game: Any, player: Any, _ctx: Dict[str, Any]) -> None:
    _gain_card(game, player, "Copper")
    _gain_card(game, player, "Copper")


# --- 33. Embassy ($5, Action, 1E) ---
def play_embassy(game: Any, player: Any) -> None:
    _draw(game, player, 5)
    hand = getattr(player, "hand", [])
    for _ in range(min(3, len(hand))):
        _discard_card(game, player, hand[-1], phase="action")


def gain_embassy(game: Any, player: Any, _ctx: Dict[str, Any]) -> None:
    for opp in _other_players(game, player):
        _gain_card(game, opp, "Silver")


# --- 34. Ill-Gotten Gains ($5, Treasure, 1E) ---
def play_ill_gotten_gains(game: Any, player: Any) -> None:
    _add_coins(player, 1)
    if getattr(player, "igg_gain_copper", False):
        _gain_card(game, player, "Copper", destination="hand")


def gain_ill_gotten_gains(game: Any, player: Any, _ctx: Dict[str, Any]) -> None:
    for opp in _other_players(game, player):
        _gain_card(game, opp, "Curse")


# --- 35. Mandarin ($5, Action, 1E) ---
def play_mandarin(game: Any, player: Any) -> None:
    _add_coins(player, 3)
    hand = getattr(player, "hand", [])
    deck = getattr(player, "deck", [])
    if hand:
        choice = getattr(player, "mandarin_topdeck_choice", hand[-1])
        if choice not in hand:
            choice = hand[-1]
        hand.remove(choice)
        deck.insert(0, choice)


def gain_mandarin(game: Any, player: Any, _ctx: Dict[str, Any]) -> None:
    in_play = getattr(player, "in_play", getattr(player, "play_area", []))
    deck = getattr(player, "deck", [])
    treasures_in_play = [c for c in list(in_play) if "Treasure" in _get_types(c)]
    for t in treasures_in_play:
        in_play.remove(t)
        deck.insert(0, t)


# ---------------------------------------------------------------------------
# Master Registry of Hinterlands Cards
# ---------------------------------------------------------------------------

HINTERLANDS_CARDS: Dict[str, HinterlandsCardSpec] = {
    # --- 17 Cards in Both 1st and 2nd Edition ---
    "Crossroads": HinterlandsCardSpec(
        name="Crossroads",
        cost=2,
        types=("Action",),
        edition="Both",
        text="Reveal your hand. +1 Card per Victory card revealed. If this is the first time you played a Crossroads this turn, +3 Actions.",
        on_play=play_crossroads,
    ),
    "Fool's Gold": HinterlandsCardSpec(
        name="Fool's Gold",
        cost=2,
        types=("Treasure", "Reaction"),
        edition="Both",
        coins=1,
        text="Worth $1 if it's the first time you played a Fool's Gold this turn, otherwise worth $4. --- When another player gains a Province, you may trash this from your hand, to gain a Gold onto your deck.",
        on_play=play_fools_gold,
    ),
    "Develop": HinterlandsCardSpec(
        name="Develop",
        cost=3,
        types=("Action",),
        edition="Both",
        text="Trash a card from your hand. Gain two cards onto your deck, with one costing exactly $1 more than it, and one costing exactly $1 less than it, in either order.",
        on_play=play_develop,
    ),
    "Oasis": HinterlandsCardSpec(
        name="Oasis",
        cost=3,
        types=("Action",),
        edition="Both",
        cards=1,
        actions=1,
        coins=1,
        text="+1 Card, +1 Action, +$1. Discard a card.",
        on_play=play_oasis,
    ),
    "Scheme": HinterlandsCardSpec(
        name="Scheme",
        cost=3,
        types=("Action",),
        edition="Both",
        cards=1,
        actions=1,
        text="+1 Card, +1 Action. This turn, you may put one of your Action cards onto your deck when you discard it from play.",
        on_play=play_scheme,
    ),
    "Tunnel": HinterlandsCardSpec(
        name="Tunnel",
        cost=3,
        types=("Victory", "Reaction"),
        edition="Both",
        vp=2,
        pile_size=12,
        text="2 VP. --- When you discard this other than in Clean-up, you may reveal it to gain a Gold.",
        on_discard=discard_tunnel,
    ),
    "Jack of All Trades": HinterlandsCardSpec(
        name="Jack of All Trades",
        cost=4,
        types=("Action",),
        edition="Both",
        text="Gain a Silver. Look at the top card of your deck; you may discard it. Draw until you have 5 cards in hand. You may trash a non-Treasure card from your hand.",
        on_play=play_jack_of_all_trades,
    ),
    "Spice Merchant": HinterlandsCardSpec(
        name="Spice Merchant",
        cost=4,
        types=("Action",),
        edition="Both",
        text="You may trash a Treasure from your hand to choose one: +2 Cards and +1 Action; or +1 Buy and +$2.",
        on_play=play_spice_merchant,
    ),
    "Trader": HinterlandsCardSpec(
        name="Trader",
        cost=4,
        types=("Action", "Reaction"),
        edition="Both",
        text="Trash a card from your hand. Gain a Silver per $1 it costs. --- When you would gain a card, you may reveal this from your hand, to instead gain a Silver.",
        on_play=play_trader,
    ),
    "Cartographer": HinterlandsCardSpec(
        name="Cartographer",
        cost=5,
        types=("Action",),
        edition="Both",
        cards=1,
        actions=1,
        text="+1 Card, +1 Action. Look at the top 4 cards of your deck. Discard any number of them, then put the rest back in any order.",
        on_play=play_cartographer,
    ),
    "Haggler": HinterlandsCardSpec(
        name="Haggler",
        cost=5,
        types=("Action",),
        edition="Both",
        coins=2,
        text="+$2. --- While this is in play, when you buy a card, gain a cheaper non-Victory card.",
        on_play=play_haggler,
    ),
    "Highway": HinterlandsCardSpec(
        name="Highway",
        cost=5,
        types=("Action",),
        edition="Both",
        cards=1,
        actions=1,
        text="+1 Card, +1 Action. --- While this is in play, cards cost $1 less, but not less than $0.",
        on_play=play_highway,
    ),
    "Inn": HinterlandsCardSpec(
        name="Inn",
        cost=5,
        types=("Action",),
        edition="Both",
        cards=2,
        actions=2,
        text="+2 Cards, +2 Actions. Discard 2 cards. --- When you gain this, look through your discard pile, reveal any number of Action cards from it (which can include this), and shuffle them into your deck.",
        on_play=play_inn,
        on_gain=gain_inn,
    ),
    "Margrave": HinterlandsCardSpec(
        name="Margrave",
        cost=5,
        types=("Action", "Attack"),
        edition="Both",
        cards=3,
        buys=1,
        text="+3 Cards, +1 Buy. Each other player draws a card, then discards down to 3 cards in hand.",
        on_play=play_margrave,
    ),
    "Stables": HinterlandsCardSpec(
        name="Stables",
        cost=5,
        types=("Action",),
        edition="Both",
        text="You may discard a Treasure, for +3 Cards and +1 Action.",
        on_play=play_stables,
    ),
    "Border Village": HinterlandsCardSpec(
        name="Border Village",
        cost=6,
        types=("Action",),
        edition="Both",
        cards=1,
        actions=2,
        text="+1 Card, +2 Actions. --- When you gain this, gain a cheaper card.",
        on_play=play_border_village,
        on_gain=gain_border_village,
    ),
    "Farmland": HinterlandsCardSpec(
        name="Farmland",
        cost=6,
        types=("Victory",),
        edition="Both",
        vp=2,
        pile_size=12,
        text="2 VP. --- When you gain this, trash a card from your hand and gain a non-Farmland card costing exactly $2 more than it.",
        on_gain=gain_or_buy_farmland,
    ),
    # --- 9 New Cards in 2nd Edition (2022) ---
    "Guard Dog": HinterlandsCardSpec(
        name="Guard Dog",
        cost=3,
        types=("Action", "Reaction"),
        edition="2E",
        cards=2,
        text="+2 Cards. If you have 5 or fewer cards in hand, +2 Cards. --- When another player plays an Attack card, you may play this from your hand.",
        on_play=play_guard_dog,
    ),
    "Nomads": HinterlandsCardSpec(
        name="Nomads",
        cost=4,
        types=("Action",),
        edition="2E",
        buys=1,
        coins=2,
        text="+1 Buy, +$2. --- When you gain or trash this, +$2.",
        on_play=play_nomads,
        on_gain=gain_or_trash_nomads,
        on_trash=gain_or_trash_nomads,
    ),
    "Trail": HinterlandsCardSpec(
        name="Trail",
        cost=4,
        types=("Action", "Reaction"),
        edition="2E",
        cards=1,
        actions=1,
        text="+1 Card, +1 Action. --- When you gain, trash, or discard this other than in Clean-up, you may play it.",
        on_play=play_trail,
        on_gain=gain_trail,
        on_trash=trash_trail,
        on_discard=discard_trail,
    ),
    "Weaver": HinterlandsCardSpec(
        name="Weaver",
        cost=4,
        types=("Action", "Reaction"),
        edition="2E",
        text="Gain two Silvers or a card costing up to $4. --- When you discard this other than in Clean-up, you may play it.",
        on_play=play_weaver,
        on_discard=discard_weaver,
    ),
    "Berserker": HinterlandsCardSpec(
        name="Berserker",
        cost=5,
        types=("Action", "Attack"),
        edition="2E",
        text="Gain a card costing less than this. Each other player discards down to 3 cards in hand. --- When you gain this, if you have an Action in play, play this.",
        on_play=play_berserker,
        on_gain=gain_berserker,
    ),
    "Cauldron": HinterlandsCardSpec(
        name="Cauldron",
        cost=5,
        types=("Treasure", "Attack"),
        edition="2E",
        coins=2,
        buys=1,
        text="$2, +1 Buy. The third time you gain an Action this turn, each other player gains a Curse.",
        on_play=play_cauldron,
    ),
    "Souk": HinterlandsCardSpec(
        name="Souk",
        cost=5,
        types=("Action",),
        edition="2E",
        buys=1,
        coins=7,
        text="+1 Buy, +$7, -$1 per card in your hand. --- When you gain this, trash up to 2 cards from your hand.",
        on_play=play_souk,
        on_gain=gain_souk,
    ),
    "Wheelwright": HinterlandsCardSpec(
        name="Wheelwright",
        cost=5,
        types=("Action",),
        edition="2E",
        cards=1,
        actions=1,
        text="+1 Card, +1 Action. You may discard a card to gain an Action card costing as much as it or less.",
        on_play=play_wheelwright,
    ),
    "Witch's Hut": HinterlandsCardSpec(
        name="Witch's Hut",
        cost=5,
        types=("Action", "Attack"),
        edition="2E",
        cards=4,
        text="+4 Cards. Discard 2 cards, revealed. If they are both Actions, each other player gains a Curse.",
        on_play=play_witchs_hut,
    ),
    # --- 9 Removed Cards from 1st Edition (2011) ---
    "Duchess": HinterlandsCardSpec(
        name="Duchess",
        cost=2,
        types=("Action",),
        edition="1E",
        coins=2,
        text="+$2. Each player (including you) looks at the top card of their deck and may discard it. --- In games using this, when you gain a Duchy, you may gain a Duchess.",
        on_play=play_duchess,
    ),
    "Oracle": HinterlandsCardSpec(
        name="Oracle",
        cost=3,
        types=("Action", "Attack"),
        edition="1E",
        cards=2,
        text="Each player (including you) reveals the top 2 cards of their deck, and discards them or puts them back, your choice. They choose the order to return them. Afterwards, +2 Cards.",
        on_play=play_oracle,
    ),
    "Noble Brigand": HinterlandsCardSpec(
        name="Noble Brigand",
        cost=4,
        types=("Action", "Attack"),
        edition="1E",
        coins=1,
        text="+$1. When you buy or play this, each other player reveals the top 2 cards of their deck, trashes a revealed Silver or Gold you choose, discards the rest, and gains a Copper if they didn't reveal a Treasure. You gain the trashed cards.",
        on_play=play_noble_brigand,
        on_buy=buy_noble_brigand,
    ),
    "Nomad Camp": HinterlandsCardSpec(
        name="Nomad Camp",
        cost=4,
        types=("Action",),
        edition="1E",
        buys=1,
        coins=2,
        text="+1 Buy, +$2. This is gained onto your deck (instead of to your discard pile).",
        on_play=play_nomad_camp,
    ),
    "Silk Road": HinterlandsCardSpec(
        name="Silk Road",
        cost=4,
        types=("Victory",),
        edition="1E",
        pile_size=12,
        text="Worth 1 VP for every 4 Victory cards you have (round down).",
        dynamic_vp=score_silk_road,
    ),
    "Cache": HinterlandsCardSpec(
        name="Cache",
        cost=5,
        types=("Treasure",),
        edition="1E",
        coins=3,
        text="$3. --- When you gain this, gain 2 Coppers.",
        on_play=play_cache,
        on_gain=gain_cache,
    ),
    "Embassy": HinterlandsCardSpec(
        name="Embassy",
        cost=5,
        types=("Action",),
        edition="1E",
        cards=5,
        text="+5 Cards. Discard 3 cards. --- When you gain this, each other player gains a Silver.",
        on_play=play_embassy,
        on_gain=gain_embassy,
    ),
    "Ill-Gotten Gains": HinterlandsCardSpec(
        name="Ill-Gotten Gains",
        cost=5,
        types=("Treasure",),
        edition="1E",
        coins=1,
        text="$1. When you play this, you may gain a Copper to your hand. --- When you gain this, each other player gains a Curse.",
        on_play=play_ill_gotten_gains,
        on_gain=gain_ill_gotten_gains,
    ),
    "Mandarin": HinterlandsCardSpec(
        name="Mandarin",
        cost=5,
        types=("Action",),
        edition="1E",
        coins=3,
        text="+$3. Put a card from your hand onto your deck. --- When you gain this, put all Treasures you have in play onto your deck in any order.",
        on_play=play_mandarin,
        on_gain=gain_mandarin,
    ),
}

HINTERLANDS_2E_CARDS: Dict[str, HinterlandsCardSpec] = {
    k: v for k, v in HINTERLANDS_CARDS.items() if v.edition in ("Both", "2E")
}

HINTERLANDS_1E_CARDS: Dict[str, HinterlandsCardSpec] = {
    k: v for k, v in HINTERLANDS_CARDS.items() if v.edition in ("Both", "1E")
}


def get_hinterlands_cards(edition: str = "all") -> Dict[str, HinterlandsCardSpec]:
    if edition == "2E":
        return dict(HINTERLANDS_2E_CARDS)
    if edition == "1E":
        return dict(HINTERLANDS_1E_CARDS)
    return dict(HINTERLANDS_CARDS)


__all__ = [
    "EXPANSION_NAME",
    "EXPANSION_ID",
    "EXPANSION_YEAR",
    "HinterlandsCardSpec",
    "HINTERLANDS_CARDS",
    "HINTERLANDS_2E_CARDS",
    "HINTERLANDS_1E_CARDS",
    "get_hinterlands_cards",
    "_gain_card",
    "_discard_card",
    "_trash_card",
    "_card_cost",
    "_play_card_effect",
]
