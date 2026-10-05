// Résultats du backtest walk-forward (moteur v2) : AVANT / APRÈS sur les mêmes vraies bougies Kraken.
// Données : table backtest_runs (écrite par GitHub Actions). Rien n'est calculé ni inventé ici : on affiche le rapport.
import { STRAT, ago, cls, esc, pct, rr } from "./ui.js";

export const REGIME = {
  TREND_UP: "Tendance haussière", TREND_DOWN: "Tendance baissière", RANGE: "Range", BREAKOUT_UP: "Cassure haussière",
  BREAKOUT_DOWN: "Cassure baissière", HIGH_VOL: "Volatilité extrême", CHAOTIC: "Marché chaotique", UNCERTAIN: "Régime incertain",
  TREND: "Tendance", BREAKOUT: "Cassure",
};

const nombre = (x, d = 2) => (x == null || !isFinite(+x) ? "—" : (+x).toLocaleString("fr-FR", { maximumFractionDigits: d }));

function ligne(nom, m) {
  if (!m || !m.trades) return `<tr><th scope="row">${nom}</th><td class="d" colspan="6">0 trade</td></tr>`;
  return `<tr><th scope="row">${nom}</th><td class="d num">${m.trades}</td><td class="d num">${pct(+m.win_rate_pct, 0)}</td>
    <td class="d num ${cls(+m.expectancy_r)}">${rr(+m.expectancy_r)}</td><td class="d num">${nombre(m.profit_factor)}</td>
    <td class="d num">${pct(+m.max_drawdown_pct, 1)}</td><td class="d num">${m.pire_serie_pertes ?? "—"}</td></tr>`;
}

export function combo(key) {
  const [strat, reg] = String(key).split("|");
  return `${STRAT[strat] || strat} · ${REGIME[reg] || reg}`;
}

export function backtestBlock(run, { admin = false } = {}) {
  const bouton = admin ? `<p><button type="button" class="btn principal mini" data-backtest>▶️ Lancer un backtest (120 jours, 16 perpétuels)</button>
    <span class="small muted">30 à 90 min sur GitHub · 1 par heure au plus</span></p>` : "";
  if (!run || !run.report) {
    return `<section class="section"><h2>📊 Backtest du moteur</h2>
      <div class="vide"><strong>Pas encore de backtest</strong>Tant qu'aucune stratégie n'a prouvé un avantage sur des données qu'elle n'a pas vues,
      le bot ne donne <b>aucun 🟢</b>. Il affiche seulement des 🟡 à surveiller.</div>${bouton}</section>`;
  }
  const r = run.report;
  if (!r.avant) {
    return `<section class="section"><h2>📊 Backtest du moteur</h2><div class="vide"><strong>Backtest impossible</strong>${esc(r.message || "données insuffisantes")}</div>${bouton}</section>`;
  }
  // Même règle que le bot (walkforward.proven) : une espérance ≤ 0 sur 3 trades hors échantillon ou plus annule la preuve.
  const ok = (e) => !!e.prouve && !((+e.oos_n || 0) >= 3 && e.oos_expectancy_r != null && +e.oos_expectancy_r <= 0);
  const edges = Object.entries(r.edges || {}).map(([k, e]) => [k, { ...e, prouve: ok(e) }])
    .sort((a, b) => (b[1].prouve - a[1].prouve) || b[1].n - a[1].n);
  const prouves = edges.filter(([, e]) => e.prouve);
  return `<section class="section"><h2>📊 Backtest du moteur</h2>
    <p class="muted">Rejoué sur <b>${Object.keys(r.instruments || {}).length} perpétuels Kraken</b> (vraies bougies 15 min, ${r.jours} jours).
      Mesuré <b>hors échantillon</b> (${esc(r.periode_hors_echantillon)}) : chaque période est jugée avec ce que le bot savait <i>avant</i>.
      Frais et glissement déduits. Lancé ${ago(run.created_at)}.</p>
    <div class="table-wrap"><table><thead><tr><th></th><th class="d">Trades</th><th class="d">Réussite</th><th class="d">Espérance</th>
      <th class="d">Profit factor</th><th class="d">Pire baisse</th><th class="d">Pire série</th></tr></thead>
      <tbody>${ligne("AVANT (ancien moteur)", r.avant)}${ligne("APRÈS (moteur v2)", r.apres)}${r.apres_seuil_70 ? ligne("v2, prouvé dès 70/100", r.apres_seuil_70) : ""}</tbody></table></div>
    <p class="small muted">Espérance = gain moyen par trade, en multiples du risque (R). Profit factor = gains ÷ pertes (au-dessus de 1 = gagnant).
      Pire baisse = recul maximum du capital avec 1 % de risque par trade.</p>
    <h3>Ce qui a le droit de donner un 🟢</h3>
    ${prouves.length ? `<ul>${prouves.map(([k, e]) => `<li><b>${esc(combo(k))}</b> : ${e.n} trades testés, ${rr(+e.expectancy_r)} / trade, PF ${nombre(e.profit_factor)}</li>`).join("")}</ul>`
      : `<p class="bloc"><b>🟡 Aucune combinaison prouvée.</b> Le bot ne donnera aucun 🟢 tant que ça ne change pas. C'est voulu : mieux vaut rater un trade que prendre un mauvais trade.</p>`}
    <details><summary class="small">Toutes les combinaisons testées</summary><div class="table-wrap"><table>
      <thead><tr><th>Stratégie · régime</th><th class="d">Trades</th><th class="d">Réussite</th><th class="d">Espérance</th><th class="d">PF</th><th>Verdict</th></tr></thead>
      <tbody>${edges.map(([k, e]) => `<tr><td>${esc(combo(k))}</td><td class="d num">${e.n}</td><td class="d num">${pct(+e.win_rate_pct, 0)}</td>
        <td class="d num ${cls(+e.expectancy_r)}">${rr(+e.expectancy_r)}</td><td class="d num">${nombre(e.profit_factor)}</td>
        <td>${e.prouve ? "🟢 prouvé" : "🚫 non"}</td></tr>`).join("")}</tbody></table></div></details>
    <p class="small muted">Un résultat passé est une mesure, pas une promesse.</p>${bouton}</section>`;
}

if (typeof document !== "undefined") {
  document.addEventListener("click", async (e) => {
    const b = e.target.closest?.("[data-backtest]");
    if (!b || b.disabled) return;
    b.disabled = true;
    const { backend } = await import("./data.js");
    const { toast } = await import("./ui.js");
    try {
      toast(await backend.requestScan("backtest", null, { days: 120, instruments: 16 }));
    } catch (err) {
      b.disabled = false;
      toast(err.message, true);
    }
  });
}
