// Détail d'un signal : graphique, échelle de prix, explications simples, formulaire pour le prendre.
import { candleChart, levelLines } from "../charts.js";
import { backend } from "../data.js";
import { ladder } from "../ladder.js";
import { eurPerQuote, krakenLink, ohlc, prices } from "../market.js";
import { STRAT, ago, dt, esc, pq, px } from "../ui.js";
import { tradeForm } from "./tradeform.js";

export async function render(main, ctx, id) {
  const s = await backend.signal(id);
  if (!s) { main.innerHTML = '<div class="vide"><strong>Signal introuvable</strong>Il a peut-être été supprimé (plus de 60 jours).</div>'; return; }
  const [mine, px0] = await Promise.all([backend.trades({ userId: ctx.me.id, limit: 300 }), prices([s])]);
  const live = px0.get(s);
  const price = live?.last ?? null;
  const expired = s.expires_at && new Date(s.expires_at) < new Date();
  const dir = s.direction === "LONG" ? "long" : "short";
  const epq = eurPerQuote(s.quote, px0) ?? s.eur_per_quote;

  main.innerHTML = `
    <a href="#/" class="muted small">← Accueil</a>
    <div class="ligne entre" style="margin-top:8px">
      <h1 style="margin:0"><span class="${dir === "long" ? "gain" : "perte"}">${s.direction === "LONG" ? "LONG ↑" : "SHORT ↓"}</span> ${esc(s.display)}</h1>
      ${s.status === "TRADE" ? (expired ? '<span class="pastille">expiré : ne plus entrer sans nouveau scan</span>' : '<span class="pastille long">🟢 trade validé</span>')
        : '<span class="pastille ambre">🟡 à surveiller : pas encore d\'entrée</span>'}
    </div>
    <p class="muted">${esc(STRAT[s.strategy] || s.strategy)} · score ${Math.round(s.score)}/100 · détecté ${ago(s.created_at)} (${dt(s.created_at)})
      ${price ? ` · prix actuel <b class="num">${pq(price, s.quote)}</b>` : px0.error ? ` · prix en direct indisponible` : ""}</p>

    <div class="split">
      <figure><div class="graph" id="chart"></div>
        <figcaption>Bougies de 15 minutes. Jaune = zone d'entrée, rouge = stop, vert = objectifs.</figcaption></figure>
      <div class="bloc">${ladder({ direction: s.direction, entryLow: s.entry_low, entryHigh: s.entry_high, sl: s.sl, tps: [s.tp1, s.tp2, s.tp3], price, anim: true })}</div>
    </div>

    <section class="section grille">
      <div class="bloc pile">
        <h2>Le plan en clair</h2>
        <p><b>Entrer</b> entre ${pq(s.entry_low, s.quote)} et ${pq(s.entry_high, s.quote)}. ${esc(s.action || "")}</p>
        <p><b>Couper</b> à ${pq(s.sl, s.quote)} si ça tourne mal. ${esc(s.invalidation || "")}.</p>
        <p><b>Encaisser</b> 30 % à ${pq(s.tp1, s.quote)}, 40 % à ${pq(s.tp2, s.quote)}, le reste à ${pq(s.tp3, s.quote)}.</p>
        ${s.quote && s.quote !== "EUR" ? `<p class="small muted">Prix en ${esc(s.quote)}. Ton risque, lui, est calculé en euros avec le taux EUR/USD du moment.</p>` : ""}
        <p class="muted small">Après le TP1 : remonte le SL au prix d'entrée seulement si le graphique confirme (le bot te le dira dans « Mes trades »).</p>
      </div>
      <div class="bloc pile">
        <h2>Pourquoi le bot le propose</h2>
        <ul>${(s.reasons || []).map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
        <p><b>Catalyseur :</b> ${esc(s.catalyst || "aucun")}</p>
        ${(s.sources || []).map((n) => `<details><summary>${esc(n.title)}</summary><p><b>Fait :</b> ${esc(n.fact)}</p>
          <p class="muted"><b>Interprétation :</b> ${esc(n.interpretation)}</p>${n.url ? `<a href="${esc(n.url)}" target="_blank" rel="noopener">Source (${esc(n.source)})</a>` : ""}</details>`).join("")}
        ${s.edge_note ? `<p class="small muted">${esc(s.edge_note)}</p>` : ""}
        ${(s.warnings || []).length ? `<div class="alerte"><ul>${s.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>` : ""}
      </div>
    </section>

    <section class="section grille">
      <div class="bloc">
        <h2>${s.status === "TRADE" ? "Prendre ce trade" : "Préparer ce trade"}</h2>
        ${s.status === "WATCH" ? `<p class="alerte">Pas encore confirmé : ${esc(s.trigger_text || "attends la bougie 15 min de confirmation")}.</p>` : ""}
        ${expired ? '<p class="alerte">Ce signal a plus de 4 heures : les niveaux ne sont peut-être plus valables.</p>' : ""}
        <div id="form"></div>
      </div>
      <div class="bloc pile">
        <h2>Le passer sur ton téléphone</h2>
        <ol>
          <li>Ouvre l'app <b>Kraken</b> et passe en mode <b>Pro</b>.</li>
          <li>Cherche <b>${esc(s.display)}</b>.</li>
          <li>Choisis <b>${s.direction === "LONG" ? "Acheter" : "Vendre"}</b>, type d'ordre <b>Limite</b>, prix dans la zone d'entrée.</li>
          <li>Entre la <b>quantité</b> calculée ici (pas un montant au hasard).</li>
          ${s.direction === "SHORT" ? "<li>Un SHORT se fait avec de la marge (levier) : choisis le même multiplicateur qu'ici.</li>" : ""}
          <li>Ajoute tout de suite un ordre <b>stop-loss</b> à ${pq(s.sl, s.quote)}, puis tes ordres limite de sortie aux TP.</li>
          <li>Reviens ici et enregistre le trade en mode <b>Réel</b> pour le suivre.</li>
        </ol>
        <a class="btn" href="${krakenLink(s)}" target="_blank" rel="noopener">Ouvrir ${esc(s.display)} sur Kraken</a>
      </div>
    </section>`;

  const el = main.querySelector("#chart");
  const draw = (candles) => candleChart(el, candles, { lines: levelLines({ entryLow: s.entry_low, entryHigh: s.entry_high, sl: s.sl, tps: [s.tp1, s.tp2, s.tp3] }) });
  let chart = draw(s.candles || []);
  ohlc(s, 15).then((c) => { if (c?.length && el.isConnected) { chart.remove(); chart = draw(c.slice(-160)); } }).catch(() => {});
  ctx.onLeave(() => chart.remove());

  const inst = { instrument_key: s.instrument_key, display: s.display, venue: s.venue, api_symbol: s.api_symbol,
    api_asset_class: s.api_asset_class, asset_class: s.asset_class, quote: s.quote, can_short: true, max_leverage: 10 };
  const insts = await backend.instruments().catch(() => []);
  const known = insts.find((i) => i.key === s.instrument_key);
  if (known) Object.assign(inst, { can_short: known.can_short, max_leverage: known.max_leverage || 1, lot_decimals: known.lot_decimals, ordermin: known.ordermin });
  tradeForm(main.querySelector("#form"), { me: ctx.me, trades: mine, inst, signal: s, price, eurPerQuote: epq,
    feeTaker: s.fee_taker_pct ?? (s.venue === "futures" ? 0.05 : 0.4), feeMaker: s.fee_maker_pct ?? (s.venue === "futures" ? 0.02 : 0.25), go: ctx.go });
}
