// Bloc « Backtest du moteur » : affiche le rapport tel quel, n'invente rien.
import { test } from "node:test";
import assert from "node:assert/strict";
import { backtestBlock, combo } from "../backtest.js";

test("sans backtest : on dit clairement qu'il n'y aura aucun 🟢", () => {
  const h = backtestBlock(null);
  assert.match(h, /Pas encore de backtest/);
  assert.match(h, /aucun 🟢/);
  assert.doesNotMatch(h, /data-backtest/);
  assert.match(backtestBlock(null, { admin: true }), /data-backtest/);
});

test("rapport : AVANT / APRÈS, combinaisons prouvées, rien d'autre", () => {
  const m = (n, w, e, pf) => ({ trades: n, win_rate_pct: w, expectancy_r: e, profit_factor: pf, max_drawdown_pct: 12.5, pire_serie_pertes: 6 });
  const run = { created_at: new Date().toISOString(), report: { jours: 120, instruments: { PF_XBTUSD: 1, PF_ETHUSD: 1 }, periode_hors_echantillon: "2026-07-01 → 2026-10-04",
    avant: m(210, 41.2, -0.18, 0.78), apres: m(23, 52.1, 0.31, 1.6),
    edges: { "tendance_pullback|TREND": { n: 44, expectancy_r: 0.27, win_rate_pct: 50, profit_factor: 1.5, prouve: true, oos_n: 9, oos_expectancy_r: 0.2 },
      "rejet_sweep|RANGE": { n: 61, expectancy_r: -0.2, win_rate_pct: 38, profit_factor: 0.7, prouve: false } } } };
  const h = backtestBlock(run);
  assert.match(h, /AVANT \(ancien moteur\)/);
  assert.match(h, /210/);
  assert.match(h, /APRÈS \(moteur v2\)/);
  assert.match(h, /Repli dans la tendance · Tendance<\/b> : 44 trades/);
  assert.match(h, /🚫 non/);
  assert.equal(combo("cassure_retest|BREAKOUT"), "Cassure + retest · Cassure");
});

test("rapport sans aucune combinaison prouvée → message NO TRADE", () => {
  const run = { created_at: new Date().toISOString(), report: { jours: 60, instruments: {}, periode_hors_echantillon: "x", avant: { trades: 0 }, apres: { trades: 0 }, edges: {} } };
  assert.match(backtestBlock(run), /Aucune combinaison prouvée/);
});

test("une combinaison qui perd hors échantillon (3 trades ou plus) n'est plus affichée comme prouvée", () => {
  const run = { created_at: new Date().toISOString(), report: { jours: 120, instruments: {}, periode_hors_echantillon: "x", avant: { trades: 0 }, apres: { trades: 0 },
    edges: { "cassure_retest|TREND": { n: 38, expectancy_r: 0.064, profit_factor: 1.1, prouve: true, oos_n: 4, oos_expectancy_r: -1.132 } } } };
  assert.match(backtestBlock(run), /Aucune combinaison prouvée/);
});

test("positive sur l'historique mais jamais confirmée hors échantillon → pas de 🟢 (règle du 06/10)", () => {
  const run = { created_at: new Date().toISOString(), report: { jours: 120, instruments: {}, periode_hors_echantillon: "x", avant: { trades: 0 }, apres: { trades: 0 },
    edges: { "rejet_sweep|TREND": { n: 43, expectancy_r: 0.069, profit_factor: 1.13, prouve: true, oos_n: 0, oos_expectancy_r: null },
      "rejet_sweep|RANGE": { n: 38, expectancy_r: 0.397, profit_factor: 1.7, prouve: true, oos_n: 13, oos_expectancy_r: 0.252 } } } };
  const h = backtestBlock(run);
  assert.match(h, /Rejet[^<]*· Range<\/b> : 38 trades/);
  assert.match(h, /confirmé sur 13 trades jamais vus/);
  assert.match(h, /⏳ pas encore confirmé/);
  assert.doesNotMatch(h, /<li><b>[^<]*Tendance<\/b>/);
});

test("07/10 : combinaisons par classe (matières premières, actions) lisibles", () => {
  assert.equal(combo("rejet_sweep|RANGE|commodity"), "Rejet / piège · Range · Matières premières");
  assert.equal(combo("tendance_pullback|TREND|xstock"), "Repli dans la tendance · Tendance · Actions");
  const run = { created_at: new Date().toISOString(), report: { jours: 120, instruments: { a: 1, b: 1, c: 1 }, classes: { crypto: 2, commodity: 1 },
    periode_hors_echantillon: "x", avant: { trades: 0 }, apres: { trades: 0 }, edges: {} } };
  assert.match(backtestBlock(run), /2 cryptos, 1 matières premières/);
});
