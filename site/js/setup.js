// Carte « setup » expliquée pour débutants : où en est le prix, scénario du bot, combien on risque / peut gagner.
// Logique pure (testée dans tests/setup.test.mjs) + HTML de la carte. Le graphique en direct est dans live.js.
import { STRAT, ago, esc, eur, pct, pq } from "./ui.js";

const BAR = 900; // bougies de 15 minutes
const CLASSE = { crypto: "Crypto", xstock: "Action (xStock)", commodity: "Matière première" };

export const base = (s) => String(s.display || "").split("/")[0];
const isLong = (s) => s.direction === "LONG";

/** Minutes avant la clôture de la bougie 15 min en cours. */
export const minutesToClose = (now = Date.now()) => 15 - Math.floor((now / 60000) % 15);

/**
 * Où en est le prix par rapport au plan du bot ?
 * Retourne { code, ton, icone, titre, texte } — uniquement à partir de vrais prix (jamais inventés).
 * candles : bougies 15 min [t, o, h, l, c] (la dernière est en cours, l'avant-dernière est la dernière fermée).
 */
export function phase(s, price, { candles = [], now = Date.now() } = {}) {
  const lo = +s.entry_low, hi = +s.entry_high, sl = +s.sl, tp1 = +s.tp1;
  const L = isLong(s);
  const watch = s.status === "WATCH";
  if (s.expires_at && new Date(s.expires_at).getTime() < now) {
    return { code: "expire", ton: "", icone: "⌛", titre: "Expiré",
      texte: "Ces niveaux ont plus de 4 heures. N'entre pas : attends le prochain scan." };
  }
  if (price == null || !isFinite(price)) {
    return { code: "nodata", ton: "", icone: "📡", titre: "Prix en direct indisponible",
      texte: "Impossible de lire le prix Kraken pour l'instant. Pas de décision sans prix." };
  }
  const dist = (target) => Math.abs(target - price) / price * 100;
  if (L ? price <= sl : price >= sl) {
    return { code: "stop", ton: "short", icone: "❌", titre: "Annulé",
      texte: `Le prix a touché le stop (${pq(sl, s.quote)}). Le scénario est raté : on oublie ce trade.` };
  }
  if (L ? price >= tp1 : price <= tp1) {
    return { code: "parti", ton: "", icone: "🏃", titre: "Trop tard",
      texte: "Le prix a déjà atteint l'objectif 1 sans nous. On ne court jamais après un mouvement." };
  }
  if (price >= lo && price <= hi) {
    if (!watch) {
      return { code: "go", ton: "long", icone: "✅", titre: "C'est le moment",
        texte: `Le prix est dans la zone d'entrée. Le bot a déjà vu la confirmation : tu peux ${L ? "acheter" : "vendre"} avec un ordre limite dans la zone.` };
    }
    const closed = candles.length >= 2 ? +candles.at(-2)[4] : null;
    const zoneTrigger = /zone/i.test(s.trigger_text || "");
    if (zoneTrigger && closed != null && closed >= lo && closed <= hi) {
      return { code: "condition", ton: "long", icone: "✅", titre: "Condition remplie",
        texte: "La dernière bougie 15 min a clôturé dans la zone. Lance « Scanner maintenant » : le bot revérifie tout (volume, structure, risque) avant de valider." };
    }
    return { code: "zone", ton: "ambre", icone: "👀", titre: "Dans la zone, pas encore confirmé",
      texte: `Attends la clôture de la bougie 15 min (dans ${minutesToClose(now)} min). Il manque : ${s.trigger_text || "une confirmation 15 min"}.` };
  }
  // Hors zone, du « bon » côté (pas encore revenu) ou du côté du stop.
  const above = price > hi;
  const waitingSide = L ? above : !above;
  if (waitingSide) {
    const target = L ? hi : lo;
    const verbe = L ? "redescendre" : "remonter";
    return { code: "attendre", ton: "ambre", icone: "⏳", titre: watch ? "Attendre" : "Attendre le retour",
      texte: `Le prix doit encore ${verbe} de ${pct(dist(target), 2)} pour revenir dans la zone jaune. ${watch ? "" : "N'entre pas plus loin : tu risquerais plus pour gagner moins."}`.trim() };
  }
  return { code: "prudence", ton: "short", icone: "⚠️", titre: "Prudence",
    texte: `Le prix est passé de l'autre côté de la zone, près du stop (${pct(dist(sl), 2)}). Attends qu'il revienne dans la zone.` };
}

/**
 * Scénario dessiné sur le graphique (illustration du plan, PAS une prévision de timing) :
 * - ok : prix actuel → zone d'entrée → objectifs 1, 2, 3
 * - rate : entrée → stop
 * Un point par bougie de 15 min pour que l'échelle de temps reste régulière.
 */
export function projection(s, candles, price = null) {
  if (!candles?.length) return { ok: [], rate: [] };
  const t0 = +candles.at(-1)[0];
  const p0 = price ?? +candles.at(-1)[4];
  const lo = +s.entry_low, hi = +s.entry_high, mid = (lo + hi) / 2;
  const inZone = p0 >= lo && p0 <= hi;
  const L = isLong(s);
  const entry = inZone ? p0 : (L ? (p0 > hi ? hi : mid) : (p0 < lo ? lo : mid));
  const tEntry = inZone ? 0 : 3;
  const ways = [[0, p0], ...(tEntry ? [[tEntry, entry]] : []), [tEntry + 6, +s.tp1], [tEntry + 12, +s.tp2], [tEntry + 18, +s.tp3]]
    .filter(([, v]) => v != null && isFinite(v));
  const line = (pts) => {
    const out = [];
    for (let k = 1; k < pts.length; k++) {
      const [a, va] = pts[k - 1], [b, vb] = pts[k];
      for (let i = k === 1 ? 0 : 1; i <= b - a; i++) out.push({ time: t0 + (a + i) * BAR, value: va + (vb - va) * (i / (b - a)) });
    }
    return out;
  };
  return { ok: line(ways), rate: line([[tEntry, entry], [tEntry + 5, +s.sl]]) };
}

/** Combien on risque / peut gagner en € avec les réglages du membre (TP 30/40/30). */
export function gains(s, me) {
  const risk = ((+me.balance_eur || 0) * (+me.risk_pct || 0)) / 100;
  const net = Array.isArray(s.rr_net) && s.rr_net.length === 3;
  const r = (net ? s.rr_net : s.rr || []).map(Number);
  if (r.length < 3 || r.some((x) => !isFinite(x))) return { risk, tp1: null, all: null, net };
  return { risk, tp1: risk * r[0] * 0.3, all: risk * (0.3 * r[0] + 0.4 * r[1] + 0.3 * r[2]), net, r };
}

export function idee(s) {
  const L = isLong(s);
  return `Le bot pense que <b>${esc(base(s))}</b> peut <b class="${L ? "gain" : "perte"}">${L ? "monter" : "baisser"}</b>.
    Son plan : ${L ? "acheter" : "vendre"} entre <b class="num">${pq(+s.entry_low, s.quote)}</b> et <b class="num">${pq(+s.entry_high, s.quote)}</b>.`;
}

export function phaseHtml(ph) {
  return `<span class="feu-icone" aria-hidden="true">${ph.icone}</span><div><strong>${esc(ph.titre)}</strong><p>${esc(ph.texte)}</p></div>`;
}

const chiffre = (label, val, cl, aide) =>
  `<div><dt>${label}</dt><dd class="num ${cl}">${val}</dd>${aide ? `<span class="small muted">${aide}</span>` : ""}</div>`;

export function chiffres(s, me) {
  const g = gains(s, me);
  return `<dl class="setup-chiffres">
    ${chiffre("Si ça rate", g.risk ? "−" + eur(g.risk) : "—", "perte", "le stop coupe la perte")}
    ${chiffre("Objectif 1", g.tp1 != null ? "+" + eur(g.tp1) : "—", "gain", "30 % encaissés")}
    ${chiffre("Si tout réussit", g.all != null ? "+" + eur(g.all) : "—", "gain", g.net ? "après frais estimés" : "avant frais")}
  </dl>`;
}

export function planTable(s) {
  const e = (+s.entry_low + +s.entry_high) / 2;
  const d = (x) => (x == null ? "" : `<span>${(((+x - e) / e) * 100 > 0 ? "+" : "")}${(((+x - e) / e) * 100).toLocaleString("fr-FR", { maximumFractionDigits: 2 })} %</span>`);
  const rows = [
    ["Entrer", `${pq(+s.entry_low, s.quote)} – ${pq(+s.entry_high, s.quote)}`, "ordre limite dans la zone"],
    ["Stop", pq(+s.sl, s.quote), d(s.sl)],
    ["Objectif 1", pq(+s.tp1, s.quote), `${d(s.tp1)} · encaisser 30 %`],
    ["Objectif 2", pq(+s.tp2, s.quote), `${d(s.tp2)} · encaisser 40 %`],
    ["Objectif 3", pq(+s.tp3, s.quote), `${d(s.tp3)} · le reste`],
  ];
  return `<table class="plan-table"><tbody>${rows.map(([a, b, c]) =>
    `<tr><th>${a}</th><td><span class="num">${b}</span><br><span class="small muted">${c}</span></td></tr>`).join("")}</tbody></table>`;
}

export const LEGENDE = `<p class="legende small">
  <span><i class="k-zone"></i>zone d'entrée</span><span><i class="k-stop"></i>stop</span>
  <span><i class="k-obj"></i>objectifs</span><span><i class="k-ok"></i>scénario prévu</span><span><i class="k-rate"></i>si ça rate</span></p>`;

/** Carte complète (accueil). Le graphique et le feu sont remplis en direct par live.js. */
export function setupCard(s, me) {
  const L = isLong(s);
  const watch = s.status === "WATCH";
  const expired = s.expires_at && new Date(s.expires_at) < new Date();
  return `<article class="setup ${L ? "long" : "short"}${watch ? " watch" : ""}" data-sig="${esc(s.id)}">
    <header class="setup-tete">
      <span class="sens-badge">${L ? "↑ LONG" : "↓ SHORT"}</span>
      <div class="setup-nom"><h3>${esc(s.display)}</h3>
        <span class="small muted">${esc(CLASSE[s.asset_class] || "")} · détecté ${ago(s.created_at)}</span></div>
      ${watch ? '<span class="pastille ambre">🟡 à surveiller</span>' : expired ? '<span class="pastille">expiré</span>' : '<span class="pastille long">🟢 validé</span>'}
    </header>
    <p class="setup-idee">${idee(s)}</p>
    <div class="feu" data-phase><span class="feu-icone">…</span><div><strong>Lecture du prix Kraken…</strong></div></div>
    <div class="setup-graph" data-chart aria-label="Graphique 15 minutes de ${esc(s.display)} avec le plan du bot"></div>
    ${LEGENDE}
    ${chiffres(s, me)}
    <details class="plan"><summary>Le plan en détail</summary>${planTable(s)}
      ${watch && s.trigger_text ? `<p class="small"><b>Condition attendue :</b> ${esc(s.trigger_text)}</p>` : ""}
      <p class="small muted">Stratégie : ${esc(STRAT[s.strategy] || s.strategy)} · score ${Math.round(s.score)}/100.
      Le tracé pointillé montre le plan du bot, pas une prédiction : le marché peut faire autre chose.</p></details>
    <a class="btn ${watch ? "" : "principal"} pleine" href="#/signal/${esc(s.id)}">${watch ? "Préparer ce trade" : "Voir le trade et calculer ma taille"}</a>
  </article>`;
}
