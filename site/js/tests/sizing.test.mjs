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

test("détail d'un trade ouvert : frais d'entrée, mouvement, frais de sortie, résultat si on ferme", async () => {
  const { pnlBreakdown } = await import("../sizing.js");
  // SHORT ouvert : 0,4 % de frais, prix qui baisse un peu
  const t = { status: "ouvert", direction: "SHORT", entry_price: 100, qty: 9, qty_remaining: 9, fee_pct: 0.4,
    eur_per_quote: 1, realized_pnl_eur: -(0.004 * 100 * 9) };
  const b = pnlBreakdown(t, 99.6);
  assert.ok(Math.abs(b.entryFee - 3.6) < 1e-9);
  assert.ok(Math.abs(b.move - 3.6) < 1e-9);          // (100 − 99,6) × 9
  assert.ok(Math.abs(b.exitFee - 0.004 * 99.6 * 9) < 1e-9);
  assert.ok(Math.abs(b.banked) < 1e-9);               // aucun TP encore
  assert.ok(Math.abs(b.ifCloseNow - (-3.6 + 3.6 - 0.004 * 99.6 * 9)) < 1e-9);
  assert.equal(pnlBreakdown(t, null).ifCloseNow, null); // pas de prix = pas de chiffre inventé
});

test("mode Kraken : quantité + levier → perte au SL, marge, liquidation, règle des 2 %", async () => {
  const { planFromQty, qtyForRisk } = await import("../sizing.js");
  const base = { direction: "LONG", entry: 100, sl: 98, tps: [104, 106, 110], balance: 90, riskPct: 1, maxRiskPct: 2,
    feeTaker: 0, feeMaker: 0, eurPerQuote: 1, lotDecimals: 4, venue: "spot" };
  const p = planFromQty({ ...base, qty: 0.45, leverage: 1 });
  assert.equal(p.ok, true);
  assert.ok(Math.abs(p.lossAtSlEur - 0.9) < 1e-9);            // 0,45 × 2 $
  assert.ok(Math.abs(p.marginEur - 45) < 1e-9);
  assert.equal(p.liqPrice, null);                             // x1 : pas de liquidation
  // Le levier ne change PAS la perte au SL, seulement la marge
  const p5 = planFromQty({ ...base, qty: 0.45, leverage: 5 });
  assert.ok(Math.abs(p5.lossAtSlEur - p.lossAtSlEur) < 1e-12);
  assert.ok(Math.abs(p5.marginEur - 9) < 1e-9);
  assert.ok(p5.liqPrice > 80 && p5.liqPrice < 100);           // x5 : liquidation ≈ 84 (sous l'entrée)
  // Trop gros : > 2 % du solde → bloqué
  const big = planFromQty({ ...base, qty: 1, leverage: 2 });
  assert.equal(big.ok, false);
  assert.ok(big.errors.some((e) => /2 %/.test(e)));
  // Entre 1 % et 2 % → avertissement, pas blocage
  const mid = planFromQty({ ...base, qty: 0.7, leverage: 1 });
  assert.equal(mid.ok, true);
  assert.ok(mid.warnings.some((w) => /habituel/.test(w)));
  // Liquidation avant le SL → bloqué (x10 : liquidation ≈ 8 % ; SL à 10 %)
  const liq = planFromQty({ ...base, sl: 90, qty: 0.05, leverage: 10 });
  assert.ok(liq.errors.some((e) => /liquidation/.test(e)));
  // SHORT spot sans levier → Kraken exige x2
  const sh = planFromQty({ ...base, direction: "SHORT", sl: 102, tps: [96], qty: 0.4, leverage: 1 });
  assert.ok(sh.errors.some((e) => /x2/.test(e)));
  // Sans SL (marge isolée) : perte max = toute la position à x1 → au-delà de 2 %, bloqué par les garde-fous
  assert.ok(planFromQty({ ...base, sl: null, qty: 0.4, leverage: 1 }).errors.some((e) => /ajoute un stop/.test(e)));
  // Bouton « risquer 1 % » : 0,90 € / 2 $ = 0,45
  assert.equal(qtyForRisk(base, 1), 0.45);
});

test("garde-fous coupés : plus rien de bloquant côté club, seulement des avertissements ; Kraken reste respecté", async () => {
  const { planFromQty, planTrade } = await import("../sizing.js");
  const base = { direction: "LONG", entry: 100, sl: 90, tps: [120], balance: 90, riskPct: 1, maxRiskPct: 2,
    feeTaker: 0, feeMaker: 0, eurPerQuote: 1, lotDecimals: 4, venue: "spot", strict: false };
  const gros = planFromQty({ ...base, qty: 5, leverage: 10 });          // 50 € de perte (55 %) + liquidation avant SL
  assert.equal(gros.ok, true);
  assert.ok(gros.warnings.some((w) => /55/.test(w)) && gros.warnings.some((w) => /liquidation/.test(w)));
  // Ce que Kraken refuserait reste bloqué
  assert.equal(planFromQty({ ...base, qty: 50, leverage: 2 }).ok, false);                       // marge insuffisante
  assert.equal(planFromQty({ ...base, direction: "SHORT", sl: 110, tps: [80], qty: 0.1, leverage: 1 }).ok, false); // short spot x1
  // Mode automatique : risque 10 % accepté
  const auto = planTrade({ ...base, riskPct: 10, leverage: 10 });
  assert.equal(auto.ok, true);
  // Avec garde-fous (par défaut), le même trade est bloqué
  assert.equal(planFromQty({ ...base, strict: true, qty: 5, leverage: 10 }).ok, false);
});

test("marge isolée : stop facultatif, perte max = marge, marge libre respectée", async () => {
  const { planFromQty, usedMarginEur, openRiskEur } = await import("../sizing.js");
  const base = { direction: "LONG", entry: 100, tps: [110], balance: 90, riskPct: 1, maxRiskPct: 2, strict: false,
    feeTaker: 0, feeMaker: 0, eurPerQuote: 1, lotDecimals: 4, venue: "spot" };
  // Sans stop, x5 : 1 unité = 100 € de position, 20 € de marge → perte max 20 €
  const p = planFromQty({ ...base, sl: null, qty: 1, leverage: 5 });
  assert.equal(p.ok, true);
  assert.equal(p.hasSl, false);
  assert.ok(Math.abs(p.lossAtSlEur - 20) < 1e-9);
  assert.ok(Math.abs(p.liqPrice - 84) < 1e-9);
  assert.ok(p.warnings.some((w) => /liquidation/.test(w)));
  // Stop au-delà de la liquidation : perte plafonnée à la marge
  const loin = planFromQty({ ...base, sl: 70, qty: 1, leverage: 5 });
  assert.ok(Math.abs(loin.lossAtSlEur - 20) < 1e-9 && loin.liqBeforeSl);
  // Marge déjà utilisée par d'autres trades : 80 € bloqués → il reste 10 €
  const open = [{ status: "ouvert", qty_remaining: 4, entry_price: 100, eur_per_quote: 1, leverage: 5, sl: null }];
  assert.equal(usedMarginEur(open), 80);
  assert.equal(openRiskEur(open[0]), 80);
  const trop = planFromQty({ ...base, sl: null, qty: 1, leverage: 5, usedMarginEur: 80 });
  assert.equal(trop.ok, false);
  // Avec garde-fous : sans stop, 20 € = 22 % du solde → bloqué
  assert.equal(planFromQty({ ...base, strict: true, sl: null, qty: 1, leverage: 5 }).ok, false);
});
