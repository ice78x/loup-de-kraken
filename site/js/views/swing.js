// Page SWING : positions de plusieurs jours du bot, preuve (backtest swing), et formulaire pour suivre une position.
import { backend } from "../data.js";
import { eurPerQuote, krakenLink, prices } from "../market.js";
import { levierConseille } from "../setup.js";
import { confiance, entreeOuverte, etatSwing, isLong, nomSwing, refPos, swingBacktestBlock, swingCard } from "../swing.js";
import { dt, esc, pq } from "../ui.js";

const jj = (d) => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(d || "")); return m ? `${m[3]}/${m[2]}` : esc(d); };
import { tradeForm } from "./tradeform.js";

export async function render(main, ctx, id = null) {
  if (id) return detail(main, ctx, id);
  const [pos, run] = await Promise.all([backend.swingPositions(), backend.latestSwing().catch(() => null)]);
  const px = await prices(pos.filter((p) => p.status === "ouvert").map(refPos), { fx: false });
  const ouvertes = pos.filter((p) => p.status === "ouvert");
  const finies = pos.filter((p) => p.status !== "ouvert").slice(0, 20);
  const total = finies.filter((p) => p.status === "clos").reduce((a, p) => a + (+p.r || 0), 0);
  main.innerHTML = `
    <a href="#/" class="muted small">← Accueil</a>
    <h1>📈 Swing : trades de plusieurs jours</h1>
    <p class="muted">Le bot regarde les bougies <b>journalières</b> une fois par jour, juste après minuit (heure de Kraken, 2 h à Paris).
      Il entre quand le prix casse son plus haut de plusieurs semaines, puis <b>remonte le stop chaque matin</b> pour suivre la tendance.
      Pas d'objectif fixe : on garde tant que ça monte. Gagne souvent peu de fois, mais les gains sont gros.</p>
    <h2>En cours (${ouvertes.length})</h2>
    ${ouvertes.length ? `<div class="grille">${ouvertes.map((p) => swingCard(p, px.get(refPos(p))?.last ?? null)).join("")}</div>`
      : `<div class="vide"><strong>Aucune position swing</strong>Rien à faire : le bot attend une cassure propre.</div>`}
    <h2 class="section">Terminées</h2>
    ${finies.length ? `<p class="small">Total des positions terminées : <b>${(total >= 0 ? "+" : "") + total.toFixed(2).replace(".", ",")} R</b></p>
      <div class="grille">${finies.map((p) => swingCard(p, null)).join("")}</div>` : '<p class="muted small">Aucune pour l\'instant.</p>'}
    <section class="section"><h2>📊 La preuve (backtest swing)</h2>${swingBacktestBlock(run)}</section>`;
}

async function detail(main, ctx, id) {
  const p = await backend.swingPosition(id);
  if (!p) { main.innerHTML = '<div class="vide"><strong>Position introuvable</strong></div>'; return; }
  const [mine, px, known] = await Promise.all([backend.trades({ userId: ctx.me.id, limit: 300 }), prices([refPos(p)]),
    backend.instrument(p.instrument_key).catch(() => null)]);
  const price = px.get(refPos(p))?.last ?? null;
  const e = etatSwing(p, price);
  const sig = { ...refPos(p), id: null, status: "TRADE", strategy: "swing", sl: +p.stop_current, tp1: null, tp2: null, tp3: null };
  const maxLev = known ? +known.max_leverage || 1 : 10;
  const lev = levierConseille(sig, ctx.me, maxLev).lev;
  const hist = [...(p.history || [])].reverse().slice(0, 30);
  main.innerHTML = `
    <a href="#/swing" class="muted small">← Swing</a>
    <div class="ligne entre" style="margin-top:8px">
      <h1 style="margin:0"><span class="${isLong(p) ? "gain" : "perte"}">${isLong(p) ? "LONG ↑" : "SHORT ↓"}</span> ${esc(nomSwing(p))} <span class="small muted">swing</span></h1>
      <span class="pastille ${e.ton}">${e.icone} ${esc(e.titre)}</span>
    </div>
    <p class="setup-idee grand">${e.texte}</p>
    ${confiance(p) ? `<p>${confiance(p)} <span class="small muted">Plus la confiance est haute, meilleurs étaient ces trades dans le passé
      (sur des données jamais vues : 1/4 ≈ −0,2 R, 2/4 ≈ +0,4 R, 3/4 et 4/4 ≈ +1,3 R par trade). Ce n'est pas une certitude.</span></p>` : ""}
    ${p.demo ? '<p class="alerte small">DÉMO : position fictive.</p>' : ""}
    <section class="section grille">
      <div class="bloc pile"><h2>Le plan</h2>
        <p><b>Signal</b> : clôture du ${jj(p.signal_date)} à ${pq(p.signal_close, p.quote)}, au-delà du ${p.variant?.includes("55") ? "plus haut de 55 jours" : "plus haut de 20 jours"}.</p>
        <p><b>Entrer</b> entre ${pq(p.entry_low, p.quote)} et ${pq(p.entry_high, p.quote)} (jusqu'à 2 jours après le signal).</p>
        <p><b>Stop</b> de départ ${pq(p.stop_initial, p.quote)} · <b>stop actuel ${pq(p.stop_current, p.quote)}</b>.</p>
        <p class="small muted">Chaque matin, le bot remonte le stop au plus bas des derniers jours (jamais il ne le recule).
          Tu reçois le nouveau stop sur Telegram : déplace ton ordre stop sur Kraken.</p></div>
      <div class="bloc pile"><h2>Le stop jour par jour</h2>
        ${hist.length ? `<div class="table-wrap"><table><thead><tr><th>Jour</th><th class="d">Clôture</th><th class="d">Stop</th></tr></thead>
          <tbody>${hist.map((h) => `<tr><td>${jj(h.date)}</td><td class="d num">${pq(h.close, p.quote)}</td><td class="d num">${pq(h.stop, p.quote)}</td></tr>`).join("")}</tbody></table></div>`
          : '<p class="muted small">Premier point demain matin.</p>'}
      </div>
    </section>
    ${entreeOuverte(p) ? `<section class="section grille">
      <div class="bloc"><h2>Prendre cette position</h2><div id="form"></div></div>
      <div class="bloc pile"><h2>Sur Kraken</h2><ol>
        <li>App <b>Kraken</b> → mode <b>Pro</b> → onglet <b>Futures</b> → <b>${esc(p.display)}</b>.</li>
        <li><b>${isLong(p) ? "Acheter" : "Vendre"}</b>, ordre <b>Limite</b> dans la zone, la <b>quantité calculée ici</b>.</li>
        <li>Levier <b>x${lev}</b>${lev > 1 ? " en marge isolée" : ""}. Le levier ne change pas ta perte au stop.</li>
        <li>Ajoute un ordre <b>stop-loss à ${pq(p.stop_current, p.quote)}</b>. <b>Pas</b> d'ordre de sortie : le stop suit.</li>
        <li>Chaque matin : déplace le stop au niveau envoyé par le bot.</li></ol>
        <a class="btn" href="${krakenLink(refPos(p))}" target="_blank" rel="noopener">Ouvrir ${esc(p.display)} sur Kraken</a></div>
    </section>` : ""}
    <p class="small muted">Créée ${dt(p.created_at)}. Probabilité, pas garantie : la plupart des positions swing finissent par une petite perte, quelques-unes rapportent beaucoup.</p>`;
  if (!entreeOuverte(p)) return;
  const inst = { instrument_key: p.instrument_key, display: p.display, venue: "futures", api_symbol: p.display, asset_class: p.asset_class,
    quote: p.quote || "USD", can_short: true, max_leverage: maxLev };
  if (known) Object.assign(inst, { base: known.base, can_short: known.can_short, lot_decimals: known.lot_decimals, pair_decimals: known.pair_decimals, ordermin: known.ordermin });
  const epq = eurPerQuote(inst.quote, px);
  if (!epq) { main.querySelector("#form").innerHTML = '<p class="alerte rouge">Taux de conversion indisponible : réessaie dans un moment.</p>'; return; }
  const risque = +(p.history || [])[0]?.risque_pct || null;   // risque conseillé par le bot pour le swing (0,5 % ou 1 %)
  tradeForm(main.querySelector("#form"), { me: ctx.me, trades: mine, inst, signal: sig, swing: p, price, eurPerQuote: epq, levRef: lev,
    riskPct: risque, go: ctx.go });
}
