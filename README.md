# Modinion (Python)

**Modinion** (formerly "Dominion (Python)") is a modular, well-tested digital deck-building game in the style of Dominion: a rules engine that is independent of any UI, a registry of
card definitions (the whole 2nd-edition **Base set** and **Intrigue expansion**, plus optional
"Catastrophe" and "Special" house-rule cards), simple bots, a text-mode game, and an **online multiplayer web game**
(FastAPI + WebSockets + a browser page).

The engine is pure standard library. The web layer needs `fastapi` and `uvicorn` (installed with the
`web` extra). Requires Python 3.10 or newer. (The game is called Modinion, but the Python package and the
server command keep the name `dominion` so that existing installs and deployments keep working.)

**To put it online, see [docs/DEPLOY.md](docs/DEPLOY.md).**  The current version is **update 25 (Rising Sun)**
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
└── tests/                      690+ tests: rules, every card, endgame, self-play, CLI, rooms,
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

### All 777 cards at a glance

* **Basic cards (10):** Copper ($0), Silver ($3), Gold ($6), Platinum ($9), Potion ($4), Estate ($2), Duchy ($5), Province ($8), Colony ($11), Curse ($0)
* **Base Kingdom cards (26):** Cellar ($2), Chapel ($2), Moat ($2), Harbinger ($3), Merchant ($3), Vassal ($3), Village ($3), Workshop ($3), Bureaucrat ($4), Gardens ($4), Militia ($4), Moneylender ($4), Poacher ($4), Remodel ($4), Smithy ($4), Throne Room ($4), Bandit ($5), Council Room ($5), Festival ($5), Laboratory ($5), Library ($5), Market ($5), Mine ($5), Sentry ($5), Witch ($5), Artisan ($6)
* **Adventures Kingdom cards (29):** Coin of the Realm ($2), Page ($2), Peasant ($2), Ratcatcher ($2), Raze ($2), Amulet ($3), Caravan Guard ($3), Dungeon ($3), Gear ($3), Guide ($3), Duplicate ($4), Magpie ($4), Messenger ($4), Miser ($4), Port ($4), Ranger ($4), Transmogrify ($4), Artificer ($5), Bridge Troll ($5), Distant Lands ($5), Giant ($5), Haunted Woods ($5), Lost City ($5), Relic ($5), Royal Carriage ($5), Storyteller ($5), Swamp Hag ($5), Wine Merchant ($5), Hireling ($6)
* **Alchemy Kingdom cards (12):** Transmute ($0), Vineyard ($0), Apothecary ($2), Herbalist ($2), Scrying Pool ($2), University ($2), Alchemist ($3), Familiar ($3), Philosopher's Stone ($3), Golem ($4), Apprentice ($5), Possession ($6)
* **Allies Kingdom cards (31):** Bauble ($2), Sycophant ($2), Townsfolk ($2), Augurs ($3), Clashes ($3), Forts ($3), Importer ($3), Merchant Camp ($3), Odysseys ($3), Sentinel ($3), Underling ($3), Wizards ($3), Broker ($4), Carpenter ($4), Courier ($4), Innkeeper ($4), Royal Galley ($4), Town ($4), Barbarian ($5), Capital City ($5), Contract ($5), Emissary ($5), Galleria ($5), Guildmaster ($5), Highwayman ($5), Hunter ($5), Modify ($5), Skirmisher ($5), Specialist ($5), Swap ($5), Marquis ($6)
* **Cornucopia & Guilds Kingdom cards (34):** Candlestick Maker ($2), Farrier ($2), Hamlet ($2), Stonemason ($2), Doctor ($3), Fortune Teller ($3), Infirmary ($3), Masterpiece ($3), Menagerie ($3), Shop ($3), Advisor ($4), Farmhands ($4), Farming Village ($4), Herald ($4), Horse Traders ($4), Plaza ($4), Remake ($4), Taxman ($4), Tournament ($4), Young Witch ($4), Baker ($5), Butcher ($5), Carnival ($5), Ferryman ($5), Footpad ($5), Harvest ($5), Horn of Plenty ($5), Hunting Party ($5), Jester ($5), Journeyman ($5), Joust ($5), Merchant Guild ($5), Soothsayer ($5), Fairgrounds ($6)
* **Dark Ages Kingdom cards (35):** Poor House ($1), Beggar ($2), Squire ($2), Vagrant ($2), Forager ($3), Hermit ($3), Market Square ($3), Sage ($3), Storeroom ($3), Urchin ($3), Armory ($4), Death Cart ($4), Feodum ($4), Fortress ($4), Ironmonger ($4), Marauder ($4), Procession ($4), Rats ($4), Scavenger ($4), Wandering Minstrel ($4), Band of Misfits ($5), Bandit Camp ($5), Catacombs ($5), Count ($5), Counterfeit ($5), Cultist ($5), Graverobber ($5), Junk Dealer ($5), Knights ($5), Mystic ($5), Pillage ($5), Rebuild ($5), Rogue ($5), Altar ($6), Hunting Grounds ($6)
* **Empires Kingdom cards (24):** City Quarter ($0), Engineer ($0), Overlord ($0), Royal Blacksmith ($0), Encampment ($2), Patrician ($2), Settlers ($2), Castles ($3), Catapult ($3), Chariot Race ($3), Enchantress ($3), Farmers' Market ($3), Gladiator ($3), Sacrifice ($4), Temple ($4), Villa ($4), Archive ($5), Capital ($5), Charm ($5), Crown ($5), Forum ($5), Groundskeeper ($5), Legionary ($5), Wild Hunt ($5)
* **Hinterlands Kingdom cards (26):** Crossroads ($2), Duchess ($2), Fool's Gold ($2), Develop ($3), Oasis ($3), Oracle ($3), Scheme ($3), Tunnel ($3), Jack of All Trades ($4), Noble Brigand ($4), Nomad Camp ($4), Silk Road ($4), Spice Merchant ($4), Trader ($4), Cache ($5), Cartographer ($5), Embassy ($5), Haggler ($5), Highway ($5), Ill-Gotten Gains ($5), Inn ($5), Mandarin ($5), Margrave ($5), Stables ($5), Border Village ($6), Farmland ($6)
* **Intrigue Kingdom cards (26):** Courtyard ($2), Lurker ($2), Pawn ($2), Masquerade ($3), Shanty Town ($3), Steward ($3), Swindler ($3), Wishing Well ($3), Baron ($4), Bridge ($4), Conspirator ($4), Diplomat ($4), Ironworks ($4), Mill ($4), Mining Village ($4), Secret Passage ($4), Courtier ($5), Duke ($5), Minion ($5), Patrol ($5), Replace ($5), Torturer ($5), Trading Post ($5), Upgrade ($5), Harem ($6), Nobles ($6)
* **Menagerie Kingdom cards (30):** Black Cat ($2), Sleigh ($2), Supplies ($2), Camel Train ($3), Goatherd ($3), Scrap ($3), Sheepdog ($3), Snowy Village ($3), Stockpile ($3), Bounty Hunter ($4), Cardinal ($4), Cavalry ($4), Groom ($4), Hostelry ($4), Village Green ($4), Barge ($5), Coven ($5), Displace ($5), Falconer ($5), Fisherman ($5), Gatekeeper ($5), Hunting Lodge ($5), Kiln ($5), Livery ($5), Mastermind ($5), Paddock ($5), Sanctuary ($5), Destrier ($6), Wayfarer ($6), Animal Fair ($7)
* **Nocturne Kingdom cards (33):** Druid ($2), Faithful Hound ($2), Guardian ($2), Monastery ($2), Pixie ($2), Tracker ($2), Changeling ($3), Fool ($3), Ghost Town ($3), Leprechaun ($3), Night Watchman ($3), Secret Cave ($3), Bard ($4), Blessed Village ($4), Cemetery ($4), Conclave ($4), Devil's Workshop ($4), Exorcist ($4), Necromancer ($4), Shepherd ($4), Skulk ($4), Cobbler ($5), Crypt ($5), Cursed Village ($5), Den of Sin ($5), Idol ($5), Pooka ($5), Sacred Grove ($5), Tormentor ($5), Tragic Hero ($5), Vampire ($5), Werewolf ($5), Raider ($6)
* **Plunder Kingdom cards (40):** Cage ($2), Grotto ($2), Jewelled Egg ($2), Search ($2), Shaman ($2), Secluded Shrine ($3), Siren ($3), Stowaway ($3), Taskmaster ($3), Abundance ($4), Cabin Boy ($4), Crucible ($4), Flagship ($4), Fortune Hunter ($4), Gondola ($4), Harbor Village ($4), Landing Party ($4), Mapmaker ($4), Maroon ($4), Rope ($4), Swamp Shacks ($4), Tools ($4), Buried Treasure ($5), Crew ($5), Cutthroat ($5), Enlarge ($5), Figurine ($5), First Mate ($5), Frigate ($5), Longship ($5), Mining Road ($5), Pendant ($5), Pickaxe ($5), Pilgrim ($5), Quartermaster ($5), Silver Mine ($5), Trickster ($5), Wealthy Village ($5), Sack of Loot ($6), King's Cache ($7)
* **Prosperity Kingdom cards (34):** Anvil ($3), Loan ($3), Trade Route ($3), Watchtower ($3), Bishop ($4), Clerk ($4), Investment ($4), Monument ($4), Quarry ($4), Talisman ($4), Tiara ($4), Workers' Village ($4), Charlatan ($5), City ($5), Collection ($5), Contraband ($5), Counting House ($5), Crystal Ball ($5), Magnate ($5), Mint ($5), Mountebank ($5), Rabble ($5), Royal Seal ($5), Vault ($5), Venture ($5), War Chest ($5), Goons ($6), Grand Market ($6), Hoard ($6), Bank ($7), Expand ($7), Forge ($7), King's Court ($7), Peddler ($8)
* **Renaissance Kingdom cards (25):** Border Guard ($2), Ducat ($2), Lackeys ($2), Acting Troupe ($3), Cargo Ship ($3), Experiment ($3), Improve ($3), Flag Bearer ($4), Hideout ($4), Inventor ($4), Mountain Village ($4), Patron ($4), Priest ($4), Research ($4), Silk Merchant ($4), Old Witch ($5), Recruiter ($5), Scepter ($5), Scholar ($5), Sculptor ($5), Seer ($5), Spices ($5), Swashbuckler ($5), Treasurer ($5), Villain ($5)
* **Rising Sun Kingdom cards (25):** Artist ($0), Daimyo ($0), Mountain Shrine ($0), Fishmonger ($2), Snake Witch ($2), Aristocrat ($3), Craftsman ($3), Riverboat ($3), Root Cellar ($3), Alley ($4), Change ($4), Ninja ($4), Poet ($4), River Shrine ($4), Rustic Village ($4), Gold Mine ($5), Imperial Envoy ($5), Kitsune ($5), Litter ($5), Rice Broker ($5), Ronin ($5), Tanuki ($5), Tea House ($5), Samurai ($6), Rice ($7)
* **Seaside Kingdom cards (26):** Embargo ($2), Haven ($2), Lighthouse ($2), Native Village ($2), Pearl Diver ($2), Ambassador ($3), Fishing Village ($3), Lookout ($3), Smugglers ($3), Warehouse ($3), Caravan ($4), Cutpurse ($4), Island ($4), Navigator ($4), Pirate Ship ($4), Salvager ($4), Sea Hag ($4), Treasure Map ($4), Bazaar ($5), Explorer ($5), Ghost Ship ($5), Merchant Ship ($5), Outpost ($5), Tactician ($5), Treasury ($5), Wharf ($5)
* **Dark Ages supporting cards (21):** Abandoned Mine ($0), Madman ($0), Mercenary ($0), Ruined Library ($0), Ruined Market ($0), Ruined Village ($0), Spoils ($0), Survivors ($0), Hovel ($1), Necropolis ($1), Overgrown Estate ($1), Sir Martin ($4), Dame Anna ($5), Dame Josephine ($5), Dame Molly ($5), Dame Natalie ($5), Dame Sylvia ($5), Sir Bailey ($5), Sir Destry ($5), Sir Michael ($5), Sir Vander ($5)
* **Adventures Traveller upgrade cards (8):** Soldier ($3), Treasure Hunter ($3), Fugitive ($4), Warrior ($4), Disciple ($5), Hero ($5), Champion ($6), Teacher ($6)
* **Adventures Events (20):** Alms ($0), Borrow ($0), Quest ($0), Save ($1), Scouting Party ($2), Travelling Fair ($2), Bonfire ($3), Expedition ($3), Ferry ($3), Plan ($3), Mission ($4), Pilgrimage ($4), Ball ($5), Raid ($5), Seaway ($5), Trade ($5), Lost Arts ($6), Training ($6), Inheritance ($7), Pathfinding ($8)
* **Empires supporting cards (13):** Humble Castle ($3), Crumbling Castle ($4), Rocks ($4), Bustling Village ($5), Emporium ($5), Plunder ($5), Small Castle ($5), Haunted Castle ($6), Opulent Castle ($7), Fortune ($8), Sprawling Castle ($8), Grand Castle ($9), King's Castle ($10)
* **Empires Events (13):** Advance ($0), Annex ($0), Donate ($0), Triumph ($0), Delve ($2), Tax ($2), Banquet ($3), Ritual ($4), Salt the Earth ($4), Wedding ($4), Windfall ($5), Conquest ($6), Dominate ($14)
* **Empires Landmarks (21):** Aqueduct ($0), Arena ($0), Bandit Fort ($0), Basilica ($0), Baths ($0), Battlefield ($0), Colonnade ($0), Defiled Shrine ($0), Fountain ($0), Keep ($0), Labyrinth ($0), Mountain Pass ($0), Museum ($0), Obelisk ($0), Orchard ($0), Palace ($0), Tomb ($0), Tower ($0), Triumphal Arch ($0), Wall ($0), Wolf Den ($0)
* **Renaissance Projects (20):** Cathedral ($3), City Gate ($3), Pageant ($3), Star Chart ($3), Exploration ($4), Fair ($4), Sewers ($4), Silos ($4), Sinister Plot ($4), Academy ($5), Capitalism ($5), Fleet ($5), Guildhall ($5), Piazza ($5), Road Network ($5), Barracks ($6), Crop Rotation ($6), Innovation ($6), Canal ($7), Citadel ($8)
* **Allies cards inside the split piles (24):** Town Crier ($2), Battle Plan ($3), Blacksmith ($3), Herb Gatherer ($3), Old Map ($3), Student ($3), Tent ($3), Acolyte ($4), Archer ($4), Conjurer ($4), Garrison ($4), Miller ($4), Voyage ($4), Elder ($5), Hill Fort ($5), Sorcerer ($5), Sorceress ($5), Sunken Treasure ($5), Warlord ($5), Distant Shore ($6), Lich ($6), Sibyl ($6), Stronghold ($6), Territory ($6)
* **Allies (23):** Architects' Guild ($0), Band of Nomads ($0), Cave Dwellers ($0), Circle of Witches ($0), City-state ($0), Coastal Haven ($0), Crafters' Guild ($0), Desert Guides ($0), Family of Inventors ($0), Fellowship of Scribes ($0), Forest Dwellers ($0), Gang of Pickpockets ($0), Island Folk ($0), League of Bankers ($0), League of Shopkeepers ($0), Market Towns ($0), Mountain Folk ($0), Order of Astrologers ($0), Order of Masons ($0), Peaceful Cult ($0), Plateau Shepherds ($0), Trappers' Lodge ($0), Woodworkers' Guild ($0)
* **Menagerie supporting cards (1):** Horse ($3)
* **Menagerie Events (20):** Delay ($0), Desperation ($0), Gamble ($2), Invest ($2), Pursue ($2), Ride ($2), Toil ($2), Enhance ($3), March ($3), Transport ($3), Banish ($4), Bargain ($4), Seize the Day ($4), Commerce ($5), Demand ($5), Stampede ($5), Reap ($7), Enclave ($8), Alliance ($10), Populate ($10)
* **Menagerie Ways (20):** Way of the Butterfly ($0), Way of the Camel ($0), Way of the Chameleon ($0), Way of the Frog ($0), Way of the Goat ($0), Way of the Horse ($0), Way of the Mole ($0), Way of the Monkey ($0), Way of the Mouse ($0), Way of the Mule ($0), Way of the Otter ($0), Way of the Owl ($0), Way of the Ox ($0), Way of the Pig ($0), Way of the Rat ($0), Way of the Seal ($0), Way of the Sheep ($0), Way of the Squirrel ($0), Way of the Turtle ($0), Way of the Worm ($0)
* **Plunder Loot cards (15):** Amphora ($7), Doubloons ($7), Endless Chalice ($7), Figurehead ($7), Hammer ($7), Insignia ($7), Jewels ($7), Orb ($7), Prize Goat ($7), Puzzle Box ($7), Sextant ($7), Shield ($7), Spell Scroll ($7), Staff ($7), Sword ($7)
* **Plunder Events (15):** Bury ($1), Avoid ($2), Deliver ($2), Peril ($2), Rush ($2), Foray ($3), Journey ($3), Launch ($3), Maelstrom ($3), Mirror ($3), Prepare ($3), Scrounge ($3), Looting ($6), Invasion ($10), Prosper ($10)
* **Plunder Traits (15):** Cheap ($0), Cursed ($0), Fated ($0), Fawning ($0), Friendly ($0), Hasty ($0), Inherited ($0), Inspiring ($0), Nearby ($0), Patient ($0), Pious ($0), Reckless ($0), Rich ($0), Shy ($0), Tireless ($0)
* **Rising Sun Events (10):** Continue ($0), Amass ($2), Asceticism ($2), Credit ($2), Foresight ($2), Kintsugi ($3), Practice ($3), Sea Trade ($4), Receive Tribute ($5), Gather ($7)
* **Rising Sun Prophecies (15):** Approaching Army ($0), Biding Time ($0), Bureaucracy ($0), Divine Wind ($0), Enlightenment ($0), Flourishing Trade ($0), Good Harvest ($0), Great Leader ($0), Growth ($0), Harsh Winter ($0), Kind Emperor ($0), Panic ($0), Progress ($0), Rapid Expansion ($0), Sickness ($0)
* **Nocturne supporting cards (15):** Haunted Mirror ($0), Magic Lamp ($0), Will-o'-Wisp ($0), Wish ($0), Bat ($2), Goat ($2), Imp ($2), Pasture ($2), Pouch ($2), Zombie Apprentice ($3), Zombie Mason ($3), Zombie Spy ($3), Cursed Gold ($4), Ghost ($4), Lucky Coin ($4)
* **Catastrophe cards (11):** Fortnite ($6), Monopoly ($6), Roofie ($6), Grand Theft Auto ($7), The Purge ($7), Fate Swap ($8), Time Stop ($8), Cataclysm ($9), Grand Swap ($9), Long Night ($10), The Snap ($10)
* **Special cards (7):** Chance Time ($4), Exodia the Forbidden One ($5), Rosebud ($5), Guardian Angel ($6), Midas Touch ($7), Invisibility Cloak ($8), God Mode ($10)
* **Exodia pieces (4):** Left Arm of the Forbidden One ($3), Left Leg of the Forbidden One ($3), Right Arm of the Forbidden One ($3), Right Leg of the Forbidden One ($3)
* **Nocturne Boons (12), Hexes (12) and States (5) and Renaissance Artifacts (5):** not cards, listed below

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

### Adventures Kingdom cards (29)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Coin of the Realm** | $2 | Reserve - Treasure | $1. When you play this, put it on your Tavern mat. Call: when you finish playing an Action card, you may call this for +2 Actions. |
| **Page** | $2 | Action - Traveller | +1 Card, +1 Action. When you discard this from play, you may exchange it for a Treasure Hunter. |
| **Peasant** | $2 | Action - Traveller | +1 Buy, +$1. When you discard this from play, you may exchange it for a Soldier. |
| **Ratcatcher** | $2 | Action - Reserve | +1 Card, +1 Action. Put this on your Tavern mat. Call: at the start of your turn, you may call this to trash a card from your hand. |
| **Raze** | $2 | Action | +1 Action. Trash this or a card from your hand. Look at the top cards of your deck equal to the cost in $ of the trashed card. Put one into your hand and discard the rest. |
| **Amulet** | $3 | Action - Duration | Now and at the start of your next turn, choose one: +$1; or trash a card from your hand; or gain a Silver. |
| **Caravan Guard** | $3 | Action - Duration - Reaction | +1 Card, +1 Action. At the start of your next turn, +$1. When another player plays an Attack card, you may first play this from your hand. |
| **Dungeon** | $3 | Action - Duration | +1 Action. Now and at the start of your next turn: +2 Cards, then discard 2 cards. |
| **Gear** | $3 | Action - Duration | +2 Cards. Set aside up to 2 cards from your hand face down. At the start of your next turn, put them into your hand. |
| **Guide** | $3 | Action - Reserve | +1 Card, +1 Action. Put this on your Tavern mat. Call: at the start of your turn, you may call this to discard your hand and draw 5 cards. |
| **Duplicate** | $4 | Action - Reserve | Put this on your Tavern mat. Call: when you gain a card costing up to $6, you may call this to gain a copy of that card. |
| **Magpie** | $4 | Action | +1 Card, +1 Action. Reveal the top card of your deck. If it is a Treasure, put it into your hand. If it is an Action or Victory card, gain a Magpie. |
| **Messenger** | $4 | Action | +1 Buy, +$2. You may put your deck into your discard pile. When this is your first buy of your turn, gain a card costing up to $4, and each other player gains a copy of it. |
| **Miser** | $4 | Action | Choose one: put a Copper from your hand onto your Tavern mat; or +$1 per Copper on your Tavern mat. |
| **Port** | $4 | Action | +1 Card, +2 Actions. When you buy this, gain another Port. |
| **Ranger** | $4 | Action | +1 Buy. Turn your Journey token over (it starts face up). If it is face up, +5 Cards. |
| **Transmogrify** | $4 | Action - Reserve | +1 Action. Put this on your Tavern mat. Call: at the start of your turn, you may call this to trash a card from your hand and gain a card costing up to $1 more into your hand. |
| **Artificer** | $5 | Action | +1 Card, +1 Action, +$1. Discard any number of cards. You may gain a card costing exactly $1 per card discarded, putting it onto your deck. |
| **Bridge Troll** | $5 | Action - Attack - Duration | Each other player takes their -$1 token. Now and at the start of your next turn: +1 Buy. While this is in play, cards cost $1 less on your turn. |
| **Distant Lands** | $5 | Action - Reserve - Victory | Put this on your Tavern mat. Worth 4 VP if this is on your Tavern mat at the end of the game (otherwise worth 0 VP). |
| **Giant** | $5 | Action - Attack | Turn your Journey token over (it starts face up). If it is face down, +$1. If it is face up, +$5 and each other player reveals the top card of their deck; if it costs $3 to $6 they trash it, otherwise they discard it and gain a Curse. |
| **Haunted Woods** | $5 | Action - Attack - Duration | At the start of your next turn, +3 Cards. Until then, when any other player buys a card, they put their hand onto their deck in any order. |
| **Lost City** | $5 | Action | +2 Cards, +2 Actions. When you gain this, each other player draws a card. |
| **Relic** | $5 | Attack - Treasure | $2. When you play this, each other player puts their -1 Card token on their deck. |
| **Royal Carriage** | $5 | Action - Reserve | +1 Action. Put this on your Tavern mat. Call: when you finish playing an Action card, if it is still in play, you may call this to replay that Action. |
| **Storyteller** | $5 | Action | +1 Action. Play up to 3 Treasures from your hand. Pay all of your $ and draw a card per $ you paid. |
| **Swamp Hag** | $5 | Action - Attack - Duration | At the start of your next turn, +$3. Until then, when any other player buys a card, they gain a Curse. |
| **Wine Merchant** | $5 | Action - Reserve | +$4, +1 Buy. Put this on your Tavern mat. Call: at the end of your Buy phase, if you have at least $2 unspent, you may discard this from your Tavern mat. |
| **Hireling** | $6 | Action - Duration | At the start of each of your turns for the rest of the game: +1 Card. (This stays in play.) |

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

### Allies Kingdom cards (31)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Bauble** | $2 | Liaison - Treasure | Choose two different options: +1 Buy; +$1; +1 Favor; this turn, when you gain a card, you may put it onto your deck. |
| **Sycophant** | $2 | Action - Liaison | +1 Action. Discard 3 cards. If you discarded at least one, +$3. \| When you gain or trash this, +2 Favors. |
| **Townsfolk** | $2 | Action - Townsfolk | This pile starts the game with 4 copies each of Town Crier, Blacksmith, Miller, and Elder, in that order. Only the top card can be gained or bought. (Rotating moves the top card, with its copies, to the bottom.) |
| **Augurs** | $3 | Action - Augur | This pile starts the game with 4 copies each of Herb Gatherer, Acolyte, Sorceress, and Sibyl, in that order. Only the top card can be gained or bought. (Rotating moves the top card, with its copies, to the bottom.) |
| **Clashes** | $3 | Action - Clash | This pile starts the game with 4 copies each of Battle Plan, Archer, Warlord, and Territory, in that order. Only the top card can be gained or bought. (Rotating moves the top card, with its copies, to the bottom.) |
| **Forts** | $3 | Action - Fort | This pile starts the game with 4 copies each of Tent, Garrison, Hill Fort, and Stronghold, in that order. Only the top card can be gained or bought. (Rotating moves the top card, with its copies, to the bottom.) |
| **Importer** | $3 | Action - Duration - Liaison | At the start of your next turn, gain a card costing up to $5. \| Setup: Each player gets +4 Favors. |
| **Merchant Camp** | $3 | Action | +2 Actions, +$1. When you discard this from play, you may put it onto your deck. |
| **Odysseys** | $3 | Action - Odyssey | This pile starts the game with 4 copies each of Old Map, Voyage, Sunken Treasure, and Distant Shore, in that order. Only the top card can be gained or bought. (Rotating moves the top card, with its copies, to the bottom.) |
| **Sentinel** | $3 | Action | Look at the top 5 cards of your deck. Trash up to 2 of them. Put the rest back in any order. |
| **Underling** | $3 | Action - Liaison | +1 Card, +1 Action, +1 Favor. |
| **Wizards** | $3 | Action - Wizard | This pile starts the game with 4 copies each of Student, Conjurer, Sorcerer, and Lich, in that order. Only the top card can be gained or bought. (Rotating moves the top card, with its copies, to the bottom.) |
| **Broker** | $4 | Action - Liaison | Trash a card from your hand and choose one: +1 Card per $1 it costs; or +1 Action per $1 it costs; or +$1 per $1 it costs; or +1 Favor per $1 it costs. |
| **Carpenter** | $4 | Action | If no Supply piles are empty, +1 Action and gain a card costing up to $4. Otherwise, trash a card from your hand and gain a card costing up to $2 more than it. |
| **Courier** | $4 | Action | +$1. Discard the top card of your deck. Look through your discard pile; you may play an Action or Treasure from it. |
| **Innkeeper** | $4 | Action | +1 Action. Choose one: +1 Card; or +3 Cards, discard 3 cards; or +5 Cards, discard 6 cards. |
| **Royal Galley** | $4 | Action - Duration | +1 Card. You may play a non-Duration Action card from your hand. Set it aside; if you did, at the start of your next turn play it. |
| **Town** | $4 | Action | Choose one: +1 Card and +2 Actions; or +1 Buy and +$2. |
| **Barbarian** | $5 | Action - Attack | +$2. Each other player trashes the top card of their deck. If it costs $3 or more they gain a cheaper card that shares a type with it; otherwise they gain a Curse. |
| **Capital City** | $5 | Action | +1 Card, +2 Actions. You may discard 2 cards for +$2. You may pay $2 for +2 Cards. |
| **Contract** | $5 | Duration - Liaison - Treasure | $2. +1 Favor. You may set aside an Action from your hand to play it at the start of your next turn. |
| **Emissary** | $5 | Action - Liaison | +3 Cards. If this made you shuffle (at least one card), +1 Action and +2 Favors. |
| **Galleria** | $5 | Action | +$3. This turn, when you gain a card costing $3 or $4, +1 Buy. |
| **Guildmaster** | $5 | Action - Liaison | +$3. This turn, when you gain a card, +1 Favor. |
| **Highwayman** | $5 | Action - Attack - Duration | At the start of your next turn, discard this from play and +3 Cards. Until then, the first Treasure each other player plays each turn does nothing. |
| **Hunter** | $5 | Action | +1 Action. Reveal the top 3 cards of your deck. From those cards, put an Action, a Treasure, and a Victory card into your hand. Discard the rest. |
| **Modify** | $5 | Action | Trash a card from your hand. Choose one: +1 Card and +1 Action; or gain a card costing up to $2 more than the trashed card. |
| **Skirmisher** | $5 | Action - Attack | +1 Card, +1 Action, +$1. This turn, when you gain an Attack card, each other player discards down to 3 cards in hand. |
| **Specialist** | $5 | Action | You may play an Action or Treasure from your hand. Choose one: play it again; or gain a copy of it. |
| **Swap** | $5 | Action | +1 Card, +1 Action. You may return an Action card from your hand to its pile, to gain to your hand a different Action card costing up to $5. |
| **Marquis** | $6 | Action | +1 Buy. +1 Card per card in your hand. Discard down to 10 cards in hand. |

### Cornucopia & Guilds Kingdom cards (34)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Candlestick Maker** | $2 | Action | +1 Action, +1 Buy, +1 Coffers. |
| **Farrier** | $2 | Action | +1 Card, +1 Action, +1 Buy. Overpay: +1 Card at the end of this turn per $1 you overpaid. |
| **Hamlet** | $2 | Action | +1 Card, +1 Action. You may discard a card for +1 Action. You may discard a card for +1 Buy. |
| **Stonemason** | $2 | Action | Trash a card from your hand. Gain 2 cards each costing less than it. Overpay: gain 2 Action cards each costing exactly the amount you overpaid. |
| **Doctor** | $3 | Action | Name a card. Reveal the top 3 cards of your deck. Trash the matches. Put the rest back on top in any order. Overpay: for each $1 you overpaid, look at the top card of your deck; trash it, discard it or put it back. |
| **Fortune Teller** | $3 | Action - Attack | +$2. Each other player reveals cards from the top of their deck until they reveal a Victory or Curse card. They put it on top and discard the rest. |
| **Infirmary** | $3 | Action | +1 Card. You may trash a card from your hand. Overpay: play this once per $1 you overpaid. |
| **Masterpiece** | $3 | Treasure | $1. Overpay: when you buy this, gain a Silver per $1 you overpaid. |
| **Menagerie** | $3 | Action | +1 Action. Reveal your hand. If there are no duplicate cards in it, +3 Cards. Otherwise, +1 Card. |
| **Shop** | $3 | Action | +1 Card, +$1. You may play an Action card from your hand that you don't have a copy of in play. |
| **Advisor** | $4 | Action | +1 Action. Reveal the top 3 cards of your deck. The player to your left chooses one of them. Discard that card and put the rest into your hand. |
| **Farmhands** | $4 | Action | +1 Card, +2 Actions. When you gain this, you may set aside an Action or Treasure card from your hand. At the start of your next turn, play it. |
| **Farming Village** | $4 | Action | +2 Actions. Reveal cards from your deck until you reveal an Action or Treasure. Put it into your hand and discard the other cards. |
| **Herald** | $4 | Action | +1 Card, +1 Action. Reveal the top card of your deck. If it's an Action, play it. Overpay: for each $1 you overpaid, put a card from your discard pile onto your deck. |
| **Horse Traders** | $4 | Action - Reaction | +1 Buy, +$3. Discard 2 cards. When another player plays an Attack card, you may set this aside from your hand. At the start of your next turn, +1 Card and return this to your hand. |
| **Plaza** | $4 | Action | +1 Card, +2 Actions. You may discard a Treasure for +1 Coffers. |
| **Remake** | $4 | Action | Do this twice: trash a card from your hand, then gain a card costing exactly $1 more than the trashed card. |
| **Taxman** | $4 | Action - Attack | You may trash a Treasure from your hand. Each other player with 5 or more cards in hand discards a copy of it (or reveals a hand without it). Gain a Treasure costing up to $3 more than the trashed one onto your deck. |
| **Tournament** | $4 | Action | +1 Action. Each player may reveal a Province from their hand. If you do, discard it and gain a Prize (from the Prize pile) or a Duchy onto your deck. If no other player does, +1 Card and +$1. |
| **Young Witch** | $4 | Action - Attack | +2 Cards. Discard 2 cards. Each other player may reveal a Bane card from their hand; if they don't, they gain a Curse. (Setup: add an extra Kingdom pile costing $2 or $3 as the Bane.) |
| **Baker** | $5 | Action | +1 Card, +1 Action, +1 Coffers. Setup: each player takes +1 Coffers. |
| **Butcher** | $5 | Action | +2 Coffers. You may trash a card from your hand and remove any number of Coffers tokens. Gain a card costing up to the trashed card's cost plus the tokens you removed. |
| **Carnival** | $5 | Action | Reveal the top 4 cards of your deck. Put a copy of each differently named card into your hand and discard the rest. |
| **Ferryman** | $5 | Action | +2 Cards, +1 Action. Discard a card. When you gain this, gain a card from the Ferryman pile. (Setup: add an extra pile of a card costing $3 or $4, outside the Supply.) |
| **Footpad** | $5 | Action - Attack | +2 Coffers. Each other player discards down to 3 cards in hand. In games using this, when you gain a card in an Action phase, +1 Card. |
| **Harvest** | $5 | Action | Reveal the top 4 cards of your deck, then discard them. +$1 per differently named card revealed. |
| **Horn of Plenty** | $5 | Treasure | Gain a card costing up to $1 per differently named card you have in play (counting this). If it's a Victory card, trash this. |
| **Hunting Party** | $5 | Action | +1 Card, +1 Action. Reveal your hand. Reveal cards from your deck until you reveal one that isn't a copy of a card in your hand. Put it into your hand and discard the rest. |
| **Jester** | $5 | Action - Attack | +$2. Each other player discards the top card of their deck. If it's a Victory card they gain a Curse. Otherwise they gain a copy of the discarded card or you do, your choice. |
| **Journeyman** | $5 | Action | Name a card. Reveal cards from your deck until you reveal 3 cards that are not the named card. Put those into your hand and discard the rest. |
| **Joust** | $5 | Action | +1 Card, +1 Action, +$1. You may set aside a Province from your hand to gain a Reward to your hand. Discard the Province at the end of the turn. (Setup: the Rewards are not in the Supply.) |
| **Merchant Guild** | $5 | Action | +1 Buy, +$1. At the end of your Buy phase this turn, +1 Coffers per card you gained during it. |
| **Soothsayer** | $5 | Action - Attack | Gain a Gold. Each other player gains a Curse. Each player who did draws a card. |
| **Fairgrounds** | $6 | Victory | Worth 2 VP per 5 differently named cards you have (round down). |

### Dark Ages Kingdom cards (35)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Poor House** | $1 | Action | +$4. Reveal your hand. -$1 per Treasure card in your hand (you can't go below $0). |
| **Beggar** | $2 | Action - Reaction | Gain 3 Coppers into your hand. When another player plays an Attack, you may first discard this to gain 2 Silvers, putting one on your deck. |
| **Squire** | $2 | Action | +$1. Choose one: +2 Actions; or +2 Buys; or gain a Silver. When you trash this, gain an Attack card. |
| **Vagrant** | $2 | Action | +1 Card, +1 Action. Reveal the top card of your deck. If it's a Curse, Ruins, Shelter or Victory card, put it into your hand. |
| **Forager** | $3 | Action | +1 Action, +1 Buy. Trash a card from your hand. +$1 per differently named Treasure in the trash. |
| **Hermit** | $3 | Action | Look through your discard pile. You may trash a card from it or from your hand that is not a Treasure. Gain a card costing up to $3. When you discard this from play, if you did not buy any cards this turn, trade it for a Madman. |
| **Market Square** | $3 | Action - Reaction | +1 Card, +1 Action, +1 Buy. When one of your cards is trashed, you may discard this from your hand to gain a Gold. |
| **Sage** | $3 | Action | +1 Action. Reveal cards from the top of your deck until you reveal one costing $3 or more. Put it into your hand and discard the rest. |
| **Storeroom** | $3 | Action | +1 Buy. Discard any number of cards, then draw that many. Then discard any number of cards for +$1 each. |
| **Urchin** | $3 | Action - Attack | +1 Card, +1 Action. Each other player discards down to 4 cards in hand. When you play another Attack card with this in play, you may trash this. If you do, gain a Mercenary. |
| **Armory** | $4 | Action | Gain a card costing up to $4 onto your deck. |
| **Death Cart** | $4 | Action - Looter | You may trash an Action card from your hand. If you don't, trash this. +$5. When you gain this, gain 2 Ruins. |
| **Feodum** | $4 | Victory | Worth 1 VP per 3 Silvers you have (round down). When you trash this, gain 3 Silvers. |
| **Fortress** | $4 | Action | +1 Card, +2 Actions. When you trash this, put it into your hand. |
| **Ironmonger** | $4 | Action | +1 Card, +1 Action. Reveal the top card of your deck; you may discard it. Either way, if it is an Action card, +1 Action; a Treasure card, +$1; a Victory card, +1 Card. |
| **Marauder** | $4 | Action - Attack - Looter | Gain a Spoils from the Spoils pile. Each other player gains a Ruins. |
| **Procession** | $4 | Action | You may play an Action card from your hand twice. Trash it. Gain an Action card costing exactly $1 more than it. (Duration cards cannot be chosen.) |
| **Rats** | $4 | Action | +1 Card, +1 Action. Gain a Rats. Trash a card from your hand other than a Rats (or reveal a hand of all Rats). When you trash this, +1 Card. (The pile has 20 cards.) |
| **Scavenger** | $4 | Action | +$2. You may put your deck into your discard pile. Look through your discard pile and put one card from it onto your deck. |
| **Wandering Minstrel** | $4 | Action | +1 Card, +2 Actions. Reveal the top 3 cards of your deck. Put the Actions back in any order and discard the rest. |
| **Band of Misfits** | $5 | Action | Play this as if it were an Action card in the Supply costing less than it that you choose, leaving that card there. |
| **Bandit Camp** | $5 | Action | +1 Card, +2 Actions. Gain a Spoils from the Spoils pile. |
| **Catacombs** | $5 | Action | Look at the top 3 cards of your deck. Choose one: put them into your hand; or discard them and +3 Cards. When you trash this, gain a cheaper card. |
| **Count** | $5 | Action | Choose one: discard 2 cards; or put a card from your hand onto your deck; or gain a Copper. Then choose one: +$3; or trash your hand; or gain a Duchy. |
| **Counterfeit** | $5 | Treasure | $1, +1 Buy. When you play this, you may play a Treasure from your hand twice. If you do, trash that Treasure. |
| **Cultist** | $5 | Action - Attack - Looter | +2 Cards. Each other player gains a Ruins. You may play a Cultist from your hand. When you trash this, +3 Cards. |
| **Graverobber** | $5 | Action | Choose one: gain a card from the trash costing from $3 to $6 onto your deck; or trash an Action card from your hand and gain a card costing up to $3 more than it. |
| **Junk Dealer** | $5 | Action | +1 Card, +1 Action, +$1. Trash a card from your hand. |
| **Knights** | $5 | Knight | A pile of 10 different Knights (Dame Anna, Dame Josephine, Dame Molly, Dame Natalie, Dame Sylvia, Sir Bailey, Sir Destry, Sir Martin, Sir Michael, Sir Vander), shuffled; only the top Knight can be bought or gained. Each is an Action - Attack that makes the others trash a card costing $3 to $6. |
| **Mystic** | $5 | Action | +1 Action, +$2. Name a card. Reveal the top card of your deck. If it's the named card, put it into your hand. |
| **Pillage** | $5 | Action - Attack | Trash this. Each other player with 5 or more cards in hand reveals their hand and discards a card that you choose. Gain 2 Spoils. |
| **Rebuild** | $5 | Action | +1 Action. Name a card. Reveal cards from the top of your deck until you reveal a Victory card that is not the named card. Discard the rest, trash the Victory card, and gain a Victory card costing up to $3 more than it. |
| **Rogue** | $5 | Action - Attack | +$2. If there are any cards in the trash costing from $3 to $6, gain one of them. Otherwise, each other player reveals the top 2 cards of their deck, trashes one of them costing from $3 to $6, and discards the rest. |
| **Altar** | $6 | Action | Trash a card from your hand. Gain a card costing up to $5. |
| **Hunting Grounds** | $6 | Action | +4 Cards. When you trash this, gain a Duchy or 3 Estates. |

### Empires Kingdom cards (24)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **City Quarter** | 8D | Action | +2 Actions. Reveal your hand. +1 Card per Action card revealed. Costs 8 Debt. |
| **Engineer** | 4D | Action | Gain a card costing up to $4. You may trash this. If you do, gain a card costing up to $4. Costs 4 Debt. |
| **Overlord** | 8D | Action - Command | Play a non-Command Action card from the Supply costing up to $5, leaving it there. Costs 8 Debt. |
| **Royal Blacksmith** | 8D | Action | +5 Cards. Reveal your hand; discard the Coppers. Costs 8 Debt. |
| **Encampment** | $2 | Action | +2 Cards, +2 Actions. You may reveal a Gold or Plunder from your hand. If you do not, set this aside and return it to the Supply at the start of Clean-up. (Top half of the Encampment/Plunder pile.) |
| **Patrician** | $2 | Action | +1 Card, +1 Action. Reveal the top card of your deck. If it costs $5 or more, put it into your hand. (Top half of the Patrician/Emporium pile.) |
| **Settlers** | $2 | Action | +1 Card, +1 Action. Look through your discard pile. You may reveal a Copper from it and put it into your hand. (Top half of the Settlers/Bustling Village pile.) |
| **Castles** | $3 | Castle | A pile of the 8 different Castles (12 cards with 3 or 4 players), cheapest on top; only the top Castle can be bought or gained. Humble, Crumbling, Small, Haunted, Opulent, Sprawling, Grand and King's Castle. |
| **Catapult** | $3 | Action - Attack | +$1. Trash a card from your hand. If it costs $3 or more, each other player gains a Curse. If it is a Treasure, each other player discards down to 3 cards in hand. (Top half of the Catapult/Rocks pile.) |
| **Chariot Race** | $3 | Action | +1 Action. Reveal the top card of your deck and put it into your hand. The player to your left reveals the top card of their deck. If your card costs more, +$1 and +1 VP. |
| **Enchantress** | $3 | Action - Attack - Duration | Until your next turn, the first time each other player plays an Action card on their turn, they get +1 Card and +1 Action instead of following its instructions. At the start of your next turn: +2 Cards. |
| **Farmers' Market** | $3 | Action - Gathering | +1 Buy. If there are 4 VP or more on the Farmers' Market pile, take them and trash this. Otherwise add 1 VP to the pile and then +$1 per 1 VP on the pile. |
| **Gladiator** | $3 | Action | +$2. Reveal a card from your hand. The player to your left may reveal a copy from their hand. If they do not, +$1 and trash a Gladiator from the Supply. (Top half of the Gladiator/Fortune pile.) |
| **Sacrifice** | $4 | Action | Trash a card from your hand. If it is an Action card: +2 Cards, +2 Actions. A Treasure card: +$2. A Victory card: +2 VP. |
| **Temple** | $4 | Action - Gathering | +1 VP. Trash from 1 to 3 differently named cards from your hand. Add 1 VP to the Temple pile. When you gain this, take the VP from the Temple pile. |
| **Villa** | $4 | Action | +2 Actions, +1 Buy, +$1. When you gain this, put it into your hand, +1 Action, and if it is your Buy phase, return to your Action phase. |
| **Archive** | $5 | Action - Duration | +1 Action. Set aside the top 3 cards of your deck face down (you may look at them). Now and at the start of your next two turns, put one of them into your hand. |
| **Capital** | $5 | Treasure | $6, +1 Buy. When you discard this from play, take 6 Debt, and then you may pay off Debt. |
| **Charm** | $5 | Treasure | When you play this, choose one: +1 Buy and +$2; or the next time you buy a card this turn, you may also gain a differently named card with the same cost. |
| **Crown** | $5 | Action - Treasure | If it is your Action phase, you may play an Action card from your hand twice. If it is your Buy phase, you may play a Treasure from your hand twice. |
| **Forum** | $5 | Action | +3 Cards, +1 Action. Discard 2 cards. When you buy this, +1 Buy. |
| **Groundskeeper** | $5 | Action | +1 Card, +1 Action. This turn, when you gain a Victory card, +1 VP. |
| **Legionary** | $5 | Action - Attack | +$3. You may reveal a Gold from your hand. If you do, each other player discards down to 2 cards in hand, then draws a card. |
| **Wild Hunt** | $5 | Action - Gathering | Choose one: +3 Cards and add 1 VP to the Wild Hunt pile; or gain an Estate, and if you do, take the VP from the pile. |

### Hinterlands Kingdom cards (26)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Crossroads** | $2 | Action | Reveal your hand. +1 Card per Victory card revealed. If this is the first time you played a Crossroads this turn, +3 Actions. |
| **Duchess** | $2 | Action | +$2. Each player (including you) looks at the top card of their deck and may discard it or put it back. In games using this, when you gain a Duchy, you may gain a Duchess. |
| **Fool's Gold** | $2 | Reaction - Treasure | Worth $1 if it's the first time you played Fool's Gold this turn, otherwise worth $4. When another player gains a Province, you may trash this from your hand. If you do, gain a Gold, putting it onto your deck. |
| **Develop** | $3 | Action | Trash a card from your hand. Gain a card costing exactly $1 more than it and a card costing exactly $1 less than it, in either order, putting them on top of your deck. |
| **Oasis** | $3 | Action | +1 Card, +1 Action, +$1. Discard a card. |
| **Oracle** | $3 | Action - Attack | Each player (including you) reveals the top 2 cards of their deck, and you choose one: either they discard them, or they put them back on top in an order they choose. +2 Cards. |
| **Scheme** | $3 | Action | +1 Card, +1 Action. At the start of Clean-up this turn, you may choose an Action card you have in play. If you discard it from play this turn, put it onto your deck. |
| **Tunnel** | $3 | Reaction - Victory | 2 VP. When you discard this other than during Clean-up, you may reveal it. If you do, gain a Gold. |
| **Jack of All Trades** | $4 | Action | Gain a Silver. Look at the top card of your deck; discard it or put it back. Draw until you have 5 cards in hand. You may trash a card from your hand that is not a Treasure. |
| **Noble Brigand** | $4 | Action - Attack | +$1. When you buy this or play it, each other player reveals the top 2 cards of their deck, trashes a revealed Silver or Gold you choose, and discards the rest. If they didn't reveal a Treasure, they gain a Copper. You gain the trashed cards. |
| **Nomad Camp** | $4 | Action | +1 Buy, +$2. When you gain this, put it onto your deck. |
| **Silk Road** | $4 | Victory | Worth 1 VP for every 4 Victory cards in your deck (round down). |
| **Spice Merchant** | $4 | Action | You may trash a Treasure from your hand. If you do, choose one: +2 Cards and +1 Action; or +$2 and +1 Buy. |
| **Trader** | $4 | Action - Reaction | Trash a card from your hand. Gain a number of Silvers equal to its cost in coins. When you would gain a card, you may reveal this from your hand. If you do, instead, gain a Silver. |
| **Cache** | $5 | Treasure | $3. When you gain this, gain two Coppers. |
| **Cartographer** | $5 | Action | +1 Card, +1 Action. Look at the top 4 cards of your deck. Discard any number of them. Put the rest back on top in any order. |
| **Embassy** | $5 | Action | +5 Cards, then discard 3 cards. When you gain this, each other player gains a Silver. |
| **Haggler** | $5 | Action | +$2. While this is in play, when you buy a card, gain a card costing less than it that is not a Victory card. |
| **Highway** | $5 | Action | +1 Card, +1 Action. While this is in play, cards cost $1 less, but not less than $0. |
| **Ill-Gotten Gains** | $5 | Treasure | $1. When you play this, you may gain a Copper, putting it into your hand. When you gain this, each other player gains a Curse. |
| **Inn** | $5 | Action | +2 Cards, +2 Actions. Discard 2 cards. When you gain this, look through your discard pile (including this), reveal any number of Action cards from it, and shuffle them into your deck. |
| **Mandarin** | $5 | Action | +$3. Put a card from your hand onto your deck. When you gain this, put all Treasures you have in play onto your deck in any order. |
| **Margrave** | $5 | Action - Attack | +3 Cards, +1 Buy. Each other player draws a card, then discards down to 3 cards in hand. |
| **Stables** | $5 | Action | You may discard a Treasure. If you do, +3 Cards and +1 Action. |
| **Border Village** | $6 | Action | +1 Card, +2 Actions. When you gain this, gain a card costing less than it. |
| **Farmland** | $6 | Victory | 2 VP. When you buy this, trash a card from your hand. Gain a card costing exactly $2 more than the trashed card. |

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

### Menagerie Kingdom cards (30)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Black Cat** | $2 | Action - Attack - Reaction | +2 Cards. If it isn't your turn, each other player gains a Curse. \| When another player gains a Victory card, you may play this from your hand. |
| **Sleigh** | $2 | Action - Reaction | Gain 2 Horses. \| When you gain a card, you may discard this from your hand, to put that card into your hand or onto your deck. |
| **Supplies** | $2 | Treasure | $1. When you play this, gain a Horse onto your deck. |
| **Camel Train** | $3 | Action | Exile a non-Victory card from the Supply. \| When you gain this, Exile a Gold from the Supply. |
| **Goatherd** | $3 | Action | You may trash a card from your hand. +1 Card per card the player to your right trashed on their last turn. |
| **Scrap** | $3 | Action | Trash a card from your hand. Choose a different thing per $1 it costs: +1 Card; +1 Action; +1 Buy; +$1; gain a Silver; gain a Horse. |
| **Sheepdog** | $3 | Action - Reaction | +2 Cards. \| When you gain a card, you may play this from your hand. |
| **Snowy Village** | $3 | Action | +1 Card, +4 Actions, +1 Buy. Ignore any further +Actions you would get this turn. |
| **Stockpile** | $3 | Treasure | $3. +1 Buy. When you play this, Exile it. |
| **Bounty Hunter** | $4 | Action | +1 Action. Exile a card from your hand. If you didn't have a copy of it in Exile, +$3. |
| **Cardinal** | $4 | Action - Attack | +$2. Each other player reveals the top 2 cards of their deck, Exiles one costing from $3 to $6, and discards the rest. |
| **Cavalry** | $4 | Action | Gain 2 Horses. \| When you gain this, +2 Cards, +1 Buy, and if it's your Buy phase, return to your Action phase. |
| **Groom** | $4 | Action | Gain a card costing up to $4. If it's an Action card, gain a Horse; a Treasure card, gain a Silver; a Victory card, +1 Card and +1 Action. |
| **Hostelry** | $4 | Action | +1 Card, +2 Actions. \| When you gain this, you may discard any number of Treasures, revealed, to gain that many Horses. |
| **Village Green** | $4 | Action - Duration - Reaction | Now or at the start of your next turn, +1 Card and +2 Actions. \| When you discard this other than in Clean-up, you may play it. |
| **Barge** | $5 | Action - Duration | Choose one: +3 Cards and +1 Buy now; or at the start of your next turn, +3 Cards and +1 Buy. |
| **Coven** | $5 | Action - Attack | +1 Action, +$2. Each other player Exiles a Curse from the Supply. If they can't, they discard their Curses from Exile. |
| **Displace** | $5 | Action | Exile a card from your hand. Gain a differently named card costing up to $2 more than it. |
| **Falconer** | $5 | Action - Reaction | Gain a card to your hand costing less than this. \| When any player gains a card with 2 or more types (Action, Attack, etc.), you may play this from your hand. |
| **Fisherman** | $5 | Action | +1 Card, +1 Action, +$1. During your turns, this costs $3 less if your discard pile is empty. (Costs $5*.) |
| **Gatekeeper** | $5 | Action - Attack - Duration | At the start of your next turn, +$3. Until then, when another player gains an Action or Treasure card that they don't have a copy of in Exile, they Exile it. |
| **Hunting Lodge** | $5 | Action | +1 Card, +2 Actions. You may discard your hand for +5 Cards. |
| **Kiln** | $5 | Action | +$2. The next time you play a card this turn, you may first gain a copy of it. |
| **Livery** | $5 | Action | +$3. This turn, when you gain a card costing $4 or more, gain a Horse. |
| **Mastermind** | $5 | Action - Duration | At the start of your next turn, you may play an Action card from your hand three times. |
| **Paddock** | $5 | Action | +$2. Gain 2 Horses. +1 Action per empty Supply pile. |
| **Sanctuary** | $5 | Action | +1 Card, +1 Action, +1 Buy. You may Exile a card from your hand. |
| **Destrier** | $6 | Action | +2 Cards, +1 Action. During your turns, this costs $1 less per card you've gained this turn. (Costs $6*.) |
| **Wayfarer** | $6 | Action | +3 Cards. You may gain a Silver. This has the same cost as the last other card gained this turn, if any. (Costs $6*.) |
| **Animal Fair** | $7 | Action | +$4. +1 Buy per empty Supply pile. \| Instead of paying this card's cost, you may trash an Action card from your hand. (Costs $7*.) |

### Nocturne Kingdom cards (33)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Druid** | $2 | Action - Fate | +1 Buy. Receive one of the set-aside Boons (leaving it there). Setup: set aside the top 3 Boons face up. |
| **Faithful Hound** | $2 | Action - Reaction | +2 Cards. When you discard this other than during Clean-up, you may set it aside, and put it into your hand at end of turn. |
| **Guardian** | $2 | Duration - Night | This is gained to your hand (instead of your discard pile). Until your next turn, when another player plays an Attack card, it doesn't affect you. At the start of your next turn, +$1. |
| **Monastery** | $2 | Night | For each card you've gained this turn, you may trash a card from your hand or a Copper you have in play. |
| **Pixie** | $2 | Action - Fate | +1 Card, +1 Action. Discard the top Boon. You may trash this to receive that Boon twice. Heirloom: Goat. |
| **Tracker** | $2 | Action - Fate | +$1. Receive a Boon. While this is in play, when you gain a card, you may put that card onto your deck. Heirloom: Pouch. |
| **Changeling** | $3 | Night | Trash this. Gain a copy of a card you have in play. In games using this, when you gain a card costing $3 or more, you may exchange it for a Changeling. |
| **Fool** | $3 | Action - Fate | If you aren't the player with Lost in the Woods, take it, take 3 Boons, and receive the Boons in any order. Heirloom: Lucky Coin. |
| **Ghost Town** | $3 | Duration - Night | At the start of your next turn, +1 Card and +1 Action. This is gained to your hand (instead of your discard pile). |
| **Leprechaun** | $3 | Action - Doom | Gain a Gold. If you have exactly 7 cards in play, gain a Wish from its pile. Otherwise, receive a Hex. |
| **Night Watchman** | $3 | Night | Look at the top 5 cards of your deck, discard any number, and put the rest back in any order. This is gained to your hand (instead of your discard pile). |
| **Secret Cave** | $3 | Action - Duration | +1 Card, +1 Action. You may discard 3 cards. If you did, then at the start of your next turn, +$3. Heirloom: Magic Lamp. |
| **Bard** | $4 | Action - Fate | +$2. Receive a Boon. |
| **Blessed Village** | $4 | Action - Fate | +1 Card, +2 Actions. When you gain this, take a Boon. Receive it now or at the start of your next turn. |
| **Cemetery** | $4 | Victory | 2 VP. When you gain this, trash up to 4 cards from your hand. Heirloom: Haunted Mirror. |
| **Conclave** | $4 | Action | +$2. You may play an Action card from your hand that you don't have a copy of in play. If you do, +1 Action. |
| **Devil's Workshop** | $4 | Night | If the number of cards you've gained this turn is: 2 or more, gain an Imp from its pile; 1, gain a card costing up to $4; 0, gain a Gold. |
| **Exorcist** | $4 | Night | Trash a card from your hand. Gain a cheaper Spirit from one of the Spirit piles. |
| **Necromancer** | $4 | Action | Play a face up, non-Duration Action card from the trash, leaving it there and turning it face down for the turn. Setup: put the 3 Zombies into the trash. |
| **Shepherd** | $4 | Action | +1 Action. Discard any number of Victory cards, revealing them. +2 Cards per card discarded. Heirloom: Pasture. |
| **Skulk** | $4 | Action - Attack - Doom | +1 Buy. Each other player receives the next Hex. When you gain this, gain a Gold. |
| **Cobbler** | $5 | Duration - Night | At the start of your next turn, gain a card to your hand costing up to $4. |
| **Crypt** | $5 | Duration - Night | Set aside any number of Treasures you have in play, face down (under this). While any remain, at the start of each of your turns, put one of them into your hand. |
| **Cursed Village** | $5 | Action - Doom | +2 Actions. Draw until you have 6 cards in hand. When you gain this, receive a Hex. |
| **Den of Sin** | $5 | Duration - Night | At the start of your next turn, +2 Cards. This is gained to your hand (instead of your discard pile). |
| **Idol** | $5 | Attack - Fate - Treasure | $2. When you play this, if you then have an odd number of Idols in play, receive a Boon; if an even number, each other player gains a Curse. |
| **Pooka** | $5 | Action | You may trash a Treasure other than Cursed Gold from your hand, for +4 Cards. Heirloom: Cursed Gold. |
| **Sacred Grove** | $5 | Action - Fate | +1 Buy, +$3. Receive a Boon. If it doesn't give +$1, each other player may receive it. |
| **Tormentor** | $5 | Action - Attack - Doom | +$2. If you have no other cards in play, gain an Imp from its pile. Otherwise, each other player receives the next Hex. |
| **Tragic Hero** | $5 | Action | +3 Cards, +1 Buy. If you have 8 or more cards in hand (after drawing), trash this and gain a Treasure. |
| **Vampire** | $5 | Attack - Doom - Night | Each other player receives the next Hex. Gain a card costing up to $5 other than a Vampire. Exchange this for a Bat. |
| **Werewolf** | $5 | Action - Attack - Doom - Night | If it's your Night phase, each other player receives the next Hex. Otherwise, +3 Cards. |
| **Raider** | $6 | Attack - Duration - Night | Each other player with 5 or more cards in hand discards a copy of a card you have in play (or reveals they can't). At the start of your next turn, +$3. |

### Plunder Kingdom cards (40)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Cage** | $2 | Duration - Treasure | Set aside up to 4 cards from your hand face down (on this). The next time you gain a Victory card, trash this, and put the set aside cards into your hand at end of turn. |
| **Grotto** | $2 | Action - Duration | +1 Action. Set aside up to 4 cards from your hand face down (on this). At the start of your next turn, discard them, then draw as many. |
| **Jewelled Egg** | $2 | Treasure | +1 Buy. When you trash this, gain a Loot. |
| **Search** | $2 | Action - Duration | +$2. The next time a Supply pile empties, trash this and gain a Loot. |
| **Shaman** | $2 | Action | +1 Action, +$1. You may trash a card from your hand. In games using this, at the start of your turn, gain a card from the trash costing up to $6. |
| **Secluded Shrine** | $3 | Action - Duration | +$1. The next time you gain a Treasure, trash up to 2 cards from your hand. |
| **Siren** | $3 | Action - Attack - Duration | Each other player gains a Curse. At the start of your next turn, draw until you have 8 cards in hand. When you gain this, trash it unless you trash an Action from your hand. |
| **Stowaway** | $3 | Action - Duration - Reaction | At the start of your next turn, +2 Cards. When anyone gains a Duration card, you may play this from your hand. |
| **Taskmaster** | $3 | Action - Duration | +1 Action, +$1, and if you gain a card costing exactly $5 this turn, then at the start of your next turn, repeat this ability. |
| **Abundance** | $4 | Duration - Treasure | The next time you gain an Action card: +1 Buy and +$3. |
| **Cabin Boy** | $4 | Action - Duration | +1 Card, +1 Action. At the start of your next turn, choose one: +$2; or trash this to gain a Duration card. |
| **Crucible** | $4 | Treasure | Trash a card from your hand. +$1 per $1 it costs. (Worth a variable number of $.) |
| **Flagship** | $4 | Action - Command - Duration | +$2. The next time you play a non-Command Action card, replay it. |
| **Fortune Hunter** | $4 | Action | +$2. Look at the top 3 cards of your deck. You may play a Treasure from them. Put the rest back in any order. |
| **Gondola** | $4 | Duration - Treasure | Either now or at the start of your next turn: +$2. When you gain this, you may play an Action card from your hand. |
| **Harbor Village** | $4 | Action | +1 Card, +2 Actions. After the next Action you play this turn, if it gave you +$, +$1. |
| **Landing Party** | $4 | Action - Duration | +2 Cards, +2 Actions. The next time the first card you play on a turn is a Treasure, put this onto your deck afterwards. |
| **Mapmaker** | $4 | Action - Reaction | Look at the top 4 cards of your deck. Put 2 into your hand and discard the rest. When any player gains a Victory card, you may play this from your hand. |
| **Maroon** | $4 | Action | Trash a card from your hand. +2 Cards per type it has (Action, Attack, etc.). |
| **Rope** | $4 | Duration - Treasure | +1 Buy. At the start of your next turn, +1 Card and you may trash a card from your hand. |
| **Swamp Shacks** | $4 | Action | +2 Actions. +1 Card per 3 cards you have in play (round down). |
| **Tools** | $4 | Treasure | Gain a copy of a card anyone has in play. |
| **Buried Treasure** | $5 | Duration - Treasure | At the start of your next turn, +1 Buy and +$3. When you gain this, play it. |
| **Crew** | $5 | Action - Duration | +3 Cards. At the start of your next turn, put this onto your deck. |
| **Cutthroat** | $5 | Action - Attack - Duration | Each other player discards down to 3 cards in hand. The next time anyone gains a Treasure costing $5 or more, gain a Loot. |
| **Enlarge** | $5 | Action - Duration | Now and at the start of your next turn: Trash a card from your hand, and gain one costing up to $2 more. |
| **Figurine** | $5 | Treasure | +2 Cards. You may discard an Action card for +1 Buy and +$1. |
| **First Mate** | $5 | Action | Play any number of Action cards with the same name from your hand, then draw until you have 6 cards in hand. |
| **Frigate** | $5 | Action - Attack - Duration | +$3. Until the start of your next turn, each time another player plays an Action card, they discard down to 4 cards in hand afterwards. |
| **Longship** | $5 | Action - Duration | +2 Actions. At the start of your next turn, +2 Cards. |
| **Mining Road** | $5 | Action | +1 Action, +1 Buy, +$2. Once this turn, when you gain a Treasure, you may play it. |
| **Pendant** | $5 | Treasure | +$1 per differently named Treasure you have in play. |
| **Pickaxe** | $5 | Treasure | Trash a card from your hand. If it costs $3 or more, gain a Loot to your hand. |
| **Pilgrim** | $5 | Action | +4 Cards. Put a card from your hand onto your deck. |
| **Quartermaster** | $5 | Action - Duration | At the start of each of your turns for the rest of the game, choose one: Gain a card costing up to $4, setting it aside on this; or put a card from this into your hand. |
| **Silver Mine** | $5 | Treasure | Gain a Treasure costing less than this to your hand. |
| **Trickster** | $5 | Action - Attack | Each other player gains a Curse. Once this turn, when you discard a Treasure from play, you may set it aside. Put it in your hand at end of turn. |
| **Wealthy Village** | $5 | Action | +1 Card, +2 Actions. When you gain this, if you have at least 3 differently named Treasures in play, gain a Loot. |
| **Sack of Loot** | $6 | Treasure | +1 Buy. Gain a Loot. |
| **King's Cache** | $7 | Treasure | You may play a Treasure from your hand 3 times. |

### Prosperity Kingdom cards (34)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Anvil** | $3 | Treasure | $1. You may discard a Treasure to gain a card costing up to $4. |
| **Loan** | $3 | Treasure | $1. When you play this, reveal cards from your deck until you reveal a Treasure. Discard it or trash it. Discard the other cards. |
| **Trade Route** | $3 | Action | +1 Buy. +$1 per token on the Trade Route mat. Trash a card from your hand. (Setup: a token on each Victory Supply pile; when a card is gained from such a pile, move its token to the mat.) |
| **Watchtower** | $3 | Action - Reaction | Draw until you have 6 cards in hand. When you gain a card, you may reveal this from your hand, to either trash that card or put it onto your deck. |
| **Bishop** | $4 | Action | +$1, +1 VP token. Trash a card from your hand. +1 VP token per $2 it costs (round down). Each other player may trash a card from their hand. |
| **Clerk** | $4 | Action - Attack - Reaction | +$2. Each other player with 5 or more cards in hand puts one onto their deck. At the start of your turn, you may play this from your hand. |
| **Investment** | $4 | Treasure | Trash a card from your hand. Choose one: +$1; or trash this to reveal your hand for +1 VP token per differently named Treasure there. |
| **Monument** | $4 | Action | +$2, +1 VP token. |
| **Quarry** | $4 | Treasure | $1. This turn, Action cards cost $2 less. |
| **Talisman** | $4 | Treasure | $1. While this is in play, when you buy a card costing $4 or less that is not a Victory card, gain a copy of it. |
| **Tiara** | $4 | Treasure | +1 Buy. This turn, when you gain a card, you may put it onto your deck. You may play a Treasure from your hand twice. |
| **Workers' Village** | $4 | Action | +1 Card, +2 Actions, +1 Buy. |
| **Charlatan** | $5 | Action - Attack | +$3. Each other player gains a Curse. In games using this, Curse is also a Treasure worth $1. |
| **City** | $5 | Action | +1 Card, +2 Actions. If there are one or more empty Supply piles, +1 Card. If there are two or more, +1 Buy and +$1. |
| **Collection** | $5 | Treasure | $2, +1 Buy. This turn, when you gain an Action card, +1 VP token. |
| **Contraband** | $5 | Treasure | $3, +1 Buy. When you play this, the player to your left names a card. You can't buy that card this turn. |
| **Counting House** | $5 | Action | Look through your discard pile, reveal any number of Coppers from it, and put them into your hand. |
| **Crystal Ball** | $5 | Treasure | $1. Look at the top card of your deck. You may trash it, discard it, or, if it's an Action or Treasure, play it. |
| **Magnate** | $5 | Action | Reveal your hand. +1 Card per Treasure in it. |
| **Mint** | $5 | Action | You may reveal a Treasure card from your hand. Gain a copy of it. When you gain this, trash all non-Duration Treasures you have in play. |
| **Mountebank** | $5 | Action - Attack | +$2. Each other player may discard a Curse. If they don't, they gain a Curse and a Copper. |
| **Rabble** | $5 | Action - Attack | +3 Cards. Each other player reveals the top 3 cards of their deck, discards the Actions and Treasures, and puts the rest back in any order they choose. |
| **Royal Seal** | $5 | Treasure | $2. While this is in play, when you gain a card, you may put that card onto your deck. |
| **Vault** | $5 | Action | +2 Cards. Discard any number of cards for +$1 each. Each other player may discard 2 cards, to draw a card. |
| **Venture** | $5 | Treasure | $1. When you play this, reveal cards from your deck until you reveal a Treasure. Discard the other cards. Play that Treasure. |
| **War Chest** | $5 | Treasure | The player to your left names a card. Gain a card costing up to $5 that hasn't been named for War Chests this turn. |
| **Goons** | $6 | Action - Attack | +1 Buy, +$2. Each other player discards down to 3 cards in hand. While this is in play, when you buy a card, +1 VP token. |
| **Grand Market** | $6 | Action | +1 Card, +1 Action, +1 Buy, +$2. You can't buy this if you have any Coppers in play. |
| **Hoard** | $6 | Treasure | $2. This turn, when you gain a Victory card, if you bought it, gain a Gold. |
| **Bank** | $7 | Treasure | $1 per Treasure card you have in play (counting this). |
| **Expand** | $7 | Action | Trash a card from your hand. Gain a card costing up to $3 more than it. |
| **Forge** | $7 | Action | Trash any number of cards from your hand. Gain a card with cost exactly equal to the total cost in coins of the trashed cards. |
| **King's Court** | $7 | Action | You may play an Action card from your hand three times. |
| **Peddler** | $8 | Action | +1 Card, +1 Action, +$1. During your Buy phase, this costs $2 less per Action card you have in play, but not less than $0. |

### Renaissance Kingdom cards (25)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Border Guard** | $2 | Action | +1 Action. Reveal the top 2 cards of your deck. Put one into your hand and discard the other. If both were Actions, take the Lantern or Horn. |
| **Ducat** | $2 | Treasure | +1 Coffers, +1 Buy. When you gain this, you may trash a Copper from your hand. |
| **Lackeys** | $2 | Action | +2 Cards. When you gain this, +2 Villagers. |
| **Acting Troupe** | $3 | Action | +4 Villagers. Trash this. |
| **Cargo Ship** | $3 | Action - Duration | +$2. Once this turn, when you gain a card, you may set it aside face up (on this). At the start of your next turn, put it into your hand. |
| **Experiment** | $3 | Action | +2 Cards, +1 Action. Return this to the Supply. When you gain this, gain another Experiment (that doesn't come with another). |
| **Improve** | $3 | Action | +$2. At the start of Clean-up, you may trash an Action card you would discard from play this turn, to gain a card costing exactly $1 more than it. |
| **Flag Bearer** | $4 | Action | +$2. When you gain or trash this, take the Flag. |
| **Hideout** | $4 | Action | +1 Card, +2 Actions. Trash a card from your hand. If it's a Victory card, gain a Curse. |
| **Inventor** | $4 | Action | Gain a card costing up to $4, then cards cost $1 less this turn (but not less than $0). |
| **Mountain Village** | $4 | Action | +2 Actions. Look through your discard pile and put a card from it into your hand; if you can't, +1 Card. |
| **Patron** | $4 | Action - Reaction | +1 Villager, +$2. When something causes you to reveal this (using the word "reveal"), +1 Coffers. |
| **Priest** | $4 | Action | +$2. Trash a card from your hand. For the rest of this turn, when you trash a card, +$2. |
| **Research** | $4 | Action - Duration | +1 Action. Trash a card from your hand. Per $1 it costs, set aside a card from your deck face down (on this). At the start of your next turn, put those cards into your hand. |
| **Silk Merchant** | $4 | Action | +2 Cards, +1 Buy. When you gain or trash this, +1 Coffers and +1 Villager. |
| **Old Witch** | $5 | Action - Attack | +3 Cards. Each other player gains a Curse and may trash a Curse from their hand. |
| **Recruiter** | $5 | Action | +2 Cards. Trash a card from your hand. +1 Villager per $1 it costs. |
| **Scepter** | $5 | Treasure | When you play this, choose one: +$2; or replay an Action card you played this turn that's still in play. |
| **Scholar** | $5 | Action | Discard your hand. +7 Cards. |
| **Sculptor** | $5 | Action | Gain a card to your hand costing up to $4. If it's a Treasure, +1 Villager. |
| **Seer** | $5 | Action | +1 Card, +1 Action. Reveal the top 3 cards of your deck. Put the ones costing from $2 to $4 into your hand. Put the rest back in any order. |
| **Spices** | $5 | Treasure | $2. +1 Buy. When you gain this, +2 Coffers. |
| **Swashbuckler** | $5 | Action | +3 Cards. If your discard pile has any cards in it: +1 Coffers, then if you have at least 4 Coffers tokens, take the Treasure Chest. |
| **Treasurer** | $5 | Action | +$3. Choose one: Trash a Treasure from your hand; or gain a Treasure from the trash to your hand; or take the Key. |
| **Villain** | $5 | Action - Attack | +2 Coffers. Each other player with 5 or more cards in hand discards one costing $2 or more (or reveals they can't). |

### Rising Sun Kingdom cards (25)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Artist** | 8D | Action | +1 Action. +1 Card per card you have exactly one copy of in play. |
| **Daimyo** | 6D | Action - Command | +1 Card, +1 Action. The next time you play a non-Command Action card this turn, replay it afterwards. |
| **Mountain Shrine** | 5D | Action - Omen | +1 Sun. +$2. You may trash a card from your hand. Then if there are any Action cards in the trash, +2 Cards. |
| **Fishmonger** | $2 | Action - Shadow | +1 Buy. +$1. You can play this from your deck as if in your hand. |
| **Snake Witch** | $2 | Action - Attack | +1 Card, +1 Action. If your hand has no duplicate cards, you may reveal it and return this to its pile, to have each other player gain a Curse. |
| **Aristocrat** | $3 | Action | If the number of Aristocrats you have in play is: 1 or 5: +3 Actions; 2 or 6: +3 Cards; 3 or 7: +$3; 4 or 8: +3 Buys. |
| **Craftsman** | $3 | Action | +2 Debt. Gain a card costing up to $5. |
| **Riverboat** | $3 | Action - Duration | At the start of your next turn, play the set aside card, leaving it there. Setup: Set aside an unused non-Duration Action card costing $5. |
| **Root Cellar** | $3 | Action | +3 Cards, +1 Action, +3 Debt. |
| **Alley** | $4 | Action - Shadow | +1 Card, +1 Action. Discard a card. You can play this from your deck as if in your hand. |
| **Change** | $4 | Action | If you have any Debt, +$3. Otherwise, trash a card from your hand, and gain a card costing more than it. +Debt equal to the difference in $. |
| **Ninja** | $4 | Action - Attack - Shadow | +1 Card. Each other player discards down to 3 cards in hand. You can play this from your deck as if in your hand. |
| **Poet** | $4 | Action - Omen | +1 Sun. +1 Card, +1 Action. Reveal the top card of your deck. If it costs $3 or less, put it into your hand. |
| **River Shrine** | $4 | Action - Omen | +1 Sun. Trash up to 2 cards from your hand. At the start of Clean-up, if you didn't gain any cards in your Buy phase this turn, gain a card costing up to $4. |
| **Rustic Village** | $4 | Action - Omen | +1 Sun. +1 Card, +2 Actions. You may discard 2 cards for +1 Card. |
| **Gold Mine** | $5 | Action | +1 Card, +1 Action, +1 Buy. You may gain a Gold and get +4 Debt. |
| **Imperial Envoy** | $5 | Action | +5 Cards, +1 Buy, +2 Debt. |
| **Kitsune** | $5 | Action - Attack - Omen | +1 Sun. Choose two different options: +2 Actions; +$2; each other player gains a Curse; gain a Silver. |
| **Litter** | $5 | Action | +2 Cards, +2 Actions, +1 Debt. |
| **Rice Broker** | $5 | Action | +1 Action. Trash a card from your hand. If it's a Treasure, +2 Cards. If it's an Action, +5 Cards. |
| **Ronin** | $5 | Action - Shadow | Draw until you have 7 cards in hand. You can play this from your deck as if in your hand. |
| **Tanuki** | $5 | Action - Shadow | Trash a card from your hand. Gain a card costing up to $2 more than it. You can play this from your deck as if in your hand. |
| **Tea House** | $5 | Action - Omen | +1 Sun. +1 Card, +1 Action, +$2. |
| **Samurai** | $6 | Action - Attack - Duration | Each other player discards down to 3 cards in hand (once). At the start of each of your turns this game, +$1. (This stays in play.) |
| **Rice** | $7 | Treasure | +1 Buy. +$1 per different type among cards you have in play. |

### Seaside Kingdom cards (26)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Embargo** | $2 | Action | +$2. Trash this: put an Embargo token on a Supply pile. When a player buys a card from that pile, they gain a Curse for each token on it. |
| **Haven** | $2 | Action - Duration | +1 Card, +1 Action. Set aside a card from your hand face down. At the start of your next turn, put it into your hand. |
| **Lighthouse** | $2 | Action - Duration | +1 Action, +$1. At the start of your next turn: +$1. Until then, when another player plays an Attack card, it doesn't affect you. |
| **Native Village** | $2 | Action | +2 Actions. Choose one: set aside the top card of your deck face down on your Native Village mat; or put all the cards from your mat into your hand. |
| **Pearl Diver** | $2 | Action | +1 Card, +1 Action. Look at the bottom card of your deck. You may put it on top. |
| **Ambassador** | $3 | Action - Attack | Reveal a card from your hand. Return up to 2 copies of it from your hand to the Supply. Then each other player gains a copy of it. |
| **Fishing Village** | $3 | Action - Duration | +2 Actions, +$1. At the start of your next turn: +1 Action, +$1. |
| **Lookout** | $3 | Action | +1 Action. Look at the top 3 cards of your deck. Trash one of them. Discard one of them. Put the other one back on top of your deck. |
| **Smugglers** | $3 | Action | Gain a copy of a card costing up to $6 that the player to your right gained on their last turn. |
| **Warehouse** | $3 | Action | +3 Cards, +1 Action. Discard 3 cards. |
| **Caravan** | $4 | Action - Duration | +1 Card, +1 Action. At the start of your next turn: +1 Card. |
| **Cutpurse** | $4 | Action - Attack | +$2. Each other player discards a Copper (or reveals a hand with no Copper). |
| **Island** | $4 | Action - Victory | 2 VP. Put this and a card from your hand onto your Island mat. |
| **Navigator** | $4 | Action | +$2. Look at the top 5 cards of your deck. Either discard all of them, or put them back on top of your deck in any order. |
| **Pirate Ship** | $4 | Action - Attack | Choose one: each other player reveals the top 2 cards of their deck, trashes a revealed Treasure that you choose, and discards the rest; if anyone trashed a Treasure, you take a coin token. Or +$1 per coin token you have taken with Pirate Ships this game. |
| **Salvager** | $4 | Action | +1 Buy. Trash a card from your hand. +$ equal to its cost. |
| **Sea Hag** | $4 | Action - Attack | Each other player discards the top card of their deck, then gains a Curse onto their deck. |
| **Treasure Map** | $4 | Action | Trash this and a Treasure Map from your hand. If you trashed two Treasure Maps, gain 4 Golds onto your deck. |
| **Bazaar** | $5 | Action | +1 Card, +2 Actions, +$1. |
| **Explorer** | $5 | Action | You may reveal a Province from your hand. If you do, gain a Gold to your hand. If you don't, gain a Silver to your hand. |
| **Ghost Ship** | $5 | Action - Attack | +2 Cards. Each other player with 4 or more cards in hand puts cards from their hand onto their deck until they have 3 cards in hand. |
| **Merchant Ship** | $5 | Action - Duration | +$2. At the start of your next turn: +$2. |
| **Outpost** | $5 | Action - Duration | You only draw 3 cards for your next hand. Take an extra turn after this one (but not a 3rd turn in a row). |
| **Tactician** | $5 | Action - Duration | Discard your hand. If you discarded any cards this way, then at the start of your next turn: +5 Cards, +1 Action, +1 Buy. |
| **Treasury** | $5 | Action | +1 Card, +1 Action, +$1. When you discard this from play, if you didn't buy a Victory card this turn, you may put this onto your deck. |
| **Wharf** | $5 | Action - Duration | +2 Cards, +1 Buy. At the start of your next turn: +2 Cards, +1 Buy. |

### Dark Ages supporting cards (21, not Kingdom piles: Knights, Ruins, Shelters, Spoils, Madman, Mercenary)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Abandoned Mine** | $0 | Action - Ruins | +$1 |
| **Madman** | $0 | Action | +2 Actions. Return this to the Madman pile. If you do, +1 Card per card in your hand. |
| **Mercenary** | $0 | Action - Attack | You may trash 2 cards from your hand. If you do, +2 Cards, +$2, and each other player discards down to 3 cards in hand. |
| **Ruined Library** | $0 | Action - Ruins | +1 Card |
| **Ruined Market** | $0 | Action - Ruins | +1 Buy |
| **Ruined Village** | $0 | Action - Ruins | +1 Action |
| **Spoils** | $0 | Treasure | $3. When you play this, return it to the Spoils pile. |
| **Survivors** | $0 | Action - Ruins | Look at the top 2 cards of your deck. Discard them or put them back in any order. |
| **Hovel** | $1 | Reaction - Shelter | When you buy a Victory card, you may trash this from your hand. |
| **Necropolis** | $1 | Action - Shelter | +2 Actions |
| **Overgrown Estate** | $1 | Shelter - Victory | 0 VP. When you trash this, +1 Card. |
| **Sir Martin** | $4 | Action - Attack - Knight | +2 Buys. Each other player reveals the top 2 cards of their deck, trashes one costing from $3 to $6, and discards the rest. If a Knight was trashed, trash this. |
| **Dame Anna** | $5 | Action - Attack - Knight | You may trash up to 2 cards from your hand. Each other player reveals the top 2 cards of their deck, trashes one costing from $3 to $6, and discards the rest. If a Knight was trashed, trash this. |
| **Dame Josephine** | $5 | Action - Attack - Knight - Victory | 2 VP. Each other player reveals the top 2 cards of their deck, trashes one costing from $3 to $6, and discards the rest. If a Knight was trashed, trash this. |
| **Dame Molly** | $5 | Action - Attack - Knight | +2 Actions. Each other player reveals the top 2 cards of their deck, trashes one costing from $3 to $6, and discards the rest. If a Knight was trashed, trash this. |
| **Dame Natalie** | $5 | Action - Attack - Knight | You may gain a card costing up to $3. Each other player reveals the top 2 cards of their deck, trashes one costing from $3 to $6, and discards the rest. If a Knight was trashed, trash this. |
| **Dame Sylvia** | $5 | Action - Attack - Knight | +$2. Each other player reveals the top 2 cards of their deck, trashes one costing from $3 to $6, and discards the rest. If a Knight was trashed, trash this. |
| **Sir Bailey** | $5 | Action - Attack - Knight | +1 Card, +1 Action. Each other player reveals the top 2 cards of their deck, trashes one costing from $3 to $6, and discards the rest. If a Knight was trashed, trash this. |
| **Sir Destry** | $5 | Action - Attack - Knight | +2 Cards. Each other player reveals the top 2 cards of their deck, trashes one costing from $3 to $6, and discards the rest. If a Knight was trashed, trash this. |
| **Sir Michael** | $5 | Action - Attack - Knight | Each other player discards down to 3 cards in hand. Each other player reveals the top 2 cards of their deck, trashes one costing from $3 to $6, and discards the rest. If a Knight was trashed, trash this. |
| **Sir Vander** | $5 | Action - Attack - Knight | Each other player reveals the top 2 cards of their deck, trashes one costing from $3 to $6, and discards the rest. If a Knight was trashed, trash this. When you trash this, gain a Gold. |

### Adventures Traveller upgrade cards (8, not Kingdom piles: Page and Peasant exchange up the line, 5 of each outside the Supply)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Soldier** | $3 | Action - Attack - Traveller | +$2. +$1 per other Attack you have in play. Each other player with 4 or more cards in hand discards a card. When you discard this from play, you may exchange it for a Fugitive. |
| **Treasure Hunter** | $3 | Action - Traveller | +1 Action, +$1. Gain a Silver per card the player to your right gained on their last turn. When you discard this from play, you may exchange it for a Warrior. |
| **Fugitive** | $4 | Action - Traveller | +2 Cards, +1 Action. Discard a card. When you discard this from play, you may exchange it for a Disciple. |
| **Warrior** | $4 | Action - Attack - Traveller | +2 Cards. For each Traveller you have in play (including this), each other player discards the top card of their deck and trashes it if it costs $3 or $4. When you discard this from play, you may exchange it for a Hero. |
| **Disciple** | $5 | Action - Traveller | You may play an Action card from your hand twice. Gain a copy of it. When you discard this from play, you may exchange it for a Teacher. |
| **Hero** | $5 | Action - Traveller | +$2. Gain a Treasure. When you discard this from play, you may exchange it for a Champion. |
| **Champion** | $6 | Action - Duration - Traveller | +1 Action. For the rest of the game, when another player plays an Attack card, it does not affect you, and when you play an Action card, +1 Action. |
| **Teacher** | $6 | Action - Reserve - Traveller | Put this on your Tavern mat. Call: at the start of your turn, you may call this to move your +1 Card, +1 Action, +1 Buy or +$1 token to an Action Supply pile you have no tokens on. |

### Adventures Events (20, bought with a Buy instead of gained; Events and Landmarks together: at most two per game)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Alms** | $0 | Event | Once per turn: if you have no Treasures in play, gain a card costing up to $4. |
| **Borrow** | $0 | Event | Once per turn: +1 Buy. If your -1 Card token is not on your deck, put it there and +$1. |
| **Quest** | $0 | Event | You may discard an Attack, two Curses, or six cards. If you did, gain a Gold. |
| **Save** | $1 | Event | Once per turn: +1 Buy. Set aside a card from your hand, and put it into your hand at end of turn (after drawing). |
| **Scouting Party** | $2 | Event | +1 Buy. Look at the top 5 cards of your deck. Discard 3 of them and put the rest back in any order. |
| **Travelling Fair** | $2 | Event | +2 Buys. When you gain a card this turn, you may put it onto your deck. |
| **Bonfire** | $3 | Event | Trash up to 2 cards you have in play. |
| **Expedition** | $3 | Event | Draw 2 extra cards for your next hand. |
| **Ferry** | $3 | Event | Move your -$2 cost token to an Action Supply pile (cards from that pile cost $2 less on your turn). |
| **Plan** | $3 | Event | Move your Trashing token to an Action Supply pile (when you buy a card from that pile, you may trash a card from your hand). |
| **Mission** | $4 | Event | Once per turn: take another turn after this one (not directly after another extra turn), in which you cannot buy cards. |
| **Pilgrimage** | $4 | Event | Once per turn: turn your Journey token over (it starts face up). If it is face up, choose up to 3 differently named cards you have in play and gain a copy of each. |
| **Ball** | $5 | Event | Take your -$1 token. Gain 2 cards each costing up to $4. |
| **Raid** | $5 | Event | Gain a Silver per Silver you have in play. Each other player puts their -1 Card token on their deck. |
| **Seaway** | $5 | Event | Gain an Action card costing up to $4. Move your +1 Buy token to its pile. |
| **Trade** | $5 | Event | Trash up to 2 cards from your hand. Gain a Silver per card you trashed. |
| **Lost Arts** | $6 | Event | Move your +1 Action token to an Action Supply pile (when you play a card from it, +1 Action). |
| **Training** | $6 | Event | Move your +$1 token to an Action Supply pile (when you play a card from it, +$1). |
| **Inheritance** | $7 | Event | Set aside a non-Victory Action card from the Supply costing up to $4. Your Estates become Actions that play as that card. |
| **Pathfinding** | $8 | Event | Move your +1 Card token to an Action Supply pile (when you play a card from it, +1 Card). |

### Empires supporting cards (13, not Kingdom piles: the bottom halves of the split piles and the eight Castles)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Humble Castle** | $3 | Castle - Treasure - Victory | $1. Worth 1 VP per Castle you have. |
| **Crumbling Castle** | $4 | Castle - Victory | 1 VP. When you gain or trash this, +1 VP and gain a Silver. |
| **Rocks** | $4 | Treasure | $1. When you gain or trash this, gain a Silver; if it is your Buy phase, put the Silver on your deck, otherwise into your hand. (Bottom half of the Catapult/Rocks pile.) |
| **Bustling Village** | $5 | Action | +1 Card, +3 Actions. Look through your discard pile. You may reveal a Settlers from it and put it into your hand. (Bottom half of the Settlers/Bustling Village pile.) |
| **Emporium** | $5 | Action | +1 Card, +1 Action, +$1. When you gain this, if you have at least 5 Action cards in play, +2 VP. (Bottom half of the Patrician/Emporium pile.) |
| **Plunder** | $5 | Action | +$2, +1 VP. (Bottom half of the Encampment/Plunder pile.) |
| **Small Castle** | $5 | Action - Castle - Victory | Trash this or a Castle from your hand. If you do, gain a Castle. 2 VP. |
| **Haunted Castle** | $6 | Castle - Victory | 2 VP. When you gain this during your turn, gain a Gold, and each other player with 5 or more cards in hand puts 2 cards from their hand onto their deck. |
| **Opulent Castle** | $7 | Action - Castle - Victory | Discard any number of Victory cards. +$2 per card discarded. 3 VP. |
| **Fortune** | $8 + 8D | Treasure | +1 Buy. When you play this, double your $ if you have not yet this turn. When you gain this, gain a Gold per Gladiator you have in play. Costs $8 and 8 Debt. (Bottom half of the Gladiator/Fortune pile.) |
| **Sprawling Castle** | $8 | Castle - Victory | 4 VP. When you gain this, gain a Duchy or 3 Estates. |
| **Grand Castle** | $9 | Castle - Victory | 5 VP. When you gain this, reveal your hand. +1 VP per Victory card in your hand and in play. |
| **King's Castle** | $10 | Castle - Victory | Worth 2 VP per Castle you have. |

### Empires Events (13, bought with a Buy instead of gained; Debt costs are paid as Debt tokens)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Advance** | $0 | Event | You may trash an Action card from your hand. If you do, gain an Action card costing up to $6. |
| **Annex** | 8D | Event | Look through your discard pile. Choose up to 5 cards from it and shuffle the rest into your deck. Gain a Duchy. (Costs 8 Debt.) |
| **Donate** | 8D | Event | After this turn, put all cards from your deck and discard pile into your hand, trash any number of them, shuffle the rest into your deck, then draw 5 cards. (Costs 8 Debt.) |
| **Triumph** | 5D | Event | Gain an Estate. If you did, +1 VP per card you have gained this turn. (Costs 5 Debt.) |
| **Delve** | $2 | Event | +1 Buy. Gain a Silver. |
| **Tax** | $2 | Event | Add 2 Debt to a Supply pile. (Setup: add 1 Debt to each Supply pile.) When a player buys a card, they take the Debt from its pile. |
| **Banquet** | $3 | Event | Gain two Coppers and a non-Victory card costing up to $5. |
| **Ritual** | $4 | Event | Gain a Curse. If you do, trash a card from your hand. +1 VP per $1 it costs. |
| **Salt the Earth** | $4 | Event | +1 VP. Trash a Victory card from the Supply. |
| **Wedding** | $4 + 3D | Event | +1 VP. Gain a Gold. (Costs $4 and 3 Debt.) |
| **Windfall** | $5 | Event | If your deck and discard pile are empty, gain 3 Golds. |
| **Conquest** | $6 | Event | Gain 2 Silvers. +1 VP per Silver you have gained this turn. |
| **Dominate** | $14 | Event | Gain a Province. If you do, +9 VP. |

### Empires Landmarks (21, standing rules for the whole game; never bought or gained)

* **Aqueduct:** When you gain a Treasure, move 1 VP from its pile to this. When you gain a Victory card, take the VP from this. Setup: put 8 VP on the Silver and Gold piles.
* **Arena:** At the start of your Buy phase, you may discard an Action card. If you do, take 2 VP from here. Setup: 6 VP here per player.
* **Bandit Fort:** When scoring, -2 VP for each Silver and each Gold you have.
* **Basilica:** When you buy a card, if you have $2 or more left, take 2 VP from here. Setup: 6 VP here per player.
* **Baths:** When you end your turn without having gained a card, take 2 VP from here. Setup: 6 VP here per player.
* **Battlefield:** When you gain a Victory card, take 2 VP from here. Setup: 6 VP here per player.
* **Colonnade:** When you gain an Action card in your Buy phase, if you have a copy of it in play, take 2 VP from here. Setup: 6 VP here per player.
* **Defiled Shrine:** When you gain an Action, move 1 VP from its pile to this. When you buy a Curse, take the VP from this. Setup: put 2 VP on each non-Gathering Action Supply pile.
* **Fountain:** When scoring, 15 VP if you have at least 10 Coppers.
* **Keep:** When scoring, 5 VP per differently named Treasure you have that you have more copies of than each other player, or tied for most.
* **Labyrinth:** When you gain a 2nd card in one of your turns, take 2 VP from here. Setup: 6 VP here per player.
* **Mountain Pass:** When you are the first player to gain a Province, after that turn, each player bids once, up to 40 Debt, ending with you. The high bidder gets +8 VP and takes the Debt they bid.
* **Museum:** When scoring, 2 VP per differently named card you have.
* **Obelisk:** When scoring, 2 VP per card you have from the chosen pile. Setup: choose a random Action Supply pile.
* **Orchard:** When scoring, 4 VP per differently named Action card you have 3 or more copies of.
* **Palace:** When scoring, 3 VP per set you have of Copper-Silver-Gold.
* **Tomb:** When you trash a card, +1 VP.
* **Tower:** When scoring, 1 VP per non-Victory card you have from an empty Supply pile.
* **Triumphal Arch:** When scoring, 3 VP per copy you have of the 2nd most common Action card among your cards (if it is a tie, count either).
* **Wall:** When scoring, -1 VP per card you have after the first 15.
* **Wolf Den:** When scoring, -3 VP per card you have exactly one copy of.

### Nocturne supporting cards (15, not Kingdom piles: the 7 Heirlooms, the Spirits Will-o'-Wisp, Imp and Ghost, Bat, Wish and the 3 Zombies)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Haunted Mirror** | $0 | Heirloom - Treasure | $1. When you trash this, you may discard an Action card, to gain a Ghost. |
| **Magic Lamp** | $0 | Heirloom - Treasure | $1. When you play this, if there are at least 6 cards that you have exactly 1 copy of in play, trash this. If you do, gain 3 Wishes from their pile. |
| **Will-o'-Wisp** | $0 | Action - Spirit | +1 Card, +1 Action. Reveal the top card of your deck. If it costs $2 or less, put it into your hand. (This is not in the Supply.) |
| **Wish** | $0 | Action | +1 Action. Return this to its pile. If you did, gain a card to your hand costing up to $6. (This is not in the Supply.) |
| **Bat** | $2 | Night | Trash up to 2 cards from your hand. If you trashed at least one, exchange this for a Vampire. (This is not in the Supply.) |
| **Goat** | $2 | Heirloom - Treasure | $1. When you play this, you may trash a card from your hand. |
| **Imp** | $2 | Action - Spirit | +2 Cards. You may play an Action card from your hand that you don't have a copy of in play. (This is not in the Supply.) |
| **Pasture** | $2 | Heirloom - Treasure - Victory | $1. Worth 1 VP per Estate you have. |
| **Pouch** | $2 | Heirloom - Treasure | $1. +1 Buy. |
| **Zombie Apprentice** | $3 | Action - Zombie | You may trash an Action card from your hand for +3 Cards and +1 Action. (Starts in the trash; only Necromancer can play it.) |
| **Zombie Mason** | $3 | Action - Zombie | Trash the top card of your deck. You may gain a card costing up to $1 more than it. (Starts in the trash; only Necromancer can play it.) |
| **Zombie Spy** | $3 | Action - Zombie | +1 Card, +1 Action. Look at the top card of your deck. Discard it or put it back. (Starts in the trash; only Necromancer can play it.) |
| **Cursed Gold** | $4 | Heirloom - Treasure | $3. When you play this, gain a Curse. |
| **Ghost** | $4 | Duration - Night - Spirit | Reveal cards from your deck until you reveal an Action. Discard the other cards and set aside the Action. At the start of your next turn, play it twice. (This is not in the Supply.) |
| **Lucky Coin** | $4 | Heirloom - Treasure | $1. When you play this, gain a Silver. |

### Nocturne Boons (12, received by the turn's player; Fate cards bring them into the game)

* **The Earth's Gift:** You may discard a Treasure to gain a card costing up to $4.
* **The Field's Gift:** +1 Action, +$1. (Keep this until Clean-up.)
* **The Flame's Gift:** You may trash a card from your hand.
* **The Forest's Gift:** +1 Buy, +$1. (Keep this until Clean-up.)
* **The Moon's Gift:** Look through your discard pile. You may put a card from it onto your deck.
* **The Mountain's Gift:** Gain a Silver.
* **The River's Gift:** +1 Card at the end of this turn. (Keep this until Clean-up.)
* **The Sea's Gift:** +1 Card.
* **The Sky's Gift:** You may discard 3 cards to gain a Gold.
* **The Sun's Gift:** Look at the top 4 cards of your deck. Discard any number of them and put the rest back in any order.
* **The Swamp's Gift:** Gain a Will-o'-Wisp from its pile.
* **The Wind's Gift:** +2 Cards, then discard 2 cards.

### Nocturne Hexes (12, received by other players; Doom cards bring them into the game)

* **Bad Omens:** Put your deck into your discard pile. Look through it and put 2 Coppers from it onto your deck (or reveal you can't).
* **Delusion:** If you don't have Deluded or Envious, take Deluded.
* **Envy:** If you don't have Deluded or Envious, take Envious.
* **Famine:** Reveal the top 3 cards of your deck. Discard the Actions. Shuffle the rest into your deck.
* **Fear:** If you have at least 5 cards in hand, discard an Action or Treasure (or reveal you can't).
* **Greed:** Gain a Copper onto your deck.
* **Haunting:** If you have at least 4 cards in hand, put one of them onto your deck.
* **Locusts:** Trash the top card of your deck. If it's Copper or Estate, gain a Curse. Otherwise, gain a cheaper card that shares a type with it.
* **Misery:** If this is your first Misery this game, take Miserable. Otherwise, flip it over to Twice Miserable.
* **Plague:** Gain a Curse to your hand.
* **Poverty:** Discard down to 3 cards in hand.
* **War:** Reveal cards from your deck until revealing one costing $3 or $4. Trash it and discard the rest.

### Nocturne States (5)

* **Deluded:** At the start of your Buy phase, return this, and you can't buy Actions this turn.
* **Envious:** At the start of your Buy phase, return this, and Silver and Gold make $1 this turn.
* **Miserable:** When scoring, -2 VP.
* **Twice Miserable:** When scoring, -4 VP.
* **Lost in the Woods:** At the start of your turn, you may discard a card to receive a Boon.

### Renaissance Projects (20, bought with a Buy and their cost in $ instead of gained; a cube on one is a permanent ability; Events, Landmarks and Projects together: at most two per game)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Cathedral** | $3 | Project | At the start of your turn, trash a card from your hand. |
| **City Gate** | $3 | Project | At the start of your turn, +1 Card, then put a card from your hand onto your deck. |
| **Pageant** | $3 | Project | At the end of your Buy phase, you may pay $1 for +1 Coffers. |
| **Star Chart** | $3 | Project | When you shuffle, you may pick one of the cards to go on top. |
| **Exploration** | $4 | Project | At the end of your Buy phase, if you didn't buy any cards, +1 Coffers and +1 Villager. |
| **Fair** | $4 | Project | At the start of your turn, +1 Buy. |
| **Sewers** | $4 | Project | When you trash a card other than with this, you may trash a card from your hand. |
| **Silos** | $4 | Project | At the start of your turn, discard any number of Coppers, revealed, and draw that many cards. |
| **Sinister Plot** | $4 | Project | At the start of your turn, add a token here, or remove your tokens here for +1 Card each. |
| **Academy** | $5 | Project | When you gain an Action card, +1 Villager. |
| **Capitalism** | $5 | Project | During your turns, Actions with + amounts in their text are also Treasures. |
| **Fleet** | $5 | Project | After the game ends, there's an extra round of turns just for players with this. |
| **Guildhall** | $5 | Project | When you gain a Treasure, +1 Coffers. |
| **Piazza** | $5 | Project | At the start of your turn, reveal the top card of your deck. If it's an Action, play it. |
| **Road Network** | $5 | Project | When another player gains a Victory card, +1 Card. |
| **Barracks** | $6 | Project | At the start of your turn, +1 Action. |
| **Crop Rotation** | $6 | Project | At the start of your turn, you may discard a Victory card for +2 Cards. |
| **Innovation** | $6 | Project | The first time you gain an Action card in each of your turns, you may set it aside. If you do, play it. |
| **Canal** | $7 | Project | During your turns, cards cost $1 less, but not less than $0. |
| **Citadel** | $8 | Project | The first time you play an Action card during each of your turns, play it again afterwards. |

### Renaissance Artifacts (5, taken by Kingdom cards; only one player has each at a time)

* **Flag:** When drawing your hand, +1 Card.
* **Horn:** Once per turn, when you discard a Border Guard from play, you may put it onto your deck.
* **Key:** At the start of your turn, +$1.
* **Lantern:** Your Border Guards reveal 3 cards and discard 2. (It takes all 3 being Actions to take the Horn.)
* **Treasure Chest:** At the start of your Buy phase, gain a Gold.

### Allies cards inside the split piles (24, not Kingdom piles of their own: Augurs, Clashes, Forts, Odysseys, Townsfolk and Wizards each hold 4 copies of 4 cards, cheapest on top)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Town Crier** | $2 | Action - Townsfolk | Choose one: +$2; or gain a Silver; or +1 Card and +1 Action. You may rotate the Townsfolk. |
| **Battle Plan** | $3 | Action - Clash | +1 Card, +1 Action. You may reveal an Attack card from your hand for +1 Card. You may rotate any Supply pile. |
| **Blacksmith** | $3 | Action - Townsfolk | Choose one: draw until you have 6 cards in hand; or +2 Cards; or +1 Card and +1 Action. You may rotate the Townsfolk. |
| **Herb Gatherer** | $3 | Action - Augur | +1 Buy. Put your deck into your discard pile. Look through it and you may play a Treasure from it. You may rotate the Augurs. |
| **Old Map** | $3 | Action - Odyssey | +1 Card, +1 Action. Discard a card. +1 Card. You may rotate the Odysseys. |
| **Student** | $3 | Action - Liaison - Wizard | +1 Action. You may rotate the Wizards. Trash a card from your hand. If it's a Treasure, +1 Favor and put this onto your deck. |
| **Tent** | $3 | Action - Fort | +$2. You may rotate the Forts. When you discard this from play, you may put it onto your deck. |
| **Acolyte** | $4 | Action - Augur | You may trash an Action or Victory card from your hand to gain a Gold. You may trash this to gain an Augur. |
| **Archer** | $4 | Action - Attack - Clash | +$2. Each other player with 5 or more cards in hand reveals all but one, and discards one of those cards that you choose. |
| **Conjurer** | $4 | Action - Duration - Wizard | Gain a card costing up to $4. At the start of your next turn, put this into your hand. |
| **Garrison** | $4 | Action - Duration - Fort | +$2. This turn, when you gain a card, add a token here. At the start of your next turn, remove them for +1 Card each. |
| **Miller** | $4 | Action - Townsfolk | +1 Action. Look at the top 4 cards of your deck. Put one into your hand and discard the rest. |
| **Voyage** | $4 | Action - Duration - Odyssey | +1 Action. Take an extra turn after this one (but not a 3rd turn in a row), during which you can only play 3 cards from your hand. |
| **Elder** | $5 | Action - Townsfolk | +$2. You may play an Action card from your hand. When it gives you a choice of abilities (e.g. "choose one") this turn, you may choose an extra (different) option. |
| **Hill Fort** | $5 | Action - Fort | Gain a card costing up to $4. Choose one: put it into your hand; or +1 Card and +1 Action. |
| **Sorcerer** | $5 | Action - Attack - Wizard | +1 Card, +1 Action. Each other player names a card, then reveals the top card of their deck. If wrong, they gain a Curse. |
| **Sorceress** | $5 | Action - Attack - Augur | +1 Action. Name a card. Reveal the top card of your deck and put it into your hand. If it's the named card, each other player gains a Curse. |
| **Sunken Treasure** | $5 | Odyssey - Treasure | Gain an Action card you don't have a copy of in play. |
| **Warlord** | $5 | Action - Attack - Clash - Duration | +1 Action. At the start of your next turn, +2 Cards. Until then, other players can't play an Action from their hand that they have 2 or more copies of in play. |
| **Distant Shore** | $6 | Action - Odyssey - Victory | +2 Cards, +1 Action. Gain an Estate. \| 2 VP. |
| **Lich** | $6 | Action - Wizard | +6 Cards, +2 Actions. Skip a turn. \| When you trash this, discard it and gain a cheaper card from the trash. |
| **Sibyl** | $6 | Action - Augur | +4 Cards, +1 Action. Put a card from your hand on top of your deck, and another on the bottom. |
| **Stronghold** | $6 | Action - Duration - Fort - Victory | Choose one: +$3; or at the start of your next turn, +3 Cards. \| 2 VP. |
| **Territory** | $6 | Clash - Victory | Worth 1 VP per differently named Victory card you have. \| When you gain this, gain a Gold per empty Supply pile. |

### Allies (23, one is used when a Liaison is in the Kingdom: what Favors can be spent on)

* **Architects' Guild:** When you gain a card, you may spend 2 Favors to gain a cheaper non-Victory card.
* **Band of Nomads:** When you gain a card costing $5 or more, you may spend a Favor, for +1 Card, or +1 Action, or +1 Buy.
* **Cave Dwellers:** At the start of your turn, you may spend a Favor, to discard a card then draw a card. Repeat as desired.
* **Circle of Witches:** After playing a Liaison, you may spend 3 Favors to have each other player gain a Curse.
* **City-state:** When you gain an Action card during your turn, you may spend 2 Favors to play it.
* **Coastal Haven:** When discarding your hand in Clean-up, you may spend any number of Favors, to keep that many cards in hand for next turn (you still draw 5).
* **Crafters' Guild:** At the start of your turn, you may spend 2 Favors to gain a card costing up to $4 onto your deck.
* **Desert Guides:** At the start of your turn, you may spend a Favor, to discard your hand and draw 5 cards. Repeat as desired.
* **Family of Inventors:** At the start of your Buy phase, you may spend a Favor, to put a Favor token on a non-Victory Supply pile (cards from that pile cost $1 less per Favor token on it).
* **Fellowship of Scribes:** After playing an Action, if you have 4 or fewer cards in hand, you may spend a Favor for +1 Card.
* **Forest Dwellers:** At the start of your turn, you may spend a Favor, to look at the top 3 cards of your deck. Discard any number of them and put the rest back in any order.
* **Gang of Pickpockets:** At the start of your turn, discard down to 4 cards in hand unless you spend a Favor.
* **Island Folk:** At the end of your turn, you may spend 5 Favors, to take an extra turn after this one (but not a 3rd turn in a row).
* **League of Bankers:** At the start of your Buy phase, +$1 per 4 Favors you have (round down).
* **League of Shopkeepers:** After playing a Liaison, if you have at least 5 Favors, +$1; at least 10, +1 Action and +1 Buy.
* **Market Towns:** At the start of your Buy phase, you may spend a Favor, to play an Action card from your hand. Repeat as desired.
* **Mountain Folk:** At the start of your turn, you may spend 5 Favors, for +3 Cards.
* **Order of Astrologers:** When shuffling, you may pick one of the cards being shuffled per Favor you spend, to put on top of your deck.
* **Order of Masons:** When shuffling, you may pick up to 2 of the cards being shuffled per Favor you spend, to put into your discard pile instead.
* **Peaceful Cult:** At the start of your Buy phase, you may spend any number of Favors, to trash that many cards from your hand.
* **Plateau Shepherds:** At the end of the game, pair up Favors with cards you have costing $2: 2 VP per pair.
* **Trappers' Lodge:** When you gain a card, you may spend a Favor, to put it onto your deck.
* **Woodworkers' Guild:** At the start of your Buy phase, you may spend a Favor, to trash an Action card from your hand. If you did, gain an Action card.

### Menagerie supporting cards (1, not a Kingdom pile: the Horse pile of 30 outside the Supply)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Horse** | $3 | Action | +2 Cards, +1 Action. Return this to the Horse pile. (Not in the Supply.) |

### Menagerie Events (20, bought with a Buy instead of gained; Events, Landmarks, Projects and Ways together: at most two per game)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Delay** | $0 | Event | You may set aside an Action card from your hand. At the start of your next turn, play it. |
| **Desperation** | $0 | Event | Once per turn: You may gain a Curse. If you do, +1 Buy and +$2. |
| **Gamble** | $2 | Event | +1 Buy. Reveal the top card of your deck. If it's a Treasure or Action, you may play it. Otherwise, discard it. |
| **Invest** | $2 | Event | Exile an Action from the Supply. While it's in Exile, when another player gains or Invests in a copy of it, +2 Cards. |
| **Pursue** | $2 | Event | Name a card. Reveal the top 4 cards of your deck. Put the ones matching the named card back and discard the rest. |
| **Ride** | $2 | Event | Gain a Horse. |
| **Toil** | $2 | Event | +1 Buy. You may play an Action card from your hand. |
| **Enhance** | $3 | Event | You may trash an Action or Treasure from your hand. Gain a card costing up to $2 more than it. |
| **March** | $3 | Event | Look through your discard pile. You may play an Action from it. |
| **Transport** | $3 | Event | Choose one: Exile an Action from the Supply; or put an Action card from your Exile mat onto your deck. |
| **Banish** | $4 | Event | Exile any number of cards with the same name from your hand. |
| **Bargain** | $4 | Event | Gain a non-Victory card costing up to $5. Each other player gains a Horse. |
| **Seize the Day** | $4 | Event | Once per game: Take an extra turn after this one (but not a 3rd turn in a row). |
| **Commerce** | $5 | Event | Gain a Gold per differently named card you've gained this turn. |
| **Demand** | $5 | Event | Gain a Horse and a card costing up to $4, both onto your deck. |
| **Stampede** | $5 | Event | You can only buy this if you have 5 or fewer cards in play. Gain 5 Horses onto your deck. |
| **Reap** | $7 | Event | Gain a Gold. Set it aside, and play it at the start of your next turn. |
| **Enclave** | $8 | Event | Gain a Gold. Exile a Duchy from the Supply. |
| **Alliance** | $10 | Event | Gain a Province, a Duchy, an Estate, a Gold, a Silver, and a Copper. |
| **Populate** | $10 | Event | Gain one card from each Action Supply pile. |

### Menagerie Ways (20, a standing option for every Action played: do the Way instead of what the card says; at most one per game)

* **Way of the Butterfly:** You may return this to its pile to gain a card costing exactly $1 more than it.
* **Way of the Camel:** Exile a Gold from the Supply.
* **Way of the Chameleon:** Follow this card's instructions; each time that would give you +Cards this turn, you get +$ instead, and vice-versa.
* **Way of the Frog:** +1 Action. When you discard this from play this turn, put it onto your deck.
* **Way of the Goat:** Trash a card from your hand.
* **Way of the Horse:** +2 Cards, +1 Action. Return this to its pile.
* **Way of the Mole:** +1 Action. Discard your hand. +3 Cards.
* **Way of the Monkey:** Until your next turn, when the player to your right gains a card, +1 Card.
* **Way of the Mouse:** Play the set-aside card, leaving it there. (Setup: set aside an unused Action Kingdom card costing $2 or $3.)
* **Way of the Mule:** +1 Action, +$1.
* **Way of the Otter:** Draw 2 cards.
* **Way of the Owl:** Draw until you have 6 cards in hand.
* **Way of the Ox:** +2 Actions.
* **Way of the Pig:** +1 Card, +1 Action, +1 Buy.
* **Way of the Rat:** You may discard a Treasure to gain a copy of this.
* **Way of the Seal:** This turn, when you gain a card, you may put it onto your deck.
* **Way of the Sheep:** +$2.
* **Way of the Squirrel:** +2 Cards at the end of this turn.
* **Way of the Turtle:** Set this aside. If you did, play it at the start of your next turn.
* **Way of the Worm:** Exile an Estate from the Supply.

### Plunder Loot cards (15, not Kingdom piles: 2 of each form the shuffled Loot pile outside the Supply; all are Treasures costing $7)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Amphora** | $7 | Duration - Loot - Treasure | Either now or at the start of your next turn: +1 Buy and +$3. |
| **Doubloons** | $7 | Loot - Treasure | $3. When you gain this, gain a Gold. |
| **Endless Chalice** | $7 | Duration - Loot - Treasure | Now and at the start of each of your turns for the rest of the game: +1 Buy. |
| **Figurehead** | $7 | Duration - Loot - Treasure | At the start of your next turn, +2 Cards. |
| **Hammer** | $7 | Loot - Treasure | Gain a card costing up to $4. |
| **Insignia** | $7 | Loot - Treasure | This turn, when you gain a card, you may put it onto your deck. |
| **Jewels** | $7 | Duration - Loot - Treasure | +1 Buy. At the start of your next turn, put this on the bottom of your deck. |
| **Orb** | $7 | Loot - Treasure | Look through your discard pile. Choose one: Play an Action or Treasure from it; or +1 Buy and +$3. |
| **Prize Goat** | $7 | Loot - Treasure | +1 Buy. You may trash a card from your hand. |
| **Puzzle Box** | $7 | Loot - Treasure | +1 Buy. You may set aside a card from your hand face down. Put it into your hand at end of turn. |
| **Sextant** | $7 | Loot - Treasure | +1 Buy. Look at the top 5 cards of your deck. Discard any number. Put the rest back in any order. |
| **Shield** | $7 | Loot - Reaction - Treasure | +1 Buy. When another player plays an Attack, you may first reveal this from your hand to be unaffected. |
| **Spell Scroll** | $7 | Action - Loot - Treasure | Trash this to gain a cheaper card. If it's an Action or Treasure, you may play it. |
| **Staff** | $7 | Loot - Treasure | +1 Buy. You may play an Action from your hand. |
| **Sword** | $7 | Attack - Loot - Treasure | +1 Buy. Each other player discards down to 4 cards in hand. |

### Plunder Events (15, bought with a Buy instead of gained; Events, Landmarks, Projects, Ways and Traits together: at most two per game)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Bury** | $1 | Event | +1 Buy. Put any card from your discard pile on the bottom of your deck. |
| **Avoid** | $2 | Event | +1 Buy. The next time you shuffle this turn, pick up to 3 of those cards to put into your discard pile. |
| **Deliver** | $2 | Event | +1 Buy. This turn, each time you gain a card, set it aside, and put it into your hand at end of turn. |
| **Peril** | $2 | Event | You may trash an Action card from your hand to gain a Loot. |
| **Rush** | $2 | Event | +1 Buy. The next time you gain an Action card this turn, play it. |
| **Foray** | $3 | Event | Discard 3 cards, revealing them. If they have 3 different names, gain a Loot. |
| **Journey** | $3 | Event | Once per turn: If the previous turn wasn't yours, you don't discard cards from play in Clean-up this turn, and take an extra turn after this one. |
| **Launch** | $3 | Event | Once per turn: Return to your Action phase. +1 Card, +1 Action, and +1 Buy. |
| **Maelstrom** | $3 | Event | Trash 3 cards from your hand. Each other player with 5 or more cards in hand trashes one of them. |
| **Mirror** | $3 | Event | +1 Buy. The next time you gain an Action card this turn, gain a copy of it. |
| **Prepare** | $3 | Event | Set aside your hand face up. At the start of your next turn, play those Actions and Treasures in any order, then discard the rest. |
| **Scrounge** | $3 | Event | Choose one: Trash a card from your hand; or gain an Estate from the trash, and if you did, gain a card costing up to $5. |
| **Looting** | $6 | Event | Gain a Loot. |
| **Invasion** | $10 | Event | You may play an Attack from your hand. Gain a Duchy. Gain an Action onto your deck. Gain a Loot; play it. |
| **Prosper** | $10 | Event | Gain a Loot, plus any number of differently named Treasures. |

### Rising Sun Events (10, bought with a Buy; Continue costs only Debt)

| Card | Cost | Type | Effect |
|---|---|---|---|
| **Continue** | 8D | Event | Once per turn: Gain a non-Attack Action card costing up to $4. Return to your Action phase and play it. +1 Action and +1 Buy. |
| **Amass** | $2 | Event | If you have no Action cards in play, gain an Action card costing up to $5. |
| **Asceticism** | $2 | Event | Pay any amount of $ to trash that many cards from your hand. |
| **Credit** | $2 | Event | Gain an Action or Treasure costing up to $8. +Debt equal to its cost. |
| **Foresight** | $2 | Event | Reveal cards from your deck until revealing an Action. Set it aside and discard the rest. Put it into your hand at end of turn. |
| **Kintsugi** | $3 | Event | Trash a card from your hand. If you've gained a Gold this game, gain a card costing up to $2 more than the trashed card. |
| **Practice** | $3 | Event | You may play an Action card from your hand twice. |
| **Sea Trade** | $4 | Event | +1 Card per Action card you have in play. Trash up to that many cards from your hand. |
| **Receive Tribute** | $5 | Event | If you've gained at least 3 cards this turn, gain up to 3 differently named Action cards you don't have copies of in play. |
| **Gather** | $7 | Event | Gain a card costing exactly $3, a card costing exactly $4, and a card costing exactly $5. |

### Rising Sun Prophecies (15, one is used whenever an Omen is in the Kingdom; its rule starts when the last Sun token is removed)

* **Approaching Army:** After you play an Attack card, +$1. Setup: Add an Attack Kingdom card pile to the Supply.
* **Biding Time:** At the start of your Clean-up, set aside your hand face down. At the start of your next turn, put those cards into your hand.
* **Bureaucracy:** When you gain a card that doesn't cost $0, gain a Copper.
* **Divine Wind:** When you remove the last Sun, remove all Kingdom card piles from the Supply, and set up 10 new random piles.
* **Enlightenment:** Treasures are also Actions. When you play a Treasure in an Action phase, instead of following its instructions, +1 Card and +1 Action.
* **Flourishing Trade:** Cards cost $1 less. You may use Action plays as Buys.
* **Good Harvest:** The first time you play each differently named Treasure each turn, first, +1 Buy and +$1.
* **Great Leader:** After each Action card you play, +1 Action.
* **Growth:** When you gain a Treasure, gain a cheaper card.
* **Harsh Winter:** When you gain a card on your turn, if there's Debt on its pile, take it; otherwise put 2 Debt on its pile.
* **Kind Emperor:** At the start of your turn, and when you remove the last Sun: Gain an Action to your hand.
* **Panic:** When you play a Treasure, +2 Buys, and when you discard one from play, return it to its pile.
* **Progress:** When you gain a card, put it onto your deck.
* **Rapid Expansion:** When you gain an Action or Treasure, set it aside, and play it at the start of your next turn.
* **Sickness:** At the start of your turn, choose one: Gain a Curse onto your deck; or discard 3 cards.

### Plunder Traits (15, each lies on one random Action or Treasure Kingdom pile for the whole game)

* **Cheap:** Cheap cards cost $1 less.
* **Cursed:** When you gain a Cursed card, gain a Loot and a Curse.
* **Fated:** When shuffling, you may look through the cards and reveal Fated cards to put them on the top or bottom.
* **Fawning:** When you gain a Province, gain a Fawning card.
* **Friendly:** At the start of your Clean-up phase, you may discard a Friendly card to gain a Friendly card.
* **Hasty:** When you gain a Hasty card, set it aside, and play it at the start of your next turn.
* **Inherited:** Setup: You start the game with an Inherited card in place of a starting card you choose.
* **Inspiring:** After playing an Inspiring card on your turn, you may play an Action from your hand that you don't have a copy of in play.
* **Nearby:** When you gain a Nearby card, +1 Buy.
* **Patient:** At the start of your Clean-up phase, you may set aside Patient cards from your hand to play them at the start of your next turn.
* **Pious:** When you gain a Pious card, you may trash a card from your hand.
* **Reckless:** Follow the instructions of played Reckless cards twice. When discarding one from play, return it to its pile.
* **Rich:** When you gain a Rich card, gain a Silver.
* **Shy:** At the start of your turn, you may discard one Shy card for +2 Cards.
* **Tireless:** When you discard a Tireless card from play, set it aside, and put it onto your deck at end of turn.

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

### Update 12: the Seaside expansion (2009)
* **All 26 cards of the original Seaside**: Embargo, Haven, Lighthouse, Native Village, Pearl Diver, Ambassador, Fishing Village,
  Lookout, Smugglers, Warehouse, Caravan, Cutpurse, Island, Navigator, Pirate Ship, Salvager, Sea Hag, Treasure Map, Bazaar,
  Explorer, Ghost Ship, Merchant Ship, Outpost, Tactician, Treasury, Wharf. Seaside is a fourth card set in the lobby.
* **Duration cards** (Action - Duration): an effect now and another at the start of the owner's next turn. They stay in play
  through cleanup (shown on the player panel as "in play") and are discarded after they have done their second job. A
  Duration card that has nothing left to do (Tactician with an empty hand, Haven with nothing to set aside) is discarded at once.
  A Throne Room that plays a Duration card stays in play with it, and both effects happen twice.
* **Mats and tokens**: the Island mat (cards still count for you, Island is worth 2 VP), the Native Village mat, Haven's
  set-aside card, the Pirate Ship's coin tokens and Embargo tokens on Supply piles (buying from such a pile gains a Curse per
  token; gaining does not).
* **Lighthouse** protects like the Invisibility Cloak against Attacks, but only until the start of its owner's next turn.
* **Outpost**: an extra turn with a 3-card hand, never a third turn in a row. **Treasury** asks at cleanup whether to go back on
  the deck when no Victory card was bought. **Smugglers** looks at what the player on your right gained during their own last turn.
* Rules decisions: Duration cards of a possessed player trigger at the start of the possessed turn (the possessor spends the
  result); an Outpost played during a possessed turn gives no extra turn; if Outpost and Possession are played in the same turn the
  Outpost turn comes first.

### Update 13: the Prosperity expansion (2010 and 2022)
* **Both editions in one set, 34 cards.** The 25 cards of the 2010 edition (Anvil is not among them): Loan, Trade Route, Watchtower,
  Bishop, Monument, Quarry, Talisman, Workers' Village, City, Contraband, Counting House, Mint, Mountebank, Rabble, Royal Seal, Vault,
  Venture, Goons, Grand Market, Hoard, Bank, Expand, Forge, King's Court, Peddler; plus the 9 new cards of the 2022 edition: Anvil, Clerk,
  Investment, Tiara, Charlatan, Collection, Crystal Ball, Magnate, War Chest. Cards in both editions use the 2022 wording (Hoard and
  Collection work "this turn", Mint triggers when gained, Quarry "this turn"). Prosperity is a fifth card set in the lobby.
* **Platinum and Colony** (cost $9 / $11, $5 / 10 VP) join the Supply together. Lobby setting: *Automatic* (a random Kingdom card is picked
  from the seed; if it is a Prosperity card they are used), *Always* or *Never*. An empty Colony pile ends the game.
* **VP tokens** (Bishop, Monument, Goons, Collection, Investment) count at the end and show on the player panels and in the results.
* **Treasures that do things** (Anvil, Crystal Ball, Venture, Loan, Contraband, War Chest, Tiara, Investment...): "Play all Treasures" stops
  at the first one that asks a question and carries on when you press it again.
* **"When you gain" effects** (Hoard, Collection, Goons, Talisman, Mint, Royal Seal, Tiara, the Watchtower Reaction): every gain is looked at
  as soon as the card that caused it has finished, in the order the cards were gained. Rules decision: this is slightly later than the printed
  timing when one card gains several things, and the player does not choose the order of simultaneous triggers.
* **Costs that change**: Quarry (Actions $2 cheaper this turn) and Peddler (cheaper in your Buy phase) show in the pile prices. **Grand Market**
  cannot be bought with a Copper in play; **Contraband** bans the card the player on your left names.
* **Clerk** may be played from your hand at the start of your turn (you are asked, once per Clerk). **Charlatan** makes Curses Treasures worth $1
  for the whole game. **Trade Route** puts a token on every Victory pile; gaining from such a pile moves it to the mat.
* Rules decisions: Counting House asks "how many Coppers" (0 up to all of them) instead of a free choice; War Chest and Contraband let any
  Supply card be named; Bank counts only Treasures played before it.

### Update 14: Cornucopia & Guilds (2011, 2012 and the combined 2024 edition)
* **34 Kingdom cards, both editions in one set** ("Cornucopia & Guilds" in the lobby): the 26 cards of the 2024 edition (Advisor, Baker,
  Butcher, Candlestick Maker, Carnival, Fairgrounds, Farmhands, Farrier, Ferryman, Footpad, Hamlet, Herald, Horn of Plenty, Hunting Party,
  Infirmary, Jester, Journeyman, Joust, Menagerie, Merchant Guild, Plaza, Remake, Shop, Soothsayer, Stonemason, Young Witch) plus the 8 it
  removed (Fortune Teller, Farming Village, Horse Traders, Tournament, Harvest, Doctor, Masterpiece, Taxman). Cards in both editions use the
  2024 wording (Merchant Guild pays at the end of the Buy phase). The 5 **Prizes** (Tournament) and 6 **Rewards** (Joust) are not in the
  Supply: they appear in a "Not in the Supply" row.
* **Coffers**: tokens on your mat, each worth +$1 when spent. Use the *Spend Coffers* button in the turn bar (a `SpendCoffers` action in the
  engine; the Big Money bot spends them before buying). Baker's setup gives every player a token.
* **Overpay**: a card marked with the "+" in its cost (Stonemason, Doctor, Masterpiece, Herald, Farrier, Infirmary) may be bought for more
  than it costs. Click it and type the extra amount; the effect happens as the card is gained. (Potion costs cannot be overpaid.)
* **Young Witch** adds a **Bane** pile (an extra Kingdom card costing $2 or $3, chosen from the game's seed, shown with a "Bane" label) and
  **Ferryman** a pile of a $3 or $4 card that is not in the Supply and can only be gained with a Ferryman.
* **Farmhands** and **Horse Traders** hold a card until the start of your next turn; **Footpad** (while it is in the game) draws a card
  whenever you gain a card in an Action phase, including a Curse someone else gave you.
* Rules decisions: the Bane and the Ferryman pile are picked by the game, not by the host; Prize and Reward piles hold 1 of each (2 of each
  Reward with 3 or more players); with a Possession turn the possessed player's Coffers are the ones spent; Princess makes every card cheaper
  by $2 for as long as it is in play, each Princess adding another $2.

### Update 15: the Hinterlands expansion (2011)
* **All 26 cards of the original Hinterlands** ("Hinterlands" in the lobby, the seventh card set): Crossroads, Duchess, Fool's Gold, Develop,
  Oasis, Oracle, Scheme, Tunnel, Jack of All Trades, Noble Brigand, Nomad Camp, Silk Road, Spice Merchant, Trader, Cache, Cartographer,
  Embassy, Haggler, Highway, Ill-Gotten Gains, Inn, Mandarin, Margrave, Stables, Border Village, Farmland. Oracle, Noble Brigand and
  Margrave are Attacks (Moat blocks them).
* **Trader** replaces a gain: when you would gain a card you may reveal Trader and gain a Silver instead. The game asks after the card
  moved, then puts it back where it came from, so nothing that happens "when you gain" that card happens. **Fool's Gold** is worth $1 the
  first time it is played in a turn and $4 after that, and asks whether to trash itself when another player gains a Province.
* **Tunnel** gains a Gold whenever it is discarded other than in Clean-up (Cellar, Oasis, Margrave and so on); the reveal is automatic.
  **Scheme** asks at the start of Clean-up (once per Scheme played, so twice with Throne Room) which Action in play goes onto your deck.
  **Duchess** (when it is in the game) offers a Duchess with every Duchy you gain. **Highway** lowers every price by $1 per Highway in play.
* **Noble Brigand**, **Farmland** and the other "when you gain" cards work as printed; Brigand and Farmland only act when the card is *bought*.
* Rules decisions: the player does not choose the order of simultaneous gain effects; Develop asks which of its two cards goes on top;
  Oracle and Duchess show the top cards only to the player who has to decide; Embassy, Ill-Gotten Gains and Duchess skip a player who wears the
  Invisibility Cloak; Mandarin asks for the order of different Treasures (identical ones need no question).

### Update 16: the Dark Ages expansion (2012)
* **All 35 Kingdom piles of the original Dark Ages** ("Dark Ages" in the lobby, the eighth card set): Poor House ($1), Beggar, Squire, Vagrant ($2),
  Forager, Hermit, Market Square, Sage, Storeroom, Urchin ($3), Armory, Death Cart, Feodum, Fortress, Ironmonger, Marauder, Scavenger,
  Wandering Minstrel, Procession, Rats ($4), Band of Misfits, Bandit Camp, Catacombs, Count, Counterfeit, Cultist, Graverobber, Junk Dealer,
  Mystic, Pillage, Rebuild, Rogue ($5), Altar, Hunting Grounds ($6) and **Knights** ($5): one pile of ten different Knights (Dame Anna, Dame
  Josephine, Dame Molly, Dame Natalie, Dame Sylvia, Sir Bailey, Sir Destry, Sir Martin, Sir Michael, Sir Vander), shuffled, where only the top
  Knight can be bought or gained. The other cards of the set are listed under "Dark Ages supporting cards" below.
* **Mixed piles** (Knights and Ruins) show only their top card and count as one pile for the "three empty piles" rule. **Ruins** (Abandoned
  Mine, Ruined Library, Ruined Market, Ruined Village, Survivors; 10 per opponent) join the game when a **Looter** (Death Cart, Marauder, Cultist)
  is in the Kingdom; Looters hand them out. **Spoils** (15, Bandit Camp / Marauder / Pillage), **Madman** (10, Hermit) and **Mercenary** (10,
  Urchin) are piles outside the Supply and show under "Not in the Supply".
* **Shelters** (Hovel, Necropolis, Overgrown Estate) replace the three starting Estates. New lobby setting "Shelters": automatic (when a random
  Kingdom card is from Dark Ages, like Platinum and Colony with Prosperity), always, or never.
* **"When you trash this"** now works for any card: Squire, Catacombs, Fortress, Hunting Grounds, Feodum, Cultist, Rats, Sir Vander and
  Overgrown Estate. **Market Square** is a Reaction to one of your cards being trashed; **Hovel** to buying a Victory card; **Beggar** to an Attack.
* Rules decisions: Band of Misfits acts as the chosen Action (a Duration it copies stays in play as the Band); Procession cannot pick a
  Duration card; a Knight, Rogue or similar attack with only one card to trash asks nobody; Mystic and Rebuild let you name any card in the game;
  the Hermit-for-Madman trade happens when the Hermit is discarded in Clean-up if you bought nothing that turn; trashes during a Possession turn
  trigger nothing (the cards come back); the player does not choose the order of simultaneous trash effects.

### Update 18: the Adventures expansion (2015)
* **All 37 cards of Adventures** ("Adventures" in the lobby, the ninth card set): **29 Kingdom piles**: Coin of the Realm, Page, Peasant, Ratcatcher, Raze ($2),
  Amulet, Caravan Guard, Dungeon, Gear, Guide ($3), Duplicate, Magpie, Messenger, Miser, Port, Ranger, Transmogrify ($4), Artificer, Bridge Troll,
  Distant Lands, Giant, Haunted Woods, Lost City, Relic, Royal Carriage, Storyteller, Swamp Hag, Wine Merchant ($5), Hireling ($6); plus the **8 Traveller
  upgrade cards** (Treasure Hunter, Warrior, Hero, Champion, Soldier, Fugitive, Disciple, Teacher) that sit outside the Supply, 5 of each.
* **Reserve cards and the Tavern mat**: a Reserve card goes to your Tavern mat (shown on the player panel, face up) when played. Later the game
  asks whether you want to **call** it at the moment printed on the card: start of your turn (Guide, Ratcatcher, Transmogrify, Teacher), after you
  finish playing an Action (Royal Carriage, Coin of the Realm), when you gain a card (Duplicate) or at the end of your Buy phase (Wine Merchant).
  Distant Lands is worth 4 VP only while it is on the mat; Miser keeps Coppers there.
* **Travellers**: Page and Peasant start two lines (Page, Treasure Hunter, Warrior, Hero, Champion and Peasant, Soldier, Fugitive, Disciple, Teacher).
  When you discard one from play at cleanup you may exchange it for the next card of the line (an exchange is not a gain).
* **Tokens**: the Journey token (Giant, Ranger, Pilgrimage), the -1 Card token (your next draw is one card smaller) and the -$1 token (the next $ you get is
  one smaller), and the pile tokens (+1 Card, +1 Action, +1 Buy, +$1, -$2 Cost, Trashing) that Teacher and the Events put on Action piles. They show on the
  player panels and on the piles.
* **Events** are a new kind of card: you buy one with a Buy and its cost in $, you do not gain it. Up to two are in a game; new lobby setting
  "Events": automatic (two, chosen from the seed, whenever a Kingdom card is from Adventures) or never. The 20 events: Alms, Borrow, Quest, Save,
  Scouting Party, Travelling Fair, Bonfire, Expedition, Ferry, Plan, Mission, Pilgrimage, Ball, Raid, Seaway, Trade, Lost Arts, Training,
  Inheritance, Pathfinding. Their text is in the card tables below and on the card help.
* **Durations that last**: Champion and Hireling stay in play for the rest of the game; Haunted Woods and Swamp Hag punish other players' buys until your
  next turn; Caravan Guard is a Duration and a Reaction; Bridge Troll makes every card cost $1 less on your turns while it is in play.
* Rules decisions: Events never get cheaper (Bridge, Bridge Troll, Quarry do not touch them); Mission's extra turn lets you buy Events but no cards
  and cannot follow another Mission turn; Inheritance can only pick a non-Victory Action that is not a Duration, Reserve or Traveller card, and
  buying it a second time does nothing; Caravan Guard's +1 Action is lost when it is played as a Reaction (it is not your turn); Champion's own play
  does not trigger its +1 Action; Royal Carriage and Coin of the Realm are offered after every Action you play, including the plays a Throne Room makes;
  Teacher and the Events may put a token on any Action pile (Teacher only on a pile where you have no token); the player does not choose the order
  of simultaneous triggers.

### Update 19: the Empires expansion (2016)
* **All of Empires** ("Empires" in the lobby, the tenth card set): **24 Kingdom piles**, **13 Events** and **21 Landmarks**.
  Kingdom: Archive, Capital, Castles, Catapult/Rocks, Chariot Race, Charm, City Quarter, Crown, Encampment/Plunder, Enchantress, Engineer,
  Farmers' Market, Forum, Gladiator/Fortune, Groundskeeper, Legionary, Overlord, Patrician/Emporium, Royal Blacksmith, Sacrifice, Settlers/Bustling Village,
  Temple, Villa, Wild Hunt. Events: Advance, Annex, Banquet, Conquest, Delve, Dominate, Donate, Ritual, Salt the Earth, Tax, Triumph, Wedding, Windfall.
  Landmarks: Aqueduct, Arena, Bandit Fort, Basilica, Baths, Battlefield, Colonnade, Defiled Shrine, Fountain, Keep, Labyrinth, Mountain Pass, Museum,
  Obelisk, Orchard, Palace, Tomb, Tower, Triumphal Arch, Wall, Wolf Den. Their text is in the card tables below and on the card help.
* **Debt**: cards and Events with a Debt cost (City Quarter, Engineer, Overlord, Royal Blacksmith, Fortune, Annex, Donate, Triumph, Wedding) make you take
  Debt tokens when you buy them, and Capital does when it is discarded from play. While you owe Debt you cannot buy cards or Events. The **Pay off Debt** button
  spends $1 per token during your Buy phase (Capital pays off what it can with your spare $ by itself). Cards with Debt in their cost are never gained by
  "costing up to $X" effects.
* **Split piles and the Castles**: five of each half, top half first; only the top card can be bought or gained (Rocks stay buried until the Catapults are gone,
  and the pile counts as empty only when both halves are). The Castles are one pile of 8 cards (12 with 3 or 4 players: two each of Humble, Small, Opulent and
  King's Castle), cheapest on top.
* **VP on piles**: Temple, Wild Hunt and Farmers' Market collect VP on their own pile; Aqueduct and Defiled Shrine move VP between piles and the Landmark. Tax puts
  Debt on piles. The pile shows its VP and Debt, and a split pile shows both counts.
* **Events and Landmarks together**: at most two per game. Automatic mode picks two from the seed whenever a Kingdom card is from Adventures or Empires
  (Adventures cards bring only Adventures Events; Empires cards bring Empires Events and Landmarks); the host can switch it off. Landmarks sit next to the
  Events and show the VP still on them.
* Rules decisions: Enchantress affects each other player's first Action of their next turn (once per Enchantress waiting on them); Charm's second card is chosen
  after the buy and must cost exactly the same (coins, Potions and Debt) under another name; Colonnade uses the current wording (gaining, not buying); Mountain Pass
  bidding starts left of the first Province gainer and ends with them, after that turn; Donate happens in Clean-up before the new hand is drawn; Groundskeeper uses the
  2022 wording (this turn); Overlord leaves the card it plays in the Supply and counts as the played card for "trash this" effects; Arena asks only when you have an Action
  card in hand; Crown asks again in each phase it is played in.

### Update 20: the Nocturne expansion (2017)
* **All of Nocturne** ("Nocturne" in the lobby, the eleventh card set): **33 Kingdom piles**, 12 Boons, 12 Hexes, 5 States, 7 Heirlooms and the extra cards
  (Will-o'-Wisp, Imp, Ghost, Bat, Wish and the three Zombies). Kingdom: Bard, Blessed Village, Cemetery, Changeling, Cobbler, Conclave, Crypt, Cursed Village,
  Den of Sin, Devil's Workshop, Druid, Exorcist, Faithful Hound, Fool, Ghost Town, Guardian, Idol, Leprechaun, Monastery, Necromancer, Night Watchman, Pixie,
  Pooka, Raider, Sacred Grove, Secret Cave, Shepherd, Skulk, Tormentor, Tracker, Tragic Hero, Vampire, Werewolf. Every card's text is in the tables below and on the card help.
* **The Night phase**: a turn is now Action, Buy, **Night**, Clean-up. Night cards are played in the Night phase for no Action (click them in your hand; the
  button changes to "End turn"). The phase is skipped unless you hold a Night card after your Buy phase. Treasures and buying are over by then. Werewolf is an
  Action and a Night card and works in either phase. Night cards cannot be played with Throne Room and friends (they are not Actions).
* **Boons and Hexes**: Fate cards bring the 12 shuffled Boons into the game, Doom cards the 12 Hexes (decks and discard piles are shown in a panel under the log, and
  each Boon and Hex has card help; the discard pile is reshuffled when a deck runs out). "Receive" a Boon or Hex: it is turned over, does its thing, and is discarded.
  The Field's, Forest's and River's Gifts stay in front of the turn's player until Clean-up (this matters for Pixie, and for reshuffling). Druid sets three Boons aside
  face up at the start and receives them without using them up. Hexes that other players receive are Attacks where the card is one (Skulk, Tormentor, Vampire,
  Werewolf: Moat, Guardian and friends protect); Leprechaun and Cursed Village hand you your own Hex.
* **States**: Deluded and Envious are returned at the start of your Buy phase (a Hex you receive during your Action phase counts that turn; later, next turn).
  Miserable and Twice Miserable are -2 and -4 VP and show in the score breakdown. Lost in the Woods (from Fool) lets its holder discard a card for a Boon at the start
  of each of their turns, until another Fool takes it. States are shown as tags on the player panel.
* **Heirlooms**: each Kingdom card that has one swaps a starting Copper for it in every deck (the Coppers go back to the pile): Cemetery - Haunted Mirror, Fool - Lucky Coin,
  Pixie - Goat, Pooka - Cursed Gold, Secret Cave - Magic Lamp, Shepherd - Pasture, Tracker - Pouch.
* **Everything else**: Durations are the Seaside ones (Cobbler, Crypt - which keeps its set-aside Treasures face down, only the count shows - Den of Sin, Ghost Town,
  Guardian, Raider, Secret Cave, Ghost). Night Watchman, Den of Sin, Ghost Town and Guardian are gained to your hand. Changeling lets you exchange a gained card costing
  $3 or more for a Changeling (a question appears; "things that happen when you gain the card" still happen). Necromancer plays Action cards from the trash (a played copy is
  face down for the turn; the three Zombies start in the trash). Vampire and Bat exchange for each other, not as gains. Piles outside the Supply appear only when needed
  (Will-o'-Wisp with any Fate card, Imp, Ghost, Wish, Bat).
* Rules decisions: start-of-turn effects happen in a fixed order (Duration cards, then Boons saved by Blessed Village, then Lost in the Woods); a Faithful Hound that is
  discarded outside Clean-up is set aside automatically and returns to its owner's hand at the end of the turn (never worse than the discard pile); "each other player
  receives the next Hex" turns no Hex over when every other player is protected; Sacred Grove asks each other player in turn whether to receive the Boon; a Boon received
  off-turn (Blessed Village gained during someone else's turn) gives no Actions, Buys or $; when you choose to discard fewer than 3 cards because you have fewer (The Sky's
  Gift, Secret Cave) you get no reward; Tragic Hero gives its Treasure even if it can no longer trash itself.

### Update 21: the Renaissance expansion (2018)
* **All of Renaissance** ("Renaissance" in the lobby, the twelfth card set): **25 Kingdom piles**, **20 Projects** and **5 Artifacts**, plus **Villagers**. Kingdom: Acting Troupe,
  Border Guard, Cargo Ship, Ducat, Experiment, Flag Bearer, Hideout, Improve, Inventor, Lackeys, Mountain Village, Old Witch, Patron, Priest, Recruiter, Research, Scepter,
  Scholar, Sculptor, Seer, Silk Merchant, Spices, Swashbuckler, Treasurer, Villain. Every card's text is in the tables below and on the card help.
* **Villagers** work like Coffers but give Actions: tokens on your mat, and a "Spend Villagers" button (Action phase only) turns each into +1 Action. The mat shows as a tag on the player panel.
* **Projects**: with a Renaissance card in the Kingdom, two of the Events / Landmarks / Projects are picked automatically (at most two in all, as before; the lobby switch for Events turns
  them off). Projects sit in the Events row. Click one in your Buy phase to put a cube on it: it costs a Buy and its cost in $ (not made cheaper by Inventor, Canal does not touch it),
  you cannot buy one while you owe Debt, you cannot cube the same Project twice, and the tag "Cubes: names" on the card shows who has it. From then on you have its ability.
* **Artifacts** (Flag, Horn, Key, Lantern, Treasure Chest) are taken by Border Guard, Flag Bearer, Swashbuckler and Treasurer; whoever takes one takes it from the previous holder.
  They show in the panel under the log (and as tags on the holder). Flag: +1 Card in your Clean-up draw. Horn: asked at Clean-up whether to put a Border Guard on your deck.
  Key: +$1 at the start of your turn. Lantern: your Border Guards reveal 3. Treasure Chest: gain a Gold at the start of your Buy phase.
* **Everything else**: Cargo Ship and Research are Durations (the cards set aside on them are still yours for scoring; Research's are face down, only the count shows). Experiment returns
  to its pile when played and brings a second copy when gained (the extra copy brings no third). Scepter replays an Action you played this turn that is still in play (it stays out as long
  as a Duration it replayed). Capitalism makes your Actions with a "+$" in their text Treasures during your turns (they can be played one by one in the Buy phase; "play all Treasures" leaves
  them alone). Citadel plays the first Action of your turn again (also one played by Piazza, Innovation or Capitalism). Fleet: when the game would end, each player with Fleet takes one more
  turn in turn order starting after the player who ended it; then the game is over whatever happened.
* Rules decisions: start-of-turn Projects happen in a fixed order (Barracks, Fair and the Key's $1; then Silos, Crop Rotation, Sinister Plot and City Gate, which draw; then Piazza; Cathedral last);
  Star Chart asks when a draw has to shuffle, and the rest of that draw happens after you pick (so a card that shuffles in the middle of its own draw finishes the draw after its other text, and
  shuffles that are not draws, like revealing cards, do not ask); Patron's Coffers are given for every Patron named in a "reveals" line of the log after each action (a hand revealed without naming its
  cards does not count); Priest's and Sewers' trash triggers resolve after the card that trashed; Old Witch, Villain and Border Guard follow the card text exactly.

### Update 22: the Menagerie expansion (2020)
* **All of Menagerie** ("Menagerie" in the lobby, the thirteenth card set): **30 Kingdom piles**, **20 Events**, **20 Ways**, the **Horse** pile and the **Exile mat**. Kingdom: Animal Fair,
  Barge, Black Cat, Bounty Hunter, Camel Train, Cardinal, Cavalry, Coven, Destrier, Displace, Falconer, Fisherman, Gatekeeper, Goatherd, Groom, Hostelry, Hunting Lodge, Kiln, Livery,
  Mastermind, Paddock, Sanctuary, Scrap, Sheepdog, Sleigh, Snowy Village, Stockpile, Supplies, Village Green, Wayfarer. Every card's text is in the tables below and on the card help.
* **Exile**: each player has an Exile mat (a tag on the player panel, face up; its cards still score). Exiling a card from the Supply is not gaining it. When you gain a card you are asked
  whether to discard the other copies of it from your mat (all of them or none). **Horses** are a pile of 30 outside the Supply that appears whenever any Menagerie card, Event or Way is in
  the game; a Horse gives +2 Cards and +1 Action and goes back to its pile.
* **Ways**: with a Way in the game (shown in the Events row, marked "Way"), every time you play an Action you are asked whether to play it normally or use the Way instead (also when Throne Room
  or Mastermind plays it again, each play separately). At most one Way per game is picked automatically (at most two Events / Landmarks / Projects / Ways in all). Way of the Chameleon runs the
  card with +Cards and +$ swapped; Way of the Mouse plays an unused Action Kingdom card costing $2 or $3 that is set aside at setup (shown on the Way); Way of the Turtle, Delay and Reap
  set a card aside (a tag on the player panel) and play it at the start of your next turn.
* **Events**: Alliance, Banish, Bargain, Commerce, Delay, Demand, Desperation, Enclave, Enhance, Gamble, Invest, March, Populate, Pursue, Reap, Ride, Seize the Day, Stampede, Toil, Transport.
  Stampede can only be bought with 5 or fewer cards in play, Desperation once per turn, Seize the Day once per game (the extra turn does not count for the tiebreaker, and never comes as a third
  turn in a row). Invest remembers which Exiled copies were Invested: when another player gains or Invests in a copy, you draw 2 cards per copy.
* **Reactions at odd times**: Sheepdog and Sleigh when you gain a card, Falconer when any player gains a card with 2 or more types, Black Cat when another player gains a Victory card, Village
  Green when you discard it other than in Clean-up. You are asked after each such gain, in turn order starting with the player whose turn it is; a Reaction played on someone else's turn is
  discarded at the end of that turn (+Actions, +Buys and +$ from it do nothing). Animal Fair asks whether to pay or to trash an Action card instead; Kiln asks before each play it triggers on.
* Rules decisions: Wayfarer copies the coin cost of the last other card gained this turn (by anyone; Potions and Debt are ignored); Destrier and Fisherman use the cost rules for the player whose
  turn it is; Goatherd counts the cards the player on your right trashed from their own cards during their last turn; Gatekeeper's Exile only happens to players it hit (Moat protects) and
  only when they have no copy of the card in Exile; Scrap's six options are +1 Card, +1 Action, +1 Buy, +$1, gain a Silver and gain a Horse, in that order; the card texts were checked
  against the published rulebook where it quotes them, so please compare against your physical cards if one plays differently.

### Update 23: the Allies expansion (2022)
* **All of Allies** ("Allies" in the lobby, the fourteenth card set): **31 Kingdom piles** (25 single cards plus the six split piles **Augurs, Clashes, Forts, Odysseys, Townsfolk and Wizards**,
  16 cards each: 4 copies of 4 different cards, cheapest on top), and **23 Allies**. Single cards: Barbarian, Bauble, Broker, Capital City, Carpenter, Contract, Courier, Emissary, Galleria,
  Guildmaster, Highwayman, Hunter, Importer, Innkeeper, Marquis, Merchant Camp, Modify, Royal Galley, Sentinel, Skirmisher, Specialist, Swap, Sycophant, Town, Underling. Every card's text is in
  the tables below and on the card help.
* **Favors and Allies**: when a Liaison is anywhere in the Kingdom (also inside a split pile, e.g. Student) the game uses one **Ally**, picked by the seed (shown in the Events row, marked "Ally"),
  and every player starts with 1 Favor (5 with Importer; Favors show on the player panel). Spending Favors is always optional: you are asked at the moment the Ally triggers (start of turn, start of the
  Buy phase, after a gain, after playing, a shuffle, the end of the turn, Clean-up). Plateau Shepherds scores in the final points (shown in the breakdown).
* **Split piles**: only the top card can be gained or bought, and the pile counts as one pile for the three-pile ending, Carpenter, Territory and the rest. "Rotate" (Town Crier, Tent, Old Map...)
  moves the top card and its copies to the bottom (you are asked each time); Battle Plan can rotate any Supply pile, Swap returns to the top. Family of Inventors puts Favor tokens on piles
  (their cards cost $1 less each, shown on the pile).
* **Extra turns**: Voyage and Island Folk use the same extra-turn rule as Seize the Day (never a third turn in a row, and they do not count as a turn for the tiebreaker); during a Voyage turn only 3 cards
  can be played from the hand (Play all Treasures plays the most valuable ones). Lich skips your next turn. Order of Astrologers / Masons stop a draw just before the shuffle (like Star Chart, the rest
  of the draw happens after the card finishes).
* **Elder** gives the Action it plays an extra, different option on "choose one" abilities, but only on cards of Allies and Menagerie's Barge: older cards with a "choose" ability from other sets
  (Charm, Nobles, ...) keep their single choice.
* Rules decisions: Warlord's restriction is checked when an Action is played from the hand directly (not for the cards Throne Room-like cards play); Garrison tokens count one per gain per Garrison
  played; Hill Fort and City-state move the gained card before its own "when you gain" effects run; Highwayman only blanks the Treasures of players it hit (Moat protects).
  **The Allies' texts come from the published rulebook, but the number printed inside a coin symbol did not survive the copy: please compare Elder (+$2), Stronghold (+$3), Band of Nomads ($5 or more)
  and Contract ($2) against your physical cards.**

### Update 24: the Plunder expansion (2022)
* **All of Plunder** ("Plunder" in the lobby, the fifteenth card set): **40 Kingdom cards**, **15 Loot cards**, **15 Events** and **15 Traits**. Kingdom cards: Abundance, Buried Treasure, Cabin Boy, Cage, Crew,
  Crucible, Cutthroat, Enlarge, Figurine, First Mate, Flagship, Fortune Hunter, Frigate, Gondola, Grotto, Harbor Village, Jewelled Egg, King's Cache, Landing Party, Longship, Mapmaker, Maroon, Mining Road,
  Pendant, Pickaxe, Pilgrim, Quartermaster, Rope, Sack of Loot, Search, Secluded Shrine, Shaman, Silver Mine, Siren, Stowaway, Swamp Shacks, Taskmaster, Tools, Trickster, Wealthy Village.
  Events: Avoid, Bury, Deliver, Foray, Invasion, Journey, Launch, Looting, Maelstrom, Mirror, Peril, Prepare, Prosper, Rush, Scrounge. Every text is on the card help.
* **Loot**: when any card of the game says "gain a Loot" the game has a shuffled Loot pile (2 of each of the 15 Loot cards, shown as one pile "Loot" under the Supply; its top card is gained, revealed).
  Loot cards are Treasures costing $7 (Spell Scroll is an Action-Treasure; Play all Treasures leaves it alone).
* **Traits**: Events, Traits... together are at most two landscape cards per game, picked by the seed when a Plunder card is in the Kingdom. A Trait lies on a random Action or Treasure Kingdom pile (shown
  in the Events row as "Trait | on <pile>"). Cheap, Cursed, Fated, Fawning, Friendly, Hasty, Inherited, Inspiring, Nearby, Patient, Pious, Reckless, Rich, Shy and Tireless are all implemented;
  Inherited asks every player (in turn order) at the very start which starting card to swap.
* **Treasure-Durations** (Abundance, Cage, Gondola, Rope...) are Treasures that stay in play; "the next time ..." cards (Abundance, Cage, Cutthroat, Flagship, Landing Party, Search, Secluded Shrine,
  Taskmaster) wait through your start of turn until it happens. Cards set aside (Cage, Grotto, Quartermaster, Prepare, Hasty, Patient) show on the player panel ("Set aside", only you see which). Cards that
  go "into your hand at end of turn" (Puzzle Box, Deliver, Cage, Trickster) arrive after the new hand was drawn.
* Journey uses the Seize the Day extra-turn rule (and keeps your cards in play for the extra turn); Launch returns to the Action phase; Mapmaker and Stowaway can be played as Reactions to any gain.
* Rules decisions and simplifications: **Friendly** discards from the hand; **Reckless** doubles a Treasure's $ as well as its effect; when Prosper gains several cards, their "when you gain" effects are looked at
  after the whole Event; Fated and Avoid stop only draws (not other looks at the deck) and replace the Allies' Orders if both apply to one shuffle; Inherited swaps the card by name (a Copper goes back to the
  Supply, an Estate to the box); Journey is allowed on the first turn of the game. **The card texts come from the published rulebook; please play-test the unusual interactions (Flagship, Prepare,
  Quartermaster, Fated) and tell me what looks wrong.**

### Update 25: the Rising Sun expansion (2024)
* **All of Rising Sun** ("Rising Sun" in the lobby, the sixteenth card set): **25 Kingdom cards** (Alley, Aristocrat, Artist, Change, Craftsman, Daimyo, Fishmonger, Gold Mine, Imperial Envoy, Kitsune, Litter,
  Mountain Shrine, Ninja, Poet, Rice, Rice Broker, River Shrine, Riverboat, Ronin, Root Cellar, Rustic Village, Samurai, Snake Witch, Tanuki, Tea House), **10 Events** (Amass, Asceticism, Continue, Credit, Foresight,
  Gather, Kintsugi, Practice, Receive Tribute, Sea Trade) and **15 Prophecies**. Debt works as in Empires (Artist, Daimyo, Mountain Shrine and Continue cost only Debt).
* **Shadows** (Alley, Fishmonger, Ninja, Ronin, Tanuki): during your Action phase they also show up as extra cards marked "deck" next to your hand when one is in your deck: click it to play it from the deck.
  Shadows go to the bottom of the deck whenever it is shuffled.
* **Omens and Prophecies**: when an Omen (Kitsune, Mountain Shrine, Poet, River Shrine, Rustic Village, Tea House) is in the Kingdom the game has one Prophecy (picked from the seed, or named in the events list) with Sun
  tokens on it (5 for 2 players, 8, 10, 12, 13). Omens remove a Sun when played; when the last one goes the Prophecy is in force. All 15 are implemented (it shows in the Events row with the tokens left).
  Approaching Army adds an Attack pile to the Supply from the start; Divine Wind swaps all Kingdom piles for 10 new random ones; Kind Emperor gains an Action when it begins.
* **Riverboat**: its set-aside card (an unused non-Duration Action costing exactly $5, picked from the seed) is shown in the Events row.
* Rules decisions and simplifications: Shadows can be played from the deck in the Action phase only (not by Throne Room-like cards that say "play a card from your hand"); Tanuki and Kintsugi can gain a card costing
  only Debt when the trashed card cost that much Debt; Harsh Winter takes over the Debt tokens on piles from Tax's rule while it is in force; Divine Wind's new piles are drawn from the card sets of the game.
  **The numbers on the cards were rebuilt from several published lists because the rulebook text lost its symbols: please compare Craftsman (+2 Debt), Root Cellar (+3 Debt), Gold Mine (+4 Debt), Imperial Envoy (+2 Debt),
  Litter (+1 Debt), Kitsune and Tea House (+$2), Credit (up to $8), Amass (up to $5), Continue (up to $4) and Harsh Winter (2 Debt) with your cards, and tell me what is off.**

## Known limitations

* A dropped player stalls the game until they rejoin (no timer or replace-with-bot button; the other players can Resign or the host can End or Delete the game).
* Free-tier hosting sleeps or restarts, which ends every game; games are not saved.
* Bots never play Action cards (Big Money), so they ignore Night cards too.
* Reactions exist as "block an Attack" (Moat) and "reveal for an effect" (Diplomat); Reactions to
  other triggers (Watchtower, Horse Traders) are not implemented.
* `legal_actions` for large optional choices enumerates all multisets (2^n for n cards); fine for a
  hand, but a UI should prefer `validate` for free-form answers (the CLI does).
* No spectators, accounts or replays. The page is built for a desktop browser (no phone layout) and tuned for
  screens from 1280x720 up; on smaller windows the panels scroll inside themselves.

Ideas for later: smarter bots, a replace-with-bot button for dropped players, saving games across
restarts, spectators, more expansions.
