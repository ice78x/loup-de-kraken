// Trade manuel : tu choisis l'actif, le sens, l'entrée, le SL, les TP et le multiplicateur.
import { backend } from "../data.js";
import { eurPerQuote, prices } from "../market.js";
import { esc } from "../ui.js";
import { tradeForm } from "./tradeform.js";

export async function render(main, ctx) {
  const [insts, mine] = await Promise.all([backend.instruments(), backend.trades({ userId: ctx.me.id, limit: 300 })]);
  main.innerHTML = `
    <a href="#/trades" class="muted small">← Mes trades</a>
    <h1>Nouveau trade manuel</h1>
    <p class="muted">Choisis un actif disponible sur Kraken. Le site calcule la bonne taille pour ton risque.</p>
    <div class="bloc">
      <label class="champ"><span>Actif</span>
        <input id="q" list="insts" placeholder="Tape BTC, ETH, TSLA, PAXG…" autocomplete="off">
        <datalist id="insts">${insts.map((i) => `<option value="${esc(i.display)}">${esc(i.asset_class)} · ${esc(i.venue)}</option>`).join("")}</datalist>
        <small>${insts.length ? `${insts.length} paires disponibles en France, lues chez Kraken · <a href="#/marches">voir la liste</a>` : "La liste arrive après le premier scan du bot."}</small>
      </label>
      <div id="form" style="margin-top:16px"></div>
    </div>`;
  const q = main.querySelector("#q");
  const host = main.querySelector("#form");
  const pick = async () => {
    const inst = insts.find((i) => i.display.toLowerCase() === q.value.trim().toLowerCase());
    if (!inst) { host.innerHTML = ""; return; }
    host.innerHTML = '<p class="muted">Récupération du prix…</p>';
    const px = await prices([inst]);
    const p = px.get(inst);
    const epq = eurPerQuote(inst.quote, px);
    if (!epq) { host.innerHTML = `<p class="alerte rouge">Taux de conversion ${esc(inst.quote)} → € indisponible pour l'instant. Réessaie dans un moment.</p>`; return; }
    tradeForm(host, { me: ctx.me, trades: mine, inst: { ...inst, instrument_key: inst.key }, price: p?.last ?? null, eurPerQuote: epq,
      feeTaker: inst.venue === "futures" ? 0.05 : 0.4, feeMaker: inst.venue === "futures" ? 0.02 : 0.25, go: ctx.go });
  };
  q.addEventListener("change", pick);
  q.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); pick(); } });
}
