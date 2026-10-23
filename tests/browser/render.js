// Loads the page with a fake WebSocket and feeds it views built by the real engine
// (written to a JSON file by tests/test_browser.py). No server needed.
const { JSDOM, VirtualConsole } = require("jsdom");
const fs = require("fs");
const path = require("path");
const fixtures = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const html = fs.readFileSync(path.join(__dirname, "../../src/dominion/web/static/index.html"), "utf8");
const errors = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function assert(c, m) { if (!c) throw new Error("ASSERT: " + m); }

(async () => {
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push(String(e.detail || e.message || e)));
  const oscillators = [];
  const dom = new JSDOM(html, {
    url: "http://127.0.0.1:1/", runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(w) {
      w.__sent = [];
      w.WebSocket = class {
        constructor() { this.readyState = 1; w.__ws = this; setTimeout(() => this.onopen && this.onopen(), 0); }
        send(t) { w.__sent.push(JSON.parse(t)); }
        close() { this.readyState = 3; }
      };
      w.__push = (m) => w.__ws.onmessage({ data: JSON.stringify(m) });
      w.AudioContext = class {              // enough of the Web Audio API to count the sounds
        constructor() { this.currentTime = 0; this.state = "running"; this.destination = {}; }
        resume() {}
        createGain() { return { gain: { setValueAtTime() {}, exponentialRampToValueAtTime() {} }, connect() {} }; }
        createOscillator() {
          const o = { frequency: { setValueAtTime() {}, exponentialRampToValueAtTime() {} }, connect() {}, start() { oscillators.push(1); }, stop() {} };
          return o;
        }
      };
    },
  });
  const w = dom.window, $ = (id) => w.document.getElementById(id);
  const click = (el) => el.dispatchEvent(new w.MouseEvent("click", { bubbles: true }));
  await sleep(100);

  // join a room so the page switches to the game screen when a view arrives
  $("name").value = "Ann"; click($("btn-create"));
  await sleep(50);
  w.__push({ type: "joined", room: "ABCD", token: "t", seat: 0 });

  // ---- 1. text options (Pawn): rendered as buttons, selectable, answered with the option text
  w.__push(fixtures.pawn);
  assert(!$("decision").hidden, "decision panel visible");
  const opts = [...$("decision-options").children];
  assert(opts.length === 4 && opts.every((o) => o.classList.contains("opt")), "text options are plain buttons, not cards");
  assert($("btn-confirm").disabled, "Confirm disabled until two are chosen");
  click(opts[0]); assert($("btn-confirm").disabled, "one is not enough");
  click(opts[3]); assert(!$("btn-confirm").disabled, "two chosen");
  click($("btn-confirm"));
  const answer = w.__sent.filter((m) => m.type === "action").pop();
  assert(JSON.stringify(answer.action) === JSON.stringify({ type: "choose", selection: ["+1 Card", "+$1"] }), "answer sent: " + JSON.stringify(answer));

  // ---- 2. Moat-style optional card choice: "Choose none"
  w.__push(fixtures.moat);
  assert($("btn-confirm").textContent === "Choose none" && !$("btn-confirm").disabled, "optional decision can be skipped");
  click($("decision-options").children[0]);
  assert($("btn-confirm").textContent === "Confirm", "selecting changes the button");

  // ---- 3. Bridge: reduced prices on supply and hand cards
  w.__push(fixtures.bridge);
  assert(/Cards cost\s*-\$1/.test($("resources").textContent), "cost-reduction pill shown");
  const market = [...w.document.querySelectorAll("#supply-kingdom .card")].find((c) => c.dataset.name === "Market");
  assert(market.querySelector(".cost").textContent === "54" && market.querySelector(".cost s").textContent === "5", "Market shows $4 with $5 struck out: " + market.querySelector(".cost").textContent);
  assert(market.querySelector(".cost").classList.contains("cheaper"), "reduced cost highlighted");

  // ---- 4. double-type cards are painted with two colours
  const nobles = [...w.document.querySelectorAll("#supply-kingdom .card")].find((c) => c.dataset.name === "Nobles");
  assert(nobles && /linear-gradient/.test(nobles.style.background), "Nobles has a split colour: " + (nobles && nobles.style.background));
  assert(/Action - Victory/.test(nobles.querySelector(".types").textContent), "type line shows both types");
  const copper = [...w.document.querySelectorAll("#supply-basic .card")].find((c) => c.dataset.name === "Copper");
  assert(!/linear-gradient/.test(copper.style.background), "single-type card is one colour");

  // ---- 5. log: indent, kinds, turn prefixes, highlighted names; catastrophe banner, sounds
  w.__push(fixtures.swap);
  let lines = [...$("log").querySelectorAll(".log-line")];
  assert(lines.filter((l) => l.classList.contains("k-summary") && l.classList.contains("ind-2")).length === 2, "who-got-what summary lines are indented, one per player");
  assert(lines.some((l) => /gets .* loses /.test(l.textContent)), "summary says who got and lost what");
  // a new game session: the first view only sets the baseline, later views produce sounds and banners
  w.__push({ type: "left" });
  $("name").value = "Ann"; click($("btn-create"));
  w.__push({ type: "joined", room: "ABCD", token: "t", seat: 0 });
  w.document.querySelectorAll("#banner").forEach((b) => b.remove());      // left over from the Grand Swap above
  w.__push(fixtures.snap_before);
  assert(!$("banner"), "no banner for the first view of a session");
  const before = oscillators.length;
  w.__push(fixtures.snap);
  lines = [...$("log").querySelectorAll(".log-line")];
  assert(lines.some((l) => l.classList.contains("k-catastrophe")), "catastrophe line styled");
  assert(lines.some((l) => l.classList.contains("ind-1") && l.classList.contains("k-trash")), "effect lines are indented");
  assert(lines.some((l) => l.classList.contains("k-turn")) && lines.every((l) => l.classList.contains("k-turn") || /^T\d+/.test(l.textContent)), "turn headers and turn-number prefixes");
  assert($("log").querySelectorAll(".cn").length > 0 && $("log").querySelectorAll(".pn").length > 0, "card and player names are highlighted");
  assert($("banner") && /THE SNAP/.test($("banner").textContent), "catastrophe banner shown");
  assert(w.document.body.classList.contains("shaking"), "screen shake on a catastrophe");
  assert(oscillators.length > before, "a catastrophe sound was played");
  assert(/Trash \(\d+\)/.test($("btn-trash").textContent) && !/\(0\)/.test($("btn-trash").textContent), "trash count updated");
  click($("btn-trash"));
  assert(/Trash pile/.test($("modal").textContent) && $("modal").querySelectorAll(".card").length > 0, "trash viewer lists cards");
  click($("modal").querySelector(".close"));

  // ---- 6. sound switch: no oscillators when sound is off
  click($("btn-settings"));
  const snd = $("set-sound"); snd.checked = false; snd.dispatchEvent(new w.Event("change", { bubbles: true }));
  click($("modal").querySelector(".close"));
  const muted = oscillators.length;
  w.__push(fixtures.snap2);
  await sleep(300);
  assert(oscillators.length === muted, "no sound while muted");

  // ---- 6b. auto-play Treasures: once per position, and never right after an undo rewinds the game
  const sentPlays = () => w.__sent.filter((m) => m.type === "action" && m.action.type === "play_all_treasures").length;
  const withVersion = (msg, n) => { const c = JSON.parse(JSON.stringify(msg)); c.view.version = n; return c; };
  assert($("auto-treasures").checked, "auto-play Treasures is ON by default");
  let base = sentPlays();
  w.__push(withVersion(fixtures.buy, 50));
  assert(sentPlays() === base + 1, "auto-play sends 'play all Treasures' in the Buy phase");
  w.__push(withVersion(fixtures.buy, 50));
  assert(sentPlays() === base + 1, "no second request for the same position");
  w.__push(withVersion(fixtures.buy, 30));          // an undo rolled the game back to an earlier position
  assert(sentPlays() === base + 1, "the position restored by an undo is not auto-played again");
  w.__push(withVersion(fixtures.buy, 31));
  assert(sentPlays() === base + 2, "auto-play works again on the next new position");
  $("auto-treasures").checked = false; $("auto-treasures").dispatchEvent(new w.Event("change", { bubbles: true }));
  w.__push(withVersion(fixtures.buy, 40));
  assert(sentPlays() === base + 2, "nothing is played automatically when the box is unticked");
  assert(JSON.parse(w.localStorage.getItem("dom_settings")).autoTreasures === false, "the choice is remembered");
  $("auto-treasures").checked = true; $("auto-treasures").dispatchEvent(new w.Event("change", { bubbles: true }));
  assert(sentPlays() === base + 3, "ticking the box again plays the Treasures right away");
  // not during the Action phase, nor while a decision is pending
  base = sentPlays();
  w.__push(withVersion(fixtures.action_phase, 60));
  w.__push(withVersion(fixtures.pawn, 61));
  assert(sentPlays() === base, "no auto-play in the Action phase or during a decision");

  // ---- 6c. auto-end turn: only in the Buy phase with no Buys left, after a short pause, once, never after an undo
  const sentEnds = () => w.__sent.filter((m) => m.type === "action" && m.action.type === "end_phase").length;
  assert($("auto-end").checked, "auto-end turn is ON by default");
  base = sentEnds();
  w.__push(withVersion(fixtures.buy_before, 70));            // still has a Buy left
  await sleep(900);
  assert(sentEnds() === base, "no auto-end while a Buy is left");
  w.__push(withVersion(fixtures.buys_out, 71));
  assert(sentEnds() === base, "the turn does not end instantly (you get to see your last purchase)");
  await sleep(900);
  assert(sentEnds() === base + 1, "the turn ends by itself once out of Buys");
  w.__push(withVersion(fixtures.buys_out, 71));
  await sleep(900);
  assert(sentEnds() === base + 1, "only once per position");
  w.__push(withVersion(fixtures.buys_out, 60));              // rolled back by an undo
  await sleep(900);
  assert(sentEnds() === base + 1, "the position an undo restored is not auto-ended again");
  w.__push(withVersion(fixtures.buys_out, 72));
  w.__push(withVersion(fixtures.buy_before, 73));            // the player moved on before the pause was over
  await sleep(900);
  assert(sentEnds() === base + 1, "a stale pending auto-end is dropped when the game has moved on");
  $("auto-end").checked = false; $("auto-end").dispatchEvent(new w.Event("change", { bubbles: true }));
  w.__push(withVersion(fixtures.buys_out, 80));
  await sleep(900);
  assert(sentEnds() === base + 1, "nothing when the box is unticked");
  assert(JSON.parse(w.localStorage.getItem("dom_settings")).autoEnd === false, "remembered");
  $("auto-end").checked = true; $("auto-end").dispatchEvent(new w.Event("change", { bubbles: true }));

  // ---- 6d. protection tags, Rosebud gifts, special cards look different from Catastrophes
  w.__push(fixtures.protected);
  const tags = [...$("players").querySelectorAll(".tag")].map((t) => t.textContent);
  assert(tags.includes("protected: 3 turns") && tags.includes("protected: God Mode") && tags.includes("gets $12 next turn"), "player tags: " + tags);
  const rose = [...w.document.querySelectorAll("#supply-catastrophe .card")].find((c) => c.dataset.name === "Rosebud");
  assert(rose && rose.classList.contains("t-special") && rose.style.background.includes("--c-special"), "Rosebud is painted as a Special card");
  assert(/Special/.test(rose.querySelector(".types").textContent), "type line says Special");
  click(rose.querySelector(".info"));
  assert(/Special card: only 2 copies/.test($("modal").textContent) && /\$12/.test($("modal").textContent), "card help explains the Special card");
  click($("modal").querySelector(".close"));
  assert(!$("catastrophe-row").hidden && /Special cards/.test($("catastrophe-row").textContent), "the row mentions Special cards");

  // ---- 6e. a Special card: gold banner and fanfare, no shake; cheats: their own sound and log colour
  w.__push({ type: "left" });
  $("name").value = "Ann"; click($("btn-create"));
  w.__push({ type: "joined", room: "ABCD", token: "t", seat: 0 });
  click($("btn-settings")); const s2 = $("set-sound"); s2.checked = true; s2.dispatchEvent(new w.Event("change", { bubbles: true })); click($("modal").querySelector(".close"));
  w.document.querySelectorAll("#banner").forEach((b) => b.remove());
  w.__push(fixtures.rose_before);
  let n0 = oscillators.length;
  w.__push(fixtures.rose_after);
  assert($("banner") && $("banner").classList.contains("special") && /ROSEBUD/.test($("banner").textContent), "gold banner for a Special card");
  assert(!w.document.body.classList.contains("shaking"), "no screen shake for a Special card");
  assert(oscillators.length >= n0 + 5, "fanfare played");
  assert([...$("log").querySelectorAll(".k-special")].length === 1, "Special log line styled");
  w.__push({ type: "left" });
  $("name").value = "Ann"; click($("btn-create"));
  w.__push({ type: "joined", room: "ABCD", token: "t", seat: 0 });
  w.document.querySelectorAll("#banner").forEach((b) => b.remove());
  w.__push(fixtures.cheat_before);
  n0 = oscillators.length;
  w.__push(fixtures.cheat_after);
  assert(oscillators.length >= n0 + 2, "cheat sound played");
  assert([...$("log").querySelectorAll(".k-cheat")].length === 1, "cheat log line styled");
  assert(!$("banner"), "no banner for a cheat");
  assert(/Coins\s*\$100/.test($("resources").textContent), "coins updated");

  // ---- 6f. Game menu: Cancel on the confirmation does nothing; Resign sends the message
  w.__push(fixtures.cheat_before);
  const sent = (t) => w.__sent.filter((m) => m.type === t).length;
  click($("btn-game"));
  w.confirm = () => false;
  const r0 = sent("resign");
  click($("menu-resign"));
  assert(sent("resign") === r0 && !$("modal-backdrop").hidden, "declining the confirmation sends nothing and keeps the menu open");
  w.confirm = () => true;
  click($("menu-resign"));
  assert(sent("resign") === r0 + 1 && $("modal-backdrop").hidden, "resign is sent after confirming");
  w.__push({ type: "game", room: "ABCD", host: 1, view: fixtures.cheat_before.view });       // someone else is host
  click($("btn-game"));
  assert($("menu-end").disabled && $("menu-delete").disabled && !$("menu-resign").disabled, "non-host: only Resign");
  click($("modal").querySelector(".close"));
  w.__push(fixtures.resigned);
  assert(/Winner: P0/.test($("winners").textContent) && /P1 resigned\./.test($("end-reason").textContent), "resignation shown at game over");
  click($("btn-game"));
  assert($("menu-resign").disabled && $("menu-end").disabled, "nothing to resign from once the game is over");
  click($("modal").querySelector(".close"));

  // ---- 6g. lobby: cheat box for the host and the guest
  w.__push(fixtures.lobby.off_host);
  assert(!$("cheats-box").checked && !$("cheats-box").disabled, "host: unticked, enabled");
  const c0 = sent("set_cheats");
  $("cheats-box").checked = true; $("cheats-box").dispatchEvent(new w.Event("change", { bubbles: true }));
  assert(sent("set_cheats") === c0 + 1 && w.__sent.filter((m) => m.type === "set_cheats").pop().cheats === true, "ticking sends set_cheats");
  w.__push(fixtures.lobby.on_host);
  assert($("cheats-box").checked && /show me the money.*power overwhelming.*greed is good/.test($("cheats-note").textContent), "phrases are listed once cheats are on");
  w.__push(fixtures.lobby.on_guest);
  assert($("cheats-box").checked && $("cheats-box").disabled, "guest: ticked but locked");
  assert(/Catastrophe &|Catastrophe \& Special|Special/.test($("catastrophe-grid").parentElement.textContent), "lobby section mentions Special cards");
  const exodiaLabel = [...$("catastrophe-grid").querySelectorAll("label")].find((l) => l.textContent.includes("Exodia"));
  assert(exodiaLabel && exodiaLabel.textContent.trim() === "Exodia the Forbidden One ($5)" + exodiaLabel.querySelector("button").textContent, "the Exodia label is just its name and cost: " + (exodiaLabel && exodiaLabel.textContent));
  assert(/any number|as many/.test($("catastrophe-grid").parentElement.textContent) || /Tick any number/.test($("catastrophe-note").textContent), "the lobby says there is no limit");
  assert($("catastrophe-grid").textContent.includes("Rosebud") && $("catastrophe-grid").textContent.includes("God Mode") && $("catastrophe-grid").textContent.includes("Guardian Angel"), "Special cards can be picked in the lobby");

  // ---- 6h. Fortnite walls
  w.__push({ type: "left" });
  $("name").value = "Ann"; click($("btn-create"));
  w.__push({ type: "joined", room: "ABCD", token: "t", seat: 0 });
  w.__push(fixtures.walls_p1);
  const gold = [...w.document.querySelectorAll("#supply-basic .card")].find((c) => c.dataset.name === "Gold");
  const silver = [...w.document.querySelectorAll("#supply-basic .card")].find((c) => c.dataset.name === "Silver");
  assert(gold.classList.contains("walled") && /Walled off by P0/.test(gold.title), "walled pile is marked, and its tooltip names the builder: " + gold.title);
  click(gold.querySelector(".info"));
  assert(/Walled off by P0/.test($("modal").textContent), "card help says who walled it off");
  click($("modal").querySelector(".close"));
  assert(!silver.classList.contains("walled"), "other piles are not marked");
  assert(!gold.classList.contains("clickable"), "a walled pile cannot be bought by someone else");
  w.__push(fixtures.walls_p0);
  assert(w.document.querySelector("#supply-basic .card.walled"), "the builder sees the walls too");

  // ---- 6i. Roofie: blinded players see only card types
  w.__push({ type: "left" });
  $("name").value = "Ann"; click($("btn-create"));
  w.__push({ type: "joined", room: "ABCD", token: "t", seat: 1 });
  w.__push(fixtures.roofie_before_p1);
  const names = () => [...w.document.querySelectorAll(".card")].map((c) => c.querySelector(".name").textContent);
  assert(names().includes("Smithy") && names().includes("Gold"), "normal view shows names");
  assert($("hand").querySelector(".card .count"), "duplicates are stacked normally");
  w.__push(fixtures.roofie_p1);
  assert($("hand").querySelectorAll(".card").length === 5, "blinded: five separate cards, no stacks: " + $("hand").querySelectorAll(".card").length);
  assert([...w.document.querySelectorAll("#hand .card, #supply-basic .card, #supply-kingdom .card, #supply-catastrophe .card")].every((c) => c.querySelector(".name").textContent === "???"), "every card name is hidden");
  assert([...w.document.querySelectorAll(".card")].every((c) => !c.querySelector(".cost") || c.querySelector(".cost").textContent === "?"), "every cost is hidden");
  assert([...w.document.querySelectorAll(".card")].every((c) => !/Smithy|Gold|Province|Copper|Estate/.test(c.title)), "tooltips do not leak names");
  assert(/types\s*only|Blinded/.test($("resources").textContent) && w.document.body.classList.contains("blinded"), "blind pill and style");
  const typesNow = [...$("hand").querySelectorAll(".card .types")].map((t) => t.textContent).sort().join();
  assert(typesNow === ["Action", "Action", "Treasure", "Victory", "Victory"].join(), "but the types are shown: " + typesNow);
  assert(!/Smithy|Gold|Copper|Estate/.test($("hand").textContent) && !/Smithy/.test($("supply-kingdom").textContent), "no card text anywhere in hand or supply");
  assert($("log").querySelectorAll(".cn").length === 0 || [...$("log").querySelectorAll(".cn")].every((c) => c.textContent === "???"), "card names in the log are hidden too");
  click($("hand").querySelector(".card .info"));
  assert(/You are blinded/.test($("modal").textContent) && !/\+\d Cards?/.test($("modal").textContent), "card help refuses while blinded");
  click($("modal").querySelector(".close"));
  const order1 = [...w.document.querySelectorAll("#supply-basic .card .types")].map((t) => t.textContent).join();
  assert([...w.document.querySelectorAll("#players .tag.blind")].length === 1, "exactly one blinded tag (P2 wears the Cloak and is unaffected)");
  w.__push(fixtures.roofie_p0);
  assert(names().includes("Roofie") || names().includes("Smithy") || names().includes("Gold"), "the attacker still reads cards");
  assert([...w.document.querySelectorAll("#players .tag")].some((t) => t.textContent === "invisible"), "invisible player is tagged");
  assert(!w.document.body.classList.contains("blinded"), "blind style off for the attacker");

  // ---- 6j. Midas Touch pill, Exodia banner and game over
  w.__push({ type: "left" });
  $("name").value = "Ann"; click($("btn-create"));
  w.__push({ type: "joined", room: "ABCD", token: "t", seat: 0 });
  w.__push(fixtures.midas);
  assert(/Midas Touch\s*Treasures = \$3/.test($("resources").textContent), "Midas pill");
  w.__push({ type: "left" });
  $("name").value = "Ann"; click($("btn-create"));
  w.__push({ type: "joined", room: "ABCD", token: "t", seat: 0 });
  w.__push(fixtures.exodia_piles);
  const piece = [...w.document.querySelectorAll("#supply-catastrophe .card")].map((c) => c.dataset.name);
  assert(piece.length === 5 && piece[0].startsWith("Exodia"), "all five Exodia piles are in the supply row: " + piece);
  const faces = [...w.document.querySelectorAll("#supply-catastrophe .card .name")].map((n) => n.textContent);
  assert(faces.join() === "Exodia,Right Arm,Left Arm,Right Leg,Left Leg", "short names on the card faces: " + faces);
  assert([...w.document.querySelectorAll("#supply-catastrophe .card")][1].title.startsWith("Right Arm of the Forbidden One"), "the tooltip keeps the full name");
  click($("btn-help")); click([...w.document.querySelectorAll("#supply-catastrophe .card")][1]);
  assert(/all five pieces of Exodia/.test($("modal").textContent), "a limb explains the win condition");
  click($("modal").querySelector(".close")); click($("btn-help"));
  w.document.querySelectorAll("#banner").forEach((b) => b.remove());
  w.__push(fixtures.exodia_before);
  w.__push(fixtures.exodia_won);
  assert($("banner") && $("banner").classList.contains("special") && /EXODIA/.test($("banner").textContent), "Exodia banner");
  assert(!$("gameover").hidden && /Winner: P0/.test($("winners").textContent) && /Exodia/.test($("end-reason").textContent), "game over says why");

  // ---- 6k. pop-ups: a question opens in the middle, can be put aside to look at the table, and comes back
  w.__push({ type: "left" });
  $("name").value = "Ann"; click($("btn-create"));
  w.__push({ type: "joined", room: "ABCD", token: "t", seat: 0 });
  w.__push(fixtures.moat_for_me || fixtures.pawn);
  assert(!$("decision").hidden && $("popup-layer").classList.contains("open"), "a question opens the pop-up layer");
  assert($("decision").closest("#popup-layer"), "the question lives in the pop-up layer");
  click($("btn-decision-peek"));
  assert($("decision").classList.contains("peek") && !$("btn-decision-restore").hidden && !$("popup-layer").classList.contains("open"), "'Look at the table' hides the question and the backdrop");
  click($("btn-decision-restore"));
  assert(!$("decision").classList.contains("peek") && $("btn-decision-restore").hidden && $("popup-layer").classList.contains("open"), "the question comes back");
  click($("btn-decision-peek"));
  w.__push(withVersion(fixtures.pawn, 900));                // a new question: it is shown again, not left hidden
  assert(!$("decision").classList.contains("peek") && $("btn-decision-restore").hidden, "a new question is never left hidden");
  w.__push(fixtures.cheat_before);                           // the question is answered: no pop-up, no empty backdrop
  assert($("decision").hidden && !$("popup-layer").classList.contains("open") && $("btn-decision-restore").hidden, "no empty backdrop once nothing is asked");

  // ---- 6l. results pop-up: Close shows the table, the header Results button brings it back
  w.__push(fixtures.finished);
  assert(!$("gameover").hidden && $("popup-layer").classList.contains("open") && !$("btn-results").hidden, "results open as a pop-up, with a Results button in the header");
  click($("btn-close-results"));
  assert($("gameover").hidden && !$("popup-layer").classList.contains("open") && !$("btn-results").hidden, "Close shows the table underneath");
  w.__push(fixtures.finished);                               // later updates do not pop it up again
  assert($("gameover").hidden, "closed results stay closed");
  click($("btn-results"));
  assert(!$("gameover").hidden && $("popup-layer").classList.contains("open"), "the Results button reopens them");

  // ---- 7. end of game: stats for every player, VP breakdown adds up
  w.__push(fixtures.finished);
  assert(!$("gameover").hidden, "game over panel");
  const cards = [...$("stats").querySelectorAll(".stat-card")];
  assert(cards.length === fixtures.finished.view.players.length, "a stats card per player");
  fixtures.finished.view.stats.forEach((s, i) => {
    const sum = s.vp_breakdown.reduce((a, r) => a + r.vp, 0);
    assert(sum === s.vp, "breakdown adds up for " + s.name);
    assert(cards[i].textContent.includes(s.vp + " VP"), "VP shown for " + s.name);
  });
  assert(/Where the points came from/.test(cards[0].textContent), "VP breakdown section");

  console.log(JSON.stringify({ ok: errors.length === 0, errors }));
  process.exit(errors.length ? 1 : 0);
})().catch((e) => { console.log("FAILED:", e.message); console.log(errors); process.exit(1); });
