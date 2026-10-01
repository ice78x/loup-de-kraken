import test from "node:test";
import assert from "node:assert/strict";
import { enCours, solde } from "../solde.js";

const since = "2026-10-01T10:00:00Z";
const t = (o) => ({ status: "clos", opened_at: "2026-10-01T12:00:00Z", realized_pnl_eur: 0, ...o });

test("le solde monte et descend avec les trades depuis le dernier réglage", () => {
  const trades = [
    t({ realized_pnl_eur: 2.5 }),                                   // gagnant clos
    t({ realized_pnl_eur: -0.9 }),                                  // stop touché
    t({ status: "ouvert", realized_pnl_eur: -0.04 }),               // ouvert : frais d'entrée déjà payés
    t({ realized_pnl_eur: 50, opened_at: "2026-09-30T12:00:00Z" }), // avant le réglage : déjà dans le solde saisi
    t({ status: "annule", realized_pnl_eur: 9 }),                   // annulé : ne compte pas
  ];
  const s = solde({ balance_eur: 90 }, trades, since);
  assert.ok(Math.abs(s.realise - 1.56) < 1e-9);
  assert.ok(Math.abs(s.actuel - 91.56) < 1e-9);
  assert.equal(s.ouverts.length, 1);
  // recalcul sur un profil déjà mis à jour : on repart toujours du solde enregistré (pas de double comptage)
  assert.ok(Math.abs(solde({ balance_eur: 91.56, balance_base: 90 }, trades, since).actuel - 91.56) < 1e-9);
  assert.equal(solde({ balance_eur: 1 }, [t({ realized_pnl_eur: -5 })], since).actuel, 0);
});

test("en cours : mouvement du prix moins les frais de sortie ; null sans prix", () => {
  const o = { status: "ouvert", direction: "LONG", entry_price: 100, qty: 1, qty_remaining: 1, fee_pct: 0.05, eur_per_quote: 1, realized_pnl_eur: -0.05 };
  assert.ok(Math.abs(enCours([o], () => 102) - (2 - 0.051)) < 1e-9);
  assert.equal(enCours([o], () => null), null);
});
