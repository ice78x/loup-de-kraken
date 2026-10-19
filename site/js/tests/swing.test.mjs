// Swing (19/10) : état d'une position du bot selon le prix en direct, sans rien inventer.
import test from "node:test";
import assert from "node:assert/strict";
import { entreeOuverte, etatSwing, rAuStop, rDe, swingBacktestBlock, swingCard } from "../swing.js";

const NOW = Date.UTC(2026, 9, 19, 9, 0);
const base = { id: 7, display: "PF_XBTUSD", quote: "USD", direction: "LONG", status: "ouvert", signal_date: "2026-10-18",
  signal_close: 100, entry_low: 99, entry_high: 101, stop_initial: 90, stop_current: 90, history: [] };

test("nouvelle position : entrer dans la zone, jamais courir après", () => {
  assert.equal(etatSwing(base, 100, NOW).code, "entrer");
  const loin = etatSwing(base, 104, NOW);
  assert.equal(loin.code, "loin");
  assert.match(loin.texte, /pas plus haut que/);
  assert.equal(etatSwing(base, 95, NOW).code, "proche");
  assert.equal(etatSwing(base, 89, NOW).code, "stop");
});

test("après 2 jours, on ne prend plus le train en marche ; résultat en R et au stop", () => {
  const p = { ...base, signal_date: "2026-10-10", entry_price: 100, stop_current: 105 };
  assert.equal(entreeOuverte(p, NOW), false);
  const e = etatSwing(p, 120, NOW);
  assert.equal(e.code, "encours");
  assert.equal(rDe(p, 120), 2);
  assert.equal(rAuStop(p), 0.5);
  assert.doesNotMatch(e.texte, /garanti/i);                                     // jamais « gain garanti »
});

test("terminée, refusée, prix absent", () => {
  assert.equal(etatSwing({ ...base, status: "clos", r: 3.2, exit_price: 132, days: 20 }, null, NOW).titre, "Terminé : +3,2 R");
  assert.equal(etatSwing({ ...base, status: "refuse", refus: "2 % déjà engagé" }, 100, NOW).code, "refuse");
  assert.equal(etatSwing(base, null, NOW).code, "nodata");
  assert.match(swingCard(base, 100, NOW), /#\/swing\/7/);
});

test("bloc backtest : rien sans rapport, sinon la preuve par classe et par année", () => {
  assert.match(swingBacktestBlock(null), /Pas encore de backtest swing/);
  const run = { report: { type: "swing", periode: "2022 → 2026", instruments: { a: 1 }, par_classe: { crypto: { prouve: true,
    variante_retenue: "canal_55_20|trail|long", stats_variante: { n: 420, expectancy_r: 0.8, jours_moyens: 20.7 },
    walk_forward: { oos: { n: 439, expectancy_r: 0.85 } }, par_annee: { 2025: { expectancy_r: 0.66 }, 2026: { expectancy_r: -0.04 } } } } } };
  const h = swingBacktestBlock(run);
  assert.match(h, /Cryptos 🟢 prouvé/);
  assert.match(h, /LONG seulement/);
  assert.match(h, /2026 : -0,04 R/);
});
