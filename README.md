# Modinion (Python)

**Modinion** (formerly "Dominion (Python)") is a modular, well-tested digital deck-building game in the style of Dominion: a rules engine that is independent of any UI, a registry of
card definitions (the whole 2nd-edition **Base set** and **Intrigue expansion**, plus optional
"Catastrophe" and "Special" house-rule cards), simple bots, a text-mode game, and an **online multiplayer web game**
(FastAPI + WebSockets + a browser page).

The engine is pure standard library. The web layer needs `fastapi` and `uvicorn` (installed with the
`web` extra). Requires Python 3.10 or newer. (The game is called Modinion, but the Python package and the
server command keep the name `dominion` so that existing installs and deployments keep working.)

**To put it online, see [docs/DEPLOY.md](docs/DEPLOY.md).**  The current version is **update 11**
(see the [update history](#update-history)).

## Quick start

```bash
cd dominion
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"            # installs the package + pytest + web dependencies

pytest                             # run the test suite

dominion-web                                # play online/locally: open http://localhost:8000

python -m dominion                          # you vs. a Big Money bot (text mode)
python -m dominion --humans 2 --bots 0      # hot-seat, two humans
python -m dominion --humans 0 --bots 2      # watch two bots play
python -m dominion --seed 42 --kingdom Village Smithy Market Cellar Chapel
```

Without installing, you can also run `PYTHONPATH=src python -m dominion` and `pytest` (pytest is
configured to find `src/`).

In the text UI, type the number of the option you want. When a card asks you to pick cards (e.g.
Cellar), type their positions separated by spaces, or press Enter to pick none. `q` quits.

## Layout

```
dominion/
├── pyproject.toml
├── README.md                   this file (the card tables in it are generated from the code)
├── docs/ARCHITECTURE.md        design, protocol, rules decisions
├── docs/DEPLOY.md              step-by-step Render deployment
├── tools/
│   ├── gen_card_tables.py      builds the card tables in this README from the card definitions
│   └── mutation_check.py       deliberate-bug check: breaks the code on purpose, tests must notice
├── src/dominion/
│   ├── cards/                  CARD DEFINITIONS (data + effect functions)
│   │   ├── base.py             CardDef, CardType, helpers (action, victory, action_victory, ...)
│   │   ├── registry.py         name -> CardDef, card sets (expansions)
│   │   ├── basic.py            Copper/Silver/Gold, Estate/Duchy/Province, Curse
│   │   ├── kingdom.py          the 26 Base-set Kingdom cards
│   │   ├── intrigue.py         the 26 Intrigue Kingdom cards
│   │   ├── catastrophe.py      the 7 optional Catastrophe cards (they hurt)
│   │   └── special.py          the optional Special cards (they help) and Exodia's pieces
│   ├── engine/                 GAME ENGINE (no I/O, no UI)
│   │   ├── actions.py          Action types a player can submit (incl. Resign, EndGame, Cheat) + Decision
│   │   ├── state.py            GameState, PlayerState (zones, protection), structured GameLog
│   │   ├── rules.py            validate() + legal_actions()  <- legality lives here
│   │   ├── game.py             Game.apply(): executes validated actions
│   │   ├── effects.py          EffectContext: the only API cards may use
│   │   ├── zones.py            draw / gain / discard / trash / swap primitives
│   │   ├── costs.py            card_cost(): printed cost minus this turn's reduction (Bridge)
│   │   ├── setup.py            GameConfig, new_game(), replay()
│   │   ├── scoring.py          VP totals, VP breakdown, end-of-game stats, winners
│   │   ├── views.py            build_view(): what ONE player may see (hides other hands)
│   │   └── codec.py            Action <-> JSON for the network
│   ├── ai/bots.py              RandomBot, BigMoneyBot, run_game()
│   ├── ui/cli.py               text-mode prototype
│   └── web/                    ONLINE PLAY
│       ├── rooms.py            rooms, seats, lobby, bots, per-player broadcast, my games, resign/end/delete, cheats
│       ├── server.py           FastAPI app: page, /healthz, /ws WebSocket
│       └── static/index.html   the browser client (plain HTML/CSS/JS, no libraries)
└── tests/                      496 tests: rules, every card, endgame, self-play, CLI, rooms,
                                live server, real browser (jsdom), README-in-sync check
```

## How the pieces fit

```
   UI / Bot / (future) network client
        │  submits Action(s)               ▲ reads GameState, legal_actions()
        ▼                                  │
   Game.apply(player, action) ──► rules.validate()  (rejects with a reason)
        │ if legal
        ▼
   mutates GameState via zones.* and card effects (through EffectContext)
```

The UI and bots **never decide what is legal**. The menu in the CLI is built from
`game.legal_actions()`, bots pick from that same list, and anything else they submit is rejected by
`validate()` without changing the game.

## Using the engine directly

```python
from dominion.engine import GameConfig, new_game, PlayAction, PlayAllTreasures, Buy, EndPhase

game = new_game(GameConfig(["Ann", "Bo"], kingdom=["Village", "Smithy"], seed=1))
game.legal_actions()                  # [EndPhase()] (no Actions in the opening hand)
game.apply(0, EndPhase())             # to the Buy phase
game.apply(0, PlayAllTreasures())
game.apply(0, Buy("Silver"))          # raises IllegalActionError if not allowed
game.apply(0, EndPhase())             # ends the turn; cleanup is automatic

# a random Kingdom drawn only from the Intrigue set, with two Catastrophe cards in the game
GameConfig(["Ann", "Bo", "Cy"], expansions=["Intrigue"], catastrophes=["The Snap", "Grand Swap"])
```

## Adding a card

Define it and register it. The engine does not change.

```python
# simple card
from dominion.cards import action, register
register(action("Moat-lite", 2, lambda ctx: ctx.draw(2), "+2 Cards."))

# card that asks the player something: a generator that yields a Decision
def _harbinger_lite(ctx):
    ctx.draw(1)
    ctx.add_actions(1)
    options = tuple(set(ctx.hand))
    if options:
        (card,) = yield ctx.choose("Discard a card to gain a Silver.", options)
        ctx.discard(card)
        ctx.gain("Silver")

register(action("Harbinger-lite", 3, _harbinger_lite, "+1 Card +1 Action. Discard a card, gain a Silver."))
```

Options of a decision may be card names **or plain text** ("+1 Card", "Yes"); the page draws text
options as buttons. Effects may only use `EffectContext`: `draw`, `gain`, `gain_from_trash`,
`discard`, `trash`, `trash_from_supply`, `add_actions/buys/coins`, `reduce_costs`, `gainable`
(`exact=True` for "costing exactly"), `cost_of`, `choose`, `attack()` (Reactions; skips protected
players), `protect` / `protect_forever`, `give_coins`, `log`, and more
(see `engine/effects.py`). Other `CardDef` options: `action_victory(...)` / `treasure_victory(...)` for
double-type cards, `expansion="..."` to put a card in a card set, and `on_attack=` for a Reaction
with an effect (Diplomat). `tests/test_extensibility.py` adds cards without touching the engine.

## Cards

All card tables below are **generated from the code** by `python tools/gen_card_tables.py --write`,
and a test fails if this section is out of date.

<!-- CARD TABLES START (generated by tools/gen_card_tables.py: do not edit by hand) -->

### All 173 cards at a glance

* **Basic cards (10):** Copper ($0), Silver ($3), Gold ($6), Platinum ($9), Potion ($4), Estate ($2), Duchy ($5), Province ($8), Colony ($11), Curse ($0)
* **Base Kingdom cards (26):** Cellar ($2), Chapel ($2), Moat ($2), Harbinger ($3), Merchant ($3), Vassal ($3), Village ($3), Workshop ($3), Bureaucrat ($4), Gardens ($4), Militia ($4), Moneylender ($4), Poacher ($4), Remodel ($4), Smithy ($4), Throne Room ($4), Bandit ($5), Council Room ($5), Festival ($5), Laboratory ($5), Library ($5), Market ($5), Mine ($5), Sentry ($5), Witch ($5), Artisan ($6)
* **Alchemy Kingdom cards (12):** Transmute ($0), Vineyard ($0), Apothecary ($2), Herbalist ($2), Scrying Pool ($2), University ($2), Alchemist ($3), Familiar ($3), Philosopher's Stone ($3), Golem ($4), Apprentice ($5), Possession ($6)
* **Cornucopia Kingdom cards (26):** Candlestick Maker ($2), Hamlet ($2), Stonemason ($2), Doctor ($3), Fortune Teller ($3), Masterpiece ($3), Menagerie ($3), Advisor ($4), Farming Village ($4), Herald ($4), Horse Traders ($4), Plaza ($4), Remake ($4), Taxman ($4), Tournament ($4), Young Witch ($4), Baker ($5), Butcher ($5), Harvest ($5), Horn of Plenty ($5), Hunting Party ($5), Jester ($5), Journeyman ($5), Merchant Guild ($5), Soothsayer ($5), Fairgrounds ($6)
* **Intrigue Kingdom cards (26):** Courtyard ($2), Lurker ($2), Pawn ($2), Masquerade ($3), Shanty Town ($3), Steward ($3), Swindler ($3), Wishing Well ($3), Baron ($4), Bridge ($4), Conspirator ($4), Diplomat ($4), Ironworks ($4), Mill ($4), Mining Village ($4), Secret Passage ($4), Courtier ($5), Duke ($5), Minion ($5), Patrol ($5), Replace ($5), Torturer ($5), Trading Post ($5), Upgrade ($5), Harem ($6), Nobles ($6)
* **Prosperity Kingdom cards (25):** Loan ($3), Trade Route ($3), Watchtower ($3), Bishop ($4), Monument ($4), Quarry ($4), Talisman ($4), Workers' Village ($4), City ($5), Contraband ($5), Counting House ($5), Mint ($5), Mountebank ($5), Rabble ($5), Royal Seal ($5), Vault ($5), Venture ($5), Goons ($6), Grand Market ($6), Hoard ($6), Bank ($7), Expand ($7), Forge ($7), King's Court ($7), Peddler ($8)
* **Seaside Kingdom cards (26):** Embargo ($2), Haven ($2), Lighthouse ($2), Native Village ($2), Pearl Diver ($2), Ambassador ($3), Fishing Village ($3), Lookout ($3), Smugglers ($3), Warehouse ($3), Caravan ($4), Cutpurse ($4), Island ($4), Navigator ($4), Pirate Ship ($4), Salvager ($4), Sea Hag ($4), Treasure Map ($4), Bazaar ($5), Explorer ($5), Ghost Ship ($5), Merchant Ship ($5), Outpost ($5), Tactician ($5), Treasury ($5), Wharf ($5)
* **Catastrophe cards (11):** Fortnite ($6), Monopoly ($6), Roofie ($6), Grand Theft Auto ($7), The Purge ($7), Fate Swap ($8), Time Stop ($8), Cataclysm ($9), Grand Swap ($9), Long Night ($10), The Snap ($10)
* **Special cards (7):** Chance Time ($4), Exodia the Forbidden One ($5), Rosebud ($5), Guardian Angel ($6), Midas Touch ($7), Invisibility Cloak ($8), God Mode ($10)
* **Exodia pieces (4):** Left Arm of the Forbidden One ($3), Left Leg of the Forbidden One ($3), Right Arm of the Forbidden One ($3), Right Leg of the Forbidden One ($3)

### Basic cards

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Copper** | $0 | Treasure | $1 |
| **Silver** | $3 | Treasure | $2 |
| **Gold** | $6 | Treasure | $3 |
| **Platinum** | $9 | Treasure | $5 |
| **Potion** | $4 | Treasure | 1 Potion |
| **Estate** | $2 | Victory | 1 VP |
| **Duchy** | $5 | Victory | 3 VP |
| **Province** | $8 | Victory | 6 VP |
| **Colony** | $11 | Victory | 10 VP |
| **Curse** | $0 | Curse | -1 VP |

### Base Kingdom cards (26)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Cellar** | $2 | Action | +1 Action. Discard any number of cards, then draw that many. |
| **Chapel** | $2 | Action | Trash up to 4 cards from your hand. |
| **Moat** | $2 | Action - Reaction | +2 Cards. When another player plays an Attack, you may first reveal this from your hand, to be unaffected by it. |
| **Harbinger** | $3 | Action | +1 Card, +1 Action. Look through your discard pile. You may put a card from it onto your deck. |
| **Merchant** | $3 | Action | +1 Card, +1 Action. The first time you play a Silver this turn, +$1. |
| **Vassal** | $3 | Action | +$2. Discard the top card of your deck. If it's an Action card, you may play it. |
| **Village** | $3 | Action | +1 Card, +2 Actions. |
| **Workshop** | $3 | Action | Gain a card costing up to $4. |
| **Bureaucrat** | $4 | Action - Attack | Gain a Silver onto your deck. Each other player reveals a Victory card from their hand and puts it onto their deck (or reveals a hand with no Victory cards). |
| **Gardens** | $4 | Victory | Worth 1 VP per 10 cards you have (rounded down). |
| **Militia** | $4 | Action - Attack | +$2. Each other player discards down to 3 cards in hand. |
| **Moneylender** | $4 | Action | You may trash a Copper from your hand for +$3. |
| **Poacher** | $4 | Action | +1 Card, +1 Action, +$1. Discard a card per empty Supply pile. |
| **Remodel** | $4 | Action | Trash a card from your hand. Gain a card costing up to $2 more. |
| **Smithy** | $4 | Action | +3 Cards. |
| **Throne Room** | $4 | Action | You may play an Action card from your hand twice. |
| **Bandit** | $5 | Action - Attack | Gain a Gold. Each other player reveals the top 2 cards of their deck, trashes a revealed Treasure other than Copper, and discards the rest. |
| **Council Room** | $5 | Action | +4 Cards, +1 Buy. Each other player draws a card. |
| **Festival** | $5 | Action | +2 Actions, +1 Buy, +$2. |
| **Laboratory** | $5 | Action | +2 Cards, +1 Action. |
| **Library** | $5 | Action | Draw until you have 7 cards in hand, skipping any Action cards you choose to; set those aside, discarding them afterwards. |
| **Market** | $5 | Action | +1 Card, +1 Action, +1 Buy, +$1. |
| **Mine** | $5 | Action | You may trash a Treasure from your hand. Gain a Treasure to your hand costing up to $3 more. |
| **Sentry** | $5 | Action | +1 Card, +1 Action. Look at the top 2 cards of your deck. Trash and/or discard any number of them. Put the rest back on top in any order. |
| **Witch** | $5 | Action - Attack | +2 Cards. Each other player gains a Curse. |
| **Artisan** | $6 | Action | Gain a card to your hand costing up to $5. Put a card from your hand onto your deck. |

### Alchemy Kingdom cards (12)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Transmute** | $0 | Action | Trash a card from your hand. If it is an Action card, gain a Duchy; a Treasure card, gain a Transmute; a Victory card, gain a Gold. |
| **Vineyard** | $0 | Victory | Worth 1 VP per 3 Action cards you have (round down). |
| **Apothecary** | $2 | Action | +1 Card, +1 Action. Reveal the top 4 cards of your deck. Put the Coppers and Potions into your hand. Put the other cards back in any order. |
| **Herbalist** | $2 | Action | +1 Buy, +$1. When you discard this from play, you may put one of your Treasures from play onto your deck. |
| **Scrying Pool** | $2 | Action - Attack | +1 Action. Each player (including you) reveals the top card of their deck and either discards it or puts it back, your choice. Then reveal cards from your deck until you reveal one that is not an Action. Put all of your revealed cards into your hand. |
| **University** | $2 | Action | +2 Actions. You may gain an Action card costing up to $5. |
| **Alchemist** | $3 | Action | +2 Cards, +1 Action. When you discard this from play, you may put this onto your deck if you have a Potion in play. |
| **Familiar** | $3 | Action - Attack | +1 Card, +1 Action. Each other player gains a Curse. |
| **Philosopher's Stone** | $3 | Treasure | When you play this, count your draw pile and discard pile together: it is worth $1 per 5 cards (round down). |
| **Golem** | $4 | Action | Reveal cards from your deck until you reveal 2 Action cards other than Golem. Discard the other cards, then play the Action cards in either order. |
| **Apprentice** | $5 | Action | +1 Action. Trash a card from your hand. +1 Card per $1 it costs. +2 Cards if it has a Potion in its cost. |
| **Possession** | $6 | Action | The player to your left takes an extra turn after this one, in which you can see all cards they can and make all decisions for them. Any cards they would gain on that turn, you gain instead; any cards of theirs that are trashed are set aside and returned to their discard pile at end of turn. |

### Cornucopia Kingdom cards (26)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Candlestick Maker** | $2 | Action | +1 Action, +1 Buy, +1 Coffer. |
| **Hamlet** | $2 | Action | +1 Card, +1 Action. You may discard a card for +1 Action. You may discard a card for +1 Buy. |
| **Stonemason** | $2 | Action | Trash a card from your hand. Gain 2 cards each costing less than it. When you buy this, you may overpay for it. If you do, gain 2 Action cards each costing the amount you overpaid. |
| **Doctor** | $3 | Action | Name a card. Reveal the top 3 cards of your deck. Trash the matches. Put the rest back in any order. When you buy this, you may overpay for it. For each $1 you overpaid, look at the top card of your deck; trash it, discard it, or put it back. |
| **Fortune Teller** | $3 | Action - Attack | +$2. Each other player reveals cards from the top of their deck until they reveal a Victory card or a Curse. They put it on top and discard the rest. |
| **Masterpiece** | $3 | Treasure | $1. When you buy this, you may overpay for it. For each $1 you overpaid, gain a Silver. |
| **Menagerie** | $3 | Action | +1 Action. Reveal your hand. If the revealed cards all have different names, +3 Cards. Otherwise, +1 Card. |
| **Advisor** | $4 | Action | +1 Action. Reveal the top 3 cards of your deck. The player to your left chooses one of them. Discard that card and put the rest into your hand. |
| **Farming Village** | $4 | Action | +2 Actions. Reveal cards from the top of your deck until you reveal an Action or Treasure card. Put that card into your hand and discard the rest. |
| **Herald** | $4 | Action | +1 Card, +1 Action. Reveal the top card of your deck. If it is an Action, play it. When you buy this, you may overpay for it. For each $1 you overpaid, look through your discard pile and put a card from it onto your deck. |
| **Horse Traders** | $4 | Action - Reaction | +1 Buy, +$3. Discard 2 cards. When another player plays an Attack card, you may first set this aside from your hand. If you do, then at the start of your next turn, +1 Card and return this to your hand. |
| **Plaza** | $4 | Action | +1 Card, +2 Actions. You may discard a Treasure card for +1 Coffer. |
| **Remake** | $4 | Action | Do this twice: Trash a card from your hand, then gain a card costing exactly $1 more than it. |
| **Taxman** | $4 | Action - Attack | You may trash a Treasure from your hand. Each other player with 5 or more cards in hand discards a copy of it (or reveals a hand without it). Gain a Treasure onto your deck costing up to $3 more than it. |
| **Tournament** | $4 | Action | +1 Action. Each player may reveal a Province from their hand. If you do, discard it and gain a Prize (from the Prize pile) or a Duchy, onto your deck. If no one else does, +1 Card and +$1. |
| **Young Witch** | $4 | Action - Attack | +2 Cards. Discard 2 cards. Each other player may reveal a Bane card from their hand; if they don't, they gain a Curse. Setup: Add an extra Kingdom card pile costing $2 or $3 to the Supply. Cards from that pile are Bane cards. |
| **Baker** | $5 | Action | +1 Card, +1 Action, +1 Coffer. Setup: Each player takes 1 Coffer. |
| **Butcher** | $5 | Action | +2 Coffers. You may trash a card from your hand. If you do, remove any number of tokens from your Coffers and gain a card costing up to the cost of the trashed card plus $1 per token removed. |
| **Harvest** | $5 | Action | Reveal the top 4 cards of your deck, then discard them. +$1 per differently named card revealed. |
| **Horn of Plenty** | $5 | Treasure | $0. When you play this, gain a card costing up to $1 per differently named card you have in play (counting this). If it's a Victory card, trash this. |
| **Hunting Party** | $5 | Action | +1 Card, +1 Action. Reveal your hand. Reveal cards from your deck until you reveal a card that isn't a duplicate of one in your hand. Put it into your hand and discard the rest. |
| **Jester** | $5 | Action - Attack | +$2. Each other player discards the top card of their deck. If it's a Victory card, they gain a Curse. Otherwise, they gain a copy of the discarded card or you do, your choice. |
| **Journeyman** | $5 | Action | Name a card. Reveal cards from your deck until you reveal 3 cards that are not the named card. Put those cards into your hand and discard the rest. |
| **Merchant Guild** | $5 | Action | +1 Buy, +$1. While this is in play, when you buy a card, +1 Coffer. |
| **Soothsayer** | $5 | Action - Attack | Gain a Gold. Each other player gains a Curse, and if they did, draws a card. |
| **Fairgrounds** | $6 | Victory | Worth 2 VP for every 5 differently named cards in your deck (round down). |

### Intrigue Kingdom cards (26)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Courtyard** | $2 | Action | +3 Cards. Put a card from your hand onto your deck. |
| **Lurker** | $2 | Action | +1 Action. Choose one: trash an Action card from the Supply, or gain an Action card from the trash. |
| **Pawn** | $2 | Action | Choose two different: +1 Card; +1 Action; +1 Buy; +$1. |
| **Masquerade** | $3 | Action | +2 Cards. Each player with any cards in hand passes one to the player on their left, all at once. Then you may trash a card from your hand. |
| **Shanty Town** | $3 | Action | +2 Actions. Reveal your hand. If you have no Action cards in hand, +2 Cards. |
| **Steward** | $3 | Action | Choose one: +2 Cards; or +$2; or trash 2 cards from your hand. |
| **Swindler** | $3 | Action - Attack | +$2. Each other player trashes the top card of their deck and gains a card with the same cost that you choose. |
| **Wishing Well** | $3 | Action | +1 Card, +1 Action. Name a card, then reveal the top card of your deck. If it is the card you named, put it into your hand. |
| **Baron** | $4 | Action | +1 Buy. You may discard an Estate for +$4. If you don't, gain an Estate. |
| **Bridge** | $4 | Action | +1 Buy, +$1. This turn, cards (everywhere) cost $1 less, but not less than $0. |
| **Conspirator** | $4 | Action | +$2. If you have played 3 or more Actions this turn (counting this), +1 Card and +1 Action. |
| **Diplomat** | $4 | Action - Reaction | +2 Cards. If you have 5 or fewer cards in hand, +2 Actions. Reaction: when another player plays an Attack, you may first reveal this from a hand of 5 or more cards: draw 2 cards, then discard 3. |
| **Ironworks** | $4 | Action | Gain a card costing up to $4. If it is an Action, +1 Action. If it is a Treasure, +$1. If it is a Victory card, +1 Card. |
| **Mill** | $4 | Action - Victory | 1 VP. +1 Card, +1 Action. You may discard 2 cards for +$2. |
| **Mining Village** | $4 | Action | +1 Card, +2 Actions. You may trash this for +$2. |
| **Secret Passage** | $4 | Action | +2 Cards, +1 Action. Take a card from your hand and put it into your deck: on top, 2nd to 5th from the top, in the middle or on the bottom. |
| **Courtier** | $5 | Action | Reveal a card from your hand. For each type it has (Action, Attack, Reaction, Treasure, Victory, Curse), choose a different one: +1 Action; +1 Buy; +$3; gain a Gold. |
| **Duke** | $5 | Victory | Worth 1 VP per Duchy you have. |
| **Minion** | $5 | Action - Attack | +1 Action. Choose one: +$2; or discard your hand, +4 Cards, and each other player with 5 or more cards in hand discards their hand and draws 4 cards. |
| **Patrol** | $5 | Action | +3 Cards. Reveal the top 4 cards of your deck. Put the Victory cards and Curses into your hand. Put the rest back in any order. |
| **Replace** | $5 | Action - Attack | Trash a card from your hand. Gain a card costing up to $2 more. If it is an Action or Treasure, put it onto your deck. If it is a Victory card, each other player gains a Curse. |
| **Torturer** | $5 | Action - Attack | +3 Cards. Each other player chooses: discard 2 cards, or gain a Curse into their hand. |
| **Trading Post** | $5 | Action | Trash 2 cards from your hand. If you did, gain a Silver to your hand. |
| **Upgrade** | $5 | Action | +1 Card, +1 Action. Trash a card from your hand. Gain a card costing exactly $1 more than it. |
| **Harem** | $6 | Treasure - Victory | $2 and 2 VP. A Treasure and a Victory card. |
| **Nobles** | $6 | Action - Victory | 2 VP. Choose one: +3 Cards; or +2 Actions. |

### Prosperity Kingdom cards (25)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Loan** | $3 | Treasure | $1. When you play this, reveal cards from your deck until you reveal a Treasure. Discard it or trash it. Discard the other cards. |
| **Trade Route** | $3 | Action | +1 Buy, +$1 per Coin token on the Trade Route mat. Trash a card from your hand. Setup: Add a token to the mat the first time a card is gained from each Victory pile. |
| **Watchtower** | $3 | Action - Reaction | Draw until you have 6 cards in your hand. When you gain a card, you may reveal this from your hand, to either trash that card or put it on top of your deck. |
| **Bishop** | $4 | Action | +$1, +1 VP token. Trash a card from your hand. +1 VP token per $2 it costs (round down). Each other player may trash a card from their hand. |
| **Monument** | $4 | Action | +$2, +1 VP token. |
| **Quarry** | $4 | Treasure | $1. While this is in play, Action cards cost $2 less, but not less than $0. |
| **Talisman** | $4 | Treasure | $1. While this is in play, when you buy a non-Victory card costing $4 or less, gain a copy of it. |
| **Workers' Village** | $4 | Action | +1 Card, +2 Actions, +1 Buy. |
| **City** | $5 | Action | +1 Card, +2 Actions. If there are one or more empty Supply piles, +1 Card. If there are two or more, +$1 and +1 Buy. |
| **Contraband** | $5 | Treasure | $3, +1 Buy. When you play this, the player to your left names a card. You can't buy that card this turn. |
| **Counting House** | $5 | Action | Look through your discard pile, reveal any number of Copper cards from it, and put them into your hand. |
| **Mint** | $5 | Action | You may reveal a Treasure card from your hand. Gain a copy of it. When you buy this, trash all Treasures you have in play. |
| **Mountebank** | $5 | Action - Attack | +$2. Each other player may discard a Curse. If they don't, they gain a Curse and a Copper. |
| **Rabble** | $5 | Action - Attack | +3 Cards. Each other player reveals the top 3 cards of their deck, discards the revealed Actions and Treasures, and puts the rest back on top in any order they choose. |
| **Royal Seal** | $5 | Treasure | $2. While this is in play, when you gain a card, you may put that card on top of your deck. |
| **Vault** | $5 | Action | +2 Cards. Discard any number of cards for +$1 each. Each other player may discard 2 cards, to draw a card. |
| **Venture** | $5 | Treasure | $1. When you play this, reveal cards from your deck until you reveal a Treasure. Discard the other cards. Play that Treasure. |
| **Goons** | $6 | Action - Attack | +1 Buy, +$2. Each other player discards down to 3 cards in hand. While this is in play, when you buy a card, +1 VP token. |
| **Grand Market** | $6 | Action | +1 Card, +1 Action, +1 Buy, +$2. You can't buy this if you have any Copper in play. |
| **Hoard** | $6 | Treasure | $2. While this is in play, when you buy a Victory card, gain a Gold. |
| **Bank** | $7 | Treasure | When you play this, it's worth $1 per Treasure card you have in play (counting this). |
| **Expand** | $7 | Action | Trash a card from your hand. Gain a card costing up to $3 more than it. |
| **Forge** | $7 | Action | Trash any number of cards from your hand. Gain a card with cost exactly equal to the total cost in coins of the trashed cards. |
| **King's Court** | $7 | Action | You may play an Action card from your hand three times. |
| **Peddler** | $8 | Action | +1 Card, +1 Action, +$1. During your Buy phase, this costs $2 less per Action card you have in play, but not less than $0. |

### Seaside Kingdom cards (26)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Embargo** | $2 | Action | +$2. Trash this card. Put an Embargo token on top of a Supply pile. When a player buys a card, he gains a Curse card per Embargo token on that pile. |
| **Haven** | $2 | Action - Duration | +1 Card, +1 Action. Set aside a card from your hand face down. At the start of your next turn, put it into your hand. |
| **Lighthouse** | $2 | Action - Duration | +1 Action. Now and at the start of your next turn: +$1. While this is in play, when another player plays an Attack card, it doesn't affect you. |
| **Native Village** | $2 | Action | +2 Actions. Choose one: Set aside the top card of your deck face down on your Native Village mat; or put all the cards from your mat into your hand. |
| **Pearl Diver** | $2 | Action | +1 Card, +1 Action. Look at the bottom card of your deck. You may put it on top. |
| **Ambassador** | $3 | Action - Attack | Reveal a card from your hand. Return up to 2 copies of it from your hand to the Supply. Then each other player gains a copy of it. |
| **Fishing Village** | $3 | Action - Duration | +2 Actions, +$1. At the start of your next turn: +1 Action, +$1. |
| **Lookout** | $3 | Action | +1 Action. Look at the top 3 cards of your deck. Trash one of them. Discard one of them. Put the other one on top of your deck. |
| **Smugglers** | $3 | Action | Gain a copy of a card costing up to $6 that the player to your right gained on their last turn. |
| **Warehouse** | $3 | Action | +3 Cards, +1 Action. Discard 3 cards. |
| **Caravan** | $4 | Action - Duration | +1 Card, +1 Action. At the start of your next turn, +1 Card. |
| **Cutpurse** | $4 | Action - Attack | +$2. Each other player discards a Copper card (or reveals a hand with no Copper). |
| **Island** | $4 | Action - Victory | Put this and a card from your hand onto your Island mat. Worth 2 VP. |
| **Navigator** | $4 | Action | +$2. Look at the top 5 cards of your deck. Either discard all of them, or put them back on top of your deck in any order. |
| **Pirate Ship** | $4 | Action - Attack | Choose one: Each other player reveals the top 2 cards of their deck, trashes a revealed Treasure that you choose, discards the rest, and if anyone trashed a Treasure you take a Coin token; or, +$1 per Coin token you have. |
| **Salvager** | $4 | Action | +1 Buy. Trash a card from your hand. +$ equal to its cost. |
| **Sea Hag** | $4 | Action - Attack | Each other player discards the top card of his deck, then gains a Curse card, putting it on top of his deck. |
| **Treasure Map** | $4 | Action | Trash this and another copy of Treasure Map from your hand. If you do, gain 4 Gold cards, putting them on top of your deck. |
| **Bazaar** | $5 | Action | +1 Card, +2 Actions, +$1. |
| **Explorer** | $5 | Action | You may reveal a Province card from your hand. If you do, gain a Gold card, putting it into your hand. Otherwise, gain a Silver card, putting it into your hand. |
| **Ghost Ship** | $5 | Action - Attack | +2 Cards. Each other player with 4 or more cards in hand puts cards from his hand on top of his deck until he has 3 cards in his hand. |
| **Merchant Ship** | $5 | Action - Duration | Now and at the start of your next turn: +$2. |
| **Outpost** | $5 | Action - Duration | You only draw 3 cards (instead of 5) in this turn's Clean-up phase. Take an extra turn after this one. This can't cause you to take more than two consecutive turns. |
| **Tactician** | $5 | Action - Duration | If you have at least one card in hand: discard your hand, and at the start of your next turn, +5 Cards, +1 Buy, and +1 Action. |
| **Treasury** | $5 | Action | +1 Card, +1 Action, +$1. When you discard this from play, if you didn't buy a Victory card this turn, you may put this on top of your deck. |
| **Wharf** | $5 | Action - Duration | Now and at the start of your next turn: +2 Cards, +1 Buy. |

### Catastrophe cards (11, optional house rule: they hurt)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Fortnite** | $6 | Action - Catastrophe | Trash this. Choose up to 3 Supply piles (not Catastrophe or Special piles) and build walls around them: nobody else can buy or gain cards from those piles until the start of your next turn. |
| **Monopoly** | $6 | Action - Attack - Catastrophe | Trash this. Each other player pays you: they put a Gold from their hand into your discard pile (a Silver if they have no Gold, nothing if they have neither). |
| **Roofie** | $6 | Action - Attack - Catastrophe | Trash this. Each other player is blinded until the end of their next turn: they can see what type each card is (Action, Treasure, Victory...), but not its name, cost or text. |
| **Grand Theft Auto** | $7 | Action - Attack - Catastrophe | Trash this. Choose 1 or 2 other players: you steal a random card from each one's hand into your discard pile. |
| **The Purge** | $7 | Action - Attack - Catastrophe | Trash this. Every player, you included, discards half (rounded down) of their draw pile, chosen at random. Only protection (not Moat) spares the other players; you are never spared. |
| **Fate Swap** | $8 | Action - Attack - Catastrophe | Trash this. Choose another player. You each take the top X cards of your draw piles (X = the smaller pile, at most 7) and put them on top of the other's draw pile. |
| **Time Stop** | $8 | Action - Attack - Catastrophe | Trash this. The next player skips their next turn. (Nobody can be skipped twice in a row.) |
| **Cataclysm** | $9 | Action - Catastrophe | Trash this. Pool every player's deck, hand and discard pile, shuffle, and deal them back so everyone has as many cards as before; the others draw a new hand of 5. Your hand is part of the pool. You may not buy cards this turn. |
| **Grand Swap** | $9 | Action - Attack - Catastrophe | Trash this. Choose another player. You trade your whole draw piles and discard piles with them (hands stay put) - except Victory and Curse cards, which stay with their owner. Both draw piles are reshuffled. Risky: you get whatever they had, good or bad. |
| **Long Night** | $10 | Action - Attack - Catastrophe | Trash this. The next two players each skip their next turn. (3+ players.) |
| **The Snap** | $10 | Action - Attack - Catastrophe | Trash this. Every player, you included, trashes half (rounded down) of the cards in their draw pile, hand and discard pile, chosen at random. Only protection (not Moat) spares the other players; you are never spared. |

### Special cards (7, optional house rule: they help)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Chance Time** | $4 | Action - Special | Trash this. Spin the wheel, one of six outcomes at random: JACKPOT (gain 2 Golds), COIN SHOWER (+$8, +1 Buy), HAND SWAP (swap hands with a random other player), BOWSER'S REVENGE (you trash 2 random cards from your draw pile), FRIENDS FOREVER (every player gains a Silver) or NEW HANDS (everybody discards their hand and draws 5). |
| **Exodia the Forbidden One** | $5 | Special | The head. It does nothing when drawn. Picking this card also puts its four limbs in the Supply (2 of each, $3): holding all five pieces of Exodia in your hand at the same time wins the game on the spot. |
| **Rosebud** | $5 | Action - Special | Trash this. Choose any player, you included: they get +$12. If you choose someone else, they get it at the start of their next turn. |
| **Guardian Angel** | $6 | Action - Special | Trash this. +2 Cards. You are protected from Attacks until the end of your 5th turn after this one. |
| **Midas Touch** | $7 | Action - Special | Trash this. For the rest of this turn every Treasure you play is worth $3, as if it were a Gold. |
| **Invisibility Cloak** | $8 | Action - Special | Trash this. For the rest of the game nothing another player's card does can affect you: Attacks and Catastrophes skip you, Cataclysm and Masquerade leave you out, Fortnite walls do not apply to you. |
| **God Mode** | $10 | Action - Special | Trash this. You are protected from Attacks for the rest of the game. +3 Actions, +3 Buys, +$5. |

### Exodia pieces (4, they arrive together with Exodia the Forbidden One)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Left Arm of the Forbidden One** | $3 | Special | A piece of Exodia. It does nothing on its own, holding all five pieces of Exodia in your hand at the same time wins the game on the spot. |
| **Left Leg of the Forbidden One** | $3 | Special | A piece of Exodia. It does nothing on its own, holding all five pieces of Exodia in your hand at the same time wins the game on the spot. |
| **Right Arm of the Forbidden One** | $3 | Special | A piece of Exodia. It does nothing on its own, holding all five pieces of Exodia in your hand at the same time wins the game on the spot. |
| **Right Leg of the Forbidden One** | $3 | Special | A piece of Exodia. It does nothing on its own, holding all five pieces of Exodia in your hand at the same time wins the game on the spot. |

<!-- CARD TABLES END -->

### Rules decisions for the cards

* **Nobles, Mill** are Action-Victory cards, **Harem** is a Treasure-Victory card; their piles are
  Victory-sized (8 cards in a 2-player game, 12 otherwise) and they count for anything that checks
  for Victory cards (Bureaucrat, Patrol, Ironworks, Replace).
* **Bridge** lowers *every* cost for the turn: Supply prices, what you may buy, what Workshop,
  Ironworks, Replace, Swindler and Upgrade may gain, and the prices shown on the page. Costs never go
  below $0 and several Bridges add up. Upgrade and Swindler use the reduced costs.
* **Conspirator** counts every Action *play* this turn, so a Throne Room'd Action counts twice.
* **Diplomat**: when another player plays an Attack and you hold 5+ cards, you are asked whether to
  reveal it (draw 2, discard 3). That happens before the Moat question, so you may use both.
* **Minion** and **Replace** ask other players for Reactions only when their Attack part is actually
  used (Minion's "attack" option; Replace gaining a Victory card).
* **Masquerade** passes to the next player in turn order, everybody chooses before any card moves,
  and the cards passed are not named in the log.
* **Torturer**: a player with fewer than 2 cards in hand must take the Curse; if the Curses have run
  out, they must discard 2.
* **Swindler**: the attacker picks the replacement, which must cost exactly the trashed card;
  if nothing costs that much, nothing is gained.
* **Wishing Well** names a card from this game's piles. **Courtier** offers at most 4 effects.
* **Secret Passage** offers these spots in your deck: on top, 2nd to 5th from the top, the middle,
  the bottom (instead of every possible position, which would be hundreds of buttons).
* **Exodia**: the four limbs are not selectable on their own; picking the head puts all five piles (2 copies of
  each) in the game. The pieces do nothing when drawn and only the head and limbs in your *hand* count, not
  cards in your deck, discard pile or in play. If you also hold other cards, it still wins: the rule is "all five
  pieces are in your hand".
* **Invisibility Cloak** is stronger than protection: besides skipping Attacks, the wearer is left out of a
  Cataclysm (they keep their cards unless they played it themselves), Masquerade passes skip over them, Fortnite
  walls do not apply to them, and Chance Time's Hand Swap and New Hands leave them alone.
* **Fortnite** cannot wall piles that are empty, already walled, or Catastrophe/Special piles. The builder is never
  blocked, and the walls come down when the builder's next turn starts (even if that turn is skipped). Swindler,
  Witch's Curses and every other gain respect the walls.
* **Lurker** never touches Catastrophe cards (neither trashing them from the Supply nor taking a
  used one back out of the trash).
* **Mining Village** trashed under a Throne Room only pays out once.

## Catastrophe and Special cards (optional house rules)

Eighteen game-changing cards, off by default: eleven **Catastrophes** that hurt other players and seven
**Special** cards that help one player (Exodia counts as one pick but brings four more pieces). In the lobby the host can tick **as many of them as they like**
(there is no limit); they get their own supply row. They are deliberately fenced in so they are dramatic but hard to abuse (the
effect of each card is in the generated table above):

* **2 copies** of each, $7 to $10, and an empty Catastrophe pile never counts towards the
  three-empty-piles game ending.
* **Single use**: the card trashes itself when played (a Throne Room can't repeat it).
* **Moat does not work** against a Catastrophe, and neither does Diplomat or any other Reaction: nobody is even
  asked. Only protection (Guardian Angel, God Mode, the Invisibility Cloak) skips a player. Ordinary Attacks
  (Militia, Witch, Swindler...) can still be blocked by Moat.
* Nobody can be **skipped twice in a row**; skipped turns still count as turns for the tiebreak.
* **Fate Swap** swaps equal numbers of draw-pile cards. **Grand Swap** is the risky one: it trades
  whole draw and discard piles, but Victory and Curse cards stay with their owner, hands are not
  touched, and both draw piles are reshuffled. **The Snap** and **The Purge** always hit the player
  who played them as well; protection spares the others, never you. **Cataclysm** also costs you your buys.
* **Special cards** play by the same fences (2 copies, single use, never end the game):
  **Rosebud** gives $12 to any player (you, or someone else at the start of their next turn),
  **Guardian Angel** protects you from Attacks until the end of your 5th turn after the one you played it
  in (it also draws 2 cards), and **God Mode** protects you for the rest of the game and gives you a big turn
  (+3 Actions, +3 Buys, +$5).
* **The eight newest** (update 9), in one line each:
  **Exodia the Forbidden One** (a head and four limbs: all five in your hand at the same time win the game
  on the spot, checked after every action, even on someone else's turn), **Invisibility Cloak** (for the rest of
  the game nothing another player's card does can affect you), **Midas Touch** (every Treasure you play this turn
  is worth $3), **Fortnite** (wall off up to 3 piles: nobody else can buy or gain from them until your next turn
  starts), **Monopoly** (every other player pays you a Gold from their hand, else a Silver), **Grand Theft Auto**
  (steal a random card from 1 or 2 other players), **Roofie** (other players are blinded for their next turn: the page shows only the
  type of each card, not its name, cost or text, and shuffles the order of their hand and of the Supply) and
  **Chance Time** (spin a wheel with six outcomes: Jackpot, Coin Shower, Hand Swap, Bowser's Revenge, Friends
  Forever, New Hands). All of them use the seeded game RNG, so replays and undo reproduce them exactly.
* **Protection** means every Attack skips you: no Moat or Diplomat question is asked and nothing happens to
  you. It covers the Catastrophes that target players (Time Stop, Long Night, Fate Swap, Grand Swap, The
  Snap, The Purge, though The Snap and The Purge always hit the player who played them). It does not stop
  things that are not Attacks (Cataclysm, Council Room, Masquerade). The player panels show who is protected.
* **Open book**: every card that moves cards between players writes a "who got what" summary
  into the log (cards gained, cards lost, new deck size), so nobody has to guess what changed.

## Online features

* **Card sets**: the host ticks *Base* and/or *Intrigue*; a random Kingdom is drawn from the ticked
  sets, or the host ticks exactly the (up to 10) cards wanted.
* **Dark theme** (default) and a light theme; sound effects with a volume slider; animations that can
  be turned off. Settings are remembered in the browser (Settings button, top right).
* **Auto-play Treasures** (ON by default; tick box above your hand): when you reach the Buy phase,
  every Treasure in your hand is played for you. **Auto-skip Action phase** (ON by default) jumps to
  the Buy phase when you have nothing to play. Neither is applied again to a position an Undo has just
  restored.
* **Layout** (update 10): the page never scrolls. Players are on the left, the Supply, "In play" and your hand
  in the middle, and the log, the chat and the turn bar (status, resources, buttons) at the bottom right under
  the chat; the turn bar can be collapsed with the arrow. Card effects that need an answer (Throne Room, Lurker,
  Pawn, Torturer...), undo votes and the final results open as a **pop-up in the middle of the screen**; a
  question has a *Look at the table* button that hides it for a moment, and the header has a *Results* button
  to bring the results back after closing them. The lobby has the players and settings on the left and the card
  pickers on the right. Card sizes adapt to the screen height.
* **Card help**: the small "i" on every card, a right-click, Shift+click, or the *Card help* button in
  the header (then any click shows the card's full text). Cards you cannot act on explain themselves
  when clicked.
* **Trash button** in the header lists everything that has been trashed. Following the rulebook, the trash is
  the only pile you may look through: there is no way to look through your draw pile or your discard pile, and
  no count of your discard pile. You see how many cards are left in your draw pile (you may count that), and
  every player's discard pile shows only its top card. A few cards break the rule on purpose: Harbinger's
  question lists the cards in your discard pile, and Sentry, Library and similar cards show you the cards
  they say they show you.
* **Leave** is in the header (lobby and game).
* **Log**: every line starts with its turn number, each turn gets a header, effects are indented
  under the card that caused them, colours show plays / buys / gains / trashing / discards / reveals /
  catastrophes, and card and player names stand out. "Who got what" summaries are teal and indented.
  Sounds and banners announce your turn, an Attack that needs your answer, and catastrophes.
* **End-of-game stats** for every player: VP, turns, cards bought, cards gained any way, final deck,
  and a VP breakdown (which cards your points came from, Gardens and Duke included).
* Everyone's victory points are shown on the player panels (a deliberate choice: it reveals each
  player's total, not which cards they own).
* Room chat (lobby and game; 300 characters, 5 messages per 10 seconds per player). The last 100 lines
  are replayed when you reconnect.
* **Undo with consent**: "Request undo" takes back your own most recent action, **even after your turn has
  ended**: with turns P1, P2, P3, P1 may ask during P2's turn or P3's turn, and the game goes back to the
  moment just before P1's last action (everything the others did since is undone too, and the request says
  how many actions that is). Every other human must agree (60 seconds, any "no" cancels, play is paused
  meanwhile). Everyone gets exactly the same cards back. You cannot ask while another human is disconnected;
  if you are playing only against bots, undo happens straight away. Undo is unavailable once the game is over.
* A disconnected player is waited for, never replaced by a bot.
* **Auto-end turn** (ON by default; tick box in the controls): once you are in the Buy phase with no Buys
  left, your turn ends by itself after a short pause (so you see your last purchase). It never fires for a
  position an Undo has just restored, and note that a turn that has ended cannot be undone.
* **Game menu** (header): **Resign** (any player, any time: the game ends for everybody, you cannot win, the
  best of the others wins), **End game now** (host only: the current scores are final, nobody resigned) and
  **Delete game** (host only: removes the game for everybody). Each asks for confirmation. Bots never resign.
* **Your games**: the home page lists every game this browser sits in (code, status, players, "your turn"),
  with **Rejoin/View**, **Delete** (host) and **Forget**. Leaving a game keeps it in the list; the list asks
  the server about each game with your secret seat token, so nobody sees games they are not part of.
* **Blind mode** (Roofie): while blinded you see each card's colour and type but "???" for its name, cost and text,
  card help refuses, hand cards are not stacked, and the order of your hand and of the Supply is shuffled on every
  update so the order cannot give names away. Your own sight comes back when your next turn ends.
* **Walls** show on the piles (red dashed outline and the builder's name), and the Buy button for a walled pile is
  simply not offered to the others.
* **Cheat codes** (host's choice in the lobby, **off by default**): on your own turn type one of these phrases in
  the chat to get **+100 coins** (`show me the money`), **+100 actions** (`power overwhelming`) or **+100 buys**
  (`greed is good`). Case and spacing do not matter, the phrase is never shown as chat, every use is announced
  in the log, it only works on your own turn with no question pending, and it can be undone like any action.
  With cheats off the same words are ordinary chat.

### Online play in one minute

```bash
dominion-web      # http://localhost:8000
```
Create a room, share the 4-letter code, optionally add bots and pick card sets / Kingdom cards /
Catastrophe cards, then start. Every browser tab is its own player. Clients only ever receive their
own view of the game (own hand, opponents' card *counts*), the server takes player identity from the
seat (never from the message), and every move is validated by the same engine as in the text game.

## Testing

```bash
pytest                                  # everything (the browser tests are skipped without Node)
cd tests/browser && npm install         # one-time: enables the real-page (jsdom) tests
python tools/gen_card_tables.py --check # README card tables match the code
python tools/mutation_check.py          # slow: ~98 deliberate bugs, every one must be caught
```

* Layout (optional, downloads a headless Chromium of about 60 MB): `cd tests/browser/layout && npm install`.
  `test_the_page_itself_never_scrolls_in_a_real_browser` renders the lobby, a crowded 4-player game, two kinds of
  question and the results at 1280x720, 1366x768, 1536x864 and 1920x1080 and fails if the page scrolls, if the
  turn bar leaves the bottom right, or if a pop-up is off-centre. Without it, the page is still checked
  structurally (jsdom) and by static tests of the stylesheet.
* Rules and cards: every Base and Intrigue card has its own tests, including Throne Room, Moat and
  empty-pile edge cases; random self-play checks that no card is ever created or lost.
* Browser tests drive the real page: a live server with two humans and a bot (lobby, card sets,
  undo, auto-play, card help, trash, settings, a full game, rematch, stats), a reconnect test, and a
  test that feeds the page real engine views (text choices, Bridge prices, catastrophes, sounds).
* `tools/mutation_check.py` edits the source on purpose (for example "Bridge can go below $0",
  "Grand Swap moves Curses", "Leave button hidden during the game"), runs the tests, and fails if any
  deliberate bug goes unnoticed. It restores every file afterwards, even when interrupted.

### Undo
The game is deterministic, so undo is a **replay**: rebuild the game from its seed and
`history[:target]`, where `target` is the requester's most recent action, from any turn (it may be several turns back; an "End turn" can be undone too).
Later actions by other players (for example an opponent's answer to your Militia) are rolled back
with it, and the prompt says how many. Every other *human* must approve; bots are not asked, and if
nobody needs to be asked it happens at once. While a vote is open, game actions are refused and bots
wait. A request times out after 60 s. Because the shuffle is fixed by the seed, an undo can never
re-roll a draw. Undo is unavailable once the game is over.

## Update history

Updates 1-5 are listed as they were delivered earlier in this project; updates 6, 7 and 8 are the newest.

### Update 1: the engine and a text game
* A modular engine: card registry, per-player zones (draw pile, hand, discard, in play), central game
  state, rules validation (`validate` / `legal_actions`), extensible card effects.
* The first 11 Kingdom cards (Cellar, Chapel, Village, Workshop, Smithy, Remodel, Moneylender, Market,
  Festival, Laboratory, Gardens), a text-mode game and a Big Money bot, automated tests.

### Update 2: online play
* FastAPI + WebSocket server, rooms with 4-letter codes, lobby, bots, per-player views that hide other
  hands, the first browser page, reconnecting, and the Render deployment guide.
* Deployment fixes: a mixed-up `__init__.py` from the drag-and-drop upload, and the full start command
  needed on Render.

### Update 3: more cards, Attacks and Reactions
* About ten more non-attack cards (Harbinger, Merchant, Vassal, Poacher, Throne Room, Mine, Library,
  Sentry, Council Room, Artisan).
* Attacks and Reactions (Moat, Militia, Witch, Bandit) and the reaction mechanism (`ctx.attack()`).
* A simulated playtest, and a random starting player online.

### Update 4: finishing the base set, chat and undo
* Bureaucrat: all 26 Base-set Kingdom cards.
* Everyone's VP is public. A dropped player is never replaced by a bot (the game waits).
* Room chat (lobby and game), and undo that needs everyone's consent.

### Update 5: Catastrophe cards
* An optional house rule with Time Stop, Long Night, Fate Swap and Cataclysm: 2 copies each, single
  use, Moat works, never ends the game by running out.

### Update 6: the Intrigue expansion, three new Catastrophes
* **All 26 Intrigue cards**: Courtyard, Lurker, Pawn, Masquerade, Shanty Town, Steward, Swindler,
  Wishing Well, Baron, Bridge, Conspirator, Diplomat, Ironworks, Mill, Mining Village, Secret Passage,
  Courtier, Duke, Minion, Patrol, Replace, Torturer, Trading Post, Upgrade, Harem, Nobles.
* New rule types in the engine: cards with two types (Action-Victory, Treasure-Victory), cost reduction
  for a turn (Bridge), "choose two" and text options, every player answering at once (Masquerade),
  Reactions with an effect (Diplomat), counting Actions played (Conspirator), trashing from the Supply
  and gaining from the trash (Lurker), scoring by what you own (Duke).
* Card sets: the lobby lets the host choose Base and/or Intrigue for random Kingdoms.
* **Grand Swap**, **The Snap** (trash half of everyone's cards at random) and **The Purge** (discard
  half of every draw pile at random): the Catastrophe row now has seven cards.
* "Who got what" summaries for every card that moves cards between players (Cataclysm included).
* Card definitions now record their card set, and a bot bug with text options was fixed.

### Update 7: a new page, a readable log, statistics
* The page was rewritten: dark theme (default) and light theme, cleaner cards with a coloured type
  stripe and a cost badge, a two-column layout (table on the left, log and chat on the right).
* Settings (theme, sound, volume, animations), sound effects and animations for card plays, buying,
  your turn, Attacks, catastrophes and the end of the game.
* **Auto-play Treasures** (default ON) and Auto-skip Action phase, both undo-safe.
* **Card help** (the "i", right-click, Shift+click, or Card-help mode), **Trash** viewer, **My discard
  pile** and **All my cards** viewers, **Leave** moved to the header.
* A structured log: turn headers and turn numbers, indentation, colours, highlighted card and player
  names, kinds the page can style.
* **End-of-game statistics** per player: VP breakdown, cards bought and gained, final deck, turns.
* The card tables in this README are generated from the code, and a test keeps them in sync.
* A deliberate-bug checker (`tools/mutation_check.py`) with 35 mutations, all caught (23 more were added in update 8 and 24 in update 9 and 16 in update 10: 98 in all).

### Update 8: game management, Special cards, cheat codes
* **Auto-end turn** when you have no Buys left (default ON, undo-safe).
* **Game menu**: Resign, End game now (host), Delete game (host), each with a confirmation; a resigned
  player cannot win; the game-over screen says why the game ended.
* **Your games** on the home page: see every game you are in, rejoin or view it, delete it (host) or forget it.
* **Rosebud** (a lot of money for any player), **Guardian Angel** (protection from Attacks for 5 turns) and
  **God Mode** (protection for the rest of the game, plus a big turn): the new **Special** card type, with
  protection shown on the player panels. The README card tables now show every card, with an
  "all cards at a glance" list.
* **Cheat codes** typed in the chat (+100 coins / actions / buys), switched on by the host in the lobby
  (off by default) and announced in the log.
* Fixed: Catastrophe cards were drawn with dark text on a dark background in the page.
* New engine actions `Resign`, `EndGame` and `Cheat` are part of the game history, so they replay and undo
  correctly; bots never choose them.

### Update 9: eight more house-rule cards, deployment fix
* **Exodia the Forbidden One** (five pieces, all in hand = instant win), **Invisibility Cloak**, **Midas Touch**,
  **Fortnite**, **Monopoly**, **Grand Theft Auto**, **Roofie** and **Chance Time**. Eighteen house-rule cards now.
* New engine pieces: companion cards (a card that brings extra piles), walls on supply piles, blindness,
  invisibility, "treat Treasures as Gold" for a turn, a win condition checked after every action, and stealing /
  paying between hands. The page got a blind mode and wall markers.
* The top-level `dominion/__init__.py` now re-exports the card API (`from .cards.base import ...`), and a test
  checks that each of the six `__init__.py` files has its own content: this guards against the mixed-up upload
  that broke an earlier deployment (see docs/DEPLOY.md).

### Update 10: rulebook visibility, undo across turns, a new layout, Modinion
* **Rulebook visibility.** Removed the "All my cards" and "My discard pile" buttons; the server no longer sends
  your whole collection or your discard pile at all. You see the size of your draw pile (counting it is allowed),
  never the size of a discard pile, and every discard pile shows only its top card. The trash stays public.
  Cards such as Harbinger still show you your discard pile when they ask you a question.
* **Undo after your turn has ended**: your most recent action can be taken back from any turn, with everything
  that happened since (other players' whole turns included). Everyone else must still agree.
* **Catastrophe cards ignore Moat** (and Diplomat): only protection (Guardian Angel, God Mode, the Invisibility
  Cloak) skips a player. Ordinary Attacks are unchanged.
* **No limit** on how many Catastrophe / Special cards a game may have (it used to be 2).
* The lobby label is now "Exodia the Forbidden One ($5)".
* **New screen layout** (see Online features): no page scrolling, players on the left, turn bar under the chat
  at the bottom right, pop-ups in the middle for questions and results.
* **Renamed to Modinion** in the page, the README and the docs (the Python package keeps the name `dominion`).
* Tests: the stylesheet and layout are checked in a real headless Chromium (optional, see Testing).

### Update 11: the Alchemy expansion
* **All 12 Alchemy cards**: Transmute, Vineyard, Herbalist, Apothecary, Scrying Pool, University, Alchemist, Familiar,
  Philosopher's Stone, Golem, Apprentice, Possession. Alchemy is a third card set in the lobby.
* **Potions**: a new second cost. Cards such as Golem cost coins *and* a Potion; the **Potion** Treasure gives one. The
  Potion pile (16) joins the Supply when a Kingdom card needs one. Effects like Workshop never offer cards that cost a Potion.
* **Cleanup can ask a question**: Herbalist (put a Treasure from play on your deck) and Alchemist (put it on your deck
  if you have a Potion in play). Alchemists are resolved before Herbalists.
* **Possession**: the player to your left takes an extra turn that you control. You see their hand and answer all their
  questions; cards they would gain go to you (to your discard pile), their trashed cards are set aside and come back at the
  end of the turn. Rules decisions: the extra turn counts as a turn for the possessed player (tiebreak); a Possession played
  during a possessed turn does nothing; an invisible player cannot be possessed; Possession is not an Attack (Moat does not
  stop it); cards stolen or paid to the possessed player by Catastrophe cards are not redirected.
* A coin-limited effect applied to a card that costs a Potion (Remodel, Upgrade...) never gains a Potion card.

## Known limitations

* A dropped player stalls the game until they rejoin (no timer or replace-with-bot button; the other players can Resign or the host can End or Delete the game).
* Free-tier hosting sleeps or restarts, which ends every game; games are not saved.
* Bots never play Action cards (Big Money). Duration cards and other expansions are not implemented.
* Reactions exist as "block an Attack" (Moat) and "reveal for an effect" (Diplomat); Reactions to
  other triggers (Watchtower, Horse Traders) are not implemented.
* `legal_actions` for large optional choices enumerates all multisets (2^n for n cards); fine for a
  hand, but a UI should prefer `validate` for free-form answers (the CLI does).
* No spectators, accounts or replays. The page is built for a desktop browser (no phone layout) and tuned for
  screens from 1280x720 up; on smaller windows the panels scroll inside themselves.

Ideas for later: smarter bots, a replace-with-bot button for dropped players, saving games across
restarts, spectators, more expansions.
