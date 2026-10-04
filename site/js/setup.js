// Carte « setup » expliquée pour débutants : où en est le prix, scénario du bot, combien on risque / peut gagner.
// Logique pure (testée dans tests/setup.test.mjs) + HTML de la carte. Le graphique en direct est dans live.js.
import { getMode, hasPerp, krakenFees, nomActif, perpSymbol, venueEffective } from "./fees.js";
import { liqFraction } from "./sizing.js";
import { STRAT, ago, esc, eur, pct, pq } from "./ui.js";

const BAR = 900; // bougies de 15 minutes
const CLASSE = { crypto: "Crypto", xstock: "Action (xStock)", commodity: "Matière première" };

export const base = (s) => nomActif(s);
const isLong = (s) => s.direction === "LONG";

/** Minutes avant la clôture de la bougie 15 min en cours. */
export const minutesToClose = (now = Date.now()) => 15 - Math.floor((now / 60000) % 15);

/**
 * Où en est le prix par rapport au plan du bot ?
 * Retourne { code, ton, icone, titre, texte } — uniquement à partir de vrais prix (jamais inventés).
 * candles : bougies 15 min [t, o, h, l, c] (la dernière est en cours, l'avant-dernière est la dernière fermée).
 */
/**
 * Ce que le prix a DÉJÀ touché depuis la détection, d'après les vraies bougies 15 min (après la bougie de détection).
 * Retourne { hit: "sl" | "tp1" | "tp2" | "tp3" | null, tpAvant (objectifs touchés avant le stop), entered }.
 * Si une même bougie touche le stop et un objectif, on compte le stop (on ne peut pas savoir lequel est venu en premier).
 */
export function touches(s, candles = []) {
  const created = new Date(s.created_at).getTime();
  if (!candles?.length || !isFinite(created)) return { hit: null, tpAvant: 0, entered: s.status === "TRADE" };
  const t0 = Math.floor(created / 1000 / BAR) * BAR + BAR;
  const L = isLong(s), lo = +s.entry_low, hi = +s.entry_high, sl = +s.sl;
  const tps = [+s.tp1, +s.tp2, +s.tp3];
  let entered = s.status === "TRADE", best = 0;
  for (const k of candles) {
    if (+k[0] < t0) continue;
    const h = +k[2], l = +k[3];
    if (!entered && l <= hi && h >= lo) entered = true;
    if (L ? l <= sl : h >= sl) return { hit: "sl", tpAvant: best, entered };
    while (best < 3 && isFinite(tps[best]) && (L ? h >= tps[best] : l <= tps[best])) best++;
    if (best === 3) break;
  }
  return { hit: best ? `tp${best}` : null, tpAvant: best, entered };
}

/** Stop minimal (% du prix), comme le bot (min_sl_pct) : en dessous, le setup n'est pas jouable. */
export const STOP_MIN_PCT = 0.5;
/** Phases « terminées » : on n'y entre plus (stop, objectif, parti sans nous, expiré, stop trop serré). */
export const FINI = ["stop", "tp", "parti", "expire", "serre", "annule", "refuse"];

export function phase(s, price, { candles = [], now = Date.now() } = {}) {
  const lo = +s.entry_low, hi = +s.entry_high, sl = +s.sl, tp1 = +s.tp1;
  const L = isLong(s);
  const watch = s.status === "WATCH";
  if (s.revuSans) {
    return { code: "annule", ton: "", icone: "🔎", titre: "Revérifié : setup abandonné",
      texte: `À ${new Date(s.revuSans).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}, le bot a revérifié cette paire et ne garde plus ce setup. N'entre pas.` };
  }
  const t = touches(s, candles);
  if (t.hit === "sl") {
    return { code: "stop", ton: "short", icone: "❌", titre: "SL touché",
      texte: t.entered ? `Le prix a touché le stop (${pq(sl, s.quote)})${t.tpAvant ? ` après l'objectif ${t.tpAvant}` : ""}. Si tu étais dans le trade, il est coupé. On n'y entre plus.`
        : `Le prix a touché le stop (${pq(sl, s.quote)}) avant de confirmer l'entrée : scénario annulé, on n'y entre plus.` };
  }
  if (t.hit) {
    const n = +t.hit.slice(2);
    if (t.entered && !watch) {
      return { code: "tp", ton: "long", icone: "🎯", titre: `TP${n} touché`, tp: n,
        texte: n === 3 ? "Objectif 3 atteint : le plan est terminé. Trop tard pour entrer maintenant."
          : `Objectif ${n} atteint. Si tu es dans le trade : encaisse ${n === 1 ? "30" : "40"} % et remonte ton stop (au prix d'entrée si le graphique confirme). Trop tard pour entrer maintenant.` };
    }
    return { code: "parti", ton: "", icone: "🏃", titre: `TP${n} touché sans nous`, tp: n,
      texte: "Le prix a atteint l'objectif avant que l'entrée soit confirmée. On ne court jamais après un mouvement." };
  }
  // Gain visé trop faible pour le risque (le bot l'a refusé) : ce n'est pas un setup jouable, même s'il apparaît encore.
  const rr2 = Array.isArray(s.rr) && s.rr.length ? +s.rr[Math.min(1, s.rr.length - 1)] : null;
  if ((rr2 != null && rr2 < 1) || (s.warnings || []).some((w) => /mauvais ratio R:R/.test(w || ""))) {
    return { code: "refuse", ton: "short", icone: "🚫", titre: "Refusé : gain trop faible pour le risque",
      texte: `Le stop est plus loin que les objectifs${rr2 != null ? ` (TP2 = ${String(+rr2.toFixed(2)).replace(".", ",")} fois le risque)` : ""} : tu risquerais plus que ce que tu peux gagner. Le bot ne le valide pas : n'entre pas.` };
  }
  const eRef = L ? hi : lo; // entrée la moins bonne de la zone
  const slPct = eRef > 0 && sl > 0 ? (Math.abs(eRef - sl) / eRef) * 100 : null;
  if (slPct != null && slPct < STOP_MIN_PCT) {
    return { code: "serre", ton: "short", icone: "🚫", titre: "Stop trop serré : ne pas prendre",
      texte: `Le stop n'est qu'à ${pct(slPct, 2)} de l'entrée : une simple mèche le touche et les frais mangent le reste. Le bot ne propose plus ce genre de setup (stop minimum ${String(STOP_MIN_PCT).replace(".", ",")} %) : attends le prochain scan.` };
  }
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
    return { code: "stop", ton: "short", icone: "❌", titre: "SL touché",
      texte: `Le prix est au stop (${pq(sl, s.quote)}). Si tu étais dans le trade, il est coupé. On n'y entre plus.` };
  }
  if (L ? price >= tp1 : price <= tp1) {
    if (!watch) return { code: "tp", ton: "long", icone: "🎯", titre: "TP1 touché", tp: 1,
      texte: "Objectif 1 atteint. Si tu es dans le trade : encaisse 30 % et remonte ton stop si le graphique confirme. Trop tard pour entrer maintenant." };
    return { code: "parti", ton: "", icone: "🏃", titre: "TP1 touché sans nous", tp: 1,
      texte: "Le prix a déjà atteint l'objectif 1 sans confirmation d'entrée. On ne court jamais après un mouvement." };
  }
  if (price >= lo && price <= hi) {
    if (!watch) {
      return { code: "go", ton: "long", icone: "✅", titre: "C'est le moment",
        texte: `Le prix est dans la zone d'entrée. Le bot a déjà vu la confirmation : tu peux ${L ? "acheter" : "vendre"} avec un ordre limite dans la zone.` };
    }
    const closed = candles.length >= 2 ? +candles.at(-2)[4] : null;
    const zoneTrigger = /zone/i.test(s.trigger_text || "");
    if (zoneTrigger && closed != null && closed >= lo && closed <= hi) {
      // Le scan qui a produit ce setup est-il postérieur à la clôture de cette bougie ? Alors le bot a déjà revérifié
      // avec cette bougie et ne l'a pas validé : on ne redemande pas de scanner, on dit pourquoi.
      const finBougie = (+candles.at(-2)[0] + BAR) * 1000;
      const scanAt = new Date(s.created_at).getTime();
      if (isFinite(scanAt) && scanAt >= finBougie) {
        const raison = (s.warnings || []).find((w) => w && !/DÉMO/.test(w)) || s.trigger_text || "une des vérifications (volume, structure, frais ou risque) n'est pas passée";
        return { code: "revu", ton: "ambre", icone: "🔎", titre: "Revérifié par le bot : pas encore validé",
          texte: `Au scan de ${new Date(scanAt).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}, le bot a vu cette bougie mais n'a pas validé le trade. Raison : ${raison}. Inutile de relancer tout de suite : attends le prochain scan automatique ou une nouvelle bougie.` };
      }
      return { code: "condition", ton: "long", icone: "✅", titre: "Condition remplie", verif: s.instrument_key,
        texte: "La dernière bougie 15 min a clôturé dans la zone. Touche « Vérifier maintenant » : le bot revérifie seulement cette paire (volume, structure, risque) en 1 à 3 minutes." };
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
    const d = dist(target), ecart = Math.abs(target - price);
    // Écart minuscule : on l'écrit en prix (« il manque 0,1 $ ») plutôt qu'un « 0 % » arrondi qui ne veut rien dire.
    const combien = d < 0.05 ? `${pq(ecart, s.quote)} (${pct(d, 3)})` : pct(d, 2);
    return { code: "attendre", ton: "ambre", icone: "⏳", titre: d < 0.05 ? "Presque dans la zone" : watch ? "Attendre" : "Attendre le retour", dist: d,
      texte: `Le prix doit encore ${verbe} de ${combien} pour revenir dans la zone jaune.${d < 0.05 ? " Il y est presque : garde l'œil dessus." : ""} ${watch ? "" : "N'entre pas plus loin : tu risquerais plus pour gagner moins."}`.trim() };
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

/** Mouvement de prix (en %) qui liquide une position isolée à ce levier (règles Kraken, voir liqFraction dans sizing.js). */
const liqPctOf = (s, lev, maxLev = 10) => {
  const v = venueEffective(s);
  // Paire du bot tradée sur son perpétuel : la marge de maintenance est celle du perpétuel (x10 max en Europe),
  // pas celle de la paire spot (ex. levier spot max x3 → maintenance faussement énorme → « liquidé » à tort).
  const m = v === "futures" && s.venue !== "futures" ? 10 : maxLev;
  return liqFraction(lev, v, m) * 100;
};
/** Mise de référence pour le levier conseillé : 25 % du solde. */
export const MISE_REF = 25;

/** Écarts du plan en % du prix d'entrée (milieu de zone) + frais Kraken du marché (en %). */
export function ecarts(s) {
  const e = (+s.entry_low + +s.entry_high) / 2;
  const d = (x) => (x == null || !isFinite(+x) || !(e > 0) ? null : (Math.abs(+x - e) / e) * 100);
  const f = krakenFees(s);
  return { slPct: d(s.sl), tpPct: [d(s.tp1), d(s.tp2), d(s.tp3)], maker: f.maker, taker: f.taker };
}

/**
 * Levier conseillé pour un setup (choisi APRÈS le stop, jamais pour risquer plus) :
 * - assez petit pour que la liquidation reste au moins 2× plus loin que le stop ;
 * - avec une mise de 25 % du solde, la perte au stop ≈ ton risque par trade (1 % par défaut) ;
 * - SHORT en spot : x2 minimum (Kraken l'exige) ; jamais plus que le maximum Kraken de la paire, ni x10.
 * Retourne { lev, misePct (mise qui donne exactement ton risque à ce levier), liqPct, slPct, note }.
 */
export function levierConseille(s, me = {}, maxLev = 10) {
  const { slPct, maker, taker } = ecarts(s);
  const cap = s.venue !== "futures" && venueEffective(s) === "futures" ? 10 : Math.max(1, Math.min(10, +maxLev || 10)); // paire spot tradée sur son perpétuel : x10 (EEE)
  const minLev = !isLong(s) && venueEffective(s) === "spot" ? Math.min(2, cap) : 1;
  if (!(slPct > 0)) return { lev: minLev, misePct: null, liqPct: liqPctOf(s, minLev, maxLev), slPct: null, note: "stop manquant" };
  const perte = slPct + maker + taker; // % de la position perdu au stop, frais compris
  let sur = cap; // plus grand levier qui garde la liquidation au moins 2× plus loin que le stop
  while (sur > 1 && liqPctOf(s, sur, maxLev) < 2 * slPct) sur--;
  const risk = +me.risk_pct || 1;
  const vise = Math.round(risk / ((MISE_REF / 100) * perte));
  const lev = Math.max(minLev, Math.min(cap, sur, Math.max(1, vise)));
  const misePct = (risk / (lev * perte)) * 100;
  return { lev, misePct, liqPct: liqPctOf(s, lev, maxLev), slPct, note: lev < vise ? "plafonné pour garder la liquidation loin du stop" : "" };
}

/**
 * Résultat en % de la MISE (l'argent bloqué sur le trade) pour un levier donné, frais Kraken compris
 * (entrée en ordre limite, sortie au stop au marché, objectifs en ordres limite). TP encaissés 30 / 40 / 30 %.
 * Si la liquidation arrive avant le stop, la perte est toute la mise.
 */
export function scenario(s, lev, maxLev = 10) {
  const { slPct, tpPct, maker, taker } = ecarts(s);
  if (!(slPct > 0)) return null;
  const liqPct = liqPctOf(s, lev, maxLev);
  const liqAvant = liqPct <= slPct;
  const perte = liqAvant ? 100 : Math.min(100, lev * (slPct + maker + taker));
  const ok = tpPct.every((x) => x != null);
  const tp1 = tpPct[0] != null ? lev * 0.3 * (tpPct[0] - 2 * maker) : null;
  const tout = ok ? lev * (0.3 * tpPct[0] + 0.4 * tpPct[1] + 0.3 * tpPct[2] - 2 * maker) : null;
  return { lev, perte, tp1, tout, liqPct, liqAvant };
}

/** Score à partir duquel un setup est classé « plus solide » (confiance du bot, 0–100). */
export const SEUIL_SOLIDE = 75;
/** Prix à moins de ce pourcentage de la zone = imminent. */
export const PROCHE_PCT = 0.5;

/**
 * Dans quel espace de l'accueil ranger la carte ?
 * imminent : à ouvrir maintenant / très bientôt · solide / fragile : selon la confiance du bot · fini : raté, trop tard, expiré.
 * ph = résultat de phase() (null tant que le prix n'est pas lu).
 */
export function espace(s, ph) {
  if (ph && FINI.includes(ph.code)) return "fini";
  if (ph && (["go", "condition", "zone"].includes(ph.code) || (ph.code === "attendre" && ph.dist != null && ph.dist <= PROCHE_PCT))) return "imminent";
  const net = scenario(s, 1);
  if (net && net.tout != null && net.tout <= 0) return "fragile"; // les frais Kraken mangent le gain : jamais dans « plus solides »
  return +s.score >= SEUIL_SOLIDE ? "solide" : "fragile";
}

/** Ordre dans un espace : validés avant « à surveiller », puis confiance décroissante. */
export const ordre = (a, b) => (a.status === "TRADE" ? 0 : 1) - (b.status === "TRADE" ? 0 : 1) || +b.score - +a.score;

export function confiance(s) {
  const v = Math.max(0, Math.min(100, Math.round(+s.score || 0)));
  const mot = v >= 85 ? "très forte" : v >= SEUIL_SOLIDE ? "forte" : v >= 65 ? "moyenne" : "faible";
  return `<div class="confiance" title="Confiance du bot : plus le score est haut, plus il y a de signaux d'accord. Ce n'est jamais une garantie.">
    <span class="small muted">Confiance du bot</span>
    <span class="jauge"><i style="width:${v}%"></i></span>
    <b class="small">${v}/100 · ${mot}</b></div>`;
}

export function idee(s) {
  const L = isLong(s);
  return `Le bot pense que <b>${esc(base(s))}</b> peut <b class="${L ? "gain" : "perte"}">${L ? "monter" : "baisser"}</b>.
    Son plan : ${L ? "acheter" : "vendre"} entre <b class="num">${pq(+s.entry_low, s.quote)}</b> et <b class="num">${pq(+s.entry_high, s.quote)}</b>.`;
}

// Vérifications express demandées depuis cette page (paire → heure de la demande), pour afficher « en cours ».
const VERIFS = new Map();
const VERIF_MAX = 6 * 60_000;

export function phaseHtml(ph) {
  const enCours = ph.verif && Date.now() - (VERIFS.get(ph.verif) || 0) < VERIF_MAX;
  const bouton = !ph.verif ? "" : enCours
    ? `<p class="small"><b>⏳ Vérification en cours</b> (lancée à ${new Date(VERIFS.get(ph.verif)).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}) : la page se met à jour toute seule.</p>`
    : `<p><button type="button" class="btn principal mini" data-verif="${esc(ph.verif)}">⚡ Vérifier maintenant</button></p>`;
  return `<span class="feu-icone" aria-hidden="true">${ph.icone}</span><div><strong>${esc(ph.titre)}</strong><p>${esc(ph.texte)}</p>${bouton}</div>`;
}

// Bouton « Vérifier maintenant » : le bot réanalyse seulement cette paire, puis la page se recharge à l'arrivée du résultat.
if (typeof document !== "undefined") {
  document.addEventListener("click", async (e) => {
    const b = e.target.closest?.("[data-verif]");
    if (!b || b.disabled) return;
    const cle = b.dataset.verif;
    b.disabled = true;
    const { backend } = await import("./data.js");
    const { toast } = await import("./ui.js");
    const depart = new Date().toISOString();
    try {
      toast(await backend.requestScan("cible", cle));
    } catch (err) {
      b.disabled = false;
      toast(err.message, true);
      return;
    }
    VERIFS.set(cle, Date.now());
    b.closest("p").innerHTML = "<b>⏳ Vérification en cours</b> : la page se met à jour toute seule.";
    const fin = Date.now() + VERIF_MAX;
    const attendre = async () => {
      if (Date.now() > fin) { VERIFS.delete(cle); toast("La vérification prend plus de temps que prévu (GitHub est lent). Recharge la page dans quelques minutes.", true); return; }
      const arrives = await backend.cibleScans(depart).catch(() => []);
      if (arrives.length) {
        VERIFS.delete(cle);
        toast("✅ Vérification terminée : résultat du bot affiché.");
        if (location.hash.startsWith("#/signal/")) location.hash = "#/"; // le résultat est un nouveau signal : direction l'accueil
        else window.dispatchEvent(new HashChangeEvent("hashchange"));
        return;
      }
      setTimeout(attendre, 20_000);
    };
    setTimeout(attendre, 30_000);
  });
}

const chiffre = (label, val, cl, aide) =>
  `<div><dt>${label}</dt><dd class="num ${cl}">${val}</dd>${aide ? `<span class="small muted">${aide}</span>` : ""}</div>`;
const p1 = (x) => (x == null || !isFinite(x) ? "—" : x.toLocaleString("fr-FR", { maximumFractionDigits: Math.abs(x) < 10 ? 1 : 0 }) + " %");
/** Pourcentage signé (+1,2 % / −0,7 %), jamais « +- ». */
const ps = (x) => (x == null || !isFinite(x) ? "—" : (x >= 0 ? "+" : "−") + p1(Math.abs(x)));
const ton = (x) => (x == null ? "" : x >= 0 ? "gain" : "perte");

/** Levier conseillé, bien visible (carte d'accueil et page du signal). */
/** Où passer l'ordre sur Kraken : le perpétuel (onglet Futures) ou le spot si aucun perpétuel n'existe. */
export function ouTrader(s) {
  if (venueEffective(s) === "futures") return `<p class="small">📍 Sur Kraken : onglet <b>Futures</b> → <b>${esc(perpSymbol(s) || s.display)}</b></p>`;
  if (getMode() === "futures" && s.asset_class !== "xstock" && !hasPerp(s)) {
    return `<p class="alerte small">📍 <b>Pas de futures perpétuel Kraken pour ${esc(base(s))}</b> : ce trade se fait en <b>spot</b> (cherche ${esc(s.display)}),
      frais spot (0,40 % / 0,80 %) et ${isLong(s) ? "levier limité" : "short seulement si Kraken propose la marge sur cette paire"}.</p>`;
  }
  return `<p class="small">📍 Sur Kraken : marché <b>spot</b> → <b>${esc(s.display)}</b></p>`;
}

export function levierBadge(s, me, maxLev) {
  const c = levierConseille(s, me, maxLev);
  return `${ouTrader(s)}<div class="levier-conseil"><span>Levier conseillé</span><b class="num">x${c.lev}</b>
    <span class="small muted">${c.lev === 1 ? "sans effet de levier" : "marge isolée"} · liquidation ≈ ${p1(c.liqPct)} contre ${p1(c.slPct)} pour le stop</span></div>`;
}

/**
 * Bloc « si ça rate / objectif 1 / si tout réussit » en % de la mise, pour chaque levier (boutons x1, x2…).
 * Le levier conseillé est sélectionné ; toucher un autre levier montre l'effet sur les mêmes chiffres.
 */
export function chiffres(s, me, maxLev = 10) {
  const c = levierConseille(s, me, maxLev);
  const cap = s.venue !== "futures" && venueEffective(s) === "futures" ? 10 : Math.max(1, Math.min(10, +maxLev || 10)); // paire spot tradée sur son perpétuel : x10 (EEE)
  const minLev = !isLong(s) && venueEffective(s) === "spot" ? Math.min(2, cap) : 1;
  const levs = [...new Set([1, 2, 3, 5, 10, c.lev])].filter((l) => l >= minLev && l <= cap).sort((a, b) => a - b);
  const f = krakenFees(s);
  const vue = (l) => {
    const r = scenario(s, l, maxLev);
    if (!r) return `<p class="small muted" data-lev-vue="${l}" ${l === c.lev ? "" : "hidden"}>Stop manquant : calcul impossible.</p>`;
    const ex = (x) => (x == null ? "—" : eur((10 * x) / 100, true));
    return `<div data-lev-vue="${l}" ${l === c.lev ? "" : "hidden"}>
      <dl class="setup-chiffres">
        ${chiffre("Si ça rate", "−" + p1(r.perte), "perte", r.liqAvant ? "⚠ liquidé avant le stop" : "de ta mise, le stop coupe")}
        ${chiffre("Objectif 1", ps(r.tp1), ton(r.tp1), "de ta mise (30 % encaissés)")}
        ${chiffre("Si tout réussit", ps(r.tout), ton(r.tout), "de ta mise, après frais")}
      </dl>
      ${r.tout != null && r.tout <= 0 ? `<p class="alerte rouge small">⚠ <b>Les frais mangent tout le gain :</b> même si tous les objectifs sont atteints, ce trade perd de l'argent
        (frais Kraken ${esc(f.label)} : ${p1(f.maker)} par ordre limite, ${p1(f.taker)} au marché, sur la valeur de la position). Les objectifs sont trop proches.
        ${venueEffective(s) === "spot" ? "En futures perpétuels, les frais sont bien plus bas (0,02 % / 0,05 %)." : "À éviter."}</p>`
        : r.tp1 != null && r.tp1 <= 0 ? `<p class="alerte small">⚠ À l'objectif 1, les frais sont plus gros que le gain : seuls les objectifs 2 et 3 rapportent.</p>` : ""}
      <p class="small muted">Ex. avec 10 € de mise à x${l} (position de ${eur(10 * l)}) : ${ex(-r.perte)} · ${ex(r.tp1)} · ${ex(r.tout)}.
        ${l > 1 && !r.liqAvant ? ` À x${l}, ta position vaut ${l} fois ta mise : le stop à ${p1(ecarts(s).slPct)} du prix coûte donc ≈ ${p1(r.perte)} de ta mise (${l} × ${p1(ecarts(s).slPct)} + frais).` : ""}</p>
    </div>`;
  };
  return `<div class="lev-bloc">
    <div class="lev-choix" role="group" aria-label="Voir les chiffres avec un autre levier">
      ${levs.map((l) => `<button type="button" class="btn mini ${l === c.lev ? "actif" : "discret"}" data-lev-pick="${l}" aria-pressed="${l === c.lev}">x${l}${l === c.lev ? " ★" : ""}</button>`).join("")}
    </div>
    ${levs.map(vue).join("")}
    <p class="small muted">★ conseillé : avec une mise d'environ ${c.misePct ? p1(Math.min(100, c.misePct)) : "—"} de ton solde à x${c.lev},
      le stop te coûte ≈ ${p1(+me.risk_pct || 1)} du solde (ta règle).</p>
  </div>`;
}

// Boutons de levier des cartes : on affiche les chiffres du levier choisi (aucun calcul réseau).
if (typeof document !== "undefined") {
  document.addEventListener("click", (e) => {
    const b = e.target.closest?.("[data-lev-pick]");
    if (!b) return;
    const bloc = b.closest(".lev-bloc");
    bloc.querySelectorAll("[data-lev-pick]").forEach((x) => {
      const on = x === b;
      x.classList.toggle("actif", on); x.classList.toggle("discret", !on); x.setAttribute("aria-pressed", on);
    });
    bloc.querySelectorAll("[data-lev-vue]").forEach((v) => { v.hidden = v.dataset.levVue !== b.dataset.levPick; });
  });
}

/** Pastille d'état de la carte, mise à jour avec le prix (validé → SL touché / TP1 touché…). */
export function etat(s, ph) {
  if (ph?.code === "stop") return ["short", "❌ SL touché"];
  if (ph?.code === "tp") return ["long", `🎯 TP${ph.tp} touché`];
  if (ph?.code === "parti") return ["", "trop tard"];
  if (ph?.code === "expire") return ["", "expiré"];
  if (ph?.code === "annule") return ["", "abandonné"];
  if (ph?.code === "refuse" || ph?.code === "serre") return ["short", "🚫 refusé"];
  return s.status === "WATCH" ? ["ambre", "🟡 à surveiller"] : ["long", "🟢 validé"];
}

export function planTable(s, lev = null) {
  const e = (+s.entry_low + +s.entry_high) / 2;
  const d = (x) => (x == null ? "" : `<span>${(((+x - e) / e) * 100 > 0 ? "+" : "")}${(((+x - e) / e) * 100).toLocaleString("fr-FR", { maximumFractionDigits: 2 })} %</span>`);
  const rows = [
    ["Entrer", `${pq(+s.entry_low, s.quote)} – ${pq(+s.entry_high, s.quote)}`, "ordre limite dans la zone"],
    ...(lev ? [["Levier", `x${lev}`, lev === 1 ? "sans levier" : "marge isolée (conseillé)"]] : []),
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
export function setupCard(s, me, maxLev = 10) {
  const L = isLong(s);
  const watch = s.status === "WATCH";
  const [ek, et] = etat(s, s.expires_at && new Date(s.expires_at) < new Date() ? { code: "expire" } : null);
  return `<article class="setup ${L ? "long" : "short"}${watch ? " watch" : ""}" data-sig="${esc(s.id)}">
    <header class="setup-tete">
      <span class="sens-badge">${L ? "↑ LONG" : "↓ SHORT"}</span>
      <div class="setup-nom"><h3>${esc(s.display)}</h3>
        <span class="small muted">${esc(CLASSE[s.asset_class] || "")} · détecté ${ago(s.created_at)}${s.precedent ? " · scan précédent" : ""}</span></div>
      <span class="pastille ${ek}" data-etat>${et}</span>
    </header>
    ${confiance(s)}
    <p class="setup-idee">${idee(s)}</p>
    ${s.inverse ? `<p class="alerte small">⚠️ Au scan précédent, le bot voyait le sens <b>inverse</b> sur cette paire : marché indécis. Attends une confirmation nette, ou passe ton tour.</p>` : ""}
    <div class="feu" data-phase><span class="feu-icone">…</span><div><strong>Lecture du prix Kraken…</strong></div></div>
    <div class="setup-graph" data-chart aria-label="Graphique 15 minutes de ${esc(s.display)} avec le plan du bot"></div>
    ${LEGENDE}
    ${levierBadge(s, me, maxLev)}
    ${chiffres(s, me, maxLev)}
    <details class="plan"><summary>Le plan en détail</summary>${planTable(s, levierConseille(s, me, maxLev).lev)}
      ${watch && s.trigger_text ? `<p class="small"><b>Condition attendue :</b> ${esc(s.trigger_text)}</p>` : ""}
      <p class="small muted">Stratégie : ${esc(STRAT[s.strategy] || s.strategy)}.
      Le tracé pointillé montre le plan du bot, pas une prédiction : le marché peut faire autre chose.</p></details>
    <a class="btn ${watch ? "" : "principal"} pleine" href="#/signal/${esc(s.id)}">${watch ? "Préparer ce trade" : "Voir le trade et choisir ma quantité"}</a>
  </article>`;
}
