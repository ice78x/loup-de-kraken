// Détail d'un trade : graphique, conseil du bot, historique des évènements, actions (encaisser, bouger le SL, clôturer).
import { candleChart } from "../charts.js";
import { backend } from "../data.js";
import { ladder } from "../ladder.js";
import { krakenLink, ohlc, prices } from "../market.js";
import { TP_SPLIT, closePart, pnlBreakdown, recalculerFrais } from "../sizing.js";
import { krakenFees } from "../fees.js";
import { STRAT, busy, cls, dt, esc, eur, modal, nextScan, num, pq, px, rr, toast } from "../ui.js";
import { depuisDernierPassage, texteDepuis } from "../suivi.js";

const ev = (text) => ({ at: new Date().toISOString(), by: "membre", text });

export async function render(main, ctx, id) {
  const t = await backend.trade(id);
  if (!t) { main.innerHTML = '<a href="#/trades" class="muted small">← Mes trades</a><div class="vide"><strong>Trade introuvable</strong><p>Il a peut-être été supprimé.</p></div>'; return; }
  const mine = t.user_id === ctx.me.id;
  const px0 = await prices([t], { fx: false });
  const price = px0.get(t)?.last ?? null;
  const b = pnlBreakdown(t, price);
  const dir = t.direction === "LONG" ? "gain" : "perte";
  // Trade enregistré avec des frais plus hauts que ceux du marché utilisé (ex. frais spot alors que tu trades en futures) ?
  const grille = krakenFees(t);
  const nouveauPct = +t.fee_pct <= 0.4 + 1e-9 ? grille.maker : grille.taker;
  const refait = mine && t.status !== "annule" && +t.fee_pct > grille.taker + 1e-9 ? recalculerFrais(t, nouveauPct) : null;

  main.innerHTML = `
    <a href="${mine ? "#/trades" : `#/membre/${t.user_id}`}" class="muted small">← Retour</a>
    <div class="ligne entre" style="margin-top:8px">
      <h1 style="margin:0"><span class="${dir}">${t.direction === "LONG" ? "LONG ↑" : "SHORT ↓"}</span> ${esc(t.display)}</h1>
      <span class="pastille ${t.status === "ouvert" ? "ambre" : ""}">${t.status} · ${t.mode === "reel" ? "réel" : "paper"} · x${t.leverage}</span>
    </div>
    <p class="muted">${esc(t.profiles?.pseudo || "")} · ouvert le ${dt(t.opened_at)} · ${esc(STRAT[t.strategy] || t.strategy || "")}
      ${t.signal_id ? ` · <a href="#/signal/${t.signal_id}">voir le signal</a>` : ""}</p>

    <dl class="chiffres">
      <div><dt>Entrée</dt><dd class="num">${pq(+t.entry_price, t.quote)}</dd></div>
      <div><dt>Prix actuel</dt><dd class="num">${price ? pq(price, t.quote) : "—"}</dd></div>
      ${t.status === "ouvert" ? `<div><dt>Si tu fermes maintenant</dt><dd class="num ${cls(b.ifCloseNow)}">${b.ifCloseNow != null ? eur(b.ifCloseNow, true) : "—"}</dd></div>
      <div><dt>Mouvement du prix</dt><dd class="num ${cls(b.move)}">${b.move != null ? eur(b.move, true) : "—"}</dd></div>
      <div><dt>Frais (entrée + sortie ≈)</dt><dd class="num perte">${eur(-(b.entryFee + (b.exitFee || 0)), true)}</dd></div>
      ${Math.abs(b.banked) > 0.005 ? `<div><dt>TP encaissés</dt><dd class="num ${cls(b.banked)}">${eur(b.banked, true)}</dd></div>` : ""}` :
        `<div><dt>Résultat</dt><dd class="num ${cls(+t.realized_pnl_eur)}">${eur(+t.realized_pnl_eur, true)}</dd></div>`}
      ${t.status === "ouvert" ? "" :
        `<div><dt>Résultat en R</dt><dd class="num ${cls(+t.r_multiple)}">${rr(+t.r_multiple)}</dd></div>`}
      <div><dt>Risque initial</dt><dd class="num">${eur(+t.risk_eur)}</dd></div>
      <div><dt>Quantité restante</dt><dd class="num">${+(+t.qty_remaining).toPrecision(6)} / ${+(+t.qty).toPrecision(6)}</dd></div>
    </dl>

    ${refait ? `<div class="alerte" id="refrais"><b>⚠ Ce trade a été enregistré avec des frais de ${String(+t.fee_pct).replace(".", ",")} %</b> (grille spot).
      Si tu l'as passé en <b>futures perpétuels</b>, Kraken prend ${String(nouveauPct).replace(".", ",")} % : ${t.status === "ouvert" ? "déjà encaissé" : "résultat"}
      <b class="${cls(+t.realized_pnl_eur)}">${eur(+t.realized_pnl_eur, true)}</b> → <b class="${cls(refait.realized)}">${eur(refait.realized, true)}</b>.
      <p style="margin:8px 0 0"><button class="btn principal mini" id="refrais-ok">Recalculer avec les frais ${esc(grille.label)}</button></p></div>` : ""}

    ${t.status === "ouvert" && t.advice ? `<div class="alerte"><b>Conseil du bot</b> (${dt(t.advice_at)}) : ${esc(t.advice)}</div>` : ""}
    <div id="depuis" aria-live="polite"></div>

    <div class="split section">
      <figure><div class="graph" id="chart"></div><figcaption>Bougies 15 min en direct depuis Kraken.</figcaption></figure>
      <div class="bloc">${ladder({ direction: t.direction, entryLow: +t.entry_price, entryHigh: +t.entry_price, sl: +t.sl > 0 ? +t.sl : (t.liq_price ? +t.liq_price : null), slLabel: +t.sl > 0 ? "SL" : "Liq.", tps: [t.tp1, t.tp2, t.tp3].map((x) => x && +x), price, riskRef: +t.risk_eur > 0 && +t.qty > 0 ? +t.risk_eur / (+t.qty * (+t.eur_per_quote || 1)) : null })}</div>
    </div>

    ${mine && t.status === "ouvert" ? `<section class="section"><h2>Gérer</h2>
      <div class="ligne">
        <button class="btn principal" id="take">Encaisser une partie</button>
        <button class="btn" id="move">Déplacer le SL</button>
        <button class="btn" id="close">Clôturer</button>
        <a class="btn discret" href="${krakenLink(t)}" target="_blank" rel="noopener">Ouvrir sur Kraken</a>
      </div>
      <label class="ligne small" style="margin-top:12px"><input type="checkbox" id="auto" style="width:auto;min-height:0" ${t.auto_track ? "checked" : ""}>
        Suivi automatique par le bot (TP et SL touchés appliqués à chaque scan)</label></section>` : ""}

    <section class="section"><h2>Journal du trade</h2>
      <div class="bloc"><ul>${(t.events || []).slice().reverse().map((e) => `<li><span class="muted small">${dt(e.at)}${e.by === "bot" ? " · bot" : ""}</span> ${esc(e.text)}</li>`).join("") || "<li>—</li>"}</ul>
      ${t.notes ? `<p><b>Note :</b> ${esc(t.notes)}</p>` : ""}</div></section>

    ${mine ? `<p><button class="btn danger" id="del">Supprimer ce trade (saisi par erreur)</button></p>` : ""}`;

  const el = main.querySelector("#chart");
  const lines = [{ price: +t.entry_price, color: "#F2B544", title: "Entrée" }, ...(+t.sl > 0 ? [{ price: +t.sl, color: "#FF6B6B", title: "SL" }] : []), ...(t.liq_price ? [{ price: +t.liq_price, color: "#FF6B6B", title: "Liquidation", dashed: true }] : []),
    ...[t.tp1, t.tp2, t.tp3].map((x, i) => x && { price: +x, color: "#3DDC97", title: `TP${i + 1}`, width: 1 }).filter(Boolean)];
  let chart = null;
  ohlc(t, 15).then((c) => {
    if (el.isConnected && c?.length) chart = candleChart(el, c.slice(-160), { lines }); else { el.innerHTML = '<p class="vide">Graphique indisponible.</p>'; return; }
    // TP / SL touchés depuis le dernier passage du bot (il passe une fois par heure) : on le montre tout de suite.
    const d = depuisDernierPassage(t, c);
    const box = main.querySelector("#depuis");
    if (d && box) box.innerHTML = `<div class="alerte ${d.sl ? "rouge" : ""}"><b>${esc(texteDepuis(d, nextScan()))}</b>
      <p class="small" style="margin:6px 0 0">${t.mode === "reel" ? "Trade réel : vérifie sur Kraken que tes ordres TP / SL ont bien été exécutés."
        : "Trade d'entraînement : tu n'as rien à faire."} Tu peux aussi l'enregistrer toi-même avec « Encaisser une partie » ou « Clôturer ».</p></div>`;
  })
    .catch(() => { el.innerHTML = '<p class="vide">Graphique indisponible (Kraken ne répond pas).</p>'; });
  ctx.onLeave(() => chart?.remove());
  const reload = () => render(main, ctx, id);
  if (!mine) return;

  main.querySelector("#refrais-ok")?.addEventListener("click", (e) => busy(e.currentTarget, async () => {
    await backend.updateTrade(t.id, {
      fee_pct: nouveauPct, realized_pnl_eur: +refait.realized.toFixed(4), risk_eur: +refait.riskEur.toFixed(4),
      ...(refait.rMultiple != null ? { r_multiple: refait.rMultiple } : {}),
      events: [...(t.events || []), ev(`Frais recalculés : ${t.fee_pct} % → ${nouveauPct} % (${grille.label}). Résultat ${eur(+t.realized_pnl_eur, true)} → ${eur(refait.realized, true)}`)],
    });
    toast("Frais recalculés. Ton solde est mis à jour.");
    ctx.go("#/trades"); setTimeout(() => ctx.go(`#/trade/${t.id}`), 50);
  }));
  main.querySelector("#del")?.addEventListener("click", (e) => {
    if (!confirm("Supprimer définitivement ce trade ?")) return;
    busy(e.currentTarget, async () => { await backend.deleteTrade(t.id); toast("Trade supprimé."); ctx.go("#/trades"); });
  });
  if (t.status !== "ouvert") return;

  main.querySelector("#auto").addEventListener("change", (e) => backend.updateTrade(t.id, { auto_track: e.target.checked }).then(() => toast("Préférence enregistrée.")));

  const priceField = `<label class="champ"><span>Prix d'exécution</span><input name="price" inputmode="decimal" value="${price ?? ""}">
    <small>Prérempli avec le prix Kraken actuel. Mets ton vrai prix si tu l'as fait sur Kraken.</small></label>`;

  main.querySelector("#take").addEventListener("click", () => modal(`
    <h2>Encaisser une partie</h2><form class="form">
      <label class="champ"><span>Part de la position de départ</span><select name="part">
        ${TP_SPLIT.map((p, i) => `<option value="${p}">${Math.round(p * 100)} % (TP${i + 1})</option>`).join("")}<option value="1">Tout ce qui reste</option></select></label>
      ${priceField}
      <div class="ligne"><button class="btn principal" type="submit">Encaisser</button><button class="btn discret" type="button" data-close>Annuler</button></div></form>`,
  (d, close) => d.querySelector("form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const p = num(e.target.price.value);
    if (!(p > 0)) return toast("Indique un prix.", true);
    const part = +e.target.part.value;
    const qty = part >= 1 ? +t.qty_remaining : +t.qty * part;
    const idx = TP_SPLIT.indexOf(part);
    const { pnl, update } = closePart(t, p, qty);
    if (idx >= 0) update[`tp${idx + 1}_hit`] = true;
    if (update.status === "clos") update.close_reason = "clôture manuelle";
    update.events = [...(t.events || []), ev(`Encaissé ${part >= 1 ? "le reste" : Math.round(part * 100) + " %"} à ${p} (${eur(pnl, true)})`)];
    await busy(e.submitter, async () => { await backend.updateTrade(t.id, update); close(); toast("Enregistré."); reload(); });
  })));

  main.querySelector("#move").addEventListener("click", () => modal(`
    <h2>${+t.sl > 0 ? "Déplacer le stop loss" : "Ajouter un stop loss"}</h2><form class="form">
      <label class="champ"><span>Nouveau SL</span><input name="sl" inputmode="decimal" value="${t.sl ?? ""}">
        <small>Au prix d'entrée (${px(+t.entry_price)}) = break-even : tu ne peux plus perdre sur ce qui reste.</small></label>
      <div class="ligne"><button class="btn" type="button" id="be">Mettre au break-even</button></div>
      <div class="ligne"><button class="btn principal" type="submit">Enregistrer</button><button class="btn discret" type="button" data-close>Annuler</button></div></form>`,
  (d, close) => {
    d.querySelector("#be").addEventListener("click", () => { d.querySelector("[name=sl]").value = t.entry_price; });
    d.querySelector("form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const sl = num(e.target.sl.value);
      const sign = t.direction === "LONG" ? 1 : -1;
      if (!(sl > 0) || (price && sign * (price - sl) <= 0)) return toast("Ce SL est déjà dépassé par le prix actuel.", true);
      await busy(e.submitter, async () => {
        await backend.updateTrade(t.id, { sl, events: [...(t.events || []), ev(+t.sl > 0 ? `SL déplacé de ${t.sl} à ${sl}` : `Stop ajouté à ${sl}`)] });
        close(); toast("SL déplacé. Pense à le modifier aussi sur Kraken si c'est un trade réel."); reload();
      });
    });
  }));

  main.querySelector("#close").addEventListener("click", () => modal(`
    <h2>Clôturer le trade</h2><form class="form">${priceField}
      <div class="ligne"><button class="btn principal" type="submit">Clôturer</button><button class="btn discret" type="button" data-close>Annuler</button></div></form>`,
  (d, close) => d.querySelector("form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const p = num(e.target.price.value);
    if (!(p > 0)) return toast("Indique un prix.", true);
    const { pnl, update } = closePart(t, p, +t.qty_remaining);
    update.close_reason = "clôture manuelle";
    update.events = [...(t.events || []), ev(`Clôturé à ${p} (${eur(pnl, true)})`)];
    await busy(e.submitter, async () => { await backend.updateTrade(t.id, update); close(); toast("Trade clôturé."); reload(); });
  })));
}
