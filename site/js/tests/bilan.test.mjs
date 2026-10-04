// En-tête de l'accueil : bilan du COMPTE (pas des setups du bot).
import { test } from "node:test";
import assert from "node:assert/strict";
import { bilanCompte } from "../solde.js";

test("cash dispo, en cours, TP1/2/3, SL, stop remonté, liquidation", () => {
  const T = (o) => ({ status: "clos", direction: "LONG", entry_price: 100, sl: 98, qty: 1, qty_remaining: 0, leverage: 5, eur_per_quote: 1, ...o });
  const trades = [
    T({ status: "ouvert", qty_remaining: 1, tp1_hit: true }),                  // marge 100/5 = 20 €, TP1 touché, stop encore sous l'entrée
    T({ close_reason: "SL", realized_pnl_eur: -2 }),
    T({ close_reason: "SL ajusté", tp1_hit: true, realized_pnl_eur: 0.5 }),
    T({ close_reason: "TP3", tp1_hit: true, tp2_hit: true, tp3_hit: true, realized_pnl_eur: 4 }),
    T({ close_reason: "Liquidation", realized_pnl_eur: -20 }),
    T({ status: "annule", close_reason: "SL", realized_pnl_eur: -99 }),        // annulé : ignoré
  ];
  const b = bilanCompte({ balance_eur: 200 }, trades);
  assert.equal(b.cash, 180);
  assert.equal(b.enCours, 1);
  assert.ok(Math.abs(b.risque - 2) < 1e-9);
  assert.deepEqual([b.tp1, b.tp2, b.tp3, b.sl, b.slProtege, b.liquidation, b.clos, b.gagnants], [3, 1, 1, 1, 1, 1, 4, 2]);
  assert.ok(Math.abs(b.resultat - -17.5) < 1e-9);
});
