// Formulaire « prendre un trade » : partagé par la page signal et le trade manuel.
// Tout se recalcule en direct : taille, marge, perte au SL, gains, R:R — avec le solde et le risque du membre.
import { backend } from "../data.js";
import { ladder } from "../ladder.js";
import { planTrade, riskBudget, suggestLeverage } from "../sizing.js";
import { busy, esc, eur, num, pct, pq, px, rr, sym, toast } from "../ui.js";

/**
 * @param host élément où afficher le formulaire
 * @param o { me, trades (du membre), inst {display, venue, api_symbol, api_asset_class, asset_class, quote, instrument_key,
 *            can_short, max_leverage, lot_decimals, ordermin}, signal?, price?, eurPerQuote, feeTaker, feeMaker, go }
 */
const r6 = (x) => (x == null || !isFinite(x) ? "" : String(+(+x).toPrecision(6)));

export function tradeForm(host, o) {
  const s = o.signal;
  const dir0 = s?.direction || "LONG";
  const inZone = s && o.price && o.price >= s.entry_low && o.price <= s.entry_high;
  const entry0 = s ? (inZone ? o.price : (dir0 === "LONG" ? s.entry_high : s.entry_low)) : o.price;
  const budget = riskBudget(o.me, o.trades);
  const maxLev = Math.max(1, Math.min(10, o.inst.max_leverage || 10));
  host.innerHTML = `
  <form class="form" novalidate>
    <div class="choix" role="radiogroup" aria-label="Sens">
      <label class="long"><input type="radio" name="dir" value="LONG" ${dir0 === "LONG" ? "checked" : ""}><span>LONG ↑ (achat)</span></label>
      <label class="short"><input type="radio" name="dir" value="SHORT" ${dir0 === "SHORT" ? "checked" : ""}><span>SHORT ↓ (vente)</span></label>
    </div>
    <div class="deux">
      <label class="champ"><span>Prix d'entrée${sym(o.inst.quote) ? " (" + sym(o.inst.quote).trim() + ")" : ""}</span><input name="entry" inputmode="decimal" value="${r6(entry0)}">
        <small>${o.price ? `Prix actuel ${pq(o.price, o.inst.quote)}` : "Prix actuel indisponible"}</small></label>
      <label class="champ"><span>Stop loss (SL)</span><input name="sl" inputmode="decimal" value="${r6(s?.sl)}">
        <small>Là où tu coupes si ça va mal</small></label>
    </div>
    <div class="trois">
      <label class="champ"><span>TP1 · 30 %</span><input name="tp1" inputmode="decimal" value="${r6(s?.tp1)}"></label>
      <label class="champ"><span>TP2 · 40 %</span><input name="tp2" inputmode="decimal" value="${r6(s?.tp2)}"></label>
      <label class="champ"><span>TP3 · 30 %</span><input name="tp3" inputmode="decimal" value="${r6(s?.tp3)}"></label>
    </div>
    <div class="deux">
      <label class="champ"><span>Multiplicateur : <b id="lev-v">x1</b></span>
        <input type="range" name="lev" min="1" max="${maxLev}" step="1" value="1">
        <small>Change la marge bloquée, <b>jamais</b> ta perte au SL.</small></label>
      <label class="champ"><span>Risque sur ce trade (%)</span>
        <input name="risk" inputmode="decimal" value="${Math.min(+o.me.risk_pct, Math.max(0.1, budget.availablePct)).toFixed(2)}">
        <small>Disponible : ${eur(budget.available)} (${pct(budget.availablePct, 2)})</small></label>
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

  function read() {
    const v = (n) => num(f.elements[n].value);
    return {
      direction: f.elements.dir.value, entry: v("entry"), sl: v("sl"), tps: [v("tp1"), v("tp2"), v("tp3")].filter((x) => x != null),
      lev: +f.elements.lev.value, risk: v("risk"), mode: f.elements.mode.value,
    };
  }

  function update() {
    const x = read();
    f.querySelector("#lev-v").textContent = "x" + x.lev;
    const p = { balance: +o.me.balance_eur, riskPct: x.risk, entry: x.entry, sl: x.sl, tps: x.tps, direction: x.direction,
      feeTaker: o.feeTaker, feeMaker: o.feeMaker, entryIsMaker: !!(s && !inZone), eurPerQuote: o.eurPerQuote,
      lotDecimals: o.inst.lot_decimals ?? 8, ordermin: o.inst.ordermin || 0 };
    plan = planTrade({ ...p, leverage: x.lev });
    if (!userTouchedLev && plan.notionalEur) {
      const sug = suggestLeverage(plan, p.balance, plan.slPct, maxLev);
      if (sug && sug !== x.lev) { f.elements.lev.value = sug; return update(); }
    }
    const errs = [...plan.errors];
    if (x.direction === "SHORT" && o.inst.can_short === false) errs.push("Cet instrument ne permet pas le SHORT sur Kraken (pas de marge).");
    if (budget.dailyStop) errs.push("Perte maximale du jour atteinte : pas de nouveau trade aujourd'hui.");
    if (plan.ok && plan.lossAtSlEur > budget.available + 1e-6) errs.push(`Risque cumulé trop élevé : il te reste ${eur(budget.available)} de risque disponible.`);
    plan.blocking = errs;
    const box = f.querySelector("#plan");
    if (!x.entry || !x.sl) { box.innerHTML = '<p class="muted">Renseigne l\'entrée et le SL pour voir la taille.</p>'; return; }
    box.innerHTML = `
      ${errs.length ? `<div class="alerte rouge"><ul>${errs.map((e) => `<li>${esc(e)}</li>`).join("")}</ul></div>` : ""}
      ${plan.qty ? `<div class="bloc"><div class="split">
        <dl class="chiffres" style="margin:0">
          <div><dt>Quantité à ${x.direction === "LONG" ? "acheter" : "vendre"}</dt><dd class="num">${+plan.qty.toPrecision(6)} ${esc(o.inst.display.split("/")[0])}</dd></div>
          <div><dt>Valeur de la position</dt><dd class="num">${eur(plan.notionalEur)}</dd></div>
          <div><dt>Marge bloquée (x${x.lev})</dt><dd class="num">${eur(plan.marginEur)}</dd></div>
          <div><dt>Perte si SL touché</dt><dd class="num perte">${eur(-plan.lossAtSlEur)}</dd></div>
          ${plan.profitsEur.map((g, i) => `<div><dt>Gain au TP${i + 1} (${[30, 40, 30][i]} %)</dt><dd class="num gain">${eur(g, true)} · ${rr(plan.rr[i])}</dd></div>`).join("")}
        </dl>
        ${ladder({ direction: x.direction, entryLow: x.entry, entryHigh: x.entry, sl: x.sl, tps: x.tps, price: o.price, compact: true })}
      </div>
      ${plan.warnings.map((w) => `<p class="small muted">⚠ ${esc(w)}</p>`).join("")}
      <p class="small muted">R:R net de frais : ${plan.rrNet.map((r, i) => `TP${i + 1} ${r.toFixed(1)}`).join(" · ")} (frais estimés ${o.feeTaker} % par ordre au marché, ${o.feeMaker} % en limite)</p></div>` : ""}`;
  }

  f.addEventListener("input", (e) => { if (e.target.name === "lev") userTouchedLev = true; update(); });
  f.addEventListener("submit", (e) => {
    e.preventDefault();
    update();
    if (!plan?.ok || plan.blocking.length) { toast(plan?.blocking?.[0] || plan?.errors?.[0] || "Vérifie les champs.", true); return; }
    const x = read();
    const btn = f.querySelector("[type=submit]");
    busy(btn, async () => {
      const t = await backend.createTrade({
        signal_id: s?.id ?? null, instrument_key: o.inst.instrument_key || o.inst.key, display: o.inst.display,
        venue: o.inst.venue, api_symbol: o.inst.api_symbol, api_asset_class: o.inst.api_asset_class || null,
        asset_class: o.inst.asset_class, quote: o.inst.quote || "EUR", direction: x.direction, mode: x.mode,
        entry_price: x.entry, sl: x.sl, tp1: x.tps[0] ?? null, tp2: x.tps[1] ?? null, tp3: x.tps[2] ?? null,
        leverage: x.lev, qty: plan.qty, qty_remaining: plan.qty, risk_eur: +plan.lossAtSlEur.toFixed(4),
        eur_per_quote: o.eurPerQuote, fee_pct: o.feeTaker, balance_at_entry: +o.me.balance_eur,
        realized_pnl_eur: -(plan.entryFeeEur || 0), strategy: s?.strategy || "manuel", notes: f.elements.notes.value || null,
        events: [{ at: new Date().toISOString(), text: `Ouverture ${x.mode === "reel" ? "réelle" : "paper"} à ${x.entry}` }],
      });
      toast("Trade enregistré. Le bot le suivra à chaque scan.");
      o.go(`#/trade/${t.id}`);
    });
  });
  update();
}
