import { test } from "node:test";
import assert from "node:assert/strict";
import { depuisDernierPassage, texteDepuis } from "../suivi.js";

// Le trade TAO de la capture : LONG 294,35, SL 290,39, TP 298,38 / 301,57 / 303,88, dernier passage du bot à 23:05
const t = { status: "ouvert", direction: "LONG", entry_price: 294.35, sl: 290.39, tp1: 298.38, tp2: 301.57, tp3: 303.88,
  opened_at: "2026-10-03T19:31:00Z", last_checked: "2026-10-03T21:05:00Z", tp1_hit: false, tp2_hit: false, tp3_hit: false };
const T = (h, m) => Date.parse(`2026-10-03T${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:00Z`) / 1000;

test("TP touchés la nuit, après le dernier passage du bot", () => {
  const c = [[T(20, 45), 294, 296, 293, 295, 1], [T(22, 0), 295, 299, 294, 298.9, 1], [T(23, 0), 299, 302, 298, 301.9, 1], [T(23, 45), 302, 307, 301, 306.5, 1]];
  const d = depuisDernierPassage(t, c);
  assert.deepEqual(d.tps, [1, 2, 3]);
  assert.equal(d.sl, false);
  assert.match(texteDepuis(d, "08:05"), /TP1, TP2 et TP3 touchés/);
});

test("stop avant les objectifs dans la même bougie (prudence), et rien avant le dernier passage", () => {
  assert.equal(depuisDernierPassage(t, [[T(20, 30), 294, 310, 280, 300, 1]]), null);  // bougie déjà vue par le bot
  const d = depuisDernierPassage(t, [[T(22, 0), 294, 305, 289, 300, 1]]);
  assert.equal(d.sl, true);
  assert.deepEqual(d.tps, []);
});
