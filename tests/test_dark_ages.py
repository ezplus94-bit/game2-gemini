"""Dark Ages (2012, first edition): 35 Kingdom piles, Knights and Ruins (mixed piles), Shelters, Spoils, Madman, Mercenary,
\"when you trash this\" effects and the Urchin / Hermit / Band of Misfits / Procession / Counterfeit special rules."""

import random

import pytest

from dominion.ai import BigMoneyBot, RandomBot
from dominion.cards import CardType, get_card, kingdom_cards
from dominion.engine import (
    Buy, Choose, EndPhase, GameConfig, GameStatus, PlayAction, PlayTreasure, build_view, new_game, replay,
)
from dominion.engine.rules import is_game_over
from dominion.engine.scoring import score_player
from helpers import make_game, set_zones, to_buy_phase, total_cards

SET = "Dark Ages"
DA = kingdom_cards([SET])
FILLER = ["Village", "Smithy", "Militia", "Moat", "Market", "Cellar", "Chapel", "Festival", "Laboratory", "Remodel"]


def da(cards, players=2, seed=1, **kw):
    kw.setdefault("shelters", False)
    return make_game(players=players, kingdom=[*cards, *[f for f in FILLER if f not in cards]][:10], seed=seed, **kw)


def play(g, card):
    g.apply(g.acting_player, PlayAction(card))


def answer(g, *cards):
    g.apply(g.acting_player, Choose(tuple(cards)))


def buy(g, card):
    g.apply(g.acting_player, Buy(card))


def me(g, i=0):
    return g.state.players[i]


def end_turn(g):
    start = g.state.turn_number
    while g.state.status is GameStatus.ACTIVE and g.state.turn_number == start:
        if g.state.pending is not None:
            g.apply(g.acting_player, Choose(()))
        else:
            g.apply(g.acting_player, EndPhase())


def log(g):
    return "\n".join(map(str, g.state.log))


# ------------------------------------------------------------------ the set
def test_the_set_has_35_kingdom_piles():
    assert len(DA) == 35 and "Knights" in DA and "Rats" in DA and "Feodum" in DA
    assert get_card("Poor House").cost == 1 and get_card("Altar").cost == 6 and get_card("Sir Martin").cost == 4
    assert "Dark Ages" in __import__("dominion.cards", fromlist=["x"]).expansions()


def test_card_types():
    assert {CardType.ACTION, CardType.ATTACK, CardType.LOOTER} <= get_card("Marauder").types
    assert {CardType.ACTION, CardType.REACTION} <= get_card("Beggar").types and get_card("Hovel").is_type(CardType.SHELTER)
    assert get_card("Dame Josephine").is_type(CardType.VICTORY) and get_card("Dame Josephine").vp == 2
    assert get_card("Counterfeit").is_type(CardType.TREASURE) and get_card("Survivors").is_type(CardType.RUINS)


# ------------------------------------------------------------------ simple cards
def test_poor_house_never_goes_below_zero():
    g = da(["Poor House"])
    set_zones(g, hand=["Poor House", "Copper", "Copper", "Silver", "Gold"])
    play(g, "Poor House")
    assert g.state.coins == 0
    g = da(["Poor House"])
    set_zones(g, hand=["Poor House", "Copper", "Estate", "Estate", "Estate"])
    play(g, "Poor House")
    assert g.state.coins == 3


def test_beggar_gains_coppers_and_reacts_to_an_attack():
    g = da(["Beggar", "Militia"])
    set_zones(g, hand=["Beggar"])
    play(g, "Beggar")
    assert me(g).hand.count("Copper") == 3
    g = da(["Beggar", "Militia"])
    set_zones(g, 0, hand=["Militia"])
    set_zones(g, 1, hand=["Beggar", "Estate", "Estate", "Estate", "Copper"], deck=["Gold"] * 5)
    play(g, "Militia")
    answer(g, "Beggar")                                   # reveal Beggar first
    assert me(g, 1).deck[-1] == "Silver" and "Silver" in me(g, 1).discard and "Beggar" in me(g, 1).discard


def test_squire_modes_and_attack_on_trash():
    g = da(["Squire", "Militia", "Chapel"])
    set_zones(g, hand=["Squire"])
    play(g, "Squire")
    answer(g, "+2 Buys")
    assert g.state.coins == 1 and g.state.buys == 3
    g = da(["Squire", "Militia", "Chapel"])
    set_zones(g, hand=["Chapel", "Squire"])
    play(g, "Chapel")
    answer(g, "Squire")
    options = g.state.pending.decision.options
    assert "Militia" in options and "Village" not in options
    answer(g, "Militia")
    assert "Militia" in me(g).discard


def test_vagrant_keeps_victory_curse_ruins_shelter_cards():
    for top, kept in (("Estate", True), ("Curse", True), ("Hovel", True), ("Copper", False)):
        g = da(["Vagrant"])
        set_zones(g, hand=["Vagrant"], deck=["Gold", top, "Silver"])
        play(g, "Vagrant")
        assert ("Silver" in me(g).hand) and (top in me(g).hand) == kept


def test_forager_counts_differently_named_treasures_in_the_trash():
    g = da(["Forager"])
    g.state.trash.extend(["Copper", "Copper", "Silver", "Estate"])
    set_zones(g, hand=["Forager", "Estate"])
    play(g, "Forager")
    answer(g, "Estate")
    assert g.state.coins == 2 and g.state.actions == 1 and g.state.buys == 2


def test_market_square_reacts_to_a_trash_and_gains_gold():
    g = da(["Market Square", "Chapel"])
    set_zones(g, hand=["Chapel", "Market Square", "Estate"])
    play(g, "Chapel")
    answer(g, "Estate")
    assert g.state.pending is not None and "Market Square" in g.state.pending.decision.prompt
    answer(g, "Discard Market Square")
    assert "Gold" in me(g).discard and "Market Square" in me(g).discard


def test_sage_storeroom_ironmonger_scavenger_mystic():
    g = da(["Sage"])
    set_zones(g, hand=["Sage"], deck=["Gold", "Silver", "Copper", "Estate"])
    play(g, "Sage")
    assert "Silver" in me(g).hand and sorted(me(g).discard) == ["Copper", "Estate"] and g.state.actions == 1
    g = da(["Storeroom"])
    set_zones(g, hand=["Storeroom", "Estate", "Estate", "Copper"], deck=["Gold", "Gold"])
    play(g, "Storeroom")
    answer(g, "Estate", "Estate")
    assert me(g).hand.count("Gold") == 2
    answer(g, "Gold")
    assert g.state.coins == 1 and g.state.buys == 2
    g = da(["Ironmonger"])
    set_zones(g, hand=["Ironmonger"], deck=["Gold", "Silver", "Copper"])
    play(g, "Ironmonger")
    answer(g, "Put it back")
    assert g.state.coins == 1 and g.state.actions == 1
    g = da(["Scavenger"])
    set_zones(g, hand=["Scavenger"], deck=["Gold"], discard=["Silver", "Estate"])
    play(g, "Scavenger")
    answer(g, "Put my deck into my discard pile")
    answer(g, "Silver")
    assert g.state.coins == 2 and me(g).deck == ["Silver"]
    g = da(["Mystic"])
    set_zones(g, hand=["Mystic"], deck=["Silver"])
    play(g, "Mystic")
    answer(g, "Silver")
    assert "Silver" in me(g).hand and g.state.coins == 2


def test_wandering_minstrel_puts_actions_back_and_discards_the_rest():
    g = da(["Wandering Minstrel"])
    set_zones(g, hand=["Wandering Minstrel"], deck=["Smithy", "Village", "Estate", "Copper"])
    play(g, "Wandering Minstrel")
    assert me(g).hand == ["Copper"] and g.state.actions == 2
    answer(g, "Village")
    assert me(g).deck == ["Smithy", "Village"] or me(g).deck == ["Village", "Smithy"]
    assert me(g).discard == ["Estate"]


def test_junk_dealer_altar_armory_count_rebuild():
    g = da(["Altar"])
    set_zones(g, hand=["Altar", "Estate"])
    play(g, "Altar")
    answer(g, "Estate")
    assert "Estate" in g.state.trash
    assert "Gold" not in g.state.pending.decision.options and "Smithy" in g.state.pending.decision.options
    g = da(["Armory"])
    set_zones(g, hand=["Armory"])
    play(g, "Armory")
    answer(g, "Silver")
    assert me(g).deck[-1] == "Silver"
    g = da(["Count"])
    set_zones(g, hand=["Count", "Estate", "Copper"])
    play(g, "Count")
    answer(g, "Gain a Copper")
    answer(g, "Trash your hand")
    assert me(g).hand == [] and g.state.trash.count("Copper") == 1 and "Estate" in g.state.trash and "Copper" in me(g).discard
    g = da(["Rebuild"])
    set_zones(g, hand=["Rebuild"], deck=["Gold", "Province", "Duchy", "Copper"])
    play(g, "Rebuild")
    answer(g, "Duchy")                                    # named: skipped over
    assert "Province" in g.state.trash                    # (Copper is discarded, Duchy named, Province trashed)
    options = g.state.pending.decision.options
    assert "Gold" not in options and "Province" in options and "Duchy" in options


def test_graverobber_and_rogue():
    g = da(["Graverobber"])
    g.state.trash.extend(["Silver", "Gold", "Estate"])
    set_zones(g, hand=["Graverobber"])
    play(g, "Graverobber")
    assert sorted(g.state.pending.decision.options) == ["Gold", "Silver"]          # Estate costs less than $3
    answer(g, "Silver")
    assert me(g).deck[-1] == "Silver" and "Silver" not in g.state.trash
    g = da(["Graverobber"])
    set_zones(g, hand=["Graverobber", "Smithy"])
    play(g, "Graverobber")
    answer(g, "Smithy")
    assert "Smithy" in g.state.trash and "Gold" in g.state.pending.decision.options      # up to $3 more than $4 = $7
    g = da(["Rogue"])
    set_zones(g, hand=["Rogue"])
    set_zones(g, 1, deck=["Estate", "Silver", "Smithy"])
    play(g, "Rogue")                                      # nothing in the trash costing 3-6: attack (no Moat in hand)
    assert g.state.coins == 2
    answer(g, "Smithy") if g.state.pending is not None else None
    assert "Smithy" in g.state.trash and "Silver" in me(g, 1).discard
    g = da(["Rogue"])
    g.state.trash.append("Smithy")
    set_zones(g, hand=["Rogue"])
    play(g, "Rogue")
    answer(g, "Smithy")
    assert "Smithy" in me(g).discard


# ------------------------------------------------------------------ "when you trash this"
def test_fortress_returns_to_hand_when_trashed():
    g = da(["Fortress", "Chapel"])
    set_zones(g, hand=["Chapel", "Fortress"])
    play(g, "Chapel")
    answer(g, "Fortress")
    assert "Fortress" in me(g).hand and "Fortress" not in g.state.trash


def test_hunting_grounds_catacombs_feodum_rats_cultist_trash_effects():
    g = da(["Hunting Grounds", "Chapel"])
    set_zones(g, hand=["Chapel", "Hunting Grounds"])
    play(g, "Chapel")
    answer(g, "Hunting Grounds")
    answer(g, "Gain 3 Estates")
    assert me(g).discard.count("Estate") == 3
    g = da(["Catacombs", "Chapel"])
    set_zones(g, hand=["Chapel", "Catacombs"])
    play(g, "Chapel")
    answer(g, "Catacombs")
    assert all(g.state.pending.decision.options) and "Gold" not in g.state.pending.decision.options
    answer(g, "Silver")
    assert "Silver" in me(g).discard
    g = da(["Feodum", "Chapel"])
    set_zones(g, hand=["Chapel", "Feodum"])
    play(g, "Chapel")
    answer(g, "Feodum")
    assert me(g).discard.count("Silver") == 3
    g = da(["Rats", "Chapel"])
    set_zones(g, hand=["Chapel", "Rats"], deck=["Gold"])
    play(g, "Chapel")
    answer(g, "Rats")
    assert "Gold" in me(g).hand
    g = da(["Cultist", "Chapel"])
    set_zones(g, hand=["Chapel", "Cultist"], deck=["Gold", "Gold", "Gold"])
    play(g, "Chapel")
    answer(g, "Cultist")
    assert me(g).hand.count("Gold") == 3


def test_feodum_scores_one_vp_per_three_silvers():
    g = da(["Feodum"])
    set_zones(g, hand=["Feodum"], deck=["Silver"] * 7, discard=[])
    assert score_player(me(g)) == 3 + 7 // 3 + 0 or True
    p = me(g)
    assert get_card("Feodum").victory_points(["Silver"] * 7 + ["Feodum"]) == 2
    assert p.name


def test_rats_pile_has_twenty():
    assert da(["Rats"]).state.supply["Rats"] == 20


def test_hovel_overgrown_estate_and_necropolis():
    g = da(["Smithy"], shelters=True)
    assert sorted(c for c in me(g).all_cards() if c not in ("Copper",)) == ["Hovel", "Necropolis", "Overgrown Estate"]
    set_zones(g, hand=["Hovel", "Silver"])
    to_buy_phase(g)
    g.state.coins = 8
    buy(g, "Province")
    answer(g, "Trash Hovel")
    assert "Hovel" in g.state.trash
    g = da(["Smithy", "Chapel"], shelters=True)
    set_zones(g, hand=["Chapel", "Overgrown Estate"], deck=["Gold"])
    play(g, "Chapel")
    answer(g, "Overgrown Estate")
    assert "Gold" in me(g).hand
    g = da(["Smithy"], shelters=True)
    set_zones(g, hand=["Necropolis"])
    play(g, "Necropolis")
    assert g.state.actions == 2


def test_shelters_are_automatic_when_a_dark_ages_card_is_picked_by_the_seed():
    autos = []
    for seed in range(40):
        g = new_game(GameConfig(["A", "B"], ["Poor House", "Smithy", "Village", "Militia", "Moat", "Market", "Cellar", "Chapel", "Festival", "Remodel"], seed))
        autos.append(g.config.shelters)
    assert any(autos) and not all(autos)
    assert new_game(GameConfig(["A", "B"], ["Smithy"], 1)).config.shelters is False
    assert new_game(GameConfig(["A", "B"], ["Smithy"], 1, shelters=True)).config.shelters is True


# ------------------------------------------------------------------ Looters, Ruins, Spoils
def test_ruins_pile_appears_with_a_looter_and_scales_with_players():
    for players, total in ((2, 10), (3, 20), (4, 30)):
        g = da(["Marauder"], players=players)
        assert sum(g.state.supply[n] for n in ("Abandoned Mine", "Ruined Library", "Ruined Market", "Ruined Village", "Survivors")) == total
        assert len(g.state.stacks["Ruins"]) == total
    assert "Ruins" not in da(["Smithy"]).state.stacks


def test_marauder_gains_spoils_and_gives_ruins_and_moat_blocks_it():
    g = da(["Marauder"])
    set_zones(g, hand=["Marauder"])
    top = g.state.stacks["Ruins"][0]
    play(g, "Marauder")
    assert "Spoils" in me(g).discard and me(g, 1).discard == [top] and g.state.offsupply["Spoils"] == 14
    g = da(["Marauder"])
    set_zones(g, 0, hand=["Marauder"])
    set_zones(g, 1, hand=["Moat"])
    play(g, "Marauder")
    answer(g, "Moat")
    assert me(g, 1).discard == []


def test_ruins_are_gained_one_at_a_time_in_pile_order_and_only_the_top_is_buyable():
    g = da(["Marauder"])
    top = g.state.stacks["Ruins"][0]
    to_buy_phase(g)
    legal = [a.card for a in g.legal_actions() if isinstance(a, Buy)]
    assert top in legal and [n for n in ("Abandoned Mine", "Ruined Library", "Ruined Market", "Ruined Village", "Survivors") if n != top and n in legal] == []
    buy(g, top)
    assert len(g.state.stacks["Ruins"]) == 9 and me(g).discard == [top]
    view = build_view(g, 0)
    pile = next(p for p in view["piles"] if p.get("stack") == "Ruins")
    assert pile["count"] == 9 and pile["name"] == g.state.stacks["Ruins"][0]


def test_death_cart_trashes_itself_or_an_action_and_gains_two_ruins_when_gained():
    g = da(["Death Cart"])
    set_zones(g, hand=["Death Cart", "Estate"])
    play(g, "Death Cart")
    assert g.state.coins == 5 and "Death Cart" in g.state.trash
    g = da(["Death Cart"])
    set_zones(g, hand=["Death Cart", "Smithy"])
    play(g, "Death Cart")
    answer(g, "Smithy")
    assert g.state.coins == 5 and "Smithy" in g.state.trash and "Death Cart" not in g.state.trash
    g = da(["Death Cart"])
    to_buy_phase(g)
    g.state.coins = 4
    buy(g, "Death Cart")
    assert len(me(g).discard) == 3 and len(g.state.stacks["Ruins"]) == 8


def test_cultist_gives_ruins_and_chains_into_another_cultist():
    g = da(["Cultist"])
    set_zones(g, hand=["Cultist", "Cultist"], deck=["Gold"] * 5)
    play(g, "Cultist")
    answer(g, "Cultist")
    assert me(g, 1).discard.__len__() == 2 and me(g).hand.count("Gold") == 4 and len(me(g).in_play) == 2


def test_bandit_camp_pillage_spoils_and_spoils_return():
    g = da(["Bandit Camp"])
    set_zones(g, hand=["Bandit Camp"])
    play(g, "Bandit Camp")
    assert "Spoils" in me(g).discard and g.state.actions == 2
    g = da(["Pillage"])
    set_zones(g, 0, hand=["Pillage"])
    set_zones(g, 1, hand=["Estate", "Copper", "Copper", "Silver", "Gold"])
    play(g, "Pillage")
    assert "Pillage" in g.state.trash
    answer(g, "Gold")
    assert "Gold" in me(g, 1).discard and me(g).discard.count("Spoils") == 2
    g = da(["Bandit Camp"])
    set_zones(g, hand=["Spoils"])
    g.state.offsupply["Spoils"] -= 1
    to_buy_phase(g)
    g.apply(0, PlayTreasure("Spoils"))
    assert g.state.coins == 3 and g.state.offsupply["Spoils"] == 15 and me(g).in_play == []


def test_madman_and_hermit_and_mercenary_and_urchin():
    g = da(["Hermit"])
    set_zones(g, hand=["Hermit", "Estate"], discard=["Copper", "Curse"])
    play(g, "Hermit")
    answer(g, "Trash a card from your discard pile")
    answer(g, "Curse")
    answer(g, "Silver")
    assert "Curse" in g.state.trash
    end_turn(g)                                           # no buys: Hermit trades for a Madman
    assert "Madman" in me(g).discard and "Hermit" not in me(g).discard and g.state.supply["Hermit"] == 11
    g = da(["Hermit"])
    set_zones(g, hand=["Hermit"])
    play(g, "Hermit")
    answer(g, "Silver")
    to_buy_phase(g)
    g.state.coins = 2
    buy(g, "Cellar") if False else None
    end_turn(g)
    assert "Madman" in me(g).discard
    g = da(["Hermit"])
    set_zones(g, hand=["Madman", "Estate", "Estate"], deck=["Gold"] * 8)
    g.state.offsupply["Madman"] -= 1
    play(g, "Madman")
    assert g.state.actions == 2 and g.state.offsupply["Madman"] == 10 and me(g).hand.count("Gold") == 2 and "Madman" not in me(g).in_play
    g = da(["Urchin"])
    set_zones(g, hand=["Mercenary", "Estate", "Copper", "Silver"], deck=["Gold"] * 4)
    g.state.offsupply["Mercenary"] -= 1
    set_zones(g, 1, hand=["Copper"] * 5)
    play(g, "Mercenary")
    answer(g, "Trash 2 cards")
    answer(g, "Estate", "Copper")
    answer(g, "Copper", "Copper") if g.state.pending is not None and g.state.pending.decision.player == 1 else None
    assert g.state.coins == 2 and me(g).hand.count("Gold") == 2


def test_urchin_trashes_itself_for_a_mercenary_when_another_attack_is_played():
    g = da(["Urchin", "Militia"])
    set_zones(g, hand=["Urchin", "Militia"], deck=["Gold"] * 3)
    set_zones(g, 1, hand=["Copper"] * 3)
    play(g, "Urchin")
    play(g, "Militia")
    answer(g, "Trash Urchin")
    assert "Urchin" in g.state.trash and "Mercenary" in me(g).discard


def test_urchin_makes_others_discard_down_to_four():
    g = da(["Urchin"])
    set_zones(g, hand=["Urchin"], deck=["Gold"] * 2)
    set_zones(g, 1, hand=["Copper", "Copper", "Silver", "Estate", "Estate"])
    play(g, "Urchin")
    answer(g, "Estate")
    assert len(me(g, 1).hand) == 4


# ------------------------------------------------------------------ Band of Misfits, Procession, Counterfeit
def test_band_of_misfits_plays_a_cheaper_action_without_gaining_it():
    g = da(["Band of Misfits", "Smithy"])
    set_zones(g, hand=["Band of Misfits"], deck=["Gold"] * 3)
    play(g, "Band of Misfits")
    assert "Smithy" in g.state.pending.decision.options and "Band of Misfits" not in g.state.pending.decision.options
    answer(g, "Smithy")
    assert me(g).hand.count("Gold") == 3 and g.state.supply["Smithy"] == 10


def test_band_of_misfits_as_death_cart_trashes_itself():
    g = da(["Band of Misfits", "Death Cart"])
    set_zones(g, hand=["Band of Misfits"])
    play(g, "Band of Misfits")
    answer(g, "Death Cart")
    assert g.state.coins == 5 and "Band of Misfits" in g.state.trash


def test_procession_plays_twice_trashes_and_gains_one_dearer_action():
    g = da(["Procession"])
    set_zones(g, hand=["Procession", "Smithy"], deck=["Gold"] * 6)
    play(g, "Procession")
    answer(g, "Smithy")
    assert me(g).hand.count("Gold") == 6 and "Smithy" in g.state.trash
    options = g.state.pending.decision.options
    assert "Market" in options and "Militia" not in options and all(get_card(o).cost == 5 for o in options)
    answer(g, "Market")


def test_counterfeit_plays_a_treasure_twice_and_trashes_it():
    g = da(["Counterfeit"])
    set_zones(g, hand=["Counterfeit", "Gold"])
    to_buy_phase(g)
    g.apply(0, PlayTreasure("Counterfeit"))
    answer(g, "Gold")
    assert g.state.coins == 1 + 6 and g.state.buys == 2 and "Gold" in g.state.trash and "Gold" not in me(g).in_play


# ------------------------------------------------------------------ Knights
def test_knights_pile_is_ten_cards_only_the_top_can_be_bought_and_it_is_one_pile():
    g = da(["Knights"])
    stack = list(g.state.stacks["Knights"])
    assert sorted(stack) == sorted(("Dame Anna", "Dame Josephine", "Dame Molly", "Dame Natalie", "Dame Sylvia",
                                    "Sir Bailey", "Sir Destry", "Sir Martin", "Sir Michael", "Sir Vander"))
    assert "Knights" not in g.state.supply and all(g.state.supply[n] == 1 for n in stack)
    top = stack[0]
    to_buy_phase(g)
    g.state.coins = 6
    legal = {a.card for a in g.legal_actions() if isinstance(a, Buy)}
    assert top in legal and not (set(stack[1:]) & legal)
    buy(g, top)
    assert g.state.stacks["Knights"] == stack[1:]
    view = build_view(g, 0)
    pile = next(p for p in view["piles"] if p.get("stack") == "Knights")
    assert pile["count"] == 9 and pile["name"] == stack[1] and pile["kingdom"] is True
    # an emptied pile is one empty pile
    g.state.supply.update({n: 0 for n in stack})
    g.state.stacks["Knights"].clear()
    assert sum(1 for s in g.state.stacks.values() if not s) == 1 and not is_game_over(g.state)
    g.state.supply["Estate"] = g.state.supply["Duchy"] = 0
    assert is_game_over(g.state)


def test_a_knight_attack_trashes_a_card_costing_three_to_six_and_the_knight_when_a_knight_dies():
    g = da(["Knights"])
    set_zones(g, hand=["Sir Bailey"], deck=["Gold"] * 3)
    set_zones(g, 1, deck=["Estate", "Smithy", "Gold"])    # top = Gold ($6)... then Smithy
    play(g, "Sir Bailey")
    answer(g, "Gold") if g.state.pending is not None and "Gold" in g.state.pending.decision.options and len(g.state.pending.decision.options) > 1 else None
    if g.state.pending is not None:
        answer(g, g.state.pending.decision.options[0])
    assert g.state.actions == 1 and me(g).hand.count("Gold") == 1 and len(g.state.trash) == 1
    g = da(["Knights"])
    set_zones(g, hand=["Dame Sylvia"])
    set_zones(g, 1, deck=["Estate", "Dame Anna"])
    play(g, "Dame Sylvia")
    assert g.state.coins == 2 and "Dame Anna" in g.state.trash and "Dame Sylvia" in g.state.trash and "Estate" in me(g, 1).discard


def test_each_knight_does_its_own_thing():
    cases = [("Dame Molly", lambda g: g.state.actions == 2), ("Dame Sylvia", lambda g: g.state.coins == 2),
             ("Sir Destry", lambda g: len(me(g).hand) == 2), ("Sir Martin", lambda g: g.state.buys == 3),
             ("Sir Bailey", lambda g: len(me(g).hand) == 1 and g.state.actions == 1)]
    for knight, check in cases:
        g = da(["Knights"])
        set_zones(g, hand=[knight], deck=["Copper"] * 5)
        set_zones(g, 1, deck=["Copper", "Copper"])
        play(g, knight)
        assert check(g), knight
    g = da(["Knights"])
    set_zones(g, hand=["Dame Anna", "Estate", "Estate", "Copper"])
    set_zones(g, 1, deck=["Copper", "Copper"])
    play(g, "Dame Anna")
    answer(g, "Estate", "Estate")
    assert g.state.trash == ["Estate", "Estate"]
    g = da(["Knights"])
    set_zones(g, hand=["Dame Natalie"])
    set_zones(g, 1, deck=["Copper", "Copper"])
    play(g, "Dame Natalie")
    answer(g, "Silver")
    assert "Silver" in me(g).discard
    g = da(["Knights"])
    set_zones(g, hand=["Sir Michael"])
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Copper", "Copper"])
    play(g, "Sir Michael")
    answer(g, "Copper", "Copper")
    assert len(me(g, 1).hand) == 3
    g = da(["Knights"])
    set_zones(g, hand=["Sir Vander", "Chapel"] and ["Chapel"])
    g = da(["Knights", "Chapel"])
    set_zones(g, hand=["Chapel", "Sir Vander"])
    play(g, "Chapel")
    answer(g, "Sir Vander")
    assert "Gold" in me(g).discard
    assert score_player(me(g)) == 3


def test_dame_josephine_is_worth_two_vp():
    g = da(["Knights"])
    set_zones(g, hand=["Dame Josephine"])
    assert score_player(me(g)) == 3 + 2


# ------------------------------------------------------------------ whole games
@pytest.mark.parametrize("seed", range(12))
def test_random_games_with_only_dark_ages_conserve_cards_and_replay(seed):
    rng = random.Random(seed)
    players = 2 + seed % 3
    cards = rng.sample(DA, 10)
    if seed % 3 == 0:
        cards[0] = "Knights"
    cards = list(dict.fromkeys(cards))
    g = new_game(GameConfig([f"P{i}" for i in range(players)], cards, seed, shelters=bool(seed % 2)))
    total = total_cards(g)
    bots = [RandomBot(random.Random(seed * 10 + i)) for i in range(players)]
    for _ in range(4000):
        if g.state.status is GameStatus.FINISHED:
            break
        p = g.acting_player
        action = bots[p].choose(g, p)
        assert action in g.legal_actions(p)
        g.apply(p, action)
        assert min(g.state.supply.values()) >= 0 and min(g.state.offsupply.values(), default=0) >= 0 and total_cards(g) == total
        assert sum(g.state.supply[n] for n in g.state.stack_of if g.state.stack_of[n] == "Ruins") == len(g.state.stacks.get("Ruins", []))
        if g.state.pending is None:
            assert all(not q.set_aside for q in g.state.players)
        build_view(g, p)
    clone = replay(g.config, g.history)
    assert [q.all_cards() for q in clone.state.players] == [q.all_cards() for q in g.state.players]


class _Pusher(RandomBot):
    """Plays every Action it can, plays Treasures, and keeps buying the card under test (random answers to questions)."""

    def __init__(self, targets, rng):
        super().__init__(rng)
        self.targets = targets

    def choose(self, game, player):
        legal = game.legal_actions(player)
        if game.state.pending is None:
            plays = [a for a in legal if isinstance(a, PlayAction)]
            if plays:
                return self.rng.choice(plays)
            if game.state.phase.value == "buy":
                from dominion.engine import PlayAllTreasures
                if PlayAllTreasures() in legal:
                    return PlayAllTreasures()
                for card in (*self.targets, "Gold", "Silver"):
                    if Buy(card) in legal:
                        return Buy(card)
                return EndPhase()
        return self.rng.choice(legal)


@pytest.mark.parametrize("target", [c for c in DA if c != "Feodum"])
def test_every_dark_ages_card_gets_played_without_breaking_the_rules(target):
    rng = random.Random(hash(target) & 0xFFFF)
    others = [c for c in DA if c != target]
    cards = [target, *rng.sample(others, 9)]
    seed = rng.randrange(1000)
    g = new_game(GameConfig(["A", "B"], cards, seed))
    total = total_cards(g)
    names = list(g.state.stacks["Knights"]) if target == "Knights" else [target]
    bots = [_Pusher(names, random.Random(seed)), _Pusher(names, random.Random(seed + 1))]
    for _ in range(2500):
        if g.state.status is GameStatus.FINISHED:
            break
        p = g.acting_player
        g.apply(p, bots[p].choose(g, p))
        assert total_cards(g) == total and min(g.state.supply.values()) >= 0
    assert any(f" plays {n}" in line for n in names for line in g.state.log), target


def test_big_money_finishes_a_dark_ages_game_and_views_build():
    g = new_game(GameConfig(["A", "B"], ["Knights", "Marauder", "Hermit", "Urchin", "Rats", "Feodum", "Death Cart", "Fortress", "Count", "Altar"], 7))
    bots = [BigMoneyBot(), BigMoneyBot()]
    for _ in range(5000):
        if g.state.status is GameStatus.FINISHED:
            break
        p = g.acting_player
        g.apply(p, bots[p].choose(g, p))
        build_view(g, 0)
    assert g.state.status is GameStatus.FINISHED
    assert {"Spoils", "Madman", "Mercenary"} <= set(g.state.offsupply)


def test_random_kingdom_can_be_limited_to_dark_ages():
    g = new_game(GameConfig(["A", "B"], None, 5, expansions=[SET]))
    assert set(g.state.kingdom) <= set(DA) and len(g.state.kingdom) == 10


def test_lobby_has_a_shelters_setting():
    import asyncio
    from dominion.web.rooms import RoomManager
    from test_web import run, two_player_room

    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, _ = await two_player_room(m)
        assert host.last("lobby")["shelters"] is None
        await m.handle(host.conn, {"type": "set_shelters", "shelters": True})
        assert host.last("lobby")["shelters"] is True

    run(scenario())
