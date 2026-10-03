// Calcul de position (même logique que le bot Python, risk/position_sizing.py).
// Ordre imposé : entrée → SL → montant accepté en perte → taille → multiplicateur (levier) EN DERNIER.
// Le multiplicateur ne change JAMAIS la perte au SL : il ne change que la marge immobilisée.

export const TP_SPLIT = [0.3, 0.4, 0.3];

const floorStep = (x, decimals) => {
  const step = 10 ** -decimals;
  return +(Math.floor(x / step + 1e-9) * step).toFixed(Math.max(0, decimals));
};

export function checkLevels(direction, entry, sl, tps) {
  const errors = [];
  if (!(entry > 0)) return ["Le prix d'entrée doit être positif."];
  if (sl != null) { // stop facultatif (marge isolée)
    if (!(sl > 0)) return ["Le SL doit être un prix positif."];
    if (direction === "LONG" && sl >= entry) errors.push("En LONG, le SL doit être sous l'entrée.");
    if (direction === "SHORT" && sl <= entry) errors.push("En SHORT, le SL doit être au-dessus de l'entrée.");
  }
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
  if (!(p.sl > 0)) errors.push("Pour calculer une taille à partir du risque, il faut un stop.");
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
  const liqPct = liqFraction(lev, p.venue || "futures", p.maxLev || 10) * 100;
  if (lev > 1 && liqPct < 2 * slPct) {
    (p.strict === false ? warnings : errors).push(`Avec x${lev}, la liquidation (≈ ${liqPct.toFixed(1).replace(".", ",")} % de mouvement) arriverait trop près de ton SL (${slPct.toFixed(1).replace(".", ",")} %). Baisse le levier.`);
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

/**
 * Distance (en fraction du prix) à laquelle Kraken liquide une position ISOLÉE (approximation, prix de référence = « mark price ») :
 * - Futures perpétuels (clients EEE) : liquidation quand marge + perte latente < marge de maintenance,
 *   et la marge de maintenance = moitié de la marge initiale minimale (10 % pour un contrat à x10 max → 5 % de la position).
 *   Donc distance ≈ 1/levier − 0,5/levier max du contrat. Ex. x10 → 5 %, x5 → 15 %, x3 → 28 %.
 * - Spot sur marge : liquidation à 40 % de « margin level » → on perd 60 % de la marge → distance ≈ 0,6/levier.
 * Sources : support.kraken.com (Perpetual contract specifications for clients in the EEA ; Margin call level and margin liquidation level).
 */
export function liqFraction(lev, venue = "futures", maxLev = 10) {
  const l = Math.max(1, +lev || 1);
  if (venue === "futures") return Math.max(0.005, 1 / l - 0.5 / Math.max(1, +maxLev || 10));
  return 0.6 / l;
}

/** Prix de liquidation approximatif d'une position isolée (null : LONG spot sans levier, jamais liquidé). */
export function liquidationPrice(direction, entry, lev, venue = "spot", maxLev = 10) {
  if (!(entry > 0)) return null;
  if (direction === "LONG" && lev <= 1 && venue === "spot") return null;
  const d = liqFraction(lev, venue, maxLev);
  return direction === "LONG" ? entry * (1 - d) : entry * (1 + d);
}

/** Marge déjà bloquée par les trades ouverts (marge isolée : chaque trade n'engage que la sienne). */
export function usedMarginEur(trades) {
  return trades.filter((t) => t.status === "ouvert")
    .reduce((a, t) => a + (+t.qty_remaining * +t.entry_price * (+t.eur_per_quote || 1)) / Math.max(1, +t.leverage || 1), 0);
}

/**
 * Mode « comme sur Kraken », MARGE ISOLÉE : le membre choisit la QUANTITÉ et le levier ; on calcule ce que ça implique.
 * - Chaque trade n'engage que sa marge (valeur / levier). Le reste du capital n'est jamais touché par ce trade.
 * - Stop loss FACULTATIF. Sans stop, la perte max = la marge (+ frais), atteinte à la liquidation.
 * - Avec stop : perte au stop, plafonnée à la marge si la liquidation arrive avant.
 * p : direction, entry, sl?, tps, qty, leverage, balance, usedMarginEur, riskPct, maxRiskPct, strict,
 *     feeTaker, feeMaker, entryIsMaker, eurPerQuote, lotDecimals, ordermin, venue
 */
export function planFromQty(p) {
  const direction = p.direction;
  const tps = (p.tps || []).filter((x) => x != null && x > 0);
  const errors = [], warnings = [];
  const lev = Math.round(p.leverage || 1);
  const hasSl = p.sl > 0;
  const strict = p.strict !== false; // garde-fous du club (coupables dans Mon compte)
  const guard = (msg) => (strict ? errors : warnings).push(msg);
  if (!(p.entry > 0)) errors.push("Indique un prix d'entrée.");
  else errors.push(...checkLevels(direction, p.entry, hasSl ? p.sl : null, tps));
  if (!(p.balance > 0)) errors.push("Ton solde doit être supérieur à 0 € (modifie-le dans Mon compte).");
  if (!(p.eurPerQuote > 0)) errors.push("Taux de conversion en euros indisponible.");
  const qty = p.qty > 0 ? floorStep(p.qty, p.lotDecimals ?? 8) : 0;
  if (!(qty > 0)) errors.push("Indique une quantité (ou un montant).");
  if (lev < 1 || lev > 10) errors.push("Le levier doit être entre x1 et x10.");
  if (direction === "SHORT" && (p.venue || "spot") === "spot" && lev < 2) {
    errors.push("Sur Kraken, un SHORT en spot se fait sur marge : choisis au moins x2.");
  }
  if (errors.length) return { ok: false, errors, warnings };
  if (p.ordermin && qty < p.ordermin) errors.push(`Quantité minimale sur Kraken : ${p.ordermin}.`);

  const ft = (p.feeTaker ?? 0.4) / 100;
  const fm = (p.feeMaker ?? p.feeTaker ?? 0.4) / 100;
  const fe = p.entryIsMaker ? fm : ft;
  const fx = p.eurPerQuote;
  const notionalQuote = qty * p.entry;
  const notionalEur = notionalQuote * fx;
  const marginEur = notionalEur / lev;
  const entryFeeEur = fe * p.entry * qty * fx;
  const liqPrice = liquidationPrice(direction, p.entry, lev, p.venue || "spot", p.maxLev || 10);
  // Perte max en marge isolée : toute la marge du trade + frais d'entrée. Jamais plus.
  const capEur = marginEur + entryFeeEur;
  let lossAtSlEur, slPct, dist, liqBeforeSl = false;
  if (hasSl) {
    dist = Math.abs(p.entry - p.sl);
    slPct = (dist / p.entry) * 100;
    const raw = (qty * dist + qty * (fe * p.entry + ft * p.sl)) * fx;
    liqBeforeSl = liqPrice != null && (direction === "LONG" ? p.sl <= liqPrice : p.sl >= liqPrice);
    lossAtSlEur = Math.min(raw, capEur);
    if (liqBeforeSl) guard(`Avec x${lev}, la liquidation (≈ ${liqPrice.toPrecision(5)}) arrive AVANT ton stop : tu perdrais toute la marge du trade.`);
  } else {
    lossAtSlEur = capEur;
    dist = liqPrice != null ? Math.abs(p.entry - liqPrice) : p.entry; // sans stop : jusqu'à la liquidation (ou 0 en LONG x1)
    slPct = (dist / p.entry) * 100;
    warnings.push(liqPrice != null
      ? `Sans stop : si le prix atteint la liquidation (≈ ${liqPrice.toPrecision(5)}), tu perds toute la marge du trade. Le reste de ton capital n'est pas touché.`
      : "Sans stop et sans levier : tu ne peux pas être liquidé, mais la position entière peut perdre de la valeur. Le reste de ton capital n'est pas touché.");
  }
  const lossPct = (lossAtSlEur / p.balance) * 100;
  const free = p.balance - (p.usedMarginEur || 0);
  // Comme Kraken : la marge ET les frais d'entrée doivent tenir dans la marge libre.
  if (marginEur + entryFeeEur > free + 1e-9) {
    const need = Math.ceil(notionalEur / Math.max(free - entryFeeEur, 1e-9));
    errors.push(free <= 0 ? "Plus de marge disponible : tes trades ouverts bloquent déjà tout ton solde."
      : need <= 10 ? `Marge insuffisante : il reste ${free.toFixed(2)} € de marge libre (il faudrait au moins x${need}, ou moins de quantité).`
        : "Marge insuffisante même à x10 : baisse la quantité.");
  }
  const maxRisk = p.maxRiskPct ?? 2;
  if (lossPct > maxRisk + 1e-9) {
    guard(strict ? `Règle du club : jamais plus de ${maxRisk} % du solde en jeu par trade. Ici tu peux perdre ${lossPct.toFixed(2)} % : ${hasSl ? "baisse la quantité" : "ajoute un stop ou baisse la quantité"}.`
      : `Tu peux perdre ${lossPct.toFixed(2)} % de ton solde sur ce trade (la règle du club conseille ${maxRisk} % maximum).`);
  } else if (p.riskPct && lossPct > p.riskPct + 1e-9) {
    warnings.push(`Tu risques ${lossPct.toFixed(2)} % de ton solde, plus que ton risque habituel (${p.riskPct} %). Réservé aux setups exceptionnels.`);
  }
  if (hasSl) {
    const feesShare = (qty * (fe * p.entry + ft * p.sl) * fx) / lossAtSlEur;
    if (feesShare > 0.35) warnings.push(`Les frais représentent ${(feesShare * 100).toFixed(0)} % de ta perte au SL : SL très serré.`);
  }
  const split = TP_SPLIT.slice(0, tps.length);
  const sum = split.reduce((a, b) => a + b, 0) || 1;
  const riskUnit = lossAtSlEur / (qty * fx); // perte max par unité, frais compris
  const rr = tps.map((tp) => Math.abs(tp - p.entry) / dist);
  const rrNet = tps.map((tp) => (Math.abs(tp - p.entry) - fe * p.entry - fm * tp) / riskUnit);
  const profitsEur = tps.map((tp, i) => {
    const q = qty * (split[i] / sum);
    return (q * Math.abs(tp - p.entry) - q * (fe * p.entry + fm * tp)) * fx;
  });
  return {
    ok: errors.length === 0, errors, warnings, qty, notionalQuote, notionalEur, marginEur, lossAtSlEur, lossPct, hasSl, liqBeforeSl,
    effectiveRiskPct: lossPct, slPct, liqPrice, rr, rrNet, profitsEur, leverage: lev, entryFeeEur, freeMarginEur: free,
  };
}

/** Quantité qui fait perdre exactement riskPct % du solde au SL (frais compris) — bouton « taille pour risquer 1 % ». */
export function qtyForRisk(p, riskPct) {
  const ft = (p.feeTaker ?? 0.4) / 100, fm = (p.feeMaker ?? p.feeTaker ?? 0.4) / 100;
  const fe = p.entryIsMaker ? fm : ft;
  const perUnit = Math.abs(p.entry - p.sl) + fe * p.entry + ft * p.sl;
  if (!(perUnit > 0) || !(p.eurPerQuote > 0) || !(p.balance > 0)) return null;
  return floorStep(((p.balance * riskPct) / 100) / p.eurPerQuote / perUnit, p.lotDecimals ?? 8);
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
  if (!(+t.sl > 0)) { // pas de stop : en marge isolée, on peut perdre la marge restante du trade
    return (+t.qty_remaining * +t.entry_price * (+t.eur_per_quote || 1)) / Math.max(1, +t.leverage || 1);
  }
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

/**
 * Détail clair d'un trade ouvert, en € :
 * - move : ce que le mouvement du prix rapporte/coûte sur la quantité restante (avant frais)
 * - entryFee : frais payés à l'ouverture (déjà prélevés)
 * - banked : ce que les TP déjà touchés ont rapporté (net de leurs frais)
 * - exitFee : frais estimés si on ferme le reste maintenant
 * - ifCloseNow : résultat total si on ferme tout maintenant = banked − entryFee + move − exitFee
 */
export function pnlBreakdown(t, price) {
  const fx = +t.eur_per_quote || 1;
  const fee = (+t.fee_pct || 0) / 100;
  const entryFee = fee * +t.entry_price * +t.qty * fx;
  const realized = +t.realized_pnl_eur || 0;
  const banked = realized + entryFee;
  const ok = price > 0 && t.status === "ouvert";
  const move = ok ? unrealizedEur(t, price) : null;
  const exitFee = ok ? fee * price * +t.qty_remaining * fx : null;
  return { entryFee, banked, move, exitFee, ifCloseNow: ok ? realized + move - exitFee : null };
}

/**
 * Recalcule un trade enregistré avec d'autres frais (ex. il a été saisi avec les frais spot 0,40 % alors qu'il est passé
 * en futures perpétuels à 0,02 %). Les ventes déjà faites (TP, clôtures) sont retrouvées à partir du résultat enregistré :
 * résultat = mouvement du prix − frais × (valeur à l'entrée + valeur des ventes). Rien n'est inventé : mêmes prix, mêmes quantités.
 * Retourne { realized, rMultiple, riskEur, ventes } (ventes = valeur des sorties, en devise de cotation) ou null si impossible.
 */
export function recalculerFrais(t, nouveauPct) {
  const f = (+t.fee_pct || 0) / 100, g = (+nouveauPct || 0) / 100;
  const E = +t.entry_price, q = +t.qty, fx = +t.eur_per_quote || 1;
  if (!(E > 0) || !(q > 0)) return null;
  const qc = q - (+t.qty_remaining || 0); // quantité déjà vendue
  const r = (+t.realized_pnl_eur || 0) / fx;
  const ventes = t.direction === "LONG" ? (r + E * qc + f * E * q) / (1 - f) : (E * qc - f * E * q - r) / (1 + f);
  if (!isFinite(ventes) || ventes < -1e-9) return null;
  const realized = (r + (f - g) * (E * q + ventes)) * fx;
  const sl = +t.sl;
  const riskEur = sl > 0 ? (q * Math.abs(E - sl) + q * g * (E + sl)) * fx : +t.risk_eur;
  return { realized, riskEur, ventes, rMultiple: t.status === "ouvert" || !(riskEur > 0) ? null : +(realized / riskEur).toFixed(3) };
}
