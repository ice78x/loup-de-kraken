// Tests du calcul de position côté site : node --test site/js/tests/
import { test } from "node:test";
import assert from "node:assert/strict";
import { planTrade, riskBudget, closePart, openRiskEur, suggestLeverage } from "../sizing.js";

const near = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) <= eps, `${a} ≠ ${b}`);
const base = { balance: 90, riskPct: 1, entry: 100, sl: 98, tps: [103, 106, 110], direction: "LONG",
  leverage: 1, feeTaker: 0, feeMaker: 0, eurPerQuote: 1, lotDecimals: 8 };

test("exemple du cahier des charges : 90 €, 1 %, SL à 2 % → perte 0,90 €", () => {
  const p = planTrade(base);
  assert.equal(p.ok, true);
  near(p.riskEur, 0.9);
  near(p.qty, 0.45);
  near(p.lossAtSlEur, 0.9);
  near(p.notionalEur, 45);
});

test("le multiplicateur ne change jamais la perte au SL", () => {
  const a = planTrade({ ...base, sl: 99.8, leverage: 5 });
  const b = planTrade({ ...base, sl: 99.8, leverage: 10 });
  near(a.lossAtSlEur, 0.9);
  near(b.lossAtSlEur, a.lossAtSlEur);
  near(a.qty, b.qty);
  near(a.marginEur, 90);
  near(b.marginEur, 45);
});

test("marge insuffisante à x1 → erreur + suggestion", () => {
  const p = planTrade({ ...base, sl: 99.8, leverage: 1 });
  assert.equal(p.ok, false);
  assert.match(p.errors.join(), /x5/);
  assert.equal(suggestLeverage(p, 90, p.slPct), 5);
});

test("liquidation avant le SL → refus", () => {
  const p = planTrade({ ...base, sl: 90, tps: [110, 120, 130], leverage: 10 });
  assert.equal(p.ok, false);
  assert.match(p.errors.join(), /liquidation/);
});

test("frais inclus : la perte au SL ne dépasse jamais le risque", () => {
  const p = planTrade({ ...base, feeTaker: 0.4, feeMaker: 0.25, entryIsMaker: true });
  assert.ok(p.lossAtSlEur <= 0.9 + 1e-9);
  assert.ok(p.rrNet[1] < p.rr[1]);
});

test("niveaux incohérents refusés", () => {
  assert.equal(planTrade({ ...base, sl: 101 }).ok, false);
  assert.equal(planTrade({ ...base, direction: "SHORT", sl: 98 }).ok, false);
  assert.equal(planTrade({ ...base, tps: [106, 103] }).ok, false);
});

test("SHORT et conversion USD", () => {
  const p = planTrade({ ...base, direction: "SHORT", entry: 14.25, sl: 14.7, tps: [13.9, 13.4, 12.8], eurPerQuote: 0.9 });
  assert.equal(p.ok, true);
  near(p.lossAtSlEur, 0.9, 1e-4);
});

test("budget de risque : plafond ouvert et stop journalier", () => {
  const prof = { balance_eur: 90, max_open_risk_pct: 2, max_daily_loss_pct: 3 };
  const open = { status: "ouvert", direction: "SHORT", entry_price: 14.25, sl: 14.7, qty_remaining: 2, eur_per_quote: 1 };
  near(openRiskEur(open), 0.9);
  const b = riskBudget(prof, [open]);
  near(b.available, 0.9);
  const lost = { status: "clos", closed_at: new Date().toISOString(), realized_pnl_eur: -2.7 };
  assert.equal(riskBudget(prof, [lost]).dailyStop, true);
});

test("clôture partielle puis totale", () => {
  const t = { direction: "LONG", entry_price: 100, qty: 1, qty_remaining: 1, fee_pct: 0, eur_per_quote: 1,
    realized_pnl_eur: 0, risk_eur: 2 };
  const a = closePart(t, 102, 0.3);
  near(a.pnl, 0.6);
  assert.equal(a.update.status, undefined);
  const b = closePart({ ...t, ...a.update }, 104, 1);
  assert.equal(b.update.status, "clos");
  near(b.update.realized_pnl_eur, 0.6 + 0.7 * 4);
  near(b.update.r_multiple, (0.6 + 2.8) / 2, 1e-3);
});
