// Ce qui s'est passé sur un trade ouvert DEPUIS le dernier passage du bot (il passe une fois par heure, à hh:05).
// Lu sur les vraies bougies Kraken, mêmes règles que le bot : dans une même bougie, le stop est testé avant les objectifs.
// Rien n'est enregistré ici : c'est le bot qui l'enregistrera à son prochain passage.

/** t : trade ouvert ; candles : [[ts (s), open, high, low, close, vol], …] triées. Retourne { sl, tps: [1, 2…], at } ou null. */
export function depuisDernierPassage(t, candles, barSec = 900) {
  if (!t || t.status !== "ouvert" || !candles?.length) return null;
  const L = t.direction === "LONG", sign = L ? 1 : -1;
  const depuis = Math.max(Date.parse(t.last_checked || 0) || 0, Date.parse(t.opened_at) || 0) / 1000;
  const sl = +t.sl > 0 ? +t.sl : null;
  const tps = [t.tp1, t.tp2, t.tp3].map((x) => (x != null && +x > 0 ? +x : null));
  const deja = [!!t.tp1_hit, !!t.tp2_hit, !!t.tp3_hit];
  const out = { sl: false, tps: [], at: null };
  for (const c of candles) {
    if (+c[0] + barSec <= depuis) continue; // bougie terminée avant le dernier passage : déjà traitée par le bot
    const adverse = L ? +c[3] : +c[2], favorable = L ? +c[2] : +c[3];
    if (sl != null && sign * (adverse - sl) <= 0) { out.sl = true; out.at = +c[0]; break; }
    tps.forEach((tp, i) => { if (tp != null && !deja[i] && !out.tps.includes(i + 1) && sign * (favorable - tp) >= 0) { out.tps.push(i + 1); out.at = +c[0]; } });
    if (tps.every((tp, i) => tp == null || deja[i] || out.tps.includes(i + 1)) && out.tps.length) break;
  }
  return out.sl || out.tps.length ? out : null;
}

/** Phrase courte pour la page du trade. */
export function texteDepuis(d, prochainScan) {
  if (!d) return "";
  const quoi = d.sl ? (d.tps.length ? `TP${d.tps.join(", TP")} puis le stop touchés` : "le stop touché")
    : d.tps.length === 1 ? `TP${d.tps[0]} touché` : `TP${d.tps.slice(0, -1).join(", TP")} et TP${d.tps.at(-1)} touchés`;
  return `${d.sl ? "❌" : "🎯"} ${quoi.charAt(0).toUpperCase() + quoi.slice(1)} depuis le dernier passage du bot.
    Il l'enregistrera tout seul à son prochain passage (vers ${prochainScan}), avec les vraies bougies Kraken.`;
}

/**
 * Rejoue les bougies 5 min CLÔTURÉES depuis le dernier passage du bot, avec EXACTEMENT les règles du bot
 * (bot/src/kraken_assistant/cloud/tracker.py) : liquidation ou stop testés avant les objectifs dans une même bougie,
 * TP1 30 % / TP2 40 % / TP3 le reste, frais à chaque sortie. Retourne { upd, events } (upd vide = rien à enregistrer).
 */
export function rejouer(t, candles5, { split = [0.3, 0.4, 0.3], now = Date.now() } = {}) {
  const upd = {}, events = [];
  if (!t || t.status !== "ouvert" || !candles5?.length) return { upd, events };
  const sign = t.direction === "LONG" ? 1 : -1;
  const n = (x) => (x == null || x === "" || !isFinite(+x) ? null : +x);
  const entry = +t.entry_price, sl = n(t.sl) > 0 ? n(t.sl) : null, liq = n(t.liq_price);
  const lev = Math.max(1, n(t.leverage) || 1);
  const qty = +t.qty;
  let rem = +t.qty_remaining;
  const epq = +t.eur_per_quote || 1, fee = (+t.fee_pct || 0) / 100;
  let realized = +t.realized_pnl_eur || 0;
  const tps = [n(t.tp1), n(t.tp2), n(t.tp3)];
  const hit = [!!t.tp1_hit, !!t.tp2_hit, !!t.tp3_hit];
  const depuis = Math.floor(Math.max(Date.parse(t.last_checked || 0) || 0, Date.parse(t.opened_at) || 0) / 1000 / 300) * 300;
  const lastTp = tps.reduce((m, x, i) => (x != null ? i : m), -1);
  const quand = (ts) => new Date(ts * 1000).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).replace(",", "");
  let closed = false, vu = null;
  for (const c of candles5) {
    const ts = +c[0];
    if (ts < depuis || (ts + 300) * 1000 > now) continue; // déjà traitée, ou pas encore clôturée
    vu = ts;
    const [o, h, l] = [+c[1], +c[2], +c[3]];
    const adverse = sign > 0 ? l : h, fav = sign > 0 ? h : l;
    const liqFirst = liq != null && (sl == null || sign * (liq - sl) >= 0);
    if (liqFirst && sign * (adverse - liq) <= 0) {
      realized -= (rem * entry * epq) / lev;
      events.push(`${quand(ts)} LIQUIDATION vers ${liq} : marge du trade perdue`);
      Object.assign(upd, { exit_price: liq, close_reason: "Liquidation" });
      rem = 0; closed = true; break;
    }
    if (sl != null && sign * (adverse - sl) <= 0) {
      const px = sign > 0 ? Math.min(o, sl) : Math.max(o, sl);
      realized += sign * (px - entry) * rem * epq - fee * px * rem * epq;
      events.push(`${quand(ts)} SL touché à ${+px.toPrecision(8)}`);
      Object.assign(upd, { exit_price: px, close_reason: hit.some(Boolean) ? "SL ajusté" : "SL" });
      rem = 0; closed = true; break;
    }
    for (let i = 0; i < 3; i++) {
      const tp = tps[i];
      if (tp == null || hit[i] || sign * (fav - tp) < 0) continue;
      const q = i === lastTp ? rem : Math.min(rem, qty * split[i]);
      realized += sign * (tp - entry) * q * epq - fee * tp * q * epq;
      rem -= q; hit[i] = true;
      events.push(`${quand(ts)} TP${i + 1} atteint à ${tp} (${+q.toPrecision(6)} clôturé)`);
      if (rem <= 1e-12) { Object.assign(upd, { exit_price: tp, close_reason: `TP${i + 1}` }); closed = true; break; }
    }
    if (closed) break;
  }
  if (!events.length) return { upd: {}, events };
  const fin = new Date(((vu ?? depuis) + 300) * 1000).toISOString();
  Object.assign(upd, { qty_remaining: Math.max(0, +rem.toFixed(12)), realized_pnl_eur: +realized.toFixed(6),
    tp1_hit: hit[0], tp2_hit: hit[1], tp3_hit: hit[2], last_checked: fin });
  if (closed || rem <= 1e-12) {
    const risk = +t.risk_eur || 0;
    Object.assign(upd, { status: "clos", closed_at: fin, qty_remaining: 0, r_multiple: risk > 0 ? +(realized / risk).toFixed(3) : null });
  }
  upd.events = [...(t.events || []), ...events.map((e) => ({ at: new Date(now).toISOString(), by: "site", text: e }))];
  return { upd, events };
}

/**
 * Rattrapage automatique des trades d'entraînement ouverts d'un membre (au plus toutes les 2 min) :
 * TP / SL touchés depuis le dernier passage du bot, enregistrés avec les vraies bougies 5 min. Retourne le nombre de trades mis à jour.
 */
let dernierRattrapage = 0;
export async function rattraper(backend, ohlc, userId, { force = false } = {}) {
  if (!userId || (!force && Date.now() - dernierRattrapage < 120_000)) return 0;
  dernierRattrapage = Date.now();
  const ouverts = (await backend.trades({ userId, status: "ouvert", limit: 50 }).catch(() => []))
    .filter((t) => t.mode === "paper" && t.auto_track !== false).slice(0, 12);
  const n = await Promise.all(ouverts.map(async (t) => {
    const { upd, events } = rejouer(t, await ohlc(t, 5).catch(() => []));
    if (!events.length) return 0;
    return (await backend.updateTrade(t.id, upd).then(() => 1).catch(() => 0));
  }));
  return n.reduce((a, b) => a + b, 0);
}
