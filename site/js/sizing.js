// Calcul de position (même logique que le bot Python, risk/position_sizing.py).
// Ordre imposé : entrée → SL → montant accepté en perte → taille → multiplicateur (levier) EN DERNIER.
// Le multiplicateur ne change JAMAIS la perte au SL : il ne change que la marge immobilisée.

export const TP_SPLIT = [0.3, 0.4, 0.3];

const floorStep = (x, decimals) => {
  const step = 10 ** -decimals;
  return Math.floor(x / step + 1e-9) * step;
};

export function checkLevels(direction, entry, sl, tps) {
  const errors = [];
  if (!(entry > 0) || !(sl > 0)) return ["Entrée et SL doivent être des prix positifs."];
  if (direction === "LONG" && sl >= entry) errors.push("En LONG, le SL doit être sous l'entrée.");
  if (direction === "SHORT" && sl <= entry) errors.push("En SHORT, le SL doit être au-dessus de l'entrée.");
  let prev = entry;
  tps.forEach((tp, i) => {
    if (tp == null) return;
    if ((direction === "LONG" && tp <= prev) || (direction === "SHORT" && tp >= prev)) {
      errors.push(`TP${i + 1} doit être plus loin que ${i ? "TP" + i : "l'entrée"} dans le sens du trade.`);
    }
    prev = tp;
  });
  return errors;
}

/**
 * @param {object} p
 * balance (€), riskPct (%), entry, sl, tps [..], direction "LONG"|"SHORT", leverage (1-10),
 * feeTaker (% par côté), feeMaker (%), entryIsMaker, eurPerQuote, lotDecimals, ordermin
 */
export function planTrade(p) {
  const direction = p.direction;
  const tps = (p.tps || []).filter((x) => x != null && x > 0);
  const errors = checkLevels(direction, p.entry, p.sl, tps);
  const warnings = [];
  const lev = Math.round(p.leverage || 1);
  if (!(p.balance > 0)) errors.push("Ton solde doit être supérieur à 0 € (modifie-le dans Mon compte).");
  if (!(p.riskPct > 0)) errors.push("Le risque par trade doit être supérieur à 0 %.");
  if (lev < 1 || lev > 10) errors.push("Le multiplicateur doit être entre x1 et x10.");
  if (!(p.eurPerQuote > 0)) errors.push("Taux de conversion en euros indisponible.");
  if (errors.length) return { ok: false, errors, warnings };

  const ft = (p.feeTaker ?? 0.4) / 100;
  const fm = (p.feeMaker ?? p.feeTaker ?? 0.4) / 100;
  const fe = p.entryIsMaker ? fm : ft;
  const dist = Math.abs(p.entry - p.sl);
  const riskEur = (p.balance * p.riskPct) / 100;
  const perUnitLoss = dist + fe * p.entry + ft * p.sl;
  const qty = floorStep(riskEur / p.eurPerQuote / perUnitLoss, p.lotDecimals ?? 8);
  if (qty <= 0 || (p.ordermin && qty < p.ordermin)) {
    const needed = (p.ordermin || 0) * perUnitLoss * p.eurPerQuote;
    return { ok: false, warnings, errors: [
      `La taille minimale Kraken est plus grande que ce que ton risque permet${needed ? ` (il faudrait risquer ${needed.toFixed(2)} €)` : ""}.`] };
  }
  const notionalEur = qty * p.entry * p.eurPerQuote;
  const marginEur = notionalEur / lev;
  const slPct = (dist / p.entry) * 100;
  if (lev > 1 && slPct > 50 / lev) {
    errors.push(`Avec x${lev}, la liquidation (≈ ${(100 / lev).toFixed(0)} % de mouvement) arriverait trop près de ton SL (${slPct.toFixed(1)} %). Baisse le multiplicateur.`);
  }
  if (marginEur > p.balance + 1e-9) {
    const need = Math.ceil(notionalEur / p.balance);
    errors.push(need <= 10
      ? `Marge insuffisante : il faut au moins x${need} pour cette taille (ton risque, lui, ne change pas).`
      : "Marge insuffisante même à x10 : le SL est trop serré pour ton solde.");
  }
  const lossAtSlEur = (qty * dist + qty * (fe * p.entry + ft * p.sl)) * p.eurPerQuote;
  const feesShare = (qty * (fe * p.entry + ft * p.sl) * p.eurPerQuote) / lossAtSlEur;
  if (feesShare > 0.35) warnings.push(`Les frais représentent ${(feesShare * 100).toFixed(0)} % de ta perte au SL : SL très serré.`);
  const split = TP_SPLIT.slice(0, tps.length);
  const sum = split.reduce((a, b) => a + b, 0) || 1;
  const rr = tps.map((tp) => Math.abs(tp - p.entry) / dist);
  const rrNet = tps.map((tp) => (Math.abs(tp - p.entry) - fe * p.entry - fm * tp) / perUnitLoss);
  const profitsEur = tps.map((tp, i) => {
    const q = qty * (split[i] / sum);
    return (q * Math.abs(tp - p.entry) - q * (fe * p.entry + fm * tp)) * p.eurPerQuote;
  });
  return {
    ok: errors.length === 0, errors, warnings, riskEur, qty, notionalEur, marginEur, lossAtSlEur,
    effectiveRiskPct: (lossAtSlEur / p.balance) * 100, slPct, rr, rrNet, profitsEur, leverage: lev,
    entryFeeEur: fe * p.entry * qty * p.eurPerQuote,
  };
}

/** Plus petit multiplicateur qui permet de loger la position dans le solde (et reste sûr vs SL). */
export function suggestLeverage(plan, balance, slPct, maxLev = 10) {
  if (!plan || !(plan.notionalEur > 0)) return 1;
  for (let lev = 1; lev <= maxLev; lev++) {
    if (plan.notionalEur / lev <= balance && (lev === 1 || slPct <= 50 / lev)) return lev;
  }
  return null;
}

/** Risque encore engagé sur un trade ouvert (0 si le SL verrouille un gain). */
export function openRiskEur(t) {
  if (t.status !== "ouvert") return 0;
  const sign = t.direction === "LONG" ? 1 : -1;
  const loss = sign * (t.entry_price - t.sl) * t.qty_remaining;
  const fee = ((t.fee_pct || 0) / 100) * t.sl * t.qty_remaining;
  return (Math.max(0, loss) + fee) * (t.eur_per_quote || 1);
}

/** Budget de risque d'un membre : plafond du risque ouvert + limite de perte du jour. */
export function riskBudget(profile, trades, now = new Date()) {
  const balance = +profile.balance_eur;
  const open = trades.filter((t) => t.status === "ouvert");
  const openRisk = open.reduce((a, t) => a + openRiskEur(t), 0);
  const day = new Date(now.toLocaleString("en-US", { timeZone: "Europe/Paris" }));
  day.setHours(0, 0, 0, 0);
  const dayStartUtc = new Date(now.getTime() - (new Date(now.toLocaleString("en-US", { timeZone: "Europe/Paris" })) - day));
  const todayPnl = trades
    .filter((t) => t.status === "clos" && t.closed_at && new Date(t.closed_at) >= dayStartUtc)
    .reduce((a, t) => a + (+t.realized_pnl_eur || 0), 0);
  const maxOpen = (balance * profile.max_open_risk_pct) / 100;
  const dailyLimit = (balance * profile.max_daily_loss_pct) / 100;
  const lossToday = Math.max(0, -todayPnl);
  const available = Math.max(0, Math.min(maxOpen - openRisk, dailyLimit - lossToday - openRisk));
  return {
    balance, openRisk, maxOpen, available, availablePct: balance ? (available / balance) * 100 : 0,
    todayPnl, dailyLimit, dailyStop: lossToday >= dailyLimit - 1e-9, openCount: open.length,
  };
}

/** Clôture partielle ou totale : P&L en € (frais de sortie inclus). */
export function closePart(t, price, qty) {
  const sign = t.direction === "LONG" ? 1 : -1;
  const q = Math.min(qty, t.qty_remaining);
  const fee = ((t.fee_pct || 0) / 100) * price * q;
  const pnl = (sign * (price - t.entry_price) * q - fee) * (t.eur_per_quote || 1);
  const remaining = +(t.qty_remaining - q).toFixed(12);
  const realized = (+t.realized_pnl_eur || 0) + pnl;
  const done = remaining <= 1e-12;
  return {
    pnl, update: {
      qty_remaining: done ? 0 : remaining, realized_pnl_eur: realized,
      ...(done ? { status: "clos", closed_at: new Date().toISOString(), exit_price: price,
        r_multiple: t.risk_eur > 0 ? +(realized / t.risk_eur).toFixed(3) : null } : {}),
    },
  };
}

/** P&L latent (non réalisé) au prix donné, en €. */
export function unrealizedEur(t, price) {
  if (!(price > 0) || t.status !== "ouvert") return 0;
  const sign = t.direction === "LONG" ? 1 : -1;
  return sign * (price - t.entry_price) * t.qty_remaining * (t.eur_per_quote || 1);
}
