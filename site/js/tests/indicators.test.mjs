// Indicateurs du graphique : vérifiés sur des séries connues.
import test from "node:test";
import assert from "node:assert/strict";
import { atr, ema, lecture, niveaux, pivots, rsi, structure, vwap } from "../indicators.js";

const k = (t, o, h, l, c, v = 1) => [t * 900, o, h, l, c, v];
const serie = (closes) => closes.map((c, i) => k(i, c, c + 0.5, c - 0.5, c, 10));

test("EMA : première valeur = moyenne simple, puis lissage 2/(n+1)", () => {
  const e = ema([1, 2, 3, 4, 5], 3);
  assert.deepEqual(e.slice(0, 2), [null, null]);
  assert.equal(e[2], 2);
  assert.equal(e[3], 4 * 0.5 + 2 * 0.5);
  assert.equal(e[4], 5 * 0.5 + 3 * 0.5);
});

test("RSI : 100 si ça ne fait que monter, 0 si ça ne fait que baisser, ~50 en zigzag régulier", () => {
  const up = serie(Array.from({ length: 30 }, (_, i) => 100 + i));
  const down = serie(Array.from({ length: 30 }, (_, i) => 100 - i));
  const zig = serie(Array.from({ length: 40 }, (_, i) => 100 + (i % 2)));
  assert.equal(rsi(up).at(-1), 100);
  assert.equal(rsi(down).at(-1), 0);
  assert.ok(Math.abs(rsi(zig).at(-1) - 50) < 5);
  assert.equal(rsi(up)[13], null);
});

test("ATR : bougies d'amplitude constante = cette amplitude", () => {
  const a = atr(serie(Array.from({ length: 30 }, () => 100)));
  assert.ok(Math.abs(a.at(-1) - 1) < 1e-9);
});

test("VWAP : moyenne pondérée par le volume, remise à zéro chaque jour", () => {
  const d = [[0, 10, 10, 10, 10, 1], [900, 20, 20, 20, 20, 3], [86400, 50, 50, 50, 50, 2]];
  const v = vwap(d);
  assert.equal(v[0], 10);
  assert.equal(v[1], (10 + 60) / 4);
  assert.equal(v[2], 50);
  assert.deepEqual(vwap([[0, 1, 1, 1, 1]]), [null]); // pas de volume : rien
});

test("pivots, structure HH/HL et tendance haussière", () => {
  // vagues montantes : creux 100, 102, 104 ; sommets 105, 107, 109
  const closes = [103, 102, 101, 100, 101, 102, 103, 104, 105, 104, 103, 102, 103, 104, 105, 106, 107, 106, 105, 104,
    105, 106, 107, 108, 109, 108, 107, 106, 107];
  const c = closes.map((x, i) => k(i, x, x + 0.2, x - 0.2, x));
  const pv = pivots(c, 3);
  assert.ok(pv.some((p) => p.type === "H") && pv.some((p) => p.type === "L"));
  const st = structure(c, 3);
  assert.equal(st.trend, "haussière");
  assert.ok(st.labels.some((l) => l.label === "HH") && st.labels.some((l) => l.label === "HL"));
});

test("supports / résistances : niveaux touchés plusieurs fois, de chaque côté du prix", () => {
  const closes = [];
  for (let r = 0; r < 4; r++) closes.push(100, 101, 102, 103, 104, 105, 104, 103, 102, 101);
  closes.push(100, 101, 102, 103);
  const c = closes.map((x, i) => k(i, x, x + 0.1, x - 0.1, x, 5));
  const nv = niveaux(c);
  assert.ok(nv.resistances[0] && Math.abs(nv.resistances[0].price - 105.1) < 0.5);
  assert.ok(nv.supports[0] && Math.abs(nv.supports[0].price - 99.9) < 0.5);
  assert.ok(nv.resistances[0].touches >= 3);
});

test("lecture rapide : null sans assez de bougies, sinon des valeurs calculées", () => {
  assert.equal(lecture(serie([1, 2, 3])), null);
  const l = lecture(serie(Array.from({ length: 80 }, (_, i) => 100 + i * 0.3)));
  assert.equal(l.tendanceEma, "haussière");
  assert.ok(l.rsi > 70);
  assert.ok(l.atrPct > 0);
});
