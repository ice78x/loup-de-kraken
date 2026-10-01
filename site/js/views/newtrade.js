// Trade manuel : tu choisis l'actif, le sens, l'entrée, le SL, les TP et le multiplicateur.
import { backend } from "../data.js";
import { eurPerQuote, prices } from "../market.js";
import { searchInstruments } from "../search.js";
import { esc } from "../ui.js";
import { tradeForm } from "./tradeform.js";

const CLASSE = { crypto: "crypto", xstock: "action", commodity: "matière première" };

export async function render(main, ctx) {
  const [insts, mine] = await Promise.all([backend.instruments(), backend.trades({ userId: ctx.me.id, limit: 300 })]);
  main.innerHTML = `
    <a href="#/trades" class="muted small">← Mes trades</a>
    <h1>Nouveau trade manuel</h1>
    <p class="muted">Choisis un actif disponible sur Kraken. Le site calcule la bonne taille pour ton risque.</p>
    <div class="bloc">
      <label class="champ"><span>Actif</span>
        <input id="q" type="search" placeholder="Tape BTC, ETH, TSLA, PAXG…" autocomplete="off" autocapitalize="characters" spellcheck="false">
        <small>${insts.length ? `${insts.length} paires disponibles en France, lues chez Kraken · <a href="#/marches">voir la liste</a>` : "La liste arrive après le premier scan du bot."}</small>
      </label>
      <div id="choix" class="choix"></div>
      <div id="form" style="margin-top:16px"></div>
    </div>`;
  const q = main.querySelector("#q");
  const list = main.querySelector("#choix");
  const host = main.querySelector("#form");
  let found = [];

  const pick = async (inst) => {
    q.value = inst.display;
    list.innerHTML = "";
    q.blur();
    host.innerHTML = '<p class="muted">Récupération du prix…</p>';
    const px = await prices([inst]);
    const p = px.get(inst);
    const epq = eurPerQuote(inst.quote, px);
    if (!epq) { host.innerHTML = `<p class="alerte rouge">Taux de conversion ${esc(inst.quote)} → € indisponible pour l'instant. Réessaie dans un moment.</p>`; return; }
    tradeForm(host, { me: ctx.me, trades: mine, inst: { ...inst, instrument_key: inst.key }, price: p?.last ?? null, eurPerQuote: epq,
      feeTaker: inst.venue === "futures" ? 0.05 : 0.4, feeMaker: inst.venue === "futures" ? 0.02 : 0.25, go: ctx.go });
  };

  const show = () => {
    found = searchInstruments(insts, q.value);
    if (!q.value.trim()) { list.innerHTML = ""; return; }
    list.innerHTML = found.length ? found.map((i, n) => `<button type="button" class="marche" data-n="${n}">
        <b>${esc(i.display)}</b>
        <span class="small muted">${esc(CLASSE[i.asset_class] || "autre")} · ${i.venue === "futures" ? "futures" : "spot"}${i.can_short ? " · short possible" : ""}${i.max_leverage > 1 ? ` · levier ×${i.max_leverage}` : ""}</span>
      </button>`).join("")
      : `<p class="muted small">Aucune paire « ${esc(q.value.trim())} » disponible sur Kraken France. <a href="#/marches">Voir la liste</a></p>`;
  };

  q.addEventListener("input", () => { host.innerHTML = ""; show(); });
  q.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); if (found[0]) pick(found[0]); } });
  list.addEventListener("click", (e) => {
    const b = e.target.closest("[data-n]");
    if (b) pick(found[+b.dataset.n]);
  });
}
