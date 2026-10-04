// Formulaire « prendre un trade » : partagé par la page signal et le trade manuel.
// Comme sur Kraken : tu choisis la quantité (ou le montant), le type d'ordre et le levier ; le site te montre ce que ça implique
// (marge isolée, perte au SL ou à la liquidation, gains aux TP, frais Kraken réels de la grille officielle).
import { backend } from "../data.js";
import { ladder } from "../ladder.js";
import { STOP_MIN_PCT } from "../setup.js";
import { getMode, hasPerp, krakenFees, nomActif, perpSymbol, venueEffective } from "../fees.js";
import { openRiskEur, planFromQty, qtyForRisk, riskBudget, suggestLeverage, usedMarginEur } from "../sizing.js";
import { busy, esc, eur, num, pct, pq, px, rr, sym, toast } from "../ui.js";

const r6 = (x) => (x == null || !isFinite(x) ? "" : String(+(+x).toPrecision(6)));
const MAX_RISK_PCT = 2;

/**
 * @param host élément où afficher le formulaire
 * @param o { me, trades (du membre), inst {display, venue, api_symbol, api_asset_class, asset_class, quote, instrument_key,
 *            can_short, max_leverage, lot_decimals, ordermin}, signal?, price?, eurPerQuote, levRef? (levier conseillé), go }
 * Frais : grille Kraken selon le marché (fees.js), sauf si o.feeTaker / o.feeMaker sont fournis.
 */
export function tradeForm(host, o) {
  const s = o.signal;
  const dir0 = s?.direction || "LONG";
  const inZone = s && o.price && o.price >= s.entry_low && o.price <= s.entry_high;
  // Prix déjà passé de l'autre côté de la zone, vers le stop (ex. NEAR du 03/10 : zone 4,68–4,69, prix 4,65, stop 4,64).
  const coteStop = !!(s && o.price && (dir0 === "LONG" ? o.price < s.entry_low : o.price > s.entry_high));
  const eRef = s ? (dir0 === "LONG" ? +s.entry_high : +s.entry_low) : 0;
  const serre = !!(s && eRef > 0 && +s.sl > 0 && (Math.abs(eRef - s.sl) / eRef) * 100 < STOP_MIN_PCT);
  const entry0 = s ? (inZone || coteStop ? o.price : (dir0 === "LONG" ? s.entry_high : s.entry_low)) : o.price;
  const budget = riskBudget(o.me, o.trades);
  const venue = venueEffective(o.inst); // futures perpétuels (par défaut) ou spot, selon Mon compte
  const perp = venue === "futures";
  const maxLev = perp ? 10 : Math.max(1, Math.min(10, o.inst.max_leverage || 10));
  const baseName = esc(nomActif(o.inst));
  const q = sym(o.inst.quote).trim() || o.inst.quote || "";
  const free = o.me.guardrails !== true; // garde-fous du club : désactivés par défaut, actifs seulement si le membre les coche
  const grille = krakenFees(o.inst);
  const fees = { taker: o.feeTaker ?? grille.taker, maker: o.feeMaker ?? grille.maker };
  const fp = (x) => String(+x.toFixed(3)).replace(".", ",") + " %";
  // Prix au pas Kraken (décimales de la paire) : sinon Kraken peut refuser le TP/SL (ex. 7 décimales sur PUMP).
  const pd = Number.isInteger(o.inst.pair_decimals) && o.inst.pair_decimals >= 0 && o.inst.pair_decimals <= 12 ? o.inst.pair_decimals : null;
  const rp = (x) => (x == null || !isFinite(x) ? "" : pd == null ? r6(x) : String(+(+x).toFixed(pd)));
  const order0 = (() => { try { return localStorage.getItem("ldk-order-type") || "limit"; } catch { return "limit"; } })();

  const sansPerp = getMode() === "futures" && !perp && o.inst.asset_class !== "xstock" && !hasPerp(o.inst);
  host.innerHTML = `
  <form class="form" novalidate>
    ${sansPerp ? `<p class="alerte small">📍 <b>Pas de futures perpétuel Kraken pour ${baseName}</b> : ce trade se fait en <b>spot</b> (frais 0,40 % / 0,80 %).</p>` : ""}
    <div class="choix" role="radiogroup" aria-label="Sens">
      <label class="long"><input type="radio" name="dir" value="LONG" ${dir0 === "LONG" ? "checked" : ""}><span>LONG ↑ (acheter)</span></label>
      <label class="short"><input type="radio" name="dir" value="SHORT" ${dir0 === "SHORT" ? "checked" : ""}><span>SHORT ↓ (vendre)</span></label>
    </div>

    <label class="champ"><span>Prix d'entrée (limite)${q ? ` en ${esc(q)}` : ""}</span><input name="entry" inputmode="decimal" value="${rp(entry0)}">
      <small>${o.price ? `Prix actuel ${pq(o.price, o.inst.quote)}` : "Prix actuel indisponible"}</small></label>

    <div class="choix" role="radiogroup" aria-label="Type d'ordre">
      <label><input type="radio" name="order" value="limit" ${order0 === "limit" ? "checked" : ""}><span>Limite · frais ${fp(fees.maker)}</span></label>
      <label><input type="radio" name="order" value="market" ${order0 === "market" ? "checked" : ""}><span>Marché · frais ${fp(fees.taker)}</span></label>
    </div>
    <p class="small muted" style="margin-top:-6px">Frais ${esc(grille.label)} (grille officielle Kraken). Un ordre limite exécuté tout de suite paie les frais « marché ».</p>

    <label class="champ"><span>Levier : <b id="lev-v">x1</b> <span class="small muted">· marge isolée</span></span>
      <input type="range" name="lev" min="1" max="${maxLev}" step="1" value="${o.levRef ? Math.min(maxLev, o.levRef) : dir0 === "SHORT" && !perp ? Math.min(2, maxLev) : 1}">
      <div class="ligne small">${[1, 2, 3, 5, 10].filter((x) => x <= maxLev).map((x) => `<button type="button" class="btn discret mini" data-lev="${x}">x${x}</button>`).join("")}</div>
      <small>${o.levRef ? `Levier conseillé pour ce trade : <b>x${o.levRef}</b>. ` : ""}Le levier réduit la mise bloquée et rapproche la liquidation ; à quantité égale, il ne change <b>pas</b> ta perte au SL.</small></label>

    <div class="champ taille">
      <span>Taille : <b id="pct-v">0 %</b> de ton capital disponible</span>
      <input type="range" name="pct" min="0" max="100" step="1" value="0" aria-label="Pourcentage du capital disponible engagé">
      <div class="ligne small">${[0, 25, 50, 75, 100].map((x) => `<button type="button" class="btn discret mini" data-pct="${x}">${x} %</button>`).join("")}</div>
      <small id="pct-info">Comme sur Kraken Pro : le curseur règle ta mise (marge) en % de ton capital disponible ; la quantité suit le levier.</small>
    </div>
    <div class="deux">
      <label class="champ"><span>Quantité (${baseName})</span><input name="qty" inputmode="decimal" placeholder="0">
        <small>${o.inst.ordermin ? `Minimum Kraken : ${o.inst.ordermin} ${baseName}` : "&nbsp;"}</small></label>
      <label class="champ"><span>ou valeur de la position (${esc(q || "total")})</span><input name="amount" inputmode="decimal" placeholder="0">
        <small id="max-pos">= quantité × prix d'entrée</small></label>
    </div>

    <label class="champ"><span>Stop loss (SL) — facultatif</span><input name="sl" inputmode="decimal" value="${rp(s?.sl)}" placeholder="aucun">
      <small>Là où tu coupes si ça va mal. Sans stop, tu peux perdre la marge du trade (liquidation), jamais plus.</small></label>
    <div class="trois">
      <label class="champ"><span>TP1 · 30 %</span><input name="tp1" inputmode="decimal" value="${rp(s?.tp1)}"></label>
      <label class="champ"><span>TP2 · 40 %</span><input name="tp2" inputmode="decimal" value="${rp(s?.tp2)}"></label>
      <label class="champ"><span>TP3 · 30 %</span><input name="tp3" inputmode="decimal" value="${rp(s?.tp3)}"></label>
    </div>

    <div class="choix" role="radiogroup" aria-label="Type de trade">
      <label><input type="radio" name="mode" value="paper" checked><span>Entraînement (paper)</span></label>
      <label><input type="radio" name="mode" value="reel"><span>Réel (passé sur Kraken)</span></label>
    </div>
    <label class="champ"><span>Note (facultatif)</span><input name="notes" maxlength="300" placeholder="Pourquoi je prends ce trade"></label>
    <div id="plan" aria-live="polite"></div>
    ${s?.status === "WATCH" || coteStop || serre ? `<label class="alerte rouge interrupteur" style="display:flex">
      <input type="checkbox" name="sansconfirm">
      <span>${serre ? `<b>🚫 Stop trop serré : ${pct((Math.abs(eRef - s.sl) / eRef) * 100, 2)} de l'entrée.</b> Une simple mèche le touche et les frais mangent le reste
        (le bot exige maintenant au moins ${String(STOP_MIN_PCT).replace(".", ",")} %).`
        : coteStop ? `<b>⚠️ Le prix (${pq(o.price, o.inst.quote)}) est déjà passé ${dir0 === "LONG" ? "SOUS" : "AU-DESSUS de"} la zone d'entrée, vers le stop.</b>
        Le scénario du bot est abîmé : le stop est tout près (${pct((Math.abs(o.price - s.sl) / o.price) * 100, 2)}) et un simple mouvement normal le touche.`
        : `<b>⚠️ Ce setup n'est PAS validé par le bot.</b> Il manque encore : ${esc(s.trigger_text || "la confirmation 15 min")}.
        Entrer maintenant, c'est parier sans la confirmation (c'est souvent là qu'on se fait sortir).`}
        Coche seulement si tu choisis d'entrer quand même.</span></label>` : ""}
    <button class="btn principal plein" type="submit">Enregistrer le trade</button>
  </form>`;

  const f = host.querySelector("form");
  let plan = null;
  let userTouchedLev = !!o.levRef; // levier conseillé par le bot : on le garde tel quel
  let lastEdited = "qty"; // quantité ou montant : le dernier champ tapé fait foi

  const v = (n) => num(f.elements[n].value);
  const orderType = () => f.elements.order.value;
  // Ordre limite « du mauvais côté » du prix (achat au-dessus / vente en dessous) : Kraken l'exécute tout de suite au marché.
  // En entraînement, le trade s'ouvre donc au prix réel du moment (et paie les frais marché), pas à un prix qui n'existe pas.
  const auMarche = () => {
    const e = v("entry");
    if (!(o.price > 0) || !(e > 0) || f.elements.mode.value !== "paper") return false;
    return f.elements.dir.value === "LONG" ? e > o.price * 1.0005 : e < o.price * 0.9995;
  };
  const base = () => ({
    direction: f.elements.dir.value, entry: auMarche() ? o.price : v("entry"), sl: v("sl"), tps: [v("tp1"), v("tp2"), v("tp3")].filter((x) => x != null),
    balance: +o.me.balance_eur, feeTaker: fees.taker, feeMaker: fees.maker, entryIsMaker: orderType() === "limit" && !auMarche(),
    eurPerQuote: o.eurPerQuote, lotDecimals: o.inst.lot_decimals ?? 8, ordermin: perp ? 0 : o.inst.ordermin || 0, venue, maxLev: perp ? 10 : +o.inst.max_leverage || 10,
    usedMarginEur: usedMarginEur(o.trades),
  });

  function syncQtyAmount() {
    const e = v("entry");
    if (!(e > 0)) return;
    if (lastEdited === "qty") { const qq = v("qty"); f.elements.amount.value = qq > 0 ? r6(qq * e) : ""; }
    else { const a = v("amount"); f.elements.qty.value = a > 0 ? r6(a / e) : ""; }
  }

  function update() {
    try { localStorage.setItem("ldk-order-type", orderType()); } catch { /* sans stockage, tant pis */ }
    const p = base();
    const lev = +f.elements.lev.value;
    f.querySelector("#lev-v").textContent = "x" + lev;
    syncQtyAmount();
    plan = planFromQty({ ...p, qty: v("qty"), leverage: lev, riskPct: +o.me.risk_pct, maxRiskPct: MAX_RISK_PCT, strict: !free });
    // Tant que tu n'as pas touché au levier, on propose le plus petit qui permet de payer la marge (comme Kraken l'exigerait).
    const libreLev = Math.max(0, p.balance - (p.usedMarginEur || 0)) - (plan.entryFeeEur || 0);
    if (!userTouchedLev && plan.notionalEur > libreLev * lev) {
      // sans stop, pas de contrainte « stop vs levier » : on prend juste le plus petit levier qui loge la marge
      const sug = suggestLeverage(plan, libreLev, plan.hasSl ? plan.slPct : 0, maxLev);
      if (sug && sug > lev) { f.elements.lev.value = sug; return update(); }
    }
    const errs = [...(plan.errors || [])];
    if (!perp && p.direction === "SHORT" && o.inst.can_short === false) errs.push("Cet instrument ne permet pas le SHORT sur Kraken (pas de marge).");
    if (free) {
      // Garde-fous coupés (par défaut) : on ne parle plus des règles de risque du club, seulement des contraintes Kraken.
      plan.warnings = plan.warnings.filter((w) => !/règle du club|risque habituel|Risque cumulé|Perte maximale du jour/.test(w));
    } else {
      if (budget.dailyStop) errs.push("Perte maximale du jour atteinte : pas de nouveau trade aujourd'hui.");
      if (plan.lossAtSlEur > budget.available + 1e-6) errs.push(`Risque cumulé élevé : il te restait ${eur(budget.available)} de risque disponible selon tes réglages (tes autres trades ouverts comptent).`);
    }
    plan.blocking = errs;
    // Trades déjà ouverts dans le même sens : ils perdent souvent ensemble (ex. MON + WLD LONG du 04/10, −37 € d'un coup).
    const memeSens = (o.trades || []).filter((t) => t.status === "ouvert" && t.direction === p.direction);
    if (memeSens.length >= 1 && plan.qty) {
      const enJeu = memeSens.reduce((a, t) => a + openRiskEur(t), 0);
      plan.warnings.unshift(`Tu as déjà ${memeSens.length} trade${memeSens.length > 1 ? "s" : ""} ${p.direction} ouvert${memeSens.length > 1 ? "s" : ""} (${memeSens.map((t) => nomActif(t)).slice(0, 4).join(", ")}) avec ${eur(enJeu)} en jeu. Si le marché part dans l'autre sens, ils perdent ensemble : avec celui-ci, ${eur(enJeu + plan.lossAtSlEur)} au total (${pct(((enJeu + plan.lossAtSlEur) / p.balance) * 100, 1)} de ton solde).`);
    }
    // Curseur : position et texte (mise en € et en % du capital disponible)
    const pc = pctDepuisQty();
    if (!parPct) f.elements.pct.value = String(Math.min(100, Math.round(pc)));
    f.querySelector("#pct-v").textContent = `${Math.round(Math.min(pc, 999))} %`;
    f.querySelector("#pct-info").innerHTML = plan.qty
      ? `Mise ${eur(plan.marginEur)} sur ${eur(capital())} disponibles · position ${eur(plan.notionalEur)} (x${lev})${pc > 100.5 ? " · <b class=\"perte\">plus que ton capital disponible</b>" : ""}`
      : `Capital disponible : <b>${eur(capital())}</b>${capital() < p.balance - 0.005 ? ` (sur ${eur(p.balance)} : le reste est bloqué par tes trades ouverts)` : ""}.`;
    f.querySelectorAll("[data-lev]").forEach((b) => { const on = +b.dataset.lev === lev; b.classList.toggle("actif", on); b.classList.toggle("discret", !on); });
    const mp = f.querySelector("#max-pos");
    if (mp && p.entry > 0 && p.eurPerQuote > 0) {
      const fe = (p.entryIsMaker ? p.feeMaker : p.feeTaker) / 100;
      const libre = Math.max(0, p.balance - (p.usedMarginEur || 0));
      const maxPos = (0.998 * libre * lev) / (p.eurPerQuote * (1 + fe * lev));
      mp.innerHTML = `Maximum à x${lev} avec ta marge libre (${eur(libre)}) : <b>${pq(maxPos, o.inst.quote)}</b>`;
    }
    render(p, lev, errs);
  }

  function render(p, lev, errs) {
    const box = f.querySelector("#plan");
    if (!p.entry) { box.innerHTML = '<p class="muted">Renseigne le prix d\'entrée.</p>'; return; }
    if (!plan.qty || errs.some((e) => /^Marge insuffisante|^Plus de marge/.test(e))) {
      box.innerHTML = errs.length ? `<div class="alerte rouge"><ul>${errs.map((e) => `<li>${esc(e)}</li>`).join("")}</ul></div>` : "";
      return;
    }
    const lossPct = plan.effectiveRiskPct ?? (plan.lossAtSlEur / p.balance) * 100;
    const ton = free ? "" : lossPct > MAX_RISK_PCT + 1e-9 ? "short" : lossPct > +o.me.risk_pct + 1e-9 ? "ambre" : "long";
    box.innerHTML = `
      ${errs.length ? `<div class="alerte rouge"><ul>${errs.map((e) => `<li>${esc(e)}</li>`).join("")}</ul></div>` : ""}
      ${auMarche() ? `<p class="alerte small">⚡ Ton prix limite (${pq(v("entry"), o.inst.quote)}) est ${p.direction === "LONG" ? "au-dessus" : "en dessous"} du prix actuel :
        sur Kraken, l'ordre serait exécuté <b>tout de suite au marché</b>. Le trade d'entraînement s'ouvre donc à ${pq(o.price, o.inst.quote)} (frais marché).</p>` : ""}
      <div class="feu ${ton}"><span class="feu-icone">${free ? "📉" : ton === "long" ? "🛡️" : ton === "ambre" ? "⚠️" : "⛔"}</span>
        <div><strong>${plan.hasSl === false ? "Sans stop, perte max" : plan.liqBeforeSl ? "Liquidation avant le stop, perte max" : "Si le SL est touché"} : ${eur(-plan.lossAtSlEur)} (${pct(lossPct, 2)} de ton solde)</strong>
        ${free ? "" : `<p>${ton === "long" ? "Dans ta règle de risque." : ton === "ambre" ? "Plus que ton risque habituel : seulement pour un setup exceptionnel."
          : `Au-delà de ${MAX_RISK_PCT} % : interdit par la règle du club.`}</p>`}</div></div>
      <div class="bloc"><div class="split">
        <dl class="chiffres" style="margin:0">
          <div><dt>Quantité à ${p.direction === "LONG" ? "acheter" : "vendre"}</dt><dd class="num">${+plan.qty.toPrecision(6)} ${baseName}</dd></div>
          <div><dt>Valeur de la position</dt><dd class="num">${eur(plan.notionalEur)}</dd></div>
          <div><dt>Ta mise (marge isolée x${lev})</dt><dd class="num ${plan.marginEur > p.balance * 0.5 ? "perte" : ""}">${eur(plan.marginEur)}</dd>
            <span class="small ${plan.marginEur > p.balance * 0.5 ? "perte" : "muted"}">${pct((plan.marginEur / p.balance) * 100, 1)} de ton solde${plan.marginEur > p.balance * 0.5 ? " · plus de la moitié de ton solde bloquée" : ""}</span></div>
          <div><dt>Frais d'entrée (${fp(p.entryIsMaker ? fees.maker : fees.taker)})</dt><dd class="num">${eur(-plan.entryFeeEur)}</dd></div>
          ${plan.liqPrice ? `<div><dt>Liquidation ≈</dt><dd class="num perte">${pq(plan.liqPrice, o.inst.quote)}</dd></div>` : ""}
          ${plan.profitsEur.map((g, i) => `<div><dt>Gain au TP${i + 1} (${[30, 40, 30][i]} %)</dt><dd class="num gain">${eur(g, true)} · ${rr(plan.rr[i])}</dd></div>`).join("")}
        </dl>
        ${ladder({ direction: p.direction, entryLow: p.entry, entryHigh: p.entry, sl: p.sl || plan.liqPrice, slLabel: p.sl ? "SL" : "Liq.", tps: p.tps, price: o.price, compact: true })}
      </div>
      ${plan.warnings.map((w) => `<p class="small muted">⚠ ${esc(w)}</p>`).join("")}
      <p class="small muted">Marge isolée : ce trade n'engage que ${eur(plan.marginEur)}. Le reste de ton capital n'est jamais touché par lui
        ${plan.freeMarginEur != null ? ` (marge encore libre avant ce trade : ${eur(plan.freeMarginEur)})` : ""}.${plan.liqPrice ? " Liquidation approximative : Kraken peut liquider un peu avant selon ses niveaux de marge." : ""}</p>
      <p class="small muted">Sur Kraken${perp ? ` (onglet Futures, <b>${esc(perpSymbol(o.inst) || "")}</b>)` : " (spot)"} : ${p.direction === "LONG" ? "Acheter" : "Vendre"} · ${p.entryIsMaker ? `Limite ${pq(p.entry, o.inst.quote)}` : "Marché"} · Quantité ${+plan.qty.toPrecision(6)} ${baseName} · Levier ${lev > 1 ? "x" + lev + " · marge isolée" : "aucun (x1)"}${p.sl ? ` · Stop ${pq(p.sl, o.inst.quote)}` : " · sans stop"}.
        R:R net de frais : ${plan.rrNet.map((r, i) => `TP${i + 1} ${r.toFixed(1)}`).join(" · ")}.</p></div>`;
  }

  // Curseur « % du capital disponible » (comme Kraken Pro) : mise = capital libre × % ; quantité = mise × levier / prix,
  // frais d'entrée gardés de côté pour que 100 % reste exécutable.
  let parPct = false; // la dernière action est le curseur : en changeant le levier, on garde le % (la quantité suit)
  const capital = () => { const p = base(); return Math.max(0, p.balance - (p.usedMarginEur || 0)); };
  const feEntree = () => { const p = base(); return (p.entryIsMaker ? p.feeMaker : p.feeTaker) / 100; };
  function qtyDepuisPct(pc) {
    const p = base();
    if (!(p.entry > 0) || !(p.eurPerQuote > 0)) return null;
    const lev = +f.elements.lev.value, fe = feEntree();
    const qq = (0.998 * capital() * (pc / 100) * lev) / (p.entry * p.eurPerQuote * (1 + fe * lev));
    if (!(qq > 0)) return 0;
    const pas = 10 ** Math.min(p.lotDecimals ?? 8, Math.max(0, 5 - Math.floor(Math.log10(Math.max(qq, 1e-12))))); // arrondi vers le bas
    return Math.floor(qq * pas) / pas;
  }
  function pctDepuisQty() {
    const p = base(), qq = v("qty"), cap = capital();
    if (!(qq > 0) || !(p.entry > 0) || !(cap > 0)) return 0;
    const lev = +f.elements.lev.value, notional = qq * p.entry * p.eurPerQuote;
    return ((notional / lev + notional * feEntree()) / cap) * 100;
  }
  function appliquerPct(pc) {
    const qq = qtyDepuisPct(pc);
    if (qq == null) { toast("Renseigne d'abord le prix d'entrée.", true); return; }
    f.elements.qty.value = qq > 0 ? String(qq) : "";
    lastEdited = "qty"; parPct = true; userTouchedLev = true;
    update();
  }
  f.elements.pct.addEventListener("input", (e) => { e.stopPropagation(); appliquerPct(+e.target.value); });
  f.querySelectorAll("[data-pct]").forEach((b) => b.addEventListener("click", () => { f.elements.pct.value = b.dataset.pct; appliquerPct(+b.dataset.pct); }));
  f.querySelectorAll("[data-lev]").forEach((b) => b.addEventListener("click", () => {
    f.elements.lev.value = b.dataset.lev; userTouchedLev = true;
    if (parPct) appliquerPct(+f.elements.pct.value); else update();
  }));
  // Plafond : impossible de saisir une position plus grosse que ce que ta marge libre permet au levier max (frais compris).
  let ramene = 0;
  function plafond(name) {
    const p = base();
    if (!(p.entry > 0) || !(p.eurPerQuote > 0)) return;
    const fe = (p.entryIsMaker ? p.feeMaker : p.feeTaker) / 100;
    const libre = Math.max(0, p.balance - (p.usedMarginEur || 0));
    const L = userTouchedLev ? +f.elements.lev.value : maxLev;
    const maxPos = (0.998 * libre * L) / (p.eurPerQuote * (1 + fe * L)); // en devise de cotation
    const val = name === "qty" ? v("qty") * p.entry : v("amount");
    if (!(val > maxPos)) return;
    const qq = maxPos / p.entry;
    const pas = 10 ** Math.min(p.lotDecimals ?? 8, Math.max(0, 5 - Math.floor(Math.log10(Math.max(qq, 1e-12)))));
    const qMax = Math.floor(qq * pas) / pas;
    f.elements.qty.value = qMax > 0 ? String(qMax) : "";
    f.elements.amount.value = qMax > 0 ? r6(qMax * p.entry) : "";
    lastEdited = "qty";
    ramene = Date.now();
    toast(libre > 0 ? `Ramené au maximum possible : ${pq(qMax * p.entry, o.inst.quote)} de position à x${L} avec ${eur(libre)} de marge libre.`
      : "Plus de marge libre : tes trades ouverts bloquent déjà tout ton solde.", true);
  }
  f.addEventListener("input", (e) => {
    if (e.target.name === "pct") return;
    if (e.target.name === "lev") { userTouchedLev = true; if (parPct) { appliquerPct(+f.elements.pct.value); return; } }
    if (e.target.name === "qty") { lastEdited = "qty"; parPct = false; }
    if (e.target.name === "amount") { lastEdited = "amount"; parPct = false; }
    update();
  });
  // Au moment de quitter le champ (pas à chaque chiffre tapé, pour ne pas couper la saisie)
  f.addEventListener("change", (e) => { if (e.target.name === "qty" || e.target.name === "amount") { plafond(e.target.name); update(); } });
  f.addEventListener("change", (e) => { if (e.target.name === "order" || e.target.name === "dir" || e.target.name === "mode") update(); });

  f.addEventListener("submit", (e) => {
    e.preventDefault();
    update();
    if (!plan?.ok || plan.blocking.length) { toast(plan?.blocking?.[0] || plan?.errors?.[0] || "Vérifie les champs.", true); return; }
    if (Date.now() - ramene < 2500) { toast("La quantité vient d'être ramenée au maximum possible : vérifie-la, puis enregistre.", true); return; }
    if ((s?.status === "WATCH" || coteStop || serre) && !f.elements.sansconfirm?.checked) {
      toast(serre ? "Stop trop serré : ce setup n'est pas jouable. Coche la case rouge seulement si tu choisis d'entrer quand même." : coteStop ? "Le prix est déjà passé vers le stop : attends qu'il revienne dans la zone, ou coche la case rouge pour entrer quand même."
        : "Ce setup n'est pas encore validé par le bot : attends la confirmation, ou coche la case rouge pour entrer quand même.", true); return;
    }
    const x = base();
    const lev = +f.elements.lev.value;
    const mode = f.elements.mode.value;
    const btn = f.querySelector("[type=submit]");
    busy(btn, async () => {
      const t = await backend.createTrade({
        signal_id: s?.id ?? null, instrument_key: o.inst.instrument_key || o.inst.key, display: o.inst.display,
        venue: o.inst.venue, api_symbol: o.inst.api_symbol, api_asset_class: o.inst.api_asset_class || null,
        asset_class: o.inst.asset_class, quote: o.inst.quote || "EUR", direction: x.direction, mode,
        entry_price: x.entry, sl: x.sl ?? null, liq_price: plan.liqPrice ?? null, tp1: x.tps[0] ?? null, tp2: x.tps[1] ?? null, tp3: x.tps[2] ?? null,
        leverage: lev, qty: plan.qty, qty_remaining: plan.qty, risk_eur: +plan.lossAtSlEur.toFixed(4),
        eur_per_quote: o.eurPerQuote, fee_pct: x.entryIsMaker ? fees.maker : fees.taker, balance_at_entry: +o.me.balance_eur,
        realized_pnl_eur: -(plan.entryFeeEur || 0), strategy: s?.strategy || "manuel", notes: f.elements.notes.value || null,
        events: [{ at: new Date().toISOString(), text: `Ouverture ${mode === "reel" ? "réelle" : "paper"} à ${x.entry} · ${+plan.qty.toPrecision(6)} ${nomActif(o.inst)} · x${lev}` }],
      });
      toast("Trade enregistré. Le bot le suivra à chaque scan.");
      o.go(`#/trade/${t.id}`);
    });
  });

  // Signal : on pré-remplit la quantité qui correspond à ton risque habituel (modifiable).
  if (s) {
    const qq = qtyForRisk(base(), Math.min(+o.me.risk_pct || 1, Math.max(0.01, budget.availablePct)));
    if (qq) f.elements.qty.value = r6(qq);
  }
  update();
}
