// Graphique d'une paire : vraies bougies Kraken en direct, outils d'analyse pour apprendre,
// signaux du bot et trades du club sur cette paire. Rien n'est inventé : sans données Kraken, on le dit.
import {
  createChart, CandlestickSeries, HistogramSeries, LineSeries, LineStyle, createSeriesMarkers,
} from "../../vendor/lightweight-charts.mjs";
import { THEME } from "../charts.js";
import { backend, DEMO } from "../data.js";
import { ema, lecture, niveaux, rsi, structure, vwap } from "../indicators.js";
import { krakenLink, ohlc, prices } from "../market.js";
import { STRAT, ago, cls, dt, esc, eur, pct, pq, px, rr } from "../ui.js";
import { ONGLETS } from "./markets.js";

const UT = [[5, "5 min"], [15, "15 min"], [60, "1 h"], [240, "4 h"], [1440, "1 jour"]];
const OUTILS = {
  ema: ["Moyennes EMA 20 / 50", "Deux lignes qui lissent le prix. EMA 20 (ambre) au-dessus de l'EMA 50 (bleue) et prix au-dessus : tendance plutôt haussière. L'inverse : plutôt baissière. Quand elles s'emmêlent : pas de tendance."],
  volume: ["Volume", "Barres en bas : combien a été échangé à chaque bougie. Une cassure avec un gros volume est plus crédible qu'une cassure sans volume."],
  niveaux: ["Supports / résistances", "Lignes bleues : prix où le marché a rebondi ou buté plusieurs fois. Un support peut freiner une baisse, une résistance une hausse. Une fois cassé, un niveau change souvent de rôle (retest)."],
  structure: ["Structure HH / HL", "Étiquettes sur les sommets et creux : HH = sommet plus haut, HL = creux plus haut (montée) ; LH = sommet plus bas, LL = creux plus bas (baisse). C'est la base de la lecture d'une tendance."],
  rsi: ["RSI", "Jauge de 0 à 100 sous le graphique. Au-dessus de 70 : beaucoup d'achats récents (le mouvement peut s'essouffler). Sous 30 : beaucoup de ventes. Indicateur secondaire : jamais seul pour entrer."],
  vwap: ["VWAP", "Prix moyen du jour pondéré par le volume (ligne violette). Au-dessus : les acheteurs du jour sont gagnants en moyenne ; en dessous : les vendeurs."],
  bot: ["Plan du bot", "Zone d'entrée (ambre), stop (rouge) et objectifs (vert) du signal choisi plus bas."],
  club: ["Trades du club", "Flèches : entrées des membres sur cette paire (LONG ↑ vert, SHORT ↓ rouge)."],
};
const DEFAUT = ["ema", "volume", "niveaux", "bot", "club"];
const COUL = { e20: "#F2B544", e50: "#6FA8DC", vwap: "#B48EF0", niveau: "#6FA8DC", sl: "#FF6B6B", tp: "#3DDC97", zone: "#F2B544" };

const lire = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } };
const ecrire = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* sans stockage */ } };

export async function render(main, ctx, rawKey) {
  const key = decodeURIComponent(rawKey || "");
  const inst = await backend.instrument(key).catch(() => null);
  if (!inst) {
    main.innerHTML = `<a href="#/graphiques" class="muted small">← Graphiques</a>
      <div class="vide"><strong>Paire introuvable</strong>Elle n'est peut-être plus disponible sur Kraken Pro France.</div>`;
    return;
  }
  const [sigs, trades] = await Promise.all([
    backend.signalsFor(key, 20).catch(() => []),
    backend.trades({ instrumentKey: key, limit: 50 }).catch(() => []),
  ]);
  const onglet = ONGLETS.find(([c]) => c === inst.asset_class)?.[1] || "Autres";
  let ut = lire("ldk-ut", 15);
  let outils = new Set(lire("ldk-outils", DEFAUT));
  const actif = sigs.find((s) => !(s.expires_at && new Date(s.expires_at) < new Date())) || null;
  let sigVu = actif?.id ?? null;

  main.innerHTML = `
    <a href="#/graphiques/${esc(inst.asset_class || "crypto")}" class="muted small">← Graphiques · ${esc(onglet)}</a>
    <div class="ligne entre" style="margin-top:8px;align-items:baseline">
      <h1 style="margin:0">${esc(inst.display)}</h1>
      <div class="num" id="prix"><span class="muted small">prix…</span></div>
    </div>
    <p class="muted small">${esc(onglet)} · ${inst.venue === "futures" ? "futures" : "spot"}${inst.can_short ? " · short possible" : " · pas de short"}${inst.max_leverage > 1 ? ` · levier max ×${inst.max_leverage}` : " · sans levier"}${DEMO ? " · <b>DÉMO : bougies fictives</b>" : ""}</p>
    <div class="ligne">
      <a class="btn principal" href="#/trade/nouveau/${encodeURIComponent(key)}">Trader cette paire</a>
      <a class="btn discret" href="${krakenLink(inst)}" target="_blank" rel="noopener">Ouvrir sur Kraken</a>
    </div>

    <div class="onglets ut section" role="group" aria-label="Durée d'une bougie">
      ${UT.map(([v, l]) => `<button type="button" class="onglet" data-ut="${v}" aria-selected="${v === ut}">${l}</button>`).join("")}
    </div>
    <div class="outils" role="group" aria-label="Outils d'analyse">
      ${Object.entries(OUTILS).map(([k, [l]]) => `<button type="button" class="btn mini ${outils.has(k) ? "actif" : "discret"}" data-outil="${k}" aria-pressed="${outils.has(k)}">${l}</button>`).join("")}
    </div>
    <div class="graph-paire" id="g"></div>
    <p class="small muted" id="g-note">Chargement des bougies Kraken…</p>

    <section class="section grille">
      <div class="bloc pile"><h2>Lecture rapide</h2><div id="lecture"><p class="muted">Calcul…</p></div>
        <p class="small muted">Calculée automatiquement sur les bougies affichées, pour apprendre à lire le graphique.
          Ce n'est pas un signal : seul le bot (avec ses confirmations) propose des trades.</p></div>
      <div class="bloc pile"><h2>Ce que tu vois</h2><ul id="aide" class="aide-outils"></ul></div>
    </section>

    <section class="section"><h2>Signaux du bot sur ${esc(inst.display)}</h2>
      ${sigs.length ? `<div class="pile">${sigs.slice(0, 10).map((s) => sigLigne(s)).join("")}</div>`
        : '<p class="muted">Le bot n\'a proposé aucun setup sur cette paire ces derniers jours.</p>'}</section>

    <section class="section"><h2>Trades du club sur ${esc(inst.display)}</h2>
      ${trades.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Membre</th><th>Sens</th><th>Entrée</th><th>Stop</th><th>État</th><th>Résultat</th></tr></thead>
        <tbody>${trades.slice(0, 30).map((t) => `<tr>
          <td><a href="#/trade/${t.id}">${esc(t.profiles?.pseudo || "membre")}</a><br><span class="small muted">${ago(t.opened_at)} · ${t.mode === "reel" ? "réel" : "paper"} · x${t.leverage}</span></td>
          <td class="${t.direction === "LONG" ? "gain" : "perte"}">${t.direction === "LONG" ? "LONG ↑" : "SHORT ↓"}</td>
          <td class="num">${pq(+t.entry_price, t.quote)}</td>
          <td class="num">${t.sl != null ? pq(+t.sl, t.quote) : "aucun"}</td>
          <td>${t.status === "ouvert" ? '<span class="pastille ambre">en cours</span>' : esc(t.close_reason || t.status)}</td>
          <td class="num ${cls(+t.realized_pnl_eur)}">${t.status === "ouvert" ? "—" : `${eur(+t.realized_pnl_eur, true)}${t.r_multiple != null ? `<br><span class="small">${rr(+t.r_multiple)}</span>` : ""}`}</td>
        </tr>`).join("")}</tbody></table></div>`
        : '<p class="muted">Aucun membre n\'a encore pris de trade sur cette paire.</p>'}</section>`;

  const el = main.querySelector("#g");
  const note = main.querySelector("#g-note");
  let chart = null, candles = [], series = null, stopped = false, live = false;

  function sigLigne(s) {
    const exp = s.expires_at && new Date(s.expires_at) < new Date();
    return `<div class="bloc sig-ligne">
      <div class="ligne entre"><span><b class="${s.direction === "LONG" ? "gain" : "perte"}">${s.direction === "LONG" ? "LONG ↑" : "SHORT ↓"}</b>
        · ${esc(STRAT[s.strategy] || s.strategy)} · ${ago(s.created_at)}</span>
        <span class="pastille ${exp ? "" : s.status === "TRADE" ? "long" : "ambre"}">${exp ? "expiré" : s.status === "TRADE" ? "🟢 validé" : "🟡 à surveiller"}</span></div>
      <span class="small num">Entrée ${px(+s.entry_low)} – ${pq(+s.entry_high, s.quote)} · Stop ${pq(+s.sl, s.quote)} · Obj. 1 ${pq(+s.tp1, s.quote)}</span>
      <div class="ligne"><button type="button" class="btn mini discret" data-voir="${s.id}">Voir sur le graphique</button>
        <a class="btn mini discret" href="#/signal/${s.id}">Ouvrir le signal</a></div></div>`;
  }

  // ------------------------------------------------------------------ dessin
  function build() {
    const keep = chart ? chart.timeScale().getVisibleLogicalRange() : null;
    chart?.remove();
    el.innerHTML = "";
    if (!candles.length) { note.textContent = "Bougies Kraken indisponibles pour l'instant : pas de graphique (rien n'est inventé)."; return; }
    const jour = ut >= 1440;
    chart = createChart(el, {
      ...THEME, autoSize: true,
      timeScale: { ...THEME.timeScale, rightOffset: 4,
        tickMarkFormatter: (t, type) => {
          const d = new Date(t * 1000);
          return type <= 2 || jour ? d.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" }) : d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
        } },
      rightPriceScale: { ...THEME.rightPriceScale, scaleMargins: { top: 0.08, bottom: outils.has("volume") ? 0.22 : 0.08 } },
    });
    const data = candles.map((k) => ({ time: +k[0], open: +k[1], high: +k[2], low: +k[3], close: +k[4] }));
    series = chart.addSeries(CandlestickSeries, {
      upColor: "#3DDC97", downColor: "#FF6B6B", borderVisible: false, wickUpColor: "#3DDC97", wickDownColor: "#FF6B6B",
    });
    series.setData(data);
    const closes = candles.map((k) => +k[4]);
    const ligne = (vals, color, title) => {
      const s = chart.addSeries(LineSeries, { color, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, title });
      s.setData(vals.map((v, i) => (v == null ? null : { time: +candles[i][0], value: v })).filter(Boolean));
    };
    if (outils.has("ema")) { ligne(ema(closes, 20), COUL.e20, "EMA 20"); ligne(ema(closes, 50), COUL.e50, "EMA 50"); }
    if (outils.has("vwap")) {
      const v = vwap(candles);
      if (v.some((x) => x != null)) ligne(v, COUL.vwap, "VWAP");
    }
    if (outils.has("volume") && candles.some((k) => k[5] != null)) {
      const vol = chart.addSeries(HistogramSeries, { priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
      chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      vol.setData(candles.map((k) => ({ time: +k[0], value: +k[5] || 0, color: +k[4] >= +k[1] ? "rgba(61,220,151,.35)" : "rgba(255,107,107,.35)" })));
    }
    if (outils.has("rsi")) {
      const r = chart.addSeries(LineSeries, { color: "#E9EFF4", lineWidth: 1.5, priceLineVisible: false, lastValueVisible: true, title: "RSI",
        priceFormat: { type: "custom", minMove: 1, formatter: (v) => String(Math.round(v)) } }, 1);
      r.setData(rsi(candles).map((v, i) => (v == null ? null : { time: +candles[i][0], value: v })).filter(Boolean));
      for (const [lvl, c] of [[70, "#FF6B6B"], [30, "#3DDC97"]]) r.createPriceLine({ price: lvl, color: c, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: String(lvl) });
      chart.panes()[1]?.setHeight(90);
    }
    const pl = (price, color, title, dashed = false, width = 1) => price != null && isFinite(+price) &&
      series.createPriceLine({ price: +price, color, lineWidth: width, lineStyle: dashed ? LineStyle.Dashed : LineStyle.Solid, axisLabelVisible: true, title });
    if (outils.has("niveaux")) {
      const nv = niveaux(candles, { max: 2 });
      nv.supports.forEach((g) => pl(g.price, COUL.niveau, `Support ×${g.touches}`, true));
      nv.resistances.forEach((g) => pl(g.price, COUL.niveau, `Résistance ×${g.touches}`, true));
    }
    const s = sigs.find((x) => x.id === sigVu);
    if (outils.has("bot") && s) {
      pl(s.entry_high, COUL.zone, "Entrée", true, 2); pl(s.entry_low, COUL.zone, "", true, 1);
      pl(s.sl, COUL.sl, "Stop", false, 2);
      [s.tp1, s.tp2, s.tp3].forEach((t, i) => pl(t, COUL.tp, `Obj. ${i + 1}`));
    }
    // Repères : structure (HH/HL…) et entrées des membres.
    const marks = [];
    const t0 = +candles[0][0], step = ut * 60;
    if (outils.has("structure")) {
      for (const l of structure(candles).labels.slice(-12)) {
        marks.push({ time: l.time, position: l.type === "H" ? "aboveBar" : "belowBar", shape: "circle", size: 0.6,
          color: l.label === "HH" || l.label === "HL" ? "#3DDC97" : "#FF6B6B", text: l.label });
      }
    }
    if (outils.has("club")) {
      for (const t of trades) {
        const tt = Math.floor(new Date(t.opened_at).getTime() / 1000 / step) * step;
        if (!(tt >= t0)) continue;
        const L = t.direction === "LONG";
        marks.push({ time: tt, position: L ? "belowBar" : "aboveBar", shape: L ? "arrowUp" : "arrowDown", color: L ? "#3DDC97" : "#FF6B6B",
          text: t.profiles?.pseudo || "membre" });
      }
    }
    if (marks.length) createSeriesMarkers(series, marks.filter((m) => data.some((d) => d.time === m.time)).sort((a, b) => a.time - b.time));
    if (keep && keep.to - keep.from > 5) chart.timeScale().setVisibleLogicalRange(keep);
    else chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, data.length - (el.clientWidth < 520 ? 60 : 120)), to: data.length + 3 });
    note.textContent = DEMO ? "Mode démo : bougies fictives." : `Bougies ${UT.find(([v]) => v === ut)[1]} Kraken${live ? ", mises à jour toutes les 30 s" : ""}. Glisse pour te déplacer, pince pour zoomer.`;
  }

  function aide() {
    main.querySelector("#aide").innerHTML = [...outils].filter((k) => OUTILS[k]).map((k) => `<li><b>${OUTILS[k][0]} :</b> ${OUTILS[k][1]}</li>`).join("")
      || '<li class="muted">Active un outil au-dessus du graphique pour voir son explication.</li>';
  }

  function lect() {
    const l = lecture(candles);
    const box = main.querySelector("#lecture");
    if (!l) { box.innerHTML = '<p class="muted">Pas assez de bougies pour une lecture (il en faut au moins 30).</p>'; return; }
    const d = (p) => (p == null ? "" : ` (${((p - l.prix) / l.prix * 100 > 0 ? "+" : "")}${((p - l.prix) / l.prix * 100).toLocaleString("fr-FR", { maximumFractionDigits: 2 })} %)`);
    const ton = (t) => (t === "haussière" ? "gain" : t === "baissière" ? "perte" : "");
    box.innerHTML = `<dl class="lecture">
      <div><dt>Tendance (EMA)</dt><dd class="${ton(l.tendanceEma)}">${esc(l.tendanceEma || "—")}</dd></div>
      <div><dt>Structure</dt><dd class="${ton(l.structure)}">${esc(l.structure)}${l.lastHigh ? ` <span class="small muted">(${l.lastHigh} · ${l.lastLow || "—"})</span>` : ""}</dd></div>
      <div><dt>RSI 14</dt><dd>${l.rsi != null ? `${Math.round(l.rsi)} <span class="small muted">· ${esc(l.rsiMot)}</span>` : "—"}</dd></div>
      <div><dt>Volatilité (ATR)</dt><dd>${l.atrPct != null ? `${pct(l.atrPct, 2)} <span class="small muted">par bougie en moyenne</span>` : "—"}</dd></div>
      <div><dt>Support proche</dt><dd class="num">${l.support ? pq(l.support.price, inst.quote) + d(l.support.price) : "aucun net"}</dd></div>
      <div><dt>Résistance proche</dt><dd class="num">${l.resistance ? pq(l.resistance.price, inst.quote) + d(l.resistance.price) : "aucune nette"}</dd></div>
      <div><dt>Volume</dt><dd>${l.volRel != null ? `${l.volRel >= 1.5 ? "fort" : l.volRel <= 0.6 ? "faible" : "normal"} <span class="small muted">(×${l.volRel.toLocaleString("fr-FR", { maximumFractionDigits: 1 })} la moyenne)</span>` : "—"}</dd></div>
    </dl>`;
  }

  // ------------------------------------------------------------------ données
  async function charger() {
    note.textContent = "Chargement des bougies Kraken…";
    try { candles = (await ohlc(inst, ut)).map((k) => [...k]); live = true; } catch { candles = []; live = false; }
    if (stopped) return;
    build(); lect();
  }

  async function prix() {
    if (stopped || document.hidden) return;
    const r = await prices([inst], { fx: false }).catch(() => null);
    const p = r?.get(inst);
    const box = main.querySelector("#prix");
    if (!p?.last) { box.innerHTML = '<span class="muted small">prix indisponible</span>'; return; }
    const ch = p.open > 0 ? ((p.last - p.open) / p.open) * 100 : null;
    box.innerHTML = `<b>${pq(p.last, inst.quote)}</b> ${ch != null ? `<span class="small ${cls(ch)}">${ch >= 0 ? "+" : ""}${ch.toLocaleString("fr-FR", { maximumFractionDigits: 2 })} %</span>` : ""}`;
    if (!candles.length || !series) return;
    const step = ut * 60, last = candles.at(-1);
    if (Math.floor(Date.now() / 1000 / step) * step > +last[0]) { charger(); return; } // nouvelle bougie : on recharge les vraies
    last[4] = p.last; last[2] = Math.max(+last[2], p.last); last[3] = Math.min(+last[3], p.last);
    series.update({ time: +last[0], open: +last[1], high: +last[2], low: +last[3], close: +last[4] });
  }

  // ------------------------------------------------------------------ interactions
  main.querySelectorAll("[data-ut]").forEach((b) => b.addEventListener("click", () => {
    ut = +b.dataset.ut; ecrire("ldk-ut", ut);
    main.querySelectorAll("[data-ut]").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
    chart?.remove(); chart = null;
    charger();
  }));
  main.querySelectorAll("[data-outil]").forEach((b) => b.addEventListener("click", () => {
    const k = b.dataset.outil;
    outils.has(k) ? outils.delete(k) : outils.add(k);
    ecrire("ldk-outils", [...outils]);
    b.classList.toggle("actif", outils.has(k)); b.classList.toggle("discret", !outils.has(k)); b.setAttribute("aria-pressed", outils.has(k));
    build(); aide();
  }));
  main.querySelectorAll("[data-voir]").forEach((b) => b.addEventListener("click", () => {
    sigVu = +b.dataset.voir;
    if (!outils.has("bot")) {
      outils.add("bot"); ecrire("ldk-outils", [...outils]);
      const ob = main.querySelector('[data-outil="bot"]');
      ob.classList.add("actif"); ob.classList.remove("discret"); ob.setAttribute("aria-pressed", "true");
    }
    build(); aide();
    el.scrollIntoView({ behavior: "smooth", block: "center" });
  }));

  aide();
  await charger();
  prix();
  const timer = setInterval(prix, 30_000);
  ctx.onLeave(() => { stopped = true; clearInterval(timer); chart?.remove(); });
}
