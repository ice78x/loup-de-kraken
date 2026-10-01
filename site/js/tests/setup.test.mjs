// Logique des cartes « setup » : feu (où en est le prix), scénario dessiné, gains en €.
import test from "node:test";
import assert from "node:assert/strict";
import { gains, minutesToClose, phase, projection } from "../setup.js";

const NOW = Date.UTC(2026, 9, 1, 12, 7);
const futur = new Date(NOW + 3600e3).toISOString();
const short = { direction: "SHORT", status: "WATCH", entry_low: 100, entry_high: 101, sl: 103, tp1: 98, tp2: 96, tp3: 94,
  quote: "USD", expires_at: futur, trigger_text: "retour dans la zone 100-101", rr: [1, 2, 3] };
const long = { ...short, direction: "LONG", status: "TRADE", entry_low: 100, entry_high: 101, sl: 98, tp1: 103, tp2: 105, tp3: 107 };
const k = (c) => [0, c, c, c, c];

test("SHORT à surveiller : attendre que le prix remonte", () => {
  const p = phase(short, 99, { now: NOW });
  assert.equal(p.code, "attendre");
  assert.match(p.texte, /remonter/);
});
test("dans la zone : confirmé seulement si la dernière bougie FERMÉE a clôturé dans la zone", () => {
  assert.equal(phase(short, 100.5, { now: NOW, candles: [k(99), k(100.5)] }).code, "zone");
  assert.equal(phase(short, 100.5, { now: NOW, candles: [k(100.4), k(100.5)] }).code, "condition");
});
test("stop touché avant l'entrée = annulé ; objectif 1 déjà atteint = trop tard", () => {
  assert.equal(phase(short, 103.2, { now: NOW }).code, "stop");
  assert.equal(phase(short, 97.5, { now: NOW }).code, "parti");
  assert.equal(phase(long, 97.9, { now: NOW }).code, "stop");
  assert.equal(phase(long, 103.5, { now: NOW }).code, "parti");
});
test("LONG validé dans la zone = feu vert ; au-dessus = attendre le retour ; entre zone et stop = prudence", () => {
  assert.equal(phase(long, 100.5, { now: NOW }).code, "go");
  assert.equal(phase(long, 102, { now: NOW }).code, "attendre");
  assert.equal(phase(long, 99, { now: NOW }).code, "prudence");
});
test("pas de prix = on ne dit rien ; signal expiré = n'entre pas", () => {
  assert.equal(phase(short, null, { now: NOW }).code, "nodata");
  assert.equal(phase({ ...short, expires_at: new Date(NOW - 1).toISOString() }, 100.5, { now: NOW }).code, "expire");
});
test("minutes avant clôture de la bougie 15 min", () => {
  assert.equal(minutesToClose(NOW), 8); // 12:07 → clôture 12:15
});
test("scénario : part du prix actuel, passe par la zone puis les objectifs ; une bougie de 15 min par point", () => {
  const candles = [[1000, 99, 99, 99, 99], [1900, 99, 99, 99, 99]];
  const p = projection(short, candles, 99);
  assert.equal(p.ok[0].time, 1900);
  assert.equal(p.ok[0].value, 99);
  const times = p.ok.map((x) => x.time);
  assert.ok(times.every((t, i) => i === 0 || t - times[i - 1] === 900));
  assert.equal(p.ok.at(-1).value, 94);                 // TP3
  assert.ok(p.ok.some((x) => x.value === 98));          // passe par TP1
  assert.equal(p.rate.at(-1).value, 103);               // le chemin « si ça rate » finit au stop
  assert.deepEqual(projection(short, []), { ok: [], rate: [] });
});
test("gains en € : risque du membre, TP 30/40/30, R nets si disponibles", () => {
  const g = gains({ rr: [1, 2, 3] }, { balance_eur: 90, risk_pct: 1 });
  assert.equal(g.risk, 0.9);
  assert.ok(Math.abs(g.tp1 - 0.27) < 1e-9);
  assert.ok(Math.abs(g.all - 0.9 * (0.3 + 0.8 + 0.9)) < 1e-9);
  assert.equal(g.net, false);
  assert.equal(gains({ rr: [1, 2, 3], rr_net: [0.8, 1.7, 2.6] }, { balance_eur: 90, risk_pct: 1 }).net, true);
  assert.equal(gains({}, { balance_eur: 90, risk_pct: 1 }).all, null);
});
