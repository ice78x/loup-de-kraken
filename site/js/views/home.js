// Accueil : le verdict du dernier scan, les signaux, le risque disponible, les news.
import { backend } from "../data.js";
import { ladder } from "../ladder.js";
import { goLive } from "../live.js";
import { PROCHE_PCT, SEUIL_SOLIDE, espace, ordre, setupCard } from "../setup.js";
import { riskBudget } from "../sizing.js";
import { STRAT, ago, busy, cls, dt, esc, eur, nextScan, pct, pq, px, sym, toast } from "../ui.js";

const VERDICT = {
  TRADE: (n) => [`${n} trade${n > 1 ? "s" : ""} validé${n > 1 ? "s" : ""}`, "Le bot a trouvé une occasion propre. Lis le ticket avant d'entrer."],
  WATCH: () => ["Pas encore d'entrée", "Des setups se forment. Le bot attend leur confirmation."],
  NONE: () => ["Aucun trade, on attend", "Rien d'assez propre pour l'instant. Attendre est une décision."],
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
        ${s.status === "TRADE" ? (expired ? '<span class="pastille">expiré</span>' : '<span class="pastille long">🟢 validé</span>')
          : '<span class="pastille ambre">🟡 à surveiller</span>'}
      </div>
      <div class="actif">${esc(s.display)}</div>
      <div class="muted small">${esc(STRAT[s.strategy] || s.strategy)} · score ${Math.round(s.score)} · ${ago(s.created_at)}</div>
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

export async function render(main, ctx) {
  const me = ctx.me;
  const [scan, mine] = await Promise.all([backend.latestScan(), backend.trades({ userId: me.id, limit: 300 })]);
  const sigs = scan ? await backend.signalsOf(scan.id) : [];
  const trades = sigs.filter((s) => s.status === "TRADE");
  const watch = sigs.filter((s) => s.status === "WATCH");
  const budget = riskBudget(me, mine);
  const open = mine.filter((t) => t.status === "ouvert");
  const [titre, sous] = scan ? VERDICT[scan.verdict]?.(trades.length) || VERDICT.NONE() : ["Le bot n'a pas encore scanné", "Le premier scan automatique arrive vers " + nextScan() + ". Tu peux aussi le lancer maintenant."];
  const icon = scan?.verdict === "TRADE" ? "🟢" : scan?.verdict === "WATCH" ? "🟡" : "🛑";

  main.innerHTML = `
    <section class="verdict">
      <img src="img/logo.svg" alt="">
      <div>
        <h1>${scan ? icon + " " : ""}${esc(titre)}</h1>
        <p>${esc(sous)}</p>
        <p class="small">${scan ? `Dernier scan ${ago(scan.created_at)} (${dt(scan.created_at)}) · ` : ""}prochain vers ${nextScan()}</p>
      </div>
    </section>

    <dl class="chiffres">
      <div><dt>Ton solde</dt><dd class="num">${eur(+me.balance_eur)}</dd></div>
      <div><dt>Risque par trade</dt><dd class="num">${eur((me.balance_eur * me.risk_pct) / 100)}</dd></div>
      <div><dt>Risque encore disponible</dt><dd class="num">${eur(budget.available)}</dd></div>
      <div><dt>Résultat du jour</dt><dd class="num ${cls(budget.todayPnl)}">${eur(budget.todayPnl, true)}</dd></div>
    </dl>
    ${budget.dailyStop ? `<div class="alerte rouge"><strong>Stop pour aujourd'hui.</strong> Tu as atteint ta perte maximale du jour
      (${pct(+me.max_daily_loss_pct)}). Le site bloque les nouveaux trades jusqu'à demain.</div>` : ""}

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
      <p class="muted">Confiance du bot de ${SEUIL_SOLIDE}/100 ou plus : beaucoup de signaux vont dans le même sens.
        Ça reste un pari : c'est le stop qui te protège.</p>
      <div class="grille setups" data-esp="solide"></div>
      <p class="vide-espace small muted" data-vide="solide">Aucun setup à forte confiance en attente.</p>
    </section>
    <section class="section espace" id="esp-fragile">
      <h2>Moins solides</h2>
      <p class="muted">Moins de signaux d'accord (confiance sous ${SEUIL_SOLIDE}/100). Utile pour apprendre ; si tu entres, sois plus prudent.</p>
      <div class="grille setups" data-esp="fragile"></div>
      <p class="vide-espace small muted" data-vide="fragile">Aucun.</p>
    </section>
    <details class="section espace" id="esp-fini"><summary><h2 style="display:inline">Ratés, trop tard ou expirés</h2>
      <span class="muted small" data-compte="fini"></span></summary>
      <p class="muted">Le prix a touché le stop, a déjà atteint l'objectif 1 sans nous, ou les niveaux sont trop anciens. On n'y entre plus.</p>
      <div class="grille setups" data-esp="fini"></div>
    </details>
    <div id="cartes-attente" hidden>${[...sigs].sort(ordre).map((s) => setupCard(s, me)).join("")}</div>` : ""}

    ${scan && !trades.length && (scan.reasons || []).length ? `<section class="section"><h2>Pourquoi pas de trade</h2>
      <div class="bloc"><ul>${scan.reasons.slice(0, 5).map((r) => `<li>${esc(r)}</li>`).join("")}</ul></div></section>` : ""}

    ${scan?.opportunities?.length ? `<section class="section"><h2>Tous les marchés analysés</h2>
      <div class="ligne">${scan.opportunities.slice(0, 40).map((o) => {
        const k = o.state === "LONG" ? "long" : o.state === "SHORT" ? "short" : o.state.startsWith("SURV") ? "ambre" : "";
        return `<span class="pastille ${k}" title="score ${o.score ?? "—"}">${esc(o.display)} · ${esc(o.state === "WAIT" ? "attendre" : o.state.toLowerCase())}</span>`;
      }).join("")}</div></section>` : ""}

    ${scan?.news?.length ? `<section class="section"><h2>News importantes</h2>${scan.news.slice(0, 6).map((n) => `
      <details><summary>${esc(n.title)} <span class="muted small">· ${esc(n.source)} · ${ago(n.published_at)} ·
        ${n.verified ? "vérifiée" : n.is_rumor ? "rumeur" : "non vérifiée"}</span></summary>
        <p><strong>Fait :</strong> ${esc(n.fact)}</p><p class="muted"><strong>Interprétation :</strong> ${esc(n.interpretation)}</p>
        ${n.url ? `<a href="${esc(n.url)}" target="_blank" rel="noopener">Lire la source</a>` : ""}</details>`).join("")}</section>` : ""}

    ${scan?.data_issues?.length ? `<section class="section"><details><summary>Problèmes de données au dernier scan (${scan.data_issues.length})</summary>
      <ul>${scan.data_issues.slice(0, 12).map((d) => `<li class="small">${esc(d)}</li>`).join("")}</ul></details></section>` : ""}
  `;

  // Rangement des cartes : par confiance d'abord, puis « imminent » / « fini » dès que le prix Kraken est lu.
  const where = new Map();
  const ranger = (s, ph) => {
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
      return { s, chartEl: card.querySelector("[data-chart]"), phaseEl: card.querySelector("[data-phase]") };
    }), { onPhase: ranger });
    ctx.onLeave(stop);
  }

  main.querySelector("#scan-now").addEventListener("click", (e) => busy(e.currentTarget, async () => toast(await backend.requestScan())));
}
