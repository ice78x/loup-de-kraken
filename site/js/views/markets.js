// Toutes les paires disponibles sur Kraken Pro pour ton pays (liste lue chez Kraken par le bot à chaque scan).
import { backend } from "../data.js";
import { ago, esc } from "../ui.js";

const CLASSES = [
  ["crypto", "Cryptos"], ["xstock", "Actions (xStocks)"], ["commodity", "Matières premières"], ["tradfi", "Indices et autres (futures)"],
];

export async function render(main) {
  const [insts, scan] = await Promise.all([backend.instruments().catch(() => []), backend.latestScan().catch(() => null)]);
  const opp = new Map((scan?.opportunities || []).map((o) => [o.key, o]));
  const maj = insts.reduce((m, i) => (i.updated_at && i.updated_at > m ? i.updated_at : m), "");

  main.innerHTML = `
    <a href="#/" class="muted small">← Accueil</a>
    <h1>Marchés Kraken Pro France</h1>
    <p class="muted">${insts.length ? `<b>${insts.length} paires</b> disponibles pour la France, lues directement chez Kraken
      (${maj ? `mise à jour ${ago(maj)}` : "à chaque scan"}).` : "La liste arrive après le premier scan du bot."}
      Seules les paires négociables en ce moment, dans tes devises (page <a href="#/bot">Le bot</a> → Paires analysées), sont listées.</p>
    <div class="bloc pile">
      <p class="small">Chaque heure, le bot <b>survole toutes ces paires</b> (prix, volume, écart achat/vente), puis analyse
        <b>en profondeur les plus liquides et les plus actives</b> (${scan?.counts?.["analysés"] ?? "—"} au dernier scan).
        Les autres ne sont pas oubliées : elles passent dans l'analyse dès qu'elles deviennent assez actives, ou si une news vérifiée les concerne.</p>
    </div>
    <label class="champ section"><span>Chercher une paire</span>
      <input id="q" placeholder="BTC, SOL, TSLA, PAXG…" autocomplete="off"></label>
    <div id="liste"></div>`;

  const liste = main.querySelector("#liste");
  const draw = (q = "") => {
    const f = q.trim().toUpperCase();
    const keep = insts.filter((i) => !f || String(i.display).toUpperCase().includes(f) || String(i.base || "").toUpperCase().includes(f));
    liste.innerHTML = CLASSES.map(([k, titre]) => {
      const l = keep.filter((i) => (CLASSES.some(([c]) => c === i.asset_class) ? i.asset_class : "tradfi") === k);
      if (!l.length) return "";
      l.sort((a, b) => (opp.has(b.key) - opp.has(a.key)) || String(a.display).localeCompare(String(b.display)));
      return `<section class="section"><h2>${titre} <span class="muted small">(${l.length})</span></h2>
        <div class="marches">${l.map((i) => {
          const o = opp.get(i.key);
          const st = o ? (o.state === "LONG" ? ["long", "long"] : o.state === "SHORT" ? ["short", "short"]
            : o.state?.startsWith("SURV") ? ["ambre", "à surveiller"] : ["", "analysé"]) : null;
          return `<div class="marche">
            <b>${esc(i.display)}</b>
            <span class="small muted">${i.venue === "futures" ? "futures" : "spot"}${i.can_short ? " · short possible" : ""}${i.max_leverage > 1 ? ` · levier ×${i.max_leverage}` : ""}</span>
            ${st ? `<span class="pastille ${st[0]}">${esc(st[1])}</span>` : ""}
          </div>`;
        }).join("")}</div></section>`;
    }).join("") || '<p class="muted section">Aucune paire ne correspond.</p>';
  };
  draw();
  main.querySelector("#q").addEventListener("input", (e) => draw(e.target.value));
}
