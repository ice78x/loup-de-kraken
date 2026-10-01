// Le bot : comment il décide, ce que dit l'historique, les réglages que le club peut changer, les idées, et comment modifier le code avec Claude.
import { backend } from "../data.js";
import { STRAT, ago, busy, dt, esc, pct, rr, toast } from "../ui.js";

const PROMPTS = [
  "Ajoute une notification Telegram quand un trade 🟢 est validé.",
  "Ajoute une stratégie qui achète les rebonds sur la moyenne mobile 200 en tendance haussière, avec ses tests.",
  "Sur la page Mes trades, ajoute un graphique de l'évolution de mon solde.",
  "Explique-moi pourquoi le bot a refusé les setups du dernier scan, en lisant le code du scanner.",
];

export async function render(main, ctx) {
  const [settings, log, edges, ideas] = await Promise.all([backend.settings(), backend.settingsLog(), backend.edges(), backend.ideas()]);
  main.innerHTML = `
    <h1>Le bot</h1>
    <p>Chaque heure, de 6 h à 23 h, le bot analyse les marchés Kraken et publie ici ses trades. Tout le club peut le régler et proposer des améliorations.</p>

    <section class="section"><h2>Comment il décide un trade</h2>
      <ol class="bloc pile" style="padding-left:36px">
        <li><b>Il liste</b> tout ce qui est vraiment disponible sur Kraken pour la France (cryptos, xStocks, matières premières).</li>
        <li><b>Il garde les marchés liquides</b> : assez de volume, écart achat/vente faible.</li>
        <li><b>Il lit les news</b> officielles (Fed, BCE, SEC…) et médias reconnus. Une rumeur ne compte jamais.</li>
        <li><b>Il analyse les graphiques</b> en 5 min, 15 min, 1 h, 4 h, et l'historique jour/semaine.</li>
        <li><b>Il cherche 4 configurations</b> : ${Object.entries(STRAT).filter(([k]) => k !== "manuel").map(([, v]) => v.toLowerCase()).join(", ")}.</li>
        <li><b>Il note chaque setup sur 100</b> (catalyseur, structure, niveau, volume, volatilité, confirmation, rapport gain/risque).</li>
        <li><b>Il élimine</b> ce qui est trop risqué : stop trop serré, mouvement déjà parti, frais trop lourds, gain trop faible.</li>
        <li><b>Il publie</b> 🟢 si tout est bon, 🟡 si ça se prépare, 🛑 sinon.</li>
      </ol></section>

    <section class="section"><h2>Ce que dit l'historique</h2>
      <p class="muted">Chaque dimanche, le bot rejoue ses stratégies sur tout l'historique et garde seulement les réglages gagnants sur des périodes qu'il n'a pas vues pendant le réglage.</p>
      ${edges.length ? `<div class="table-wrap"><table><thead><tr><th>Marché</th><th>Stratégie</th><th>Statut</th><th class="d">Trades testés</th><th class="d">Résultat moyen</th><th class="d">Réussite</th></tr></thead>
      <tbody>${edges.map((e) => `<tr><td>${esc(e.asset_class)}</td><td>${esc(STRAT[e.strategy] || e.strategy)}</td>
        <td><span class="pastille ${e.status === "adopté" ? "long" : e.status === "désactivé" ? "short" : ""}">${esc(e.status)}</span></td>
        <td class="d">${e.oos_trades ?? 0}</td><td class="d num">${e.oos_expectancy == null ? "—" : rr(+e.oos_expectancy) + " / trade"}</td>
        <td class="d">${e.oos_win_rate == null ? "—" : pct(+e.oos_win_rate, 0)}</td></tr>`).join("")}</tbody></table></div>`
        : '<div class="vide"><strong>Pas encore de résultat</strong>La première optimisation a lieu le dimanche suivant, quand assez d\'historique est accumulé.</div>'}
      <p class="small muted">Un bon résultat passé est une mesure, pas une promesse.</p></section>

    <section class="section"><h2>Réglages du bot</h2>
      <p class="muted">Tout membre peut les changer. Chaque changement est noté ci-dessous et s'applique au scan suivant. Les limites de sécurité ne peuvent pas être dépassées.</p>
      <div class="grille">${settings.map(settingCard).join("")}</div>
      <details style="margin-top:16px"><summary>Derniers changements</summary><ul>${log.map((l) => `<li class="small">${dt(l.created_at)} · <b>${esc(l.profiles?.pseudo || "bot")}</b> :
        ${esc(l.key)} ${esc(JSON.stringify(l.old_value))} → ${esc(JSON.stringify(l.new_value))}</li>`).join("") || "<li>Aucun</li>"}</ul></details></section>

    <section class="section"><h2>Idées d'amélioration</h2>
      <form class="form bloc" id="idea"><div class="deux">
        <label class="champ"><span>Ton idée</span><input name="title" required minlength="3" maxlength="140" placeholder="Ex. alerte quand un 🟢 sort"></label>
        <label class="champ"><span>Détails (facultatif)</span><input name="body" maxlength="1000"></label></div>
        <button class="btn principal" type="submit">Proposer</button></form>
      <div id="ideas" style="margin-top:12px">${ideas.map((i) => ideaRow(i, ctx)).join("") || '<p class="muted">Aucune idée pour l\'instant.</p>'}</div></section>

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
    if (s.key === "quote_currencies" && !value.length) return toast("Garde au moins une devise.", true);
    else value = +String(f.elements.v.value).replace(",", ".");
    if (typeof value === "number" && (!isFinite(value) || (s.min_value != null && value < s.min_value) || (s.max_value != null && value > s.max_value))) {
      return toast(`Valeur autorisée : entre ${s.min_value} et ${s.max_value}.`, true);
    }
    busy(e.submitter, async () => { await backend.setSetting(s.key, value); toast("Réglage enregistré : il s'applique au prochain scan."); render(main, ctx); });
  }));
  main.querySelector("#idea").addEventListener("submit", (e) => {
    e.preventDefault();
    busy(e.submitter, async () => { await backend.addIdea(e.target.title.value.trim(), e.target.body.value.trim()); toast("Idée ajoutée."); render(main, ctx); });
  });
  main.querySelectorAll("[data-vote]").forEach((b) => b.addEventListener("click", () => busy(b, async () => {
    const id = +b.dataset.vote;
    await (b.dataset.voted ? backend.unvote(id) : backend.vote(id));
    render(main, ctx);
  })));
  main.querySelectorAll("[data-status]").forEach((sel) => sel.addEventListener("change", () =>
    backend.setIdea(+sel.dataset.status, { status: sel.value }).then(() => toast("Statut mis à jour."))));
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

function ideaRow(i, ctx) {
  const voted = (i.idea_votes || []).some((v) => v.user_id === ctx.me.id);
  const n = (i.idea_votes || []).length;
  return `<div class="bloc ligne entre">
    <div><b>${esc(i.title)}</b>${i.body ? `<p class="small muted" style="margin:4px 0 0">${esc(i.body)}</p>` : ""}
      <span class="small muted">${esc(i.profiles?.pseudo)} · ${ago(i.created_at)}</span></div>
    <div class="ligne">
      ${ctx.me.is_admin ? `<select data-status="${i.id}" style="width:auto">${["proposée", "en cours", "faite", "refusée"].map((s) =>
        `<option ${s === i.status ? "selected" : ""}>${s}</option>`).join("")}</select>` : `<span class="pastille">${esc(i.status)}</span>`}
      <button class="btn ${voted ? "principal" : ""}" data-vote="${i.id}" ${voted ? "data-voted=1" : ""} aria-pressed="${voted}">👍 ${n}</button>
    </div></div>`;
}
