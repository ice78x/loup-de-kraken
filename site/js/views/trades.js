// Mes trades : positions ouvertes (P&L en direct) et historique avec statistiques.
import { backend } from "../data.js";
import { prices } from "../market.js";
import { pnlBreakdown } from "../sizing.js";
import { soldeBloc, soldeLive } from "../solde.js";
import { STRAT, cls, dt, esc, eur, pct, pq, px, rr } from "../ui.js";

export function stats(list) {
  const closed = list.filter((t) => t.status === "clos");
  const wins = closed.filter((t) => +t.realized_pnl_eur > 0);
  const pnl = closed.reduce((a, t) => a + +t.realized_pnl_eur, 0);
  const rs = closed.map((t) => +t.r_multiple).filter((x) => isFinite(x));
  const gw = wins.reduce((a, t) => a + +t.realized_pnl_eur, 0);
  const gl = -closed.filter((t) => +t.realized_pnl_eur <= 0).reduce((a, t) => a + +t.realized_pnl_eur, 0);
  const rw = rs.filter((x) => x > 0), rl = rs.filter((x) => x <= 0);
  return { n: closed.length, wins: wins.length, losses: closed.length - wins.length,
    winRate: closed.length ? (wins.length / closed.length) * 100 : null, pnl,
    avgR: rs.length ? rs.reduce((a, b) => a + b, 0) / rs.length : null, totalR: rs.reduce((a, b) => a + b, 0),
    avgWinR: rw.length ? rw.reduce((a, b) => a + b, 0) / rw.length : null, avgLossR: rl.length ? rl.reduce((a, b) => a + b, 0) / rl.length : null,
    pf: gl > 0 ? gw / gl : null };
}

export function statsBlock(st) {
  const lecture = st.n < 1 ? "" : st.n < 30
    ? `${st.n} trade${st.n > 1 ? "s" : ""} clos : encore trop peu pour juger ta méthode (vise 30 à 50). Garde le même risque à chaque trade.`
    : st.totalR > 0 ? "Sur ce nombre de trades, ta méthode est positive : continue pareil, sans augmenter le risque."
      : "Sur ce nombre de trades, ta méthode perd : regarde quels setups te coûtent (stratégie, heure, actif) avant de continuer.";
  return `<dl class="chiffres">
    <div><dt>Trades clos</dt><dd>${st.n}${st.n ? ` <span class="small muted">(${st.wins} ✅ / ${st.losses} ❌)</span>` : ""}</dd></div>
    <div><dt>Réussite</dt><dd>${st.winRate == null ? "—" : pct(st.winRate, 0)}</dd></div>
    <div><dt>Résultat</dt><dd class="num ${cls(st.pnl)}">${eur(st.pnl, true)}</dd></div>
    <div><dt>Total en R</dt><dd class="num ${cls(st.totalR)}">${st.n ? rr(st.totalR) : "—"}</dd></div>
    <div><dt>R moyen</dt><dd class="num">${rr(st.avgR)}</dd>
      ${st.avgWinR != null || st.avgLossR != null ? `<span class="small muted">gain moyen ${rr(st.avgWinR)} · perte moyenne ${rr(st.avgLossR)}</span>` : ""}</div>
    <div><dt>Profit factor</dt><dd class="num">${st.pf == null ? "—" : st.pf.toFixed(2)}</dd></div>
  </dl>${lecture ? `<p class="small muted">${lecture}</p>` : ""}`;
}

const NOM_FIN = { sl: "stop", be: "stop au prix d'entrée", tp3: "TP3", temps: "48 h écoulées", non_entre: "jamais entré" };
/** Ce que le bot apprend : résultats RÉELS de ses signaux passés, rejoués sur les vraies bougies Kraken. */
export function apprentissageBlock(rows, recents) {
  const verts = (rows || []).filter((r) => r.status === "TRADE" && +r.n > 0);
  const tot = verts.reduce((a, r) => ({ n: a.n + +r.n, sum: a.sum + +r.sum_r, gagn: a.gagn + (+r.win_rate / 100) * +r.n }), { n: 0, sum: 0, gagn: 0 });
  const tete = tot.n ? `<dl class="chiffres">
      <div><dt>Signaux 🟢 entrés</dt><dd>${tot.n}</dd></div>
      <div><dt>Réussite</dt><dd>${pct((tot.gagn / tot.n) * 100, 0)}</dd></div>
      <div><dt>Total en R</dt><dd class="num ${cls(tot.sum)}">${rr(tot.sum)}</dd></div>
      <div><dt>R moyen</dt><dd class="num ${cls(tot.sum)}">${rr(tot.sum / tot.n)}</dd></div></dl>` : "";
  const table = verts.length ? `<div class="table-wrap"><table><thead><tr><th>Stratégie</th><th>Marché</th><th class="d">Trades</th><th class="d">Réussite</th><th class="d">R moyen</th></tr></thead>
    <tbody>${verts.sort((a, b) => +b.n - +a.n).map((r) => `<tr><td>${esc(STRAT[r.strategy] || r.strategy)}</td><td>${esc(r.asset_class || "")}</td>
      <td class="d num">${r.n}</td><td class="d num">${r.win_rate == null ? "—" : pct(+r.win_rate, 0)}</td>
      <td class="d num ${cls(+r.avg_r)}">${rr(+r.avg_r)}${+r.n >= 15 && +r.avg_r < -0.15 ? " 🚫" : ""}</td></tr>`).join("")}</tbody></table></div>` : "";
  const liste = (recents || []).length ? `<details><summary class="small">Les derniers signaux terminés</summary><div class="table-wrap"><table>
    <thead><tr><th>Date</th><th>Actif</th><th>Sens</th><th>Signal</th><th>Fin</th><th class="d">R</th></tr></thead>
    <tbody>${recents.map((o) => `<tr><td>${dt(o.created_at)}</td><td>${esc(o.display)}</td><td class="${o.direction === "LONG" ? "gain" : "perte"}">${o.direction}</td>
      <td>${o.status === "TRADE" ? "🟢" : "🟡"}</td><td>${esc(NOM_FIN[o.outcome] || o.outcome)}</td><td class="d num ${cls(+o.r)}">${o.r == null ? "—" : rr(+o.r)}</td></tr>`).join("")}</tbody></table></div></details>` : "";
  return `<section class="section"><h2>🧠 Ce que le bot apprend</h2>
    <p class="muted">Après chaque scan, le bot rejoue ses signaux passés sur les <b>vraies bougies Kraken</b> : entrée dans la zone, stop testé avant les objectifs,
      30 / 40 / 30 % aux TP, stop au prix d'entrée après le TP1, frais déduits. Une stratégie qui perd en vrai sur 15 trades ou plus ne donne plus de 🟢 (🚫).</p>
    ${tete || '<div class="vide"><strong>Pas encore de résultat enregistré</strong>Les premiers arrivent quelques heures après les prochains scans.</div>'}
    ${table}${liste}</section>`;
}

export function historyTable(list, { who = false } = {}) {
  if (!list.length) return '<div class="vide"><strong>Aucun trade clos pour l\'instant</strong>Ils apparaîtront ici avec leur résultat.</div>';
  return `<div class="table-wrap"><table>
    <thead><tr><th>Date</th>${who ? "<th>Membre</th>" : ""}<th>Actif</th><th>Sens</th><th>Type</th><th class="d">Entrée</th><th class="d">Sortie</th><th class="d">Résultat</th><th class="d">R</th><th>Fin</th></tr></thead>
    <tbody>${list.map((t) => `<tr>
      <td><a href="#/trade/${t.id}">${dt(t.closed_at || t.opened_at)}</a></td>
      ${who ? `<td><a href="#/membre/${t.user_id}">${esc(t.profiles?.pseudo)}</a></td>` : ""}
      <td>${esc(t.display)}</td><td class="${t.direction === "LONG" ? "gain" : "perte"}">${t.direction}</td>
      <td>${t.mode === "reel" ? "réel" : "paper"}</td>
      <td class="d num">${px(+t.entry_price)}</td><td class="d num">${px(+t.exit_price)}</td>
      <td class="d num ${cls(+t.realized_pnl_eur)}">${t.status === "annule" ? "annulé" : eur(+t.realized_pnl_eur, true)}</td>
      <td class="d num">${rr(+t.r_multiple)}</td><td>${esc(t.close_reason || t.status)}</td></tr>`).join("")}</tbody></table></div>`;
}

function openCard(t, p) {
  const b = pnlBreakdown(t, p?.last);
  const dir = t.direction === "LONG" ? "long" : "short";
  return `<a class="ticket ${dir}" href="#/trade/${t.id}" style="grid-template-columns:1fr">
    <div>
      <div class="ligne entre"><span class="sens">${t.direction === "LONG" ? "LONG ↑" : "SHORT ↓"}</span>
        <span class="pastille ${t.mode === "reel" ? "ambre" : ""}">${t.mode === "reel" ? "réel" : "paper"} · x${t.leverage}</span></div>
      <div class="actif">${esc(t.display)}</div>
      <dl>
        <dt>Entrée</dt><dd class="num">${pq(+t.entry_price, t.quote)}</dd>
        <dt>Prix actuel</dt><dd class="num">${p?.last ? pq(p.last, t.quote) : "indisponible"}</dd>
        <dt>Si tu fermes maintenant</dt><dd class="num ${cls(b.ifCloseNow)}"><b>${b.ifCloseNow != null ? eur(b.ifCloseNow, true) : "—"}</b>
          ${b.ifCloseNow != null ? `<br><span class="small muted">prix ${eur(b.move, true)} · frais d'entrée ${eur(-b.entryFee, true)} · frais de sortie ≈ ${eur(-b.exitFee, true)}${Math.abs(b.banked) > 0.005 ? ` · TP encaissés ${eur(b.banked, true)}` : ""}</span>` : ""}</dd>
        <dt>SL / TP</dt><dd class="num">${+t.sl > 0 ? px(+t.sl) : `aucun${t.liq_price ? ` (liq. ≈ ${px(+t.liq_price)})` : ""}`} / ${[t.tp1, t.tp2, t.tp3].map((x, i) => x ? px(+x) + (t[`tp${i + 1}_hit`] ? " ✓" : "") : "—").join(" · ")}</dd>
      </dl>
      ${t.advice ? `<p class="small" style="margin-top:10px"><b>Conseil du bot :</b> ${esc(t.advice)}</p>` : ""}
    </div></a>`;
}

export async function render(main, ctx) {
  const mine = await backend.trades({ userId: ctx.me.id, limit: 500 });
  const open = mine.filter((t) => t.status === "ouvert");
  const done = mine.filter((t) => t.status !== "ouvert");
  main.innerHTML = `
    <div class="ligne entre"><h1 style="margin:0">Mes trades</h1><a class="btn principal" href="#/trade/nouveau">Trade manuel</a></div>
    <dl class="chiffres">${soldeBloc(ctx.me)}</dl>
    ${statsBlock(stats(mine))}
    <section class="section"><h2>En cours (${open.length})</h2>
      <div id="open" class="grille">${open.length ? "" : '<div class="vide"><strong>Aucun trade en cours</strong>Prends un signal 🟢 depuis l\'accueil ou crée un trade manuel.</div>'}</div>
      <p class="small muted" id="px-note"></p></section>
    <section class="section"><h2>Historique</h2>${historyTable(done)}</section>
    <div id="apprend"></div>`;
  Promise.all([backend.signalStats().catch(() => null), backend.recentOutcomes(25).catch(() => [])]).then(([rows, rec]) => {
    const el = main.querySelector("#apprend");
    if (el && rows) el.innerHTML = apprentissageBlock(rows, rec);
  });
  ctx.onLeave(soldeLive(main, ctx.me));
  if (!open.length) return;
  const box = main.querySelector("#open");
  const refresh = async () => {
    const px0 = await prices(open, { fx: false });
    box.innerHTML = open.map((t) => openCard(t, px0.get(t))).join("");
    main.querySelector("#px-note").textContent = px0.error ? `Prix en direct : ${px0.error}` : `Prix Kraken mis à jour à ${new Date().toLocaleTimeString("fr-FR")}`;
  };
  await refresh();
  const timer = setInterval(() => { if (document.visibilityState === "visible") refresh(); }, 30000);
  ctx.onLeave(() => clearInterval(timer));
}
