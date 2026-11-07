"""Special cards: optional single-use house-rule cards that *help* a player (the Catastrophe cards hurt).

Like the Catastrophe cards they are scarce (2 copies, their own supply row, never end the game by
running out) and trash themselves when played, so a Throne Room cannot repeat them.

  * Rosebud        - a pile of money for any player.
  * Guardian Angel - protection from Attacks for your next 5 turns.
  * God Mode       - protection from Attacks for the rest of the game, plus a big turn.
  * Invisibility Cloak - nothing another player's card does can affect you for the rest of the game.
  * Midas Touch    - every Treasure you play this turn is worth $3.
  * Chance Time    - spin a wheel with six outcomes (some of them bad for you).
  * Exodia the Forbidden One - collect all five pieces in your hand at the same time and you win on the spot.

"Protected" means every Attack (including the Catastrophes that target players) skips you: no Reaction
question is asked and nothing happens to you. It does not stop things that are not Attacks (Cataclysm,
Council Room giving you a card, Masquerade passing you one).
"""

from __future__ import annotations

from .base import CardDef, CardType, action
from .registry import register

ROSEBUD_COINS = 12


def _rosebud(ctx):
    if not ctx.trash_self():
        return
    names = (ctx.player_name, *[ctx.name_of(p) for p in ctx.other_players()])
    (chosen,) = yield ctx.choose(f"Rosebud: choose who gets ${ROSEBUD_COINS}.", names)
    who = ctx.player if chosen == ctx.player_name else ctx.other_players()[names[1:].index(chosen)]
    ctx.log("ROSEBUD! A fortune changes hands.", "special", 0)
    ctx.give_coins(who, ROSEBUD_COINS)


def _guardian_angel(ctx):
    if not ctx.trash_self():
        return
    ctx.log("GUARDIAN ANGEL! A protector watches over them.", "special", 0)
    ctx.draw(2)
    ctx.protect(5)


def _god_mode(ctx):
    if not ctx.trash_self():
        return
    ctx.log("GOD MODE! Nothing can touch them now.", "special", 0)
    ctx.protect_forever()
    ctx.add_actions(3)
    ctx.add_buys(3)
    ctx.add_coins(5)


_SPECIAL = (CardType.SPECIAL,)
register(action(
    "Rosebud", 5, _rosebud,
    f"Trash this. Choose any player, you included: they get +${ROSEBUD_COINS}. If you choose someone else, "
    "they get it at the start of their next turn.",
    kingdom=False, extra_types=_SPECIAL, expansion="Special",
))
register(action(
    "Guardian Angel", 6, _guardian_angel,
    "Trash this. +2 Cards. You are protected from Attacks until the end of your 5th turn after this one.",
    kingdom=False, extra_types=_SPECIAL, expansion="Special",
))
register(action(
    "God Mode", 10, _god_mode,
    "Trash this. You are protected from Attacks for the rest of the game. +3 Actions, +3 Buys, +$5.",
    kingdom=False, extra_types=_SPECIAL, expansion="Special",
))


# ----------------------------------------------------------------- Invisibility Cloak, Midas Touch, Chance Time
def _invisibility_cloak(ctx):
    if not ctx.trash_self():
        return
    ctx.log("INVISIBILITY CLOAK! They can no longer be touched.", "special", 0)
    ctx.make_invisible()


def _midas_touch(ctx):
    if not ctx.trash_self():
        return
    ctx.log("MIDAS TOUCH! Everything they touch this turn turns to gold.", "special", 0)
    ctx.start_midas()


CHANCE_OUTCOMES = (
    "JACKPOT",         # gain 2 Golds
    "COIN SHOWER",     # +$8 and +1 Buy
    "HAND SWAP",       # swap hands with a random other player (skipping protected ones)
    "BOWSER'S REVENGE",  # you lose 2 random cards from your draw pile
    "FRIENDS FOREVER", # every player gains a Silver
    "NEW HANDS",       # everybody discards their hand and draws 5 new cards
)


def _chance_time(ctx):
    if not ctx.trash_self():
        return
    outcome = CHANCE_OUTCOMES[ctx.random_int(len(CHANCE_OUTCOMES))]
    ctx.log(f"CHANCE TIME! The wheel lands on {outcome}!", "special", 0)
    if outcome == "JACKPOT":
        ctx.gain("Gold")
        ctx.gain("Gold")
    elif outcome == "COIN SHOWER":
        ctx.add_coins(8)
        ctx.add_buys(1)
    elif outcome == "HAND SWAP":
        eligible = [p for p in ctx.other_players() if not ctx.is_protected(p)]
        if eligible:
            ctx.swap_hands_with(eligible[ctx.random_int(len(eligible))])
        else:
            ctx.log("Nobody can be swapped with.")
    elif outcome == "BOWSER'S REVENGE":
        ctx.trash_random_from_deck(2)
    elif outcome == "FRIENDS FOREVER":
        for p in ctx.all_players():
            ctx.gain("Silver", player=p)
    else:                                               # NEW HANDS
        for p in ctx.all_players():
            if p == ctx.player or not ctx.is_invisible(p):
                ctx.discard_hand(p)
                ctx.draw(5, player=p)


register(action(
    "Invisibility Cloak", 8, _invisibility_cloak,
    "Trash this. For the rest of the game nothing another player's card does can affect you: Attacks and "
    "Catastrophes skip you, Cataclysm and Masquerade leave you out, Fortnite walls do not apply to you.",
    kingdom=False, extra_types=_SPECIAL, expansion="Special",
))
register(action(
    "Midas Touch", 7, _midas_touch,
    "Trash this. For the rest of this turn every Treasure you play is worth $3, as if it were a Gold.",
    kingdom=False, extra_types=_SPECIAL, expansion="Special",
))
register(action(
    "Chance Time", 4, _chance_time,
    "Trash this. Spin the wheel, one of six outcomes at random: JACKPOT (gain 2 Golds), COIN SHOWER (+$8, +1 Buy), "
    "HAND SWAP (swap hands with a random other player), BOWSER'S REVENGE (you trash 2 random cards from your draw pile), "
    "FRIENDS FOREVER (every player gains a Silver) or NEW HANDS (everybody discards their hand and draws 5).",
    kingdom=False, extra_types=_SPECIAL, expansion="Special",
))

# ----------------------------------------------------------------- Exodia: five pieces, one win
_LIMBS = ("Right Arm of the Forbidden One", "Left Arm of the Forbidden One",
          "Right Leg of the Forbidden One", "Left Leg of the Forbidden One")
_EXODIA_RULE = "holding all five pieces of Exodia in your hand at the same time wins the game on the spot."
register(CardDef(
    "Exodia the Forbidden One", 5, frozenset({CardType.SPECIAL}),
    text="The head. It does nothing when drawn. Picking this card also puts its four limbs in the Supply "
         "(2 of each, $3): " + _EXODIA_RULE,
    kingdom=False, expansion="Special", companions=_LIMBS,
))
for _limb in _LIMBS:
    register(CardDef(
        _limb, 3, frozenset({CardType.SPECIAL}),
        text="A piece of Exodia. It does nothing on its own, " + _EXODIA_RULE,
        kingdom=False, expansion="Special", companion_of="Exodia the Forbidden One",
    ))
