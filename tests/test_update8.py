"""Special cards (Rosebud, Guardian Angel, God Mode), protection, resign / end game, cheat codes,
the 'my games' list, delete game, and auto-end-turn data."""

import json
import random

import pytest

from dominion.ai import BigMoneyBot, RandomBot
from dominion.cards import CardType, get_card
from dominion.cards.registry import catastrophe_cards, fenced_cards, special_cards
from dominion.engine import (
    Buy, Cheat, Choose, EndGame, EndPhase, GameConfig, GameStatus, IllegalActionError, PlayAction, PlayAllTreasures,
    Resign, build_view, legal_actions, new_game, replay,
)
from dominion.engine.scoring import score_player
from helpers import make_game, set_zones, to_buy_phase, total_cards
from test_bots import play_checked

KINGDOM = ["Moat", "Village", "Smithy", "Militia", "Witch"]


def sg(players=3, cats=("Rosebud",), **kw):
    return make_game(players=players, kingdom=KINGDOM, catastrophes=list(cats), **kw)


def play(g, card, player=0):
    g.apply(player, PlayAction(card))


def answer(g, player, *cards):
    g.apply(player, Choose(tuple(cards)))


def log_text(g):
    return "\n".join(str(x) for x in g.state.log)


# ------------------------------------------------------------------ the cards themselves
def test_special_cards_are_registered_and_fenced_like_catastrophes():
    assert special_cards() == [
        "Chance Time", "Exodia the Forbidden One", "God Mode", "Guardian Angel", "Invisibility Cloak", "Midas Touch", "Rosebud",
    ]
    assert set(fenced_cards()) == set(catastrophe_cards()) | set(special_cards())
    for n in special_cards():
        c = get_card(n)
        assert c.is_type(CardType.SPECIAL) and not c.kingdom and c.expansion == "Special"
        assert c.is_type(CardType.ACTION) == (n != "Exodia the Forbidden One")      # the Exodia pieces are not playable
    assert [get_card(n).cost for n in ("Rosebud", "Guardian Angel", "God Mode")] == [5, 6, 10]


def test_special_cards_get_two_copy_piles_and_never_end_the_game():
    g = sg(cats=("Rosebud", "God Mode"))
    assert g.state.supply["Rosebud"] == 2 and g.state.supply["God Mode"] == 2
    g.state.supply["Rosebud"] = g.state.supply["God Mode"] = 0
    g.state.supply["Village"] = 0
    g.state.supply["Moat"] = 0
    assert g.state.status is GameStatus.ACTIVE
    from dominion.engine.rules import is_game_over
    assert not is_game_over(g.state)                       # only 2 ordinary piles are empty


def test_special_cards_are_never_in_a_random_kingdom_and_need_the_host_to_pick_them():
    from dominion.cards import kingdom_cards
    assert not set(special_cards()) & set(kingdom_cards())
    g = make_game(players=2, kingdom=KINGDOM, catastrophes=["Rosebud", "God Mode", "Guardian Angel"])   # no limit on how many
    assert all(g.state.supply[n] == 2 for n in ("Rosebud", "God Mode", "Guardian Angel"))


def test_lurker_cannot_touch_special_cards():
    g = make_game(players=2, kingdom=["Lurker", "Village"], catastrophes=["Rosebud"])
    set_zones(g, 0, hand=["Lurker"])
    play(g, "Lurker")
    assert "Rosebud" not in g.state.pending.decision.options


# ------------------------------------------------------------------ Rosebud
def test_rosebud_gives_money_to_yourself_right_away():
    g = sg()
    set_zones(g, 0, hand=["Rosebud", "Copper"])
    play(g, "Rosebud")
    assert g.state.trash == ["Rosebud"]
    d = g.state.pending.decision
    assert d.options == ("P0", "P1", "P2")
    answer(g, 0, "P0")
    assert g.state.coins == 12
    assert "ROSEBUD" in log_text(g)


def test_rosebud_for_another_player_arrives_at_the_start_of_their_next_turn():
    g = sg()
    set_zones(g, 0, hand=["Rosebud"])
    play(g, "Rosebud")
    answer(g, 0, "P2")
    assert g.state.players[2].bonus_coins == 12 and g.state.coins == 0
    assert "P2 will get +$12" in log_text(g)
    g.apply(0, EndPhase()); g.apply(0, EndPhase())        # P1's turn: P2's gift is not theirs
    assert g.state.coins == 0 and g.state.players[2].bonus_coins == 12
    g.apply(1, EndPhase()); g.apply(1, EndPhase())        # P2's turn
    assert g.state.current_player == 2 and g.state.coins == 12 and g.state.players[2].bonus_coins == 0
    assert "P2 receives $12 from Rosebud" in log_text(g)
    g.apply(2, EndPhase())
    assert g.state.coins == 12                            # still there in the Buy phase
    g.apply(2, EndPhase())
    g.apply(0, EndPhase()); g.apply(0, EndPhase())
    assert g.state.coins == 0                             # one-off: nothing the following turns


def test_rosebud_gift_waits_through_a_skipped_turn():
    g = sg(cats=("Rosebud", "Long Night"))
    g.state.players[1].bonus_coins = 12
    g.state.players[1].skips = 1
    g.apply(0, EndPhase()); g.apply(0, EndPhase())        # P1's turn is skipped, P2 plays
    assert g.state.current_player == 2 and g.state.players[1].bonus_coins == 12
    g.apply(2, EndPhase()); g.apply(2, EndPhase())
    g.apply(0, EndPhase()); g.apply(0, EndPhase())
    assert g.state.current_player == 1 and g.state.coins == 12


def test_rosebud_money_buys_things_and_is_single_use_under_throne_room():
    g = make_game(players=2, kingdom=["Throne Room", "Village"], catastrophes=["Rosebud"])
    set_zones(g, 0, hand=["Throne Room", "Rosebud"])
    play(g, "Throne Room")
    answer(g, 0, "Rosebud")
    answer(g, 0, "P0")
    assert g.state.pending is None and g.state.coins == 12 and g.state.trash == ["Rosebud"]
    to_buy_phase(g)
    g.apply(0, Buy("Province"))
    assert g.state.coins == 4


# ------------------------------------------------------------------ Guardian Angel / God Mode
def test_guardian_angel_protects_for_five_of_your_own_turns():
    g = sg(cats=("Guardian Angel",), players=2)
    set_zones(g, 0, hand=["Guardian Angel"], deck=["Gold", "Gold"])
    play(g, "Guardian Angel")
    me = g.state.players[0]
    assert len(me.hand) == 2 and me.protection == 5 and g.state.trash == ["Guardian Angel"]
    view = build_view(g, 1)["players"][0]
    assert view["protection"] == 5
    for turn in range(5):                                       # her 5 following turns
        g.apply(0, EndPhase()); g.apply(0, EndPhase())          # end this turn
        assert me.protection == 5 - turn if turn else me.protection == 5
        assert me.protection > 0
        g.apply(1, EndPhase()); g.apply(1, EndPhase())          # opponent's turn: she is protected throughout
    # the 5th later turn has not been played yet: protection is still on
    assert me.protection == 1
    g.apply(0, EndPhase()); g.apply(0, EndPhase())              # end of her 5th turn after the one it was played
    assert me.protection == 0
    assert "protection runs out" in log_text(g)


def test_attacks_skip_a_protected_player_without_asking_questions():
    g = sg(cats=("Guardian Angel",))
    g.state.players[1].protection = 3
    set_zones(g, 0, hand=["Militia"])
    set_zones(g, 1, hand=["Moat", "Copper", "Copper", "Copper", "Copper"])
    set_zones(g, 2, hand=["Copper"] * 5)
    play(g, "Militia")
    # P1 is protected: no Moat prompt and nobody makes them discard; P2 is asked to discard
    d = g.state.pending.decision
    assert d.player == 2 and d.min_choices == 2
    assert len(g.state.players[1].hand) == 5
    assert "P1 is protected and unaffected" in log_text(g)


def test_protection_covers_witch_and_targeted_catastrophes():
    g = sg(cats=("Grand Swap", "Time Stop"))
    g.state.players[1].protected_forever = True
    set_zones(g, 0, hand=["Grand Swap"], deck=["Gold"] * 4)
    set_zones(g, 1, deck=["Copper"] * 4)
    play(g, "Grand Swap")
    answer(g, 0, "P1")
    assert g.state.players[0].deck == ["Gold"] * 4          # nothing was swapped
    assert g.state.players[1].deck == ["Copper"] * 4
    g2 = sg(cats=("The Snap",))
    g2.state.players[1].protected_forever = True
    set_zones(g2, 0, hand=["The Snap"], deck=["Gold"] * 6)
    set_zones(g2, 1, hand=["Copper"] * 5, deck=["Copper"] * 5)
    play(g2, "The Snap")
    assert len(g2.state.players[1].all_cards()) == 10       # protected player untouched
    assert len(g2.state.players[0].all_cards()) == 3        # the player who played it is always hit


def test_protection_does_not_stop_things_that_are_not_attacks():
    g = sg(cats=("Cataclysm",))
    g.state.players[1].protected_forever = True
    set_zones(g, 0, hand=["Cataclysm", "Gold"], deck=["Gold"] * 3)
    set_zones(g, 1, hand=["Copper"] * 5, deck=["Copper"] * 5)
    play(g, "Cataclysm")
    assert "Every deck is combined" in log_text(g)


def test_god_mode_is_permanent_and_gives_a_big_turn():
    g = sg(cats=("God Mode",), players=2)
    set_zones(g, 0, hand=["God Mode"])
    play(g, "God Mode")
    s = g.state
    assert (s.actions, s.buys, s.coins) == (3, 4, 5)                  # played one action: 0 + 3 ; buys 1 + 3 ; $5
    assert s.players[0].protected_forever and s.trash == ["God Mode"]
    for _ in range(12):
        g.apply(g.state.current_player, EndPhase()); g.apply(g.state.current_player, EndPhase())
    assert s.players[0].protected_forever
    assert build_view(g, 1)["players"][0]["protection"] == "forever"
    assert "GOD MODE" in log_text(g)


def test_guardian_angel_replayed_keeps_the_stronger_protection():
    g = sg(cats=("Guardian Angel",), players=2)
    g.state.players[0].protection = 3
    set_zones(g, 0, hand=["Guardian Angel", "Guardian Angel"], in_play=[])
    g.state.actions = 2
    play(g, "Guardian Angel")
    assert g.state.players[0].protection == 5
    g.state.players[0].protection = 5
    play(g, "Guardian Angel")
    assert g.state.players[0].protection == 5


# ------------------------------------------------------------------ resign / end game
def test_resign_ends_the_game_and_the_resigner_cannot_win():
    g = make_game(players=2, kingdom=KINGDOM, seed=1)
    g.state.players[0].discard.extend(["Province"] * 4)            # P0 is far ahead ...
    g.apply(0, Resign())                                           # ... but resigns
    s = g.state
    assert s.status is GameStatus.FINISHED and s.winners == [1] and s.resigned == [0]
    assert s.end_reason == "P0 resigned."
    v = build_view(g, 1)
    assert v["status"] == "finished" and v["end_reason"] == "P0 resigned." and v["resigned"] == [0] and "stats" in v
    assert "P0 resigns." in log_text(g)


def test_a_player_may_resign_off_turn_and_mid_decision():
    g = make_game(players=3, kingdom=KINGDOM, seed=1)
    g.apply(2, Resign())                                           # not their turn
    assert g.state.winners and 2 not in g.state.winners
    g = make_game(players=2, kingdom=KINGDOM, seed=1)
    set_zones(g, 0, hand=["Militia"])
    set_zones(g, 1, hand=["Copper"] * 5)
    play(g, "Militia")
    assert g.state.pending is not None
    g.apply(1, Resign())                                           # in the middle of an Attack
    assert g.state.pending is None and g.state.winners == [0]


def test_end_game_keeps_the_current_scores():
    g = make_game(players=3, kingdom=KINGDOM, seed=1)
    g.state.players[2].discard.extend(["Province"] * 2)
    g.apply(1, EndGame())
    assert g.state.status is GameStatus.FINISHED and g.state.winners == [2] and g.state.resigned == []
    assert g.state.end_reason == "P1 ended the game early."


def test_nothing_is_possible_after_the_game_ends_and_bots_never_resign():
    g = make_game(players=2, kingdom=KINGDOM, seed=1)
    g.apply(0, Resign())
    for action in (Resign(), EndGame(), Cheat("coins"), EndPhase()):
        with pytest.raises(IllegalActionError):
            g.apply(0, action)
    g = make_game(players=2, kingdom=KINGDOM, seed=1)
    assert not any(isinstance(a, (Resign, EndGame, Cheat)) for a in legal_actions(g.state))


def test_resign_is_part_of_the_history_and_replays():
    g = make_game(players=2, kingdom=KINGDOM, seed=1)
    g.apply(0, EndPhase()); g.apply(0, EndPhase())
    g.apply(1, Resign())
    r = replay(g.config, g.history)
    assert r.state.status is GameStatus.FINISHED and r.state.winners == g.state.winners == [0]
    assert [str(x) for x in r.state.log] == [str(x) for x in g.state.log]


def test_resign_with_everyone_else_resigned_still_has_a_winner():
    from dominion.engine.scoring import determine_winners
    g = make_game(players=2, kingdom=KINGDOM, seed=1)
    g.state.resigned = [0, 1]
    assert determine_winners(g.state) in ([0, 1], [0], [1])


# ------------------------------------------------------------------ cheat codes
def cheat_game(**kw):
    g = new_game(GameConfig(["P0", "P1"], KINGDOM, 1, cheats=True, **kw))
    return g


def test_cheats_give_100_of_each_on_your_own_turn_and_are_logged():
    g = cheat_game()
    g.apply(0, Cheat("coins")); g.apply(0, Cheat("actions")); g.apply(0, Cheat("buys"))
    s = g.state
    assert (s.coins, s.actions, s.buys) == (100, 101, 101)
    assert "P0 uses a cheat code: +100 coins!" in log_text(g)
    assert s.log[-1].kind == "cheat"
    assert build_view(g, 0)["cheats"] is True


def test_cheats_really_work_in_play():
    g = cheat_game()
    set_zones(g, 0, hand=["Village", "Village", "Village", "Copper", "Copper"], in_play=[])
    g.apply(0, Cheat("actions"))
    for _ in range(3):
        play(g, "Village")
    g.apply(0, Cheat("coins")); g.apply(0, Cheat("buys"))
    to_buy_phase(g)
    for _ in range(5):
        g.apply(0, Buy("Province"))
    assert g.state.coins == 100 - 40 and g.state.buys == 101 - 5 and g.state.supply["Province"] == 3


def test_cheats_are_refused_when_off_off_turn_mid_decision_or_unknown():
    g = make_game(players=2, kingdom=KINGDOM, seed=1)              # cheats not enabled
    with pytest.raises(IllegalActionError, match="not turned on"):
        g.apply(0, Cheat("coins"))
    g = cheat_game()
    with pytest.raises(IllegalActionError, match="your own turn"):
        g.apply(1, Cheat("coins"))
    with pytest.raises(IllegalActionError, match="Unknown cheat"):
        g.apply(0, Cheat("lives"))
    set_zones(g, 0, hand=["Militia"])
    play(g, "Militia")
    with pytest.raises(IllegalActionError, match="pending decision"):
        g.apply(0, Cheat("coins"))
    assert g.state.coins == 2                                        # nothing was given


def test_cheats_reset_each_turn_and_replay():
    g = cheat_game()
    g.apply(0, Cheat("coins"))
    g.apply(0, EndPhase()); g.apply(0, EndPhase())
    assert g.state.coins == 0 and g.state.actions == 1 and g.state.buys == 1
    g.apply(1, Cheat("buys"))
    r = replay(g.config, g.history)
    assert r.state.buys == 101 and [str(x) for x in r.state.log] == [str(x) for x in g.state.log]


# ------------------------------------------------------------------ random play with the new cards
@pytest.mark.parametrize("players", [2, 3, 4])
def test_random_games_with_special_cards_keep_every_card_and_protection_sane(players):
    for seed in range(8):
        rng = random.Random(seed)
        g = make_game(players=players, kingdom=KINGDOM, catastrophes=["Rosebud", "Guardian Angel"], seed=seed)
        for p in g.state.players:
            p.deck.extend(["Rosebud", "Guardian Angel", "Militia", "Witch"])
            rng.shuffle(p.deck)
        before = total_cards(g)
        bots = [RandomBot(random.Random(rng.random())) for _ in range(players)]
        for _ in range(1200):
            if g.state.status is GameStatus.FINISHED:
                break
            play_checked(g, bots)
            assert total_cards(g) == before
            for p in g.state.players:
                assert 0 <= p.protection <= 5 and p.bonus_coins in (0, 12, 24, 36)


# ================================================================== the server side
def _chat_texts(client):
    return [m["text"] for m in client.inbox if m["type"] == "chat"]


def test_host_turns_cheat_codes_on_and_they_work_through_the_chat():
    from test_web_rooms import Client, RoomManager, run, two_player_room

    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, code = await two_player_room(m)
        assert host.last("lobby")["cheats"] is False                    # off by default
        await guest.say(type="set_cheats", cheats=True)
        assert guest.last_error() == "Only the host can do that."
        for bad in ("yes", 1, None):
            await host.say(type="set_cheats", cheats=bad)
            assert "on or off" in host.last_error(), bad
        # while cheats are off a "cheat phrase" is only chat, in the lobby and in the game
        await host.say(type="chat", text="show me the money")
        assert "show me the money" in _chat_texts(guest)
        await host.say(type="set_cheats", cheats=True)
        assert host.last("lobby")["cheats"] and guest.last("lobby")["cheats"]
        await host.say(type="chat", text="greed is good")                # lobby: still just chat
        assert "greed is good" in _chat_texts(guest)
        await host.say(type="start")
        assert host.view["cheats"] is True and guest.view["cheats"] is True
        seen = len(_chat_texts(guest))

        await host.say(type="chat", text="  Show   ME the Money ")      # case and spacing do not matter
        assert host.view["coins"] == 100 and guest.view["coins"] == 100
        await host.say(type="chat", text="power overwhelming")
        await host.say(type="chat", text="greed is good")
        assert (host.view["actions"], host.view["buys"]) == (101, 101)
        assert len(_chat_texts(guest)) == seen, "a cheat code must not appear as chat"
        assert any("Ann uses a cheat code: +100 coins" in e["text"] for e in guest.view["log"])
        assert any(e["kind"] == "cheat" for e in guest.view["log"])

        await guest.say(type="chat", text="show me the money")           # not the guest's turn
        assert "your own turn" in guest.last_error()
        assert guest.view["coins"] == 100                                 # the host's coins, unchanged by the guest
        assert len(_chat_texts(host)) == seen

        # cheats can be taken back with an undo, like any other action
        await host.say(type="undo_request")
        await guest.say(type="undo_vote", approve=True)
        assert (host.view["coins"], host.view["actions"], host.view["buys"]) == (100, 101, 1)   # only the last cheat is taken back
    run(scenario())


def test_cheats_off_means_the_phrase_is_chat_in_the_game():
    from test_web_rooms import RoomManager, run, two_player_room

    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, code = await two_player_room(m)
        await host.say(type="start")
        await host.say(type="chat", text="show me the money")
        assert "show me the money" in _chat_texts(guest) and host.view["coins"] == 0
    run(scenario())


def test_cheat_chat_is_refused_during_an_undo_vote():
    from test_web_rooms import RoomManager, run, two_player_room

    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, code = await two_player_room(m)
        await host.say(type="set_cheats", cheats=True)
        await host.say(type="start")
        room = m.rooms[code]
        await host.say(type="action", action={"type": "end_phase"})
        await host.say(type="undo_request")
        await host.say(type="chat", text="greed is good")
        assert "undo vote" in host.last_error()
        assert room.game.state.buys == 1
    run(scenario())


def test_my_games_list_shows_only_games_you_hold_a_token_for():
    from test_web_rooms import Client, RoomManager, run, two_player_room

    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, code = await two_player_room(m)
        other_host = Client(m)
        await other_host.say(type="create", name="Zed")
        other_code = other_host.last("joined")["room"]
        home = Client(m)                                                   # a browser on the home page
        mine = [{"room": code, "token": host.token}, {"room": other_code, "token": host.token},
                {"room": "ZZZZ", "token": "x"}, {"room": code, "token": "wrong"}, "junk", {"room": 5}]
        await home.say(type="list_games", games=mine)
        reply = home.last("games")
        assert [g["room"] for g in reply["games"]] == [code]
        g = reply["games"][0]
        assert g["status"] == "lobby" and g["players"] == ["Ann", "Bo"] and g["you"] == 0 and g["is_host"] is True
        assert reply["gone"] == [other_code, "ZZZZ", code, "", "5"]
        await host.say(type="start")
        await home.say(type="list_games", games=[{"room": code, "token": guest.token}])
        g = home.last("games")["games"][0]
        assert g["status"] == "playing" and g["you"] == 1 and g["is_host"] is False
        assert g["your_turn"] is False and g["turn"] == 1
        await home.say(type="list_games", games=[{"room": code, "token": host.token}])
        assert home.last("games")["games"][0]["your_turn"] is True
        await guest.say(type="resign")
        await home.say(type="list_games", games=[{"room": code, "token": host.token}])
        assert home.last("games")["games"][0]["status"] == "finished"
        for bad in ("x", None, [{}] * 21, 5):
            await home.say(type="list_games", games=bad)
            assert "up to 20" in home.last_error()
        assert "Zed" not in json.dumps(home.last("games"))                 # other rooms never leak
    run(scenario())


def test_resign_end_game_and_rematch_through_the_server():
    from test_web_rooms import RoomManager, run, two_player_room

    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, code = await two_player_room(m)
        await guest.say(type="resign")
        assert "no game to resign" in guest.last_error()
        await host.say(type="end_game")
        assert "no game to end" in host.last_error()
        await host.say(type="start")
        await guest.say(type="end_game")
        assert guest.last_error() == "Only the host can do that."
        assert host.view["status"] == "active"
        await guest.say(type="resign")                                    # not their turn: still fine
        for c in (host, guest):
            assert c.view["status"] == "finished" and c.view["winners"] == [0]
            assert c.view["end_reason"] == "Bo resigned." and c.view["resigned"] == [1]
        await host.say(type="resign")
        assert "already over" in host.last_error()
        await host.say(type="rematch")
        assert host.last("lobby") is not None and host.inbox[-1]["type"] == "lobby"
        # the host ends a game early: scores count, nobody resigned
        await host.say(type="start")
        m.rooms[code].game.state.players[1].discard.extend(["Province"] * 2)
        await host.say(type="end_game")
        assert host.view["status"] == "finished" and host.view["winners"] == [1] and host.view["resigned"] == []
        assert host.view["end_reason"] == "Ann ended the game early."
        assert [s["name"] for s in host.view["stats"]] == ["Ann", "Bo"]
    run(scenario())


def test_resigning_cancels_a_pending_undo_vote():
    from test_web_rooms import RoomManager, run, two_player_room

    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, code = await two_player_room(m)
        await host.say(type="start")
        await host.say(type="action", action={"type": "end_phase"})
        await host.say(type="undo_request")
        assert m.rooms[code].undo is not None
        await guest.say(type="resign")
        assert m.rooms[code].undo is None and host.view["status"] == "finished"
        assert "undo" in " ".join(_chat_texts(host)).lower()
    run(scenario())


def test_only_the_host_can_delete_a_game_and_everyone_is_sent_home():
    from test_web_rooms import Client, RoomManager, run, two_player_room

    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, code = await two_player_room(m)
        home = Client(m)
        await home.say(type="delete_room", room=code, token=guest.token)
        assert home.last_error() == "Only the host can delete a game." and code in m.rooms
        for bad in ({"room": "NOPE", "token": "x"}, {"room": code, "token": "wrong"}, {"room": code}, {}):
            await home.say(type="delete_room", **bad)
            assert home.last_error() == "Game not found."
        await host.say(type="start")
        await home.say(type="delete_room", room=code, token=host.token)    # from the home page, mid-game
        assert code not in m.rooms
        assert home.inbox[-1] == {"type": "deleted", "room": code}
        for c in (host, guest):
            assert c.inbox[-1] == {"type": "left", "reason": "The host deleted this game."}
            assert c.conn.room is None
        await host.say(type="join", room=code, name="Ann", token=host.token)
        assert host.last_error() == "Room not found."
    run(scenario())


def test_delete_a_lobby_with_a_bot_and_no_leftover_tasks():
    from test_web_rooms import RoomManager, run, two_player_room

    async def scenario():
        m = RoomManager(bot_delay=0)
        host, _none, code = await two_player_room(m, bot=True)
        await host.say(type="start")
        room = m.rooms[code]
        await host.say(type="delete_room", room=code, token=host.token)
        assert code not in m.rooms
        await __import__("asyncio").sleep(0.05)
        assert room.bot_task is None or room.bot_task.done()
    run(scenario())


# ================================================================== the page's stylesheet
def test_every_card_css_class_is_one_the_page_really_puts_on_cards():
    """A rule like `.card.catastrophe` (a class no card ever has) once made Catastrophe cards unreadable."""
    import re
    from pathlib import Path
    from dominion.cards import CardType

    html = (Path(__file__).resolve().parent.parent / "src/dominion/web/static/index.html").read_text(encoding="utf-8")
    used = set(re.findall(r"\.card\.([a-z][a-z-]*)", html))
    real = {"small", "big", "clickable", "dim", "empty", "selected", "enter", "flash", "walled", "blind", "long", "xlong"} | {f"t-{t.value}" for t in CardType}
    assert used <= real, f"CSS styles card classes nothing ever sets: {sorted(used - real)}"
    # and the classes the script sets on cards are exactly these
    assert "c.classList.add(...info.types.map((t) => \"t-\" + t))" in html
    for cls in ("walled", "blind", "long", "xlong"):     # classes added later are really set by the script
        assert f'classList.add("{cls}")' in html, cls


# ================================================================== package layout (the "mixed-up __init__.py" upload problem)
def test_top_level_package_exports_the_cards_and_each_init_file_has_its_own_content():
    from pathlib import Path
    import dominion

    assert dominion.__version__ and dominion.get_card("Smithy").cost == 4
    assert {"CardDef", "CardType", "get_card", "kingdom_cards", "register"} <= set(dominion.__all__)
    root = Path(dominion.__file__).parent
    top = (root / "__init__.py").read_text(encoding="utf-8")
    cards = (root / "cards" / "__init__.py").read_text(encoding="utf-8")
    assert "from .cards.base import" in top and "from .base import" not in top      # not the cards file
    assert "from .base import" in cards and "from .cards.base import" not in cards  # not the top-level file
    for sub in ("cards", "engine", "ai", "ui", "web"):
        assert (root / sub / "__init__.py").is_file(), f"{sub}/__init__.py is missing (flattened upload?)"
    assert len({(root / p / "__init__.py").read_text(encoding="utf-8") for p in ("", "cards", "engine", "ai", "ui", "web")}) == 6


# ================================================================== update 10: the page's structure, written down as tests
def _page():
    from pathlib import Path
    return (Path(__file__).resolve().parent.parent / "src/dominion/web/static/index.html").read_text(encoding="utf-8")


def test_the_game_is_called_modinion_everywhere_the_player_can_see_it():
    import re
    html = _page()
    assert "<title>Modinion</title>" in html and "<h1>Modinion</h1>" in html and "Play Modinion online" in html
    text = re.sub(r"<script>.*?</script>|<style>.*?</style>|<!--.*?-->", "", html, flags=re.S)
    assert "Dominion" not in text, "the old name is still visible in the page"
    script = re.search(r"<script>(.*?)</script>", html, flags=re.S).group(1)
    assert "Your turn - Modinion" in script and "- Dominion" not in script
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    assert (root / "README.md").read_text(encoding="utf-8").startswith("# Modinion")
    assert "Deploying Modinion" in (root / "docs/DEPLOY.md").read_text(encoding="utf-8")


def test_the_page_is_laid_out_without_scrolling_players_left_turn_bar_bottom_right():
    import re
    html = _page()
    css = re.search(r"<style>(.*?)</style>", html, flags=re.S).group(1)
    assert re.search(r"html, body \{[^}]*overflow: hidden", css), "the page itself must never scroll"
    assert re.search(r"#game-grid \{[^}]*grid-template-columns: 230px minmax\(0, 1fr\) 330px", css)
    assert "max-height: 940px" in css and "--cw" in css                    # card size follows the screen height
    for panel in ("#supply-panel", "#hand-panel", "#inplay-panel", "#log, #chat-log", "#players-panel .players"):
        assert re.search(re.escape(panel) + r" \{[^}]*overflow(-y)?: auto", css), f"{panel} must scroll inside itself when it is too full"
    assert re.search(r"#popup-layer \{[^}]*position: fixed[^}]*justify-content: center", css)
    pos = {name: html.index(f'id="{name}"') for name in (
        "left-col", "players", "center-col", "supply-panel", "bottom-row", "right-col", "log-panel", "chat-slot-game",
        "topbar", "popup-layer", "decision", "undo-panel", "gameover")}
    assert pos["left-col"] < pos["players"] < pos["center-col"] < pos["supply-panel"] < pos["bottom-row"] < pos["right-col"]
    assert pos["right-col"] < pos["log-panel"] < pos["chat-slot-game"] < pos["topbar"], "log, chat, then the turn bar at the bottom"
    assert pos["popup-layer"] < pos["undo-panel"] < pos["decision"] < pos["gameover"]
    for removed in ("btn-deck-view", "btn-discard-view", "All the cards you own", "Your discard pile", "my_discard", "my_cards", "discard_count"):
        assert removed not in html, f"{removed} must be gone: players may not look through or count their discard pile"
    assert "brings " not in html.replace("brings it back", "") and "more pieces" not in html, "the Exodia lobby label is just the name and the cost"
