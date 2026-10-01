// Solde qui bouge avec les trades.
// Le solde enregistré dans « Mon compte » est un point de départ (daté). À partir de là, chaque euro gagné ou perdu
// sur tes trades (frais d'entrée, TP encaissés, clôtures, stops — paper et réel) s'y ajoute automatiquement.
// Quand tu corriges ton solde dans « Mon compte » (dépôt, retrait, alignement sur Kraken), on repart de cette valeur.
import { pnlBreakdown } from "./sizing.js";
import { cls, dt, eur } from "./ui.js";

/**
 * me : profil (balance_eur = solde enregistré) ; trades : trades du membre ; since : date du dernier réglage du solde.
 * Seuls les trades ouverts depuis ce réglage comptent (les plus anciens sont déjà inclus dans le solde saisi).
 */
export function solde(me, trades, since) {
  const t0 = since ? new Date(since).getTime() : 0;
  const pris = (trades || []).filter((t) => t.status !== "annule" && new Date(t.opened_at).getTime() >= t0);
  const realise = pris.reduce((a, t) => a + (+t.realized_pnl_eur || 0), 0);
  const base = +(me.balance_base ?? me.balance_eur) || 0;
  return { base, realise, actuel: Math.max(0, base + realise), since, ouverts: pris.filter((t) => t.status === "ouvert") };
}

/** Gain ou perte EN COURS (pas encore encaissé) des trades ouverts, frais de sortie compris. null si aucun prix. */
export function enCours(ouverts, priceOf) {
  let tot = 0, ok = false;
  for (const t of ouverts) {
    const p = priceOf(t);
    const b = pnlBreakdown(t, p);
    if (b.move == null) continue;
    tot += b.move - b.exitFee;
    ok = true;
  }
  return ok ? tot : null;
}

/** Recalcule le solde du membre connecté (appelé à chaque page). Ne modifie rien dans la base. */
export async function majSolde(ctx, backend) {
  const me = ctx.me;
  if (!me) return;
  const [hist, trades] = await Promise.all([
    backend.balanceHistory(me.id).catch(() => []),
    backend.trades({ userId: me.id, limit: 500 }).catch(() => null),
  ]);
  if (!trades) return;
  if (me.balance_base == null) me.balance_base = +me.balance_eur;
  const s = solde(me, trades, hist[0]?.created_at || me.created_at);
  me.solde = s;
  me.balance_eur = +s.actuel.toFixed(2); // tout le site (risque, levier conseillé, garde-fous) utilise le solde à jour
}

/** Bloc « solde » de l'accueil et de Mes trades, avec le gain/perte en cours mis à jour toutes les 30 s. */
export function soldeBloc(me) {
  const s = me.solde;
  if (!s) return `<div><dt>Ton solde</dt><dd class="num">${eur(+me.balance_eur)}</dd></div>`;
  return `<div class="solde-bloc">
    <dt>Ton solde</dt><dd class="num solde-montant">${eur(s.actuel)}</dd>
    <span class="small ${cls(s.realise)}">${Math.abs(s.realise) >= 0.005 ? `${eur(s.realise, true)} depuis le ${dt(s.since).split(" ")[0]}` : "aucun gain ni perte encaissé depuis ton dernier réglage"}</span>
    ${s.ouverts.length ? `<span class="small" data-encours>trades en cours : lecture des prix…</span>` : ""}
  </div>`;
}

/** Met à jour « en direct » le bloc solde (prix Kraken toutes les 30 s). Retourne une fonction d'arrêt. */
export function soldeLive(root, me) {
  const el = root.querySelector("[data-encours]");
  const ouverts = me.solde?.ouverts || [];
  if (!el || !ouverts.length) return () => {};
  let stop = false;
  const tick = async () => {
    if (stop || document.hidden) return;
    const { prices } = await import("./market.js"); // import tardif : ce module reste testable hors navigateur
    const px = await prices(ouverts, { fx: false }).catch(() => null);
    if (stop || !px) return;
    const v = enCours(ouverts, (t) => px.get(t)?.last ?? null);
    if (v == null) { el.className = "small muted"; el.textContent = "trades en cours : prix indisponible"; return; }
    const direct = me.solde.actuel + v;
    el.className = `small ${cls(v)}`;
    el.innerHTML = `en direct avec ${ouverts.length > 1 ? `tes ${ouverts.length} trades` : "ton trade"} en cours : <b>${eur(direct)}</b> (${eur(v, true)} pas encore encaissés)`;
  };
  tick();
  const timer = setInterval(tick, 30_000);
  return () => { stop = true; clearInterval(timer); };
}
