"""Deliberate-bug check: break the code on purpose and make sure the tests notice.

    python tools/mutation_check.py

Each mutation edits one source file, runs the test suite, then restores the file.
A mutation that the tests do NOT catch is reported as SURVIVED (and the script exits 1).
"""

import atexit
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "dominion"

MUTATIONS = [
    ("Bridge can make costs negative", "engine/costs.py", "return max(0, get_card(name).cost - state.cost_reduction)", "return get_card(name).cost - state.cost_reduction"),
    ("Bridge reduction ignored when buying", "engine/game.py", "s.coins -= card_cost(s, card)", "s.coins -= get_card(card).cost"),
    ("Bridge reduction ignored by legal buys", "engine/rules.py", "card_cost(state, name) <= state.coins and not is_walled(state, name, actor)", "get_card(name).cost <= state.coins and not is_walled(state, name, actor)"),
    ("Bridge reduction survives the turn", "engine/game.py", "        s.cost_reduction = 0\n", "        pass\n"),
    ("Grand Swap moves Curses", "engine/zones.py", "return definition.is_type(CardType.VICTORY) or definition.is_type(CardType.CURSE)", "return definition.is_type(CardType.VICTORY)"),
    ("Grand Swap moves Victory cards", "engine/zones.py", "return definition.is_type(CardType.VICTORY) or definition.is_type(CardType.CURSE)", "return definition.is_type(CardType.CURSE)"),
    ("The Snap trashes too many", "engine/effects.py", "total // 2)\n            self._state.trash.extend(removed)", "(total + 1) // 2)\n            self._state.trash.extend(removed)"),
    ("The Snap spares the player", "cards/catastrophe.py", "ctx.snap([ctx.player, *[p for p in ctx.other_players() if p in affected]])", "ctx.snap([p for p in ctx.other_players() if p in affected])"),
    ("The Purge also hits the hand", "engine/effects.py", 'removed = zones.remove_random_cards(self._state, i, ("deck",), total // 2)', 'removed = zones.remove_random_cards(self._state, i, ("deck", "hand"), total // 2)'),
    ("The Purge ignores Moat", "cards/catastrophe.py", "ctx.purge([ctx.player, *[p for p in ctx.other_players() if p in affected]])", "ctx.purge([ctx.player, *ctx.other_players()])"),
    ("Diplomat offered with 4 cards", "cards/intrigue.py", "on_attack_min_hand=5)", "on_attack_min_hand=4)"),
    ("Conspirator needs only 2 Actions", "cards/intrigue.py", "if ctx.plays_this_turn >= 3:", "if ctx.plays_this_turn >= 2:"),
    ("Throne Room plays are not counted", "engine/effects.py", "        self._state.plays_this_turn += 1\n        result = get_card(card).on_play", "        result = get_card(card).on_play"),
    ("Masquerade passes the wrong way", "engine/effects.py", "receivers[p] = nxt[0] if nxt else None", "receivers[p] = nxt[-1] if nxt else None"),
    ("Swindler gains any cost up to", "cards/intrigue.py", "options = ctx.gainable(cost, exact=True, gainer=p)", "options = ctx.gainable(cost, gainer=p)"),
    ("Upgrade gains up to, not exactly", "cards/intrigue.py", "options = ctx.gainable(target, exact=True)", "options = ctx.gainable(target)"),
    ("Courtier uncapped choices", "cards/intrigue.py", "n = min(len(ctx.card_types(card)), len(_COURTIER_OPTIONS))", "n = len(ctx.card_types(card))"),
    ("Duke scores nothing", "cards/intrigue.py", 'score_fn=lambda cards: list(cards).count("Duchy")', "score_fn=lambda cards: 0"),
    ("Lurker may touch Catastrophes", "cards/intrigue.py", "and not get_card(c).is_type(CardType.CATASTROPHE)", ""),
    ("Gains from the trash are not tracked", "engine/zones.py", "    getattr(player, destination).append(card)\n    player.gained.append(card)\n    return True\n\n\ndef trash_from_supply", "    getattr(player, destination).append(card)\n    return True\n\n\ndef trash_from_supply"),
    ("Buys are not tracked", "engine/game.py", "        s.players[player].bought.append(card)\n", ""),
    ("VP breakdown drops variable cards", "engine/scoring.py", "if total != 0:", "if total != 0 and get_card(name).vp != 0:"),
    ("Log lines lose their turn number", "engine/state.py", "super().append(LogLine(text, self.turn_of(), kind or classify(text), indent))", "super().append(LogLine(text, 0, kind or classify(text), indent))"),
    ("Turn headers are not logged", "engine/game.py", '            s.log.append(f"Turn {s.turn_number} - {nxt.name}", "turn")\n', ""),
    ("Cataclysm does not say who got what", "engine/effects.py", "        self.log_card_changes(before)\n\n    def grand_swap_with", "        pass\n\n    def grand_swap_with"),
    ("Torturer ignores empty Curse pile", "cards/intrigue.py", "can_curse = ctx.supply_count(\"Curse\") > 0", "can_curse = True"),
    ("Bot cannot handle text options", "ai/bots.py", "    except UnknownCardError:        # a text option such as \"+1 Card\" or \"Yes\": no preference\n        return 0", "    except UnknownCardError:\n        raise"),
    ("Page: auto-play ignores the undo guard", "web/static/index.html", "lastAutoVersion = v.version; lastTreasureVersion = v.version; lastEndVersion = v.version; }", "lastAutoVersion = v.version; lastEndVersion = v.version; }"),
    ("Page: no auto-play of Treasures", "web/static/index.html", "settings.autoTreasures && free && v.phase", "false && free && v.phase"),
    ("Page: Leave button hidden in game", "web/static/index.html", '$("btn-leave").hidden = id === "home";', '$("btn-leave").hidden = id !== "lobby";'),
    ("Page: text options drawn as cards", "web/static/index.html", "const isCard = !!cardInfo(name);", "const isCard = true;"),
    ("Page: log lines lose the turn prefix", "web/static/index.html", 'row.appendChild(el("span", "tn", "T" + e.turn));', ""),
    ("Page: stats never rendered", "web/static/index.html", "(v.stats || []).forEach((s, i) => {", "([]).forEach((s, i) => {"),
    ("Page: trash count never updates", "web/static/index.html", '$("btn-trash").textContent = "Trash (" + v.trash.length + ")";', ""),
    ("Page: reduced price not shown", "web/static/index.html", "return Math.max(0, info.cost - cut);", "return info.cost;"),
    ("Protected players are not skipped by Attacks", "engine/effects.py", "            if self.is_protected(p):\n                self.log(f\"{self.name_of(p)} is protected and unaffected.\", \"reveal\")\n                continue\n", ""),
    ("Protection counts the turn it was gained", "engine/game.py", "        if me.protection_fresh:                 # the turn protection was gained does not count\n            me.protection_fresh = False\n        elif me.protection > 0:", "        if me.protection > 0:"),
    ("God Mode is not permanent", "engine/effects.py", "        self._me().protected_forever = True\n", "        pass\n"),
    ("Guardian Angel lasts 4 turns", "cards/special.py", "    ctx.protect(5)", "    ctx.protect(4)"),
    ("Rosebud gift is never paid out", "engine/game.py", "            if nxt.bonus_coins:\n                s.coins += nxt.bonus_coins", "            if False:\n                s.coins += nxt.bonus_coins"),
    ("Rosebud always pays the player", "engine/effects.py", "        if player == self._state.current_player:\n            self.add_coins(amount)", "        if True:\n            self.add_coins(amount)"),
    ("A resigned player can win", "engine/scoring.py", "eligible = [i for i in range(len(scores)) if i not in state.resigned] or list(range(len(scores)))", "eligible = list(range(len(scores)))"),
    ("A pending question survives the end of the game", "engine/game.py", "        s.pending = None                 # an unanswered question dies with the game\n", ""),
    ("Cheats work when switched off", "engine/rules.py", "        if not state.cheats:\n            return \"Cheat codes are not turned on in this game.\"\n", ""),
    ("Cheats work on someone else's turn", "engine/rules.py", "        if player != turn_controller(state):\n            return \"Cheat codes only work on your own turn.\"\n        return None\n\n    # A paused", "        return None\n\n    # A paused"),
    ("Cheat phrases are shown as chat", "web/rooms.py", "if kind is not None and room.game is not None and room.game.state.status is GameStatus.ACTIVE:", "if False:"),
    ("My games leaks games without a token", "web/rooms.py", "if room is None or seat is None:\n                gone.append(code)", "if room is None:\n                gone.append(code)"),
    ("Anyone may end the game", "web/rooms.py", "            if action is EndGame and room.seats.index(seat) != room.host_index():\n                raise UserError(\"Only the host can do that.\")\n", ""),
    ("Anyone may delete the game", "web/rooms.py", "        if room.seats.index(seat) != room.host_index():\n            raise UserError(\"Only the host can delete a game.\")\n", ""),
    ("Resigning leaves the undo vote open", "web/rooms.py", "            if room.undo is not None:\n                await self._end_undo(room, \"The undo request was cancelled because the game ended.\")\n", ""),
    ("Page: auto-end ignores the undo guard", "web/static/index.html", "lastTreasureVersion = v.version; lastEndVersion = v.version; }", "lastTreasureVersion = v.version; }"),
    ("Page: auto-end fires on a stale position", "web/static/index.html", "if (view && view.version === at && settings.autoEnd) act", "if (settings.autoEnd) act"),
    ("Page: auto-end with Buys left", "web/static/index.html", 'settings.autoEnd && free && v.phase === "buy" && v.buys === 0', 'settings.autoEnd && free && v.phase === "buy"'),
    ("Page: Resign without asking", "web/static/index.html", 'if (window.confirm("Resign? The game ends for everybody and you cannot win.")) { send({ type: "resign" }); closeModal(); }', 'send({ type: "resign" }); closeModal();'),
    ("Page: games are not remembered", "web/static/index.html", "      rememberGame(m.room, m.token, store.getItem(\"dom_name\") || \"Player\");\n", ""),
    ("Page: protection not shown", "web/static/index.html", 'else if (p.protection > 0) tags.appendChild(el("span", "tag gold", "protected: "', 'else if (false) tags.appendChild(el("span", "tag gold", "protected: "'),
    ("Page: cheat box not sent", "web/static/index.html", '$("cheats-box").addEventListener("change", (e) => send({ type: "set_cheats", cheats: e.target.checked }));', ''),
    ("Page: Catastrophe cards unreadable", "web/static/index.html", "  .card.t-catastrophe { color: #f6e9ea; border-color: var(--bad); }", "  .card.catastrophe { color: #f6e9ea; border-color: var(--bad); }"),
    ("U9: Exodia needs only four pieces", "engine/game.py", "if all(piece in p.hand for piece in EXODIA_PIECES):", "if sum(piece in p.hand for piece in EXODIA_PIECES) >= 4:"),
    ("U9: Exodia counts pieces anywhere in the deck", "engine/game.py", "if all(piece in p.hand for piece in EXODIA_PIECES):", "if all(piece in p.all_cards() for piece in EXODIA_PIECES):"),
    ("U9: Exodia limbs do not come with the head", "engine/setup.py", "out.extend(c for c in get_card(name).companions if c not in out)", "pass"),
    ("U9: a limb can be picked alone", "engine/setup.py", "        if card.companion_of is not None:\n            raise ValueError(f\"{name} comes with {card.companion_of} and cannot be picked on its own.\")\n", ""),
    ("U9: Cataclysm takes the cloaked player's cards", "engine/zones.py", "i for i, p in enumerate(state.players) if not p.invisible or i == no_new_hand_for", "i for i, p in enumerate(state.players)"),
    ("U9: Masquerade passes to a cloaked player", "engine/effects.py", "if not players[(p + k) % n].invisible]", "]"),
    ("U9: the cloak does not stop Attacks", "engine/effects.py", "return p.protected_forever or p.protection > 0 or p.invisible", "return p.protected_forever or p.protection > 0"),
    ("U9: Midas Touch changes nothing", "engine/game.py", "if s.midas and value < 3:", "if s.midas and value > 3:"),
    ("U9: Midas Touch lasts forever", "engine/game.py", "        s.midas = False\n", "        pass\n"),
    ("U9: walls do not stop buying", "engine/rules.py", "        if is_walled(state, action.card, player):\n", "        if False:\n"),
    ("U9: walls do not stop gaining", "engine/zones.py", "or is_walled(state, card, player_index):", ":"),
    ("U9: walls never come down", "engine/game.py", "            for pile in [p for p, owner in s.walls.items() if owner == s.current_player]:", "            for pile in []:"),
    ("U9: walls block their own builder", "engine/costs.py", "return owner is not None and owner != player and not state.players[player].invisible", "return owner is not None and not state.players[player].invisible"),
    ("U9: Swindler ignores the victim's walls", "cards/intrigue.py", "options = ctx.gainable(cost, exact=True, gainer=p)", "options = ctx.gainable(cost, exact=True)"),
    ("U9: Monopoly takes Silver before Gold", "engine/effects.py", 'for card in ("Gold", "Silver"):', 'for card in ("Silver", "Gold"):'),
    ("U9: Grand Theft Auto robs everybody", "cards/catastrophe.py", "affected = yield from ctx.attack(only=targets)", "affected = yield from ctx.attack()"),
    ("U9: Grand Theft Auto destroys the card", "engine/zones.py", "    state.players[thief].discard.append(card)\n    state.players[thief].gained.append(card)\n    return card", "    return card"),
    ("U9: Roofie never wears off", "engine/game.py", "            me.blind -= 1\n", "            pass\n"),
    ("U9: Chance Time coin shower pays $5", "cards/special.py", "ctx.add_coins(8)", "ctx.add_coins(5)"),
    ("U9: Chance Time swaps with protected players", "cards/special.py", "eligible = [p for p in ctx.other_players() if not ctx.is_protected(p)]", "eligible = ctx.other_players()"),
    ("U9: Page: blind mode never hides names", "web/static/index.html", "    const blind = isBlind();\n    const info", "    const blind = false;\n    const info"),
    ("U9: Page: blinded hand stays stacked and sorted", "web/static/index.html", 'seededShuffle(v.hand.map((n, i) => [n, i]), v.version).forEach(([n, i]) => counts.set(n + "\\u0000" + i, 1));', 'v.hand.forEach((n) => counts.set(n, (counts.get(n) || 0) + 1));'),
    ("U9: Page: wall marker missing", "web/static/index.html", "      if (walled) { c.classList.add(\"walled\");", "      if (false) { c.classList.add(\"walled\");"),
    ("U9: Page: game over hides the Exodia banner", "web/static/index.html", "if (!special && !cat) banner(won", "if (true) banner(won"),
    ("U10: Catastrophes can be blocked by Moat", "engine/effects.py", "reactable = not get_card(self.source).is_type(CardType.CATASTROPHE)", "reactable = True"),
    ("U10: at most 2 house-rule cards (engine)", "engine/setup.py", "    if len(set(picked)) != len(picked):\n        raise ValueError(\"Catastrophe and Special cards must be unique.\")", "    if len(picked) > 2 or len(set(picked)) != len(picked):\n        raise ValueError(\"Catastrophe and Special cards must be unique.\")"),
    ("U10: at most 2 house-rule cards (lobby)", "web/rooms.py", "                    or not set(chosen) <= set(fenced_cards())", "                    or len(chosen) > 2 or not set(chosen) <= set(fenced_cards())"),
    ("U10: undo only from the current turn", "web/rooms.py", "        if game.history[i][0] == seat_index:\n            return i\n    return None", "        if game.history[i][0] == seat_index:\n            return i if game.history_turns[i] == game.state.turn_number else None\n    return None"),
    ("U10: the view leaks discard pile sizes", "engine/views.py", "            \"discard_top\": p.discard[-1] if p.discard else None,", "            \"discard_top\": p.discard[-1] if p.discard else None,\n            \"discard_count\": len(p.discard),"),
    ("U10: the view leaks your discard pile", "engine/views.py", "        \"cost_reduction\": s.cost_reduction,", "        \"cost_reduction\": s.cost_reduction,\n        \"my_discard\": sorted(me.discard),"),
    ("U10: Page: players panel shows a discard count", "web/static/index.html", "\"Hand \" + p.hand_count + \" | Deck \" + p.deck_count));", "\"Hand \" + p.hand_count + \" | Deck \" + p.deck_count + \" | Discard 0\"));"),
    ("U10: Page: Exodia label has a suffix again", "web/static/index.html", "      }, (c.min_players > 1 ? \", \" + c.min_players + \"+ players\" : \"\")));", "      }, (c.min_players > 1 ? \", \" + c.min_players + \"+ players\" : \"\") + (c.companions && c.companions.length ? \", brings 4 more pieces\" : \"\")));"),
    ("U10: Page: questions never open the pop-up layer", "web/static/index.html", "$(\"popup-layer\").classList.toggle(\"open\", showing);", "$(\"popup-layer\").classList.toggle(\"open\", false);"),
    ("U10: Page: a hidden question stays hidden", "web/static/index.html", "if (key !== selectionKey) { selection = []; selectionKey = key; decisionPeek = false; }", "if (key !== selectionKey) { selection = []; selectionKey = key; }"),
    ("U10: Page: Close does not close the results", "web/static/index.html", "{ resultsClosed = true; if (view) renderGame(); });", "{ resultsClosed = false; if (view) renderGame(); });"),
    ("U10: Page: the page scrolls", "web/static/index.html", "html, body { margin: 0; height: 100%; overflow: hidden; }", "html, body { margin: 0; height: 100%; overflow: auto; }"),
    ("U10: Page: pop-ups off-centre", "web/static/index.html", "justify-content: center; gap: 12px; padding: 16px;", "justify-content: flex-start; gap: 12px; padding: 16px;"),
    ("U10: Page: still called Dominion", "web/static/index.html", "document.title = mineNow ? \"* Your turn - Modinion\" : \"Modinion\";", "document.title = mineNow ? \"* Your turn - Dominion\" : \"Dominion\";"),
    ("U10: Page: no room for the turn bar", "web/static/index.html", "  #bottom-row { flex: 0 0 auto; display: flex; gap: 10px; max-height: 44vh; min-height: 0; }", "  #bottom-row { flex: 0 0 auto; display: flex; gap: 10px; min-height: 0; }"),
    ("U10: Page: the supply panel stops scrolling", "web/static/index.html", "  #supply-panel { flex: 1 1 auto; min-height: 0; overflow: auto; }", "  #supply-panel { flex: 1 1 auto; min-height: 0; }"),
]



def run_tests(page_only: bool) -> bool:
    """Page mutations only need the browser tests; engine mutations skip them (much faster)."""
    args = ["tests/test_update8.py", "tests/test_browser.py"] if page_only else ["--deselect", "tests/test_browser.py"]
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", *args],
        cwd=ROOT, capture_output=True, text=True, timeout=900,
    )
    return result.returncode == 0


_ORIGINALS = {}


def _restore_all(*_args) -> None:
    for path, text in _ORIGINALS.items():
        path.write_text(text, encoding="utf-8")
    if _args:
        raise SystemExit(130)


def main() -> int:
    atexit.register(_restore_all)
    signal.signal(signal.SIGTERM, _restore_all)
    signal.signal(signal.SIGINT, _restore_all)
    only = sys.argv[1:]            # optional: words that must appear in a mutation's name
    todo = [m for m in MUTATIONS if not only or any(w.lower() in m[0].lower() for w in only)]
    survived = []
    for label, rel, old, new in todo:
        path = SRC / rel
        original = path.read_text(encoding="utf-8")
        _ORIGINALS[path] = original
        if original.count(old) != 1:
            print(f"BROKEN MUTATION (pattern found {original.count(old)}x): {label}")
            survived.append(label)
            continue
        path.write_text(original.replace(old, new), encoding="utf-8")
        try:
            passed = run_tests(rel.endswith(".html"))
        finally:
            path.write_text(original, encoding="utf-8")
        print(("SURVIVED  " if passed else "caught    ") + label, flush=True)
        if passed:
            survived.append(label)
    print(f"\n{len(todo) - len(survived)} of {len(todo)} deliberate bugs were caught.")
    return 1 if survived else 0


if __name__ == "__main__":
    raise SystemExit(main())
