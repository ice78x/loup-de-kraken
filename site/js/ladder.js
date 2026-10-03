// L'échelle de prix : SL, zone d'entrée et TP placés à leur vraie distance.
// On voit d'un coup d'œil combien on risque (rouge) et combien on peut gagner (vert).
import { px } from "./ui.js";

export function ladder({ direction, entryLow, entryHigh, sl, tps = [], price = null, compact = false, anim = false, slLabel = "SL", riskRef = null }) {
  if (!(sl > 0)) return ""; // ni stop ni liquidation (LONG sans levier) : pas d'échelle de risque
  const tp = tps.filter((x) => x != null);
  const vals = [sl, entryLow, entryHigh, ...tp, ...(price ? [price] : [])].filter((x) => x != null && isFinite(x));
  if (vals.length < 3) return "";
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const H = compact ? 170 : 260, top = 14, bot = 14, W = 200;
  const y = (v) => top + (hi - v) / (hi - lo || 1) * (H - top - bot);
  const entry = direction === "LONG" ? entryHigh : entryLow;
  // riskRef : distance du risque de départ (trade dont le stop a été déplacé, ex. au break-even) ; sinon entrée → stop.
  const risk = riskRef > 0 ? riskRef : Math.abs(entry - sl) || 1;
  const sgn = direction === "LONG" ? 1 : -1;
  const rSl = (sgn * (sl - entry)) / risk;
  const slR = riskRef > 0 ? (Math.abs(rSl) < 0.05 ? " · 0R (break-even)" : ` · ${rSl > 0 ? "+" : "−"}${Math.abs(rSl).toFixed(1)}R`) : " · −1R";
  const bandTop = y(Math.max(entryLow, entryHigh)), bandBot = y(Math.min(entryLow, entryHigh));
  const rows = [];
  // zone de risque et de gain
  rows.push(`<rect x="34" y="${Math.min(y(entry), y(sl))}" width="10" height="${Math.abs(y(entry) - y(sl))}" fill="#FF6B6B" opacity=".35"/>`);
  if (tp.length) rows.push(`<rect x="34" y="${Math.min(y(entry), y(tp.at(-1)))}" width="10" height="${Math.abs(y(entry) - y(tp.at(-1)))}" fill="#3DDC97" opacity=".3"/>`);
  rows.push(`<rect x="30" y="${bandTop}" width="${W - 30}" height="${Math.max(3, bandBot - bandTop)}" fill="#F2B544" opacity=".25" rx="2"/>`);
  const line = (v, color, name, extra = "") => {
    const yy = y(v).toFixed(1);
    return `<line class="trait" x1="30" x2="${W}" y1="${yy}" y2="${yy}" stroke="${color}"/>` +
      `<text x="0" y="${+yy + 4}" class="lbl">${name}</text>` +
      `<text x="${W}" y="${+yy - 4}" text-anchor="end">${px(v)}${extra}</text>`;
  };
  rows.push(line(sl, rSl >= -0.05 && riskRef > 0 ? "#F2B544" : "#FF6B6B", slLabel, slR));
  tp.forEach((t, i) => rows.push(line(t, "#3DDC97", `TP${i + 1}`, ` · +${(Math.abs(t - entry) / risk).toFixed(1)}R`)));
  rows.push(line(entry, "#F2B544", "Entrée"));
  if (price) {
    const yy = y(price).toFixed(1);
    rows.push(`<circle cx="39" cy="${yy}" r="5" fill="#E9EFF4" stroke="#0E1A2B" stroke-width="2"/><title>Prix actuel ${px(price)}</title>`);
  }
  return `<svg class="echelle${anim ? " anim" : ""}" viewBox="0 0 ${W} ${H}" role="img"
    aria-label="Échelle de prix : SL ${px(sl)}, entrée ${px(entry)}, objectifs ${tp.map(px).join(", ")}">${rows.join("")}</svg>`;
}
