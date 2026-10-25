"""Comprehensive tests for the Cornucopia expansion (13 Kingdom cards + 5 Prizes + Bane setup)."""

from __future__ import annotations

import pytest

from dominion.cards import CardType, expansions, get_card, kingdom_cards, prize_cards
from dominion.engine import (
    Buy, Choose, EndPhase, GameConfig, IllegalActionError, Phase, PlayAction, PlayTreasure,
    build_view, new_game, score_player,
)


def _make_game(kingdom=None, num_players=2, seed=42, **kw):
    names = ["Alice", "Bob", "Carol", "Dave"][:num_players]
    return new_game(GameConfig(names, kingdom=kingdom or ["Hamlet"], seed=seed, colonies=False, **kw))


def test_cornucopia_registration_and_inventory():
    assert "Cornucopia" in expansions()
    kc = kingdom_cards(["Cornucopia"])
    expected_kingdom = [
        "Fairgrounds", "Farming Village", "Fortune Teller", "Hamlet", "Harvest",
        "Horn of Plenty", "Horse Traders", "Hunting Party", "Jester", "Menagerie",
        "Remake", "Tournament", "Young Witch",
    ]
    assert kc == sorted(expected_kingdom)
    expected_prizes = ["Bag of Gold", "Diadem", "Followers", "Princess", "Trusty Steed"]
    assert prize_cards() == sorted(expected_prizes)
    for name in expected_prizes:
        c = get_card(name)
        assert not c.kingdom
        assert c.is_type(CardType.PRIZE)
        assert c.cost == 0


def test_hamlet_both_discards_and_skip():
    game = _make_game(["Hamlet"])
    p = game.state.players[0]
    p.hand = ["Hamlet", "Copper", "Estate"]
    p.deck = ["Silver"]
    game.apply(0, PlayAction("Hamlet"))
    assert game.state.actions == 1
    assert "Silver" in p.hand
    # Discard Copper for +1 Action
    game.apply(0, Choose(("Copper",)))
    assert game.state.actions == 2
    assert "Copper" in p.discard
    # Discard Estate for +1 Buy
    game.apply(0, Choose(("Estate",)))
    assert game.state.buys == 2
    assert "Estate" in p.discard
    assert game.state.pending is None


def test_hamlet_decline_both():
    game = _make_game(["Hamlet"])
    p = game.state.players[0]
    p.hand = ["Hamlet", "Copper"]
    p.deck = ["Silver"]
    game.apply(0, PlayAction("Hamlet"))
    game.apply(0, Choose(()))
    game.apply(0, Choose(()))
    assert game.state.actions == 1
    assert game.state.buys == 1
    assert len(p.hand) == 2


def test_fortune_teller_reveals_until_victory_or_curse():
    game = _make_game(["Fortune Teller"])
    p0, p1 = game.state.players[0], game.state.players[1]
    p0.hand = ["Fortune Teller"]
    # Top of deck is end of list: Copper, Silver, Estate (so Silver & Copper are revealed first, then Estate)
    p1.deck = ["Gold", "Estate", "Copper", "Silver"]
    p1.discard = []
    game.apply(0, PlayAction("Fortune Teller"))
    assert game.state.coins == 2
    assert p1.deck[-1] == "Estate"
    assert set(p1.discard) == {"Copper", "Silver"}
    assert "Gold" in p1.deck


def test_fortune_teller_no_victory_or_curse_discards_all():
    game = _make_game(["Fortune Teller"])
    p0, p1 = game.state.players[0], game.state.players[1]
    p0.hand = ["Fortune Teller"]
    p1.deck = ["Copper", "Silver"]
    p1.discard = ["Gold"]
    game.apply(0, PlayAction("Fortune Teller"))
    assert p1.deck == []
    assert sorted(p1.discard) == ["Copper", "Gold", "Silver"]


def test_menagerie_unique_vs_duplicate_hand():
    game = _make_game(["Menagerie"])
    p = game.state.players[0]
    p.hand = ["Menagerie", "Copper", "Estate", "Silver"]
    p.deck = ["Gold", "Duchy", "Province"]
    game.apply(0, PlayAction("Menagerie"))
    assert game.state.actions == 1
    assert len(p.hand) == 6  # 3 kept + 3 drawn

    # Now with duplicates
    game2 = _make_game(["Menagerie"])
    p2 = game2.state.players[0]
    p2.hand = ["Menagerie", "Copper", "Copper"]
    p2.deck = ["Gold", "Duchy", "Province"]
    game2.apply(0, PlayAction("Menagerie"))
    assert len(p2.hand) == 3  # 2 kept + 1 drawn


def test_farming_village_finds_action_or_treasure():
    game = _make_game(["Farming Village"])
    p = game.state.players[0]
    p.hand = ["Farming Village"]
    # Top of deck is end: Curse, Estate, Silver, Gold
    p.deck = ["Gold", "Silver", "Estate", "Curse"]
    game.apply(0, PlayAction("Farming Village"))
    assert game.state.actions == 2
    assert p.hand == ["Silver"]
    assert sorted(p.discard) == ["Curse", "Estate"]
    assert p.deck == ["Gold"]


def test_horse_traders_play_and_reaction():
    game = _make_game(["Horse Traders", "Militia"])
    p0, p1 = game.state.players[0], game.state.players[1]
    p0.hand = ["Militia"]
    p1.hand = ["Horse Traders", "Copper", "Copper", "Estate", "Estate"]
    p1.deck = ["Gold"]

    game.apply(0, PlayAction("Militia"))
    # p1 is asked whether to reveal Horse Traders first
    assert game.acting_player == 1
    game.apply(1, Choose(("Horse Traders",)))
    assert "Horse Traders" in p1.horse_traders
    assert "Horse Traders" not in p1.hand
    # Now p1 has 4 cards in hand, so Militia asks p1 to discard 1 card down to 3
    assert game.acting_player == 1
    game.apply(1, Choose(("Estate",)))
    assert len(p1.hand) == 3

    # End p0's turn -> start of p1's turn returns Horse Traders to hand and draws 1 card
    game.apply(0, EndPhase())
    game.apply(0, EndPhase())
    assert game.state.current_player == 1
    assert p1.horse_traders == []
    assert "Horse Traders" in p1.hand
    assert "Gold" in p1.hand

    # Play Horse Traders on p1's turn
    game.apply(1, PlayAction("Horse Traders"))
    assert game.state.buys == 2
    assert game.state.coins == 3
    game.apply(1, Choose(("Copper", "Copper")))
    assert game.state.pending is None


def test_remake_trashes_twice_and_gains_exact_plus_one():
    game = _make_game(["Remake", "Hamlet", "Menagerie", "Farming Village"])
    p = game.state.players[0]
    p.hand = ["Remake", "Copper", "Estate"]
    game.apply(0, PlayAction("Remake"))
    # First trash: Copper ($0) -> nothing costs $1, so no gain prompt for Copper
    game.apply(0, Choose(("Copper",)))
    assert "Copper" in game.state.trash
    # Second trash: Only Estate ($2) remains in hand -> choose Estate, then gain Menagerie ($3) or Silver ($3)
    game.apply(0, Choose(("Estate",)))
    assert "Estate" in game.state.trash
    game.apply(0, Choose(("Menagerie",)))
    assert "Menagerie" in p.discard
    assert game.state.pending is None


def test_tournament_prizes_setup_and_branches():
    game = _make_game(["Tournament"])
    assert len(game.state.prizes) == 5
    p0, p1 = game.state.players[0], game.state.players[1]

    # Branch 1: p0 reveals Province, p1 does not -> p0 gets Prize on deck AND +1 Card, +$1
    p0.hand = ["Tournament", "Province"]
    p0.deck = ["Copper"]
    p1.hand = ["Province", "Estate"]
    game.apply(0, PlayAction("Tournament"))
    game.apply(0, Choose(("Province",)))  # p0 reveals Province
    game.apply(1, Choose(()))             # p1 declines to reveal Province
    # p0 picks Bag of Gold onto deck, then draws 1 card (which draws the Bag of Gold just put on deck!)
    game.apply(0, Choose(("Bag of Gold",)))
    assert "Bag of Gold" not in game.state.prizes
    assert "Bag of Gold" in p0.hand       # put on deck, then drawn by +1 Card!
    assert game.state.coins == 1
    assert game.state.actions == 1

    # Branch 2: p1 reveals Province -> p0 does NOT get +1 Card / +$1
    p0.hand = ["Tournament"]
    p1.hand = ["Province"]
    game.apply(0, PlayAction("Tournament"))
    game.apply(1, Choose(("Province",)))
    assert game.state.coins == 1  # unchanged


def test_all_five_prizes_effects():
    game = _make_game(["Tournament", "Village"])
    p0, p1 = game.state.players[0], game.state.players[1]

    # 1. Bag of Gold
    p0.hand = ["Bag of Gold"]
    game.apply(0, PlayAction("Bag of Gold"))
    assert game.state.actions == 1
    assert p0.deck[-1] == "Gold"

    # 2. Princess (+1 Buy, costs $2 less while in play)
    p0.hand = ["Princess"]
    game.apply(0, PlayAction("Princess"))
    assert game.state.buys == 2
    from dominion.engine.costs import card_cost
    assert card_cost(game.state, "Province") == 6
    assert card_cost(game.state, "Estate") == 0

    # 3. Followers (+2 Cards, gain Estate, attack: gain Curse & discard to 3)
    p0.hand = ["Followers"]
    p0.deck = ["Copper", "Silver"]
    p1.hand = ["Copper", "Copper", "Copper", "Estate", "Estate"]
    game.state.actions = 1
    game.apply(0, PlayAction("Followers"))
    game.apply(1, Choose(("Estate", "Estate")))
    assert "Estate" in p0.discard
    assert "Curse" in p1.discard
    assert len(p1.hand) == 3

    # 4. Trusty Steed (choose 2)
    p0.hand = ["Trusty Steed"]
    p0.deck = ["Copper", "Silver"]
    game.state.actions = 1
    game.apply(0, PlayAction("Trusty Steed"))
    game.apply(0, Choose(("+2 Actions", "Gain 4 Silvers and put your deck into your discard pile")))
    assert game.state.actions == 2
    assert p0.deck == []
    assert p0.discard.count("Silver") >= 4

    # 5. Diadem ($2 + $1 per unused Action)
    p0.hand = ["Diadem"]
    game.state.actions = 3
    game.apply(0, EndPhase())  # move to Buy phase with 3 unused Actions
    game.apply(0, PlayTreasure("Diadem"))
    assert game.state.coins >= 5  # $2 base + $3 from 3 unused Actions


def test_young_witch_bane_setup_and_reveal():
    game = _make_game(["Young Witch"], bane="Hamlet")
    assert game.state.bane == "Hamlet"
    assert "Hamlet" in game.state.supply
    view = build_view(game, 0)
    assert view["bane"] == "Hamlet"

    p0, p1 = game.state.players[0], game.state.players[1]
    p0.hand = ["Young Witch", "Copper", "Estate"]
    p0.deck = ["Silver", "Gold"]
    p1.hand = ["Hamlet", "Copper"]

    game.apply(0, PlayAction("Young Witch"))
    game.apply(0, Choose(("Copper", "Estate")))
    # p1 reveals Bane (Hamlet) to avoid Curse
    game.apply(1, Choose(("Hamlet",)))
    assert "Curse" not in p1.discard

    # Without revealing Bane, p1 gains a Curse
    p0.hand.append("Young Witch")
    game.state.actions = 1
    game.apply(0, PlayAction("Young Witch"))
    game.apply(0, Choose((p0.hand[0], p0.hand[1])))
    game.apply(1, Choose(()))
    assert "Curse" in p1.discard


def test_harvest_and_horn_of_plenty_and_hunting_party_and_jester_and_fairgrounds():
    game = _make_game(["Harvest", "Horn of Plenty", "Hunting Party", "Jester", "Fairgrounds"])
    p0, p1 = game.state.players[0], game.state.players[1]

    # Harvest: 3 distinct names in top 4 cards -> +$3
    p0.hand = ["Harvest"]
    p0.deck = ["Copper", "Copper", "Silver", "Gold"]
    game.apply(0, PlayAction("Harvest"))
    assert game.state.coins == 3

    # Hunting Party: +1 Card, +1 Action, searches deck for card not in hand
    p0.hand = ["Hunting Party", "Copper"]
    p0.deck = ["Province", "Copper", "Copper", "Silver"]  # top is Silver -> drawn into hand; then Copper, Copper skipped, Province taken
    game.state.actions = 1
    game.apply(0, PlayAction("Hunting Party"))
    assert "Silver" in p0.hand
    assert "Province" in p0.hand

    # Jester: +$2, discards top of p1's deck
    p0.hand = ["Jester"]
    p1.deck = ["Gold", "Estate"]  # top is Estate -> Victory, so p1 gains Curse
    game.state.actions = 1
    game.apply(0, PlayAction("Jester"))
    assert "Curse" in p1.discard

    # Jester with non-Victory (Gold): p0 chooses to gain a copy
    p0.hand = ["Jester"]
    game.state.actions = 1
    game.apply(0, PlayAction("Jester"))
    game.apply(0, Choose(("You gain Gold",)))
    assert "Gold" in p0.discard

    # Horn of Plenty: played in Buy phase; counts distinct names in play; trashes self if Victory gained
    p0.hand = ["Horn of Plenty"]
    # Currently in play: Harvest, Hunting Party, Jester, Jester (3 distinct) + Horn of Plenty = 4 distinct
    game.apply(0, EndPhase())
    game.apply(0, PlayTreasure("Horn of Plenty"))
    game.apply(0, Choose(("Estate",)))  # Victory card -> Horn of Plenty trashes itself!
    assert "Estate" in p0.discard
    assert "Horn of Plenty" in game.state.trash
    assert "Horn of Plenty" not in p0.in_play

    # Fairgrounds scoring: 2 VP per 5 differently named cards
    p0.deck = ["Copper", "Silver", "Gold", "Estate", "Duchy", "Province", "Curse", "Harvest", "Jester", "Fairgrounds"]
    p0.hand, p0.discard, p0.in_play = [], [], []
    assert get_card("Fairgrounds").victory_points(p0.all_cards()) == 4
