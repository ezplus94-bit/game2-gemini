"""Renaissance (2018): Villagers, Projects, Artifacts and every Kingdom card."""

import random

import pytest

from dominion.ai import RandomBot, BigMoneyBot, run_game
from dominion.cards import CardType, get_card, kingdom_cards, project_cards
from dominion.cards.renaissance import ARTIFACTS
from dominion.engine import (
    Buy, BuyEvent, Choose, EndPhase, GameConfig, GameStatus, IllegalActionError, Phase, PlayAction, PlayAllTreasures, PlayTreasure,
    SpendCoffers, SpendVillager, action_from_dict, action_to_dict, build_view, new_game, replay,
)
from dominion.engine.scoring import score_player
from helpers import make_game, set_zones, to_buy_phase

FILLER = ["Village", "Smithy", "Militia", "Moat", "Market", "Cellar", "Chapel", "Festival", "Laboratory", "Remodel"]
PROJECT_COSTS = {"Cathedral": 3, "City Gate": 3, "Pageant": 3, "Star Chart": 3, "Exploration": 4, "Fair": 4, "Silos": 4, "Sinister Plot": 4,
                 "Sewers": 4, "Academy": 5, "Capitalism": 5, "Fleet": 5, "Guildhall": 5, "Piazza": 5, "Road Network": 5, "Barracks": 6,
                 "Crop Rotation": 6, "Innovation": 6, "Canal": 7, "Citadel": 8}


def rn(cards, projects=(), players=2, seed=1, **kw):
    kw.setdefault("shelters", False)
    return make_game(players=players, kingdom=[*cards, *[f for f in FILLER if f not in cards]][:10], seed=seed, events=list(projects), **kw)


def me(g, i=0):
    return g.state.players[i]


def play(g, card):
    g.apply(g.acting_player, PlayAction(card))


def answer(g, *cards):
    g.apply(g.acting_player, Choose(tuple(cards)))


def end(g):
    g.apply(g.acting_player, EndPhase())


def log(g):
    return "\n".join(map(str, g.state.log))


def finish_turn(g):
    start = g.state.turn_number
    while g.state.status is GameStatus.ACTIVE and g.state.turn_number == start:
        if g.state.pending is not None:
            d = g.state.pending.decision
            g.apply(g.acting_player, Choose(() if d.min_choices == 0 else tuple(d.options[:d.min_choices])))
        else:
            g.apply(g.acting_player, EndPhase())


def next_turn_start(g):
    """End the turn in progress without answering anything fancy and stop at the first question or the next player's Action phase."""
    start = g.state.turn_number
    while g.state.turn_number == start and g.state.pending is None:
        end(g)


def buy_project(g, name, coins=None):
    to_buy_phase(g)
    g.state.coins = PROJECT_COSTS[name] if coins is None else coins
    g.apply(g.acting_player, BuyEvent(name))


# ------------------------------------------------------------------ the set
def test_set_contents():
    names = kingdom_cards(["Renaissance"])
    assert len(names) == 25 and len(project_cards()) == 20 and len(ARTIFACTS) == 5
    costs = {"Border Guard": 2, "Ducat": 2, "Lackeys": 2, "Acting Troupe": 3, "Cargo Ship": 3, "Experiment": 3, "Improve": 3, "Flag Bearer": 4,
             "Hideout": 4, "Inventor": 4, "Mountain Village": 4, "Patron": 4, "Priest": 4, "Research": 4, "Silk Merchant": 4, "Old Witch": 5,
             "Recruiter": 5, "Scepter": 5, "Scholar": 5, "Sculptor": 5, "Seer": 5, "Spices": 5, "Swashbuckler": 5, "Treasurer": 5, "Villain": 5}
    assert {n: get_card(n).cost for n in names} == costs
    assert {n: get_card(n).cost for n in project_cards()} == PROJECT_COSTS
    assert all(CardType.PROJECT in get_card(n).types and not get_card(n).kingdom for n in project_cards())
    assert get_card("Ducat").is_type(CardType.TREASURE) and get_card("Cargo Ship").is_type(CardType.DURATION)


def test_projects_are_picked_automatically_with_a_renaissance_card():
    g = new_game(GameConfig(["A", "B"], ["Fair"] and ["Villain", "Scholar", "Village", "Smithy", "Militia", "Moat", "Market", "Cellar", "Chapel", "Remodel"], 3, shelters=False))
    assert len(g.state.events) == 2 and all(CardType.PROJECT in get_card(n).types or CardType.EVENT in get_card(n).types
                                            or CardType.LANDMARK in get_card(n).types for n in g.state.events)
    plain = new_game(GameConfig(["A", "B"], FILLER, 3, shelters=False))
    assert plain.state.events == ()


def test_config_accepts_projects_and_at_most_two():
    g = rn(["Villain"], ["Fair", "Silos"])
    assert set(g.state.events) == {"Fair", "Silos"}
    with pytest.raises(ValueError):
        rn(["Villain"], ["Fair", "Silos", "Canal"])


# ------------------------------------------------------------------ Villagers
def test_villagers_give_actions_in_the_action_phase_only():
    g = rn(["Recruiter"])
    me(g).villagers = 3
    assert SpendVillager(1) in g.legal_actions() and SpendVillager(3) in g.legal_actions()
    g.apply(0, SpendVillager(2))
    assert g.state.actions == 3 and me(g).villagers == 1
    with pytest.raises(IllegalActionError):
        g.apply(0, SpendVillager(2))
    end(g)
    assert not any(isinstance(a, SpendVillager) for a in g.legal_actions())
    with pytest.raises(IllegalActionError):
        g.apply(0, SpendVillager(1))


def test_spend_villager_codec_and_view():
    assert action_from_dict(action_to_dict(SpendVillager(2))) == SpendVillager(2)
    g = rn(["Recruiter"])
    me(g).villagers = 2
    v = build_view(g, 0)
    assert v["players"][0]["villagers"] == 2 and {"type": "spend_villager", "count": 1} in v["legal_actions"]


def test_acting_troupe():
    g = rn(["Acting Troupe"])
    set_zones(g, hand=["Acting Troupe", "Copper"])
    play(g, "Acting Troupe")
    assert me(g).villagers == 4 and g.state.trash == ["Acting Troupe"] and "Acting Troupe" not in me(g).in_play


# ------------------------------------------------------------------ Artifacts
def test_border_guard_artifacts_flow():
    g = rn(["Border Guard"])
    assert g.state.artifacts == {"Horn": None, "Lantern": None}
    set_zones(g, hand=["Border Guard", "Copper"], deck=["Copper", "Village", "Smithy"])
    play(g, "Border Guard")
    assert g.state.actions == 1
    answer(g, "Village")
    assert "Village" in me(g).hand and me(g).discard == ["Smithy"]
    answer(g, "Lantern")
    assert g.state.artifacts["Lantern"] == 0
    set_zones(g, hand=["Border Guard"], deck=["Copper", "Village", "Smithy", "Market"], discard=[])
    g.state.actions = 1
    play(g, "Border Guard")
    assert set(g.state.pending.decision.options) == {"Village", "Smithy", "Market"}
    answer(g, "Market")
    assert set(g.state.pending.decision.options) == {"Take the Horn"}
    answer(g, "Take the Horn")
    assert g.state.artifacts["Horn"] == 0


def test_border_guard_without_two_actions_takes_nothing_and_lantern_needs_three():
    g = rn(["Border Guard"])
    set_zones(g, hand=["Border Guard"], deck=["Copper", "Village", "Gold"])
    play(g, "Border Guard")
    answer(g, "Gold")
    assert g.state.pending is None and g.state.artifacts["Lantern"] is None
    g = rn(["Border Guard"])
    g.state.artifacts["Lantern"] = 0
    set_zones(g, hand=["Border Guard"], deck=["Copper", "Village", "Smithy", "Gold"])
    play(g, "Border Guard")
    answer(g, "Gold")
    assert g.state.pending is None and g.state.artifacts["Horn"] is None


def test_horn_puts_border_guard_on_deck_at_cleanup():
    g = rn(["Border Guard"])
    g.state.artifacts["Horn"] = 0
    set_zones(g, hand=["Border Guard", "Copper", "Copper", "Copper", "Copper"], deck=["Gold"] * 6 + ["Copper", "Estate", "Estate"])
    play(g, "Border Guard")
    answer(g, "Estate")
    end(g)
    end(g)
    assert g.state.pending is not None and "Horn" in g.state.pending.decision.prompt
    answer(g, "Put it onto your deck")
    assert "Border Guard" in me(g).hand        # drawn again with the new hand
    assert "Border Guard" not in me(g).discard


def test_flag_bearer_takes_flag_when_gained_or_trashed_and_flag_draws_extra():
    g = rn(["Flag Bearer"])
    set_zones(g, hand=["Copper"] * 5)
    to_buy_phase(g)
    g.state.coins = 4
    g.apply(0, Buy("Flag Bearer"))
    assert g.state.artifacts["Flag"] == 0
    end(g)
    assert len(me(g).hand) == 6
    g.state.artifacts["Flag"] = 1
    set_zones(g, 0, hand=["Flag Bearer", "Copper"])
    me(g, 0).hand.append("Flag Bearer")
    from dominion.engine.zones import trash_from_hand
    trash_from_hand(g.state, 0, "Flag Bearer")
    g.state.trash_events.clear()
    g.state.gain_events.clear()
    g.state.artifacts["Flag"] = 1
    from dominion.engine.zones import send_to_trash
    g2 = rn(["Flag Bearer"])
    set_zones(g2, hand=["Flag Bearer", "Copper"])
    g2.state.artifacts["Flag"] = 1
    me(g2).hand.remove("Flag Bearer")
    send_to_trash(g2.state, 0, "Flag Bearer")
    g2._settle()
    assert g2.state.artifacts["Flag"] == 0


def test_treasure_chest_gold_each_buy_phase_and_key_coin():
    g = rn(["Swashbuckler"])
    g.state.artifacts["Treasure Chest"] = 0
    set_zones(g, hand=["Copper"] * 5)
    end(g)
    assert "Gold" in me(g).discard
    g = rn(["Treasurer"])
    g.state.artifacts["Key"] = 1
    end(g); end(g)
    assert g.state.current_player == 1 and g.state.coins == 1


# ------------------------------------------------------------------ Kingdom cards
def test_cargo_ship_sets_a_gained_card_aside_for_next_turn():
    g = rn(["Cargo Ship"])
    set_zones(g, hand=["Cargo Ship", "Copper", "Copper", "Copper", "Copper"])
    play(g, "Cargo Ship")
    assert g.state.coins == 2
    to_buy_phase(g)
    g.state.coins, g.state.buys = 9, 2
    g.apply(0, Buy("Gold"))
    answer(g, "Set it aside")
    assert me(g).cargo_aside == ["Gold"] and "Gold" not in me(g).discard
    g.apply(0, Buy("Silver"))
    assert g.state.pending is None and "Silver" in me(g).discard
    assert me(g).all_cards().count("Gold") == 1
    end(g)
    assert "Cargo Ship" in me(g).in_play
    finish_turn(g)
    assert "Gold" in me(g).hand and not me(g).cargo_aside


def test_cargo_ship_that_sets_nothing_aside_is_discarded():
    g = rn(["Cargo Ship"])
    set_zones(g, hand=["Cargo Ship", "Copper", "Copper", "Copper", "Copper"])
    play(g, "Cargo Ship")
    end(g); end(g)
    assert "Cargo Ship" not in me(g).in_play


def test_ducat():
    g = rn(["Ducat"])
    set_zones(g, hand=["Ducat", "Copper", "Copper"])
    to_buy_phase(g)
    g.apply(0, PlayTreasure("Ducat"))
    assert g.state.coins == 0 and me(g).coffers == 1 and g.state.buys == 2
    g.state.coins = 2
    g.apply(0, Buy("Ducat"))
    answer(g, "Trash a Copper")
    assert g.state.trash == ["Copper"] and "Ducat" in me(g).discard


def test_experiment_returns_and_gains_two():
    g = rn(["Experiment"])
    set_zones(g, hand=["Experiment", "Copper"], deck=["Gold"] * 4)
    play(g, "Experiment")
    assert g.state.supply["Experiment"] == 11 and g.state.actions == 1 and len(me(g).hand) == 3
    g2 = rn(["Experiment"])
    set_zones(g2, hand=["Copper"] * 5)
    to_buy_phase(g2)
    g2.state.coins = 3
    g2.apply(0, Buy("Experiment"))
    assert me(g2).discard.count("Experiment") == 2 and g2.state.supply["Experiment"] == 8 and g2.state.pending is None


def test_experiment_second_copy_goes_to_discard_when_first_goes_to_hand():
    g = rn(["Experiment", "Sculptor"])
    set_zones(g, hand=["Sculptor"])
    play(g, "Sculptor")
    answer(g, "Experiment")
    assert me(g).hand == ["Experiment"] and me(g).discard == ["Experiment"] and g.state.supply["Experiment"] == 8


def test_hideout():
    g = rn(["Hideout"])
    set_zones(g, hand=["Hideout", "Estate", "Copper"], deck=["Gold"] * 3)
    play(g, "Hideout")
    assert g.state.actions == 2
    answer(g, "Estate")
    assert "Curse" in me(g).discard and g.state.trash == ["Estate"]
    g = rn(["Hideout"])
    set_zones(g, hand=["Hideout", "Copper"], deck=["Gold"] * 3)
    play(g, "Hideout")
    answer(g, "Copper")
    assert "Curse" not in me(g).discard


def test_improve_trashes_an_action_at_cleanup_for_exactly_one_more():
    g = rn(["Improve"])
    set_zones(g, hand=["Improve", "Village", "Copper", "Copper", "Copper"])
    play(g, "Village")
    play(g, "Improve")
    assert g.state.coins == 2
    end(g); end(g)
    assert set(g.state.pending.decision.options) == {"Improve", "Village"}
    answer(g, "Village")
    assert g.state.trash == ["Village"] and "Village" not in me(g).in_play
    assert "Smithy" in g.state.pending.decision.options                       # costing exactly $4: Village ($3) + 1
    assert "Gold" not in g.state.pending.decision.options and "Silver" not in g.state.pending.decision.options
    answer(g, "Smithy")
    assert "Smithy" in me(g).all_cards()                                       # (gained during Clean-up, so it may already be in the new deck)


def test_inventor_gains_and_lowers_costs():
    g = rn(["Inventor"])
    set_zones(g, hand=["Inventor", "Inventor"])
    g.state.actions = 2
    play(g, "Inventor")
    answer(g, "Silver")
    assert g.state.cost_reduction == 1
    play(g, "Inventor")
    assert "Duchy" in g.state.pending.decision.options and "Province" not in g.state.pending.decision.options      # Duchy now costs $4
    answer(g, "Smithy")
    from dominion.engine.costs import card_cost
    assert card_cost(g.state, "Province") == 6 and card_cost(g.state, "Silver") == 1


def test_lackeys():
    g = rn(["Lackeys"])
    set_zones(g, hand=["Lackeys"], deck=["Gold"] * 4)
    play(g, "Lackeys")
    assert len(me(g).hand) == 2
    set_zones(g, hand=["Copper"] * 5)
    to_buy_phase(g)
    g.state.coins = 2
    g.apply(0, Buy("Lackeys"))
    assert me(g).villagers == 2


def test_mountain_village():
    g = rn(["Mountain Village"])
    set_zones(g, hand=["Mountain Village"], deck=["Gold"] * 3, discard=["Silver", "Curse"])
    play(g, "Mountain Village")
    assert g.state.actions == 2
    answer(g, "Silver")
    assert me(g).hand == ["Silver"] and me(g).discard == ["Curse"]
    g = rn(["Mountain Village"])
    set_zones(g, hand=["Mountain Village"], deck=["Gold"] * 3, discard=[])
    play(g, "Mountain Village")
    assert me(g).hand == ["Gold"]


def test_old_witch():
    g = rn(["Old Witch"])
    set_zones(g, hand=["Old Witch"], deck=["Gold"] * 4)
    set_zones(g, 1, hand=["Curse", "Copper", "Copper", "Copper", "Copper"])
    play(g, "Old Witch")
    assert len(me(g).hand) == 3 and me(g, 1).discard == ["Curse"]
    assert g.state.pending.decision.player == 1
    answer(g, "Trash a Curse")
    assert g.state.trash == ["Curse"] and "Curse" not in me(g, 1).hand
    g = rn(["Old Witch"])
    set_zones(g, hand=["Old Witch"], deck=["Gold"] * 4)
    set_zones(g, 1, hand=["Copper"] * 5)
    play(g, "Old Witch")
    assert me(g, 1).discard == ["Curse"] and g.state.pending is None


def test_patron_gives_villager_coins_and_coffers_when_revealed():
    g = rn(["Patron", "Border Guard"])
    set_zones(g, hand=["Patron", "Copper"])
    play(g, "Patron")
    assert me(g).villagers == 1 and g.state.coins == 2
    g = rn(["Patron", "Border Guard"])
    set_zones(g, hand=["Border Guard"], deck=["Copper", "Patron", "Patron"])
    play(g, "Border Guard")
    assert me(g).coffers == 2                                  # two Patrons revealed
    answer(g, "Patron")


def test_priest_and_sewers_bonus_for_trashing():
    g = rn(["Priest"])
    set_zones(g, hand=["Priest", "Priest", "Estate", "Copper", "Curse"])
    g.state.actions = 2
    play(g, "Priest")
    answer(g, "Estate")
    assert g.state.coins == 2 and g.state.trash == ["Estate"]
    play(g, "Priest")
    answer(g, "Curse")
    assert g.state.coins == 2 + 2 + 2 and g.state.trash == ["Estate", "Curse"]


def test_recruiter():
    g = rn(["Recruiter"])
    set_zones(g, hand=["Recruiter", "Silver", "Copper"], deck=["Gold"] * 2)
    play(g, "Recruiter")
    answer(g, "Silver")
    assert me(g).villagers == 3 and g.state.trash == ["Silver"]


def test_research():
    g = rn(["Research"])
    set_zones(g, hand=["Research", "Silver", "Copper"], deck=["Estate", "Gold", "Curse", "Duchy"])
    play(g, "Research")
    answer(g, "Silver")
    assert g.state.actions == 1 and len(me(g).research_aside) == 3 and me(g).deck == ["Estate"]
    assert score_player(me(g), g.state) == me(g).all_cards().count("Estate") + 3 - 1
    end(g); end(g)
    assert "Research" in me(g).in_play
    finish_turn(g)
    assert not me(g).research_aside and me(g).hand.count("Duchy") == 1 and me(g).hand.count("Gold") == 1


def test_research_trashing_a_free_card_sets_nothing_aside():
    g = rn(["Research"])
    set_zones(g, hand=["Research", "Copper"], deck=["Gold"] * 3)
    play(g, "Research")
    answer(g, "Copper")
    end(g); end(g)
    assert "Research" not in me(g).in_play


def test_scepter_coins_or_replay():
    g = rn(["Scepter"])
    set_zones(g, hand=["Village", "Smithy", "Scepter"], deck=["Gold"] * 8)
    play(g, "Village")
    to_buy_phase(g)
    g.apply(0, PlayTreasure("Scepter"))
    assert set(g.state.pending.decision.options) == {"+$2", "Replay an Action card"}
    answer(g, "Replay an Action card")
    answer(g, "Village")
    assert g.state.actions == 1 - 1 + 2 + 2 and me(g).in_play.count("Village") == 1
    g = rn(["Scepter"])
    set_zones(g, hand=["Scepter"])
    to_buy_phase(g)
    g.apply(0, PlayTreasure("Scepter"))
    assert g.state.pending.decision.options == ("+$2",)                        # nothing to replay
    answer(g, "+$2")
    assert g.state.coins == 2


def test_scholar():
    g = rn(["Scholar"])
    set_zones(g, hand=["Scholar", "Copper", "Copper"], deck=["Gold"] * 8)
    play(g, "Scholar")
    assert me(g).hand == ["Gold"] * 7 and me(g).discard == ["Copper", "Copper"]


def test_sculptor():
    g = rn(["Sculptor"])
    set_zones(g, hand=["Sculptor"])
    play(g, "Sculptor")
    answer(g, "Silver")
    assert me(g).hand == ["Silver"] and me(g).villagers == 1
    g = rn(["Sculptor"])
    set_zones(g, hand=["Sculptor"])
    play(g, "Sculptor")
    answer(g, "Smithy")
    assert me(g).hand == ["Smithy"] and me(g).villagers == 0


def test_seer():
    g = rn(["Seer"])
    set_zones(g, hand=["Seer"], deck=["Gold", "Silver", "Estate", "Copper", "Smithy", "Curse", "Village"])
    play(g, "Seer")
    assert me(g).hand == ["Village", "Smithy"] and g.state.actions == 1        # revealed Curse, Smithy, Copper: only Smithy costs $2 to $4
    assert set(g.state.pending.decision.options) == {"Curse", "Copper"}       # the other two go back in an order of your choice


def test_silk_merchant_and_spices():
    g = rn(["Silk Merchant", "Spices"])
    set_zones(g, hand=["Silk Merchant", "Copper"], deck=["Gold"] * 4)
    play(g, "Silk Merchant")
    assert len(me(g).hand) == 3 and g.state.buys == 2
    set_zones(g, hand=["Copper"] * 5)
    to_buy_phase(g)
    g.state.coins = 9
    g.state.buys = 3
    g.apply(0, Buy("Silk Merchant"))
    assert me(g).coffers == 1 and me(g).villagers == 1
    g.apply(0, Buy("Spices"))
    assert me(g).coffers == 3
    set_zones(g, hand=["Spices"])
    buys = g.state.buys
    coins = g.state.coins
    g.apply(0, PlayTreasure("Spices"))
    assert g.state.buys == buys + 1 and g.state.coins == coins + 2


def test_swashbuckler_takes_treasure_chest_with_four_coffers():
    g = rn(["Swashbuckler"])
    me(g).coffers = 3
    set_zones(g, hand=["Swashbuckler"], deck=["Gold"] * 5, discard=["Copper"])
    play(g, "Swashbuckler")
    assert me(g).coffers == 4 and g.state.artifacts["Treasure Chest"] == 0
    g = rn(["Swashbuckler"])
    me(g).coffers = 3
    set_zones(g, hand=["Swashbuckler"], deck=["Gold"] * 5, discard=[])
    play(g, "Swashbuckler")
    assert me(g).coffers == 3 and g.state.artifacts["Treasure Chest"] is None


def test_treasurer_three_ways():
    g = rn(["Treasurer"])
    set_zones(g, hand=["Treasurer", "Silver", "Estate"])
    g.state.trash = ["Gold", "Estate"]
    play(g, "Treasurer")
    assert g.state.coins == 3 and set(g.state.pending.decision.options) == {
        "Trash a Treasure from your hand", "Gain a Treasure from the trash to your hand", "Take the Key"}
    answer(g, "Gain a Treasure from the trash to your hand")
    answer(g, "Gold")
    assert "Gold" in me(g).hand and g.state.trash == ["Estate"]
    g = rn(["Treasurer"])
    set_zones(g, hand=["Treasurer"])
    play(g, "Treasurer")
    assert g.state.pending.decision.options == ("Take the Key",)
    answer(g, "Take the Key")
    assert g.state.artifacts["Key"] == 0


def test_villain():
    g = rn(["Villain"])
    set_zones(g, hand=["Villain"])
    set_zones(g, 1, hand=["Copper", "Estate", "Silver", "Copper", "Copper"])
    play(g, "Villain")
    assert me(g).coffers == 2 and g.state.pending.decision.player == 1 and set(g.state.pending.decision.options) == {"Estate", "Silver"}
    answer(g, "Silver")
    assert me(g, 1).discard == ["Silver"]
    g = rn(["Villain"])
    set_zones(g, hand=["Villain"])
    set_zones(g, 1, hand=["Copper"] * 4)
    play(g, "Villain")
    assert g.state.pending is None


# ------------------------------------------------------------------ Projects
def test_buying_a_project_uses_a_buy_and_coins_and_places_a_cube():
    g = rn(["Villain"], ["Fair"])
    set_zones(g, hand=["Copper"] * 5)
    to_buy_phase(g)
    g.state.coins = 3
    assert BuyEvent("Fair") not in g.legal_actions()
    g.state.coins = 4
    assert BuyEvent("Fair") in g.legal_actions()
    g.apply(0, BuyEvent("Fair"))
    assert me(g).projects == ["Fair"] and g.state.coins == 0 and g.state.buys == 0
    g.state.coins, g.state.buys = 4, 1
    assert BuyEvent("Fair") not in g.legal_actions()
    with pytest.raises(IllegalActionError):
        g.apply(0, BuyEvent("Fair"))
    v = build_view(g, 1)
    assert v["events"][0]["owners"] == [0] and v["events"][0]["types"] == ["project"]


def test_fair_and_barracks_give_buy_and_action_each_turn():
    g = rn(["Villain"], ["Fair", "Barracks"])
    me(g, 1).projects = ["Fair", "Barracks"]
    finish_turn(g)
    assert g.state.current_player == 1 and g.state.buys == 2 and g.state.actions == 2


def test_academy_guildhall_road_network():
    g = rn(["Villain", "Hideout"], ["Academy", "Guildhall"])
    me(g).projects = ["Academy", "Guildhall"]
    set_zones(g, hand=["Copper"] * 5)
    to_buy_phase(g)
    g.state.coins, g.state.buys = 11, 3
    g.apply(0, Buy("Hideout"))
    g.apply(0, Buy("Silver"))
    assert me(g).villagers == 1 and me(g).coffers == 1
    g = rn(["Villain"], ["Road Network"])
    me(g, 1).projects = ["Road Network"]
    set_zones(g, hand=["Copper"] * 5)
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Gold"] * 5)
    to_buy_phase(g)
    g.state.coins = 5
    g.apply(0, Buy("Duchy"))
    assert len(me(g, 1).hand) == 6


def test_cathedral_city_gate_crop_rotation_silos_at_start_of_turn():
    g = rn(["Villain"], ["Cathedral"])
    me(g, 1).projects = ["Cathedral"]
    set_zones(g, 1, hand=["Estate", "Copper", "Copper", "Copper", "Copper"])
    finish_turn_to_question = lambda: next_turn_start(g)
    finish_turn_to_question()
    assert g.state.pending.decision.player == 1
    answer(g, "Estate")
    assert g.state.trash == ["Estate"]
    g = rn(["Villain"], ["City Gate"])
    me(g, 1).projects = ["City Gate"]
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Gold"] * 4)
    next_turn_start(g)
    answer(g, "Copper")
    assert len(me(g, 1).hand) == 5 and me(g, 1).deck[-1] == "Copper"
    g = rn(["Villain"], ["Crop Rotation"])
    me(g, 1).projects = ["Crop Rotation"]
    set_zones(g, 1, hand=["Estate", "Copper", "Copper", "Copper", "Copper"], deck=["Gold"] * 4)
    next_turn_start(g)
    answer(g, "Estate")
    assert len(me(g, 1).hand) == 6 and me(g, 1).discard == ["Estate"]
    g = rn(["Villain"], ["Silos"])
    me(g, 1).projects = ["Silos"]
    set_zones(g, 1, hand=["Copper", "Copper", "Estate", "Estate", "Estate"], deck=["Gold"] * 4)
    next_turn_start(g)
    answer(g, "Copper", "Copper")
    assert me(g, 1).hand.count("Gold") == 2 and me(g, 1).discard == ["Copper", "Copper"]


def test_sinister_plot_adds_tokens_then_draws():
    g = rn(["Villain"], ["Sinister Plot"])
    me(g, 1).projects = ["Sinister Plot"]
    next_turn_start(g)
    answer(g, "Add a token")
    assert me(g, 1).plot_tokens == 1
    finish_turn(g)
    finish_turn(g)
    assert g.state.pending is not None
    assert len(g.state.pending.decision.options) == 2
    set_zones(g, 1, deck=["Gold"] * 5)
    answer(g, g.state.pending.decision.options[1])
    assert me(g, 1).plot_tokens == 0 and me(g, 1).hand.count("Gold") == 1


def test_piazza_plays_a_revealed_action():
    g = rn(["Villain"], ["Piazza"])
    me(g, 1).projects = ["Piazza"]
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Gold", "Village"])
    next_turn_start(g)
    assert "Village" in me(g, 1).in_play and g.state.actions == 3
    g = rn(["Villain"], ["Piazza"])
    me(g, 1).projects = ["Piazza"]
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Gold", "Estate"])
    next_turn_start(g)
    assert me(g, 1).deck == ["Gold", "Estate"] and g.state.actions == 1


def test_exploration_and_pageant_at_end_of_buy_phase():
    g = rn(["Villain"], ["Exploration"])
    me(g).projects = ["Exploration"]
    set_zones(g, hand=["Copper"] * 5)
    end(g); end(g)
    assert me(g).coffers == 1 and me(g).villagers == 1
    g = rn(["Villain"], ["Exploration"])
    me(g).projects = ["Exploration"]
    set_zones(g, hand=["Copper"] * 5)
    to_buy_phase(g)
    g.state.coins = 3
    g.apply(0, Buy("Silver"))
    end(g)
    assert me(g).coffers == 0
    g = rn(["Villain"], ["Pageant"])
    me(g).projects = ["Pageant"]
    set_zones(g, hand=["Copper"] * 5)
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    end(g)
    answer(g, "Pay $1 for +1 Coffers")
    assert me(g).coffers == 1


def test_sewers_trash_when_trashing_otherwise():
    g = rn(["Priest"], ["Sewers"])
    me(g).projects = ["Sewers"]
    set_zones(g, hand=["Priest", "Estate", "Curse", "Copper"])
    play(g, "Priest")
    answer(g, "Estate")
    assert set(g.state.pending.decision.options) == {"Curse", "Copper"}
    answer(g, "Curse")
    assert g.state.pending is None and sorted(g.state.trash) == ["Curse", "Estate"]


def test_canal_makes_everything_cost_less_on_your_turn_only():
    g = rn(["Villain"], ["Canal"])
    me(g).projects = ["Canal"]
    from dominion.engine.costs import card_cost
    assert card_cost(g.state, "Province") == 7 and card_cost(g.state, "Copper") == 0
    finish_turn(g)
    assert card_cost(g.state, "Province") == 8


def test_capitalism_makes_plus_coin_actions_treasures():
    g = rn(["Villain"], ["Capitalism"])
    me(g).projects = ["Capitalism"]
    set_zones(g, hand=["Market", "Village", "Copper"], deck=["Gold"] * 3)
    to_buy_phase(g)
    legal = g.legal_actions()
    assert PlayTreasure("Market") in legal and PlayTreasure("Village") not in legal
    g.apply(0, PlayTreasure("Market"))
    assert g.state.coins == 1 and g.state.buys == 2 and "Market" in me(g).in_play


def test_citadel_plays_the_first_action_twice():
    g = rn(["Villain"], ["Citadel"])
    me(g).projects = ["Citadel"]
    set_zones(g, hand=["Smithy", "Smithy"], deck=["Gold"] * 10)
    g.state.actions = 2
    play(g, "Smithy")
    assert len(me(g).hand) == 1 + 6
    play(g, "Smithy")
    assert len(me(g).hand) == 7 + 3 - 1


def test_innovation_plays_the_first_gained_action():
    g = rn(["Villain"], ["Innovation"])
    me(g).projects = ["Innovation"]
    set_zones(g, hand=["Copper"] * 5, deck=["Gold"] * 5)
    to_buy_phase(g)
    g.state.coins, g.state.buys = 8, 2
    g.apply(0, Buy("Smithy"))
    answer(g, "Play it")
    assert "Smithy" in me(g).in_play and len(me(g).hand) == 8
    g.apply(0, Buy("Village"))
    assert g.state.pending is None and "Village" in me(g).discard


def test_star_chart_picks_top_card_after_a_shuffle():
    g = rn(["Villain"], ["Star Chart"])
    me(g).projects = ["Star Chart"]
    set_zones(g, hand=["Smithy"], deck=["Gold"], discard=["Estate", "Estate", "Curse", "Silver", "Copper", "Copper"])
    play(g, "Smithy")
    assert g.state.pending is not None and "Star Chart" in g.state.pending.decision.prompt
    answer(g, "Silver")
    assert len(me(g).hand) == 3 and "Silver" in me(g).hand


def test_star_chart_at_cleanup():
    g = rn(["Villain"], ["Star Chart"])
    me(g).projects = ["Star Chart"]
    set_zones(g, hand=["Copper"] * 5, deck=["Gold", "Gold"], discard=["Estate", "Curse", "Silver", "Copper"])
    end(g); end(g)
    assert g.state.pending is not None
    answer(g, "Silver")
    assert len(me(g).hand) == 5 and "Silver" in me(g).hand


def test_fleet_gives_an_extra_round_to_its_owners_after_the_game_ends():
    g = rn(["Villain"], ["Fleet"], players=3)
    me(g, 1).projects = ["Fleet"]
    g.state.supply["Province"] = 1
    set_zones(g, hand=["Copper"] * 5)
    to_buy_phase(g)
    g.state.coins = 8
    g.apply(0, Buy("Province"))
    end(g)
    assert g.state.status is GameStatus.ACTIVE and g.state.current_player == 1 and "Fleet" in log(g)
    finish_turn(g)
    assert g.state.status is GameStatus.FINISHED


def test_fleet_with_no_owner_ends_the_game_at_once():
    g = rn(["Villain"], ["Fair"])
    g.state.supply["Province"] = 1
    set_zones(g, hand=["Copper"] * 5)
    to_buy_phase(g)
    g.state.coins = 8
    g.apply(0, Buy("Province"))
    end(g)
    assert g.state.status is GameStatus.FINISHED


# ------------------------------------------------------------------ whole games
def count_all(g):
    s = g.state
    return (sum(s.supply.values()) + sum(s.offsupply.values()) + len(s.trash)
            + sum(len(p.all_cards()) for p in s.players) + sum(len(v) for v in s.stacks.values()) - sum(
                s.supply.get(n, 0) for n in s.stack_of))


@pytest.mark.parametrize("seed", range(60))
def test_random_games_with_renaissance_cards_hold_every_invariant(seed):
    rng = random.Random(seed)
    cards = rng.sample(kingdom_cards(["Renaissance"]), 10 if seed % 2 else 7) 
    cards += rng.sample([c for c in kingdom_cards(["Base", "Nocturne", "Adventures"]) if c not in cards], 10 - len(cards))
    projects = rng.sample(project_cards(), 2) if seed % 3 else None
    g = new_game(GameConfig(["A", "B", "C", "D"][: 2 + seed % 3], cards, seed, shelters=False, events=projects))
    start = count_all(g)
    bots = [RandomBot(random.Random(seed * 13 + i)) for i in range(4)]
    for _ in range(9000):
        if g.state.status is GameStatus.FINISHED:
            break
        p = g.acting_player
        g.apply(p, bots[p].choose(g, p))
        assert count_all(g) == start, g.state.log[-3:]
        assert all(q.villagers >= 0 and q.coffers >= 0 and q.plot_tokens >= 0 and len(q.projects) <= 2 for q in g.state.players)
        assert sum(1 for n, holder in g.state.artifacts.items() if holder is not None) <= len(g.state.artifacts)
    build_view(g, 0)
    clone = replay(g.config, g.history)
    assert clone.state.trash == g.state.trash and [q.projects for q in clone.state.players] == [q.projects for q in g.state.players]


def test_every_renaissance_card_survives_a_bot_game():
    for name in kingdom_cards(["Renaissance"]):
        cards = [name] + random.Random(1).sample([c for c in kingdom_cards(["Base"]) if c != name], 9)
        g = new_game(GameConfig(["A", "B"], cards, 3, shelters=False, events=["Citadel", "Innovation"]))
        bots = [RandomBot(random.Random(i)) for i in range(2)]
        for _ in range(2500):
            if g.state.status is GameStatus.FINISHED:
                break
            p = g.acting_player
            g.apply(p, bots[p].choose(g, p))


def test_every_project_survives_a_bot_game():
    for name in project_cards():
        cards = random.Random(2).sample(kingdom_cards(["Renaissance"]), 10)
        g = new_game(GameConfig(["A", "B"], cards, 5, shelters=False, events=[name]))
        for p in g.state.players:
            p.projects.append(name)
        bots = [RandomBot(random.Random(i)) for i in range(2)]
        for _ in range(2500):
            if g.state.status is GameStatus.FINISHED:
                break
            p = g.acting_player
            g.apply(p, bots[p].choose(g, p))


def test_view_shows_artifacts_and_card_info():
    g = rn(["Border Guard", "Treasurer"])
    g.state.artifacts["Key"] = 1
    v = build_view(g, 0)
    assert v["artifacts"] == {"Horn": None, "Lantern": None, "Key": 1}
    assert v["cards"]["Key"]["types"] == ["artifact"] and v["cards"]["Key"]["text"] == ARTIFACTS["Key"]
    assert v["nocturne"] is None


def test_capitalism_play_all_treasures_leaves_the_actions_alone():
    g = rn(["Villain"], ["Capitalism"])
    me(g).projects = ["Capitalism"]
    set_zones(g, hand=["Market", "Copper", "Copper"], deck=["Gold"] * 3)
    to_buy_phase(g)
    assert PlayAllTreasures() in g.legal_actions()
    g.apply(0, PlayAllTreasures())
    assert g.state.coins == 2 and "Market" in me(g).hand
    g2 = rn(["Villain"], ["Capitalism"])
    me(g2).projects = ["Capitalism"]
    set_zones(g2, hand=["Market", "Village"])
    to_buy_phase(g2)
    assert PlayAllTreasures() not in g2.legal_actions() and PlayTreasure("Market") in g2.legal_actions()


def test_star_chart_does_not_ask_without_a_shuffle():
    g = rn(["Villain"], ["Star Chart"])
    me(g).projects = ["Star Chart"]
    set_zones(g, hand=["Smithy"], deck=["Gold"] * 5)
    play(g, "Smithy")
    assert g.state.pending is None and len(me(g).hand) == 3


def test_citadel_replays_a_duration_card_and_unused_cargo_ships_are_discarded():
    g = rn(["Cargo Ship"], ["Citadel"])
    me(g).projects = ["Citadel"]
    set_zones(g, hand=["Cargo Ship"])
    play(g, "Cargo Ship")
    assert g.state.coins == 4 and len(me(g).durations) == 2
    to_buy_phase(g)
    g.state.coins = 3
    g.apply(0, Buy("Silver"))
    answer(g, "Set it aside")                               # one of the two plays' set-asides
    assert me(g).cargo_aside == ["Silver"]
    end(g)
    assert "Cargo Ship" in me(g).in_play and len(me(g).durations) == 1      # the other entry set nothing aside and is gone
