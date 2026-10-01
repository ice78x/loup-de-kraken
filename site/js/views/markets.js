// Graphiques : toutes les paires Kraken Pro France, rangées en onglets (cryptos / actions / matières premières).
// Toucher une paire ouvre son graphique (#/graphique/<clé>). Liste lue chez Kraken par le bot à chaque scan.
import { backend } from "../data.js";
import { prices } from "../market.js";
import { searchInstruments } from "../search.js";
import { ago, esc, pq } from "../ui.js";

export const ONGLETS = [
  ["crypto", "Cryptos"], ["xstock", "Actions (xStocks)"], ["commodity", "Matières premières"], ["tradfi", "Autres"],
];
const classe = (i) => (ONGLETS.some(([c]) => c === i.asset_class) ? i.asset_class : "tradfi");
const lienGraph = (i) => `#/graphique/${encodeURIComponent(i.key)}`;
const NB_PRIX = 30; // prix en direct pour les 30 premières paires de l'onglet (limite du proxy Kraken)

export async function render(main, ctx, onglet = null) {
  const [insts, scan] = await Promise.all([backend.instruments().catch(() => []), backend.latestScan().catch(() => null)]);
  const opp = new Map((scan?.opportunities || []).map((o) => [o.display, o]));
  const maj = insts.reduce((m, i) => (i.updated_at && i.updated_at > m ? i.updated_at : m), "");
  const counts = Object.fromEntries(ONGLETS.map(([k]) => [k, insts.filter((i) => classe(i) === k).length]));
  let tab = onglet && counts[onglet] ? onglet : (() => { try { return localStorage.getItem("ldk-onglet") || "crypto"; } catch { return "crypto"; } })();
  if (!counts[tab]) tab = "crypto";

  main.innerHTML = `
    <h1>Graphiques</h1>
    <p class="muted">${insts.length ? `<b>${insts.length} paires</b> disponibles sur Kraken Pro France${maj ? ` (liste mise à jour ${ago(maj)})` : ""}.` : "La liste arrive après le premier scan du bot."}
      Touche une paire pour ouvrir son graphique en direct, avec des outils pour apprendre à le lire.</p>
    <div class="onglets" role="tablist">
      ${ONGLETS.filter(([k]) => counts[k]).map(([k, t]) => `<button type="button" role="tab" class="onglet" data-tab="${k}" aria-selected="${k === tab}">${t} <span class="small">${counts[k]}</span></button>`).join("")}
    </div>
    <label class="champ section" style="margin-top:12px"><span>Chercher une paire</span>
      <input id="q" type="search" placeholder="BTC, SOL, TSLA, PAXG…" autocomplete="off" autocapitalize="characters" spellcheck="false"></label>
    <div id="liste" class="liste-paires"></div>
    <p class="small muted section">Les pastilles montrent ce que le bot pense de la paire au dernier scan (${scan ? ago(scan.created_at) : "pas encore de scan"}).
      Les autres paires ne sont pas analysées en profondeur à chaque scan. Variation : depuis minuit UTC (spot) ou sur 24 h (futures).</p>`;

  const liste = main.querySelector("#liste");
  const q = main.querySelector("#q");
  let token = 0;

  const draw = async () => {
    const txt = q.value.trim();
    // Recherche : toutes classes confondues. Sinon : l'onglet, paires suivies par le bot d'abord, puis les plus connues.
    const l = txt ? searchInstruments(insts, txt, 60)
      : (() => {
        const pop = searchInstruments(insts.filter((i) => classe(i) === tab), "", 1e6);
        const rest = insts.filter((i) => classe(i) === tab && !pop.includes(i)).sort((a, b) => String(a.display).localeCompare(String(b.display)));
        return [...pop, ...rest].sort((a, b) => (opp.has(b.display) - opp.has(a.display)));
      })();
    main.querySelectorAll("[data-tab]").forEach((b) => { b.setAttribute("aria-selected", String(!txt && b.dataset.tab === tab)); });
    liste.innerHTML = l.length ? l.map((i) => {
      const o = opp.get(i.display);
      const st = o ? (o.state === "LONG" ? ["long", "bot : long"] : o.state === "SHORT" ? ["short", "bot : short"]
        : o.state?.startsWith("SURV") ? ["ambre", "bot : à surveiller"] : ["", "bot : attendre"]) : null;
      return `<a class="paire" href="${lienGraph(i)}" data-key="${esc(i.key)}">
        <span class="paire-nom"><b>${esc(i.display)}</b>
          <span class="small muted">${i.venue === "futures" ? "futures" : "spot"}${i.can_short ? " · short" : ""}${i.max_leverage > 1 ? ` · levier max ×${i.max_leverage}` : ""}</span></span>
        <span class="paire-prix num" data-prix>${st ? `<span class="pastille ${st[0]}">${esc(st[1])}</span>` : ""}</span>
        <span class="fleche-d" aria-hidden="true">›</span></a>`;
    }).join("") : `<p class="muted">Aucune paire « ${esc(txt)} » sur Kraken France.</p>`;
    // Prix en direct des premières paires affichées (vrais prix Kraken, rien si indisponible).
    const mine = ++token;
    const firsts = l.slice(0, NB_PRIX);
    if (!firsts.length) return;
    const px = await prices(firsts, { fx: false }).catch(() => null);
    if (!px || mine !== token) return;
    for (const i of firsts) {
      const p = px.get(i);
      const el = liste.querySelector(`[data-key="${CSS.escape(i.key)}"] [data-prix]`);
      if (!el || !p?.last) continue;
      const ch = p.open > 0 ? ((p.last - p.open) / p.open) * 100 : null;
      el.insertAdjacentHTML("afterbegin", `<span>${pq(p.last, i.quote)}</span>${ch != null ? `<span class="small ${ch >= 0 ? "gain" : "perte"}">${ch >= 0 ? "+" : ""}${ch.toLocaleString("fr-FR", { maximumFractionDigits: 2 })} %</span>` : ""}`);
    }
  };

  main.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => {
    tab = b.dataset.tab;
    q.value = "";
    try { localStorage.setItem("ldk-onglet", tab); } catch { /* sans stockage */ }
    history.replaceState(null, "", `#/graphiques/${tab}`);
    draw();
  }));
  let t = 0;
  q.addEventListener("input", () => { clearTimeout(t); t = setTimeout(draw, 150); });
  draw();
}
