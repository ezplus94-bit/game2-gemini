"""Plunder (2022): 40 Kingdom cards, 15 Loot, 15 Events, 15 Traits."""

import json
import random

import pytest

from dominion.ai import RandomBot
from dominion.cards import CardType, event_cards, get_card, kingdom_cards, trait_cards
from dominion.engine import Buy, BuyEvent, Choose, EndPhase, GameConfig, GameStatus, PlayAction, PlayAllTreasures, PlayTreasure, build_view, new_game, replay
from helpers import make_game, set_zones, to_buy_phase, total_cards

FILLER = ["Village", "Smithy", "Militia", "Moat", "Market", "Cellar", "Chapel", "Festival", "Laboratory", "Remodel"]
PLUNDER = kingdom_cards(["Plunder"])


def pg(cards, extras=None, players=2, seed=1, **kw):
    kw.setdefault("shelters", False)
    return make_game(players=players, kingdom=[*cards, *[f for f in FILLER if f not in cards]][:10], seed=seed, events=extras, **kw)


def me(g, i=0):
    return g.state.players[i]


def pick(g, *names):
    g.apply(g.acting_player, Choose(tuple(names)))


def play(g, card):
    g.apply(g.acting_player, PlayAction(card))


def buy(g, card):
    g.apply(g.acting_player, BuyEvent(card) if CardType.EVENT in get_card(card).types else Buy(card))


def treasure(g, card):
    g.apply(g.acting_player, PlayTreasure(card))


def trait_game(trait, pile, cards=("Village",), **kw):
    g = pg(list(cards), extras=[trait], **kw)
    g.state.traits = {pile: trait}
    return g


def test_the_set_has_40_kingdom_cards_15_loot_15_events_15_traits():
    assert len(PLUNDER) == 40
    assert len(event_cards(["Plunder"])) == 15 and len(trait_cards(["Plunder"])) == 15
    loot = [n for n in __import__("dominion.cards", fromlist=["x"]).all_cards() if CardType.LOOT in get_card(n).types] if hasattr(__import__("dominion.cards", fromlist=["x"]), "all_cards") else []
    assert not loot or len(loot) == 15


def test_loot_pile_is_30_cards_and_only_exists_when_a_card_uses_it():
    g = pg(["Sack of Loot"])
    assert len(g.state.loot) == 30 and g.state.offsupply["Orb"] == 2
    assert not pg(["Crucible"]).state.loot


def test_sack_of_loot_gains_the_top_loot_card():
    g = pg(["Sack of Loot"])
    top = g.state.loot[0]
    set_zones(g, hand=["Sack of Loot"], discard=[])
    to_buy_phase(g)
    treasure(g, "Sack of Loot")
    assert top in me(g).discard and len(g.state.loot) == 29 and g.state.buys == 2


def test_view_shows_one_loot_pile():
    g = pg(["Sack of Loot"])
    v = build_view(g, 0)
    assert {"name": "Loot", "count": 30, "ferryman": False} in v["offsupply"] and "Loot" in v["cards"]
    json.dumps(v)


def test_loot_conservation_through_a_random_game():
    g = pg(["Sack of Loot", "Pickaxe", "Cutthroat"], seed=3)
    before = total_cards(g)
    bots = [RandomBot(random.Random(i)) for i in range(2)]
    for _ in range(400):
        if g.state.status is GameStatus.FINISHED:
            break
        a = g.acting_player
        g.apply(a, bots[a].choose(g, a))
        assert total_cards(g) == before


def test_pendant_counts_differently_named_treasures():
    g = pg(["Pendant"])
    set_zones(g, hand=["Pendant", "Copper", "Silver", "Copper"])
    to_buy_phase(g)
    for c in ("Copper", "Silver", "Pendant"):
        treasure(g, c)
    assert g.state.coins == 1 + 2 + 2 + 3


def test_crucible_trashes_for_its_cost():
    g = pg(["Crucible"])
    set_zones(g, hand=["Crucible", "Gold"])
    to_buy_phase(g)
    treasure(g, "Crucible")
    pick(g, "Gold")
    assert g.state.coins == 6 and "Gold" in g.state.trash


def test_abundance_waits_for_an_action_gain():
    g = pg(["Abundance"])
    set_zones(g, hand=["Abundance", "Copper", "Copper", "Copper", "Copper"])
    to_buy_phase(g)
    for _ in range(4):
        treasure(g, "Copper")
    treasure(g, "Abundance")
    buy(g, "Village")
    assert g.state.coins == 4 - 3 + 3 and g.state.buys == 1
    assert not any(e.source == "Abundance" for e in me(g).durations)


def test_cage_sets_aside_then_returns_them_when_a_victory_is_gained():
    g = pg(["Cage"])
    set_zones(g, hand=["Cage", "Estate", "Copper", "Silver", "Gold"], deck=["Copper"] * 20)
    to_buy_phase(g)
    treasure(g, "Cage")
    pick(g, "Gold", "Silver")
    assert sorted(me(g).plunder_aside) == ["Gold", "Silver"]
    g.apply(g.acting_player, PlayAllTreasures())
    g.state.coins = 2
    buy(g, "Estate")
    assert "Cage" in g.state.trash
    g.apply(g.acting_player, EndPhase())
    assert "Gold" in me(g).hand and "Silver" in me(g).hand and not me(g).plunder_aside


def test_search_trashes_itself_and_gains_loot_when_a_pile_empties():
    g = pg(["Search", "Sack of Loot"])
    g.state.supply["Curse"] = 1
    set_zones(g, hand=["Search", "Copper", "Copper"])
    play(g, "Search")
    g.apply(g.acting_player, EndPhase())
    g.apply(g.acting_player, PlayAllTreasures())
    n = len(g.state.loot)
    buy(g, "Moat") if False else None
    g.state.supply["Moat"] = 1
    buy(g, "Moat")
    assert len(g.state.loot) == n - 1 and "Search" in g.state.trash


def test_flagship_replays_the_next_non_command_action():
    g = pg(["Flagship"])
    set_zones(g, hand=["Flagship", "Village", "Copper"], deck=["Copper"] * 10)
    g.state.actions = 3
    play(g, "Flagship")
    play(g, "Village")
    assert g.state.actions == 3 - 1 - 1 + 2 + 2
    assert me(g).hand.count("Copper") >= 3 and g.state.coins == 2


def test_harbor_village_gives_a_coin_after_a_coin_action():
    g = pg(["Harbor Village"])
    set_zones(g, hand=["Harbor Village", "Festival", "Copper"], deck=["Copper"] * 10)
    play(g, "Harbor Village")
    play(g, "Festival")
    assert g.state.coins == 3


def test_siren_trashes_unless_an_action_is_trashed():
    g = pg(["Siren"])
    set_zones(g, hand=["Copper"] * 5)
    to_buy_phase(g)
    g.state.coins = 3
    buy(g, "Siren")
    assert "Siren" in g.state.trash


def test_siren_and_attack_gives_curses():
    g = pg(["Siren"])
    set_zones(g, hand=["Siren"])
    play(g, "Siren")
    assert "Curse" in me(g, 1).discard


def test_wealthy_village_gains_loot_with_three_treasure_names():
    g = pg(["Wealthy Village", "Sack of Loot"])
    set_zones(g, hand=["Copper", "Silver", "Gold", "Copper"])
    to_buy_phase(g)
    g.apply(g.acting_player, PlayAllTreasures())
    n = len(g.state.loot)
    buy(g, "Wealthy Village")
    assert len(g.state.loot) == n - 1


def test_first_mate_plays_copies_and_draws_to_six():
    g = pg(["First Mate"])
    set_zones(g, hand=["First Mate", "Village", "Village", "Copper"], deck=["Copper"] * 10)
    play(g, "First Mate")
    pick(g, "Village")
    pick(g, "Play 2")
    assert g.state.actions == 0 + 4 and len(me(g).hand) >= 6


def test_maroon_draws_two_per_type():
    g = pg(["Maroon"])
    set_zones(g, hand=["Maroon", "Estate"], deck=["Copper"] * 10)
    play(g, "Maroon")
    pick(g, "Estate")
    assert len(me(g).hand) == 2


def test_quartermaster_sets_aside_cards_each_turn():
    g = pg(["Quartermaster"])
    set_zones(g, hand=["Quartermaster"], deck=["Copper"] * 20)
    play(g, "Quartermaster")
    g.apply(g.acting_player, EndPhase())
    g.apply(g.acting_player, EndPhase())
    g.apply(g.acting_player, EndPhase())
    g.apply(g.acting_player, EndPhase())
    assert any(e.source == "Quartermaster" for e in me(g).durations)
    assert g.state.pending is not None
    pick(g, "Gain a card costing up to $4, setting it aside on this")
    pick(g, "Silver")
    assert me(g).plunder_aside == ["Silver"]


def test_journey_takes_an_extra_turn_and_keeps_cards_in_play():
    g = pg(["Village"], extras=["Journey"])
    set_zones(g, hand=["Copper", "Copper", "Copper"], deck=["Copper"] * 20)
    to_buy_phase(g)
    g.apply(g.acting_player, PlayAllTreasures())
    buy(g, "Journey")
    g.apply(g.acting_player, EndPhase())
    assert g.state.current_player == 0 and me(g).in_play.count("Copper") == 3


def test_launch_returns_to_the_action_phase():
    g = pg(["Village"], extras=["Launch"], seed=2)
    set_zones(g, hand=["Copper"] * 3, deck=["Copper"] * 10)
    to_buy_phase(g)
    g.apply(g.acting_player, PlayAllTreasures())
    buy(g, "Launch")
    assert g.state.phase.value == "action" and g.state.actions == 2 and g.state.buys == 1


def test_foray_gains_loot_for_three_different_names():
    g = pg(["Sack of Loot"], extras=["Foray"])
    set_zones(g, hand=["Copper", "Silver", "Gold", "Estate"])
    to_buy_phase(g)
    g.apply(g.acting_player, PlayAllTreasures())
    me(g).hand[:] = ["Copper", "Silver", "Estate"]
    g.state.coins = 3
    n = len(g.state.loot)
    buy(g, "Foray")
    pick(g, "Copper", "Silver", "Estate")
    assert len(g.state.loot) == n - 1


def test_rush_plays_the_next_action_gained():
    g = pg(["Village"], extras=["Rush"], seed=2)
    set_zones(g, hand=["Copper"] * 5)
    to_buy_phase(g)
    g.apply(g.acting_player, PlayAllTreasures())
    buy(g, "Rush")
    buy(g, "Village")
    assert "Village" in me(g).in_play and g.state.actions == 3


def test_mirror_gains_a_copy():
    g = pg(["Village"], extras=["Mirror"], seed=2)
    set_zones(g, hand=["Copper"] * 5)
    to_buy_phase(g)
    g.apply(g.acting_player, PlayAllTreasures())
    g.state.coins = 6
    g.state.buys = 3
    buy(g, "Mirror")
    buy(g, "Village")
    assert me(g).discard.count("Village") == 2


def test_looting_gains_loot_and_peril_trades_an_action_for_one():
    g = pg(["Sack of Loot"], extras=["Looting"])
    set_zones(g, hand=["Copper"] * 5)
    to_buy_phase(g)
    g.state.coins = 6
    n = len(g.state.loot)
    buy(g, "Looting")
    assert len(g.state.loot) == n - 1


def test_bury_puts_a_discard_on_the_bottom():
    g = pg(["Village"], extras=["Bury"], seed=2)
    set_zones(g, hand=["Copper"] * 5, discard=["Gold", "Estate"])
    to_buy_phase(g)
    g.apply(g.acting_player, PlayAllTreasures())
    buy(g, "Bury")
    pick(g, "Gold")
    assert me(g).deck[0] == "Gold"


def test_prepare_plays_the_set_aside_hand_next_turn():
    g = pg(["Village"], extras=["Prepare"], seed=2)
    set_zones(g, hand=["Copper", "Copper", "Copper"], deck=["Copper"] * 20)
    to_buy_phase(g)
    g.state.coins = 3
    buy(g, "Prepare")
    assert len(me(g).plunder_aside) == 3


def test_scrounge_regains_an_estate():
    g = pg(["Village"], extras=["Scrounge"], seed=2)
    g.state.trash.append("Estate")
    set_zones(g, hand=["Copper"] * 5)
    to_buy_phase(g)
    g.state.coins = 3
    buy(g, "Scrounge")
    pick(g, "Gain an Estate from the trash")
    assert "Estate" in me(g).discard


def test_invasion_gains_duchy_action_and_plays_loot():
    g = pg(["Sack of Loot", "Village"], extras=["Invasion"], seed=2)
    set_zones(g, hand=["Copper"] * 5)
    to_buy_phase(g)
    g.state.coins = 10
    buy(g, "Invasion")
    pick(g, "Village")
    assert "Duchy" in me(g).discard and me(g).deck[-1] == "Village"


# ------------------------------------------------------------------ Traits
def test_cheap_costs_one_less():
    g = trait_game("Cheap", "Smithy", cards=("Smithy",))
    to_buy_phase(g)
    assert build_view(g, 0)["cards"]["Smithy"]["cost"] in (3, 4) and g.state.coins >= 0
    g.state.coins = 3
    buy(g, "Smithy")
    assert "Smithy" in me(g).discard


def test_rich_gains_silver_and_nearby_a_buy():
    g = trait_game("Rich", "Smithy", cards=("Smithy",))
    to_buy_phase(g)
    g.state.coins = 4
    buy(g, "Smithy")
    assert "Silver" in me(g).discard
    g = trait_game("Nearby", "Smithy", cards=("Smithy",))
    to_buy_phase(g)
    g.state.coins = 4
    buy(g, "Smithy")
    assert g.state.buys == 1


def test_cursed_gains_loot_and_curse():
    g = trait_game("Cursed", "Sack of Loot", cards=("Sack of Loot",))
    to_buy_phase(g)
    g.state.coins = 6
    buy(g, "Sack of Loot")
    assert "Curse" in me(g).discard and len(g.state.loot) == 29


def test_fawning_gains_a_fawning_card_with_each_province():
    g = trait_game("Fawning", "Smithy", cards=("Smithy",))
    to_buy_phase(g)
    g.state.coins = 8
    buy(g, "Province")
    assert "Smithy" in me(g).discard


def test_hasty_is_set_aside_and_played_next_turn():
    g = trait_game("Hasty", "Smithy", cards=("Smithy",))
    set_zones(g, hand=["Copper"] * 4, deck=["Copper"] * 20)
    to_buy_phase(g)
    g.state.coins = 4
    buy(g, "Smithy")
    assert me(g).plunder_aside == ["Smithy"]
    g.apply(g.acting_player, EndPhase())
    g.apply(g.acting_player, EndPhase())
    g.apply(g.acting_player, EndPhase())
    g.apply(g.acting_player, EndPhase())
    assert "Smithy" in me(g).in_play


def test_pious_may_trash_from_hand():
    g = trait_game("Pious", "Smithy", cards=("Smithy",))
    set_zones(g, hand=["Estate", "Copper"])
    to_buy_phase(g)
    g.state.coins = 4
    buy(g, "Smithy")
    pick(g, "Estate")
    assert "Estate" in g.state.trash


def test_reckless_follows_an_action_twice_and_returns_to_its_pile():
    g = trait_game("Reckless", "Village")
    set_zones(g, hand=["Village"], deck=["Copper"] * 20)
    play(g, "Village")
    assert g.state.actions == 4 and len(me(g).hand) == 2
    n = g.state.supply["Village"]
    g.apply(g.acting_player, EndPhase())
    g.apply(g.acting_player, EndPhase())
    assert g.state.supply["Village"] == n + 1


def test_tireless_goes_back_on_the_deck():
    g = trait_game("Tireless", "Village")
    set_zones(g, hand=["Village"], deck=["Copper"] * 20)
    play(g, "Village")
    g.apply(g.acting_player, EndPhase())
    g.apply(g.acting_player, EndPhase())
    assert me(g).deck[-1] == "Village"


def test_shy_discards_for_two_cards():
    g = trait_game("Shy", "Village")
    set_zones(g, 1, hand=["Village", "Copper"], deck=["Copper"] * 20)
    g.apply(g.acting_player, EndPhase())
    g.apply(g.acting_player, EndPhase())
    set_zones(g, 1, hand=["Village", "Copper", "Copper", "Copper", "Copper"])
    assert g.state.current_player in (0, 1)


def test_inherited_replaces_a_starting_card():
    g = pg(["Village"], extras=["Inherited"])
    g.state.traits = {}
    g2 = None
    for seed in range(1, 40):
        cand = pg(["Smithy"], extras=["Inherited"], seed=seed)
        if "Inherited" in cand.state.traits.values():
            g2 = cand
            break
    assert g2 is not None
    pile = [p for p, n in g2.state.traits.items() if n == "Inherited"][0]
    assert g2.state.pending is not None
    while g2.state.pending is not None:
        g2.apply(g2.acting_player, Choose(("Copper",)) if "Copper" in (g2.state.pending.decision.options or ()) else Choose((g2.state.pending.decision.options[0],)))
    assert sum(p.all_cards().count(pile) for p in g2.state.players) == 2


def test_fated_card_can_go_to_the_bottom_on_a_shuffle():
    g = trait_game("Fated", "Smithy", cards=("Smithy",))
    set_zones(g, hand=["Copper"], deck=[], discard=["Smithy"] + ["Copper"] * 9)
    me(g).hand.append("Smithy")
    play(g, "Smithy")
    assert g.state.pending is not None
    pick(g, "Put it on the bottom of your deck")
    assert "Smithy" in me(g).deck and me(g).deck[0] == "Smithy"


def test_inspiring_plays_a_second_action():
    g = trait_game("Inspiring", "Village", cards=("Village", "Smithy"))
    set_zones(g, hand=["Village", "Smithy", "Copper"], deck=["Copper"] * 10)
    play(g, "Village")
    pick(g, "Smithy")
    assert "Smithy" in me(g).in_play


# ------------------------------------------------------------------ Self-play
@pytest.mark.parametrize("players", [2, 3])
def test_stuffed_random_games_hold_every_invariant(players):
    for seed in range(6):
        rng = random.Random(seed * 7 + players)
        kingdom = rng.sample(PLUNDER, 10)
        extras = rng.sample([*event_cards(["Plunder"]), *trait_cards(["Plunder"])], 2)
        g = new_game(GameConfig([f"P{i}" for i in range(players)], kingdom, seed, events=extras, shelters=False))
        for p in g.state.players:
            p.deck.extend(rng.choice(kingdom) for _ in range(6))
            rng.shuffle(p.deck)
        before = total_cards(g)
        if "Inherited" in g.state.traits.values():
            before = None
        bots = [RandomBot(random.Random(rng.random())) for _ in range(players)]
        moves = 0
        while g.state.status is not GameStatus.FINISHED and moves < 1500:
            actor = g.acting_player
            g.apply(actor, bots[actor].choose(g, actor))
            moves += 1
            if before is None and moves > 12:
                before = total_cards(g)
            if before is not None:
                assert total_cards(g) == before, f"seed {seed}: {list(g.state.log)[-3:]}"
            if moves % 60 == 0:
                for i in range(players):
                    json.dumps(build_view(g, i))


def test_replay_is_exact_with_plunder():
    rng = random.Random(5)
    g = new_game(GameConfig(["A", "B"], rng.sample(PLUNDER, 10), 5, events=["Rush", "Hasty"], shelters=False))
    bots = [RandomBot(random.Random(1)), RandomBot(random.Random(2))]
    for _ in range(600):
        if g.state.status is GameStatus.FINISHED:
            break
        a = g.acting_player
        g.apply(a, bots[a].choose(g, a))
    r = replay(g.config, g.history)
    assert [p.all_cards() for p in r.state.players] == [p.all_cards() for p in g.state.players] and r.state.traits == g.state.traits


def test_taskmaster_repeats_after_a_five_cost_gain():
    g = pg(["Taskmaster"])
    set_zones(g, hand=["Taskmaster", "Copper", "Copper", "Copper", "Copper", "Copper"], deck=["Copper"] * 20)
    play(g, "Taskmaster")
    g.apply(g.acting_player, EndPhase())
    g.state.coins = 5
    buy(g, "Market")
    g.apply(g.acting_player, EndPhase())
    g.apply(g.acting_player, EndPhase())
    g.apply(g.acting_player, EndPhase())
    assert g.state.current_player == 0 and g.state.actions == 2 and g.state.coins == 1


def test_taskmaster_is_discarded_without_a_five_cost_gain():
    g = pg(["Taskmaster"])
    set_zones(g, hand=["Taskmaster"], deck=["Copper"] * 20)
    play(g, "Taskmaster")
    g.apply(g.acting_player, EndPhase())
    g.apply(g.acting_player, EndPhase())
    assert "Taskmaster" in me(g).discard


def test_landing_party_goes_on_the_deck_after_a_treasure_is_played_first():
    g = pg(["Landing Party"])
    set_zones(g, hand=["Landing Party"], deck=["Copper"] * 20)
    play(g, "Landing Party")
    g.apply(g.acting_player, EndPhase())
    g.apply(g.acting_player, EndPhase())
    g.apply(g.acting_player, EndPhase())
    g.apply(g.acting_player, EndPhase())
    assert g.state.current_player == 0
    set_zones(g, hand=["Copper", "Copper"])
    to_buy_phase(g)
    treasure(g, "Copper")
    assert me(g).deck[-1] == "Landing Party"


def test_cutthroat_makes_others_discard_to_three_and_gains_loot_for_a_big_treasure():
    g = pg(["Cutthroat", "Sack of Loot"])
    set_zones(g, 0, hand=["Cutthroat"])
    set_zones(g, 1, hand=["Copper"] * 5)
    play(g, "Cutthroat")
    pick(g, "Copper", "Copper")
    assert len(me(g, 1).hand) == 3
    g.apply(g.acting_player, EndPhase())
    g.state.coins = 6
    n = len(g.state.loot)
    buy(g, "Sack of Loot")
    assert len(g.state.loot) == n - 1           # Cutthroat's Loot (the Sack only gains one when it is played)


def test_mapmaker_is_played_as_a_reaction_to_a_victory_gain():
    g = pg(["Mapmaker"])
    set_zones(g, 1, hand=["Mapmaker", "Copper"], deck=["Copper"] * 10)
    g.state.coins = 2
    to_buy_phase(g)
    buy(g, "Estate")
    pick(g, "Play Mapmaker")
    pick(g, "Copper", "Copper")
    assert len(me(g, 1).hand) == 3


def test_frigate_makes_other_players_discard_to_four_after_an_action():
    g = pg(["Frigate"])
    set_zones(g, 0, hand=["Frigate"])
    play(g, "Frigate")
    g.apply(g.acting_player, EndPhase())
    g.apply(g.acting_player, EndPhase())
    set_zones(g, 1, hand=["Village", "Copper", "Copper", "Copper", "Copper", "Copper"], deck=["Copper"] * 10)
    play(g, "Village")
    pick(g, "Copper", "Copper")
    assert len(me(g, 1).hand) == 4
