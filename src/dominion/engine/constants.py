"""Rule constants (kept in one place so variants are easy to add)."""

MIN_PLAYERS = 2
MAX_PLAYERS = 4
KINGDOM_SIZE = 10
HAND_SIZE = 5
STARTING_COPPERS = 7
STARTING_ESTATES = 3
EMPTY_PILE_LIMIT = 3   # game ends when this many supply piles are empty
POTION_PILE_SIZE = 16  # the Potion pile (added when a Kingdom card costs a Potion)

# Catastrophe cards (optional house rule): scarce, expensive, single-use
EXODIA_PIECES = (                 # holding all five in your hand at once wins the game on the spot
    "Exodia the Forbidden One", "Right Arm of the Forbidden One", "Left Arm of the Forbidden One",
    "Right Leg of the Forbidden One", "Left Leg of the Forbidden One",
)
CHEAT_AMOUNT = 100             # what a cheat code adds
CHEAT_KINDS = ("coins", "actions", "buys")
# what to type in the chat (when the host allows cheat codes) -> which cheat
CHEAT_PHRASES = {
    "show me the money": "coins",
    "power overwhelming": "actions",
    "greed is good": "buys",
}
CATASTROPHE_PILE_SIZE = 2   # cards per Catastrophe pile, whatever the player count
