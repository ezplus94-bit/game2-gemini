"""Comprehensive tests for the Guilds expansion (13 Kingdom cards, Coffers, Villagers, Overpay)."""

from __future__ import annotations

import pytest

from dominion.cards import expansions, get_card, kingdom_cards
from dominion.engine import (
    Buy, Choose, EndPhase, GameConfig, IllegalActionError, Phase, PlayAction, PlayTreasure,
    SpendCoffers, SpendVillagers, action_from_dict, action_to_dict, build_view, new_game,
)


def _make_game(kingdom=None, num_players=2, seed=42, **kw):
    names = ["Alice", "Bob", "Carol", "Dave"][:num_players]
    return new_game(GameConfig(names, kingdom=kingdom or ["Candlestick Maker"], seed=seed, colonies=False, **kw))


def test_guilds_registration_and_inventory():
    assert "Guilds" in expansions()
    kc = kingdom_cards(["Guilds"])
    expected = [
        "Advisor", "Baker", "Butcher", "Candlestick Maker", "Doctor",
        "Herald", "Journeyman", "Masterpiece", "Merchant Guild", "Plaza",
        "Soothsayer", "Stonemason", "Taxman",
    ]
    assert kc == sorted(expected)


def test_baker_setup_and_coffers_persistence_and_spending():
    game = _make_game(["Baker", "Candlestick Maker"])
    p0, p1 = game.state.players[0], game.state.players[1]
    # Baker setup gives every player 1 Coffers at start of game
    assert p0.coffers == 1
    assert p1.coffers == 1

    p0.hand = ["Baker", "Candlestick Maker"]
    game.apply(0, PlayAction("Baker"))
    assert p0.coffers == 2
    assert game.state.actions == 1

    game.apply(0, PlayAction("Candlestick Maker"))
    assert p0.coffers == 3
    assert game.state.buys == 2

    # Move to Buy phase and spend 2 Coffers
    game.apply(0, EndPhase())
    assert SpendCoffers(1) in game.legal_actions(0)
    game.apply(0, SpendCoffers(2))
    assert p0.coffers == 1
    assert game.state.coins == 2

    # Codec round-trip for SpendCoffers and SpendVillagers
    assert action_from_dict(action_to_dict(SpendCoffers(2))) == SpendCoffers(2)
    assert action_from_dict(action_to_dict(SpendVillagers(1))) == SpendVillagers(1)

    # End turn: remaining 1 Coffers persists across turns!
    game.apply(0, EndPhase())
    assert p0.coffers == 1


def test_villagers_spending_and_restrictions():
    game = _make_game(["Candlestick Maker", "Baker"])
    p0 = game.state.players[0]
    p0.villagers = 2
    p0.hand = ["Candlestick Maker", "Baker"]
    game.state.actions = 0

    assert SpendVillagers(1) in game.legal_actions(0)
    game.apply(0, SpendVillagers(1))
    assert p0.villagers == 1
    assert game.state.actions == 1

    # Cannot spend Villagers in Buy phase
    game.apply(0, EndPhase())
    with pytest.raises(IllegalActionError):
        game.apply(0, SpendVillagers(1))


def test_plaza_and_butcher():
    game = _make_game(["Plaza", "Butcher"])
    p0 = game.state.players[0]
    p0.hand = ["Plaza", "Butcher", "Copper", "Estate"]
    p0.deck = ["Silver", "Gold"]

    game.apply(0, PlayAction("Plaza"))
    assert game.state.actions == 2
    game.apply(0, Choose(("Copper",)))
    assert p0.coffers == 1

    game.apply(0, PlayAction("Butcher"))
    assert p0.coffers == 3
    # Trash Estate ($2) and remove 3 Coffers -> gain Gold ($5) or Butcher ($5)
    game.apply(0, Choose(("Estate",)))
    game.apply(0, Choose(("Remove 3 Coffers",)))
    assert p0.coffers == 0
    game.apply(0, Choose(("Butcher",)))
    assert "Butcher" in p0.discard


def test_stonemason_play_and_overpay():
    game = _make_game(["Stonemason", "Plaza", "Advisor"])
    p0 = game.state.players[0]
    p0.hand = ["Stonemason", "Gold"]
    game.apply(0, PlayAction("Stonemason"))
    game.apply(0, Choose(("Gold",)))
    # Gold costs $6 -> gain 2 cards costing up to $5
    game.apply(0, Choose(("Duchy",)))
    game.apply(0, Choose(("Plaza",)))
    assert "Duchy" in p0.discard
    assert "Plaza" in p0.discard

    # Buy Stonemason ($2) with $6 coins -> overpay $4 -> gain 2 Action cards costing $4
    game.apply(0, EndPhase())
    game.state.coins = 6
    game.apply(0, Buy("Stonemason"))
    # Overpay prompt: pay $4 extra
    game.apply(0, Choose(("$4",)))
    assert game.state.coins == 0
    game.apply(0, Choose(("Plaza",)))
    game.apply(0, Choose(("Advisor",)))
    assert p0.discard.count("Plaza") == 2
    assert "Advisor" in p0.discard


def test_doctor_play_and_overpay():
    game = _make_game(["Doctor"])
    p0 = game.state.players[0]
    p0.hand = ["Doctor"]
    p0.deck = ["Gold", "Copper", "Estate", "Copper"]  # top 3: Copper, Estate, Copper
    game.apply(0, PlayAction("Doctor"))
    game.apply(0, Choose(("Copper",)))
    assert game.state.trash.count("Copper") == 2
    assert p0.deck == ["Gold", "Estate"]

    # Buy Doctor ($3) with $5 -> overpay $2
    game.apply(0, EndPhase())
    game.state.coins = 5
    game.apply(0, Buy("Doctor"))
    game.apply(0, Choose(("$2",)))
    # First card: Estate -> Trash it
    game.apply(0, Choose(("Trash it",)))
    # Second card: Gold -> Put it back
    game.apply(0, Choose(("Put it back",)))
    assert "Estate" in game.state.trash
    assert p0.deck == ["Gold"]


def test_masterpiece_overpay():
    game = _make_game(["Masterpiece"])
    p0 = game.state.players[0]
    game.apply(0, EndPhase())
    game.state.coins = 6
    game.apply(0, Buy("Masterpiece"))
    game.apply(0, Choose(("$3",)))
    assert game.state.coins == 0
    assert p0.discard.count("Silver") == 3
    assert "Masterpiece" in p0.discard


def test_advisor_left_player_chooses():
    game = _make_game(["Advisor"])
    p0 = game.state.players[0]
    p0.hand = ["Advisor"]
    p0.deck = ["Copper", "Silver", "Gold"]
    game.apply(0, PlayAction("Advisor"))
    assert game.acting_player == 1  # left player chooses which card p0 discards
    game.apply(1, Choose(("Gold",)))
    assert "Gold" in p0.discard
    assert sorted(p0.hand) == ["Copper", "Silver"]


def test_herald_play_and_overpay():
    game = _make_game(["Herald", "Candlestick Maker"])
    p0 = game.state.players[0]
    p0.hand = ["Herald"]
    # Top of deck is Silver (drawn), then Candlestick Maker (revealed & played!)
    p0.deck = ["Estate", "Candlestick Maker", "Silver"]
    p0.discard = ["Gold", "Duchy"]
    game.apply(0, PlayAction("Herald"))
    assert "Silver" in p0.hand
    assert "Candlestick Maker" in p0.in_play
    assert p0.coffers == 1
    assert game.state.actions == 2
    assert game.state.buys == 2

    # Buy Herald ($4) with $6 -> overpay $2 -> put 2 cards from discard onto deck
    game.apply(0, EndPhase())
    game.state.coins = 6
    game.apply(0, Buy("Herald"))
    game.apply(0, Choose(("$2",)))
    game.apply(0, Choose(("Gold",)))
    game.apply(0, Choose(("Duchy",)))
    assert p0.deck[-2:] == ["Gold", "Duchy"]


def test_taxman_journeyman_merchant_guild_soothsayer():
    game = _make_game(["Taxman", "Journeyman", "Merchant Guild", "Soothsayer"])
    p0, p1 = game.state.players[0], game.state.players[1]

    # Taxman: trash Copper -> p1 with 5 cards discards Copper -> p0 gains Silver onto deck
    p0.hand = ["Taxman", "Copper"]
    p1.hand = ["Copper", "Estate", "Estate", "Estate", "Estate"]
    game.apply(0, PlayAction("Taxman"))
    game.apply(0, Choose(("Copper",)))
    assert "Copper" in p1.discard
    game.apply(0, Choose(("Silver",)))
    assert p0.deck[-1] == "Silver"

    # Journeyman: name Copper -> reveals until 3 non-Coppers
    p0.hand = ["Journeyman"]
    p0.deck = ["Gold", "Copper", "Silver", "Copper", "Estate"]
    game.state.actions = 1
    game.apply(0, PlayAction("Journeyman"))
    game.apply(0, Choose(("Copper",)))
    assert sorted(p0.hand) == ["Estate", "Gold", "Silver"]
    assert p0.discard.count("Copper") == 2

    # Soothsayer: gain Gold, p1 gains Curse and draws 1 card
    p0.hand = ["Soothsayer"]
    p1.deck = ["Province"]
    p1_hand_before = len(p1.hand)
    game.state.actions = 1
    game.apply(0, PlayAction("Soothsayer"))
    assert "Gold" in p0.discard
    assert "Curse" in p1.discard
    assert len(p1.hand) == p1_hand_before + 1

    # If Curse pile is empty, Soothsayer victim does NOT draw a card
    game.state.supply["Curse"] = 0
    p0.hand = ["Soothsayer"]
    p1.deck = ["Duchy"]
    p1_hand_before = len(p1.hand)
    game.state.actions = 1
    game.apply(0, PlayAction("Soothsayer"))
    assert len(p1.hand) == p1_hand_before

    # Merchant Guild: while in play, buying a card gives +1 Coffers per Merchant Guild in play
    p0.hand = ["Merchant Guild"]
    game.state.actions = 1
    game.apply(0, PlayAction("Merchant Guild"))
    assert game.state.buys == 2
    assert game.state.coins == 1
    game.apply(0, EndPhase())
    coffers_before = p0.coffers
    game.apply(0, Buy("Copper"))
    assert p0.coffers == coffers_before + 1
