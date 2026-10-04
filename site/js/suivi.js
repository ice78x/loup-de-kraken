// Ce qui s'est passé sur un trade ouvert DEPUIS le dernier passage du bot (le bot ne tourne pas la nuit, de 23 h à 6 h).
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
  return `${d.sl ? "❌" : "🎯"} ${quoi.charAt(0).toUpperCase() + quoi.slice(1)} depuis le dernier passage du bot. Le bot ne tourne pas la nuit (23 h – 6 h) :
    il l'enregistrera tout seul à son prochain passage (vers ${prochainScan}), avec les vraies bougies Kraken.`;
}
