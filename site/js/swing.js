// SWING (19/10) : positions de plusieurs jours du bot (bougies journalières, stop suiveur remonté chaque matin).
// Rien n'est inventé : les positions viennent de la table swing_positions (écrite par le bot), le prix de /api/market.
import { esc, pq, rr } from "./ui.js";

export const isLong = (p) => p.direction === "LONG";
const sens = (p) => (isLong(p) ? 1 : -1);
/** Objet compatible avec market.js (prix en direct du perpétuel). */
export const refPos = (p) => ({ ...p, venue: "futures", api_symbol: String(p.display), api_asset_class: null });
export const entreeDe = (p) => (p.entry_price != null ? +p.entry_price : +p.signal_close);
export const risqueDe = (p) => Math.abs(entreeDe(p) - +p.stop_initial);
export const nomSwing = (p) => { const d = String(p.display).replace(/^PF_/, ""); const b = d.endsWith("USD") ? d.slice(0, -3) : d; return b === "XBT" ? "BTC" : b; };

/** Résultat en R au prix donné (null si prix absent). */
export function rDe(p, price) {
  const r = risqueDe(p);
  return price > 0 && r > 0 ? (sens(p) * (price - entreeDe(p))) / r : null;
}
/** Ce que donnerait une sortie au stop actuel, en R (négatif = perte, positif = gain conservé). */
export const rAuStop = (p) => { const r = risqueDe(p); return r > 0 ? (sens(p) * (+p.stop_current - entreeDe(p))) / r : null; };

export function joursDepuis(day, now = Date.now()) {
  const t = Date.parse(`${day}T00:00:00Z`);
  return isFinite(t) ? Math.floor((now - t) / 864e5) : null;
}

/** Fenêtre d'entrée : le jour qui suit le signal et le suivant (après, on ne prend plus le train en marche). */
export const entreeOuverte = (p, now = Date.now()) => p.status === "ouvert" && (joursDepuis(p.signal_date, now) ?? 99) <= 2;

export function etatSwing(p, price, now = Date.now()) {
  if (p.status === "refuse") return { code: "refuse", ton: "", icone: "⏸", titre: "Pas pris : risque du club déjà engagé", texte: p.refus || "Règle du club : 2 % de risque ouvert au maximum." };
  if (p.status === "clos") {
    const r = +p.r;
    return { code: "clos", ton: r > 0 ? "long" : "short", icone: r > 0 ? "🏁" : "❌", titre: `Terminé : ${rr(r)}`,
      texte: `Sortie au stop vers ${pq(p.exit_price, p.quote)}${p.days != null ? ` après ${p.days} jour${p.days > 1 ? "s" : ""}` : ""}.` };
  }
  if (!(price > 0)) return { code: "nodata", ton: "", icone: "📡", titre: "Prix en direct indisponible", texte: `Stop actuel : ${pq(p.stop_current, p.quote)}.` };
  const s = sens(p);
  if (s * (price - +p.stop_current) <= 0) return { code: "stop", ton: "short", icone: "❌", titre: "Au stop", texte: `Le prix touche le stop (${pq(p.stop_current, p.quote)}) : la position se ferme.` };
  if (entreeOuverte(p, now)) {
    const lo = +p.entry_low, hi = +p.entry_high;
    if (price >= lo && price <= hi) {
      return { code: "entrer", ton: "long", icone: "🟢", titre: "C'est le moment d'entrer",
        texte: `${isLong(p) ? "Achète" : "Vends"} entre ${pq(lo, p.quote)} et ${pq(hi, p.quote)}, stop à ${pq(p.stop_current, p.quote)}. Pas d'objectif fixe : le stop suit la tendance.` };
    }
    if (s * (price - (isLong(p) ? hi : lo)) > 0) {
      return { code: "loin", ton: "ambre", icone: "⏳", titre: `Prix déjà ${isLong(p) ? "au-dessus" : "en dessous"} de la zone`,
        texte: `N'${isLong(p) ? "achète" : "entre"} pas ${isLong(p) ? "plus haut" : "plus bas"} que ${pq(isLong(p) ? hi : lo, p.quote)} : on ne court pas après. Si le prix revient dans la zone avant demain soir, c'est bon.` };
    }
    return { code: "proche", ton: "ambre", icone: "⚠️", titre: "Prix sous la zone, plus près du stop",
      texte: "Encore valable. Calcule la taille ici : ta perte au stop reste ton 1 %." };
  }
  const now_r = rDe(p, price), stop_r = rAuStop(p);
  return { code: "encours", ton: now_r >= 0 ? "long" : "short", icone: now_r >= 0 ? "📈" : "📉", titre: `En cours : ${rr(now_r)}`,
    texte: `Stop actuel ${pq(p.stop_current, p.quote)} : au stop, tu sortirais vers ${rr(stop_r)}. Le bot le remonte chaque matin (message Telegram).` };
}

/** Confiance 1/4…4/4 calculée par le bot au signal (cassure 55 j, tendance de fond, BTC porteur). */
export const palierDe = (p) => +(p.history || [])[0]?.palier || null;
export function confiance(p) {
  const k = palierDe(p);
  return k ? `<span class="pastille ${k >= 3 ? "long" : k === 2 ? "ambre" : ""}" title="Hors échantillon : 1/4 ≈ −0,2 R, 2/4 ≈ +0,4 R, 3/4 et 4/4 ≈ +1,3 R par trade">Confiance ${k}/4</span>` : "";
}

export function swingCard(p, price, now = Date.now()) {
  const e = etatSwing(p, price, now);
  return `<article class="bloc swing-carte" data-swing="${esc(p.id)}">
    <div class="ligne entre"><div><b class="${isLong(p) ? "gain" : "perte"}">${isLong(p) ? "LONG ↑" : "SHORT ↓"}</b> <b>${esc(nomSwing(p))}</b>
      <span class="small muted">· swing</span></div>
      <span class="pastille ${e.ton}">${e.icone} ${esc(e.titre)}</span></div>
    <p class="small" style="margin:8px 0">${confiance(p)} ${e.texte}</p>
    <div class="small muted">Entrée ${pq(entreeDe(p), p.quote)} · stop ${pq(p.stop_current, p.quote)}${p.days != null ? ` · ${p.days} j` : ""}
      ${p.demo ? " · <b>DÉMO</b>" : ""} · <a href="#/swing/${esc(p.id)}">détails →</a></div>
  </article>`;
}

/** Bloc « backtest swing » : on affiche le rapport du bot tel quel, rien n'est recalculé ici. */
export function swingBacktestBlock(run) {
  const r = run?.report;
  if (!r || !r.par_classe) {
    return `<div class="vide"><strong>Pas encore de backtest swing</strong>Sans preuve sur des années de données, le bot ne propose aucune position swing.</div>`;
  }
  const NOM = { crypto: "Cryptos", xstock: "Actions", commodity: "Matières premières" };
  const lignes = Object.entries(r.par_classe).map(([cls, c]) => {
    const o = c.walk_forward?.oos || {}, s = c.stats_variante || {};
    const ans = Object.entries(c.par_annee || {}).map(([y, st]) => `<span class="pastille ${+st.expectancy_r > 0 ? "long" : "short"}">${y} : ${rr(+st.expectancy_r)}</span>`).join(" ");
    return `<div class="bloc pile"><h3>${esc(NOM[cls] || cls)} ${c.prouve ? "🟢 prouvé" : "🚫 pas prouvé"}</h3>
      <p class="small">${esc(c.variante_retenue ? (c.variante_retenue.includes("55") ? "Cassure du plus haut de 55 jours" : "Cassure du plus haut de 20 jours") : "—")}
        ${c.variante_retenue?.endsWith("|long") ? " · LONG seulement" : ""} : <b>${s.n || 0} trades</b>, ${rr(+s.expectancy_r || 0)} par trade,
        durée moyenne ${s.jours_moyens ?? "—"} jours.</p>
      <p class="small">Sur des périodes jamais vues : <b>${o.n || 0} trades, ${rr(+o.expectancy_r || 0)}</b> par trade.</p>
      <div class="ligne small">${ans}</div></div>`;
  }).join("");
  return `${r.etude ? '<p class="small muted">🔬 Étude (pas utilisée pour donner des positions).</p>' : ""}
    <p class="small muted">${esc(r.periode || "")} · ${Object.keys(r.instruments || {}).length} perpétuels Kraken · frais, glissement et funding compris
      (funding connu sur une partie de l'historique seulement). Un résultat passé est une mesure, pas une promesse.</p>
    <div class="grille">${lignes}</div>`;
}
