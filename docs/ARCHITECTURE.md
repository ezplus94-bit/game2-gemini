# Architecture and implementation plan

## 1. Goals

1. The **engine decides legality**. UI and AI only submit requests.
2. **Cards are data plus a small effect function**; new cards never require
   engine changes.
3. **Deterministic**: a seed plus the list of actions reproduces a game exactly
   (replays, bug reports, clones for AI search, server-side verification).
4. **Layered**: cards -> engine -> (ai, ui). The engine imports cards; cards do
   not import the engine; UI/AI import the engine.

## 2. Modules and responsibilities

| Concern | Module | Notes |
|---|---|---|
| Card definitions | `cards/base.py`, `basic.py`, `kingdom.py` | `CardDef` is a frozen dataclass: name, cost, types, coins, vp, optional `score_fn`, optional `on_play`. |
| Card registry | `cards/registry.py` | `register`, `get_card`, `kingdom_cards`. Adding a card = registering it. |
| Player state | `engine/state.py` `PlayerState` | Zones: `deck` (draw pile, top = end of list), `hand`, `discard`, `in_play`, `set_aside`. |
| Game state | `engine/state.py` `GameState` | Players, supply, trash, current player, phase, actions, buys, coins, status, pending decision, log. Pure data. |
| Rules validation | `engine/rules.py` | `validate(state, player, action) -> reason or None`; `legal_actions(state, player)`. No mutation. |
| Game engine | `engine/game.py` | `Game.apply()` validates, then executes. Only code that mutates state. |
| Card-effect API | `engine/effects.py` | `EffectContext`: the only way effects touch the game. |
| Card movement | `engine/zones.py` | Draw/reshuffle, gain, discard, trash. |
| Setup | `engine/setup.py` | `GameConfig`, `new_game`, `replay`. Validates Kingdom and player count; builds supply. |
| Scoring | `engine/scoring.py` | VP, winners, fewest-turns tiebreak. |
| Player views | `engine/views.py` | `build_view(game, player)`: the ONLY thing sent to a client. Hides other hands/decks. |
| Wire format | `engine/codec.py` | `Action` <-> JSON, strict shape checks (not legality). |
| UI (text) | `ui/cli.py` | Display + submit. Menu is built from `legal_actions()`. |
| UI (web) | `web/static/index.html` | Browser client. Displays the view, submits actions. |
| Rooms/lobby | `web/rooms.py` | Seats, tokens, host controls, bot driver, broadcasting. Transport-agnostic. |
| HTTP/WebSocket | `web/server.py` | FastAPI: serves the page, `/healthz`, `/ws`. |
| AI | `ai/bots.py` | Bots choose from `legal_actions()`. |

Cards are referenced everywhere by **name** (a string). Base Dominion has no
card identity beyond its name, so lists of names are simple and cheap. If a
future card needs identity (e.g. tracking a specific card across zones), the
zone lists can become lists of card-instance ids without changing the public
API much.

## 3. Turn structure

```
ACTION phase ──EndPhase──► BUY phase ──EndPhase──► cleanup (automatic) ──► next player
   PlayAction(card)           PlayTreasure(card) / PlayAllTreasures
   (costs 1 Action)           Buy(card) (costs 1 Buy and coins)
```

* Resources start each turn at Actions 1, Buys 1, Coins 0 and are reset in cleanup.
* Cleanup: discard hand and in-play, draw 5 (reshuffling if needed), increment
  `turns_taken`, then check the end condition, then pass the turn. Cleanup has
  no player choices in the base game, so it is not a phase.
* **Game end** is checked at the end of a turn: the Province pile is empty, or
  3 supply piles are empty. Winner = highest VP; ties go to the fewest turns;
  remaining ties are shared.
* Moving from the Action phase to the Buy phase is explicit (`EndPhase`) so the
  engine stays strict. A UI may auto-advance when nothing is playable.

## 4. Decisions (interactive card effects)

Effects that need an answer are Python generators:

```python
def _remodel(ctx):
    (trashed,) = yield ctx.choose("Trash a card from your hand.", ctx.hand)   # pause
    ctx.trash(trashed)
    (card,) = yield ctx.choose("Gain a card...", ctx.gainable(ctx.cost_of(trashed) + 2))
    ctx.gain(card)
```

When an effect yields, the engine stores the suspended generator in
`state.pending` along with the `Decision` (who answers, prompt, options,
min/max). While a decision is pending, the **only** legal action is
`Choose(selection)` from `decision.player`; the selection must be a sub-multiset
of the options within the min/max bounds. After a valid answer the generator
resumes, and may finish or ask again.

Because `Decision.player` is explicit, attacks that ask *other* players
(Militia, Witch reactions) fit the same mechanism (tested in `test_extensibility.py`).

Cards can play other cards: `yield from ctx.resolve(card)` runs the inner card's
effect and passes any questions it asks straight through (Throne Room, Vassal;
Throne Room can even play Throne Room). Effects that last until end of turn use
`ctx.add_trigger(event, handler)` (Merchant); the engine fires `treasure_played`
and clears triggers at cleanup. Cards temporarily out of play (Sentry's top two,
Library's skipped Actions) live in the `set_aside` zone so card counts always
add up, and it is empty whenever no decision is pending (tested).

**Attacks and Reactions.** An Attack card has types `ACTION + ATTACK`; a Reaction
has `blocks_attack=True` (Moat). An Attack effect starts with
`targets = yield from ctx.attack()`: every other player in turn order who holds a
blocking Reaction is asked (privately) whether to reveal it, and the attack then
resolves only against players who did not. All reaction questions come before any
attack effect, as in the rules. Each defender's answer is a normal `Decision`
addressed to that player (`ctx.choose(..., player=p)`), so the engine waits for
them, other players cannot act, and a Throne Room'd Attack asks again the second
time. Bots answer attacks by giving up their least useful cards.

Trade-off: suspended generators cannot be copied or serialized. Instead, a game
is cloned/saved by **replay** (`Game.clone()`, `replay(config, history)`),
which works because everything is deterministic.

## 5. Determinism

* All randomness comes from one `random.Random(seed)` stored in the state.
* `new_game` resolves the seed and Kingdom and stores them in `game.config`;
  `game.history` is the list of `(player, action)`.
* The random Kingdom pick uses its own RNG derived from the seed so it never
  perturbs shuffles.

## 6. Testing strategy

* **Setup**: supply sizes by player count, starting decks, Kingdom validation.
* **Turn flow**: phases, coins, buys, cleanup, turn order, reshuffling.
* **Rules**: legal-action lists; illegal actions leave state unchanged.
* **Cards**: every implemented card, including rejected answers.
* **Endgame**: end conditions, scoring, tiebreaks.
* **Extensibility**: temporary cards registered inside tests.
* **Self-play**: random and Big Money bots across 2 to 4 players. After every
  action: the action was in `legal_actions`, no pile is negative, and total
  card count is conserved. Games are replayed to prove determinism.
* Intentionally breaking rules (removing the turn check, coin check, etc.)
  makes tests fail, which is how the suite was sanity-checked.

## 7. Rules assumptions to double-check

These are standard Dominion (2nd edition) values entered from the rulebook as
I know it; verify against your copy before relying on them: Victory piles of 8
(2 players) or 12 (3 to 4); Curses `10 x (players - 1)`; Coppers `60 - 7 x players`;
Silver 40; Gold 30; Kingdom piles of 10; a Victory-type Kingdom card (Gardens)
uses the Victory pile size. 5 to 6 players are not supported yet (they need
different pile counts and a 4-pile ending).

## 8. Implementation plan

| Milestone | Scope | Status |
|---|---|---|
| **M0 Foundation** | Engine, state, zones, rules validator, decisions, setup, scoring, bots, CLI, tests | Done |
| **M1 Base-set non-attack cards** | Harbinger, Merchant, Vassal, Poacher, Mine, Library, Sentry, Artisan, Council Room, Throne Room | Done |
| **M2 Attacks and reactions** | `ATTACK`/`REACTION` types, a reaction step before an Attack resolves, Moat, Militia, Witch, Bandit | Done |
| **M3 Triggers and durations** | Event hooks (e.g. on-gain, on-play) for Merchant/Watchtower-style cards; `set_aside` zone use for Library/Sentry; Duration cards later | |
| **M4 Hidden information and networking** | Per-player view, JSON codec, FastAPI WebSocket server, rooms, seats, reconnection by token, bots in rooms | Done |
| **M5 Web UI** | Browser lobby + board + card-choice prompts; invite links; rematch | Done (basic) |
| **M5b Web polish** | Card art/layout, animations, sound, spectators, chat, mobile layout tuning, accounts/persistence (SQLite) so games survive restarts | Next |
| **M6 AI and balance** | Better bots (Big Money with Actions, search using `clone()`), simulation harness for balance statistics | |
| **M7 Content and variants** | Kingdom presets, 5 to 6 players, expansions | |

## 9. Web layer

### Message protocol (JSON over one WebSocket at `/ws`)

Client -> server

| type | fields | who / when |
|---|---|---|
| `create` | `name` | anyone; makes a room, you become host |
| `join` | `room`, `name`, optional `token` | with a valid `token` it re-attaches your seat (reconnect) |
| `leave` | | removes your seat in the lobby; detaches during a game |
| `set_kingdom` | `kingdom` (1-10 names, or empty for random) | host, lobby |
| `add_bot` / `remove_seat` (`seat`) | | host, lobby |
| `start` / `rematch` | | host (rematch only after game over) |
| `action` | `action`: `{type: play_action/play_treasure/play_all_treasures/buy/end_phase/choose, card?, selection?}` | seated player |
| `ping` | | keepalive (the page sends one every 25 s) |
| `set_catastrophes` | `catastrophes` (0-2 names) | host, lobby |
| `set_expansions` | `expansions` (1 or more card-set names, e.g. `["Base","Intrigue"]`) | host, lobby; the card sets a random Kingdom is drawn from |
| `set_cheats` | `cheats` (bool) | host, lobby; allows cheat codes typed in the chat (default off) |
| `list_games` | `games`: up to 20 `{room, token}` | anyone, even on the home page; answered with `games` (only games whose token is valid) |
| `resign` | | any seated player, any time the game is active: the game ends, the resigner cannot win |
| `end_game` | | host, game active: the game ends with the current scores |
| `delete_room` | `room`, `token` | host's token (works from the home page): removes the game for everybody |
| `chat` | `text` | seated player; 300 chars, 5 per 10 s. With cheats on, the three cheat phrases are intercepted: they run `Cheat(...)` and are never shown as chat |
| `undo_request` / `undo_cancel` | | request to take back your last action this turn / withdraw it |
| `undo_vote` | `approve` (bool) | every other human must vote yes |

Server -> client: `joined` (room, secret token, seat), `lobby` (players, kingdom,
available cards, `expansions`, `available_expansions`), `game` (the player's `view`, plus an `undo` block while a vote is
open), `chat` / `chat_history`, `error` (message), `left` (optional `reason`, e.g. when the host deleted the game), `games` (`games` with status / players / your_turn, and `gone`: codes that no longer exist or whose token was wrong), `deleted` (`room`; sent to whoever deleted a game), `pong`.

### Security and correctness rules
* **Identity comes from the seat bound to the connection**, found via a secret
  random token. Messages never say which player they are; claiming otherwise is ignored.
* **Legality is the engine's**: `action` -> `action_from_dict` (shape) -> `Game.apply` (rules).
* **No hidden-information leaks**: clients only get `build_view` output. An
  opponent's decision prompt/options are withheld. Tests assert opponents'
  hands never appear. If a future card logs hidden info (e.g. "reveals X"),
  decide deliberately whether that line is public.
* Messages are size-limited and must be JSON objects; names are trimmed to 20
  characters and rendered as text, never HTML.
* Bots run on the server as a background task with a short delay so humans can
  follow along; they pick only from `legal_actions`.
* All rooms are in memory in ONE process. Restarts and sleeping free-tier hosts
  end games (clients return to the home screen). Persistence is a later step.

### Testing
* `test_web_rooms.py`: protocol and room logic with fake connections.
* `test_web_server.py`: a real uvicorn server and real WebSocket clients
  (garbage input, two browsers + bot, reconnect over a new socket).
* `test_web_fuzz.py`: a simulated playtest. Random players play full games through
  the room protocol while dropping connections, rejoining with their token and
  sending junk; every game must finish, never log an error, and never leak a
  hidden card.
* `test_browser.py` + `tests/browser/*.js`: the real `index.html` run in jsdom
  against a live server: two humans and a bot play a full game through the
  buttons (including card-choice prompts), plus automatic reconnect. Optional;
  needs Node and `npm install` in `tests/browser`.

### Catastrophe cards (design rationale)
They are a separate card type (`CardType.CATASTROPHE`), never part of the random
Kingdom, added per game via `GameConfig.catastrophes` (0-2) and extra piles of 2.
Design choices, each backed by a test:

* **Skips** (`PlayerState.skips`, `skip_protected`): a skipped player is protected
  until they take a real turn, so nobody can be chain-locked; skips never stack; in
  a 2-player game Time Stop is a double turn for you, which is why it costs $8 and
  trashes itself.
* **Fate Swap** swaps the same number of *draw-pile* cards both ways (not whole decks).
  A full swap would let a player steal a big deck by comparing public deck counts, or
  swap standings on the last turn. Equal-size, blind swaps make it a gamble with a
  tactical edge (play it when your own remaining draw pile is weak), not a heist.
* **Cataclysm** pools deck+hand+discard of everyone (cards in play stay), deals the
  same counts back, and locks the player's buys for the turn, so it is a Hail Mary
  with a real cost, not a free win on the final turn.
* **Single use**: `ctx.trash_self()` returns False if the card is already gone, so a
  Throne Room'd copy does nothing the second time.
* **Moat** can block the targeted three (`ctx.attack(only=[...])` asks only the
  players actually targeted). Cataclysm is not an attack.
* The scarce piles are excluded from the "three empty piles" end condition.
* To test them with random bots, tests register $0 copies of the real effects.

Ideas if you want them wilder or tamer: raise the pile size or lower the costs; allow
a full-deck swap as an even riskier fifth card; make Cataclysm affect hands only.

### Undo
The game is deterministic, so undo is a **replay**: rebuild the game from its seed
and `history[:target]`, where `target` is the requester's most recent action *from any turn*
(update 10: it used to be limited to the current turn). Everything the other players did after it is
rolled back with it (for example their whole turns), and the prompt says how many actions that is. Every other *human* must approve; bots are not asked, and if nobody
needs to be asked it happens at once. While a vote is open, game actions are refused
and bots wait. A request times out after 60 s. Because the shuffle is fixed by the
seed, an undo can never re-roll a draw. Undo is unavailable once the game is over.

### Update 6-7 design notes

* **Structured log.** `state.log` is a `GameLog` (a list subclass). Every entry is a `LogLine`, which *is a
  `str`* (so `"text" in log` and equality keep working) and also carries `turn`, `kind` and `indent`.
  `log.append(text, kind=None, indent=0)` classifies plain text itself (`state.classify`) when no kind is
  given; effects log at indent 1, "who got what" summaries at indent 2. The view sends the last 200
  entries as `{i, turn, kind, indent, text}`; `i` is the entry's position in the whole log, so a client can
  tell which entries are new (used for sounds and banners). Turn headers (`kind: "turn"`) are written when
  a turn starts. Undo rebuilds the log by replaying, so it is identical after an undo.
* **Costs.** Never read `CardDef.cost` for a price: call `engine.costs.card_cost(state, name)`. It subtracts
  `state.cost_reduction` (Bridge; reset in cleanup) and never goes below 0. Rules (`validate`, `legal_actions`),
  `Game._buy` and `EffectContext.cost_of/gainable` all use it, and the view adds `price` to each pile.
* **Reactions with an effect.** `CardDef.on_attack` (with `on_attack_min_hand`) lets a card in hand be offered
  when another player plays an Attack, before the Moat question (`EffectContext.attack`).
* **Counting plays.** `state.plays_this_turn` counts every Action play, including repeats by Throne Room
  (`EffectContext.resolve`); Conspirator reads it.
* **Card sets.** `CardDef.expansion` names the set; `kingdom_cards(expansions)` filters; `GameConfig.expansions`
  limits only the *random* Kingdom (a custom Kingdom may mix sets). Catastrophe cards are set `"Catastrophe"`
  and never appear in a random Kingdom.
* **Stats.** `PlayerState.bought` / `.gained` are filled by `zones.gain_card`, `zones.gain_from_trash` and
  `Game._buy`; `scoring.final_stats` builds the end-of-game summary (only sent once the game is finished).
* **Randomness for card effects** (The Snap, The Purge, Grand Swap's reshuffle) comes from the game's own seeded
  RNG, so replays and undo stay exact.
* **Page.** One HTML file, no libraries. Settings live in `localStorage` (`dom_settings`); the session token in
  `sessionStorage` (one player per tab). Sound is synthesised with Web Audio (no files) and only starts after
  the first click. Auto-play of Treasures and of the Action-phase skip fire once per game position
  (`view.version`) and never for a position an undo has just restored.

### Update 8 design notes

* **Resign, EndGame and Cheat are engine Actions** (`engine/actions.py`), so they are part of `history` and replay /
  undo reproduce them exactly. They are *never* in `legal_actions` (bots cannot pick them) and the network `action`
  message cannot carry them (`codec` does not know them): the server creates them from the dedicated messages, after
  its own checks (host-only for `end_game`; `resign` for any seated player). `validate` accepts Resign / EndGame at any
  moment (even mid-decision, even off turn); `Cheat` needs `state.cheats`, your own turn and no pending decision.
  Finishing clears `state.pending`, so a question left open dies with the game. `determine_winners` ignores resigned
  players; `state.end_reason` says why the game ended and is in the view.
* **Cheats** are a per-room, host-chosen flag (`GameConfig.cheats` -> `state.cheats`), default off. Phrases live in
  `engine/constants.CHEAT_PHRASES`; the server matches the chat text (case and spacing ignored) *only* when the flag is
  on and a game is active, otherwise the text is ordinary chat. Each use is a `cheat`-kind log line, so nobody is cheated
  in secret.
* **Special cards** (`CardType.SPECIAL`, `cards/special.py`) are fenced exactly like Catastrophes (`registry.fenced_cards()`
  = both kinds): 2 copies, own supply row, never end the game, never in a random Kingdom, untouchable by Lurker. The room's
  `catastrophes` list (max 2) may hold either kind.
* **Protection** is state on `PlayerState` (`protection` turns left, `protection_fresh`, `protected_forever`). It is only
  checked in `EffectContext.attack()`, so everything that is an Attack skips protected players before any Reaction question,
  and nothing that is not an Attack is affected. `Game._cleanup` counts it down at the end of the owner's turns (not the
  turn it was gained). **Rosebud** gifts to other players are `PlayerState.bonus_coins`, paid when their next real turn
  starts (a skipped turn does not use them up).
* **My games**: the page keeps `[{room, token, name}]` in `localStorage` and asks `list_games`. The server answers only for
  valid tokens, so a code alone reveals nothing.
* **Auto-end turn** is client-side like the other conveniences: Buy phase + `buys === 0` + no pending decision, after 700 ms,
  once per `view.version`, dropped if the position changed meanwhile, never for a position restored by an undo.

### Update 9 design notes

* **Companion cards.** `CardDef.companions` / `companion_of` let one pick bring extra piles (Exodia's four limbs).
  `registry.fenced_cards()` lists only selectable cards; `setup._with_companions` adds the extra piles to the supply
  and to `state.catastrophes` (so they are fenced like the rest) but `config.catastrophes` keeps only the picks, so
  replay is exact. (There is no limit on the number of picks since update 10.) A companion cannot be picked on its own.
* **Win conditions.** `Game._check_exodia` runs after every applied action (any player's hand can change on anyone's
  turn) and finishes the game with `_finish(winners=[i])`; `end_reason` says why.
* **Walls.** `state.walls` maps pile -> builder. `costs.is_walled(state, pile, player)` is the single check, used by
  `rules.validate/legal_actions` (Buy), `zones.gain_card` (every gain) and `EffectContext.gainable(gainer=...)` (what a
  card may offer; `gainer` is the player who would *receive* the card, e.g. Swindler's victim). `Game._next_turn` removes
  a builder's walls when that player's turn slot comes round (even if the turn is skipped).
* **Invisibility.** `PlayerState.invisible` makes `is_protected` true (so `attack()` skips the player) and is checked by
  Cataclysm (`zones.redistribute_all_cards` leaves them out unless they played it), Masquerade (`pass_cards` skips them),
  walls and Chance Time. Protection from a Guardian Angel / God Mode only affects Attacks.
* **Blindness** is state (`PlayerState.blind`, counted down in `_cleanup` for the owner) plus a view flag (`view["blind"]`,
  true only for the blinded viewer). Hiding is done by the page, which only ever hides things the player already owns
  (their own hand) or that are public; the server never sends less. The page shuffles hand and Supply order while
  blinded so the order cannot reveal names.
* **Randomness** for Chance Time (`EffectContext.random_int`), Grand Theft Auto (`zones.steal_random_hand_card`) and
  the other random cards always comes from `state.rng`, so a replay (undo) reproduces them.

### Update 10 design notes

* **What a player may see (rulebook).** `build_view` no longer contains `my_cards`, `my_discard` or any
  `discard_count`; each player entry has `deck_count` (you may count a draw pile) and `discard_top` (the only public
  card of a discard pile). Cards that are allowed to show a discard pile (Harbinger) do it through the options of
  their Decision. The trash is public (`view["trash"]`).
* **Reactions and Catastrophes.** `EffectContext.attack` skips the reaction step entirely when the source card has
  `CardType.CATASTROPHE`: nobody is asked about Moat or Diplomat. `is_protected` (Guardian Angel, God Mode, the Cloak)
  is still checked first.
* **No cap on house-rule cards**: `MAX_CATASTROPHES` is gone from the engine and the server; each pick is still
  validated (known card, unique, enough players, not a companion).
* **Undo** (`rooms._undo_target`): the requester's latest action in the whole history; the replay drops everything
  after it, whoever did it.
* **Page layout.** One grid per screen: `#game-grid` is `230px | 1fr | 330px` in a viewport-sized frame
  (`html, body { overflow: hidden }`, sections absolutely positioned inside `main`), so the page itself can never
  scroll; panels that may overflow (`#supply-panel`, `#log`, the hand panel, the lobby pickers, the results pop-up)
  scroll inside themselves. `#popup-layer` is a fixed full-screen flex container whose children (`#decision`,
  `#undo-panel`, `#gameover`) are the pop-ups; it only gets a backdrop (`.open`) while one of them is showing.
  Card size comes from the CSS variables `--cw` / `--ch`, stepped down on short screens.
  `tests/browser/layout/` (optional) renders the real page in headless Chromium to check all of this.

### Visible information
Each player's victory-point total is part of the public view (`players[i].vp`) on
request from the players. It leaks an aggregate, not card identities.

### Playtest notes
* The online game picks the first player at random (`GameConfig.random_start`);
  the engine default is still seat 0 so tests stay simple.
* Decision: a dropped player is waited for, never replaced by a bot.
* Update 10 removed the discard-pile and all-my-cards viewers again, following the rulebook (see below).
* Ideas not built yet: turn timers, and bots that play Action cards.

## 10. Known limitations

* All 26 base-set Kingdom cards are implemented. Only one kind of Reaction exists (blocks an Attack, like Moat). Reactions with other triggers or effects (Diplomat, Watchtower, Horse Traders) and Duration cards are not implemented yet.
* `legal_actions` for large optional choices enumerates all multisets (2^n for
  n cards); fine for a hand, but a UI should prefer `validate` for free-form
  answers (the CLI does).
* The browser page is functional rather than pretty; there is no chat, spectator
  mode or persistence yet.
* Disconnected players stall the game (it waits for them to rejoin). There is no
  turn timer or forfeit yet.
