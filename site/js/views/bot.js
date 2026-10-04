// Le bot (ADMIN seulement) : comment il décide, ce que dit l'historique, ses réglages, et comment modifier le code avec Claude.
// Les membres passent par la boîte à idées (#/idees) ; la base refuse aussi toute modification des réglages par un non-admin.
import { backend } from "../data.js";
import { backtestBlock } from "../backtest.js";
import { STRAT, ago, busy, dt, esc, pct, rr, toast } from "../ui.js";

const PROMPTS = [
  "Ajoute une notification Telegram quand un trade 🟢 est validé.",
  "Ajoute une stratégie qui achète les rebonds sur la moyenne mobile 200 en tendance haussière, avec ses tests.",
  "Sur la page Mes trades, ajoute un graphique de l'évolution de mon solde.",
  "Explique-moi pourquoi le bot a refusé les setups du dernier scan, en lisant le code du scanner.",
];

export async function render(main, ctx) {
  if (!ctx.me.is_admin) {
    main.innerHTML = `<div class="vide"><strong>Réservé à l'administrateur</strong>Tu as une idée pour améliorer le bot ou le site ?
      <a class="btn principal" href="#/idees" style="margin-top:12px">Proposer une idée</a></div>`;
    return;
  }
  const [settings, log, edges, run] = await Promise.all([backend.settings(), backend.settingsLog(), backend.edges(),
    backend.latestBacktest().catch(() => null)]);
  main.innerHTML = `
    <h1>Le bot</h1>
    <p>Chaque heure, 24 h / 24, le bot analyse les marchés Kraken et publie ici ses trades. Page réservée à l'admin : les membres envoient leurs idées depuis l'onglet Idées, tu les reçois dans Mon compte.</p>

    <section class="section"><h2>Comment il décide un trade</h2>
      <ol class="bloc pile" style="padding-left:36px">
        <li><b>Il liste</b> tout ce qui est vraiment disponible sur Kraken pour la France (cryptos, xStocks, matières premières).</li>
        <li><b>Il garde les marchés liquides</b> : assez de volume, écart achat/vente faible.</li>
        <li><b>Il lit les news</b> officielles (Fed, BCE, SEC…) et médias reconnus. Une rumeur ne compte jamais.</li>
        <li><b>Il détermine le régime du marché</b> (1 jour, 4 h, 1 h) : tendance haussière, baissière, range, cassure, volatilité extrême, chaotique.
          Chaotique, incertain ou trop volatil → <b>aucun trade</b>.</li>
        <li><b>Il regarde BTC et ETH d'abord</b> : un LONG sur une altcoin est bloqué si BTC baisse nettement (et inversement).</li>
        <li><b>Il choisit la stratégie du régime</b> : repli ou cassure dans le sens de la tendance, rejet seulement en range.</li>
        <li><b>Il note chaque setup sur 100</b> avec des règles fixes : régime 20 · alignement des tendances 20 · structure 20 · volume 10 · momentum 10 · news 10 · gain/risque 10.
          90+ = 🔥 A+, 80+ = 🟢, 70+ = 🟡, en dessous rien n'est affiché.</li>
        <li><b>Il exige une preuve</b> : pas de 🟢 tant que la stratégie n'a pas gagné, dans ce régime, sur des données qu'elle n'avait pas vues (backtest ci-dessous).</li>
        <li><b>Il élimine</b> le reste : stop trop serré, mouvement déjà parti, frais trop lourds, gain trop faible, série de pertes récente.</li>
        <li><b>Il publie</b> au plus 2 🟢 par scan, et un seul par sens sur les cryptos (elles bougent ensemble).</li>
      </ol></section>

    ${backtestBlock(run, { admin: true })}

    <section class="section"><h2>Ancien optimiseur</h2>
      <p class="muted">Chaque dimanche, le bot rejoue ses stratégies sur tout l'historique et garde seulement les réglages gagnants sur des périodes qu'il n'a pas vues pendant le réglage.</p>
      ${edges.length ? `<div class="table-wrap"><table><thead><tr><th>Marché</th><th>Stratégie</th><th>Statut</th><th class="d">Trades testés</th><th class="d">Résultat moyen</th><th class="d">Réussite</th></tr></thead>
      <tbody>${edges.map((e) => `<tr><td>${esc(e.asset_class)}</td><td>${esc(STRAT[e.strategy] || e.strategy)}</td>
        <td><span class="pastille ${e.status === "adopté" ? "long" : e.status === "désactivé" ? "short" : ""}">${esc(e.status)}</span></td>
        <td class="d">${e.oos_trades ?? 0}</td><td class="d num">${e.oos_expectancy == null ? "—" : rr(+e.oos_expectancy) + " / trade"}</td>
        <td class="d">${e.oos_win_rate == null ? "—" : pct(+e.oos_win_rate, 0)}</td></tr>`).join("")}</tbody></table></div>`
        : '<div class="vide"><strong>Pas encore de résultat</strong>La première optimisation a lieu le dimanche suivant, quand assez d\'historique est accumulé.</div>'}
      <p class="small muted">Un bon résultat passé est une mesure, pas une promesse.</p></section>

    <section class="section"><h2>Réglages du bot</h2>
      <p class="muted">Seul un admin peut les changer. Chaque changement est noté ci-dessous et s'applique au scan suivant. Les limites de sécurité ne peuvent pas être dépassées.</p>
      <div class="grille">${settings.map(settingCard).join("")}</div>
      <details style="margin-top:16px"><summary>Derniers changements</summary><ul>${log.map((l) => `<li class="small">${dt(l.created_at)} · <b>${esc(l.profiles?.pseudo || "bot")}</b> :
        ${esc(l.key)} ${esc(JSON.stringify(l.old_value))} → ${esc(JSON.stringify(l.new_value))}</li>`).join("") || "<li>Aucun</li>"}</ul></details></section>


    <section class="section"><h2>Modifier le code avec Claude</h2>
      <div class="bloc pile">
        <p>Le code du site et du bot est sur GitHub. Pour l'améliorer, ouvre le projet avec <b>Claude</b> (Claude Code, ou une conversation reliée au dépôt) et demande ce que tu veux, en français. Le fichier <code>CLAUDE.md</code> lui explique déjà comment le projet fonctionne et les règles à respecter.</p>
        <p>Chaque modification est vérifiée automatiquement par les tests sur GitHub. Le site se met à jour tout seul après validation.</p>
        <p><b>Exemples de demandes :</b></p>
        <ul>${PROMPTS.map((p) => `<li><button class="btn discret small copy" data-t="${esc(p)}">Copier</button> ${esc(p)}</li>`).join("")}</ul>
      </div></section>`;

  main.querySelectorAll("form[data-key]").forEach((f) => f.addEventListener("submit", (e) => {
    e.preventDefault();
    const s = settings.find((x) => x.key === f.dataset.key);
    let value;
    if (typeof s.value === "boolean") value = f.elements.v.checked;
    else if (Array.isArray(s.value)) value = [...f.querySelectorAll("input:checked")].map((c) => c.value);
    else value = +String(f.elements.v.value).replace(",", ".");
    if (s.key === "quote_currencies" && !value.length) return toast("Garde au moins une devise.", true);
    if (typeof value === "number" && (!isFinite(value) || (s.min_value != null && value < s.min_value) || (s.max_value != null && value > s.max_value))) {
      return toast(`Valeur autorisée : entre ${s.min_value} et ${s.max_value}.`, true);
    }
    busy(e.submitter, async () => { await backend.setSetting(s.key, value); toast("Réglage enregistré : il s'applique au prochain scan."); render(main, ctx); });
  }));
  main.querySelectorAll(".copy").forEach((b) => b.addEventListener("click", () => navigator.clipboard?.writeText(b.dataset.t).then(() => toast("Copié."))));
}

function settingCard(s) {
  let input;
  if (typeof s.value === "boolean") {
    input = `<label class="ligne"><input type="checkbox" name="v" style="width:auto;min-height:0" ${s.value ? "checked" : ""}> Activé</label>`;
  } else if (s.key === "quote_currencies") {
    input = [["USD", "Paires en dollars (USD)"], ["EUR", "Paires en euros (EUR)"]].map(([k, v]) =>
      `<label class="ligne small"><input type="checkbox" value="${k}" style="width:auto;min-height:0" ${s.value.includes(k) ? "checked" : ""}> ${v}</label>`).join("");
  } else if (Array.isArray(s.value)) {
    input = Object.entries(STRAT).filter(([k]) => k !== "manuel").map(([k, v]) =>
      `<label class="ligne small"><input type="checkbox" value="${k}" style="width:auto;min-height:0" ${s.value.includes(k) ? "checked" : ""}> ${esc(v)}</label>`).join("");
  } else {
    input = `<input name="v" inputmode="decimal" value="${esc(s.value)}"><small>Entre ${s.min_value} et ${s.max_value}</small>`;
  }
  return `<form class="bloc form" data-key="${esc(s.key)}"><div class="champ"><span>${esc(s.label || s.key)}</span>${input}</div>
    ${s.help ? `<p class="small muted" style="margin:0">${esc(s.help)}</p>` : ""}
    <button class="btn" type="submit">Enregistrer</button>
    ${s.updated_at ? `<p class="small muted" style="margin:0">Modifié ${ago(s.updated_at)}</p>` : ""}</form>`;
}

