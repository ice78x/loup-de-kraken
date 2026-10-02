// Détail d'un signal : graphique, échelle de prix, explications simples, formulaire pour le prendre.
import { backend } from "../data.js";
import { goLive } from "../live.js";
import { LEGENDE, chiffres, etat, idee, levierBadge, levierConseille, planTable } from "../setup.js";
import { perpSymbol, venueEffective } from "../fees.js";
import { eurPerQuote, krakenLink, prices } from "../market.js";
import { STRAT, ago, dt, esc, pq, px } from "../ui.js";
import { tradeForm } from "./tradeform.js";
import { newsBlock } from "./home.js";

export async function render(main, ctx, id) {
  const s = await backend.signal(id);
  if (!s) { main.innerHTML = '<div class="vide"><strong>Signal introuvable</strong>Il a peut-être été supprimé (plus de 60 jours).</div>'; return; }
  const [mine, px0, known] = await Promise.all([backend.trades({ userId: ctx.me.id, limit: 300 }), prices([s]),
    backend.instrument(s.instrument_key).catch(() => null)]);
  const maxLev = known ? +known.max_leverage || 1 : 10;
  const lev = levierConseille(s, ctx.me, maxLev).lev;
  const live = px0.get(s);
  const price = live?.last ?? null;
  const expired = s.expires_at && new Date(s.expires_at) < new Date();
  const dir = s.direction === "LONG" ? "long" : "short";
  const epq = eurPerQuote(s.quote, px0) ?? s.eur_per_quote;

  main.innerHTML = `
    <a href="#/" class="muted small">← Accueil</a>
    <div class="ligne entre" style="margin-top:8px">
      <h1 style="margin:0"><span class="${dir === "long" ? "gain" : "perte"}">${s.direction === "LONG" ? "LONG ↑" : "SHORT ↓"}</span> ${esc(s.display)}</h1>
      <span class="pastille ${etat(s, expired ? { code: "expire" } : null)[0]}" data-etat>${etat(s, expired ? { code: "expire" } : null)[1]}</span>
    </div>
    <p class="muted">${esc(STRAT[s.strategy] || s.strategy)} · score ${Math.round(s.score)}/100 · détecté ${ago(s.created_at)} (${dt(s.created_at)})
      ${price ? ` · prix actuel <b class="num">${pq(price, s.quote)}</b>` : px0.error ? ` · prix en direct indisponible` : ""}</p>

    <p class="setup-idee grand">${idee(s)}</p>
    <div class="feu" id="phase"><span class="feu-icone">…</span><div><strong>Lecture du prix Kraken…</strong></div></div>

    <figure class="section"><div class="graph setup-graph grand" id="chart"></div>
      ${LEGENDE}
      <figcaption class="small muted" id="chart-note">Chargement des bougies Kraken…</figcaption>
      <p class="small muted">Les pointillés montrent le <b>plan</b> du bot (et ce qui se passe s'il rate), pas une prédiction :
      le marché peut faire autre chose. C'est le stop qui limite la perte.</p></figure>

    <section class="section grille">
      <div class="bloc pile"><h2>Ce que tu risques, ce que tu peux gagner</h2>${levierBadge(s, ctx.me, maxLev)}${chiffres(s, ctx.me, maxLev)}
        <p class="small muted">En % de ta <b>mise</b> (l'argent bloqué sur le trade), frais Kraken compris, objectifs encaissés 30 / 40 / 30 %.
          Touche un autre levier pour voir l'effet.</p></div>
      <div class="bloc pile"><h2>Les niveaux</h2>${planTable(s, lev)}</div>
    </section>

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
        ${(s.sources || []).map(newsBlock).join("")}
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
          <li>${venueEffective(s) === "futures" ? `Onglet <b>Futures</b>, cherche <b>${esc(perpSymbol(s))}</b> (le perpétuel de ${esc(s.display)}).` : `Cherche <b>${esc(s.display)}</b>.`}</li>
          <li>Choisis <b>${s.direction === "LONG" ? "Acheter" : "Vendre"}</b>, type d'ordre <b>Limite</b>, prix dans la zone d'entrée.</li>
          <li>Entre la <b>quantité</b> choisie ici, après avoir vérifié ta perte au stop (pas un montant au hasard).</li>
          <li>Levier : <b>x${lev}</b>${lev > 1 ? " en marge <b>isolée</b>" : " (pas de levier)"}${s.direction === "SHORT" && venueEffective(s) === "spot" ? " — un SHORT en spot demande au moins x2" : ""}.</li>
          <li>Ajoute tout de suite un ordre <b>stop-loss</b> à ${pq(s.sl, s.quote)}, puis tes ordres limite de sortie aux TP.</li>
          <li>Reviens ici et enregistre le trade en mode <b>Réel</b> pour le suivre.</li>
        </ol>
        <a class="btn" href="${krakenLink(s)}" target="_blank" rel="noopener">Ouvrir ${esc(s.display)} sur Kraken</a>
      </div>
    </section>`;

  ctx.onLeave(goLive([{ s, chartEl: main.querySelector("#chart"), phaseEl: main.querySelector("#phase"), noteEl: main.querySelector("#chart-note") }],
    { interactive: true, bars: 64 }));

  const inst = { instrument_key: s.instrument_key, display: s.display, venue: s.venue, api_symbol: s.api_symbol,
    api_asset_class: s.api_asset_class, asset_class: s.asset_class, quote: s.quote, can_short: true, max_leverage: 10 };
  if (known) Object.assign(inst, { base: known.base, can_short: known.can_short, max_leverage: known.max_leverage || 1, lot_decimals: known.lot_decimals, ordermin: known.ordermin });
  // Frais : grille officielle Kraken selon le marché (fees.js).
  tradeForm(main.querySelector("#form"), { me: ctx.me, trades: mine, inst, signal: s, price, eurPerQuote: epq, levRef: lev, go: ctx.go });
}
