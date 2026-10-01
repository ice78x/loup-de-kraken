// Petits outils d'affichage partagés par toutes les pages.

export const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export function px(x) {
  if (x == null || !isFinite(x)) return "—";
  const a = Math.abs(x);
  if (a >= 1000) return x.toLocaleString("fr-FR", { maximumFractionDigits: 1 });
  if (a >= 1) return x.toLocaleString("fr-FR", { maximumSignificantDigits: 6 });
  return x.toLocaleString("fr-FR", { maximumSignificantDigits: 5 });
}

export const sym = (quote) => ({ USD: " $", EUR: " €" }[quote] ?? (quote ? " " + quote : ""));
/** Prix avec sa devise de cotation (ex. « 64 230,5 $ »). */
export const pq = (x, quote) => (x == null || !isFinite(x) ? "—" : px(x) + sym(quote));

export const eur = (x, signe = false) => (x == null || !isFinite(x) ? "—" :
  (signe && x > 0 ? "+" : "") + x.toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " €");
export const pct = (x, d = 1) => (x == null || !isFinite(x) ? "—" : x.toLocaleString("fr-FR", { maximumFractionDigits: d }) + " %");
export const rr = (x) => (x == null || !isFinite(x) ? "—" : (x > 0 ? "+" : "") + x.toLocaleString("fr-FR", { maximumFractionDigits: 2 }) + " R");
export const cls = (x) => (x > 0 ? "gain" : x < 0 ? "perte" : "");

export function ago(iso) {
  if (!iso) return "—";
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 1) return "à l'instant";
  if (m < 60) return `il y a ${m} min`;
  const h = Math.round(m / 60);
  if (h < 48) return `il y a ${h} h`;
  return `il y a ${Math.round(h / 24)} j`;
}
export const hm = (iso) => (iso ? new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }) : "—");
export const dt = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—");

/** Prochain scan automatique : chaque heure à hh:05, de 6 h à 23 h (heure de Paris). */
export function nextScan() {
  const d = new Date();
  const paris = new Date(d.toLocaleString("en-US", { timeZone: "Europe/Paris" }));
  const next = new Date(paris);
  next.setMinutes(5, 0, 0);
  if (next <= paris) next.setHours(next.getHours() + 1);
  if (next.getHours() < 6) next.setHours(6, 5, 0, 0);
  if (next.getHours() > 23) { next.setDate(next.getDate() + 1); next.setHours(6, 5, 0, 0); }
  return next.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}

let toastTimer;
export function toast(msg, erreur = false) {
  document.querySelector(".toast")?.remove();
  const t = document.createElement("div");
  t.className = "toast" + (erreur ? " erreur" : "");
  t.setAttribute("role", erreur ? "alert" : "status");
  t.textContent = msg;
  document.body.append(t);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.remove(), erreur ? 7000 : 3500);
}

/** Ouvre une boîte de dialogue ; `build(dialog, close)` remplit le contenu. */
export function modal(html, onMount) {
  const d = document.createElement("dialog");
  d.innerHTML = html;
  document.body.append(d);
  const close = () => { d.close(); d.remove(); };
  d.addEventListener("cancel", close);
  d.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", close));
  d.showModal();
  onMount?.(d, close);
  return close;
}

/** Désactive un bouton pendant une action asynchrone et affiche l'erreur éventuelle. */
export async function busy(btn, fn) {
  const label = btn?.textContent;
  if (btn) { btn.disabled = true; btn.textContent = "Un instant…"; }
  try { return await fn(); }
  catch (e) { toast(e.message || String(e), true); }
  finally { if (btn && btn.isConnected) { btn.disabled = false; btn.textContent = label; } }
}

export const num = (v) => { const x = parseFloat(String(v).replace(",", ".").replace(/\s/g, "")); return isFinite(x) ? x : null; };

export const DIR = { LONG: "LONG ↑ achat", SHORT: "SHORT ↓ vente" };
export const STRAT = {
  cassure_retest: "Cassure + retest", rejet_sweep: "Rejet / piège", tendance_pullback: "Repli dans la tendance",
  news_momentum: "Réaction à une news", manuel: "Trade manuel",
};
