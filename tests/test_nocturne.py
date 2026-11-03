"""Nocturne (2017): Night phase, Boons, Hexes, States, Heirlooms and every Kingdom card."""

import random

import pytest

from dominion.ai import BigMoneyBot, RandomBot, run_game
from dominion.cards import CardType, get_card, kingdom_cards
from dominion.cards.nocturne import BOON_NAMES, BOONS, HEX_NAMES, HEXES, KEPT_BOONS
from dominion.cards.registry import supporting_cards
from dominion.engine import (
    Buy, Choose, EndPhase, GameConfig, GameStatus, Phase, PlayAction, PlayAllTreasures, PlayTreasure, build_view, new_game,
    replay, IllegalActionError,
)
from dominion.engine.scoring import score_player
from helpers import make_game, set_zones, to_buy_phase

FILLER = ["Village", "Smithy", "Militia", "Moat", "Market", "Cellar", "Chapel", "Festival", "Laboratory", "Remodel"]
HEIRLOOMS = {"Haunted Mirror", "Magic Lamp", "Goat", "Pasture", "Pouch", "Cursed Gold", "Lucky Coin"}


def nc(cards, players=2, seed=1, **kw):
    kw.setdefault("shelters", False)
    kw.setdefault("events", [])
    return make_game(players=players, kingdom=[*cards, *[f for f in FILLER if f not in cards]][:10], seed=seed, **kw)


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


def boons(g, *names):
    g.state.boons = list(names)


def hexes(g, *names):
    g.state.hexes = list(names)


def until_prompt(g):
    """Finish turns (answering anything automatically) until the next start-of-turn question for player 0."""
    for _ in range(6):
        if g.state.pending is not None and g.state.pending.decision.player == 0:
            return
        finish_turn(g)
    raise AssertionError("no prompt")


def to_night(g):
    end(g)
    end(g)
    assert g.state.phase is Phase.NIGHT


# ------------------------------------------------------------------ the set
def test_set_contents():
    names = kingdom_cards(["Nocturne"])
    assert len(names) == 33 and "Cemetery" in names and "Idol" in names
    assert len(BOON_NAMES) == 12 and len(HEX_NAMES) == 12 and len(KEPT_BOONS) == 3
    assert set(supporting_cards("Nocturne")) == HEIRLOOMS | {"Will-o'-Wisp", "Imp", "Ghost", "Bat", "Wish", "Zombie Apprentice", "Zombie Mason", "Zombie Spy"}
    costs = {"Druid": 2, "Faithful Hound": 2, "Guardian": 2, "Monastery": 2, "Pixie": 2, "Tracker": 2, "Changeling": 3, "Fool": 3,
             "Ghost Town": 3, "Leprechaun": 3, "Night Watchman": 3, "Secret Cave": 3, "Bard": 4, "Blessed Village": 4, "Cemetery": 4,
             "Conclave": 4, "Devil's Workshop": 4, "Exorcist": 4, "Necromancer": 4, "Shepherd": 4, "Skulk": 4, "Cobbler": 5, "Crypt": 5,
             "Cursed Village": 5, "Den of Sin": 5, "Idol": 5, "Pooka": 5, "Sacred Grove": 5, "Tormentor": 5, "Tragic Hero": 5,
             "Vampire": 5, "Werewolf": 5, "Raider": 6}
    assert {n: get_card(n).cost for n in names} == costs
    assert all(get_card(n).is_type(CardType.NIGHT) for n in ("Monastery", "Vampire", "Werewolf", "Raider", "Guardian", "Crypt"))
    assert get_card("Werewolf").is_type(CardType.ACTION) and not get_card("Vampire").is_type(CardType.ACTION)


# ------------------------------------------------------------------ setup
def test_heirlooms_replace_coppers_and_return_them_to_the_pile():
    g = nc(["Pixie", "Tracker"])
    for p in g.state.players:
        assert sorted(p.all_cards()).count("Copper") == 5 and "Goat" in p.all_cards() and "Pouch" in p.all_cards()
    assert g.state.supply["Copper"] == 60 - 5 * 2
    plain = nc(["Bard"])
    assert plain.state.supply["Copper"] == 60 - 7 * 2 and sorted(me(plain).all_cards()).count("Copper") == 7


def test_each_heirloom_goes_with_its_card():
    pairs = {"Cemetery": "Haunted Mirror", "Fool": "Lucky Coin", "Pixie": "Goat", "Pooka": "Cursed Gold", "Secret Cave": "Magic Lamp",
             "Shepherd": "Pasture", "Tracker": "Pouch"}
    for card, heirloom in pairs.items():
        g = nc([card])
        assert heirloom in me(g).all_cards(), card


def test_boons_hexes_druid_and_zombies_setup():
    g = nc(["Bard", "Skulk"])
    assert sorted(g.state.boons) == sorted(BOON_NAMES) and sorted(g.state.hexes) == sorted(HEX_NAMES)
    d = nc(["Druid", "Necromancer"])
    assert len(d.state.druid_boons) == 3 and len(d.state.boons) == 9 and not set(d.state.druid_boons) & set(d.state.boons)
    assert sorted(d.state.trash) == ["Zombie Apprentice", "Zombie Mason", "Zombie Spy"]
    assert not nc(["Conclave"]).state.boons and not nc(["Conclave"]).state.hexes


def test_extra_piles():
    g = nc(["Bard", "Devil's Workshop", "Cemetery", "Leprechaun", "Vampire"])
    assert g.state.offsupply == {"Will-o'-Wisp": 12, "Imp": 13, "Ghost": 6, "Wish": 12, "Bat": 10}
    e = nc(["Exorcist"])
    assert set(e.state.offsupply) == {"Will-o'-Wisp", "Imp", "Ghost"}
    assert nc(["Secret Cave"]).state.offsupply == {"Wish": 12}
    assert nc(["Conclave"]).state.offsupply == {}


def test_cemetery_pile_is_a_victory_pile():
    assert nc(["Cemetery"]).state.supply["Cemetery"] == 8
    assert nc(["Cemetery"], players=3).state.supply["Cemetery"] == 12


# ------------------------------------------------------------------ Night phase
def test_night_phase_only_with_a_night_card_in_hand():
    g = nc(["Monastery"])
    set_zones(g, hand=["Copper"] * 5)
    end(g); end(g)
    assert g.state.phase is Phase.ACTION and g.state.current_player == 1
    g = nc(["Monastery"])
    set_zones(g, hand=["Monastery", "Copper", "Copper", "Copper", "Copper"])
    end(g); end(g)
    assert g.state.phase is Phase.NIGHT and g.state.current_player == 0
    assert "Night phase" in log(g)


def test_night_cards_cannot_be_played_in_action_or_buy_phase_and_cost_no_action():
    g = nc(["Monastery", "Werewolf"])
    set_zones(g, hand=["Monastery", "Werewolf", "Copper", "Copper", "Copper"], deck=["Copper"] * 10)
    assert PlayAction("Monastery") not in g.legal_actions() and PlayAction("Werewolf") in g.legal_actions()
    with pytest.raises(IllegalActionError):
        play(g, "Monastery")
    end(g)
    assert PlayAction("Werewolf") not in g.legal_actions()
    end(g)
    assert g.state.phase is Phase.NIGHT
    actions = g.state.actions
    assert {a for a in g.legal_actions() if isinstance(a, PlayAction)} == {PlayAction("Monastery"), PlayAction("Werewolf")}
    assert not any(isinstance(a, (Buy, PlayTreasure, PlayAllTreasures)) for a in g.legal_actions())
    play(g, "Monastery")
    assert g.state.actions == actions
    end(g)
    assert g.state.current_player == 1 and "Monastery" in me(g).discard


def test_non_night_card_cannot_be_played_at_night():
    g = nc(["Monastery"])
    set_zones(g, hand=["Monastery", "Village", "Copper", "Copper", "Copper"])
    to_night(g)
    with pytest.raises(IllegalActionError):
        play(g, "Village")


def test_werewolf_in_action_phase_draws_three():
    g = nc(["Werewolf"])
    set_zones(g, hand=["Werewolf"] + ["Copper"] * 4, deck=["Silver"] * 6)
    play(g, "Werewolf")
    assert len(me(g).hand) == 7


def test_werewolf_at_night_gives_hex_to_others():
    g = nc(["Werewolf"])
    set_zones(g, hand=["Werewolf", "Copper", "Copper", "Copper", "Copper"])
    hexes(g, "Plague")
    to_night(g)
    play(g, "Werewolf")
    assert me(g, 1).hand.count("Curse") == 1 and me(g).hand.count("Curse") == 0


def test_moat_blocks_night_attack():
    g = nc(["Werewolf"])
    set_zones(g, hand=["Werewolf", "Copper", "Copper", "Copper", "Copper"])
    set_zones(g, 1, hand=["Moat"] + ["Copper"] * 4)
    hexes(g, "Plague")
    to_night(g)
    play(g, "Werewolf")
    answer(g, "Moat")
    assert "Curse" not in me(g, 1).hand and g.state.hexes == ["Plague"]


# ------------------------------------------------------------------ Boons
def bard_with(boon, hand=None, deck=None, **kw):
    g = nc(["Bard", *kw.pop("extra", [])], **kw)
    set_zones(g, hand=["Bard"] + (hand or ["Copper"] * 4), deck=deck or ["Copper"] * 10)
    boons(g, boon)
    return g


def test_bard_gives_two_coins_and_a_boon():
    g = bard_with("The Mountain's Gift")
    play(g, "Bard")
    assert g.state.coins == 2 and "Silver" in me(g).discard and g.state.boons_discard == ["The Mountain's Gift"]


def test_earth_gift():
    g = bard_with("The Earth's Gift", hand=["Silver", "Copper", "Estate", "Estate"])
    play(g, "Bard")
    answer(g, "Silver")
    answer(g, "Silver")
    assert "Silver" in me(g).discard and me(g).discard.count("Silver") == 2


def test_field_and_forest_gifts_are_kept_until_cleanup():
    g = bard_with("The Field's Gift")
    play(g, "Bard")
    assert g.state.actions == 1 and g.state.coins == 3 and g.state.kept_boons == ["The Field's Gift"] and not g.state.boons_discard
    end(g); end(g)
    assert g.state.boons_discard == ["The Field's Gift"] and not g.state.kept_boons
    g = bard_with("The Forest's Gift")
    play(g, "Bard")
    assert g.state.buys == 2 and g.state.coins == 3


def test_flame_gift_trash():
    g = bard_with("The Flame's Gift", hand=["Curse", "Copper"])
    play(g, "Bard")
    answer(g, "Curse")
    assert g.state.trash == ["Curse"]


def test_moon_gift_puts_discard_on_deck():
    g = bard_with("The Moon's Gift")
    set_zones(g, discard=["Gold", "Curse"])
    play(g, "Bard")
    answer(g, "Gold")
    assert me(g).deck[-1] == "Gold"


def test_river_gift_draws_at_end_of_turn():
    g = bard_with("The River's Gift")
    play(g, "Bard")
    assert "The River's Gift" in g.state.kept_boons
    end(g); end(g)
    assert len(me(g).hand) == 6 and g.state.boons_discard == ["The River's Gift"]


def test_sea_gift_draws():
    g = bard_with("The Sea's Gift")
    play(g, "Bard")
    assert len(me(g).hand) == 5


def test_sky_gift_discards_three_for_gold():
    g = bard_with("The Sky's Gift", hand=["Copper", "Copper", "Estate", "Estate"])
    play(g, "Bard")
    answer(g, "Discard 3 cards")
    answer(g, "Copper", "Copper", "Estate")
    assert "Gold" in me(g).discard and len(me(g).hand) == 1


def test_sky_gift_with_fewer_cards_gives_no_gold():
    g = bard_with("The Sky's Gift", hand=["Copper", "Estate"])
    play(g, "Bard")
    answer(g, "Discard your 2 card(s)")
    answer(g, "Copper", "Estate")
    assert "Gold" not in me(g).discard and not me(g).hand


def test_sun_gift_looks_at_four():
    g = bard_with("The Sun's Gift", deck=["Gold", "Copper", "Estate", "Curse", "Silver"])
    play(g, "Bard")
    answer(g, "Curse", "Estate")
    answer(g, "Copper")                                     # the rest go back in an order of your choice: Copper first (on top)
    assert sorted(me(g).discard) == ["Curse", "Estate"] and me(g).deck == ["Gold", "Silver", "Copper"]


def test_swamp_gift_gains_will_o_wisp():
    g = bard_with("The Swamp's Gift")
    play(g, "Bard")
    assert "Will-o'-Wisp" in me(g).discard and g.state.offsupply["Will-o'-Wisp"] == 11


def test_wind_gift_draws_two_discards_two():
    g = bard_with("The Wind's Gift", hand=["Copper", "Copper"], deck=["Gold", "Gold", "Silver"])
    play(g, "Bard")
    answer(g, "Copper", "Copper")
    assert sorted(me(g).hand) == ["Gold", "Silver"]


def test_boon_deck_reshuffles_from_discard():
    g = bard_with("The Sea's Gift")
    g.state.boons_discard = ["The Mountain's Gift"]
    g.state.boons = []
    play(g, "Bard")
    assert "Silver" in me(g).discard and g.state.boons_discard == ["The Mountain's Gift"] and g.state.boons == []
    assert "shuffled" in log(g)


# ------------------------------------------------------------------ Hexes
def hex_test(hex_name, hand=None, deck=None, discard=None):
    g = nc(["Skulk"])
    set_zones(g, hand=["Skulk", "Copper", "Copper", "Copper", "Copper"])
    set_zones(g, 1, hand=hand or ["Copper"] * 5, deck=deck or ["Copper"] * 10, discard=discard or [])
    hexes(g, hex_name)
    play(g, "Skulk")
    return g


def test_skulk_buy_and_gold_on_gain():
    g = hex_test("Greed")
    assert g.state.buys == 2 and me(g, 1).deck[-1] == "Copper" and g.state.hexes_discard == ["Greed"]
    g2 = nc(["Skulk"])
    set_zones(g2, hand=["Copper"] * 5)
    to_buy_phase(g2)
    g2.state.coins = 4
    g2.apply(0, Buy("Skulk"))
    assert "Gold" in me(g2).discard and "Skulk" in me(g2).discard


def test_bad_omens():
    g = hex_test("Bad Omens", deck=["Gold", "Copper", "Silver", "Copper", "Estate"], discard=["Copper"])
    p = me(g, 1)
    assert p.deck == ["Copper", "Copper"] and sorted(p.discard) == ["Copper", "Estate", "Gold", "Silver"]


def test_delusion_blocks_action_buys_next_turn():
    g = hex_test("Delusion")
    assert me(g, 1).deluded
    finish_turn(g)
    set_zones(g, 1, hand=["Copper"] * 5)
    to_buy_phase(g)
    assert not me(g, 1).deluded and g.state.deluded_turn
    g.state.coins = 8
    assert Buy("Village") not in g.legal_actions() and Buy("Silver") in g.legal_actions()
    with pytest.raises(IllegalActionError):
        g.apply(1, Buy("Village"))
    end(g)
    assert not g.state.deluded_turn


def test_envy_makes_silver_and_gold_worth_one():
    g = hex_test("Envy")
    finish_turn(g)
    set_zones(g, 1, hand=["Silver", "Gold", "Copper", "Copper", "Copper"])
    to_buy_phase(g)
    g.apply(1, PlayAllTreasures())
    assert g.state.coins == 1 + 1 + 3


def test_delusion_when_already_envious_does_nothing():
    g = nc(["Skulk"])
    set_zones(g, hand=["Skulk", "Copper", "Copper", "Copper", "Copper"])
    me(g, 1).envious = True
    hexes(g, "Delusion")
    play(g, "Skulk")
    assert me(g, 1).envious and not me(g, 1).deluded and g.state.hexes_discard == ["Delusion"]


def test_famine():
    g = hex_test("Famine", deck=["Gold", "Village", "Estate", "Market", "Copper"])
    p = me(g, 1)
    assert p.discard == ["Market"] and sorted(p.deck) == ["Copper", "Estate", "Gold", "Village"]


def test_fear_discards_action_or_treasure():
    g = hex_test("Fear", hand=["Estate", "Estate", "Estate", "Copper", "Estate"])
    answer(g, "Copper")
    assert me(g, 1).discard == ["Copper"]
    g = hex_test("Fear", hand=["Estate"] * 5)
    assert not g.state.pending and not me(g, 1).discard
    g = hex_test("Fear", hand=["Copper"] * 4)
    assert not g.state.pending


def test_haunting():
    g = hex_test("Haunting", hand=["Estate", "Copper", "Copper", "Silver"])
    answer(g, "Silver")
    assert me(g, 1).deck[-1] == "Silver" and len(me(g, 1).hand) == 3
    g = hex_test("Haunting", hand=["Estate", "Copper", "Copper"])
    assert not g.state.pending


def test_locusts_copper_gives_curse_and_other_cards_give_cheaper():
    g = hex_test("Locusts", deck=["Gold", "Copper"])
    assert g.state.trash == ["Copper"] and "Curse" in me(g, 1).discard
    g = hex_test("Locusts", deck=["Estate", "Estate", "Smithy"])
    answer(g, "Village")
    assert g.state.trash == ["Smithy"] and "Village" in me(g, 1).discard


def test_locusts_with_no_cheaper_sharing_card():
    g = hex_test("Locusts", deck=["Curse", "Curse", "Curse"])
    assert g.state.trash == ["Curse"] and not g.state.pending and not me(g, 1).discard


def test_misery_twice_and_score():
    g = hex_test("Misery")
    assert me(g, 1).miserable == 1
    assert score_player(me(g, 1), g.state) == -2
    me(g, 1).miserable = 2
    assert score_player(me(g, 1), g.state) == -4


def test_plague_poverty():
    g = hex_test("Plague")
    assert me(g, 1).hand.count("Curse") == 1
    g = hex_test("Poverty")
    answer(g, "Copper", "Copper")
    assert len(me(g, 1).hand) == 3


def test_war():
    g = hex_test("War", deck=["Gold", "Silver", "Smithy", "Estate", "Copper"])
    assert g.state.trash == ["Smithy"] and sorted(me(g, 1).discard) == ["Copper", "Estate"] and me(g, 1).deck == ["Gold", "Silver"]
    g = hex_test("War", deck=["Gold", "Copper", "Estate"])
    assert g.state.trash == [] and sorted(me(g, 1).discard) == ["Copper", "Estate", "Gold"]


def test_hex_deck_reshuffles():
    g = hex_test("Greed")
    assert g.state.hexes_discard == ["Greed"] and len(g.state.hexes) == 0
    g.state.hexes = []
    hexes_before = g.state.hexes_discard
    set_zones(g, 0, hand=["Skulk"] + ["Copper"] * 4)
    finish_turn(g)
    finish_turn(g)
    assert g.state.status is GameStatus.ACTIVE


# ------------------------------------------------------------------ Kingdom cards
def test_blessed_village_now_or_later():
    g = nc(["Blessed Village"])
    set_zones(g, hand=["Copper"] * 5)
    to_buy_phase(g)
    g.state.coins = 4
    boons(g, "The Mountain's Gift")
    g.apply(0, Buy("Blessed Village"))
    answer(g, "Receive it now")
    assert "Silver" in me(g).discard and not me(g).held_boons
    g = nc(["Blessed Village"])
    set_zones(g, hand=["Copper"] * 5)
    to_buy_phase(g)
    g.state.coins = 4
    boons(g, "The Mountain's Gift")
    g.apply(0, Buy("Blessed Village"))
    answer(g, "Receive it at the start of your next turn")
    assert me(g).held_boons == ["The Mountain's Gift"] and "Silver" not in me(g).discard
    view = build_view(g, 1)
    assert view["players"][0]["held_boons"] == ["The Mountain's Gift"]
    finish_turn(g)
    finish_turn(g)
    assert "Silver" in me(g).discard and not me(g).held_boons


def test_blessed_village_plays():
    g = nc(["Blessed Village"])
    set_zones(g, hand=["Blessed Village", "Copper"], deck=["Gold"] * 3)
    play(g, "Blessed Village")
    assert g.state.actions == 2 and len(me(g).hand) == 2


def test_cemetery_trashes_up_to_four_on_gain_and_scores():
    g = nc(["Cemetery"])
    set_zones(g, hand=["Estate", "Estate", "Copper", "Copper", "Curse"])
    to_buy_phase(g)
    g.state.coins = 4
    before = score_player(me(g), g.state)
    g.apply(0, Buy("Cemetery"))
    answer(g, "Estate", "Curse", "Copper")
    assert sorted(g.state.trash) == ["Copper", "Curse", "Estate"]
    assert score_player(me(g), g.state) == before + 2          # +2 for Cemetery, -1 for the Estate, +1 for the Curse


def test_haunted_mirror_gains_ghost():
    g = nc(["Cemetery"])
    assert "Haunted Mirror" in me(g).all_cards()
    set_zones(g, hand=["Haunted Mirror", "Village", "Estate"])
    g.state.offsupply["Ghost"] = 6
    play_c = g
    # trash it with Chapel-like effect: use the Flame's Gift via direct trash
    from dominion.engine.zones import trash_from_hand
    trash_from_hand(g.state, 0, "Haunted Mirror")
    g.state.gain_events.clear()
    g._settle()
    assert g.state.pending is not None
    answer(g, "Village")
    assert "Ghost" in me(g).discard and g.state.offsupply["Ghost"] == 5 and "Village" in me(g).discard


def test_changeling_trash_and_gain_copy():
    g = nc(["Changeling"])
    set_zones(g, hand=["Changeling", "Silver", "Copper", "Copper", "Copper"])
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    end(g)
    play(g, "Changeling")
    assert "Changeling" in g.state.trash
    answer(g, "Silver")
    assert "Silver" in me(g).discard


def test_changeling_exchange_on_gain():
    g = nc(["Changeling", "Skulk"])
    set_zones(g, hand=["Copper"] * 5)
    to_buy_phase(g)
    g.state.coins = 4
    g.apply(0, Buy("Skulk"))
    assert g.state.pending is not None
    answer(g, "Exchange it for a Changeling")
    assert "Changeling" in me(g).discard and "Skulk" not in me(g).discard and g.state.supply["Skulk"] == 10
    assert g.state.supply["Changeling"] == 9 and "Gold" in me(g).discard           # Skulk's on-gain still happened


def test_changeling_not_offered_for_cheap_cards():
    g = nc(["Changeling"])
    set_zones(g, hand=["Copper"] * 5)
    to_buy_phase(g)
    g.state.coins = 2
    g.apply(0, Buy("Cellar") if "Cellar" in g.state.supply else Buy("Silver"))
    assert g.state.pending is None


def test_cobbler_gains_to_hand_next_turn():
    g = nc(["Cobbler"])
    set_zones(g, hand=["Cobbler", "Copper", "Copper", "Copper", "Copper"])
    to_night(g)
    play(g, "Cobbler")
    end(g)
    assert "Cobbler" in me(g).in_play
    finish_turn(g)                                           # player 1's turn; then player 0's start of turn asks
    assert g.state.pending is not None and g.state.pending.decision.player == 0
    answer(g, "Silver")
    assert "Silver" in me(g).hand


def test_conclave():
    g = nc(["Conclave"])
    set_zones(g, hand=["Conclave", "Village", "Smithy", "Conclave"], deck=["Copper"] * 8)
    play(g, "Conclave")
    assert g.state.coins == 2
    assert set(g.state.pending.decision.options) == {"Village", "Smithy"}
    answer(g, "Village")
    assert g.state.actions == 3                                  # 1 -1 (Conclave) +2 (Village) +1 (Conclave)
    g = nc(["Conclave"])
    set_zones(g, hand=["Conclave", "Conclave"], deck=["Copper"] * 8)
    play(g, "Conclave")
    assert g.state.pending is None and g.state.actions == 0


def test_crypt_sets_aside_treasures_over_turns():
    g = nc(["Crypt"])
    set_zones(g, hand=["Crypt", "Copper", "Copper", "Silver", "Estate"])
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    end(g)
    play(g, "Crypt")
    answer(g, "Copper", "Copper", "Silver")
    assert sorted(me(g).crypt) == ["Copper", "Copper", "Silver"] and not any(c in me(g).in_play for c in ("Copper", "Silver"))
    assert score_player(me(g), g.state) == me(g).all_cards().count("Estate")      # the set-aside Treasures are still yours
    until_prompt(g)
    answer(g, "Silver")
    assert "Silver" in me(g).hand and "Crypt" in me(g).in_play
    until_prompt(g)
    answer(g, "Copper")
    assert len(me(g).crypt) == 1 and "Crypt" in me(g).in_play
    until_prompt(g)
    answer(g, "Copper")
    assert not me(g).crypt
    finish_turn(g)
    finish_turn(g)
    assert "Crypt" not in me(g).in_play


def test_cursed_village():
    g = nc(["Cursed Village"])
    set_zones(g, hand=["Cursed Village", "Copper"], deck=["Gold"] * 8)
    play(g, "Cursed Village")
    assert g.state.actions == 2 and len(me(g).hand) == 6
    g = nc(["Cursed Village", "Skulk"])
    set_zones(g, hand=["Copper"] * 5)
    to_buy_phase(g)
    g.state.coins = 5
    hexes(g, "Plague")
    g.apply(0, Buy("Cursed Village"))
    assert me(g).hand.count("Curse") == 1 and g.state.hexes_discard == ["Plague"]


def test_den_of_sin_gained_to_hand_and_draws_next_turn():
    g = nc(["Den of Sin"])
    set_zones(g, hand=["Copper"] * 5)
    to_buy_phase(g)
    g.state.coins = 5
    g.apply(0, Buy("Den of Sin"))
    assert "Den of Sin" in me(g).hand and "Den of Sin" not in me(g).discard
    end(g)
    assert g.state.phase is Phase.NIGHT
    play(g, "Den of Sin")
    end(g)
    set_zones(g, 0, deck=["Gold"] * 10)
    finish_turn(g)                                           # player 1's turn; player 0 then starts with +2 Cards
    assert len(me(g).hand) == 7 and me(g).hand.count("Gold") == 2


def test_devils_workshop_three_ways():
    for n, expect in ((0, "Gold"), (1, "Silver"), (2, "Imp")):
        g = nc(["Devil's Workshop"])
        set_zones(g, hand=["Devil's Workshop", "Copper", "Copper", "Copper", "Copper"])
        to_buy_phase(g)
        g.state.coins = 6
        for _ in range(n):
            g.state.buys = 1
            g.apply(0, Buy("Silver"))
        g.state.buys = 0
        end(g)
        play(g, "Devil's Workshop")
        if n == 1:
            answer(g, "Silver")
        assert expect in me(g).discard, (n, me(g).discard)


def test_druid_receives_set_aside_boon_without_using_it_up():
    g = nc(["Druid"])
    set_zones(g, hand=["Druid", "Village", "Copper", "Copper", "Copper"])
    first = g.state.druid_boons[0]
    play(g, "Druid")
    assert g.state.buys == 2
    answer(g, first)
    assert g.state.druid_boons[0] == first and first not in g.state.kept_boons and first not in g.state.boons_discard


def test_exorcist():
    g = nc(["Exorcist"])
    set_zones(g, hand=["Exorcist", "Silver", "Copper", "Copper", "Copper"])
    to_night(g)
    play(g, "Exorcist")
    answer(g, "Silver")
    assert set(g.state.pending.decision.options) == {"Will-o'-Wisp", "Imp"}
    answer(g, "Imp")
    assert "Imp" in me(g).discard and "Silver" in g.state.trash
    g = nc(["Exorcist"])
    set_zones(g, hand=["Exorcist", "Copper", "Copper", "Copper", "Copper"])
    to_night(g)
    play(g, "Exorcist")
    answer(g, "Copper")
    assert g.state.pending is None and g.state.trash == ["Copper"]                # nothing costs less than a Copper


def test_faithful_hound_set_aside_when_discarded_by_others():
    g = nc(["Faithful Hound", "Raider"])
    set_zones(g, hand=["Raider", "Copper", "Copper", "Copper", "Copper"])
    set_zones(g, 1, hand=["Faithful Hound", "Copper", "Estate", "Estate", "Estate"])
    g = nc(["Faithful Hound", "Militia"])
    set_zones(g, hand=["Militia", "Copper", "Copper", "Copper", "Copper"])
    set_zones(g, 1, hand=["Faithful Hound", "Copper", "Estate", "Estate", "Estate"])
    play(g, "Militia")
    answer(g, "Faithful Hound", "Copper")
    assert me(g, 1).hounds == ["Faithful Hound"] and "Faithful Hound" not in me(g, 1).discard
    end(g); end(g)
    assert "Faithful Hound" in me(g, 1).hand and not me(g, 1).hounds


def test_faithful_hound_not_set_aside_in_cleanup_and_draws():
    g = nc(["Faithful Hound"])
    set_zones(g, hand=["Faithful Hound", "Copper"], deck=["Gold"] * 5)
    play(g, "Faithful Hound")
    assert len(me(g).hand) == 3
    end(g); end(g)
    assert not me(g).hounds and "Faithful Hound" not in me(g).in_play


def test_fool_takes_lost_in_the_woods_and_receives_three_boons():
    g = nc(["Fool"])
    assert "Lucky Coin" in me(g).all_cards()
    set_zones(g, hand=["Fool", "Copper", "Copper", "Copper", "Copper"])
    boons(g, "The Mountain's Gift", "The Sea's Gift", "The Field's Gift", "The Sky's Gift")
    play(g, "Fool")
    assert g.state.lost_in_woods == 0
    answer(g, "The Sea's Gift")
    answer(g, "The Field's Gift")
    assert "Silver" in me(g).discard and g.state.actions == 1
    assert g.state.boons == ["The Sky's Gift"]
    assert sorted(g.state.boons_discard + g.state.kept_boons) == sorted(["The Mountain's Gift", "The Sea's Gift", "The Field's Gift"])
    g2 = g
    set_zones(g2, hand=["Fool"])
    # a Fool played while holding Lost in the Woods does nothing
    me(g2).hand.append("Fool")
    g2.state.actions = 1
    play(g2, "Fool")
    assert g2.state.pending is None


def test_lost_in_the_woods_discard_for_boon_each_turn_and_stolen_by_another_fool():
    g = nc(["Fool"])
    g.state.lost_in_woods = 1
    boons(g, "The Mountain's Gift")
    finish_turn(g)
    assert g.state.pending is not None and g.state.pending.decision.player == 1
    answer(g, "Copper")
    assert "Silver" in me(g, 1).discard and "Copper" in me(g, 1).discard
    set_zones(g, 0, hand=["Fool"] + ["Copper"] * 4)
    finish_turn(g)
    g.state.pending is None or answer(g)
    p0 = g.state.current_player
    set_zones(g, p0, hand=["Fool", "Copper", "Copper", "Copper", "Copper"])
    boons(g, "The Sea's Gift", "The Sea's Gift", "The Sea's Gift")
    play(g, "Fool")
    assert g.state.lost_in_woods == p0


def test_ghost_town_and_guardian():
    g = nc(["Ghost Town", "Guardian", "Militia"])
    set_zones(g, hand=["Ghost Town", "Guardian", "Copper", "Copper", "Copper"])
    to_night(g)
    play(g, "Ghost Town")
    play(g, "Guardian")
    end(g)
    set_zones(g, 1, hand=["Militia", "Copper", "Copper", "Copper", "Copper"])
    play(g, "Militia")
    assert g.state.coins == 2 and len(me(g).hand) == 5 and g.state.pending is None          # Militia does nothing to the Guardian's owner
    finish_turn(g)
    set_zones(g, 0, deck=["Gold"] * 10)
    finish_turn(g)
    assert me(g).hand.count("Gold") >= 1


def test_idol_boon_then_curse():
    g = nc(["Idol", "Bard"])
    set_zones(g, hand=["Idol", "Idol", "Copper", "Copper", "Copper"])
    boons(g, "The Mountain's Gift")
    to_buy_phase(g)
    g.apply(0, PlayTreasure("Idol"))
    assert "Silver" in me(g).discard and g.state.coins == 2
    g.apply(0, PlayTreasure("Idol"))
    assert me(g, 1).discard.count("Curse") == 1 and g.state.coins == 4


def test_leprechaun_seven_cards_wish_else_hex():
    g = nc(["Leprechaun"])
    set_zones(g, hand=["Leprechaun"], in_play=["Copper"] * 6)
    play(g, "Leprechaun")
    assert "Wish" in me(g).discard and "Gold" in me(g).discard and g.state.hexes_discard == []
    g = nc(["Leprechaun", "Skulk"])
    set_zones(g, hand=["Leprechaun"], in_play=["Copper"] * 2)
    hexes(g, "Greed")
    play(g, "Leprechaun")
    assert "Wish" not in me(g).discard and me(g).deck[-1] == "Copper" and g.state.hexes_discard == ["Greed"]


def test_monastery_trashes_per_card_gained():
    g = nc(["Monastery"])
    set_zones(g, hand=["Monastery", "Copper", "Estate", "Estate", "Curse"])
    to_buy_phase(g)
    g.state.coins = 6
    g.state.buys = 2
    g.apply(0, Buy("Silver"))
    g.apply(0, Buy("Silver"))
    end(g)
    play(g, "Monastery")
    answer(g, "Curse")
    answer(g, "Estate")
    assert sorted(g.state.trash) == ["Curse", "Estate"] and g.state.pending is None


def test_monastery_can_trash_copper_in_play():
    g = nc(["Monastery"])
    set_zones(g, hand=["Monastery", "Copper"])
    to_buy_phase(g)
    g.apply(0, PlayTreasure("Copper"))
    g.state.coins = 3
    g.apply(0, Buy("Silver"))
    end(g)
    play(g, "Monastery")
    answer(g, "Copper (in play)")
    assert g.state.trash == ["Copper"] and "Copper" not in me(g).in_play


def test_necromancer_plays_zombies_from_trash_once_each():
    g = nc(["Necromancer"])
    set_zones(g, hand=["Necromancer", "Necromancer", "Smithy"], deck=["Gold"] * 8)
    g.state.actions = 2
    play(g, "Necromancer")
    assert set(g.state.pending.decision.options) == {"Zombie Apprentice", "Zombie Mason", "Zombie Spy"}
    answer(g, "Zombie Spy")
    assert len(me(g).hand) == 3 and g.state.actions == 2        # Necromancer used one Action, Zombie Spy gave one back
    answer(g, "Put it back")
    assert sorted(g.state.trash) == ["Zombie Apprentice", "Zombie Mason", "Zombie Spy"]
    play(g, "Necromancer")
    assert set(g.state.pending.decision.options) == {"Zombie Apprentice", "Zombie Mason"}
    answer(g, "Zombie Apprentice")
    answer(g, "Smithy")
    assert len(me(g).hand) == 4 and g.state.actions == 2 and g.state.trash.count("Smithy") == 1


def test_zombie_mason():
    g = nc(["Necromancer"])
    set_zones(g, hand=["Necromancer"], deck=["Gold", "Estate"])
    play(g, "Necromancer")
    answer(g, "Zombie Mason")
    assert g.state.trash.count("Estate") == 1
    assert "Silver" in g.state.pending.decision.options and "Smithy" not in g.state.pending.decision.options
    answer(g, "Silver")
    assert "Silver" in me(g).discard


def test_night_watchman_gained_to_hand_and_looks_at_five():
    g = nc(["Night Watchman"])
    set_zones(g, hand=["Copper"] * 5)
    to_buy_phase(g)
    g.state.coins = 3
    g.apply(0, Buy("Night Watchman"))
    assert "Night Watchman" in me(g).hand
    set_zones(g, deck=["Gold", "Curse", "Curse", "Estate", "Silver"])
    end(g)
    play(g, "Night Watchman")
    answer(g, "Curse", "Curse", "Estate")
    answer(g, "Gold")
    assert me(g).deck == ["Silver", "Gold"] and sorted(me(g).discard) == ["Curse", "Curse", "Estate"]


def test_pixie_receives_boon_twice():
    g = nc(["Pixie"])
    assert "Goat" in me(g).all_cards()
    set_zones(g, hand=["Pixie", "Copper", "Copper", "Copper", "Copper"], deck=["Copper"] * 5)
    boons(g, "The Mountain's Gift")
    play(g, "Pixie")
    answer(g, "Trash Pixie to receive it twice")
    assert me(g).discard.count("Silver") == 2 and "Pixie" in g.state.trash
    g = nc(["Pixie"])
    set_zones(g, hand=["Pixie", "Copper", "Copper", "Copper", "Copper"], deck=["Copper"] * 5)
    boons(g, "The Field's Gift")
    play(g, "Pixie")
    answer(g)
    assert g.state.coins == 0 and g.state.boons_discard == ["The Field's Gift"]
    g = nc(["Pixie"])
    set_zones(g, hand=["Pixie", "Copper", "Copper", "Copper", "Copper"], deck=["Copper"] * 5)
    boons(g, "The Field's Gift")
    play(g, "Pixie")
    answer(g, "Trash Pixie to receive it twice")
    assert g.state.coins == 2 and g.state.kept_boons == ["The Field's Gift"]


def test_goat_trashes_a_card():
    g = nc(["Pixie"])
    set_zones(g, hand=["Goat", "Curse", "Copper"])
    to_buy_phase(g)
    g.apply(0, PlayTreasure("Goat"))
    answer(g, "Curse")
    assert g.state.trash == ["Curse"] and g.state.coins == 1


def test_pooka_and_cursed_gold():
    g = nc(["Pooka"])
    assert "Cursed Gold" in me(g).all_cards()
    set_zones(g, hand=["Pooka", "Cursed Gold", "Silver", "Copper", "Estate"], deck=["Gold"] * 6)
    play(g, "Pooka")
    assert "Cursed Gold" not in g.state.pending.decision.options
    answer(g, "Silver")
    assert len(me(g).hand) == 7 and g.state.trash == ["Silver"]
    set_zones(g, hand=["Cursed Gold"])
    g.state.actions = 0
    end(g)
    g.apply(0, PlayTreasure("Cursed Gold"))
    assert g.state.coins == 3 and "Curse" in me(g).discard


def test_raider_discards_copy_and_pays_next_turn():
    g = nc(["Raider"])
    set_zones(g, hand=["Raider", "Copper", "Silver", "Copper", "Copper"], deck=["Copper"] * 10)
    set_zones(g, 1, hand=["Copper", "Gold", "Estate", "Estate", "Estate"])
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    end(g)
    play(g, "Raider")
    assert g.state.pending.decision.player == 1 and set(g.state.pending.decision.options) == {"Copper"}
    answer(g, "Copper")
    set_zones(g, 1, hand=["Gold", "Estate", "Estate", "Estate"])
    finish_turn(g)
    finish_turn(g)
    assert g.state.coins == 3


def test_raider_reveals_when_no_copy_or_small_hand():
    g = nc(["Raider"])
    set_zones(g, hand=["Raider", "Copper", "Copper", "Copper", "Copper"])
    set_zones(g, 1, hand=["Gold", "Estate", "Estate", "Estate", "Estate"])
    to_night(g)
    play(g, "Raider")
    assert g.state.pending is None and "reveals their hand" in log(g)


def test_sacred_grove_shares_boon():
    g = nc(["Sacred Grove"])
    set_zones(g, hand=["Sacred Grove", "Copper", "Copper", "Copper", "Copper"])
    boons(g, "The Mountain's Gift")
    play(g, "Sacred Grove")
    assert g.state.buys == 2 and g.state.coins == 3 and "Silver" in me(g).discard
    assert g.state.pending.decision.player == 1
    answer(g, "Receive The Mountain's Gift")
    assert "Silver" in me(g, 1).discard
    g = nc(["Sacred Grove"])
    set_zones(g, hand=["Sacred Grove", "Copper", "Copper", "Copper", "Copper"])
    boons(g, "The Forest's Gift")
    play(g, "Sacred Grove")
    assert g.state.pending is None and g.state.buys == 3 and g.state.coins == 4


def test_sacred_grove_river_gift_other_player_draws_at_end_of_turn():
    g = nc(["Sacred Grove"])
    set_zones(g, hand=["Sacred Grove", "Copper", "Copper", "Copper", "Copper"])
    boons(g, "The River's Gift")
    play(g, "Sacred Grove")
    answer(g, "Receive The River's Gift")
    end(g); end(g)
    assert len(me(g, 1).hand) == 6 and len(me(g, 0).hand) == 6


def test_secret_cave():
    g = nc(["Secret Cave"])
    assert "Magic Lamp" in me(g).all_cards()
    set_zones(g, hand=["Secret Cave", "Estate", "Estate", "Estate", "Copper"], deck=["Copper"] * 8)
    play(g, "Secret Cave")
    answer(g, "Discard 3 cards")
    answer(g, "Estate", "Estate", "Estate")
    end(g); end(g)
    assert "Secret Cave" in me(g).in_play
    finish_turn(g)                                           # player 1's turn; player 0's next turn starts with +$3
    assert g.state.current_player == 0 and g.state.coins == 3
    g = nc(["Secret Cave"])
    set_zones(g, hand=["Secret Cave", "Estate", "Estate", "Copper"], deck=["Copper"] * 8)
    play(g, "Secret Cave")
    answer(g)
    end(g); end(g)
    assert "Secret Cave" not in me(g).in_play


def test_magic_lamp():
    g = nc(["Secret Cave"])
    set_zones(g, hand=["Magic Lamp"], in_play=["Copper", "Silver", "Gold", "Estate", "Village"])
    g.state.actions = 0
    end(g)
    g.apply(0, PlayTreasure("Magic Lamp"))
    assert "Magic Lamp" in g.state.trash and me(g).discard.count("Wish") == 3 and g.state.offsupply["Wish"] == 9
    g = nc(["Secret Cave"])
    set_zones(g, hand=["Magic Lamp"], in_play=["Copper", "Copper", "Gold", "Estate", "Village"])
    end(g)
    g.apply(0, PlayTreasure("Magic Lamp"))
    assert "Magic Lamp" not in g.state.trash


def test_wish_returns_and_gains_to_hand():
    g = nc(["Secret Cave"])
    set_zones(g, hand=["Wish"])
    g.state.offsupply["Wish"] = 11
    play(g, "Wish")
    assert g.state.offsupply["Wish"] == 12 and g.state.actions == 1
    answer(g, "Gold")
    assert "Gold" in me(g).hand


def test_shepherd_and_pasture():
    g = nc(["Shepherd"])
    set_zones(g, hand=["Shepherd", "Estate", "Estate", "Copper", "Province"], deck=["Gold"] * 8)
    play(g, "Shepherd")
    answer(g, "Estate", "Estate", "Province")
    assert me(g).hand.count("Gold") == 6 and g.state.actions == 1
    p = me(g)
    p.deck, p.hand, p.discard, p.in_play = [], [], [], []
    p.deck = ["Pasture", "Estate", "Estate"]
    assert score_player(p, g.state) == 2 + 2


def test_skulk_blocked_by_moat_turns_no_hex():
    g = nc(["Skulk"])
    set_zones(g, hand=["Skulk", "Copper", "Copper", "Copper", "Copper"])
    set_zones(g, 1, hand=["Moat", "Copper", "Copper", "Copper", "Copper"])
    hexes(g, "Plague")
    play(g, "Skulk")
    answer(g, "Moat")
    assert g.state.hexes == ["Plague"] and g.state.buys == 2 and "Curse" not in me(g, 1).hand


def test_tormentor_imp_or_hex():
    g = nc(["Tormentor"])
    set_zones(g, hand=["Tormentor", "Copper"])
    play(g, "Tormentor")
    assert "Imp" in me(g).discard and g.state.coins == 2 and g.state.hexes_discard == []
    g = nc(["Tormentor"])
    set_zones(g, hand=["Tormentor"], in_play=["Copper"])
    hexes(g, "Plague")
    play(g, "Tormentor")
    assert "Imp" not in me(g).discard and me(g, 1).hand.count("Curse") == 1


def test_imp_plays_a_card_without_a_copy_in_play():
    g = nc(["Tormentor"])
    set_zones(g, hand=["Imp", "Village", "Imp", "Smithy"], deck=["Gold"] * 8)
    g.state.offsupply["Imp"] = 12
    play(g, "Imp")
    assert set(g.state.pending.decision.options) == {"Village", "Smithy"}
    answer(g, "Smithy")
    assert len(me(g).hand) == 7


def test_tracker_puts_gained_cards_on_deck():
    g = nc(["Tracker"])
    assert "Pouch" in me(g).all_cards()
    set_zones(g, hand=["Tracker", "Copper", "Copper", "Copper", "Copper"])
    boons(g, "The Mountain's Gift")
    play(g, "Tracker")
    assert g.state.coins == 1
    assert g.state.pending is not None
    answer(g, "Put it onto your deck")
    assert me(g).deck[-1] == "Silver"
    to_buy_phase(g)
    g.apply(0, PlayAllTreasures())
    g.state.coins = 3
    g.apply(0, Buy("Silver"))
    answer(g)
    assert "Silver" in me(g).discard


def test_pouch():
    g = nc(["Tracker"])
    set_zones(g, hand=["Pouch"])
    to_buy_phase(g)
    g.apply(0, PlayTreasure("Pouch"))
    assert g.state.buys == 2 and g.state.coins == 1


def test_tragic_hero_trashes_itself_with_eight_cards_and_gains_treasure():
    g = nc(["Tragic Hero"])
    set_zones(g, hand=["Tragic Hero", "Copper", "Copper", "Copper", "Copper"], deck=["Estate"] * 6)
    play(g, "Tragic Hero")
    assert len(me(g).hand) == 7 and g.state.pending is None and g.state.buys == 2
    g = nc(["Tragic Hero"])
    set_zones(g, hand=["Tragic Hero"] + ["Copper"] * 5, deck=["Estate"] * 6)
    play(g, "Tragic Hero")
    assert "Tragic Hero" in g.state.trash
    assert "Gold" in g.state.pending.decision.options and "Curse" not in g.state.pending.decision.options
    answer(g, "Gold")
    assert "Gold" in me(g).discard


def test_vampire_hexes_gains_and_becomes_bat_and_back():
    g = nc(["Vampire"])
    set_zones(g, hand=["Vampire", "Copper", "Copper", "Copper", "Copper"])
    hexes(g, "Plague")
    to_night(g)
    play(g, "Vampire")
    assert me(g, 1).hand.count("Curse") == 1
    assert "Vampire" not in g.state.pending.decision.options and "Gold" not in g.state.pending.decision.options
    answer(g, "Smithy")
    assert "Smithy" in me(g).discard and "Bat" in me(g).discard and "Vampire" not in me(g).in_play
    assert g.state.supply["Vampire"] == 11 and g.state.offsupply["Bat"] == 9      # (this Vampire was not gained: its pile grows)
    set_zones(g, 0, hand=["Bat", "Curse", "Estate", "Copper"])
    finish_turn(g)
    set_zones(g, 0, hand=["Bat", "Curse", "Estate", "Copper"])
    g.state.current_player == 0
    finish_turn(g)
    to_buy_phase(g)
    end(g)
    play(g, "Bat")
    answer(g, "Curse", "Estate")
    assert "Vampire" in me(g).discard and g.state.offsupply["Bat"] == 10 and g.state.supply["Vampire"] == 10


def test_bat_without_trashing_stays_a_bat():
    g = nc(["Vampire"])
    set_zones(g, hand=["Bat", "Copper"])
    g.state.offsupply["Bat"] = 9
    to_night(g)
    play(g, "Bat")
    answer(g)
    assert "Bat" in me(g).discard + me(g).in_play and "Vampire" not in me(g).discard


def test_ghost_plays_action_twice_next_turn():
    g = nc(["Cemetery"])
    set_zones(g, hand=["Ghost", "Copper"], deck=["Estate", "Village", "Copper"])
    g.state.offsupply["Ghost"] = 5
    to_night(g)
    play(g, "Ghost")
    assert me(g).ghosted == ["Village"] and me(g).discard == ["Copper"] and me(g).deck == ["Estate"]
    finish_turn(g)
    set_zones(g, 0, deck=["Gold"] * 10)
    finish_turn(g)
    assert g.state.actions == 5 and "Village" in me(g).in_play and "Ghost" in me(g).in_play     # 1 + 2 + 2


def test_ghost_without_an_action_is_discarded():
    g = nc(["Cemetery"])
    set_zones(g, hand=["Ghost"], deck=["Estate", "Copper", "Copper"], discard=[])
    to_night(g)
    play(g, "Ghost")
    assert not me(g).ghosted and "Ghost" in me(g).in_play
    end(g)
    assert "Ghost" not in me(g).in_play


def test_will_o_wisp():
    g = nc(["Bard"])
    set_zones(g, hand=["Will-o'-Wisp"], deck=["Gold", "Copper", "Silver"])
    play(g, "Will-o'-Wisp")
    assert sorted(me(g).hand) == ["Copper", "Silver"] and me(g).deck == ["Gold"]
    g = nc(["Bard"])
    set_zones(g, hand=["Will-o'-Wisp"], deck=["Copper", "Gold", "Silver"])
    play(g, "Will-o'-Wisp")
    assert me(g).deck == ["Copper", "Gold"] and me(g).hand == ["Silver"]


# ------------------------------------------------------------------ whole games
def count_all(g):
    s = g.state
    return (sum(s.supply.values()) + sum(s.offsupply.values()) + len(s.trash)
            + sum(len(p.all_cards()) for p in s.players) + sum(len(v) for v in s.stacks.values()) - sum(
                s.supply.get(n, 0) for n in s.stack_of))


@pytest.mark.parametrize("seed", range(60))
def test_random_games_with_nocturne_cards_hold_every_invariant(seed):
    rng = random.Random(seed)
    cards = rng.sample(kingdom_cards(["Nocturne"]), 10)
    g = new_game(GameConfig(["A", "B", "C", "D"][: 2 + seed % 3], cards, seed, shelters=bool(seed % 2)))
    start = count_all(g)
    bots = [RandomBot(random.Random(seed * 11 + i)) for i in range(4)]
    for _ in range(8000):
        if g.state.status is GameStatus.FINISHED:
            break
        p = g.acting_player
        g.apply(p, bots[p].choose(g, p))
        assert count_all(g) == start, g.state.log[-3:]
        assert all(c >= 0 for c in g.state.supply.values()) and all(c >= 0 for c in g.state.offsupply.values())
        assert 0 <= g.state.actions < 400
        assert sorted(g.state.boons + g.state.boons_discard + g.state.kept_boons + g.state.druid_boons
                      + [b for q in g.state.players for b in q.held_boons]) in ([], sorted(BOON_NAMES)) or g.state.pending is not None
    build_view(g, 0)
    clone = replay(g.config, g.history)
    assert [q.deck for q in clone.state.players] == [q.deck for q in g.state.players]
    assert clone.state.trash == g.state.trash and clone.state.boons == g.state.boons


@pytest.mark.parametrize("seed", range(6))
def test_nocturne_games_are_finished_by_bots_and_have_scores(seed):
    cards = random.Random(seed).sample(kingdom_cards(["Nocturne"]), 10)
    g = new_game(GameConfig(["A", "B"], cards, seed, shelters=False))
    run_game(g, [BigMoneyBot(), BigMoneyBot()])
    assert g.state.status is GameStatus.FINISHED
    view = build_view(g, 0)
    assert view["phase"] in ("action", "buy", "night")


def test_view_carries_boons_hexes_states_and_card_info():
    g = nc(["Bard", "Skulk", "Fool"])
    v = build_view(g, 0)
    assert v["nocturne"]["boons_left"] == 12 and v["nocturne"]["hexes_left"] == 12 and v["has_night"] is False
    assert v["cards"]["The Sea's Gift"]["text"] == BOONS["The Sea's Gift"] and v["cards"]["Envy"]["types"] == ["hex"]
    assert v["cards"]["Lost in the Woods"]["types"] == ["state"] and v["cards"]["Lucky Coin"]["cost"] == 4
    me(g, 1).miserable = 1
    me(g, 1).deluded = True
    g.state.lost_in_woods = 1
    assert build_view(g, 0)["players"][1]["states"] == ["Deluded", "Miserable", "Lost in the Woods"]
    assert nc(["Monastery"]) and build_view(nc(["Monastery"]), 0)["has_night"] is True
    assert build_view(nc(["Conclave"]), 0)["nocturne"] is None


def test_every_kingdom_card_can_be_played_by_a_bot_game_without_errors():
    for name in kingdom_cards(["Nocturne"]):
        cards = [name] + random.Random(1).sample([c for c in kingdom_cards(["Base"]) if c != name], 9)
        g = new_game(GameConfig(["A", "B"], cards, 3, shelters=False))
        bots = [RandomBot(random.Random(i)) for i in range(2)]
        for _ in range(2500):
            if g.state.status is GameStatus.FINISHED:
                break
            p = g.acting_player
            g.apply(p, bots[p].choose(g, p))


def test_view_legal_actions_in_the_night_phase():
    g = nc(["Monastery", "Werewolf"])
    set_zones(g, hand=["Monastery", "Copper", "Copper", "Copper", "Copper"])
    to_night(g)
    v = build_view(g, 0)
    assert v["phase"] == "night" and v["has_night"] is True
    kinds = [(a["type"], a.get("card")) for a in v["legal_actions"]]
    assert ("play_action", "Monastery") in kinds and ("end_phase", None) in kinds
    assert not any(k[0] in ("buy", "play_treasure", "play_all_treasures") for k in kinds)
