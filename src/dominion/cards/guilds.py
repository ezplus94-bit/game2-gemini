"""Dominion: Guilds (2013) & Cornucopia/Guilds 2nd Edition (2024) card implementations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from ..game import Game
    from ..state import PlayerState


EXPANSION_NAME = "Guilds"
EXPANSION_YEAR = 2013
EXPANSION_2E_YEAR = 2024


# ---------------------------------------------------------------------------
# Helper utilities compatible with standard engine primitives
# ---------------------------------------------------------------------------

def _add_coffers(player: Any, amount: int = 1) -> None:
    """Grant Coffers (Coin tokens) to a player, keeping aliases synchronized."""
    current = getattr(player, "coffers", getattr(player, "coin_tokens", 0)) or 0
    new_val = max(0, current + amount)
    player.coffers = new_val
    player.coin_tokens = new_val
    if hasattr(player, "tokens") and isinstance(player.tokens, dict):
        player.tokens["coffers"] = new_val
        player.tokens["coin_tokens"] = new_val


def _spend_coffers(player: Any, amount: int) -> int:
    """Spend up to `amount` Coffers for +$1 each (or for Butcher)."""
    current = getattr(player, "coffers", getattr(player, "coin_tokens", 0)) or 0
    actual = max(0, min(int(amount), current))
    _add_coffers(player, -actual)
    return actual


def _get_card_cost(game: Any, card: Any, player: Any = None) -> int:
    """Resolve effective coin cost of a card or card name."""
    if hasattr(game, "get_cost"):
        try:
            return int(game.get_cost(card, player=player))
        except TypeError:
            return int(game.get_cost(card))
    if hasattr(card, "cost"):
        c = card.cost
        return int(c.coins if hasattr(c, "coins") else c)
    if isinstance(card, str) and hasattr(game, "card_registry"):
        spec = game.card_registry.get(card)
        if spec is not None:
            c = getattr(spec, "cost", 0)
            return int(c.coins if hasattr(c, "coins") else c)
    return 0


def _card_name(card: Any) -> str:
    if isinstance(card, str):
        return card
    return getattr(card, "name", str(card))


def _card_types(card: Any, game: Any = None) -> List[str]:
    if hasattr(card, "types"):
        t = card.types
        return [str(x).lower() for x in (t if isinstance(t, (list, tuple, set)) else [t])]
    if isinstance(card, str) and game is not None and hasattr(game, "card_registry"):
        spec = game.card_registry.get(card)
        if spec is not None and hasattr(spec, "types"):
            return [str(x).lower() for x in spec.types]
    return []


def _is_type(card: Any, type_name: str, game: Any = None) -> bool:
    t_lower = type_name.lower()
    types = _card_types(card, game)
    if t_lower in types:
        return True
    attr = f"is_{t_lower}"
    if hasattr(card, attr):
        val = getattr(card, attr)
        return bool(val() if callable(val) else val)
    return False


def _draw_cards(game: Any, player: Any, count: int) -> List[Any]:
    if hasattr(game, "draw_cards"):
        return game.draw_cards(player, count)
    if hasattr(player, "draw"):
        return player.draw(count)
    drawn = []
    for _ in range(count):
        if not player.deck and player.discard:
            player.deck.extend(player.discard)
            player.discard.clear()
            if hasattr(game, "rng"):
                game.rng.shuffle(player.deck)
        if player.deck:
            c = player.deck.pop(0)
            player.hand.append(c)
            drawn.append(c)
    return drawn


def _reveal_top_cards(game: Any, player: Any, count: int) -> List[Any]:
    if hasattr(game, "reveal_top_cards"):
        return list(game.reveal_top_cards(player, count))
    revealed = []
    for _ in range(count):
        if not player.deck and player.discard:
            player.deck.extend(player.discard)
            player.discard.clear()
            if hasattr(game, "rng"):
                game.rng.shuffle(player.deck)
        if player.deck:
            revealed.append(player.deck.pop(0))
    return revealed


def _trash_card(game: Any, player: Any, card: Any, from_zone: Optional[List[Any]] = None) -> None:
    if from_zone is not None and card in from_zone:
        from_zone.remove(card)
    if hasattr(game, "trash_card"):
        try:
            game.trash_card(player, card, from_zone=None)
            return
        except TypeError:
            game.trash_card(player, card)
            return
    if hasattr(game, "trash"):
        if card not in game.trash:
            game.trash.append(card)


def _gain_card(
    game: Any,
    player: Any,
    card_name: str,
    destination: str = "discard",
) -> Optional[Any]:
    if hasattr(game, "gain_card"):
        try:
            return game.gain_card(player, card_name, destination=destination)
        except TypeError:
            try:
                return game.gain_card(player, card_name, to_zone=destination)
            except TypeError:
                card = game.gain_card(player, card_name)
                if card is not None and destination == "deck":
                    if card in player.discard:
                        player.discard.remove(card)
                        player.deck.insert(0, card)
                elif card is not None and destination == "hand":
                    if card in player.discard:
                        player.discard.remove(card)
                        player.hand.append(card)
                return card
    supply = getattr(game, "supply", {})
    if card_name in supply:
        pile = supply[card_name]
        if isinstance(pile, int):
            if pile <= 0:
                return None
            supply[card_name] = pile - 1
            gained = card_name
        elif isinstance(pile, list):
            if not pile:
                return None
            gained = pile.pop(0)
        else:
            return None
        if destination == "deck":
            player.deck.insert(0, gained)
        elif destination == "hand":
            player.hand.append(gained)
        else:
            player.discard.append(gained)
        return gained
    return None


def _available_supply_cards(
    game: Any,
    player: Any = None,
    exact_cost: Optional[int] = None,
    max_cost: Optional[int] = None,
    strictly_less_than: Optional[int] = None,
    required_type: Optional[str] = None,
) -> List[str]:
    supply = getattr(game, "supply", {})
    results: List[str] = []
    for name, pile in supply.items():
        count = pile if isinstance(pile, int) else len(pile)
        if count <= 0:
            continue
        cost = _get_card_cost(game, name, player=player)
        if exact_cost is not None and cost != exact_cost:
            continue
        if max_cost is not None and cost > max_cost:
            continue
        if strictly_less_than is not None and cost >= strictly_less_than:
            continue
        if required_type is not None and not _is_type(name, required_type, game):
            continue
        results.append(name)
    return results


def _choose_from_options(
    game: Any,
    player: Any,
    prompt: str,
    options: List[Any],
    optional: bool = False,
) -> Any:
    if not options:
        return None
    if hasattr(player, "decisions") and player.decisions:
        dec = player.decisions.pop(0)
        if dec is None and optional:
            return None
        if dec in options:
            return dec
        for opt in options:
            if _card_name(opt) == _card_name(dec):
                return opt
    if hasattr(game, "prompt_choice"):
        try:
            return game.prompt_choice(player, prompt, options, optional=optional)
        except TypeError:
            return game.prompt_choice(player, options)
    return options[0]


# ---------------------------------------------------------------------------
# Individual Guilds (2013 1st Edition) Card Effects & Overpay Hooks
# ---------------------------------------------------------------------------

def play_candlestick_maker(game: Any, player: Any, card: Any = None) -> None:
    """Candlestick Maker ($2, Action): +1 Action, +1 Buy, +1 Coffers."""
    player.actions = getattr(player, "actions", 0) + 1
    player.buys = getattr(player, "buys", 0) + 1
    _add_coffers(player, 1)


def play_stonemason(game: Any, player: Any, card: Any = None) -> None:
    """Stonemason ($2+, Action): Trash a card from hand. Gain 2 cards each costing less than it."""
    if not player.hand:
        return
    to_trash = _choose_from_options(
        game, player, "Choose a card from your hand to trash for Stonemason", list(player.hand)
    )
    if to_trash is None:
        to_trash = player.hand[0]
    trashed_cost = _get_card_cost(game, to_trash, player=player)
    _trash_card(game, player, to_trash, from_zone=player.hand)
    for i in range(2):
        candidates = _available_supply_cards(
            game, player=player, strictly_less_than=trashed_cost
        )
        if not candidates:
            break
        choice = _choose_from_options(
            game,
            player,
            f"Choose card #{i + 1} costing less than ${trashed_cost} to gain",
            candidates,
        )
        if choice is not None:
            _gain_card(game, player, _card_name(choice))


def overpay_stonemason(game: Any, player: Any, overpaid: int, card: Any = None) -> None:
    """Stonemason Overpay: If you overpaid > $0, gain 2 Action cards each costing the amount overpaid."""
    if overpaid <= 0:
        return
    for i in range(2):
        candidates = _available_supply_cards(
            game, player=player, exact_cost=overpaid, required_type="action"
        )
        if not candidates:
            break
        choice = _choose_from_options(
            game,
            player,
            f"Stonemason overpay: choose Action card #{i + 1} costing ${overpaid}",
            candidates,
        )
        if choice is not None:
            _gain_card(game, player, _card_name(choice))


def play_doctor(game: Any, player: Any, card: Any = None, named_card: Optional[str] = None) -> None:
    """Doctor ($3+, Action): Name a card. Reveal top 3 cards of deck. Trash matches. Put rest back in any order."""
    if named_card is None:
        if hasattr(player, "named_card") and player.named_card:
            named_card = player.named_card
        else:
            supply_names = list(getattr(game, "supply", {}).keys()) or ["Copper", "Estate", "Curse"]
            default_opts = ["Copper", "Curse", "Estate"] + [n for n in supply_names if n not in ("Copper", "Curse", "Estate")]
            named_card = _card_name(
                _choose_from_options(game, player, "Name a card for Doctor", default_opts)
            )
    revealed = _reveal_top_cards(game, player, 3)
    remaining = []
    for c in revealed:
        if _card_name(c) == named_card:
            _trash_card(game, player, c)
        else:
            remaining.append(c)
    # Put the rest back in chosen order (default: preserve order on top of deck)
    for c in reversed(remaining):
        player.deck.insert(0, c)


def overpay_doctor(game: Any, player: Any, overpaid: int, card: Any = None) -> None:
    """Doctor Overpay: For each $1 overpaid, look at top card of deck; trash it, discard it, or put it back."""
    for _ in range(max(0, int(overpaid))):
        top_list = _reveal_top_cards(game, player, 1)
        if not top_list:
            break
        top_card = top_list[0]
        action = _choose_from_options(
            game,
            player,
            f"Doctor overpay: choose disposition for {_card_name(top_card)}",
            ["trash", "discard", "put_back"],
        )
        if action == "trash":
            _trash_card(game, player, top_card)
        elif action == "discard":
            player.discard.append(top_card)
        else:
            player.deck.insert(0, top_card)


def play_masterpiece(game: Any, player: Any, card: Any = None) -> None:
    """Masterpiece ($3+, Treasure): +$1."""
    player.coins = getattr(player, "coins", 0) + 1


def overpay_masterpiece(game: Any, player: Any, overpaid: int, card: Any = None) -> None:
    """Masterpiece Overpay: For each $1 overpaid, gain a Silver."""
    for _ in range(max(0, int(overpaid))):
        _gain_card(game, player, "Silver")


def play_advisor(game: Any, player: Any, card: Any = None) -> None:
    """Advisor ($4, Action): +1 Action. Reveal top 3 cards. Left player chooses 1 to discard; put rest in hand."""
    player.actions = getattr(player, "actions", 0) + 1
    revealed = _reveal_top_cards(game, player, 3)
    if not revealed:
        return
    # Identify player to the left
    players = getattr(game, "players", [player])
    if len(players) > 1 and player in players:
        idx = (players.index(player) + 1) % len(players)
        chooser = players[idx]
    else:
        chooser = player
    # Default AI heuristic for left player: discard the highest-cost card
    sorted_by_cost = sorted(
        revealed, key=lambda c: _get_card_cost(game, c, player=player), reverse=True
    )
    discarded = _choose_from_options(
        game, chooser, "Choose a revealed card for Advisor to discard", sorted_by_cost
    )
    if discarded is None or discarded not in revealed:
        discarded = sorted_by_cost[0]
    revealed.remove(discarded)
    player.discard.append(discarded)
    player.hand.extend(revealed)


def play_plaza(game: Any, player: Any, card: Any = None) -> None:
    """Plaza ($4, Action): +1 Card, +2 Actions. You may discard a Treasure for +1 Coffers."""
    _draw_cards(game, player, 1)
    player.actions = getattr(player, "actions", 0) + 2
    treasures = [c for c in player.hand if _is_type(c, "treasure", game)]
    if not treasures:
        return
    choice = _choose_from_options(
        game,
        player,
        "You may discard a Treasure card for +1 Coffers",
        treasures,
        optional=True,
    )
    if choice is not None and choice in player.hand:
        player.hand.remove(choice)
        player.discard.append(choice)
        _add_coffers(player, 1)


def play_taxman(game: Any, player: Any, card: Any = None) -> None:
    """Taxman ($4, Action - Attack): You may trash a Treasure from hand. Others with >=5 cards discard a copy. Gain a Treasure onto deck costing up to $3 more."""
    treasures = [c for c in player.hand if _is_type(c, "treasure", game)]
    if not treasures:
        return
    to_trash = _choose_from_options(
        game,
        player,
        "You may trash a Treasure from your hand for Taxman",
        treasures,
        optional=True,
    )
    if to_trash is None or to_trash not in player.hand:
        return
    trashed_name = _card_name(to_trash)
    trashed_cost = _get_card_cost(game, to_trash, player=player)
    _trash_card(game, player, to_trash, from_zone=player.hand)

    for other in getattr(game, "players", []):
        if other is player:
            continue
        if hasattr(game, "is_attack_blocked") and game.is_attack_blocked(other, source=card):
            continue
        if any(_card_name(c) == "Moat" for c in getattr(other, "hand", [])):
            continue
        if len(other.hand) >= 5:
            matching = [c for c in other.hand if _card_name(c) == trashed_name]
            if matching:
                victim_card = matching[0]
                other.hand.remove(victim_card)
                other.discard.append(victim_card)

    candidates = _available_supply_cards(
        game, player=player, max_cost=trashed_cost + 3, required_type="treasure"
    )
    if candidates:
        # Prefer highest value treasure by default if no explicit choice
        candidates_sorted = sorted(
            candidates, key=lambda n: _get_card_cost(game, n, player=player), reverse=True
        )
        gained_name = _choose_from_options(
            game,
            player,
            f"Choose a Treasure costing up to ${trashed_cost + 3} to gain onto your deck",
            candidates_sorted,
        )
        if gained_name is not None:
            _gain_card(game, player, _card_name(gained_name), destination="deck")


def play_herald(game: Any, player: Any, card: Any = None) -> None:
    """Herald ($4+, Action): +1 Card, +1 Action. Reveal top card of deck; if Action, play it."""
    _draw_cards(game, player, 1)
    player.actions = getattr(player, "actions", 0) + 1
    top_list = _reveal_top_cards(game, player, 1)
    if not top_list:
        return
    top_card = top_list[0]
    if _is_type(top_card, "action", game):
        if hasattr(game, "play_card"):
            # Put in play or let game.play_card handle free play
            try:
                game.play_card(player, top_card, free=True, from_zone="revealed")
                return
            except TypeError:
                pass
        if hasattr(player, "in_play"):
            player.in_play.append(top_card)
        spec = getattr(game, "card_registry", {}).get(_card_name(top_card))
        if hasattr(top_card, "on_play") and callable(top_card.on_play):
            top_card.on_play(game, player)
        elif spec is not None and hasattr(spec, "on_play") and callable(spec.on_play):
            spec.on_play(game, player)
    else:
        player.deck.insert(0, top_card)


def overpay_herald(game: Any, player: Any, overpaid: int, card: Any = None) -> None:
    """Herald Overpay: For each $1 overpaid, look at your discard pile and put a card from it onto your deck."""
    for _ in range(max(0, int(overpaid))):
        if not player.discard:
            break
        chosen = _choose_from_options(
            game,
            player,
            "Herald overpay: choose a card from discard to put onto your deck",
            list(player.discard),
        )
        if chosen is not None and chosen in player.discard:
            player.discard.remove(chosen)
            player.deck.insert(0, chosen)


def play_baker(game: Any, player: Any, card: Any = None) -> None:
    """Baker ($5, Action): +1 Card, +1 Action, +1 Coffers. Setup: Each player gets +1 Coffers."""
    _draw_cards(game, player, 1)
    player.actions = getattr(player, "actions", 0) + 1
    _add_coffers(player, 1)


def setup_baker(game: Any) -> None:
    """Baker Setup hook: Each player starts the game with +1 Coffers."""
    for p in getattr(game, "players", []):
        _add_coffers(p, 1)


def play_butcher(game: Any, player: Any, card: Any = None) -> None:
    """Butcher ($5, Action): +2 Coffers. You may trash a card from hand, pay any # of Coffers, and gain a card costing up to trashed cost + $1 per Coffers paid."""
    _add_coffers(player, 2)
    if not player.hand:
        return
    to_trash = _choose_from_options(
        game,
        player,
        "You may trash a card from your hand for Butcher",
        list(player.hand),
        optional=True,
    )
    if to_trash is None or to_trash not in player.hand:
        return
    base_cost = _get_card_cost(game, to_trash, player=player)
    _trash_card(game, player, to_trash, from_zone=player.hand)

    avail_coffers = getattr(player, "coffers", getattr(player, "coin_tokens", 0)) or 0
    spend_options = list(range(avail_coffers + 1))
    coffers_to_spend = _choose_from_options(
        game,
        player,
        f"Choose how many Coffers to spend for Butcher (0-{avail_coffers})",
        spend_options,
    )
    spent = _spend_coffers(player, int(coffers_to_spend or 0))
    max_gain_cost = base_cost + spent
    candidates = _available_supply_cards(game, player=player, max_cost=max_gain_cost)
    if candidates:
        chosen = _choose_from_options(
            game,
            player,
            f"Choose a card costing up to ${max_gain_cost} to gain from Butcher",
            candidates,
        )
        if chosen is not None:
            _gain_card(game, player, _card_name(chosen))


def play_journeyman(game: Any, player: Any, card: Any = None, named_card: Optional[str] = None) -> None:
    """Journeyman ($5, Action): Name a card. Reveal from deck until 3 non-matching cards are revealed; put them into hand and discard the rest."""
    if named_card is None:
        if hasattr(player, "named_card") and player.named_card:
            named_card = player.named_card
        else:
            default_opts = ["Estate", "Copper", "Curse"] + [
                n for n in getattr(game, "supply", {}).keys() if n not in ("Estate", "Copper", "Curse")
            ]
            named_card = _card_name(
                _choose_from_options(game, player, "Name a card for Journeyman", default_opts)
            )
    kept: List[Any] = []
    set_aside: List[Any] = []
    max_cards = len(player.deck) + len(player.discard)
    inspected = 0
    while len(kept) < 3 and inspected < max_cards:
        revealed = _reveal_top_cards(game, player, 1)
        if not revealed:
            break
        inspected += 1
        c = revealed[0]
        if _card_name(c) == named_card:
            set_aside.append(c)
        else:
            kept.append(c)
    player.hand.extend(kept)
    player.discard.extend(set_aside)


def play_merchant_guild(game: Any, player: Any, card: Any = None) -> None:
    """Merchant Guild ($5, Action): +1 Buy, +$1. While in play, when you buy a card, +1 Coffers."""
    player.buys = getattr(player, "buys", 0) + 1
    player.coins = getattr(player, "coins", 0) + 1
    player.merchant_guild_triggers = getattr(player, "merchant_guild_triggers", 0) + 1


def play_soothsayer(game: Any, player: Any, card: Any = None) -> None:
    """Soothsayer ($5, Action - Attack): Gain a Gold. Each other player gains a Curse, and if they did, draws a card."""
    _gain_card(game, player, "Gold")
    for other in getattr(game, "players", []):
        if other is player:
            continue
        if hasattr(game, "is_attack_blocked") and game.is_attack_blocked(other, source=card):
            continue
        if any(_card_name(c) == "Moat" for c in getattr(other, "hand", [])):
            continue
        gained_curse = _gain_card(game, other, "Curse")
        if gained_curse is not None:
            _draw_cards(game, other, 1)


# ---------------------------------------------------------------------------
# Guilds 2nd Edition (2024 Combined Cornucopia & Guilds 2E) Card Effects
# ---------------------------------------------------------------------------

def play_farrier(game: Any, player: Any, card: Any = None) -> None:
    """Farrier ($2+, Action, 2E): +1 Card, +1 Action, +1 Buy."""
    _draw_cards(game, player, 1)
    player.actions = getattr(player, "actions", 0) + 1
    player.buys = getattr(player, "buys", 0) + 1


def overpay_farrier(game: Any, player: Any, overpaid: int, card: Any = None) -> None:
    """Farrier Overpay (2E): Overpay any amount; draw +1 Card per $1 overpaid at end of turn."""
    if overpaid > 0:
        player.farrier_extra_draw = getattr(player, "farrier_extra_draw", 0) + int(overpaid)
        _draw_cards(game, player, int(overpaid))


def play_shop(game: Any, player: Any, card: Any = None) -> None:
    """Shop ($3, Action, 2E): +1 Card, +1 Action, +$1. You may play an Action card from hand that you don't have a copy of in play."""
    _draw_cards(game, player, 1)
    player.actions = getattr(player, "actions", 0) + 1
    player.coins = getattr(player, "coins", 0) + 1
    in_play_names = {_card_name(c) for c in getattr(player, "in_play", [])}
    eligible = [
        c for c in player.hand
        if _is_type(c, "action", game) and _card_name(c) not in in_play_names
    ]
    if not eligible:
        return
    chosen = _choose_from_options(
        game, player, "Shop: you may play an Action not in play", eligible, optional=True
    )
    if chosen is not None and chosen in player.hand:
        player.hand.remove(chosen)
        if hasattr(player, "in_play"):
            player.in_play.append(chosen)
        spec = getattr(game, "card_registry", {}).get(_card_name(chosen))
        if hasattr(chosen, "on_play") and callable(chosen.on_play):
            chosen.on_play(game, player)
        elif spec is not None and hasattr(spec, "on_play") and callable(spec.on_play):
            spec.on_play(game, player)


def play_infirmary(game: Any, player: Any, card: Any = None) -> None:
    """Infirmary ($4+, Action, 2E): +1 Card. You may trash a card from your hand."""
    _draw_cards(game, player, 1)
    if not player.hand:
        return
    to_trash = _choose_from_options(
        game, player, "Infirmary: you may trash a card from your hand", list(player.hand), optional=True
    )
    if to_trash is not None and to_trash in player.hand:
        _trash_card(game, player, to_trash, from_zone=player.hand)


def overpay_infirmary(game: Any, player: Any, overpaid: int, card: Any = None) -> None:
    """Infirmary Overpay (2E): Play Infirmary once per $1 overpaid."""
    for _ in range(max(0, int(overpaid))):
        play_infirmary(game, player, card)


def play_footpad(game: Any, player: Any, card: Any = None) -> None:
    """Footpad ($5, Action - Attack, 2E): +2 Coffers. Each other player discards down to 4 cards."""
    _add_coffers(player, 2)
    for other in getattr(game, "players", []):
        if other is player:
            continue
        if hasattr(game, "is_attack_blocked") and game.is_attack_blocked(other, source=card):
            continue
        if any(_card_name(c) == "Moat" for c in getattr(other, "hand", [])):
            continue
        while len(other.hand) > 4:
            c = other.hand.pop()
            other.discard.append(c)


def on_gain_footpad(game: Any, player: Any, card: Any = None) -> None:
    """Footpad on-gain (2E): +1 Card, and you may play it."""
    _draw_cards(game, player, 1)


# ---------------------------------------------------------------------------
# Card Definitions Catalog
# ---------------------------------------------------------------------------

GUILDS_CARD_DEFS: List[Dict[str, Any]] = [
    {
        "name": "Candlestick Maker",
        "cost": 2,
        "types": ("Action",),
        "expansion": "Guilds",
        "edition": "1E/2E",
        "text": "+1 Action, +1 Buy, +1 Coffers.",
        "on_play": play_candlestick_maker,
        "actions": 1,
        "buys": 1,
        "coffers": 1,
    },
    {
        "name": "Stonemason",
        "cost": 2,
        "can_overpay": True,
        "types": ("Action",),
        "expansion": "Guilds",
        "edition": "1E/2E",
        "text": "Trash a card from your hand. Gain 2 cards each costing less than it. Overpay: Gain 2 Action cards each costing the amount you overpaid.",
        "on_play": play_stonemason,
        "on_overpay": overpay_stonemason,
    },
    {
        "name": "Doctor",
        "cost": 3,
        "can_overpay": True,
        "types": ("Action",),
        "expansion": "Guilds",
        "edition": "1E",
        "text": "Name a card. Reveal the top 3 cards of your deck. Trash the matches. Put the rest back in any order. Overpay: For each $1 overpaid, look at the top card of your deck; trash it, discard it, or put it back.",
        "on_play": play_doctor,
        "on_overpay": overpay_doctor,
    },
    {
        "name": "Masterpiece",
        "cost": 3,
        "can_overpay": True,
        "types": ("Treasure",),
        "expansion": "Guilds",
        "edition": "1E",
        "coins": 1,
        "text": "$1. Overpay: For each $1 overpaid, gain a Silver.",
        "on_play": play_masterpiece,
        "on_overpay": overpay_masterpiece,
    },
    {
        "name": "Advisor",
        "cost": 4,
        "types": ("Action",),
        "expansion": "Guilds",
        "edition": "1E/2E",
        "actions": 1,
        "text": "+1 Action. Reveal the top 3 cards of your deck. The player to your left chooses one of them. Discard that card and put the rest into your hand.",
        "on_play": play_advisor,
    },
    {
        "name": "Plaza",
        "cost": 4,
        "types": ("Action",),
        "expansion": "Guilds",
        "edition": "1E/2E",
        "cards": 1,
        "actions": 2,
        "text": "+1 Card, +2 Actions. You may discard a Treasure for +1 Coffers.",
        "on_play": play_plaza,
    },
    {
        "name": "Taxman",
        "cost": 4,
        "types": ("Action", "Attack"),
        "expansion": "Guilds",
        "edition": "1E",
        "text": "You may trash a Treasure from your hand. Each other player with 5 or more cards in hand discards a copy of it. Gain a Treasure onto your deck costing up to $3 more than the trashed card.",
        "on_play": play_taxman,
    },
    {
        "name": "Herald",
        "cost": 4,
        "can_overpay": True,
        "types": ("Action",),
        "expansion": "Guilds",
        "edition": "1E",
        "cards": 1,
        "actions": 1,
        "text": "+1 Card, +1 Action. Reveal the top card of your deck. If it is an Action, play it. Overpay: For each $1 overpaid, look at your discard pile and put a card from it onto your deck.",
        "on_play": play_herald,
        "on_overpay": overpay_herald,
    },
    {
        "name": "Baker",
        "cost": 5,
        "types": ("Action",),
        "expansion": "Guilds",
        "edition": "1E/2E",
        "cards": 1,
        "actions": 1,
        "coffers": 1,
        "text": "+1 Card, +1 Action, +1 Coffers. Setup: Each player gets +1 Coffers.",
        "on_play": play_baker,
        "on_setup": setup_baker,
    },
    {
        "name": "Butcher",
        "cost": 5,
        "types": ("Action",),
        "expansion": "Guilds",
        "edition": "1E/2E",
        "coffers": 2,
        "text": "+2 Coffers. You may trash a card from your hand. If you do, pay any number of Coffers and gain a card costing up to the cost of the trashed card plus $1 per Coffers paid.",
        "on_play": play_butcher,
    },
    {
        "name": "Journeyman",
        "cost": 5,
        "types": ("Action",),
        "expansion": "Guilds",
        "edition": "1E/2E",
        "text": "Name a card. Reveal cards from your deck until you reveal 3 cards other than the named card. Put those cards into your hand and discard the rest.",
        "on_play": play_journeyman,
    },
    {
        "name": "Merchant Guild",
        "cost": 5,
        "types": ("Action",),
        "expansion": "Guilds",
        "edition": "1E/2E",
        "buys": 1,
        "coins": 1,
        "text": "+1 Buy, +$1. While this is in play, when you buy a card, +1 Coffers.",
        "on_play": play_merchant_guild,
    },
    {
        "name": "Soothsayer",
        "cost": 5,
        "types": ("Action", "Attack"),
        "expansion": "Guilds",
        "edition": "1E/2E",
        "text": "Gain a Gold. Each other player gains a Curse, and if they did, draws a card.",
        "on_play": play_soothsayer,
    },
    # 2024 2nd Edition Cards (Cornucopia & Guilds 2E)
    {
        "name": "Farrier",
        "cost": 2,
        "can_overpay": True,
        "types": ("Action",),
        "expansion": "Guilds",
        "edition": "2E",
        "cards": 1,
        "actions": 1,
        "buys": 1,
        "text": "+1 Card, +1 Action, +1 Buy. Overpay: Draw +1 Card per $1 overpaid.",
        "on_play": play_farrier,
        "on_overpay": overpay_farrier,
    },
    {
        "name": "Shop",
        "cost": 3,
        "types": ("Action",),
        "expansion": "Guilds",
        "edition": "2E",
        "cards": 1,
        "actions": 1,
        "coins": 1,
        "text": "+1 Card, +1 Action, +$1. You may play an Action card from your hand that you don't have a copy of in play.",
        "on_play": play_shop,
    },
    {
        "name": "Infirmary",
        "cost": 4,
        "can_overpay": True,
        "types": ("Action",),
        "expansion": "Guilds",
        "edition": "2E",
        "cards": 1,
        "text": "+1 Card. You may trash a card from your hand. Overpay: Play this that many times.",
        "on_play": play_infirmary,
        "on_overpay": overpay_infirmary,
    },
    {
        "name": "Footpad",
        "cost": 5,
        "types": ("Action", "Attack"),
        "expansion": "Guilds",
        "edition": "2E",
        "coffers": 2,
        "text": "+2 Coffers. Each other player with 5 or more cards in hand discards down to 4 cards. When you gain this, +1 Card.",
        "on_play": play_footpad,
        "on_gain": on_gain_footpad,
    },
]

GUILDS_1E_NAMES = [d["name"] for d in GUILDS_CARD_DEFS if "1E" in d["edition"]]
GUILDS_2E_NAMES = [d["name"] for d in GUILDS_CARD_DEFS if "2E" in d["edition"]]
ALL_GUILDS_NAMES = [d["name"] for d in GUILDS_CARD_DEFS]


# ---------------------------------------------------------------------------
# Engine Card Class / Registry Integration
# ---------------------------------------------------------------------------

class GuildsCardSpec:
    """Universal card specification object compatible with Card / CardSpec patterns."""

    def __init__(self, data: Dict[str, Any]) -> None:
        self.data = data
        self.name: str = data["name"]
        self.cost: int = data["cost"]
        self.can_overpay: bool = bool(data.get("can_overpay", False))
        self.overpay: bool = self.can_overpay
        self.types: tuple = tuple(data["types"])
        self.expansion: str = data.get("expansion", "Guilds")
        self.edition: str = data.get("edition", "1E/2E")
        self.text: str = data.get("text", "")
        self.description: str = self.text
        self.cards: int = data.get("cards", 0)
        self.actions: int = data.get("actions", 0)
        self.buys: int = data.get("buys", 0)
        self.coins: int = data.get("coins", 0)
        self.coffers: int = data.get("coffers", 0)
        self.on_play = data.get("on_play")
        self.on_overpay = data.get("on_overpay")
        self.on_setup = data.get("on_setup")
        self.on_gain = data.get("on_gain")

    @property
    def is_action(self) -> bool:
        return "Action" in self.types

    @property
    def is_treasure(self) -> bool:
        return "Treasure" in self.types

    @property
    def is_attack(self) -> bool:
        return "Attack" in self.types

    @property
    def is_victory(self) -> bool:
        return "Victory" in self.types

    def play(self, game: Any, player: Any) -> None:
        if self.on_play:
            self.on_play(game, player, self)

    def __repr__(self) -> str:
        plus = "+" if self.can_overpay else ""
        return f"<Card {self.name} (${self.cost}{plus}) [{', '.join(self.types)}]>"


def _instantiate_cards() -> Dict[str, Any]:
    """Build card objects using the repository's native Card/CardSpec class when available."""
    registry: Dict[str, Any] = {}
    native_cls = None
    cost_cls = None
    try:
        from .. import costs as _costs_mod
        cost_cls = getattr(_costs_mod, "Cost", getattr(_costs_mod, "CardCost", None))
    except Exception:
        pass

    for mod_name in ("..cards", "..state", "..effects", ".basic", ".base"):
        try:
            from importlib import import_module
            mod = import_module(mod_name, package=__package__)
            for attr in ("CardSpec", "Card", "CardDef", "CardTemplate"):
                if hasattr(mod, attr):
                    native_cls = getattr(mod, attr)
                    break
            if native_cls is not None:
                break
        except Exception:
            continue

    for d in GUILDS_CARD_DEFS:
        spec = GuildsCardSpec(d)
        if native_cls is not None:
            try:
                import inspect
                sig = inspect.signature(native_cls)
                kwargs: Dict[str, Any] = {}
                for param in sig.parameters:
                    if param == "name":
                        kwargs["name"] = d["name"]
                    elif param == "cost":
                        if cost_cls is not None:
                            try:
                                kwargs["cost"] = cost_cls(coins=d["cost"], overpay=d.get("can_overpay", False))
                            except TypeError:
                                try:
                                    kwargs["cost"] = cost_cls(d["cost"])
                                except Exception:
                                    kwargs["cost"] = d["cost"]
                        else:
                            kwargs["cost"] = d["cost"]
                    elif param in ("types", "card_types"):
                        kwargs[param] = d["types"]
                    elif param in ("expansion", "set_name"):
                        kwargs[param] = "Guilds"
                    elif param in ("text", "description", "rules_text"):
                        kwargs[param] = d["text"]
                    elif param in ("can_overpay", "overpay"):
                        kwargs[param] = d.get("can_overpay", False)
                    elif param in ("on_play", "effect", "play_fn", "action"):
                        kwargs[param] = d.get("on_play")
                    elif param in ("on_overpay", "overpay_effect", "overpay_fn"):
                        kwargs[param] = d.get("on_overpay")
                    elif param in ("on_setup", "setup_fn"):
                        kwargs[param] = d.get("on_setup")
                    elif param in ("on_gain", "gain_fn"):
                        kwargs[param] = d.get("on_gain")
                    elif param in d:
                        kwargs[param] = d[param]
                obj = native_cls(**kwargs)
                for extra_attr in ("can_overpay", "on_play", "on_overpay", "on_setup", "on_gain", "edition", "text"):
                    if not hasattr(obj, extra_attr) or getattr(obj, extra_attr) is None:
                        try:
                            setattr(obj, extra_attr, getattr(spec, extra_attr))
                        except Exception:
                            pass
                registry[d["name"]] = obj
                continue
            except Exception:
                pass
        registry[d["name"]] = spec
    return registry


GUILDS_CARDS: Dict[str, Any] = _instantiate_cards()
CARDS: Dict[str, Any] = GUILDS_CARDS
CARD_LIST: List[Any] = list(GUILDS_CARDS.values())


def get_cards() -> Dict[str, Any]:
    return dict(GUILDS_CARDS)


def register_cards(target_registry: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if target_registry is not None:
        target_registry.update(GUILDS_CARDS)
        return target_registry
    return dict(GUILDS_CARDS)
