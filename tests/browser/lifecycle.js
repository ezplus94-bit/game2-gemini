// Real server, real pages: cheat codes in the lobby and chat, the Game menu (resign / end / delete),
// and the "Your games" list on the home page.
const { JSDOM, VirtualConsole } = require("jsdom");
const PORT = process.argv[2];
const URL = `http://127.0.0.1:${PORT}/`;
const errors = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function open(label) {
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push(label + ": " + (e.detail || e.message || e)));
  vc.on("error", (e) => errors.push(label + " console.error: " + e));
  const dom = await JSDOM.fromURL(URL, { runScripts: "dangerously", resources: "usable", pretendToBeVisual: true, virtualConsole: vc });
  const w = dom.window;
  w.confirm = () => true;
  w.addEventListener("error", (e) => errors.push(label + " window error: " + e.message));
  await sleep(300);
  return w;
}
const $ = (w, id) => w.document.getElementById(id);
const click = (el) => el.dispatchEvent(new el.ownerDocument.defaultView.MouseEvent("click", { bubbles: true }));
const change = (el) => el.dispatchEvent(new el.ownerDocument.defaultView.Event("change", { bubbles: true }));
async function until(fn, what, ms = 8000) {
  const end = Date.now() + ms;
  while (Date.now() < end) { if (fn()) return; await sleep(20); }
  throw new Error("timeout waiting for: " + what);
}
function assert(c, m) { if (!c) throw new Error("ASSERT: " + m); }
const say = (w, text) => { $(w, "chat-input").value = text; click($(w, "btn-chat")); };
const closeModal = (w) => click($(w, "modal").querySelector(".close"));

(async () => {
  const A = await open("Ann"), B = await open("Bo");
  $(A, "name").value = "Ann"; click($(A, "btn-create"));
  await until(() => !$(A, "lobby").hidden, "Ann in lobby");
  const code = $(A, "lobby-code").textContent;
  $(B, "name").value = "Bo"; $(B, "code").value = code; click($(B, "btn-join"));
  await until(() => !$(B, "lobby").hidden && $(B, "lobby-count").textContent === "2/4", "Bo in lobby");

  // ---- cheat codes: host's choice, off by default
  assert(!$(A, "cheats-box").checked && !$(A, "cheats-box").disabled, "host sees an unticked, enabled cheat box");
  assert($(B, "cheats-box").disabled, "the guest cannot change it");
  assert(/Off/.test($(A, "cheats-note").textContent), "off by default");
  $(A, "cheats-box").checked = true; change($(A, "cheats-box"));
  await until(() => $(B, "cheats-box").checked && /show me the money/.test($(B, "cheats-note").textContent), "guest sees cheats on and the phrases");

  // ---- Game menu in the lobby: only Delete, and only for the host
  click($(A, "btn-game"));
  assert($(A, "menu-delete") && !$(A, "menu-delete").disabled && !$(A, "menu-resign"), "lobby menu: host can delete, no resign yet");
  closeModal(A);
  click($(B, "btn-game"));
  assert($(B, "menu-delete").disabled, "the guest cannot delete");
  closeModal(B);

  click($(A, "btn-start"));
  await until(() => !$(A, "game").hidden && !$(B, "game").hidden, "game started");
  let mover = null;
  await until(() => { for (const w of [A, B]) if (/^Your turn/.test($(w, "status").textContent)) { mover = w; return true; } return false; }, "someone's turn");
  const other = mover === A ? B : A;
  await until(() => /buy phase/.test($(mover, "status").textContent), "auto-skip to the Buy phase");

  // ---- cheat codes in the chat
  const coinsOf = (w) => parseInt(($(w, "resources").textContent.match(/Coins\s*\$(\d+)/) || [0, "-1"])[1], 10);
  await until(() => $(mover, "btn-treasures").hidden, "Treasures auto-played");
  await sleep(400);
  const before = coinsOf(mover);
  say(other, "show me the money");                                   // not their turn
  await until(() => /your own turn/.test($(other, "toast").textContent), "cheating off-turn is refused");
  assert(coinsOf(mover) === before, "the other player's attempt changed nothing");
  say(mover, "show me the money");
  await until(() => coinsOf(mover) >= before + 100, "+100 coins");
  say(mover, "greed is good");
  await until(() => /Buys\s*10[1-9]/.test($(mover, "resources").textContent), "+100 buys");
  say(mover, "power overwhelming");
  await until(() => /Actions\s*10[0-9]/.test($(mover, "resources").textContent), "+100 actions");
  assert(!/show me the money|greed is good|power overwhelming/.test($(other, "chat-log").textContent), "cheat codes are not shown as chat");
  await until(() => $(other, "log").querySelectorAll(".k-cheat").length === 3, "all three cheats are announced in the log");
  assert(/cheat code: \+100 coins/.test($(other, "log").textContent), "announcement names the cheat");

  // ---- Game menu during the game
  click($(mover, "btn-game"));
  assert($(mover, "menu-resign") && !$(mover, "modal-backdrop").hidden, "the Game menu opens during a game");
  closeModal(mover);
  click($(A, "btn-game"));
  assert(!$(A, "menu-resign").disabled && !$(A, "menu-end").disabled && !$(A, "menu-delete").disabled, "host: resign, end and delete are all available");
  closeModal(A);
  click($(B, "btn-game"));
  assert(!$(B, "menu-resign").disabled && $(B, "menu-end").disabled && $(B, "menu-delete").disabled, "guest: only resign");
  // ---- Bo resigns (it does not have to be Bo's turn)
  click($(B, "menu-resign"));
  await until(() => !$(A, "gameover").hidden && !$(B, "gameover").hidden, "game over after the resignation");
  assert(/Winner: Ann/.test($(A, "winners").textContent), "Ann wins: " + $(A, "winners").textContent);
  assert(/Bo resigned\./.test($(A, "end-reason").textContent) && !$(A, "end-reason").hidden, "reason shown");
  assert([...$(A, "players").querySelectorAll(".tag.bad")].some((t) => t.textContent === "resigned"), "Bo is tagged as resigned");
  assert($(A, "stats").querySelectorAll(".stat-card").length === 2, "stats for both players");
  assert($(B, "modal-backdrop").hidden, "the menu closed itself");

  // ---- "Your games": leave, find it on the home page, view it again
  click($(A, "btn-leave"));
  await until(() => !$(A, "home").hidden && !$(A, "my-games-panel").hidden, "Your games appears on the home page");
  let row = $(A, "my-games").querySelector(".grow");
  assert(row.dataset.room === code && /finished/.test(row.textContent) && /host/.test(row.textContent), "row shows code, status, host: " + row.textContent);
  assert([...row.querySelectorAll("button")].map((b) => b.textContent).join() === "View,Delete,Forget", "buttons: " + [...row.querySelectorAll("button")].map((b) => b.textContent));
  click(row.querySelector("button.primary"));
  await until(() => !$(A, "game").hidden && !$(A, "gameover").hidden, "viewing the finished game again");
  click($(A, "btn-leave"));
  await until(() => !$(A, "my-games-panel").hidden, "back at the list");
  // the guest sees it too, without the Delete button
  click($(B, "btn-leave"));
  await until(() => !$(B, "my-games-panel").hidden, "guest's list");
  row = $(B, "my-games").querySelector(".grow");
  assert([...row.querySelectorAll("button")].map((b) => b.textContent).join() === "View,Forget", "a guest cannot delete");
  // "Forget" only removes it from the list
  click(row.querySelector("button:last-child"));
  await until(() => $(B, "my-games-panel").hidden, "forgotten");
  assert(B.localStorage.getItem("dom_games") === "[]", "the list is saved empty");

  // ---- host deletes from the home page
  row = $(A, "my-games").querySelector(".grow");
  click(row.querySelector("button.danger"));
  await until(() => $(A, "my-games-panel").hidden, "game deleted from the list");
  assert(/deleted/.test($(A, "toast").textContent), "toast confirms");
  $(B, "code").value = code; $(B, "name").value = "Bo"; click($(B, "btn-join"));
  await until(() => /Room not found/.test($(B, "toast").textContent), "the room is really gone");

  // ---- a second game: the host ends it early; a bot plays along
  click($(A, "btn-create"));
  await until(() => !$(A, "lobby").hidden, "new lobby");
  click($(A, "btn-bot"));
  await until(() => $(A, "lobby-count").textContent === "2/4", "bot added");
  assert($(A, "cheats-box").checked === false, "a new game starts with cheats off");
  click($(A, "btn-start"));
  await until(() => !$(A, "game").hidden, "second game started");
  click($(A, "btn-game"));
  click($(A, "menu-end"));
  await until(() => !$(A, "gameover").hidden, "game ended early");
  assert(/Ann ended the game early/.test($(A, "end-reason").textContent), "reason: " + $(A, "end-reason").textContent);
  assert(!/resigned/.test([...$(A, "players").querySelectorAll(".tag")].map((t) => t.textContent).join()), "nobody is tagged resigned");
  // ---- and deleted from inside the game menu
  click($(A, "btn-game"));
  click($(A, "menu-delete"));
  await until(() => !$(A, "home").hidden, "sent home after deleting");
  assert(/deleted/.test($(A, "toast").textContent), "told it was deleted");
  assert($(A, "my-games-panel").hidden, "nothing left in Your games");

  console.log(JSON.stringify({ ok: errors.length === 0, errors }));
  process.exit(errors.length ? 1 : 0);
})().catch((e) => { console.log("FAILED:", e.message); console.log(errors); process.exit(1); });
