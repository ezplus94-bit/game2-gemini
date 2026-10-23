const { JSDOM, VirtualConsole } = require("jsdom");
const URL = `http://127.0.0.1:${process.argv[2]}/`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const errors = [];
(async () => {
  const sockets = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push(String(e.detail || e.message)));
  const dom = await JSDOM.fromURL(URL, {
    runScripts: "dangerously", resources: "usable", pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(w) {                       // capture every WebSocket the page opens
      // no auto-play: this test compares the hand before and after the reconnect
      w.localStorage.setItem("dom_settings", JSON.stringify({ autoSkip: false, autoTreasures: false }));
      const Real = w.WebSocket;
      w.WebSocket = function (...a) { const s = new Real(...a); sockets.push(s); return s; };
      w.WebSocket.prototype = Real.prototype;
      Object.assign(w.WebSocket, { OPEN: 1, CLOSED: 3, CONNECTING: 0, CLOSING: 2 });
    },
  });
  const w = dom.window, $ = (id) => w.document.getElementById(id);
  const click = (el) => el.dispatchEvent(new w.MouseEvent("click", { bubbles: true }));
  const until = async (fn, what, ms = 8000) => { const end = Date.now() + ms; while (Date.now() < end) { if (fn()) return; await sleep(20); } throw new Error("timeout: " + what); };
  await sleep(300);
  $("name").value = "Ann"; click($("btn-create"));
  await until(() => !$("lobby").hidden, "lobby");
  click($("btn-bot")); await until(() => $("lobby-players").children.length === 2, "bot");
  click($("btn-start")); await until(() => !$("game").hidden, "game");
  const handBefore = [...$("hand").children].map((c) => c.textContent).join("|");
  const code = w.sessionStorage.getItem("dom_room");

  sockets[0].close();                      // the network drops
  await until(() => /disconnected/.test($("conn").textContent), "shows disconnected");
  await until(() => sockets.length === 2 && /^connected$/.test($("conn").textContent), "reconnected", 10000);
  await sleep(300);
  const handAfter = [...$("hand").children].map((c) => c.textContent).join("|");
  if (w.sessionStorage.getItem("dom_room") !== code) throw new Error("room changed");
  if ($("game").hidden) throw new Error("game screen lost after reconnect");
  if (handBefore !== handAfter) throw new Error("hand changed after reconnect: " + handBefore + " vs " + handAfter);
  console.log(JSON.stringify({ ok: errors.length === 0, reconnected: true, hand: handAfter, errors }));
  process.exit(errors.length ? 1 : 0);
})().catch((e) => { console.log("FAILED:", e.message, errors); process.exit(1); });
