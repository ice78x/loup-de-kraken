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
    <p class="muted">Choisis un actif disponible sur Kraken, puis la quantité, comme sur Kraken. Le site te montre la marge, la perte possible et les frais.</p>
    <div class="bloc">
      <div class="champ"><span>Actif</span>
        <div class="deroulant" id="dd">
          <div class="saisie"><input id="q" type="search" placeholder="Choisir un actif…" autocomplete="off" autocapitalize="characters" spellcheck="false"
            role="combobox" aria-expanded="false" aria-controls="choix">
          <span class="fleche" aria-hidden="true">▾</span></div>
          <div id="choix" class="menu" role="listbox" hidden></div>
        </div>
        <small>${insts.length ? `${insts.length} paires disponibles en France, lues chez Kraken · <a href="#/marches">voir la liste</a>` : "La liste arrive après le premier scan du bot."}</small>
      </div>
      <div id="form" style="margin-top:16px"></div>
    </div>`;
  const q = main.querySelector("#q");
  const list = main.querySelector("#choix");
  const dd = main.querySelector("#dd");
  const host = main.querySelector("#form");
  let found = [];

  const close = () => { list.hidden = true; q.setAttribute("aria-expanded", "false"); dd.classList.remove("ouvert"); };
  const pick = async (inst) => {
    q.value = inst.display;
    close();
    q.blur();
    host.innerHTML = '<p class="muted">Récupération du prix…</p>';
    const px = await prices([inst]);
    const p = px.get(inst);
    const epq = eurPerQuote(inst.quote, px);
    if (!epq) { host.innerHTML = `<p class="alerte rouge">Taux de conversion ${esc(inst.quote)} → € indisponible pour l'instant. Réessaie dans un moment.</p>`; return; }
    tradeForm(host, { me: ctx.me, trades: mine, inst: { ...inst, instrument_key: inst.key }, price: p?.last ?? null, eurPerQuote: epq, go: ctx.go });
  };

  // Menu déroulant : s'ouvre au toucher (actifs populaires), puis s'affine à chaque lettre tapée.
  const show = () => {
    const txt = q.value.trim();
    found = searchInstruments(insts, txt, 40);
    list.innerHTML = (txt ? "" : '<p class="menu-titre">Les plus suivis — ou tape un nom</p>') + (found.length ? found.map((i, n) => `<button type="button" class="option" role="option" data-n="${n}">
        <b>${esc(i.display)}</b>
        <span class="small muted">${esc(CLASSE[i.asset_class] || "autre")} · ${i.venue === "futures" ? "futures" : "spot"}${i.can_short ? " · short" : ""}${i.max_leverage > 1 ? ` · ×${i.max_leverage}` : ""}</span>
      </button>`).join("")
      : `<p class="menu-titre">Aucune paire « ${esc(txt)} » sur Kraken France.</p>`);
    list.hidden = false;
    list.scrollTop = 0;
    q.setAttribute("aria-expanded", "true");
    dd.classList.add("ouvert");
  };
  const open = () => {
    if (q.value && found.some((i) => i.display === q.value)) q.select();
    show();
    // Remonte le champ en haut de l'écran pour que le menu reste visible au-dessus du clavier du téléphone.
    setTimeout(() => dd.scrollIntoView({ block: "start", behavior: "smooth" }), 250);
  };

  q.addEventListener("focus", open);
  q.addEventListener("click", () => { if (list.hidden) open(); });
  q.addEventListener("input", () => { host.innerHTML = ""; show(); });
  q.addEventListener("keyup", (e) => { if (e.key === "Escape") close(); });
  const outside = (e) => {
    if (!dd.isConnected) return document.removeEventListener("pointerdown", outside); // page quittée
    if (!dd.contains(e.target)) close();
  };
  document.addEventListener("pointerdown", outside);
  q.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); if (found[0]) pick(found[0]); } });
  list.addEventListener("click", (e) => {
    const b = e.target.closest("[data-n]");
    if (b) pick(found[+b.dataset.n]);
  });
}
