// Accueil : le verdict du dernier scan, les signaux, le risque disponible, les news.
import { backend } from "../data.js";
import { ladder } from "../ladder.js";
import { goLive } from "../live.js";
import { FINI, PROCHE_PCT, SEUIL_SOLIDE, espace, ordre, setupCard } from "../setup.js";
import { riskBudget } from "../sizing.js";
import { bilanCompte, soldeBloc, soldeLive } from "../solde.js";
import { STRAT, ago, busy, cls, dt, esc, eur, nextScan, pct, pq, px, sym, toast } from "../ui.js";

const VERDICT = {
  TRADE: (n) => [`${n} trade${n > 1 ? "s" : ""} validé${n > 1 ? "s" : ""}`, "Le bot a trouvé une occasion propre. Lis le ticket avant d'entrer."],
  WATCH: () => ["NO TRADE pour l'instant", "Des setups se forment, mais aucun n'a encore assez de confluence ou de preuve statistique pour un 🟢."],
  NONE: () => ["NO TRADE", "Aucun setup suffisamment robuste actuellement. Mieux vaut rater un trade que prendre un mauvais trade."],
  DATA: () => ["Données insuffisantes", "Kraken n'a pas répondu correctement. Aucun trade n'est proposé sans données fiables."],
};

export function ticket(s, me, { href = true } = {}) {
  const dir = s.direction === "LONG" ? "long" : "short";
  const expired = s.expires_at && new Date(s.expires_at) < new Date();
  const entry = s.direction === "LONG" ? s.entry_high : s.entry_low;
  const riskEur = (me.balance_eur * me.risk_pct) / 100;
  const tag = href ? "a" : "div";
  return `<${tag} class="ticket ${dir}${s.status === "WATCH" ? " watch" : ""}" ${href ? `href="#/signal/${s.id}"` : ""}>
    <div>
      <div class="ligne entre">
        <span class="sens">${s.direction === "LONG" ? "LONG ↑" : "SHORT ↓"}</span>
        ${s.status === "TRADE" ? (expired ? '<span class="pastille">expiré</span>' : s.grade === "A+" ? '<span class="pastille long">🔥 TRADE A+</span>' : '<span class="pastille long">🟢 validé</span>')
          : '<span class="pastille ambre">🟡 à surveiller</span>'}
      </div>
      <div class="actif">${esc(s.display)}</div>
      <div class="muted small">${esc(STRAT[s.strategy] || s.strategy)} · qualité ${Math.round(s.score)}/100${s.grade ? ` (${esc(s.grade)})` : ""} · ${ago(s.created_at)}</div>
      <dl>
        <dt>Entrée</dt><dd class="num">${px(s.entry_low)} – ${pq(s.entry_high, s.quote)}</dd>
        <dt>Stop (SL)</dt><dd class="num">${pq(s.sl, s.quote)}</dd>
        <dt>Objectif 1</dt><dd class="num">${pq(s.tp1, s.quote)}</dd>
        ${s.status === "TRADE" ? `<dt>Ton risque</dt><dd class="num">${eur(riskEur)} (${pct(+me.risk_pct)})</dd>` :
          `<dt>Il manque</dt><dd>${esc(s.trigger_text || (s.warnings || [])[0] || "une confirmation 15 min")}</dd>`}
      </dl>
    </div>
    ${ladder({ direction: s.direction, entryLow: s.entry_low, entryHigh: s.entry_high, sl: s.sl, tps: [s.tp1, s.tp2, s.tp3], compact: true })}
  </${tag}>`;
}

/** Une news : titre en français, ce que ça peut changer, puis les faits (titre original, source, heure). */
export function newsBlock(n) {
  const etat = n.is_rumor ? '<span class="pastille short">rumeur</span>' : n.verified ? '<span class="pastille long">vérifiée</span>' : '<span class="pastille">non vérifiée</span>';
  return `<details class="news"><summary><b>${esc(n.title_fr || n.title)}</b>
      <span class="small muted">· ${esc(n.source)} · ${ago(n.published_at || n.published)}</span> ${etat}
      ${n.impact_label && n.impact_label !== "—" ? `<span class="pastille ${n.impact_label === "fort" ? "ambre" : ""}">impact ${esc(n.impact_label)}</span>` : ""}</summary>
    ${n.explain ? `<p><b>Ce que ça peut changer :</b> ${esc(n.explain)}</p>` : ""}
    <p class="small muted"><b>Titre original (${esc(n.source)}) :</b> ${esc(n.title)}${n.title_fr ? "" : " <i>(traduction indisponible)</i>"}</p>
    ${n.interpretation ? `<p class="small muted"><b>Lecture du bot :</b> ${esc(n.interpretation)}</p>` : ""}
    ${n.url ? `<a href="${esc(n.url)}" target="_blank" rel="noopener">Lire la source</a>` : ""}</details>`;
}

// Scan demandé depuis le site : on garde l'heure de lancement même si on change de page.
let lancement = null; // { at: ms, apres: id du scan affiché au moment du clic }
const ATTENTE_MAX = 8 * 60_000; // au-delà, on prévient que GitHub est lent

export async function render(main, ctx) {
  const me = ctx.me;
  const [scans, mine, newIdeas, membres] = await Promise.all([backend.recentScans(2), backend.trades({ userId: me.id, limit: 300 }),
    me.is_admin ? backend.unseenIdeas().catch(() => 0) : Promise.resolve(0),
    me.is_admin ? backend.members().catch(() => []) : Promise.resolve([])]);
  const aValider = membres.filter((m) => !m.approved).length;
  const pseudos = membres.filter((m) => m.approved && m.pseudo_pending && m.id !== me.id).length;
  // Les 2 derniers scans : tout le dernier, plus les setups du précédent qui n'y sont plus (même paire + même sens = on garde le plus récent).
  const scan = scans[0] || null, prev = scans[1] || null;
  const [sigsNow, sigsPrev] = await Promise.all([scan ? backend.signalsOf(scan.id) : [], prev ? backend.signalsOf(prev.id).catch(() => []) : []]);
  // Une seule carte par paire : le scan le plus récent fait foi (jamais un LONG et un SHORT sur la même paire en même temps).
  const cle = (s) => s.instrument_key || s.display;
  const deja = new Set(sigsNow.map(cle));
  // Sens inversé par rapport au scan précédent sur la même paire : on le signale (marché indécis).
  const sensAvant = new Map(sigsPrev.map((s) => [cle(s), s.direction]));
  let sigs = [...sigsNow.map((s) => (sensAvant.has(cle(s)) && sensAvant.get(cle(s)) !== s.direction ? { ...s, inverse: true } : s)),
    ...sigsPrev.filter((s) => !deja.has(cle(s))).map((s) => ({ ...s, precedent: prev.created_at }))];
  // Vérifications express (bouton « Vérifier maintenant ») arrivées depuis le dernier scan : elles remplacent l'ancien setup de la paire.
  const cibles = scan ? await backend.cibleScans(scan.created_at).catch(() => []) : [];
  for (const c of cibles) {
    const neufs = (await backend.signalsOf(c.id).catch(() => [])).map((s) => ({ ...s, verifie: c.created_at }));
    const revus = new Set((c.opportunities || []).map((o) => o.display));
    const cles = new Set(neufs.map(cle));
    // La vérification remplace tout ce qu'on avait sur la paire (les deux sens) ; sans nouveau setup, l'ancien est abandonné.
    sigs = sigs.filter((s) => !cles.has(cle(s))).map((s) => (revus.has(s.display) && !s.verifie ? { ...s, revuSans: c.created_at } : s));
    sigs.push(...neufs);
  }
  // Levier maximum Kraken de chaque paire (pour le levier conseillé).
  const maxLev = new Map((await backend.instrumentsByKeys([...new Set(sigs.map((s) => s.instrument_key))]).catch(() => []))
    .map((i) => [i.key, +i.max_leverage || 1]));
  const trades = sigs.filter((s) => s.status === "TRADE");
  const watch = sigs.filter((s) => s.status === "WATCH");
  const budget = riskBudget(me, mine);
  const open = mine.filter((t) => t.status === "ouvert");
  const compte = bilanCompte(me, mine);
  const [titre, sous] = scan ? VERDICT[scan.verdict]?.(trades.length) || VERDICT.NONE() : ["Le bot n'a pas encore scanné", "Le premier scan automatique arrive vers " + nextScan() + ". Tu peux aussi le lancer maintenant."];
  const icon = scan?.verdict === "TRADE" ? "🟢" : ["WATCH", "NONE"].includes(scan?.verdict) ? "🟡" : "🛑";

  main.innerHTML = `
    ${aValider || pseudos ? `<a class="alerte lien-alerte" href="#/compte">👤 À valider :
      ${[aValider ? `<b>${aValider} nouveau${aValider > 1 ? "x" : ""} membre${aValider > 1 ? "s" : ""}</b>` : "", pseudos ? `<b>${pseudos} changement${pseudos > 1 ? "s" : ""} de pseudo</b>` : ""].filter(Boolean).join(" et ")} → Mon compte</a>` : ""}
    ${newIdeas ? `<a class="alerte lien-alerte" href="#/compte">💡 <b>${newIdeas} nouvelle${newIdeas > 1 ? "s" : ""} idée${newIdeas > 1 ? "s" : ""}</b> d'amélioration reçue${newIdeas > 1 ? "s" : ""} → Mon compte</a>` : ""}
    <section class="verdict">
      <img src="img/logo.svg" alt="">
      <div>
        <h1>💶 ${eur(compte.cash)} disponibles</h1>
        <p>Solde ${eur(compte.solde)}${compte.marge > 0.005 ? ` · ${eur(compte.marge)} bloqués dans tes trades` : ""} ·
          ${compte.enCours ? `<b>${compte.enCours} trade${compte.enCours > 1 ? "s" : ""} en cours</b> (${eur(compte.risque)} en jeu au stop)` : "aucun trade en cours"}</p>
        <div class="ligne bilan-compte">
          <span class="pastille ambre">⏳ ${compte.enCours} en cours</span>
          <span class="pastille long">🎯 TP1 ${compte.tp1}</span>
          <span class="pastille long">🎯 TP2 ${compte.tp2}</span>
          <span class="pastille long">🏆 TP3 ${compte.tp3}</span>
          <span class="pastille short">❌ SL ${compte.sl}</span>
          <span class="pastille">🛡 stop remonté ${compte.slProtege}</span>
          ${compte.liquidation ? `<span class="pastille short">💥 liquidé ${compte.liquidation}</span>` : ""}
          ${compte.autres ? `<span class="pastille">✋ fermé à la main ${compte.autres}</span>` : ""}
        </div>
        <p class="small">${compte.clos ? `${compte.clos} trade${compte.clos > 1 ? "s" : ""} terminé${compte.clos > 1 ? "s" : ""} · ${compte.gagnants} gagnant${compte.gagnants > 1 ? "s" : ""} · résultat <b class="${cls(compte.resultat)}">${eur(compte.resultat, true)}</b>` : "Aucun trade terminé pour l'instant."}
          <a href="#/trades">Mes trades →</a></p>
        <p class="small muted" id="verdict-bot">🤖 Bot : ${scan ? icon + " " : ""}<b id="verdict-titre">${esc(titre)}</b> · <span id="verdict-sous">${esc(sous)}</span><br>
          ${scan ? `Dernier scan ${ago(scan.created_at)} (${dt(scan.created_at)})${prev ? ` · précédent ${dt(prev.created_at).split(" ")[1] || dt(prev.created_at)}` : ""} · ` : ""}prochain vers ${nextScan()}</p>
      </div>
    </section>

    <dl class="chiffres">
      ${soldeBloc(me)}
      <div><dt>Résultat du jour</dt><dd class="num ${cls(budget.todayPnl)}">${eur(budget.todayPnl, true)}</dd></div>
    </dl>
    ${budget.dailyStop && me.guardrails === true ? `<div class="alerte rouge"><strong>Stop pour aujourd'hui.</strong> Tu as atteint ta perte maximale du jour
      (${pct(+me.max_daily_loss_pct)}). ${me.guardrails === false ? "Tes garde-fous sont coupés : rien n'est bloqué, mais c'est souvent le moment de faire une pause."
        : "Le site bloque les nouveaux trades jusqu'à demain."}</div>` : ""}

    <div id="scan-etat" aria-live="polite"></div>
    <div class="ligne" style="margin-top:16px">
      <button class="btn principal" id="scan-now">Scanner maintenant</button>
      <a class="btn" href="#/trade/nouveau">Trade manuel</a>
      ${open.length ? `<a class="btn discret" href="#/trades">${open.length} trade${open.length > 1 ? "s" : ""} en cours</a>` : ""}
    </div>

    ${sigs.length ? `
    <section class="section espace imminent" id="esp-imminent">
      <h2>⚡ Imminent</h2>
      <p class="muted">À ouvrir maintenant ou très bientôt : le prix est dans la zone d'entrée, ou à moins de ${String(PROCHE_PCT).replace(".", ",")} %.
        Garde l'app Kraken sous la main et lis le feu de la carte.</p>
      <div class="grille setups" data-esp="imminent"></div>
      <p class="vide-espace small muted" data-vide="imminent">Lecture des prix Kraken…</p>
    </section>
    <section class="section espace" id="esp-solide">
      <h2>💪 Les plus solides</h2>
      <p class="muted">Score qualité de ${SEUIL_SOLIDE}/100 ou plus : régime, tendances, structure, volume et gain/risque vont dans le même sens.
        Ça reste un pari : c'est le stop qui te protège.</p>
      <div class="grille setups" data-esp="solide"></div>
      <p class="vide-espace small muted" data-vide="solide">Aucun setup à forte confiance en attente.</p>
    </section>
    <section class="section espace" id="esp-fragile">
      <h2>Moins solides</h2>
      <p class="muted">Score qualité sous ${SEUIL_SOLIDE}/100 : pas assez de confluence pour un 🟢. À surveiller seulement.</p>
      <div class="grille setups" data-esp="fragile"></div>
      <p class="vide-espace small muted" data-vide="fragile">Aucun.</p>
    </section>
    <details class="section espace" id="esp-fini"><summary><h2 style="display:inline">Terminés : SL touché, objectif atteint ou expirés</h2>
      <span class="muted small" data-compte="fini"></span></summary>
      <p class="muted">Le prix a touché le stop, a déjà atteint un objectif, ou les niveaux sont trop anciens. On n'y entre plus
        (si tu es déjà dedans, suis ton trade dans « Mes trades »).</p>
      <div class="grille setups" data-esp="fini"></div>
    </details>
    <div id="cartes-attente" hidden>${[...sigs].sort(ordre).map((s) => setupCard(s, me, maxLev.get(s.instrument_key) ?? 10)).join("")}</div>` : ""}

    ${scan && !trades.length && (scan.reasons || []).length ? `<section class="section"><h2>Pourquoi pas de trade</h2>
      <div class="bloc"><ul>${scan.reasons.slice(0, 5).map((r) => `<li>${esc(r)}</li>`).join("")}</ul></div></section>` : ""}

    ${scan?.opportunities?.length ? `<section class="section"><div class="ligne entre"><h2 style="margin:0">Marchés analysés ce scan</h2>
      <a href="#/graphiques">Tous les graphiques Kraken Pro France →</a></div>
      <div class="ligne">${scan.opportunities.slice(0, 40).map((o) => {
        const k = o.state === "LONG" ? "long" : o.state === "SHORT" ? "short" : o.state.startsWith("SURV") ? "ambre" : "";
        return `<span class="pastille ${k}" title="score ${o.score ?? "—"}">${esc(o.display)} · ${esc(o.state === "WAIT" ? "attendre" : o.state.toLowerCase())}</span>`;
      }).join("")}</div></section>` : ""}

    ${scan?.news?.length ? `<section class="section"><h2>News importantes</h2>
      <p class="small muted">Titres traduits automatiquement. Le titre original et la source restent la référence.</p>
      ${scan.news.slice(0, 6).map(newsBlock).join("")}</section>` : ""}

    ${scan?.data_issues?.length ? `<section class="section"><details><summary>Problèmes de données au dernier scan (${scan.data_issues.length})</summary>
      <ul>${scan.data_issues.slice(0, 12).map((d) => `<li class="small">${esc(d)}</li>`).join("")}</ul></details></section>` : ""}
  `;

  // Verdict en haut : si les trades validés ont déjà touché leur stop ou un objectif, on le dit (au lieu de « 1 trade validé »).
  const phases = new Map();
  // Verdict en haut, mis à jour avec les vraies bougies : trades validés encore ouverts, sinon le bilan TP / SL touchés du scan.
  const titre0 = main.querySelector("#verdict-titre").textContent, sous0 = main.querySelector("#verdict-sous").textContent;
  const majVerdict = () => {
    const vus = sigs.filter((s) => phases.has(s.id));
    const code = (s) => phases.get(s.id).code;
    const tp = vus.filter((s) => code(s) === "tp").length; // « parti sans nous » n'est pas un gain : jamais entré
    const sl = vus.filter((s) => code(s) === "stop").length;
    const enJeu = vus.filter((s) => !FINI.includes(code(s))).length;
    const sansEntree = vus.filter((s) => ["parti", "expire", "serre"].includes(code(s))).length;
    const h1 = main.querySelector("#verdict-titre"), p = main.querySelector("#verdict-sous");
    const ouverts = trades.filter((s) => phases.has(s.id) && !FINI.includes(code(s)));
    if (ouverts.length) {
      h1.textContent = `${ouverts.length} trade${ouverts.length > 1 ? "s" : ""} validé${ouverts.length > 1 ? "s" : ""}`;
      p.textContent = sous0;
    } else if (tp || sl) {
      h1.textContent = [tp ? `${tp} setup${tp > 1 ? "s" : ""} au TP` : "", sl ? `${sl} setup${sl > 1 ? "s" : ""} au SL` : ""].filter(Boolean).join(" · ");
      p.textContent = `sur les ${sigs.length} setups ${prev ? "des 2 derniers scans" : "du dernier scan"}${enJeu ? `, ${enJeu} encore en jeu` : ""}${sansEntree ? `, ${sansEntree} sans entrée` : ""}`;
    } else {
      h1.textContent = titre0; p.textContent = sous0;
    }
  };

  // Rangement des cartes : par confiance d'abord, puis « imminent » / « fini » dès que le prix Kraken est lu.
  const where = new Map();
  const ranger = (s, ph) => {
    if (ph) { phases.set(s.id, ph); majVerdict(); }
    const card = main.querySelector(`[data-sig="${CSS.escape(String(s.id))}"]`);
    const esp = espace(s, ph);
    if (!card || where.get(s.id) === esp) return;
    where.set(s.id, esp);
    const box = main.querySelector(`[data-esp="${esp}"]`);
    const next = [...box.children].find((c) => ordre(s, sigs.find((x) => String(x.id) === c.dataset.sig) || s) < 0);
    box.insertBefore(card, next || null);
    for (const k of ["imminent", "solide", "fragile", "fini"]) {
      const n = main.querySelector(`[data-esp="${k}"]`).children.length;
      const vide = main.querySelector(`[data-vide="${k}"]`);
      if (vide) vide.hidden = n > 0;
      if (k === "fini") { main.querySelector("#esp-fini").hidden = n === 0; main.querySelector('[data-compte="fini"]').textContent = `(${n})`; }
      if (k === "fragile") main.querySelector("#esp-fragile").hidden = n === 0;
    }
    const vi = main.querySelector('[data-vide="imminent"]');
    if (ph && vi && vi.textContent.startsWith("Lecture")) vi.textContent = "Rien d'imminent : aucun prix n'est dans sa zone d'entrée pour l'instant. Le bot surveille.";
  };
  if (sigs.length) {
    sigs.forEach((s) => ranger(s, null));
    main.querySelector("#cartes-attente").remove();
    const stop = goLive(sigs.map((s) => {
      const card = main.querySelector(`[data-sig="${CSS.escape(String(s.id))}"]`);
      // Bougies chargées tout de suite (même hors écran) pour savoir si le SL ou un objectif a déjà été touché (bilan en haut).
      return { s, chartEl: card.querySelector("[data-chart]"), phaseEl: card.querySelector("[data-phase]"), etatEl: card.querySelector("[data-etat]"), eager: true };
    }), { onPhase: ranger, bars: 32 });
    ctx.onLeave(stop);
  }

  ctx.onLeave(soldeLive(main, me));
  // Suivi du scan : un scan dure en général 2 à 4 minutes (mise en route de GitHub + analyse).
  // On interroge la base toutes les 20 s et on affiche « Nouveau scan disponible » dès qu'il arrive (scan demandé ou scan horaire).
  const etat = main.querySelector("#scan-etat");
  const dureeAnalyse = scan?.duration_s ? Math.round(+scan.duration_s) : null;
  const dessinerEtat = (nouveau = null) => {
    if (nouveau) {
      etat.innerHTML = `<div class="alerte verte ligne entre"><span>✅ <b>Nouveau scan disponible</b> (${dt(nouveau.created_at)}).</span>
        <button class="btn principal mini" id="actualiser">Actualiser</button></div>`;
      etat.querySelector("#actualiser").addEventListener("click", () => { lancement = null; render(main, ctx); });
      return;
    }
    if (!lancement) { etat.innerHTML = ""; return; }
    const ecoule = Date.now() - lancement.at;
    const min = Math.floor(ecoule / 60000), sec = Math.floor((ecoule % 60000) / 1000);
    etat.innerHTML = ecoule < ATTENTE_MAX
      ? `<div class="alerte"><b>⏳ Scan en cours</b> depuis ${min ? `${min} min ` : ""}${sec} s. Il faut en général <b>2 à 4 minutes</b>
          (démarrage de GitHub ≈ 1 min${dureeAnalyse ? `, puis ≈ ${dureeAnalyse} s d'analyse au dernier scan` : ", puis l'analyse"}). Tu peux rester ici : un message apparaîtra.</div>`
      : `<div class="alerte rouge"><b>Le scan prend plus de temps que prévu</b> (${min} min). GitHub est peut-être lent ou en panne :
          réessaie dans quelques minutes, ou regarde l'onglet Actions sur GitHub. <button class="btn mini" id="actualiser">Actualiser</button></div>`;
    etat.querySelector("#actualiser")?.addEventListener("click", () => { lancement = null; render(main, ctx); });
  };
  const verifier = async () => {
    if (document.hidden) return;
    const dernier = await backend.latestScan().catch(() => null);
    if (dernier && scan && dernier.id !== scan.id) return dessinerEtat(dernier);
    if (dernier && !scan) return dessinerEtat(dernier);
    dessinerEtat();
  };
  dessinerEtat();
  const tTick = setInterval(() => { if (lancement && !etat.querySelector(".verte")) dessinerEtat(); }, 1000);
  const tPoll = setInterval(verifier, lancement ? 20_000 : 60_000);
  ctx.onLeave(() => { clearInterval(tTick); clearInterval(tPoll); });

  main.querySelector("#scan-now").addEventListener("click", (e) => busy(e.currentTarget, async () => {
    toast(await backend.requestScan());
    lancement = { at: Date.now() };
    dessinerEtat();
    clearInterval(tPoll);
    const t2 = setInterval(verifier, 20_000);
    ctx.onLeave(() => clearInterval(t2));
  }));
}
