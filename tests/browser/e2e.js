// Drives the real page (index.html) in jsdom against a live server, like two players would.
const { JSDOM, VirtualConsole } = require("jsdom");
const PORT = process.argv[2];
const URL = `http://127.0.0.1:${PORT}/`;
const errors = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function open(label, url = URL) {
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push(label + ": " + (e.detail || e.message || e)));
  vc.on("error", (e) => errors.push(label + " console.error: " + e));
  const dom = await JSDOM.fromURL(url, { runScripts: "dangerously", resources: "usable", pretendToBeVisual: true, virtualConsole: vc });
  const w = dom.window;
  w.addEventListener("error", (e) => errors.push(label + " window error: " + e.message));
  await sleep(300);
  return w;
}
const $ = (w, id) => w.document.getElementById(id);
const visible = (w, id) => !$(w, id).hidden;
const click = (el) => el.dispatchEvent(new el.ownerDocument.defaultView.MouseEvent("click", { bubbles: true }));
async function until(fn, what, ms = 8000) {
  const end = Date.now() + ms;
  while (Date.now() < end) { if (fn()) return; await sleep(20); }
  throw new Error("timeout waiting for: " + what);
}
function assert(c, m) { if (!c) throw new Error("ASSERT: " + m); }

// A simple "human": returns true if it did something.
const PRIORITY = ["Province", "Gold", "Smithy", "Silver", "Cellar", "Village"];
function step(w) {
  if (visible(w, "gameover")) return false;
  // decision panel
  if (visible(w, "decision")) {
    const prompt = $(w, "decision-prompt").textContent;
    const opts = [...$(w, "decision-options").children];
    const hint = $(w, "decision-hint").textContent;
    const min = parseInt(hint.match(/Choose (\d+)/)[1], 10);
    const names = opts.map((o) => o.dataset.name);
    if (/Cellar/.test(prompt)) {          // discard the Estates
      names.forEach((n, i) => { if (n === "Estate" || n === "Curse") click(opts[i]); });
    } else if (min >= 1) {
      for (let i = 0; i < min && i < opts.length; i++) click(opts[i]);
    }
    const btn = $(w, "btn-confirm");
    if (btn.disabled) return false;
    click(btn);
    return true;
  }
  const status = $(w, "status").textContent;
  if (!/^Your turn/.test(status)) return false;
  // play an action card from hand
  const hand = [...$(w, "hand").children].filter((c) => c.classList.contains("clickable"));
  if (/action phase/.test(status) && hand.length) { click(hand[0]); return true; }
  if (/action phase/.test(status)) { click($(w, "btn-end")); return true; }
  if (!$(w, "btn-treasures").hidden) { click($(w, "btn-treasures")); return true; }
  const piles = [...w.document.querySelectorAll("#supply-basic .clickable, #supply-kingdom .clickable")];
  for (const name of PRIORITY) {
    const p = piles.find((c) => c.querySelector(".name").textContent === name);
    if (p) { click(p); return true; }
  }
  click($(w, "btn-end"));
  return true;
}

(async () => {
  const A = await open("A");
  assert(visible(A, "home") && !visible(A, "lobby"), "home screen first");

  // empty name is rejected client-side
  click($(A, "btn-create"));
  assert($(A, "toast").textContent.includes("name"), "name required toast");

  $(A, "name").value = "Ann";
  click($(A, "btn-create"));
  await until(() => visible(A, "lobby"), "lobby for host");
  const code = $(A, "lobby-code").textContent;
  assert(/^[A-Z]{4}$/.test(code), "room code shown: " + code);

  // second player joins through the invite link
  const B = await open("B", URL + "#" + code);
  assert($(B, "code").value === code, "invite link prefilled the code");
  $(B, "name").value = "<b>Bo</b>";                 // hostile-looking name must stay text
  click($(B, "btn-join"));
  await until(() => visible(B, "lobby"), "lobby for guest");
  await until(() => $(A, "lobby-players").children.length === 2, "host sees the guest");
  assert($(A, "lobby-players").innerHTML.includes("&lt;b&gt;Bo&lt;/b&gt;"), "name is escaped, not parsed as HTML");
  assert(!$(B, "host-controls").hidden === false, "guest has no host controls");
  assert($(B, "btn-start").parentElement.hidden, "guest cannot start");

  // card sets: both ticked by default, the guest cannot change them, the last one cannot be unticked
  const setBoxes = (w) => [...$(w, "expansion-row").querySelectorAll("input")];
  assert(setBoxes(A).length === 4 && setBoxes(A).every((i) => i.checked), "Base, Alchemy, Intrigue and Seaside are all ticked by default");
  assert(setBoxes(B).every((i) => i.disabled), "guest cannot change the card sets");
  setBoxes(A)[0].checked = false; setBoxes(A)[0].dispatchEvent(new A.Event("change", { bubbles: true }));
  await until(() => setBoxes(B)[0].checked === false && setBoxes(B)[1].checked === true, "guest sees Base unticked");
  setBoxes(A)[1].checked = false; setBoxes(A)[1].dispatchEvent(new A.Event("change", { bubbles: true }));
  await until(() => setBoxes(B)[1].checked === false && setBoxes(B)[2].checked === true, "guest sees Alchemy unticked");
  setBoxes(A)[2].checked = false; setBoxes(A)[2].dispatchEvent(new A.Event("change", { bubbles: true }));
  await until(() => setBoxes(B)[2].checked === false && setBoxes(B)[3].checked === true, "guest sees Intrigue unticked");
  setBoxes(A)[3].checked = false; setBoxes(A)[3].dispatchEvent(new A.Event("change", { bubbles: true }));
  await until(() => /at least one card set/.test($(A, "toast").textContent), "cannot untick every card set");
  await until(() => setBoxes(A)[3].checked === true, "page re-syncs the rejected tick");
  setBoxes(A)[0].checked = true; setBoxes(A)[0].dispatchEvent(new A.Event("change", { bubbles: true }));
  await until(() => setBoxes(B)[0].checked === true, "Base ticked again");
  assert($(A, "kingdom-grid").textContent.includes("Torturer") && $(A, "kingdom-grid").textContent.includes("Cellar"), "kingdom picker lists both sets");
  assert([...$(A, "kingdom-grid").querySelectorAll(".exp-title")].map((e) => e.textContent).join() === "Base,Alchemy,Intrigue,Seaside", "picker grouped by set");
  assert($(A, "btn-leave") && !$(A, "btn-leave").hidden, "Leave button is in the header, in the lobby too");

  // host adds a bot and picks a custom kingdom
  click($(A, "btn-bot"));
  await until(() => $(A, "lobby-players").children.length === 3, "bot added");
  for (const want of ["Cellar", "Village", "Smithy", "Remodel", "Chapel"]) {
    const label = [...$(A, "kingdom-grid").querySelectorAll("label")].find((l) => l.textContent.includes(want + " ("));
    const box = label.querySelector("input");
    box.checked = true;
    box.dispatchEvent(new A.Event("change", { bubbles: true }));
    await until(() => [...$(A, "kingdom-grid").querySelectorAll("input")].some((i) => i.checked) , "checked");
    await sleep(60);
  }
  await until(() => /Custom Kingdom \(5\/10 selected\)/.test($(A, "kingdom-note").textContent), "custom kingdom note");
  await until(() => /Custom Kingdom \(5\/10 selected\)/.test($(B, "kingdom-note").textContent), "guest sees kingdom");

  // optional Catastrophe cards: the host ticks two, the guest sees the choice, and cannot change it
  assert([...$(B, "catastrophe-grid").querySelectorAll("input")].every((i) => i.disabled), "guest cannot edit catastrophes");
  for (const want of ["Time Stop", "Cataclysm"]) {
    const label = [...$(A, "catastrophe-grid").querySelectorAll("label")].find((l) => l.textContent.includes(want + " ("));
    const box = label.querySelector("input");
    box.checked = true;
    box.dispatchEvent(new A.Event("change", { bubbles: true }));
    await sleep(80);
  }
  await until(() => /Cataclysm/.test($(B, "catastrophe-note").textContent) && /Time Stop/.test($(B, "catastrophe-note").textContent), "guest sees the catastrophe choice");

  $(A, "chat-input").value = "hello from Ann <i>x</i>";
  click($(A, "btn-chat"));
  await until(() => $(B, "chat-log").textContent.includes("hello from Ann <i>x</i>"), "lobby chat reaches the guest");
  assert(!$(B, "chat-log").querySelector("i"), "chat text is never parsed as HTML");

  click($(A, "btn-start"));
  await until(() => visible(A, "game") && visible(B, "game"), "both enter the game");
  const supplyNames = [...A.document.querySelectorAll("#supply-kingdom .name")].map((e) => e.textContent).sort();
  assert(JSON.stringify(supplyNames) === JSON.stringify(["Cellar", "Chapel", "Remodel", "Smithy", "Village"]), "kingdom shown: " + supplyNames);
  assert($(A, "hand").children.length > 0, "host sees a hand");
  const cataNames = [...A.document.querySelectorAll("#supply-catastrophe .name")].map((e) => e.textContent).sort();
  assert(JSON.stringify(cataNames) === JSON.stringify(["Cataclysm", "Time Stop"]), "catastrophe row shown: " + cataNames);
  assert(!$(A, "catastrophe-row").hidden && !$(B, "catastrophe-row").hidden, "both players see the catastrophe row");
  assert([...A.document.querySelectorAll("#supply-catastrophe .count")].every((e) => e.textContent === "2"), "2 copies each");

  // ---- new page features
  assert(!$(A, "btn-leave").hidden && $(A, "btn-leave").closest("header"), "Leave button lives in the header during the game");
  assert($(A, "room-badge").textContent === code, "room code badge in the header");
  assert(!$(A, "btn-trash").hidden && $(A, "btn-trash").textContent === "Trash (0)", "trash button in the header");
  assert(A.document.documentElement.getAttribute("data-theme") === "dark", "dark theme is the default");
  assert($(A, "auto-treasures").checked && $(A, "auto-skip").checked, "auto-play Treasures and auto-skip default to ON");
  const firstTurn = $(A, "log").querySelector(".k-turn");
  assert(firstTurn && /^Turn 1\s+\|/.test(firstTurn.textContent), "log starts with a turn header: " + (firstTurn && firstTurn.textContent));
  assert([...$(A, "log").querySelectorAll(".log-line .tn")].every((t) => /^T\d+$/.test(t.textContent)), "every log line is prefixed with its turn number");
  // card help: the "i" button, right-click, and Card-help mode all show the card text
  const smithy = [...A.document.querySelectorAll("#supply-kingdom .card")].find((c) => c.dataset.name === "Smithy");
  click(smithy.querySelector(".info"));
  assert(!$(A, "modal-backdrop").hidden && $(A, "modal").textContent.includes("+3 Cards") && $(A, "modal").textContent.includes("Cost $4"), "card help shows the full text");
  A.document.dispatchEvent(new A.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  assert($(A, "modal-backdrop").hidden, "Escape closes the modal");
  smithy.dispatchEvent(new A.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  assert($(A, "modal").textContent.includes("Smithy"), "right-click opens card help");
  click($(A, "modal").querySelector(".close"));
  assert($(A, "modal-backdrop").hidden, "Close button closes the modal");
  click($(A, "btn-help"));
  const handCard = $(A, "hand").querySelector(".card");
  click(handCard);
  assert(!$(A, "modal-backdrop").hidden, "in Card-help mode a click explains the card");
  click($(A, "modal").querySelector(".close"));
  click($(A, "btn-help"));
  assert(!A.document.body.classList.contains("help-mode"), "Card-help mode turns off again");
  // trash viewer
  click($(A, "btn-trash"));
  assert(/Trash pile \(0\)/.test($(A, "modal").textContent) && /Nothing has been trashed/.test($(A, "modal").textContent), "empty trash viewer");
  click($(A, "modal").querySelector(".close"));
  // rulebook: nobody may look through or count a discard pile, or look through their deck (but the trash is public)
  assert(!$(A, "btn-deck-view") && !$(A, "btn-discard-view"), "no 'All my cards' and no 'My discard pile' buttons");
  assert(/draw pile: \d+ cards?/.test($(A, "deckinfo").textContent) && !/discard/i.test($(A, "deckinfo").textContent), "you may count your draw pile only: " + $(A, "deckinfo").textContent);
  const panelsText = [...$(A, "players").querySelectorAll(".player")].map((d) => d.textContent);
  assert(panelsText.length === 3 && panelsText.every((t) => /Discard pile, top card:/.test(t) && /Deck \d+/.test(t) && !/Discard \d/.test(t) && !/Discard pile \d/.test(t)), "player panels show the draw pile size and only the top discard card: " + panelsText[0]);
  // layout: players left, table in the middle, log / chat / turn bar on the right; questions and results are pop-ups
  const before = (a, b) => !!(a.compareDocumentPosition(b) & A.Node.DOCUMENT_POSITION_FOLLOWING);
  assert($(A, "left-col").contains($(A, "players")), "players are in the left column");
  assert($(A, "center-col").contains($(A, "supply-basic")) && $(A, "center-col").contains($(A, "inplay")) && $(A, "center-col").contains($(A, "hand")), "supply, in play and hand are in the middle");
  assert($(A, "right-col").contains($(A, "log")) && $(A, "right-col").contains($(A, "chat")) && $(A, "right-col").contains($(A, "topbar")), "log, chat and the turn bar are on the right");
  assert(before($(A, "log-panel"), $(A, "chat")) && before($(A, "chat"), $(A, "topbar")), "the turn bar sits under the chat, at the bottom right");
  assert(["decision", "undo-panel", "gameover"].every((id) => $(A, id).closest("#popup-layer")), "questions, undo votes and results are pop-ups");
  assert(!$(A, "popup-layer").classList.contains("open") || !$(A, "decision").hidden || !$(A, "undo-panel").hidden, "no empty pop-up backdrop");
  // the turn bar can be collapsed, and remembers it
  click($(A, "btn-collapse-bar"));
  assert($(A, "topbar").classList.contains("collapsed") && JSON.parse(A.localStorage.getItem("dom_settings")).barCollapsed === true, "turn bar collapses");
  click($(A, "btn-collapse-bar"));
  assert(!$(A, "topbar").classList.contains("collapsed"), "and expands again");
  assert(A.document.title.includes("Modinion") && !/Dominion/.test(A.document.title) && /Modinion/.test($(A, "home").textContent + A.document.querySelector("header h1").textContent), "the game is called Modinion");
  // settings: theme persists, sound and animation switches work
  click($(A, "btn-settings"));
  const theme = $(A, "set-theme");
  theme.value = "light"; theme.dispatchEvent(new A.Event("change", { bubbles: true }));
  assert(A.document.documentElement.getAttribute("data-theme") === "light", "theme switches to light");
  assert(JSON.parse(A.localStorage.getItem("dom_settings")).theme === "light", "theme is remembered");
  theme.value = "dark"; theme.dispatchEvent(new A.Event("change", { bubbles: true }));
  const anim = $(A, "set-anim"); anim.checked = false; anim.dispatchEvent(new A.Event("change", { bubbles: true }));
  assert(!A.document.body.classList.contains("anim"), "animations can be switched off");
  anim.checked = true; anim.dispatchEvent(new A.Event("change", { bubbles: true }));
  assert(A.document.body.classList.contains("anim"), "animations can be switched back on");
  click($(A, "modal").querySelector(".close"));

  // hidden information: opponents' panels show counts only, never card names from their hands
  const panelText = $(A, "players").textContent;
  assert(/Hand 5/.test(panelText), "opponent hand counts shown");

  assert(/3 VP/.test($(A, "players").textContent) && /3 VP/.test($(B, "players").textContent), "everyone's VP is visible");
  assert($(A, "chat-log").textContent.includes("hello from Ann"), "chat history carried into the game");
  $(B, "chat-input").value = "good luck";
  click($(B, "btn-chat"));
  await until(() => $(A, "chat-log").textContent.includes("good luck"), "in-game chat reaches the host");

  // undo with consent: wait for a human's turn (the page auto-skips the Action phase and auto-plays Treasures)
  let mover = null;
  await until(() => { for (const w of [A, B]) if (/^Your turn/.test($(w, "status").textContent)) { mover = w; return true; } return false; }, "a human's turn", 15000);
  const other = mover === A ? B : A;
  await until(() => /buy phase/.test($(mover, "status").textContent), "auto-skip to the Buy phase");
  await until(() => $(mover, "btn-treasures").hidden && /Coins\s*\$[1-9]/.test($(mover, "resources").textContent), "Treasures were played automatically", 4000);
  click($(mover, "btn-undo"));
  await until(() => !$(other, "undo-panel").hidden && !$(other, "btn-undo-yes").hidden, "the other human is asked to agree");
  assert(!$(mover, "btn-undo-cancel").hidden && $(mover, "btn-undo-yes").hidden, "requester sees Cancel, not Allow");
  click($(other, "btn-undo-no"));
  await until(() => $(mover, "undo-panel").hidden && /denied/.test($(mover, "chat-log").textContent), "denial reaches the requester");
  assert(/buy phase/.test($(mover, "status").textContent) && $(mover, "btn-treasures").hidden, "a denied undo changes nothing");
  click($(mover, "btn-undo"));
  await until(() => !$(other, "undo-panel").hidden, "asked again");
  click($(other, "btn-undo-yes"));
  await until(() => !$(mover, "btn-treasures").hidden, "approved undo takes the auto-played Treasures back");
  await sleep(300);
  assert(!$(mover, "btn-treasures").hidden && /buy phase/.test($(mover, "status").textContent), "auto-play does not immediately redo the undone move");
  // turn auto-play off: nothing is played for us any more
  const box = $(mover, "auto-treasures");
  box.checked = false; box.dispatchEvent(new mover.Event("change", { bubbles: true }));
  click($(mover, "btn-treasures"));
  await until(() => $(mover, "btn-treasures").hidden, "manual play all Treasures still works");
  box.checked = true; box.dispatchEvent(new mover.Event("change", { bubbles: true }));   // auto-play back ON, Treasures already played
  click($(mover, "btn-undo"));
  await until(() => !$(other, "undo-panel").hidden, "asked a third time");
  click($(other, "btn-undo-yes"));
  await until(() => !$(mover, "btn-treasures").hidden, "undo of the manual play");
  await sleep(400);
  assert(!$(mover, "btn-treasures").hidden, "auto-play does not replay the Treasures we just took back (stale-version guard)");
  click($(mover, "btn-undo"));
  await until(() => !$(other, "undo-panel").hidden, "asked a fourth time");
  click($(other, "btn-undo-yes"));
  await until(() => /action phase/.test($(mover, "status").textContent), "undoing the phase change restores the Action phase");
  await sleep(300);
  assert(/action phase/.test($(mover, "status").textContent), "auto-skip does not immediately redo the undone move");
  click($(mover, "btn-undo"));
  await until(() => $(mover, "toast").textContent.includes("Nothing to undo"), "nothing left to undo");
  box.checked = true; box.dispatchEvent(new mover.Event("change", { bubbles: true }));

  // play the whole game with both humans (the bot is driven by the server)
  let actions = 0, decisions = 0, idle = 0;
  while (!visible(A, "gameover")) {
    let acted = false;
    for (const w of [A, B]) {
      if (visible(w, "decision")) decisions++;
      if (step(w)) { acted = true; actions++; await sleep(15); }
    }
    if (!acted) { idle++; await sleep(25); } else idle = 0;
    assert(idle < 600, "game stalled (status A: " + $(A, "status").textContent + " | B: " + $(B, "status").textContent + ")");
    assert(actions < 6000, "too many actions");
  }
  await until(() => visible(B, "gameover"), "guest sees game over");
  const winners = $(A, "winners").textContent;
  assert(/^Winners?: /.test(winners), "winner text: " + winners);
  assert($(A, "scores").querySelectorAll("tr").length === 4, "score table has header + 3 players");
  assert(!$(A, "btn-rematch").hidden && $(B, "btn-rematch").hidden, "only host sees rematch");
  const cards = [...$(A, "stats").querySelectorAll(".stat-card")];
  assert(cards.length === 3, "one stats card per player: " + cards.length);
  assert(cards.every((c) => /\d+ VP/.test(c.textContent) && /Turns taken/.test(c.textContent) && /Where the points came from/.test(c.textContent) && /Cards bought/.test(c.textContent)), "stats cards show VP, turns, VP sources and purchases");
  assert($(A, "stats").querySelectorAll(".stat-card.winner").length >= 1, "winner highlighted");
  assert([...$(A, "log").querySelectorAll(".k-end")].length >= 2, "game-over lines are styled in the log");
  assert(/^Trash \(\d+\)$/.test($(A, "btn-trash").textContent), "trash button still there at the end");

  click($(A, "btn-rematch"));
  await until(() => visible(A, "lobby") && visible(B, "lobby"), "rematch returns both to lobby");

  // Regression: in the second game, whoever moves first with no Action cards must be
  // auto-advanced to the Buy phase just like in the first game.
  click($(A, "btn-start"));
  await until(() => visible(A, "game") && visible(B, "game"), "second game starts");
  let rematchChecked = false;
  for (const w of [A, B]) {
    if (/^Your turn/.test($(w, "status").textContent)) {
      await until(() => /buy phase/.test($(w, "status").textContent), "auto-skip works again after a rematch", 2500);
      rematchChecked = true;
    }
  }

  console.log(JSON.stringify({ ok: errors.length === 0, rematchChecked, actions, decisionsSeen: decisions, winners, errors }));
  process.exit(errors.length ? 1 : 0);
})().catch((e) => { console.log("FAILED:", e.message); console.log(errors); process.exit(1); });
