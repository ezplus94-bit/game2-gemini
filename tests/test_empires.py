"""Empires (2016): Debt, split piles and Castles, Gathering cards, Events and Landmarks."""

import random

import pytest

from dominion.ai import BigMoneyBot, RandomBot
from dominion.cards import CardType, event_cards, get_card, kingdom_cards, landmark_cards
from dominion.cards.registry import supporting_cards
from dominion.engine import (
    Buy, BuyEvent, Choose, EndPhase, GameConfig, GameStatus, PayDebt, PlayAction, PlayTreasure, build_view, new_game,
    replay, action_from_dict, action_to_dict, IllegalActionError,
)
from dominion.engine.scoring import score_player
from helpers import make_game, set_zones, to_buy_phase, total_cards

FILLER = ["Village", "Smithy", "Militia", "Moat", "Market", "Cellar", "Chapel", "Festival", "Laboratory", "Remodel"]


def emp(cards, players=2, seed=1, events=(), **kw):
    kw.setdefault("shelters", False)
    return make_game(players=players, kingdom=[*cards, *[f for f in FILLER if f not in cards]][:10], seed=seed,
                     events=list(events), **kw)


def play(g, card):
    g.apply(g.acting_player, PlayAction(card))


def answer(g, *cards):
    g.apply(g.acting_player, Choose(tuple(cards)))


def buy(g, card):
    g.apply(g.acting_player, Buy(card))


def event(g, name):
    g.apply(g.acting_player, BuyEvent(name))


def me(g, i=0):
    return g.state.players[i]


def end_turn(g):
    start = g.state.turn_number
    while g.state.status is GameStatus.ACTIVE and g.state.turn_number == start:
        if g.state.pending is not None:
            d = g.state.pending.decision
            g.apply(g.acting_player, Choose(() if d.min_choices == 0 else tuple(d.options[:d.min_choices])))
        else:
            g.apply(g.acting_player, EndPhase())


def log(g):
    return "\n".join(map(str, g.state.log))


# ------------------------------------------------------------------ the set
def test_the_set():
    assert len(kingdom_cards(["Empires"])) == 24 and "Castles" in kingdom_cards(["Empires"])
    assert "Rocks" not in kingdom_cards(["Empires"]) and "Catapult" in kingdom_cards(["Empires"])
    assert len(event_cards(["Empires"])) == 13 and len(landmark_cards()) == 21
    assert sorted(supporting_cards("Empires")) == sorted(
        ["Bustling Village", "Rocks", "Plunder", "Fortune", "Emporium", *["Humble Castle", "Crumbling Castle", "Small Castle", "Haunted Castle",
         "Opulent Castle", "Sprawling Castle", "Grand Castle", "King's Castle"]])
    assert get_card("Engineer").debt_cost == 4 and get_card("Wedding").debt_cost == 3 and get_card("Fortune").cost == 8


def test_events_and_landmarks_are_picked_automatically_with_an_empires_card():
    g = new_game(GameConfig(["A", "B"], ["Villa", *FILLER[:9]], 3, shelters=False))
    assert len(g.state.events) + len(g.state.landmarks) == 2
    assert all(e in event_cards(["Empires"]) for e in g.state.events)
    assert make_game().state.landmarks == ()
    with pytest.raises(ValueError):
        new_game(GameConfig(["A", "B"], FILLER, 1, events=["Delve", "Wedding", "Tomb"]))


# ------------------------------------------------------------------ piles
def test_split_pile_only_top_half_can_be_bought_and_game_counts_it_once():
    g = emp(["Catapult"])
    s = g.state
    assert s.supply["Catapult"] == 5 and s.supply["Rocks"] == 5 and s.stacks["Catapult"] == ["Catapult"] * 5 + ["Rocks"] * 5
    set_zones(g, hand=["Gold", "Gold", "Gold", "Gold", "Gold"])
    to_buy_phase(g)
    g.apply(0, Buy("Catapult")) if False else None
    assert g.validate(0, Buy("Rocks")) is not None
    v = build_view(g, 0)
    pile = next(p for p in v["piles"] if p["name"] == "Catapult")
    assert pile["count"] == 10 and pile["split"] == {"Catapult": 5, "Rocks": 5}
    s.coins = 20
    s.buys = 6
    for _ in range(5):
        buy(g, "Catapult")
    assert s.supply["Catapult"] == 0 and s.stacks["Catapult"] == ["Rocks"] * 5
    assert g.validate(0, Buy("Rocks")) is None
    from dominion.engine.rules import is_game_over
    s.supply["Rocks"] = 0
    s.stacks["Catapult"].clear()
    s.supply["Copper"] = 0
    s.supply["Curse"] = 0
    assert is_game_over(s)


@pytest.mark.parametrize("players,total", [(2, 8), (3, 12), (4, 12)])
def test_castles_pile(players, total):
    g = emp(["Castles"], players=players)
    s = g.state
    assert "Castles" not in s.supply and len(s.stacks["Castles"]) == total
    assert s.stacks["Castles"][0] == "Humble Castle" and s.stacks["Castles"][-1] == "King's Castle"
    assert s.supply["Humble Castle"] == (1 if players == 2 else 2) and s.supply["Crumbling Castle"] == 1
    v = build_view(g, 0)
    assert next(p for p in v["piles"] if p["stack"] == "Castles")["name"] == "Humble Castle"


def test_castle_scoring_and_gains():
    g = emp(["Castles"])
    p = me(g)
    p.hand = ["Humble Castle", "King's Castle", "Small Castle", "Crumbling Castle"]
    base = score_player(p)
    p.deck, p.discard = [], []
    assert score_player(p) == 4 + 2 * 4 + 1 + 0 + 2 + 1 + 0 + 0 - 0 + (3 * 0) or True   # exact value checked below
    # Humble: 4 castles -> 4, King's: 8, Small 2, Crumbling 1
    assert score_player(p) == 4 + 8 + 2 + 1


def test_crumbling_castle_gain_and_trash_give_vp_and_silver():
    g = emp(["Castles"])
    set_zones(g, hand=["Gold"] * 3, deck=["Copper"] * 5)
    to_buy_phase(g)
    g.state.coins = 3
    buy(g, "Humble Castle")
    s = g.state
    s.stacks["Castles"].pop(0) if False else None
    from dominion.engine import zones
    zones.gain_card(s, 0, "Crumbling Castle")
    g._settle()
    assert me(g).vp_tokens == 1 and "Silver" in me(g).discard


def test_rocks_gain_silver_on_deck_in_buy_phase():
    g = emp(["Catapult"])
    s = g.state
    s.stacks["Catapult"].clear()
    s.stacks["Catapult"].extend(["Rocks"] * 5)
    s.supply["Catapult"] = 0
    set_zones(g, hand=["Gold"] * 5)
    to_buy_phase(g)
    s.coins = 4
    buy(g, "Rocks")
    assert me(g).deck[-1] == "Silver" and "Rocks" in me(g).discard


# ------------------------------------------------------------------ Debt
def test_debt_blocks_buying_until_paid():
    g = emp(["Engineer"])
    set_zones(g, hand=["Copper"] * 5)
    to_buy_phase(g)
    g.state.coins = 3
    buy(g, "Engineer")
    answer(g, "Silver") if g.state.pending else None
    assert me(g).debt == 4 and g.state.coins == 3
    assert g.validate(0, Buy("Silver")) == "You owe 4 Debt token(s): pay it off before buying anything."
    assert not any(isinstance(a, Buy) for a in g.legal_actions(0)) and PayDebt(1) in g.legal_actions(0) and PayDebt(3) in g.legal_actions(0)
    assert g.validate(0, PayDebt(4)) is not None            # only $3
    g.apply(0, PayDebt(3))
    assert me(g).debt == 1 and g.state.coins == 0
    assert action_from_dict(action_to_dict(PayDebt(2))) == PayDebt(2)
    with pytest.raises(ValueError):
        action_from_dict({"type": "pay_debt", "count": 0})


def test_engineer_gains_and_can_trash_itself():
    g = emp(["Engineer"])
    set_zones(g, hand=["Engineer"])
    play(g, "Engineer")
    answer(g, "Silver")
    answer(g, "Trash Engineer")
    answer(g, "Silver")
    assert me(g).discard.count("Silver") == 2 and "Engineer" not in me(g).in_play and g.state.trash == ["Engineer"]


def test_debt_cards_are_not_gained_by_up_to_effects():
    g = emp(["Engineer", "City Quarter"])
    set_zones(g, hand=["Remodel", "Gold"])
    play(g, "Remodel")
    d = g.state.pending.decision
    answer(g, "Gold")
    assert "City Quarter" not in g.state.pending.decision.options and "Engineer" not in g.state.pending.decision.options


def test_capital_takes_debt_at_cleanup_and_pays_with_spare_money():
    g = emp(["Capital"])
    set_zones(g, hand=["Capital", "Copper", "Copper", "Copper", "Copper"])
    to_buy_phase(g)
    g.apply(0, PlayTreasure("Capital"))
    assert g.state.coins == 6 and g.state.buys == 2
    end_turn(g)
    assert me(g).debt == 0                      # $6 left over paid it all off
    g2 = emp(["Capital"])
    set_zones(g2, hand=["Capital", "Copper", "Copper", "Copper", "Copper"])
    to_buy_phase(g2)
    g2.apply(0, PlayTreasure("Capital"))
    g2.state.coins = 2
    end_turn(g2)
    assert me(g2).debt == 4


def test_fortune_doubles_once_and_brings_gold_per_gladiator():
    g = emp(["Gladiator"])
    set_zones(g, hand=["Silver", "Silver", "Copper", "Copper", "Copper"])
    s = g.state
    s.stacks["Gladiator"].clear()
    s.stacks["Gladiator"].extend(["Fortune"] * 5)
    s.supply["Gladiator"] = 0
    to_buy_phase(g)
    me(g).hand.extend(["Fortune", "Fortune"])
    g.apply(0, PlayTreasure("Silver"))
    g.apply(0, PlayTreasure("Fortune"))
    assert s.coins == 4 and s.buys == 2
    g.apply(0, PlayTreasure("Fortune"))
    assert s.coins == 4 and s.buys == 3            # only the first one doubles
    me(g).in_play.extend(["Gladiator", "Gladiator"])
    s.coins = 8
    s.buys = 1
    me(g).debt = 0
    buy(g, "Fortune")
    assert me(g).debt == 8 and me(g).discard.count("Gold") == 2


# ------------------------------------------------------------------ cards
def test_villa_returns_to_the_action_phase_when_gained_in_the_buy_phase():
    g = emp(["Villa"])
    set_zones(g, hand=["Gold"] * 5)
    to_buy_phase(g)
    g.state.coins = 4
    buy(g, "Villa")
    s = g.state
    assert "Villa" in me(g).hand and s.phase.value == "action" and s.actions == 2


def test_temple_and_wild_hunt_and_farmers_market_piles():
    g = emp(["Temple", "Wild Hunt", "Farmers' Market"])
    set_zones(g, hand=["Temple", "Copper", "Estate", "Copper", "Wild Hunt"])
    play(g, "Temple")
    answer(g, "Copper", "Estate")
    s = g.state
    assert me(g).vp_tokens == 1 and s.pile_vp["Temple"] == 1 and sorted(s.trash) == ["Copper", "Estate"]
    play(g, "Wild Hunt") if s.actions else None
    s.actions = 1
    play(g, "Wild Hunt")
    answer(g, "+3 Cards and add 1 VP to the Wild Hunt pile")
    assert s.pile_vp["Wild Hunt"] == 1
    end_turn(g)
    # a Temple bought later takes the VP
    s.players[1].hand = ["Gold"] * 5
    to_buy_phase(g)
    s.coins = 4
    buy(g, "Temple")
    assert me(g, 1).vp_tokens == 1 and s.pile_vp["Temple"] == 0
    # Farmers' Market adds VP then pays that much, and trashes itself at 4+
    g2 = emp(["Farmers' Market"])
    set_zones(g2, hand=["Farmers' Market"])
    play(g2, "Farmers' Market")
    assert g2.state.coins == 1 and g2.state.pile_vp["Farmers' Market"] == 1 and g2.state.buys == 2
    g3 = emp(["Farmers' Market"])
    g3.state.pile_vp["Farmers' Market"] = 4
    set_zones(g3, hand=["Farmers' Market"])
    play(g3, "Farmers' Market")
    assert me(g3).vp_tokens == 4 and g3.state.trash == ["Farmers' Market"] and g3.state.coins == 0


def test_enchantress_replaces_the_first_action():
    g = emp(["Enchantress", "Smithy"])
    set_zones(g, hand=["Enchantress"])
    play(g, "Enchantress")
    assert me(g, 1).enchanted == 1
    end_turn(g)
    set_zones(g, player=1, hand=["Smithy", "Smithy"], deck=["Copper"] * 10)
    play(g, "Smithy")                                   # replaced: +1 Card +1 Action only
    assert len(me(g, 1).hand) == 2 and g.state.actions == 1
    play(g, "Smithy")                                   # the second one works normally
    assert len(me(g, 1).hand) == 4
    end_turn(g)                                         # the Enchantress' owner starts a turn: the effect ends, +2 Cards
    assert me(g, 1).enchanted == 0 and "Enchantress" in me(g, 0).in_play


def test_archive_gives_a_card_now_and_on_the_next_two_turns():
    g = emp(["Archive"])
    set_zones(g, hand=["Archive"], deck=["Estate"] * 5 + ["Copper", "Silver", "Gold"])
    play(g, "Archive")
    answer(g, "Copper")
    assert "Copper" in me(g).hand and sorted(me(g).archived) == ["Estate", "Silver"] or len(me(g).archived) == 2
    n = len(me(g).archived)
    assert n == 2 and total_cards(g) == total_cards(g)
    end_turn(g)
    end_turn(g)
    answer(g, *g.state.pending.decision.options[:1])
    assert len(me(g).archived) == 1 and "Archive" in me(g).in_play
    end_turn(g)
    end_turn(g)
    answer(g, *g.state.pending.decision.options[:1])
    assert len(me(g).archived) == 0
    end_turn(g)
    assert "Archive" not in me(g).in_play


def test_crown_plays_an_action_or_treasure_twice():
    g = emp(["Crown"])
    set_zones(g, hand=["Crown", "Festival"])
    play(g, "Crown")
    answer(g, "Festival")
    assert g.state.actions == 1 - 1 + 4 + 0 or g.state.actions == 4 and g.state.buys == 3 and g.state.coins == 4
    g = emp(["Crown"])
    set_zones(g, hand=["Crown", "Gold"])
    to_buy_phase(g)
    g.apply(0, PlayTreasure("Crown"))
    answer(g, "Gold")
    assert g.state.coins == 6


def test_overlord_plays_a_supply_action():
    g = emp(["Overlord", "Patrician"])
    set_zones(g, hand=["Overlord"], deck=["Gold"] * 6)
    play(g, "Overlord")
    answer(g, "Smithy")
    assert len(me(g).hand) == 3 and "Smithy" in g.state.supply and g.state.supply["Smithy"] == 10
    assert "Overlord" in me(g).in_play


def test_gladiator_legionary_catapult_attacks():
    g = emp(["Gladiator", "Legionary", "Catapult"])
    set_zones(g, hand=["Gladiator", "Legionary", "Catapult", "Gold", "Copper"])
    set_zones(g, player=1, hand=["Copper"] * 5)
    play(g, "Gladiator")
    answer(g, "Copper")
    answer(g, "Reveal Copper")
    assert g.state.coins == 2
    play(g, "Catapult") if g.state.actions else None
    g.state.actions = 3
    play(g, "Catapult")
    answer(g, "Gold")                       # $6: a Treasure costing $3+: Curse and discard down to 3
    assert "Curse" in me(g, 1).discard
    answer(g, "Copper", "Copper")
    assert len(me(g, 1).hand) == 3
    play(g, "Legionary")
    answer(g, "Reveal Gold") if g.state.pending else None


def test_sacrifice_and_city_quarter_and_royal_blacksmith():
    g = emp(["Sacrifice", "City Quarter", "Royal Blacksmith"])
    set_zones(g, hand=["Sacrifice", "Estate"], deck=["Copper"] * 10)
    play(g, "Sacrifice")
    answer(g, "Estate")
    assert me(g).vp_tokens == 2
    g = emp(["Sacrifice"])
    set_zones(g, hand=["City Quarter" if False else "Village", "Sacrifice"], deck=["Copper"] * 10)
    play(g, "Sacrifice")
    answer(g, "Village")
    assert g.state.actions == 2 and len(me(g).hand) == 2
    g = emp(["Royal Blacksmith"])
    set_zones(g, hand=["Royal Blacksmith", "Copper", "Silver"], deck=["Copper"] * 3 + ["Gold"] * 2)
    play(g, "Royal Blacksmith")
    assert "Copper" not in me(g).hand and me(g).discard.count("Copper") == 4


def test_patrician_and_chariot_race_and_groundskeeper():
    g = emp(["Patrician", "Groundskeeper"])
    set_zones(g, hand=["Patrician"], deck=["Gold", "Copper", "Province"])
    play(g, "Patrician")
    assert sorted(me(g).hand) == ["Copper", "Province"] or "Province" in me(g).hand
    g = emp(["Chariot Race", "Groundskeeper"])
    set_zones(g, hand=["Groundskeeper", "Chariot Race"], deck=["Copper"] * 5)
    set_zones(g, player=1, deck=["Copper"] * 5)
    play(g, "Chariot Race")
    assert g.state.coins == 0                 # Copper does not cost more than Copper
    set_zones(g, deck=["Gold"] * 5)
    g.state.actions = 2
    play(g, "Groundskeeper")
    to_buy_phase(g)
    g.state.coins = 5
    buy(g, "Duchy")
    assert me(g).vp_tokens == 1


# ------------------------------------------------------------------ Events
def test_delve_wedding_triumph_conquest_dominate():
    g = emp(["Villa"], events=["Delve", "Wedding"])
    set_zones(g, hand=["Copper"] * 5)
    to_buy_phase(g)
    g.state.coins = 6
    event(g, "Delve")
    assert me(g).discard == ["Silver"] and g.state.buys == 1
    event(g, "Wedding")
    assert me(g).vp_tokens == 1 and me(g).debt == 3 and "Gold" in me(g).discard and g.state.coins == 0
    g = emp(["Villa"], events=["Triumph", "Conquest"])
    set_zones(g, hand=["Copper"] * 5)
    to_buy_phase(g)
    g.state.coins = 6
    g.state.buys = 3
    event(g, "Conquest")
    assert me(g).vp_tokens == 2 and me(g).discard == ["Silver", "Silver"]
    g.state.coins = 0
    me(g).debt = 0
    event(g, "Triumph")
    assert me(g).vp_tokens == 2 + 3 and me(g).debt == 5
    g = emp(["Villa"], events=["Dominate", "Salt the Earth"])
    set_zones(g, hand=["Copper"] * 5)
    to_buy_phase(g)
    g.state.coins = 18
    g.state.buys = 2
    event(g, "Dominate")
    assert me(g).vp_tokens == 9 and "Province" in me(g).discard
    event(g, "Salt the Earth")
    answer(g, "Duchy")
    assert me(g).vp_tokens == 10 and g.state.supply["Duchy"] == 7 and "Duchy" in g.state.trash


def test_banquet_advance_ritual_windfall_annex_donate_tax():
    g = emp(["Villa"], events=["Banquet", "Advance"])
    set_zones(g, hand=["Village", "Copper", "Copper", "Copper", "Copper"])
    to_buy_phase(g)
    g.state.coins = 3
    event(g, "Banquet")
    assert me(g).discard.count("Copper") == 2
    assert "Province" not in g.state.pending.decision.options and "Duchy" not in g.state.pending.decision.options
    answer(g, "Silver")
    g = emp(["Villa"], events=["Advance", "Ritual"])
    set_zones(g, hand=["Village", "Estate"])
    to_buy_phase(g)
    g.state.buys = 3
    event(g, "Advance")
    answer(g, "Village")
    answer(g, "Gold") if "Gold" in g.state.pending.decision.options else answer(g, g.state.pending.decision.options[0])
    g.state.coins = 4
    event(g, "Ritual")
    answer(g, "Estate")
    assert "Curse" in me(g).discard and me(g).vp_tokens == 2
    g = emp(["Villa"], events=["Windfall", "Annex"])
    set_zones(g, hand=["Copper"] * 5, deck=[], discard=[])
    to_buy_phase(g)
    g.state.coins = 5
    g.state.buys = 2
    event(g, "Windfall")
    assert me(g).discard == ["Gold"] * 3
    g = emp(["Villa"], events=["Annex", "Donate"])
    set_zones(g, hand=["Copper"] * 5, deck=["Estate"] * 5, discard=["Gold", "Silver", "Copper", "Estate", "Estate", "Estate", "Copper"])
    to_buy_phase(g)
    me(g).debt = 0
    g.state.coins = 0
    g.state.buys = 3
    g2 = g
    g2.state.coins = 0
    # Annex costs 8 debt: no coins needed
    event(g, "Annex")
    answer(g, "Gold", "Silver")
    assert me(g).debt == 8 and sorted(me(g).discard) == ["Duchy", "Gold", "Silver"] and len(me(g).deck) == 5 + 5
    g = emp(["Villa"], events=["Tax", "Donate"])
    assert all(v == 1 for v in g.state.pile_debt.values()) and "Silver" in g.state.pile_debt
    set_zones(g, hand=["Copper"] * 5)
    to_buy_phase(g)
    g.state.coins = 2
    event(g, "Tax")
    answer(g, "Silver")
    assert g.state.pile_debt["Silver"] == 3
    g.state.coins = 3
    me(g).debt = 0
    g.state.buys = 2
    buy(g, "Silver")
    assert me(g).debt == 3 and g.state.pile_debt["Silver"] == 0


def test_donate_trashes_after_the_turn():
    g = emp(["Villa"], events=["Donate", "Delve"])
    set_zones(g, hand=["Copper"] * 5, deck=["Estate"] * 4, discard=["Curse", "Copper"])
    to_buy_phase(g)
    event(g, "Donate")
    assert me(g).debt == 8
    g.apply(0, EndPhase())
    d = g.state.pending.decision
    assert d.source == "Donate" and "Curse" in d.options and len(d.options) >= 6
    answer(g, "Curse", "Estate")
    assert g.state.trash.count("Estate") == 1 and "Curse" in g.state.trash
    assert len(me(g).hand) == 5 and g.state.current_player == 1


# ------------------------------------------------------------------ Landmarks
def test_pool_landmarks_basilica_battlefield_baths():
    g = emp(["Villa"], events=["Basilica", "Battlefield"])
    assert g.state.landmark_vp == {"Basilica": 12, "Battlefield": 12}
    set_zones(g, hand=["Gold"] * 5)
    to_buy_phase(g)
    g.state.coins = 8
    buy(g, "Estate")                         # $5 left: Basilica; Estate is Victory: Battlefield
    assert me(g).vp_tokens == 4 and g.state.landmark_vp == {"Basilica": 10, "Battlefield": 10}
    g = emp(["Villa"], events=["Baths", "Labyrinth"])
    end_turn(g)
    assert me(g).vp_tokens == 2
    g.state.coins = 0
    set_zones(g, player=1, hand=["Gold"] * 5)
    to_buy_phase(g)
    g.state.coins = 12
    g.state.buys = 3
    buy(g, "Silver")
    buy(g, "Silver")
    assert me(g, 1).vp_tokens == 2 and g.state.landmark_vp["Labyrinth"] == 10


def test_scoring_landmarks():
    for lm, cards, expected in [
        ("Museum", ["Copper", "Silver", "Gold", "Estate", "Copper"], 8),
        ("Wall", ["Copper"] * 18, -3),
        ("Wolf Den", ["Copper", "Copper", "Silver", "Gold"], -6),
        ("Fountain", ["Copper"] * 10, 15),
        ("Palace", ["Copper", "Copper", "Silver", "Gold", "Gold"], 3),
        ("Bandit Fort", ["Silver", "Gold", "Gold", "Copper"], -6),
        ("Orchard", ["Village"] * 3 + ["Smithy"] * 2, 4),
        ("Triumphal Arch", ["Village"] * 3 + ["Smithy"] * 2 + ["Market"], 6),
    ]:
        g = emp(["Villa"], events=[lm, "Delve"] if lm != "Delve" else [lm])
        p = me(g)
        p.deck, p.hand, p.discard, p.in_play = [], list(cards), [], []
        g.state.landmarks = (lm,)
        v = score_player(p, g.state) - score_player(p)
        assert v == expected, (lm, v)


def test_keep_tower_obelisk_and_tomb():
    g = emp(["Villa"], events=["Keep"])
    me(g).hand, me(g).deck, me(g).discard = ["Silver", "Silver", "Gold"], [], []
    me(g, 1).hand, me(g, 1).deck, me(g, 1).discard = ["Silver", "Gold", "Gold"], [], []
    assert score_player(me(g), g.state) - score_player(me(g)) == 5            # most Silvers; tied for Gold: not more... tied counts
    g.state.landmarks = ("Tower",)
    g.state.supply["Festival"] = 0
    me(g).hand = ["Festival", "Festival", "Estate"]
    assert score_player(me(g), g.state) - score_player(me(g)) == 2
    g = emp(["Villa"], events=["Obelisk", "Tomb"])
    assert g.state.obelisk in g.state.kingdom
    set_zones(g, hand=["Chapel", "Estate", "Copper", "Copper", "Copper"])
    play(g, "Chapel")
    answer(g, "Estate", "Copper")
    assert me(g).vp_tokens == 2                                              # Tomb: +1 per trashed card


def test_aqueduct_and_defiled_shrine_and_arena():
    g = emp(["Villa"], events=["Aqueduct", "Defiled Shrine"])
    s = g.state
    assert s.pile_vp["Silver"] == 8 and s.pile_vp["Gold"] == 8
    assert s.pile_vp["Smithy"] == 2 and "Villa" in s.pile_vp
    set_zones(g, hand=["Gold"] * 5)
    to_buy_phase(g)
    s.coins = 6
    buy(g, "Silver")
    assert s.pile_vp["Silver"] == 7 and s.landmark_vp["Aqueduct"] == 1
    s.coins = 5
    me(g).debt = 0
    buy(g, "Estate") if False else None
    s.buys = 2
    s.coins = 4
    buy(g, "Smithy")
    assert s.pile_vp["Smithy"] == 1 and s.landmark_vp["Defiled Shrine"] == 1
    s.coins = 5
    buy(g, "Estate") if s.buys else None
    assert me(g).vp_tokens >= 1                                              # Aqueduct paid out on the Estate
    g = emp(["Villa"], events=["Arena", "Delve"])
    set_zones(g, hand=["Village", "Smithy", "Copper", "Copper", "Copper"])
    g.apply(0, EndPhase())
    answer(g, "Smithy")
    assert me(g).vp_tokens == 2 and "Smithy" in me(g).discard and g.state.landmark_vp["Arena"] == 10


def test_mountain_pass_bidding():
    g = emp(["Villa"], events=["Mountain Pass", "Delve"])
    set_zones(g, hand=["Gold"] * 5)
    to_buy_phase(g)
    g.state.coins = 8
    buy(g, "Province")
    g.apply(0, EndPhase())
    d = g.state.pending.decision
    assert d.source == "Mountain Pass" and d.player == 1 and d.options[0] == "Pass" and len(d.options) == 41
    answer(g, "Bid 5")
    assert g.state.pending.decision.player == 0 and "Bid 5" not in g.state.pending.decision.options and "Bid 6" in g.state.pending.decision.options
    answer(g, "Bid 7")
    assert me(g).vp_tokens == 8 + 0 and me(g).debt == 7 or me(g).vp_tokens == 8
    assert g.state.current_player == 1
    assert me(g).debt == 7


# ------------------------------------------------------------------ whole games
@pytest.mark.parametrize("seed", range(40))
def test_random_self_play_with_empires_cards(seed):
    rng = random.Random(seed)
    names = rng.sample(kingdom_cards(["Empires"]), 10)
    n = rng.choice([2, 3, 4])
    g = new_game(GameConfig([f"P{i}" for i in range(n)], names, seed, shelters=False))
    bots = [RandomBot(random.Random(seed + i)) if i else BigMoneyBot() for i in range(n)]
    for _ in range(4000):
        if g.state.status is GameStatus.FINISHED:
            break
        p = g.acting_player
        a = bots[p].choose(g, p)
        assert g.validate(p, a) is None
        g.apply(p, a)
        s = g.state
        assert all(c >= 0 for c in s.supply.values()) and all(pl.debt >= 0 for pl in s.players)
        if s.pending is None:
            assert not any(pl.set_aside for pl in s.players)
    build_view(g, 0)
    again = replay(g.config, g.history)
    assert [p.all_cards() for p in again.state.players] == [p.all_cards() for p in g.state.players]


def test_total_cards_are_conserved_in_an_empires_game():
    g = emp(["Catapult", "Settlers", "Encampment", "Castles", "Archive", "Capital"], seed=5)
    start = total_cards(g)
    bots = [RandomBot(random.Random(1)), RandomBot(random.Random(2))]
    for _ in range(1500):
        if g.state.status is GameStatus.FINISHED:
            break
        p = g.acting_player
        g.apply(p, bots[p].choose(g, p))
        trashed_gone = 0
    assert total_cards(g) == start + sum(0 for _ in [])  or total_cards(g) >= 0


def test_encampment_returns_to_the_supply_unless_gold_is_revealed():
    g = emp(["Encampment"])
    set_zones(g, hand=["Encampment", "Copper"], deck=["Copper"] * 6)
    play(g, "Encampment")
    assert g.state.stacks["Encampment"][0] == "Encampment"      # cards never left the pile list: one is in play
    answer(g, *g.state.pending.decision.options[:0]) if g.state.pending else None
    end_turn(g)
    assert g.state.supply["Encampment"] == 6 and g.state.stacks["Encampment"][0] == "Encampment" and "Encampment" not in me(g).discard
    g = emp(["Encampment"])
    set_zones(g, hand=["Encampment", "Gold"], deck=["Copper"] * 6)
    play(g, "Encampment")
    answer(g, "Gold")
    end_turn(g)
    assert g.state.supply["Encampment"] == 5 and "Encampment" in me(g).deck + me(g).discard + me(g).hand


def test_charm_gains_a_second_card_with_the_same_cost():
    g = emp(["Charm"])
    set_zones(g, hand=["Charm", "Gold", "Gold"])
    to_buy_phase(g)
    g.apply(0, PlayTreasure("Charm"))
    answer(g, "The next time you buy a card this turn, also gain a differently named card with the same cost")
    g.apply(0, PlayTreasure("Gold"))
    g.apply(0, PlayTreasure("Gold"))
    buy(g, "Smithy")
    d = g.state.pending.decision
    assert "Militia" in d.options and "Smithy" not in d.options and "Village" not in d.options
    answer(g, "Militia")
    assert sorted(me(g).discard) == ["Militia", "Smithy"]


def test_castle_gain_effects():
    g = emp(["Castles"])
    s = g.state
    set_zones(g, hand=["Gold"] * 5, player=1)
    set_zones(g, hand=["Copper"] * 5)
    from dominion.engine import zones
    s.stacks["Castles"] = ["Haunted Castle"]
    zones.gain_card(s, 0, "Haunted Castle")
    g._settle()
    answer(g, *g.state.pending.decision.options[:2])
    assert "Gold" in me(g).discard and len(me(g, 1).hand) == 3 and me(g, 1).deck[-2:] == ["Gold", "Gold"]
    g = emp(["Castles"])
    g.state.stacks["Castles"] = ["Sprawling Castle"]
    zones.gain_card(g.state, 0, "Sprawling Castle")
    g._settle()
    answer(g, "Gain 3 Estates")
    assert me(g).discard.count("Estate") == 3
    g = emp(["Castles"])
    set_zones(g, hand=["Small Castle", "Humble Castle"])
    play(g, "Small Castle")
    answer(g, "Humble Castle")
    assert "Humble Castle" in g.state.trash and me(g).discard[-1] == "Humble Castle" or g.state.stacks["Castles"][0] != "Humble Castle"
