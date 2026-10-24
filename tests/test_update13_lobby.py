"""The lobby setting for Platinum and Colony (needs the web layer, so it lives apart from the engine tests)."""

from test_web_rooms import RoomManager, run, two_player_room


def test_host_chooses_platinum_and_colony_in_the_lobby():
    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, code = await two_player_room(m)
        assert host.last("lobby")["colonies"] is None                  # automatic by default
        await guest.say(type="set_colonies", colonies=True)
        assert guest.last_error() == "Only the host can do that."
        for bad in ("yes", 1, [], {}):
            await host.say(type="set_colonies", colonies=bad)
            assert "Platinum and Colony" in host.last_error(), bad
        await host.say(type="set_colonies", colonies=True)
        assert host.last("lobby")["colonies"] is True and guest.last("lobby")["colonies"] is True
        await host.say(type="set_kingdom", kingdom=["Village", "Smithy"])
        await host.say(type="start")
        names = {p["name"] for p in host.view["piles"]}
        assert {"Platinum", "Colony"} <= names
        await host.say(type="set_colonies", colonies=False)             # too late once started
        assert "already started" in host.last_error()
    run(scenario())


def test_colonies_never_and_automatic_follow_the_kingdom():
    async def scenario():
        m = RoomManager(bot_delay=0)
        host, guest, code = await two_player_room(m)
        await host.say(type="set_colonies", colonies=False)
        await host.say(type="set_kingdom", kingdom=["Bank", "Hoard", "Watchtower"])
        await host.say(type="start")
        assert "Colony" not in {p["name"] for p in host.view["piles"]}
        await host.say(type="end_game")
        await host.say(type="rematch")
        await host.say(type="set_colonies", colonies=None)              # automatic: three Prosperity cards, all Prosperity
        await host.say(type="start")
        assert "Colony" in {p["name"] for p in host.view["piles"]}
    run(scenario())
