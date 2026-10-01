// Formulaire « prendre un trade » : partagé par la page signal et le trade manuel.
// Deux façons de choisir la taille :
//  - « Comme sur Kraken » : tu choisis la quantité (ou le montant) et le levier ; le site te montre ce que ça implique.
//  - « Automatique » : tu choisis le risque en % ; le site calcule la quantité.
// Garde-fous du club dans les deux cas : SL obligatoire, jamais plus de 2 % du solde au SL, budget de risque du jour.
import { backend } from "../data.js";
import { ladder } from "../ladder.js";
import { planFromQty, planTrade, qtyForRisk, riskBudget, suggestLeverage, usedMarginEur } from "../sizing.js";
import { busy, esc, eur, num, pct, pq, px, rr, sym, toast } from "../ui.js";

const r6 = (x) => (x == null || !isFinite(x) ? "" : String(+(+x).toPrecision(6)));
const MAX_RISK_PCT = 2;

/**
 * @param host élément où afficher le formulaire
 * @param o { me, trades (du membre), inst {display, venue, api_symbol, api_asset_class, asset_class, quote, instrument_key,
 *            can_short, max_leverage, lot_decimals, ordermin}, signal?, price?, eurPerQuote, feeTaker, feeMaker, go }
 */
export function tradeForm(host, o) {
  const s = o.signal;
  const dir0 = s?.direction || "LONG";
  const inZone = s && o.price && o.price >= s.entry_low && o.price <= s.entry_high;
  const entry0 = s ? (inZone ? o.price : (dir0 === "LONG" ? s.entry_high : s.entry_low)) : o.price;
  const budget = riskBudget(o.me, o.trades);
  const maxLev = Math.max(1, Math.min(10, o.inst.max_leverage || 10));
  const baseName = esc(String(o.inst.display || "").split("/")[0]);
  const q = sym(o.inst.quote).trim() || o.inst.quote || "";
  const free = o.me.guardrails === false; // garde-fous coupés par le membre (Mon compte)
  const sizeMode0 = (() => { try { return localStorage.getItem("ldk-size-mode") || "qty"; } catch { return "qty"; } })();

  host.innerHTML = `
  <form class="form" novalidate>
    ${free ? '<p class="alerte">Garde-fous coupés : rien n\'est bloqué, lis bien les avertissements (réactivables dans Mon compte).</p>' : ""}
    <div class="choix" role="radiogroup" aria-label="Sens">
      <label class="long"><input type="radio" name="dir" value="LONG" ${dir0 === "LONG" ? "checked" : ""}><span>LONG ↑ (acheter)</span></label>
      <label class="short"><input type="radio" name="dir" value="SHORT" ${dir0 === "SHORT" ? "checked" : ""}><span>SHORT ↓ (vendre)</span></label>
    </div>

    <label class="champ"><span>Prix d'entrée (limite)${q ? ` en ${esc(q)}` : ""}</span><input name="entry" inputmode="decimal" value="${r6(entry0)}">
      <small>${o.price ? `Prix actuel ${pq(o.price, o.inst.quote)}` : "Prix actuel indisponible"}</small></label>

    <div class="choix" role="radiogroup" aria-label="Choix de la taille">
      <label><input type="radio" name="size" value="qty" ${sizeMode0 === "qty" ? "checked" : ""}><span>Je choisis la quantité (comme Kraken)</span></label>
      <label><input type="radio" name="size" value="risk" ${sizeMode0 === "risk" ? "checked" : ""}><span>Automatique (risque en %)</span></label>
    </div>

    <div data-size="qty">
      <div class="deux">
        <label class="champ"><span>Quantité (${baseName})</span><input name="qty" inputmode="decimal" placeholder="0">
          <small>${o.inst.ordermin ? `Minimum Kraken : ${o.inst.ordermin} ${baseName}` : "&nbsp;"}</small></label>
        <label class="champ"><span>ou montant (${esc(q || "total")})</span><input name="amount" inputmode="decimal" placeholder="0">
          <small>= quantité × prix d'entrée</small></label>
      </div>
      <div class="ligne small">
        <span class="muted">Remplir pour risquer :</span>
        <button type="button" class="btn discret mini" data-fill="${+o.me.risk_pct || 1}">${String(+o.me.risk_pct || 1).replace(".", ",")} % (habituel)</button>
        <button type="button" class="btn discret mini" data-fill="${MAX_RISK_PCT}">${MAX_RISK_PCT} % (maximum)</button>
      </div>
      <div class="ligne small">
        <span class="muted">Ou engager en marge :</span>
        ${[10, 25, 50, 100].map((k) => `<button type="button" class="btn discret mini" data-marge="${k}">${k} %</button>`).join("")}
        <span class="muted">du solde</span>
      </div>
    </div>

    <label class="champ" data-size="risk"><span>Risque sur ce trade (%)</span>
      <input name="risk" inputmode="decimal" value="${Math.min(+o.me.risk_pct, Math.max(0.1, budget.availablePct)).toFixed(2)}">
      <small>Disponible : ${eur(budget.available)} (${pct(budget.availablePct, 2)})</small></label>

    <label class="champ"><span>Levier : <b id="lev-v">x1</b></span>
      <input type="range" name="lev" min="1" max="${maxLev}" step="1" value="${dir0 === "SHORT" && (o.inst.venue || "spot") === "spot" ? Math.min(2, maxLev) : 1}">
      <small>Le levier réduit la marge bloquée et rapproche la liquidation. Il ne change <b>pas</b> ta perte au SL.</small></label>

    <label class="champ"><span>Stop loss (SL) — facultatif</span><input name="sl" inputmode="decimal" value="${r6(s?.sl)}" placeholder="aucun">
      <small>Là où tu coupes si ça va mal. Sans stop, tu peux perdre la marge du trade (liquidation), jamais plus.</small></label>
    <div class="trois">
      <label class="champ"><span>TP1 · 30 %</span><input name="tp1" inputmode="decimal" value="${r6(s?.tp1)}"></label>
      <label class="champ"><span>TP2 · 40 %</span><input name="tp2" inputmode="decimal" value="${r6(s?.tp2)}"></label>
      <label class="champ"><span>TP3 · 30 %</span><input name="tp3" inputmode="decimal" value="${r6(s?.tp3)}"></label>
    </div>

    <div class="choix" role="radiogroup" aria-label="Type de trade">
      <label><input type="radio" name="mode" value="paper" checked><span>Entraînement (paper)</span></label>
      <label><input type="radio" name="mode" value="reel"><span>Réel (passé sur Kraken)</span></label>
    </div>
    <label class="champ"><span>Note (facultatif)</span><input name="notes" maxlength="300" placeholder="Pourquoi je prends ce trade"></label>
    <div id="plan" aria-live="polite"></div>
    <button class="btn principal plein" type="submit">Enregistrer le trade</button>
  </form>`;

  const f = host.querySelector("form");
  let plan = null;
  let userTouchedLev = false;
  let lastEdited = "qty"; // quantité ou montant : le dernier champ tapé fait foi

  const v = (n) => num(f.elements[n].value);
  const sizeMode = () => f.elements.size.value;
  const base = () => ({
    direction: f.elements.dir.value, entry: v("entry"), sl: v("sl"), tps: [v("tp1"), v("tp2"), v("tp3")].filter((x) => x != null),
    balance: +o.me.balance_eur, feeTaker: o.feeTaker, feeMaker: o.feeMaker, entryIsMaker: !!(s && !inZone),
    eurPerQuote: o.eurPerQuote, lotDecimals: o.inst.lot_decimals ?? 8, ordermin: o.inst.ordermin || 0, venue: o.inst.venue || "spot",
    usedMarginEur: usedMarginEur(o.trades),
  });

  function syncQtyAmount() {
    const e = v("entry");
    if (!(e > 0)) return;
    if (lastEdited === "qty") { const qq = v("qty"); f.elements.amount.value = qq > 0 ? r6(qq * e) : ""; }
    else { const a = v("amount"); f.elements.qty.value = a > 0 ? r6(a / e) : ""; }
  }

  function showMode() {
    const m = sizeMode();
    f.querySelectorAll("[data-size]").forEach((el) => { el.hidden = el.dataset.size !== m; });
    try { localStorage.setItem("ldk-size-mode", m); } catch { /* sans stockage, tant pis */ }
  }

  function update() {
    showMode();
    const p = base();
    const lev = +f.elements.lev.value;
    f.querySelector("#lev-v").textContent = "x" + lev;
    if (sizeMode() === "qty") {
      syncQtyAmount();
      plan = planFromQty({ ...p, qty: v("qty"), leverage: lev, riskPct: +o.me.risk_pct, maxRiskPct: MAX_RISK_PCT, strict: !free });
      // Tant que tu n'as pas touché au levier, on propose le plus petit qui permet de payer la marge (comme Kraken l'exigerait).
      if (!userTouchedLev && plan.notionalEur > p.balance * lev) {
        const sug = suggestLeverage(plan, p.balance, plan.slPct, maxLev);
        if (sug && sug > lev) { f.elements.lev.value = sug; return update(); }
      }
    } else {
      plan = planTrade({ ...p, riskPct: v("risk"), leverage: lev, strict: !free });
      if (!userTouchedLev && plan.notionalEur) {
        const sug = suggestLeverage(plan, p.balance, plan.slPct, maxLev);
        if (sug && sug !== lev) { f.elements.lev.value = sug; return update(); }
      }
      if (plan.ok && plan.effectiveRiskPct > MAX_RISK_PCT + 1e-9) {
        (free ? plan.warnings : plan.errors).push(free ? `Tu risques ${plan.effectiveRiskPct.toFixed(2)} % de ton solde (la règle du club conseille ${MAX_RISK_PCT} % maximum).`
          : `Règle du club : jamais plus de ${MAX_RISK_PCT} % du solde par trade.`);
      }
    }
    const errs = [...(plan.errors || [])];
    if (p.direction === "SHORT" && o.inst.can_short === false) errs.push("Cet instrument ne permet pas le SHORT sur Kraken (pas de marge).");
    const club = free ? plan.warnings : errs; // garde-fous du club : bloquants, ou simples avertissements s'ils sont coupés
    if (budget.dailyStop) club.push("Perte maximale du jour atteinte" + (free ? "." : " : pas de nouveau trade aujourd'hui."));
    if (plan.lossAtSlEur > budget.available + 1e-6) club.push(`Risque cumulé élevé : il te restait ${eur(budget.available)} de risque disponible selon tes réglages (tes autres trades ouverts comptent).`);
    plan.blocking = errs;
    render(p, lev, errs);
  }

  function render(p, lev, errs) {
    const box = f.querySelector("#plan");
    if (!p.entry || (sizeMode() === "risk" && !p.sl)) {
      box.innerHTML = `<p class="muted">${sizeMode() === "risk" ? "Le mode automatique a besoin d'un stop pour calculer la taille." : "Renseigne le prix d'entrée."}</p>`; return;
    }
    if (!plan.qty) {
      box.innerHTML = errs.length ? `<div class="alerte rouge"><ul>${errs.map((e) => `<li>${esc(e)}</li>`).join("")}</ul></div>` : "";
      return;
    }
    const lossPct = plan.effectiveRiskPct ?? (plan.lossAtSlEur / p.balance) * 100;
    const ton = lossPct > MAX_RISK_PCT + 1e-9 ? "short" : lossPct > +o.me.risk_pct + 1e-9 ? "ambre" : "long";
    box.innerHTML = `
      ${errs.length ? `<div class="alerte rouge"><ul>${errs.map((e) => `<li>${esc(e)}</li>`).join("")}</ul></div>` : ""}
      <div class="feu ${ton}"><span class="feu-icone">${ton === "long" ? "🛡️" : ton === "ambre" || free ? "⚠️" : "⛔"}</span>
        <div><strong>${plan.hasSl === false ? "Sans stop, perte max" : plan.liqBeforeSl ? "Liquidation avant le stop, perte max" : "Si le SL est touché"} : ${eur(-plan.lossAtSlEur)} (${pct(lossPct, 2)} de ton solde)</strong>
        <p>${ton === "long" ? "Dans ta règle de risque." : ton === "ambre" ? "Plus que ton risque habituel : seulement pour un setup exceptionnel."
          : free ? `Au-delà des ${MAX_RISK_PCT} % conseillés par le club.` : `Au-delà de ${MAX_RISK_PCT} % : interdit par la règle du club.`}</p></div></div>
      <div class="bloc"><div class="split">
        <dl class="chiffres" style="margin:0">
          <div><dt>Quantité à ${p.direction === "LONG" ? "acheter" : "vendre"}</dt><dd class="num">${+plan.qty.toPrecision(6)} ${baseName}</dd></div>
          <div><dt>Valeur de la position</dt><dd class="num">${eur(plan.notionalEur)}</dd></div>
          <div><dt>Marge isolée (x${lev})</dt><dd class="num">${eur(plan.marginEur)}</dd></div>
          ${plan.liqPrice ? `<div><dt>Liquidation ≈</dt><dd class="num perte">${pq(plan.liqPrice, o.inst.quote)}</dd></div>` : ""}
          ${plan.profitsEur.map((g, i) => `<div><dt>Gain au TP${i + 1} (${[30, 40, 30][i]} %)</dt><dd class="num gain">${eur(g, true)} · ${rr(plan.rr[i])}</dd></div>`).join("")}
        </dl>
        ${ladder({ direction: p.direction, entryLow: p.entry, entryHigh: p.entry, sl: p.sl || plan.liqPrice, slLabel: p.sl ? "SL" : "Liq.", tps: p.tps, price: o.price, compact: true })}
      </div>
      ${plan.warnings.map((w) => `<p class="small muted">⚠ ${esc(w)}</p>`).join("")}
      <p class="small muted">Marge isolée : ce trade n'engage que ${eur(plan.marginEur)}. Le reste de ton capital n'est jamais touché par lui
        ${plan.freeMarginEur != null ? ` (marge encore libre avant ce trade : ${eur(plan.freeMarginEur)})` : ""}.${plan.liqPrice ? " Liquidation approximative : Kraken peut liquider un peu avant selon ses niveaux de marge." : ""}</p>
      <p class="small muted">Sur Kraken : ${p.direction === "LONG" ? "Acheter" : "Vendre"} · Limite ${pq(p.entry, o.inst.quote)} · Quantité ${+plan.qty.toPrecision(6)} ${baseName} · Levier ${lev > 1 ? "x" + lev + " · marge isolée" : "aucun (x1)"}${p.sl ? ` · Stop ${pq(p.sl, o.inst.quote)}` : " · sans stop"}.
        R:R net de frais : ${plan.rrNet.map((r, i) => `TP${i + 1} ${r.toFixed(1)}`).join(" · ")}.</p></div>`;
  }

  // Bouton « remplir pour risquer X % » : calcule la quantité correspondante.
  f.querySelectorAll("[data-fill]").forEach((b) => b.addEventListener("click", () => {
    const qq = qtyForRisk(base(), +b.dataset.fill);
    if (!qq) { toast("Renseigne d'abord l'entrée et le SL.", true); return; }
    lastEdited = "qty";
    f.elements.qty.value = r6(qq);
    update();
  }));
  // Bouton « engager X % du solde en marge » (comme le curseur de Kraken) : quantité = solde × X % × levier / prix.
  f.querySelectorAll("[data-marge]").forEach((b) => b.addEventListener("click", () => {
    const p = base();
    if (!(p.entry > 0) || !(p.eurPerQuote > 0)) { toast("Renseigne d'abord le prix d'entrée.", true); return; }
    const lev = +f.elements.lev.value;
    const qq = ((p.balance * +b.dataset.marge) / 100) * lev / (p.entry * p.eurPerQuote);
    lastEdited = "qty";
    userTouchedLev = true; // on garde le levier choisi
    f.elements.qty.value = r6(Math.floor(qq * 10 ** (p.lotDecimals ?? 8)) / 10 ** (p.lotDecimals ?? 8));
    update();
  }));
  f.addEventListener("input", (e) => {
    if (e.target.name === "lev") userTouchedLev = true;
    if (e.target.name === "qty") lastEdited = "qty";
    if (e.target.name === "amount") lastEdited = "amount";
    update();
  });
  f.addEventListener("change", (e) => { if (e.target.name === "size" || e.target.name === "dir") update(); });

  f.addEventListener("submit", (e) => {
    e.preventDefault();
    update();
    if (!plan?.ok || plan.blocking.length) { toast(plan?.blocking?.[0] || plan?.errors?.[0] || "Vérifie les champs.", true); return; }
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
        eur_per_quote: o.eurPerQuote, fee_pct: o.feeTaker, balance_at_entry: +o.me.balance_eur,
        realized_pnl_eur: -(plan.entryFeeEur || 0), strategy: s?.strategy || "manuel", notes: f.elements.notes.value || null,
        events: [{ at: new Date().toISOString(), text: `Ouverture ${mode === "reel" ? "réelle" : "paper"} à ${x.entry} · ${+plan.qty.toPrecision(6)} ${o.inst.display.split("/")[0]} · x${lev}` }],
      });
      toast("Trade enregistré. Le bot le suivra à chaque scan.");
      o.go(`#/trade/${t.id}`);
    });
  });

  // Signal : on pré-remplit la quantité qui correspond à ton risque habituel (modifiable).
  if (s && sizeMode() === "qty") {
    const qq = qtyForRisk(base(), Math.min(+o.me.risk_pct || 1, Math.max(0.01, budget.availablePct)));
    if (qq) f.elements.qty.value = r6(qq);
  }
  update();
}
