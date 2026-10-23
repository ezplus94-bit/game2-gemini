"""The Prosperity expansion (2010): all 25 Kingdom cards, Platinum & Colony, VP tokens, and Trade Route."""

import pytest

from dominion.cards import CardType, get_card, kingdom_cards
from dominion.engine import (
    Buy, Choose, EndPhase, GameStatus, IllegalActionError, PlayAction, PlayAllTreasures, PlayTreasure,
    build_view, is_game_over, legal_actions, score_player,
)
from dominion.engine.scoring import vp_breakdown
from helpers import make_game, set_zones, to_buy_phase, total_cards

PROSPERITY = kingdom_cards(["Prosperity"])


def pg(players=2, cards=("Monument",), seed=1, **kw):
    return make_game(players=players, kingdom=[*cards, "Village", "Smithy"], seed=seed, **kw)


def play(g, card, who=None):
    g.apply(g.acting_player if who is None else who, PlayAction(card))


def answer(g, *cards, who=None):
    g.apply(g.acting_player if who is None else who, Choose(tuple(cards)))


def end_turn(g):
    start = g.state.turn_number
    while g.state.status is GameStatus.ACTIVE and g.state.turn_number == start:
        if g.state.pending is not None:
            g.apply(g.acting_player, Choose(()))
        else:
            g.apply(g.acting_player, EndPhase())


def test_prosperity_has_25_kingdom_cards_plus_platinum_and_colony():
    assert len(PROSPERITY) == 25
    assert set(PROSPERITY) == {
        "Loan", "Trade Route", "Watchtower",
        "Bishop", "Monument", "Quarry", "Talisman", "Workers' Village",
        "City", "Contraband", "Counting House", "Mint", "Mountebank", "Rabble", "Royal Seal", "Vault", "Venture",
        "Goons", "Grand Market", "Hoard",
        "Bank", "Expand", "Forge", "King's Court",
        "Peddler",
    }
    assert get_card("Platinum").cost == 9 and get_card("Platinum").coins == 5
    assert get_card("Colony").cost == 11 and get_card("Colony").vp == 10


def test_platinum_and_colony_join_supply_when_prosperity_card_present_and_colony_ends_game():
    g = pg(cards=("Monument",))
    assert g.state.supply["Platinum"] == 12 and g.state.supply["Colony"] == 8
    g.state.supply["Colony"] = 0
    assert is_game_over(g.state)


def test_monument_and_bishop_award_vp_tokens_counted_in_score():
    g = pg(cards=("Monument", "Bishop"))
    set_zones(g, 0, hand=["Monument", "Bishop", "Gold"], deck=["Copper"] * 5, discard=[])
    set_zones(g, 1, hand=["Estate", "Copper"], deck=["Copper"] * 5, discard=[])
    g.state.actions = 2
    play(g, "Monument")
    assert g.state.coins == 2 and g.state.players[0].vp_tokens == 1
    play(g, "Bishop")
    answer(g, "Gold")  # $6 -> +3 VP tokens (+1 base = +4)
    answer(g, "Estate")  # P1 optionally trashes Estate
    assert g.state.players[0].vp_tokens == 5
    assert "Estate" in g.state.trash
    assert score_player(g.state.players[0]) == 5
    assert any(r["card"] == "VP tokens" and r["vp"] == 5 for r in vp_breakdown(g.state.players[0]))


def test_loan_and_venture_and_bank():
    g = pg(cards=("Loan", "Venture", "Bank"))
    set_zones(g, 0, hand=["Loan", "Venture", "Bank"], deck=["Copper", "Estate", "Silver", "Village"])
    to_buy_phase(g)
    g.apply(0, PlayTreasure("Loan"))
    answer(g, "Trash it")  # trashes Silver
    assert "Silver" in g.state.trash and "Village" in g.state.players[0].discard
    g.apply(0, PlayTreasure("Venture"))  # reveals Estate (discarded), then plays Copper
    assert "Copper" in g.state.players[0].in_play
    g.apply(0, PlayTreasure("Bank"))  # Loan + Venture + Copper + Bank = 4 Treasures in play -> +$4
    assert g.state.coins == 1 + 1 + 1 + 4


def test_quarry_and_peddler_cost_reductions():
    g = pg(cards=("Quarry", "Peddler"))
    set_zones(g, 0, hand=["Village", "Quarry"], deck=["Copper"] * 5)
    play(g, "Village")
    to_buy_phase(g)
    # In Buy phase with 1 Action in play: Peddler costs $8 - $2 = $6
    from dominion.engine.costs import card_cost
    assert card_cost(g.state, "Peddler") == 6
    g.apply(0, PlayTreasure("Quarry"))
    # With Quarry in play, Action cards (including Peddler) cost $2 less -> $4
    assert card_cost(g.state, "Peddler") == 4
    assert card_cost(g.state, "Village") == 1


def test_contraband_and_grand_market_buy_restrictions():
    g = pg(cards=("Contraband", "Grand Market"))
    set_zones(g, 0, hand=["Contraband", "Copper", "Gold", "Gold"])
    to_buy_phase(g)
    g.apply(0, PlayTreasure("Contraband"))
    answer(g, "Gold", who=1)  # P1 bans Gold
    g.apply(0, PlayAllTreasures())
    assert Buy("Gold") not in legal_actions(g.state)
    assert Buy("Grand Market") not in legal_actions(g.state)  # Copper is in play
    with pytest.raises(IllegalActionError, match="Contraband"):
        g.apply(0, Buy("Gold"))
    with pytest.raises(IllegalActionError, match="Copper in play"):
        g.apply(0, Buy("Grand Market"))


def test_hoard_talisman_goons_and_mint_on_buy():
    g = pg(cards=("Hoard", "Talisman", "Goons", "Mint"))
    set_zones(g, 0, hand=["Goons", "Hoard", "Talisman", "Gold", "Gold"], discard=[])
    set_zones(g, 1, hand=["Copper"] * 3)
    play(g, "Goons")
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    g.state.buys = 3
    g.state.coins = 20
    g.apply(0, Buy("Estate"))  # Victory -> Hoard gains Gold; Cost <= 4 but Victory so Talisman doesn't copy; Goons +1 VP
    assert "Gold" in g.state.players[0].discard and g.state.players[0].vp_tokens == 1
    g.apply(0, Buy("Village"))  # Non-Victory <= $4 -> Talisman gains a second Village; Goons +1 VP
    assert g.state.players[0].discard.count("Village") == 2 and g.state.players[0].vp_tokens == 2
    g.apply(0, Buy("Mint"))  # Trashes all Treasures in play (Hoard, Talisman, Gold, Gold)
    assert not any(get_card(c).is_type(CardType.TREASURE) for c in g.state.players[0].in_play)


def test_watchtower_and_royal_seal_react_to_gained_cards():
    g = pg(cards=("Watchtower", "Royal Seal"))
    set_zones(g, 0, hand=["Watchtower", "Royal Seal", "Gold"], discard=[])
    to_buy_phase(g)
    g.apply(0, PlayTreasure("Royal Seal"))
    g.apply(0, PlayTreasure("Gold"))
    g.apply(0, Buy("Silver"))
    # Royal Seal asks first, then Watchtower
    answer(g, "Leave it")
    answer(g, "Put on deck")
    assert g.state.players[0].deck[-1] == "Silver"


def test_kings_court_plays_an_action_three_times():
    g = pg(cards=("King's Court", "Monument"))
    set_zones(g, 0, hand=["King's Court", "Monument"])
    play(g, "King's Court")
    answer(g, "Monument")
    assert g.state.coins == 6 and g.state.players[0].vp_tokens == 3
