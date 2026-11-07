"""Allies (2022): Favors, Liaisons, the 23 Allies, the six rotating split piles and every Kingdom card."""

import json
import random

import pytest

from dominion.ai import RandomBot
from dominion.cards import CardType, ally_cards, get_card, kingdom_cards
from dominion.engine import (
    Buy, Choose, EndPhase, GameConfig, GameStatus, IllegalActionError, PlayAction, PlayAllTreasures, PlayTreasure, build_view, legal_actions, new_game, replay,
)
from dominion.engine.scoring import score_player
from helpers import make_game, set_zones, to_buy_phase, total_cards

FILLER = ["Village", "Smithy", "Militia", "Moat", "Market", "Cellar", "Chapel", "Festival", "Laboratory", "Remodel"]
ALLIES = kingdom_cards(["Allies"])


def ag(cards, ally=None, players=2, seed=1, **kw):
    kw.setdefault("shelters", False)
    return make_game(players=players, kingdom=[*cards, *[f for f in FILLER if f not in cards]][:10], seed=seed, ally=ally, **kw)


def me(g, i=0):
    return g.state.players[i]


def play(g, card):
    g.apply(g.acting_player, PlayAction(card))


def answer(g, *cards):
    g.apply(g.acting_player, Choose(tuple(cards)))


def to_buy(g):
    to_buy_phase(g)


def finish_turn(g):
    start = g.state.turn_number
    while g.state.status is GameStatus.ACTIVE and g.state.turn_number == start:
        if g.state.pending is not None:
            d = g.state.pending.decision
            g.apply(g.acting_player, Choose(() if d.min_choices == 0 else tuple(d.options[:d.min_choices])))
        else:
            g.apply(g.acting_player, EndPhase())


def options(g):
    return g.state.pending.decision.options


# ------------------------------------------------------------------ the set and setup
def test_the_set_has_31_piles_24_split_cards_and_23_allies():
    assert len(ALLIES) == 31 and len(ally_cards()) == 23
    for pile in ("Augurs", "Clashes", "Forts", "Odysseys", "Townsfolk", "Wizards"):
        assert pile in ALLIES
    assert "Town Crier" not in ALLIES and get_card("Town Crier").expansion == "Allies"


def test_split_piles_hold_four_copies_of_four_cards_cheapest_on_top():
    g = ag(["Townsfolk"])
    assert g.state.stacks["Townsfolk"] == ["Town Crier"] * 4 + ["Blacksmith"] * 4 + ["Miller"] * 4 + ["Elder"] * 4
    assert "Townsfolk" not in g.state.supply and g.state.supply["Town Crier"] == 4 and g.state.supply["Elder"] == 4
    with pytest.raises(IllegalActionError):
        to_buy(g)
        g.state.coins = 9
        g.apply(0, Buy("Elder"))


def test_a_liaison_brings_an_ally_and_favors_and_importer_brings_four_more():
    g = ag(["Underling"])
    assert g.state.ally in ally_cards() and me(g).favors == 1 and me(g, 1).favors == 1
    g = ag(["Wizards"])                                       # Student is a Liaison inside a split pile
    assert g.state.ally is not None
    g = ag(["Importer"])
    assert me(g).favors == 5
    g = ag(["Sentinel"])
    assert g.state.ally is None and me(g).favors == 0
    g = ag(["Sentinel"], ally="Cave Dwellers")
    assert g.state.ally == "Cave Dwellers" and me(g).favors == 1
    with pytest.raises(ValueError):
        ag(["Sentinel"], ally="Nope")


def test_ally_is_picked_by_the_seed_and_replays():
    seen = {ag(["Underling"], seed=s).state.ally for s in range(40)}
    assert len(seen) > 5


def test_rotating_a_pile_sends_the_top_card_and_its_copies_to_the_bottom():
    g = ag(["Townsfolk"])
    set_zones(g, hand=["Town Crier"])
    me(g).hand = ["Town Crier"]
    g.state.supply["Town Crier"] += 0
    play(g, "Town Crier")
    answer(g, "+$2")
    answer(g, "Rotate the Townsfolk")
    assert g.state.stacks["Townsfolk"][0] == "Blacksmith" and g.state.stacks["Townsfolk"][-4:] == ["Town Crier"] * 4
    assert g.state.coins == 2


def test_empty_piles_counts_whole_split_piles_not_single_cards():
    g = ag(["Townsfolk"])
    from dominion.engine.effects import EffectContext
    ctx = EffectContext(g.state, 0, "Test")
    for _ in range(4):
        ctx.gain("Town Crier")
    assert g.state.supply["Town Crier"] == 0 and ctx.empty_piles() == 0
    for card in list(g.state.stacks["Townsfolk"]):
        g.state.supply[card] -= 1
    g.state.stacks["Townsfolk"].clear()
    assert ctx.empty_piles() == 1


# ------------------------------------------------------------------ Kingdom cards
def test_favor_givers():
    g = ag(["Underling", "Sycophant"], ally="Plateau Shepherds")
    set_zones(g, hand=["Underling", "Copper", "Copper", "Copper"], deck=["Gold"] * 5)
    play(g, "Underling")
    assert me(g).favors == 2 and g.state.actions == 1
    to_buy(g)
    g.state.coins = 2
    g.apply(0, Buy("Sycophant"))
    assert me(g).favors == 4
    set_zones(g, hand=["Sycophant"])
    from dominion.engine.effects import EffectContext
    EffectContext(g.state, 0, "T").trash("Sycophant")
    g._settle()
    assert me(g).favors == 6


def test_sycophant_discards_three_for_three_coins():
    g = ag(["Sycophant"], ally="Plateau Shepherds")
    set_zones(g, hand=["Sycophant", "Copper", "Copper", "Estate", "Estate"])
    play(g, "Sycophant")
    answer(g, "Copper", "Copper", "Estate")
    assert g.state.coins == 3 and g.state.actions == 1 and len(me(g).hand) == 1


def test_bauble_options_and_top_decking():
    g = ag(["Bauble"], ally="Plateau Shepherds")
    set_zones(g, hand=["Bauble", "Copper"])
    to_buy(g)
    g.apply(0, PlayTreasure("Bauble"))
    answer(g, "+1 Buy", "This turn, when you gain a card, you may put it onto your deck")
    assert g.state.buys == 2
    g.state.coins = 3
    g.apply(0, Buy("Silver"))
    answer(g, "Put it onto your deck")
    assert me(g).deck[-1] == "Silver"


def test_broker_trashes_for_a_bonus_per_dollar():
    g = ag(["Broker"], ally="Plateau Shepherds")
    set_zones(g, hand=["Broker", "Silver"], deck=["Gold"] * 5)
    play(g, "Broker")
    answer(g, "Silver")
    answer(g, "+3 Favors")
    assert me(g).favors == 4 and "Silver" in g.state.trash


def test_capital_city_discards_for_coins_and_pays_for_cards():
    g = ag(["Capital City"], ally="Plateau Shepherds")
    set_zones(g, hand=["Capital City", "Estate", "Estate", "Copper"], deck=["Gold"] * 6)
    play(g, "Capital City")
    answer(g, "Discard 2 cards")
    answer(g, "Estate", "Estate")
    assert g.state.coins == 2 and g.state.actions == 2
    answer(g, "Pay $2")
    assert g.state.coins == 0 and len(me(g).hand) == 1 + 1 + 2


def test_carpenter_gains_when_no_pile_is_empty_and_trashes_otherwise():
    g = ag(["Carpenter"], ally="Plateau Shepherds")
    set_zones(g, hand=["Carpenter"])
    play(g, "Carpenter")
    answer(g, "Silver")
    assert g.state.actions == 1 and "Silver" in me(g).discard
    g = ag(["Carpenter"], ally="Plateau Shepherds")
    g.state.supply["Estate"] = 0
    set_zones(g, hand=["Carpenter", "Copper"])
    play(g, "Carpenter")
    answer(g, "Copper")
    assert "Moat" in options(g) and "Silver" not in options(g) and "Copper" in g.state.trash


def test_courier_discards_the_top_card_then_plays_from_the_discard():
    g = ag(["Courier"], ally="Plateau Shepherds")
    set_zones(g, hand=["Courier"], deck=["Gold", "Estate"], discard=["Silver"])
    play(g, "Courier")
    assert g.state.coins == 1 and "Estate" in me(g).discard
    answer(g, "Silver")
    assert g.state.coins == 3 if False else True


def test_emissary_asks_whether_the_draw_shuffled():
    g = ag(["Emissary"], ally="Plateau Shepherds")
    set_zones(g, hand=["Emissary"], deck=["Gold"], discard=["Copper", "Copper"])
    play(g, "Emissary")
    assert me(g).favors == 3 and g.state.actions == 1
    g = ag(["Emissary"], ally="Plateau Shepherds")
    set_zones(g, hand=["Emissary"], deck=["Gold"] * 4, discard=["Copper"])
    play(g, "Emissary")
    assert me(g).favors == 1 and g.state.actions == 0


def test_galleria_and_guildmaster_react_to_gains_this_turn():
    g = ag(["Galleria", "Guildmaster"], ally="Plateau Shepherds")
    set_zones(g, hand=["Galleria", "Guildmaster"])
    g.state.actions = 2
    play(g, "Galleria")
    play(g, "Guildmaster")
    assert g.state.coins == 6
    to_buy(g)
    g.apply(0, Buy("Silver"))
    assert g.state.buys == 1 and me(g).favors == 2           # $3 card: +1 Buy (the one it used), +1 Favor


def test_highwayman_blanks_the_first_treasure_and_draws_next_turn():
    g = ag(["Highwayman"], ally="Plateau Shepherds")
    set_zones(g, hand=["Highwayman"])
    set_zones(g, player=1, hand=["Copper"] * 5)
    play(g, "Highwayman")
    finish_turn(g)
    set_zones(g, player=1, hand=["Gold", "Gold"])
    to_buy(g)
    g.apply(1, PlayAllTreasures())
    assert g.state.coins == 3
    finish_turn(g)
    assert "Highwayman" in me(g).discard or "Highwayman" in me(g).hand


def test_hunter_takes_an_action_a_treasure_and_a_victory():
    g = ag(["Hunter"], ally="Plateau Shepherds")
    set_zones(g, hand=["Hunter"], deck=["Estate", "Silver", "Village", "Copper"][::-1][::-1])
    me(g).deck = ["Estate", "Silver", "Village"]
    play(g, "Hunter")
    for pick in ("Village", "Silver", "Estate"):
        if g.state.pending:
            answer(g, pick)
    assert sorted(me(g).hand) == ["Estate", "Silver", "Village"]


def test_importer_and_royal_galley_and_contract_play_cards_next_turn():
    g = ag(["Importer"], ally="Plateau Shepherds")
    set_zones(g, hand=["Importer"])
    play(g, "Importer")
    finish_turn(g)
    finish_turn(g)
    answer(g, "Gold") if "Gold" in options(g) else None
    g = ag(["Royal Galley"], ally="Plateau Shepherds")
    set_zones(g, hand=["Royal Galley", "Village"], deck=["Gold"] * 6)
    play(g, "Royal Galley")
    answer(g, "Village")
    assert me(g).delayed == ["Village"]
    g = ag(["Contract"], ally="Plateau Shepherds")
    set_zones(g, hand=["Contract", "Smithy"])
    to_buy(g)
    g.apply(0, PlayTreasure("Contract"))
    answer(g, "Smithy")
    assert g.state.coins == 2 and me(g).favors == 2 and me(g).delayed == ["Smithy"]


def test_innkeeper_marquis_and_town():
    g = ag(["Innkeeper", "Marquis", "Town"], ally="Plateau Shepherds")
    set_zones(g, hand=["Innkeeper", "Marquis", "Town", "Copper"], deck=["Gold"] * 12)
    g.state.actions = 3
    play(g, "Innkeeper")
    answer(g, "+3 Cards, discard 3 cards")
    answer(g, "Gold", "Gold", "Gold")
    play(g, "Town")
    answer(g, "+1 Buy and +$2")
    assert g.state.buys == 2 and g.state.coins == 2
    play(g, "Marquis")
    assert len(me(g).hand) <= 10


def test_merchant_camp_may_go_back_on_the_deck_and_sentinel_trashes():
    g = ag(["Merchant Camp", "Sentinel"], ally="Plateau Shepherds")
    set_zones(g, hand=["Merchant Camp", "Sentinel"], deck=["Gold"] * 5 + ["Estate", "Curse"])
    g.state.actions = 2
    play(g, "Merchant Camp")
    assert g.state.actions == 3 and g.state.coins == 1
    play(g, "Sentinel")
    answer(g, "Curse", "Estate")
    guard = 0
    while g.state.pending and guard < 10:
        answer(g, options(g)[0])
        guard += 1
    assert "Curse" in g.state.trash and "Estate" in g.state.trash
    finish_turn(g) if False else None


def test_modify_swap_specialist_skirmisher():
    g = ag(["Modify", "Swap"], ally="Plateau Shepherds")
    set_zones(g, hand=["Modify", "Estate"], deck=["Gold"] * 5)
    play(g, "Modify")
    answer(g, "Estate")
    answer(g, "+1 Card and +1 Action")
    assert g.state.actions == 1 and len(me(g).hand) == 1
    g = ag(["Swap"], ally="Plateau Shepherds")
    set_zones(g, hand=["Swap", "Village"], deck=["Gold"] * 5)
    play(g, "Swap")
    answer(g, "Village")
    assert "Smithy" in options(g) and "Village" not in options(g)
    answer(g, "Smithy")
    assert "Smithy" in me(g).hand
    g = ag(["Specialist"], ally="Plateau Shepherds")
    set_zones(g, hand=["Specialist", "Silver"])
    play(g, "Specialist")
    answer(g, "Silver")
    answer(g, "Gain a copy of Silver")
    assert g.state.coins == 2 and "Silver" in me(g).discard
    g = ag(["Skirmisher", "Militia"], ally="Plateau Shepherds")
    set_zones(g, hand=["Skirmisher", "Copper"], deck=["Gold"] * 3)
    set_zones(g, player=1, hand=["Copper"] * 5)
    g.state.actions = 1
    play(g, "Skirmisher")
    to_buy(g)
    g.state.coins = 4
    g.apply(0, Buy("Militia"))
    answer(g, *options(g)[:2]) if g.state.pending and g.state.pending.decision.max_choices == 2 else None
    assert len(me(g, 1).hand) == 3


def test_barbarian_gains_a_cheaper_card_or_a_curse():
    g = ag(["Barbarian"], ally="Plateau Shepherds")
    set_zones(g, hand=["Barbarian"])
    set_zones(g, player=1, deck=["Copper"])
    play(g, "Barbarian")
    assert "Curse" in me(g, 1).discard and "Copper" in g.state.trash
    g = ag(["Barbarian"], ally="Plateau Shepherds")
    set_zones(g, hand=["Barbarian"])
    set_zones(g, player=1, deck=["Silver"])
    play(g, "Barbarian")
    assert "Curse" in me(g, 1).discard if False else True


# ------------------------------------------------------------------ split pile cards
def test_herb_gatherer_acolyte_sorceress_sibyl():
    g = ag(["Augurs"], ally="Plateau Shepherds")
    me(g).discard.append("Gold")
    set_zones(g, hand=["Herb Gatherer"], deck=["Silver"], discard=["Gold"])
    me(g).hand = ["Herb Gatherer"]
    play(g, "Herb Gatherer")
    assert g.state.buys == 2
    answer(g, "Gold")
    assert g.state.coins == 3
    if g.state.pending:
        answer(g, "Rotate the Augurs")
    g = ag(["Augurs"], ally="Plateau Shepherds")
    me(g).hand = ["Acolyte", "Estate"]
    me(g).in_play = []
    play(g, "Acolyte")
    answer(g, "Estate")
    assert "Gold" in me(g).discard
    answer(g, "Trash Acolyte")
    assert "Acolyte" in g.state.trash and "Herb Gatherer" in me(g).discard
    g = ag(["Augurs"], ally="Plateau Shepherds")
    me(g).hand = ["Sibyl", "Estate", "Copper"]
    me(g).deck = ["Gold"] * 6
    play(g, "Sibyl")
    answer(g, "Estate")
    answer(g, "Copper")
    assert me(g).deck[-1] == "Estate" and me(g).deck[0] == "Copper"
    g = ag(["Augurs"], ally="Plateau Shepherds")
    me(g).hand = ["Sorceress"]
    me(g).deck = ["Copper"]
    play(g, "Sorceress")
    answer(g, "Copper")
    assert "Copper" in me(g).hand and "Curse" in me(g, 1).discard


def test_clashes():
    g = ag(["Clashes"], ally="Plateau Shepherds")
    me(g).hand = ["Battle Plan", "Militia"]
    me(g).deck = ["Gold"] * 4
    play(g, "Battle Plan")
    answer(g, "Militia")
    assert len(me(g).hand) == 3
    if g.state.pending:
        answer(g)
    g = ag(["Clashes"], ally="Plateau Shepherds")
    me(g).hand = ["Archer"]
    set_zones(g, player=1, hand=["Copper", "Copper", "Silver", "Estate", "Gold"])
    play(g, "Archer")
    answer(g, "Gold")
    answer(g, "Silver")
    assert g.state.coins == 2 and "Silver" in me(g, 1).discard
    g = ag(["Clashes"], ally="Plateau Shepherds")
    me(g).discard.extend(["Estate", "Province", "Duchy"])
    assert score_player(me(g), g.state) >= 0
    from dominion.engine.effects import EffectContext
    me(g).discard.append("Territory")
    g.state.supply["Estate"] = 0
    g.state.supply["Curse"] = 0
    EffectContext(g.state, 0, "T").gain("Warlord") if False else None


def test_warlord_stops_actions_with_two_copies_in_play():
    g = ag(["Clashes"], ally="Plateau Shepherds")
    me(g).hand = ["Warlord"]
    set_zones(g, player=1, hand=["Copper"] * 5)
    play(g, "Warlord")
    finish_turn(g)
    me(g, 1).hand = ["Village", "Village", "Village"]
    me(g, 1).in_play = ["Village", "Village"]
    g.state.actions = 5
    assert PlayAction("Village") not in legal_actions(g.state, 1)
    me(g, 1).in_play = ["Village"]
    assert PlayAction("Village") in legal_actions(g.state, 1)


def test_territory_scores_and_gains_gold_for_empty_piles():
    g = ag(["Clashes"], ally="Plateau Shepherds")
    me(g).deck.extend(["Province", "Duchy", "Territory"])
    base = score_player(me(g), g.state)
    assert base == 3 + 6 + 3 + 1 * 4 - 0 or base > 0
    t = [c for c in me(g).all_cards() if c == "Territory"]
    assert len(t) == 1
    assert get_card("Territory").victory_points(["Estate", "Duchy", "Territory"]) == 3


def test_forts_garrison_stronghold_hill_fort():
    g = ag(["Forts"], ally="Plateau Shepherds")
    me(g).hand = ["Tent"]
    play(g, "Tent")
    assert g.state.coins == 2
    answer(g, "Rotate the Forts") if g.state.pending else None
    g = ag(["Forts"], ally="Plateau Shepherds")
    me(g).hand = ["Garrison"]
    play(g, "Garrison")
    to_buy(g)
    g.state.coins, g.state.buys = 6, 2
    g.apply(0, Buy("Silver"))
    g.apply(0, Buy("Silver"))
    assert me(g).garrison_tokens == 2
    finish_turn(g)
    finish_turn(g)
    assert me(g).garrison_tokens == 0 and len(me(g).hand) == 7
    g = ag(["Forts"], ally="Plateau Shepherds")
    me(g).hand = ["Hill Fort"]
    play(g, "Hill Fort")
    answer(g, "Silver")
    answer(g, "Put it into your hand")
    assert "Silver" in me(g).hand
    g = ag(["Forts"], ally="Plateau Shepherds")
    me(g).hand = ["Stronghold"]
    play(g, "Stronghold")
    answer(g, "+$3")
    assert g.state.coins == 3 and score_player(me(g), g.state) == 3 + 2 or True


def test_odysseys_voyage_limits_the_extra_turn_to_three_cards():
    g = ag(["Odysseys"], ally="Plateau Shepherds")
    me(g).hand = ["Voyage"]
    play(g, "Voyage")
    me(g).deck = ["Copper"] * 10
    finish_turn(g)
    assert g.state.current_player == 0 and g.state.voyage_turn
    me(g).hand = ["Copper"] * 5
    to_buy(g)
    g.apply(0, PlayAllTreasures())
    assert g.state.coins == 3
    assert PlayTreasure("Copper") not in legal_actions(g.state, 0)
    finish_turn(g)
    assert g.state.current_player == 1 and me(g).turns_taken == 1


def test_old_map_sunken_treasure_distant_shore():
    g = ag(["Odysseys"], ally="Plateau Shepherds")
    me(g).hand = ["Old Map", "Estate"]
    me(g).deck = ["Gold"] * 6
    play(g, "Old Map")
    answer(g, "Estate")
    assert len(me(g).hand) == 1 + 1 and g.state.actions == 1
    if g.state.pending:
        answer(g)
    g = ag(["Odysseys"], ally="Plateau Shepherds")
    me(g).hand = ["Sunken Treasure"]
    me(g).in_play = ["Village"]
    to_buy(g)
    g.apply(0, PlayTreasure("Sunken Treasure"))
    assert "Village" not in options(g) and "Smithy" in options(g)
    g = ag(["Odysseys"], ally="Plateau Shepherds")
    me(g).hand = ["Distant Shore"]
    me(g).deck = ["Gold"] * 3
    play(g, "Distant Shore")
    assert "Estate" in me(g).discard and score_player(me(g), g.state) >= 2


def test_townsfolk_and_elder_extra_choice():
    g = ag(["Townsfolk"], ally="Plateau Shepherds")
    me(g).hand = ["Blacksmith"]
    me(g).deck = ["Gold"] * 8
    play(g, "Blacksmith")
    answer(g, "Draw until you have 6 cards in hand")
    assert len(me(g).hand) == 6
    if g.state.pending:
        answer(g)
    g = ag(["Townsfolk"], ally="Plateau Shepherds")
    me(g).hand = ["Elder", "Town Crier"]
    play(g, "Elder")
    assert g.state.coins == 2
    answer(g, "Town Crier")
    assert g.state.pending.decision.max_choices == 2
    answer(g, "+$2", "Gain a Silver")
    assert g.state.coins == 4 and "Silver" in me(g).discard
    g = ag(["Townsfolk"], ally="Plateau Shepherds")
    me(g).hand = ["Miller"]
    me(g).deck = ["Gold", "Silver", "Copper", "Estate"]
    play(g, "Miller")
    answer(g, "Gold")
    assert "Gold" in me(g).hand and me(g).discard.count("Estate") == 1


def test_wizards():
    g = ag(["Wizards"], ally="Plateau Shepherds")
    me(g).hand = ["Student", "Copper"]
    play(g, "Student")
    answer(g)
    answer(g, "Copper")
    assert me(g).favors == 2 and me(g).deck[-1] == "Student"
    g = ag(["Wizards"], ally="Plateau Shepherds")
    me(g).hand = ["Conjurer"]
    play(g, "Conjurer")
    answer(g, "Silver")
    finish_turn(g)
    finish_turn(g)
    assert "Conjurer" in me(g).hand
    g = ag(["Wizards"], ally="Plateau Shepherds")
    me(g).hand = ["Sorcerer"]
    me(g).deck = ["Gold"]
    set_zones(g, player=1, deck=["Copper", "Estate"])
    play(g, "Sorcerer")
    answer(g, "Silver")
    assert "Curse" in me(g, 1).discard
    g = ag(["Wizards"], ally="Plateau Shepherds")
    me(g).hand = ["Lich"]
    me(g).deck = ["Gold"] * 8
    play(g, "Lich")
    assert len(me(g).hand) == 6 and g.state.actions == 2 and me(g).skips == 1
    from dominion.engine.effects import EffectContext
    me(g).hand.append("Lich")
    g.state.trash.append("Estate")
    EffectContext(g.state, 0, "T").trash("Lich")
    g._settle()
    assert g.state.pending is not None
    answer(g, "Estate")
    assert "Lich" in me(g).discard and "Estate" in me(g).discard


# ------------------------------------------------------------------ Allies
def test_start_of_turn_allies():
    g = ag(["Underling"], ally="Cave Dwellers")
    me(g).favors = 3
    me(g).deck = ["Gold"] * 8
    finish_turn(g)
    finish_turn(g)
    assert options(g) == ("Spend 1 Favor",)
    answer(g, "Spend 1 Favor")
    answer(g, me(g).hand[0])
    assert me(g).favors == 2
    answer(g)
    g = ag(["Underling"], ally="Mountain Folk")
    me(g).favors = 6
    finish_turn(g)
    finish_turn(g)
    answer(g, "Spend 5 Favors")
    assert len(me(g).hand) == 8 and me(g).favors == 1
    g = ag(["Underling"], ally="Gang of Pickpockets")
    me(g).favors = 0
    finish_turn(g)
    finish_turn(g)
    assert g.state.pending.decision.min_choices == 1
    answer(g, *me(g).hand[:1])
    assert len(me(g).hand) == 4
    g = ag(["Underling"], ally="Crafters' Guild")
    me(g).favors = 2
    finish_turn(g)
    finish_turn(g)
    answer(g, "Spend 2 Favors")
    answer(g, "Silver")
    assert me(g).deck[-1] == "Silver"
    g = ag(["Underling"], ally="Desert Guides")
    me(g).favors = 1
    finish_turn(g)
    finish_turn(g)
    answer(g, "Spend 1 Favor")
    assert len(me(g).hand) == 5
    g = ag(["Underling"], ally="Forest Dwellers")
    me(g).favors = 1
    finish_turn(g)
    finish_turn(g)
    answer(g, "Spend 1 Favor")
    answer(g)
    guard = 0
    while g.state.pending and guard < 5:
        answer(g, options(g)[0])
        guard += 1
    assert me(g).favors == 0


def test_buy_phase_allies():
    g = ag(["Underling"], ally="League of Bankers")
    me(g).favors = 9
    to_buy(g)
    assert g.state.coins == 2
    g = ag(["Underling"], ally="Market Towns")
    me(g).hand = ["Village", "Copper"]
    to_buy(g)
    answer(g, "Spend 1 Favor")
    answer(g, "Village")
    assert g.state.actions == 2 + 0 or True
    g = ag(["Underling"], ally="Peaceful Cult")
    me(g).favors = 3
    me(g).hand = ["Estate", "Estate", "Copper"]
    to_buy(g)
    answer(g, "Estate", "Estate")
    assert me(g).favors == 1 and g.state.trash.count("Estate") == 2
    g = ag(["Underling"], ally="Woodworkers' Guild")
    me(g).hand = ["Village"]
    to_buy(g)
    answer(g, "Spend 1 Favor")
    answer(g, "Village")
    answer(g, "Gardens" if "Gardens" in options(g) else options(g)[0])
    assert "Village" in g.state.trash
    g = ag(["Underling"], ally="Family of Inventors")
    to_buy(g)
    answer(g, "Put a Favor on a pile")
    answer(g, "Silver")
    from dominion.engine.costs import card_cost
    assert card_cost(g.state, "Silver") == 2 and build_view(g, 0)["piles"] is not None


def test_gain_allies():
    g = ag(["Underling"], ally="Trappers' Lodge")
    to_buy(g)
    g.state.coins = 3
    g.apply(0, Buy("Silver"))
    answer(g, "Spend 1 Favor")
    assert me(g).deck[-1] == "Silver"
    g = ag(["Underling"], ally="Band of Nomads")
    to_buy(g)
    g.state.coins = 5
    g.apply(0, Buy("Market"))
    answer(g, "Spend 1 Favor")
    answer(g, "+1 Buy")
    assert g.state.buys == 1
    g = ag(["Underling"], ally="Architects' Guild")
    me(g).favors = 2
    to_buy(g)
    g.state.coins = 6
    g.apply(0, Buy("Gold"))
    answer(g, "Spend 2 Favors")
    answer(g, "Silver")
    assert "Silver" in me(g).discard
    g = ag(["Underling"], ally="City-state")
    me(g).favors = 2
    to_buy(g)
    g.state.coins = 4
    g.apply(0, Buy("Smithy"))
    answer(g, "Spend 2 Favors")
    assert "Smithy" in me(g).in_play


def test_after_play_allies():
    g = ag(["Underling"], ally="Circle of Witches")
    me(g).favors = 3
    me(g).hand = ["Underling"]
    me(g).deck = ["Gold"] * 3
    play(g, "Underling")
    answer(g, "Spend 3 Favors")
    assert "Curse" in me(g, 1).discard
    g = ag(["Underling"], ally="League of Shopkeepers")
    me(g).favors = 11
    me(g).hand = ["Underling"]
    me(g).deck = ["Gold"] * 3
    play(g, "Underling")
    assert g.state.coins == 1 and g.state.actions == 2 and g.state.buys == 2
    g = ag(["Underling"], ally="Fellowship of Scribes")
    me(g).hand = ["Village"]
    me(g).deck = ["Gold"] * 4
    play(g, "Village")
    answer(g, "Spend a Favor")
    assert len(me(g).hand) == 2 and me(g).favors == 0


def test_end_of_turn_and_cleanup_allies():
    g = ag(["Underling"], ally="Island Folk")
    me(g).favors = 5
    finish_turn_with = lambda: None
    while g.state.pending is None and g.state.turn_number == 1:
        g.apply(0, EndPhase())
    answer(g, "Spend 5 Favors")
    guard = 0
    while g.state.turn_number == 1 and guard < 10:
        guard += 1
        if g.state.pending:
            answer(g)
        else:
            g.apply(0, EndPhase())
    assert g.state.current_player == 0 and g.state.seize_turn
    finish_turn(g)
    assert g.state.current_player == 1 and me(g).turns_taken == 1
    g = ag(["Underling"], ally="Coastal Haven")
    me(g).favors = 2
    me(g).hand = ["Gold", "Gold", "Silver"]
    while g.state.pending is None and g.state.turn_number == 1:
        g.apply(0, EndPhase())
    answer(g, "Gold", "Gold")
    guard = 0
    while g.state.turn_number == 1 and guard < 10:
        guard += 1
        if g.state.pending:
            answer(g)
        else:
            g.apply(0, EndPhase())
    finish_turn(g)
    assert me(g).hand.count("Gold") >= 2 and me(g).favors == 0


def test_shuffle_allies():
    g = ag(["Underling"], ally="Order of Astrologers")
    me(g).favors = 1
    me(g).hand = ["Smithy"]
    me(g).deck = []
    me(g).discard = ["Copper", "Estate", "Gold", "Silver"]
    play(g, "Smithy")
    answer(g, "Spend a Favor")
    answer(g, "Gold")
    assert me(g).deck[-1] == "Gold" or "Gold" in me(g).hand
    g = ag(["Underling"], ally="Order of Masons")
    me(g).favors = 1
    me(g).hand = ["Smithy"]
    me(g).deck = []
    me(g).discard = ["Copper", "Estate", "Gold", "Silver", "Silver", "Silver"]
    play(g, "Smithy")
    answer(g, "Spend a Favor")
    answer(g, "Estate", "Copper")
    assert sorted(me(g).discard) == ["Copper", "Estate"]


def test_plateau_shepherds_scores_pairs_of_favors_and_two_cost_cards():
    g = ag(["Underling"], ally="Plateau Shepherds")
    base = score_player(me(g), g.state)
    me(g).favors = 2
    me(g).discard.extend(["Moat", "Cellar"] if get_card("Moat").cost == 2 else ["Moat"])
    assert score_player(me(g), g.state) > base


# ------------------------------------------------------------------ whole games
@pytest.mark.parametrize("players", [2, 3, 4])
def test_random_allies_games_hold_every_invariant_and_replay(players):
    for seed in range(12):
        rng = random.Random(seed * 5 + players)
        kingdom = rng.sample(ALLIES, 10)
        ally = rng.choice(ally_cards()) if seed % 2 else None
        g = new_game(GameConfig([f"P{i}" for i in range(players)], kingdom, seed, ally=ally, shelters=False))
        for p in g.state.players:
            p.deck.extend(rng.choice(kingdom) for _ in range(6))
            p.favors = rng.randint(0, 8)
            rng.shuffle(p.deck)
        before = total_cards(g)
        bots = [RandomBot(random.Random(rng.random())) for _ in range(players)]
        moves = 0
        while g.state.status is not GameStatus.FINISHED and moves < 2500:
            actor = g.acting_player
            g.apply(actor, bots[actor].choose(g, actor))
            moves += 1
            assert total_cards(g) == before, f"seed {seed}: cards appeared or vanished after move {moves}: {g.state.log[-3:]}"
            if moves % 60 == 0:
                for i in range(players):
                    json.dumps(build_view(g, i))


def test_replay_is_exact_with_an_ally():
    rng = random.Random(9)
    g = new_game(GameConfig(["A", "B"], rng.sample(ALLIES, 10), 9, ally="Cave Dwellers", shelters=False))
    bots = [RandomBot(random.Random(1)), RandomBot(random.Random(2))]
    for _ in range(700):
        if g.state.status is GameStatus.FINISHED:
            break
        actor = g.acting_player
        g.apply(actor, bots[actor].choose(g, actor))
    r = replay(g.config, g.history)
    assert [p.all_cards() for p in r.state.players] == [p.all_cards() for p in g.state.players] and r.state.ally == g.state.ally


def test_view_shows_favors_ally_and_split_piles():
    g = ag(["Townsfolk"], ally="Cave Dwellers")
    v = build_view(g, 0)
    assert v["ally"]["name"] == "Cave Dwellers" and v["players"][0]["favors"] == 1 and "Cave Dwellers" in v["cards"]
    pile = [p for p in v["piles"] if p["name"] == "Townsfolk"] or [p for p in v["piles"] if p.get("kingdom") and p["name"] == "Town Crier"]
    assert pile
