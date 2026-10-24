// Renders the page in a real (headless) Chromium with a fake WebSocket and views built by the real engine.
// Usage: node layout.mjs fixtures.json [screenshot-dir]      (prints one JSON line per size/screen)
import chromium from "@sparticuz/chromium";
import puppeteer from "puppeteer-core";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const here = path.dirname(fileURLToPath(import.meta.url));
const html = "file://" + path.resolve(here, "../../../src/dominion/web/static/index.html");
const fx = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const shotDir = process.argv[3] || null;
const sizes = [[1366, 768], [1920, 1080], [1536, 864], [1280, 720]];
const screens = [["home", null], ["lobby", "lobby"], ["mid", "mid"], ["decision", "decision"], ["lurker", "decision_lurker"], ["finished", "finished"], ["bighand", "big_hand"]];

const browser = await puppeteer.launch({ args: [...chromium.args, "--no-sandbox"], executablePath: await chromium.executablePath(), headless: "shell" });
for (const [w, h] of sizes) {
  const page = await browser.newPage();
  await page.setViewport({ width: w, height: h });
  await page.evaluateOnNewDocument(() => {
    window.WebSocket = class { constructor() { this.readyState = 1; window.__ws = this; setTimeout(() => this.onopen && this.onopen(), 0); } send() {} close() {} };
    window.__push = (m) => window.__ws.onmessage({ data: JSON.stringify(m) });
  });
  await page.goto(html);
  await new Promise((r) => setTimeout(r, 200));
  for (const [name, key] of screens) {
    if (key) {
      await page.evaluate(() => { document.getElementById("name").value = "Ann"; document.getElementById("btn-create").click(); });
      await new Promise((r) => setTimeout(r, 60));
      await page.evaluate((m, j, isLobby) => {
        if (!isLobby) window.__push({ type: "left" });
        document.getElementById("name").value = "Ann"; document.getElementById("btn-create").click();
        window.__push(j); window.__push(m);
      }, key === "lobby" ? fx.lobby : fx[key], fx.joined, key === "lobby");
    }
    await new Promise((r) => setTimeout(r, 450));
    const m = await page.evaluate(() => {
      const de = document.documentElement;
      const rect = (id) => { const e = document.getElementById(id); if (!e || e.hidden) return null; const r = e.getBoundingClientRect(); return { l: Math.round(r.left), t: Math.round(r.top), r: Math.round(r.right), b: Math.round(r.bottom) }; };
      const scrolls = [];
      for (const id of ["supply-panel", "hand-panel", "inplay-panel", "players", "log", "picker-panel", "gameover", "decision"]) {
        const e = document.getElementById(id);
        if (e && !e.hidden && e.scrollHeight > e.clientHeight + 1) scrolls.push(id);
      }
      const overflowY = {};
      for (const id of ["supply-panel", "hand-panel", "inplay-panel", "players", "log", "picker-panel", "decision", "gameover"]) {
        const e = document.getElementById(id);
        if (e) overflowY[id] = getComputedStyle(e).overflowY;
      }
      return { overflowY, pageScrollY: de.scrollHeight - innerHeight, pageScrollX: de.scrollWidth - innerWidth, bodyScrollY: document.body.scrollHeight - innerHeight,
               innerScrolls: scrolls, vw: innerWidth, vh: innerHeight,
               topbar: rect("topbar"), chat: rect("chat"), hand: rect("hand-panel"), supply: rect("supply-panel"), bottom: rect("bottom-row"), decision: rect("decision"), gameover: rect("gameover"), players: rect("players-panel") };
    });
    console.log(JSON.stringify({ size: `${w}x${h}`, screen: name, ...m }));
    if (shotDir) await page.screenshot({ path: path.join(shotDir, `shot_${name}_${w}x${h}.png`) });
  }
  await page.close();
}
await browser.close();
