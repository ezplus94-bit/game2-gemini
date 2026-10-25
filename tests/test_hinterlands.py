"""Comprehensive tests for the Dominion: Hinterlands Second Edition expansion (all 26 Kingdom cards)."""

from __future__ import annotations

import pytest

from dominion.cards import CardType, expansions, get_card, kingdom_cards
from dominion.engine import (
    Buy, Choose, EndPhase, GameConfig, IllegalActionError, Phase, PlayAction, PlayAllTreasures, PlayTreasure,
    build_view, new_game, score_player,
)
from dominion.engine.costs import card_cost


HINTERLANDS_2E_CARDS = [
    "Berserker", "Border Village", "Cartographer", "Cauldron", "Crossroads",
    "Develop", "Farmland", "Fool's Gold", "Guard Dog", "Haggler",
    "Highway", "Inn", "Jack of All Trades", "Margrave", "Nomads",
    "Oasis", "Scheme", "Souk", "Spice Merchant", "Stables",
    "Trader", "Trail", "Tunnel", "Weaver", "Wheelwright", "Witch's Hut",
]

REMOVED_1E_CARDS = [
    "Duchess", "Embassy", "Ill-Gotten Gains", "Mandarin", "Noble Brigand",
    "Nomad Camp", "Oracle", "Silk Road", "Cache",
]


def _make_game(kingdom=None, num_players=2, seed=42, **kw):
    names = ["Alice", "Bob", "Carol", "Dave"][:num_players]
    return new_game(GameConfig(names, kingdom=kingdom or ["Oasis"], seed=seed, colonies=False, **kw))


def test_hinterlands_2e_inventory_and_types():
    assert "Hinterlands" in expansions()
    kc = kingdom_cards(["Hinterlands"])
    assert kc == sorted(HINTERLANDS_2E_CARDS)
    assert len(kc) == 26
    for removed in REMOVED_1E_CARDS:
        assert removed not in kc

    # Verify multi-type cards
    assert get_card("Fool's Gold").types == frozenset({CardType.TREASURE, CardType.REACTION})
    assert get_card("Tunnel").types == frozenset({CardType.VICTORY, CardType.REACTION})
    assert get_card("Cauldron").types == frozenset({CardType.TREASURE, CardType.ATTACK})
    assert get_card("Guard Dog").types == frozenset({CardType.ACTION, CardType.REACTION})
    assert get_card("Trader").types == frozenset({CardType.ACTION, CardType.REACTION})
    assert get_card("Trail").types == frozenset({CardType.ACTION, CardType.REACTION})
    assert get_card("Weaver").types == frozenset({CardType.ACTION, CardType.REACTION})
    assert get_card("Berserker").types == frozenset({CardType.ACTION, CardType.ATTACK})
    assert get_card("Margrave").types == frozenset({CardType.ACTION, CardType.ATTACK})
    assert get_card("Witch's Hut").types == frozenset({CardType.ACTION, CardType.ATTACK})
    assert get_card("Farmland").types == frozenset({CardType.VICTORY})


def test_crossroads_first_and_second_play():
    game = _make_game(["Crossroads"])
    p = game.state.players[0]
    p.hand = ["Crossroads", "Crossroads", "Estate", "Duchy"]
    p.deck = ["Copper", "Silver", "Gold"]

    game.apply(0, PlayAction("Crossroads"))
    # 2 Victory cards in hand -> draws 2; first Crossroads -> +3 Actions (1 - 1 + 3 = 3)
    assert game.state.actions == 3
    assert len(p.hand) == 5  # Crossroads, Estate, Duchy + 2 drawn

    # Second Crossroads play this turn: draws 2 for Estate & Duchy, but 0 extra Actions (3 - 1 = 2)
    game.apply(0, PlayAction("Crossroads"))
    assert game.state.actions == 2


def test_fools_gold_value_and_province_reaction():
    game = _make_game(["Fool's Gold"])
    p0, p1 = game.state.players[0], game.state.players[1]
    p0.hand = ["Fool's Gold", "Fool's Gold"]
    game.apply(0, EndPhase())

    game.apply(0, PlayTreasure("Fool's Gold"))
    assert game.state.coins == 1
    game.apply(0, PlayTreasure("Fool's Gold"))
    assert game.state.coins == 5  # $1 + $4

    # End p0's turn; on p1's turn, p0 holds Fool's Gold and p1 buys Province
    game.apply(0, EndPhase())
    p0.hand = ["Fool's Gold", "Copper"]
    game.apply(1, EndPhase())
    game.state.coins = 8
    game.apply(1, Buy("Province"))

    # p0 is prompted to trash Fool's Gold to gain Gold onto deck
    assert game.acting_player == 0
    game.apply(0, Choose(("Fool's Gold",)))
    assert "Fool's Gold" in game.state.trash
    assert p0.deck[-1] == "Gold"


def test_develop_trashes_and_gains_plus_and_minus_one_onto_deck():
    game = _make_game(["Develop", "Oasis", "Crossroads", "Nomads"])
    p0 = game.state.players[0]
    p0.hand = ["Develop", "Oasis"]  # Oasis costs $3 -> gains $4 and $2 onto deck
    game.apply(0, PlayAction("Develop"))
    game.apply(0, Choose(("Oasis",)))
    assert "Oasis" in game.state.trash
    # Choose whether to gain $4 or $2 first
    game.apply(0, Choose(("Gain $4 card first",)))
    game.apply(0, Choose(("Nomads",)))
    # Nomads on_gain gives +$2!
    game.apply(0, Choose(("Crossroads",)))
    assert p0.deck[-2:] == ["Nomads", "Crossroads"]
    assert game.state.coins == 2


def test_guard_dog_play_and_reaction_to_opponent_5_cost_gain():
    game = _make_game(["Guard Dog", "Margrave"])
    p0, p1 = game.state.players[0], game.state.players[1]
    p0.hand = ["Guard Dog", "Copper", "Estate"]
    p1.hand = ["Guard Dog", "Copper", "Copper", "Estate"]
    p1.deck = ["Silver", "Gold"]

    # p0 buys Duchy ($5) -> p1 reacts with Guard Dog from hand!
    game.apply(0, EndPhase())
    game.state.coins = 5
    game.apply(0, Buy("Duchy"))
    assert game.acting_player == 1
    game.apply(1, Choose(("Guard Dog",)))
    assert "Guard Dog" in p1.in_play
    assert len(p1.hand) == 5  # 3 remaining + 2 drawn


def test_oasis_and_tunnel_discard_reaction():
    game = _make_game(["Oasis", "Tunnel"])
    p0 = game.state.players[0]
    p0.hand = ["Oasis", "Tunnel"]
    p0.deck = ["Copper"]
    game.apply(0, PlayAction("Oasis"))
    assert game.state.actions == 1
    assert game.state.coins == 1
    game.apply(0, Choose(("Tunnel",)))
    # Tunnel triggers when discarded outside Clean-up!
    game.apply(0, Choose(("Reveal Tunnel (gain a Gold)",)))
    assert "Gold" in p0.discard
    assert score_player(p0) >= 2  # Tunnel is worth 2 VP


def test_tunnel_does_not_trigger_during_cleanup():
    game = _make_game(["Tunnel"])
    p0 = game.state.players[0]
    p0.hand = ["Tunnel", "Copper"]
    game.apply(0, EndPhase())
    game.apply(0, EndPhase())
    # Turn ended cleanly without asking Tunnel reaction
    assert game.state.current_player == 1
    assert game.state.pending is None
    assert "Gold" not in p0.discard


def test_scheme_puts_action_from_play_onto_deck_at_cleanup():
    game = _make_game(["Scheme", "Oasis"])
    p0 = game.state.players[0]
    p0.hand = ["Scheme", "Oasis", "Copper"]
    p0.deck = ["Silver", "Gold"]
    game.apply(0, PlayAction("Scheme"))
    game.apply(0, PlayAction("Oasis"))
    game.apply(0, Choose(("Copper",)))
    game.apply(0, EndPhase())
    game.apply(0, EndPhase())
    # During cleanup, Scheme asks which Action card from play to put onto deck
    assert game.acting_player == 0
    game.apply(0, Choose(("Oasis",)))
    # p0 draws 5 cards for next hand, and since Oasis was put onto deck before drawing, Oasis is drawn into p0's new hand!
    assert "Oasis" in p0.hand
    assert game.state.current_player == 1


def test_jack_of_all_trades():
    game = _make_game(["Jack of All Trades"])
    p0 = game.state.players[0]
    p0.hand = ["Jack of All Trades", "Estate"]
    p0.deck = ["Copper", "Silver", "Gold", "Duchy", "Curse"]  # top is Curse
    game.apply(0, PlayAction("Jack of All Trades"))
    assert "Silver" in p0.discard
    # Look at top card (Curse) -> Discard it
    game.apply(0, Choose(("Discard it",)))
    assert "Curse" in p0.discard
    # Draws up to 5 cards in hand (had Estate, so draws 4: Duchy, Gold, Silver, Copper)
    assert len(p0.hand) == 5
    # Trash a non-Treasure (Estate or Duchy)
    game.apply(0, Choose(("Estate",)))
    assert "Estate" in game.state.trash


def test_nomads_play_gain_and_trash():
    game = _make_game(["Nomads", "Spice Merchant", "Remodel"])
    p0 = game.state.players[0]
    # Gain Nomads via buy -> +$2 on gain
    game.apply(0, EndPhase())
    game.state.coins = 4
    game.apply(0, Buy("Nomads"))
    assert game.state.coins == 2  # 4 - 4 + 2 from Nomads on_gain!

    # Trash Nomads with Remodel -> +$2 on trash!
    game.state.phase = Phase.ACTION
    game.state.actions = 1
    game.state.coins = 0
    p0.hand = ["Remodel", "Nomads"]
    game.apply(0, PlayAction("Remodel"))
    game.apply(0, Choose(("Nomads",)))
    assert game.state.coins == 2
    game.apply(0, Choose(("Gold",)))


def test_spice_merchant_and_stables_and_wheelwright():
    game = _make_game(["Spice Merchant", "Stables", "Wheelwright", "Oasis"])
    p0 = game.state.players[0]
    p0.hand = ["Spice Merchant", "Stables", "Wheelwright", "Copper", "Silver", "Gold"]
    p0.deck = ["Estate", "Copper", "Copper", "Copper", "Copper", "Copper"]

    # Spice Merchant: trash Copper for +2 Cards and +1 Action
    game.apply(0, PlayAction("Spice Merchant"))
    game.apply(0, Choose(("Copper",)))
    game.apply(0, Choose(("+2 Cards and +1 Action",)))
    assert "Copper" in game.state.trash
    assert game.state.actions == 1

    # Stables: discard Silver for +3 Cards and +1 Action
    game.apply(0, PlayAction("Stables"))
    game.apply(0, Choose(("Silver",)))
    assert game.state.actions == 1

    # Wheelwright: discard Gold ($6) to gain an Action costing up to $6
    game.apply(0, PlayAction("Wheelwright"))
    game.apply(0, Choose(("Gold",)))
    game.apply(0, Choose(("Wheelwright",)))
    assert "Wheelwright" in p0.discard


def test_trader_play_and_would_gain_reaction():
    game = _make_game(["Trader", "Oasis", "Witch"])
    p0, p1 = game.state.players[0], game.state.players[1]
    p0.hand = ["Trader", "Estate"]
    game.apply(0, PlayAction("Trader"))
    game.apply(0, Choose(("Estate",)))
    assert p0.discard.count("Silver") == 2

    # When p1 plays Witch, p0 holds Trader and reveals it to gain a Silver instead of a Curse!
    game.apply(0, EndPhase())
    game.apply(0, EndPhase())
    p0.hand = ["Trader", "Copper"]
    p1.hand = ["Witch"]
    game.apply(1, PlayAction("Witch"))
    assert game.acting_player == 0
    game.apply(0, Choose(("Reveal Trader (gain a Silver instead)",)))
    assert "Curse" not in p0.discard
    assert "Silver" in p0.discard
    assert game.state.supply["Curse"] == 10


def test_trail_and_weaver_play_on_discard_and_gain():
    game = _make_game(["Trail", "Weaver", "Oasis"])
    p0 = game.state.players[0]
    p0.hand = ["Oasis", "Trail", "Weaver"]
    p0.deck = ["Copper", "Silver", "Gold"]

    # Play Oasis, discard Trail -> Trail reactions plays it (+1 Card, +1 Action)
    game.apply(0, PlayAction("Oasis"))
    game.apply(0, Choose(("Trail",)))
    game.apply(0, Choose(("Trail",)))
    assert "Trail" in p0.in_play
    assert game.state.actions == 2

    # Play another Oasis (or discard Weaver) -> Weaver plays on discard and gains 2 Silvers!
    p0.hand.append("Oasis")
    game.apply(0, PlayAction("Oasis"))
    game.apply(0, Choose(("Weaver",)))
    game.apply(0, Choose(("Weaver",)))
    game.apply(0, Choose(("Gain two Silvers",)))
    assert "Weaver" in p0.in_play
    assert p0.discard.count("Silver") == 2

    # Gain Trail -> may play it immediately!
    game.apply(0, EndPhase())
    game.state.coins = 4
    game.apply(0, Buy("Trail"))
    game.apply(0, Choose(("Trail",)))
    assert p0.in_play.count("Trail") == 2


def test_berserker_on_gain_with_action_in_play_and_attack():
    game = _make_game(["Berserker", "Oasis", "Crossroads"])
    p0, p1 = game.state.players[0], game.state.players[1]
    p0.hand = ["Oasis", "Copper"]
    p1.hand = ["Copper", "Copper", "Copper", "Estate", "Estate"]

    # Play Oasis so an Action card is in play
    game.apply(0, PlayAction("Oasis"))
    game.apply(0, Choose(("Copper",)))
    assert "Oasis" in p0.in_play

    # Move to Buy phase and buy Berserker -> since Oasis is in play, Berserker plays itself!
    game.apply(0, EndPhase())
    game.state.coins = 5
    game.apply(0, Buy("Berserker"))
    # Berserker gains a card costing less than $5
    game.apply(0, Choose(("Oasis",)))
    # Berserker attacks p1 to discard down to 3
    assert game.acting_player == 1
    game.apply(1, Choose(("Estate", "Estate")))
    assert "Berserker" in p0.in_play
    assert len(p1.hand) == 3


def test_cartographer_and_cauldron_and_haggler_and_highway():
    game = _make_game(["Cartographer", "Cauldron", "Haggler", "Highway", "Oasis", "Crossroads"])
    p0, p1 = game.state.players[0], game.state.players[1]

    # Cartographer: +1 Card, +1 Action, look at top 4, discard some, reorder rest
    p0.hand = ["Cartographer"]
    p0.deck = ["Copper", "Estate", "Silver", "Duchy", "Gold"]  # Gold drawn; top 4: Duchy, Silver, Estate, Copper
    game.apply(0, PlayAction("Cartographer"))
    game.apply(0, Choose(("Estate", "Duchy")))
    game.apply(0, Choose(("Silver",)))  # put Silver on top, Copper second
    assert p0.deck[-1] == "Silver"

    # Highway: reduces costs by $1 while in play
    p0.hand = ["Highway"]
    game.apply(0, PlayAction("Highway"))
    assert card_cost(game.state, "Province") == 7

    # Haggler: +$2; when you buy a card, gain a cheaper non-Victory card
    p0.hand = ["Haggler", "Cauldron"]
    game.apply(0, PlayAction("Haggler"))
    game.apply(0, EndPhase())
    game.apply(0, PlayTreasure("Cauldron"))
    # Buy Duchy (costs $4 with Highway) -> Haggler gains a non-Victory card costing up to $3 (e.g. Silver or Oasis)
    game.state.coins = 10
    game.state.buys = 4
    game.apply(0, Buy("Duchy"))
    game.apply(0, Choose(("Oasis",)))  # 1st Action gained this turn!
    assert "Oasis" in p0.discard

    # Cauldron: gain 2nd and 3rd Action cards this turn -> 3rd triggers Curse on p1!
    game.apply(0, Buy("Crossroads"))
    game.apply(0, Choose(("Copper",)))
    game.apply(0, Buy("Crossroads"))
    game.apply(0, Choose(("Copper",)))
    assert "Curse" in p1.discard


def test_inn_margrave_souk_witchs_hut_border_village_farmland():
    game = _make_game(["Inn", "Margrave", "Souk", "Witch's Hut", "Border Village", "Farmland", "Oasis"])
    p0, p1 = game.state.players[0], game.state.players[1]

    # Margrave: +3 Cards, +1 Buy; p1 draws 1 then discards down to 3
    p0.hand = ["Margrave"]
    p0.deck = ["Copper", "Silver", "Gold"]
    p1.hand = ["Copper", "Copper", "Copper", "Estate"]
    p1.deck = ["Duchy"]
    game.apply(0, PlayAction("Margrave"))
    game.apply(1, Choose(("Estate", "Duchy")))
    assert len(p1.hand) == 3

    # Witch's Hut: +4 Cards, discard 2 revealed; if both Actions -> Curse
    p0.hand = ["Witch's Hut", "Oasis", "Inn"]
    p0.deck = ["Copper", "Copper", "Copper", "Copper"]
    game.state.actions = 1
    game.apply(0, PlayAction("Witch's Hut"))
    game.apply(0, Choose(("Oasis", "Inn")))
    assert "Curse" in p1.discard

    # Souk: +1 Buy, +$7, lose $1 per card in hand (never below $0); on_gain: trash up to 2 from hand
    p0.hand = ["Souk", "Copper", "Estate"]  # after playing Souk, 2 cards in hand -> +$7 - $2 = +$5
    game.state.actions = 1
    game.state.coins = 0
    game.apply(0, PlayAction("Souk"))
    assert game.state.coins == 5

    # Buy Souk -> on_gain trashes up to 2 cards from hand
    game.apply(0, EndPhase())
    game.apply(0, Buy("Souk"))
    game.apply(0, Choose(("Copper", "Estate")))
    assert "Copper" in game.state.trash and "Estate" in game.state.trash

    # Border Village: when gained, gain a cheaper card (e.g. Inn, which then shuffles Actions from discard into deck!)
    game.state.coins = 6
    game.state.buys = 2
    game.apply(0, Buy("Border Village"))
    game.apply(0, Choose(("Inn",)))
    # Inn's on_gain triggers: choose Inn & Oasis from discard to shuffle into deck!
    game.apply(0, Choose(("Inn", "Oasis")))
    assert "Inn" in p0.deck and "Oasis" in p0.deck

    # Farmland: when bought, trash a card from hand and gain one costing exactly $2 more
    p0.hand = ["Oasis"]  # costs $3 -> gains $5 card
    game.state.coins = 6
    game.apply(0, Buy("Farmland"))
    game.apply(0, Choose(("Oasis",)))
    game.apply(0, Choose(("Margrave",)))
    assert "Margrave" in p0.discard
