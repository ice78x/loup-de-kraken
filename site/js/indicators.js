// Indicateurs techniques calculés à partir des VRAIES bougies Kraken (rien d'inventé). Fonctions pures, testées.
// Bougie = [temps (s), ouverture, plus haut, plus bas, clôture, volume?].

const C = (k) => +k[4], H = (k) => +k[2], Lo = (k) => +k[3];

/** Moyenne mobile exponentielle. Retourne un tableau aligné sur les entrées (null tant qu'il n'y a pas assez de données). */
export function ema(values, n) {
  const out = new Array(values.length).fill(null);
  if (values.length < n) return out;
  const a = 2 / (n + 1);
  let e = values.slice(0, n).reduce((s, v) => s + v, 0) / n;
  out[n - 1] = e;
  for (let i = n; i < values.length; i++) { e = values[i] * a + e * (1 - a); out[i] = e; }
  return out;
}

/** RSI de Wilder (14 par défaut), aligné sur les bougies. */
export function rsi(candles, n = 14) {
  const out = new Array(candles.length).fill(null);
  if (candles.length <= n) return out;
  let g = 0, l = 0;
  for (let i = 1; i <= n; i++) { const d = C(candles[i]) - C(candles[i - 1]); if (d > 0) g += d; else l -= d; }
  g /= n; l /= n;
  out[n] = l === 0 ? 100 : 100 - 100 / (1 + g / l);
  for (let i = n + 1; i < candles.length; i++) {
    const d = C(candles[i]) - C(candles[i - 1]);
    g = (g * (n - 1) + Math.max(0, d)) / n;
    l = (l * (n - 1) + Math.max(0, -d)) / n;
    out[i] = l === 0 ? 100 : 100 - 100 / (1 + g / l);
  }
  return out;
}

/** ATR (volatilité moyenne d'une bougie), aligné sur les bougies. */
export function atr(candles, n = 14) {
  const out = new Array(candles.length).fill(null);
  if (candles.length <= n) return out;
  const tr = candles.map((k, i) => (i === 0 ? H(k) - Lo(k)
    : Math.max(H(k) - Lo(k), Math.abs(H(k) - C(candles[i - 1])), Math.abs(Lo(k) - C(candles[i - 1])))));
  let a = tr.slice(1, n + 1).reduce((s, v) => s + v, 0) / n;
  out[n] = a;
  for (let i = n + 1; i < candles.length; i++) { a = (a * (n - 1) + tr[i]) / n; out[i] = a; }
  return out;
}

/** VWAP qui repart de zéro chaque jour (UTC). null si le volume manque. */
export function vwap(candles) {
  let day = null, pv = 0, v = 0;
  return candles.map((k) => {
    const vol = +k[5];
    if (!(vol >= 0) || k[5] == null) return null;
    const d = Math.floor(+k[0] / 86400);
    if (d !== day) { day = d; pv = 0; v = 0; }
    pv += ((H(k) + Lo(k) + C(k)) / 3) * vol;
    v += vol;
    return v > 0 ? pv / v : null;
  });
}

/**
 * Sommets et creux « pivots » : un sommet est plus haut que les `k` bougies de chaque côté (idem pour un creux).
 * Retourne [{ i, time, price, type: "H" | "L" }] dans l'ordre du temps.
 */
export function pivots(candles, k = 3) {
  const out = [];
  for (let i = k; i < candles.length - k; i++) {
    const h = H(candles[i]), l = Lo(candles[i]);
    let top = true, bot = true;
    for (let j = i - k; j <= i + k; j++) {
      if (j === i) continue;
      if (H(candles[j]) >= h) top = false;
      if (Lo(candles[j]) <= l) bot = false;
    }
    if (top) out.push({ i, time: +candles[i][0], price: h, type: "H" });
    if (bot) out.push({ i, time: +candles[i][0], price: l, type: "L" });
  }
  return out;
}

/**
 * Structure du marché : chaque sommet comparé au précédent (HH plus haut / LH plus bas), chaque creux (HL / LL).
 * Retourne les pivots étiquetés + la tendance qui en découle.
 */
export function structure(candles, k = 3) {
  const pv = pivots(candles, k);
  let lastH = null, lastL = null;
  const labels = [];
  for (const p of pv) {
    if (p.type === "H") { if (lastH != null) labels.push({ ...p, label: p.price > lastH ? "HH" : "LH" }); lastH = p.price; }
    else { if (lastL != null) labels.push({ ...p, label: p.price > lastL ? "HL" : "LL" }); lastL = p.price; }
  }
  const lastHigh = [...labels].reverse().find((x) => x.type === "H")?.label;
  const lastLow = [...labels].reverse().find((x) => x.type === "L")?.label;
  const trend = lastHigh === "HH" && lastLow === "HL" ? "haussière" : lastHigh === "LH" && lastLow === "LL" ? "baissière" : "sans direction claire";
  return { labels, trend, lastHigh, lastLow };
}

/**
 * Supports et résistances : pivots regroupés quand ils sont proches (moins de `tol` × ATR).
 * Plus un niveau a été touché, plus il compte. Retourne au plus `max` niveaux sous et au-dessus du prix.
 */
export function niveaux(candles, { k = 3, tol = 0.6, max = 3 } = {}) {
  if (candles.length < 2 * k + 2) return { supports: [], resistances: [] };
  const a = atr(candles).filter((x) => x != null).at(-1) || (H(candles.at(-1)) - Lo(candles.at(-1)));
  const groups = [];
  for (const p of pivots(candles, k)) {
    const g = groups.find((x) => Math.abs(x.price - p.price) <= tol * a);
    if (g) { g.price = (g.price * g.touches + p.price) / (g.touches + 1); g.touches++; g.last = Math.max(g.last, p.time); }
    else groups.push({ price: p.price, touches: 1, last: p.time });
  }
  const px = C(candles.at(-1));
  const score = (g) => g.touches * 2 + g.last / 1e10;
  const supports = groups.filter((g) => g.price < px).sort((x, y) => score(y) - score(x)).slice(0, max).sort((x, y) => y.price - x.price);
  const resistances = groups.filter((g) => g.price > px).sort((x, y) => score(y) - score(x)).slice(0, max).sort((x, y) => x.price - y.price);
  return { supports, resistances };
}

/** Lecture rapide en français simple (pédagogique, PAS un signal). null pour les éléments impossibles à calculer. */
export function lecture(candles) {
  if (!candles?.length || candles.length < 30) return null;
  const closes = candles.map(C);
  const px = closes.at(-1);
  const e20 = ema(closes, 20).at(-1), e50 = ema(closes, 50).at(-1);
  const r = rsi(candles).at(-1);
  const a = atr(candles).at(-1);
  const st = structure(candles);
  const nv = niveaux(candles);
  const vols = candles.map((k) => +k[5]).filter((v) => v >= 0);
  const volRel = vols.length >= 21 ? vols.at(-2) / (vols.slice(-22, -2).reduce((s, v) => s + v, 0) / 20) : null;
  const tendanceEma = e20 == null || e50 == null ? null : px > e20 && e20 > e50 ? "haussière" : px < e20 && e20 < e50 ? "baissière" : "hésitante";
  return {
    prix: px,
    tendanceEma, e20, e50,
    structure: st.trend, lastHigh: st.lastHigh, lastLow: st.lastLow,
    rsi: r, rsiMot: r == null ? null : r >= 70 ? "très acheté : le mouvement peut s'essouffler" : r <= 30 ? "très vendu : un rebond est possible"
      : r >= 55 ? "acheteurs plutôt aux commandes" : r <= 45 ? "vendeurs plutôt aux commandes" : "neutre",
    atrPct: a == null ? null : (a / px) * 100,
    support: nv.supports[0] || null, resistance: nv.resistances[0] || null,
    volRel,
  };
}
