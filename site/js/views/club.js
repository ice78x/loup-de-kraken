// Le club : classement, derniers trades de tous les membres, et la page de chaque membre.
import { backend } from "../data.js";
import { cls, esc, eur, pct, rr } from "../ui.js";
import { historyTable, stats, statsBlock } from "./trades.js";

export async function render(main, ctx, memberId) {
  if (memberId) return renderMember(main, ctx, memberId);
  const [lb, feed] = await Promise.all([backend.leaderboard(), backend.trades({ limit: 60 })]);
  main.innerHTML = `
    <h1>Le club</h1>
    <p class="muted">Tout le monde voit les trades de tout le monde : c'est comme ça qu'on progresse ensemble.</p>
    <section class="section"><h2>Classement</h2>
      <div class="table-wrap"><table>
        <thead><tr><th>#</th><th>Membre</th><th class="d">Trades</th><th class="d">Réussite</th><th class="d">Résultat</th><th class="d">R total</th><th class="d">R moyen</th><th class="d">En cours</th></tr></thead>
        <tbody>${lb.map((m, i) => `<tr>
          <td>${i + 1}</td><td><a href="#/membre/${m.id}">${esc(m.pseudo)}</a>${m.id === ctx.me.id ? " (toi)" : ""}</td>
          <td class="d">${m.trades}</td><td class="d">${m.trades ? pct((m.wins / m.trades) * 100, 0) : "—"}</td>
          <td class="d num ${cls(+m.pnl_eur)}">${eur(+m.pnl_eur, true)}</td><td class="d num ${cls(+m.total_r)}">${rr(+m.total_r)}</td>
          <td class="d num">${rr(m.avg_r == null ? null : +m.avg_r)}</td><td class="d">${m.open_trades}</td></tr>`).join("")}</tbody>
      </table></div>
      <p class="small muted">Le R compare les membres à risque égal : +2 R = deux fois la mise risquée, quel que soit le solde.</p>
    </section>
    <section class="section"><h2>En cours dans le club</h2>
      ${feed.filter((t) => t.status === "ouvert").map((t) => `<div class="bloc ligne entre">
        <span><a href="#/membre/${t.user_id}">${esc(t.profiles?.pseudo)}</a> · <b class="${t.direction === "LONG" ? "gain" : "perte"}">${t.direction}</b>
        <a href="#/trade/${t.id}">${esc(t.display)}</a></span><span class="pastille">${t.mode === "reel" ? "réel" : "paper"}</span></div>`).join("")
        || '<div class="vide"><strong>Personne n\'a de trade en cours</strong></div>'}
    </section>
    <section class="section"><h2>Derniers trades clos</h2>${historyTable(feed.filter((t) => t.status !== "ouvert"), { who: true })}</section>`;
}

async function renderMember(main, ctx, id) {
  const [members, list] = await Promise.all([backend.members(), backend.trades({ userId: id, limit: 500 })]);
  const m = members.find((x) => x.id === id);
  main.innerHTML = `
    <a href="#/club" class="muted small">← Le club</a>
    <h1>${esc(m?.pseudo || "Membre")}</h1>
    ${statsBlock(stats(list))}
    <section class="section"><h2>En cours</h2>
      ${list.filter((t) => t.status === "ouvert").map((t) => `<div class="bloc ligne entre"><a href="#/trade/${t.id}">${esc(t.display)}</a>
        <b class="${t.direction === "LONG" ? "gain" : "perte"}">${t.direction}</b></div>`).join("") || '<p class="muted">Aucun.</p>'}</section>
    <section class="section"><h2>Historique</h2>${historyTable(list.filter((t) => t.status !== "ouvert"))}</section>`;
}
