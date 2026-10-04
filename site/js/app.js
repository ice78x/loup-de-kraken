// Point d'entrée : connexion, navigation entre les pages, structure (menu, barre d'onglets).
// Pour ajouter une page : créer js/views/mapage.js (export async function render(main, ctx, ...params))
// puis l'ajouter dans ROUTES et, si besoin, dans NAV.
import { backend, DEMO } from "./data.js";
import { esc, toast } from "./ui.js";
import { majSolde } from "./solde.js";
import { setMode, setPerps } from "./fees.js";
import * as home from "./views/home.js";
import * as signal from "./views/signal.js";
import * as trades from "./views/trades.js";
import * as trade from "./views/trade.js";
import * as newtrade from "./views/newtrade.js";
import * as markets from "./views/markets.js";
import * as chart from "./views/chart.js";
import * as club from "./views/club.js";
import * as bot from "./views/bot.js";
import * as ideas from "./views/ideas.js";
import * as learn from "./views/learn.js";
import * as account from "./views/account.js";
import * as auth from "./views/auth.js";

const I = {
  home: '<path d="M3 11 12 4l9 7v9h-6v-6H9v6H3z"/>',
  trades: '<path d="M4 19V9m6 10V5m6 14v-7m4 7H2"/>',
  club: '<circle cx="9" cy="8" r="3.2"/><circle cx="17" cy="9" r="2.4"/><path d="M3 20c0-3.3 2.7-5.5 6-5.5s6 2.2 6 5.5M15 15.2c.6-.2 1.3-.3 2-.3 2.6 0 4 1.7 4 4.6"/>',
  bot: '<rect x="4" y="7" width="16" height="12" rx="3"/><path d="M12 3v4M9 12h.01M15 12h.01M9 16h6"/>',
  idea: '<path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1v.5h5V16c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z"/>',
  chart: '<path d="M4 20V4M4 20h16"/><path d="M8 15l3-4 3 2 5-6"/>',
  learn: '<path d="M3 6l9-3 9 3-9 3zM7 8v5c0 1.7 2.2 3 5 3s5-1.3 5-3V8"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-6.5 8-6.5s8 2.5 8 6.5"/>',
};
const icon = (k) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${I[k]}</svg>`;

const NAV = [
  // [lien, icône, libellé, libellé court pour la barre d'onglets du téléphone]
  ["#/", "home", "Accueil"], ["#/graphiques", "chart", "Graphiques"], ["#/trades", "trades", "Mes trades", "Trades"], ["#/club", "club", "Le club", "Club"],
  ["#/idees", "idea", "Idées"], ["#/apprendre", "learn", "Apprendre"],
];
const ROUTES = [
  [/^#?\/?$/, home, "#/"], [/^#\/signal\/(\d+)$/, signal, "#/"], [/^#\/trades$/, trades, "#/trades"],
  [/^#\/trade\/nouveau$/, newtrade, "#/trades"], [/^#\/trade\/nouveau\/(.+)$/, newtrade, "#/trades"], [/^#\/trade\/(\d+)$/, trade, "#/trades"],
  [/^#\/club$/, club, "#/club"], [/^#\/membre\/([\w-]+)$/, club, "#/club"], [/^#\/bot$/, bot, "#/compte"], [/^#\/idees$/, ideas, "#/idees"],
  [/^#\/apprendre$/, learn, "#/apprendre"], [/^#\/(?:marches|graphiques)$/, markets, "#/graphiques"],
  [/^#\/graphiques\/(\w+)$/, markets, "#/graphiques"], [/^#\/graphique\/(.+)$/, chart, "#/graphiques"], [/^#\/compte$/, account, "#/compte"],
];

const ctx = {
  me: null,
  leave: [],
  onLeave(fn) { this.leave.push(fn); },
  go(hash) { location.hash = hash; },
  async refreshMe() { this.me = await backend.me(); return this.me; },
};

const banner = DEMO ? '<div class="demo-banner">Mode démo : données fictives. Configure Supabase pour activer le vrai site (guide, étape 3).</div>' : "";

function shell() {
  const links = NAV.map(([h, ic, label]) => `<a href="${h}" data-nav="${h}">${icon(ic)}<span>${label}</span></a>`).join("");
  const tabs = NAV.map(([h, ic, label, court]) => `<a href="${h}" data-nav="${h}">${icon(ic)}<span>${court || label}</span></a>`).join("");
  return `${banner}
  <div class="shell">
    <aside class="sidebar">
      <a class="brand" href="#/"><img src="img/logo.svg" alt=""><strong>Le Loup de Kraken<span>club privé</span></strong></a>
      <nav class="nav" aria-label="Navigation principale">${links}</nav>
      <nav class="nav me"><a href="#/compte" data-nav="#/compte">${icon("user")}<span id="me-name">${esc(ctx.me?.pseudo)}</span></a></nav>
    </aside>
    <header class="topbar">
      <a class="brand" href="#/"><img src="img/logo.svg" alt=""><strong>Le Loup de Kraken</strong></a>
      <a class="btn discret" href="#/compte" aria-label="Mon compte">${icon("user")}</a>
    </header>
    <main id="main" tabindex="-1"></main>
    <nav class="tabbar" aria-label="Navigation">${tabs}</nav>
  </div>`;
}

async function route() {
  ctx.leave.splice(0).forEach((fn) => { try { fn(); } catch { /* rien */ } });
  const root = document.getElementById("app");
  const session = await backend.session();
  lastUid = session?.user?.id || null;
  if (!session) { root.innerHTML = banner + '<div id="main"></div>'; return auth.render(document.getElementById("main"), ctx); }
  if (!ctx.me) {
    try { await ctx.refreshMe(); } catch (e) { toast(e.message, true); }
  }
  if (!ctx.me?.approved) { root.innerHTML = banner + '<div id="main"></div>'; return auth.renderPending(document.getElementById("main"), ctx); }
  // Solde à jour avec les gains/pertes des trades (recalculé à chaque page, rien n'est modifié dans la base).
  // Trades d'entraînement : TP / SL touchés depuis le dernier passage du bot → enregistrés avant de calculer le solde.
  try {
    const { rattraper } = await import("./suivi.js");
    const { ohlc } = await import("./market.js");
    if (!DEMO) await rattraper(backend, ohlc, ctx.me?.id); // en démo, les bougies sont fictives : on ne touche à rien
  } catch { /* le bot s'en chargera à son prochain passage */ }
  try { await majSolde(ctx, backend); } catch { /* on garde le solde enregistré */ }
  setMode(ctx.me?.trade_mode); // frais / levier / liquidation : futures perpétuels par défaut, ou spot (Mon compte)
  if (!perpsCharges) { perpsCharges = true; try { setPerps(await backend.perps()); } catch { perpsCharges = false; } }
  if (!document.querySelector(".shell")) root.innerHTML = shell();
  const hash = location.hash || "#/";
  const match = ROUTES.find(([re]) => re.test(hash));
  const [re, view, navKey] = match || ROUTES[0];
  document.querySelectorAll("[data-nav]").forEach((a) =>
    a.dataset.nav === navKey ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
  const main = document.getElementById("main");
  main.innerHTML = '<p class="vide">Chargement…</p>';
  const params = match ? hash.match(re).slice(1) : [];
  try {
    await view.render(main, ctx, ...params);
  } catch (e) {
    console.error(e);
    main.innerHTML = `<div class="alerte rouge"><strong>Cette page n'a pas pu se charger.</strong><p>${esc(e.message)}</p>
      <button class="btn" onclick="location.reload()">Recharger</button></div>`;
  }
  const nameEl = document.getElementById("me-name");
  if (nameEl) nameEl.textContent = ctx.me?.pseudo || "";
  window.scrollTo(0, 0);
}

let lastUid;
let perpsCharges = false;
backend.onAuth(async (s) => {
  const uid = s?.user?.id || null;
  if (uid === lastUid) return; // même personne : on ne recharge pas la page
  ctx.me = null;
  document.getElementById("app").innerHTML = "";
  await route();
});
window.addEventListener("hashchange", route);
route();

if ("serviceWorker" in navigator && !DEMO && location.protocol === "https:") navigator.serviceWorker.register("sw.js").catch(() => {});
