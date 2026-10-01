// Graphiques en chandeliers (TradingView Lightweight Charts, licence Apache 2.0, intégré au site).
import { createChart, CandlestickSeries, LineSeries, LineStyle, createSeriesMarkers } from "../vendor/lightweight-charts.mjs";
import { px } from "./ui.js";

export const THEME = {
  layout: { background: { color: "#14243A" }, textColor: "#9DB4C8", fontFamily: "Atkinson Hyperlegible, sans-serif" },
  grid: { vertLines: { color: "rgba(39,64,95,.45)" }, horzLines: { color: "rgba(39,64,95,.45)" } },
  rightPriceScale: { borderColor: "#27405F" },
  timeScale: {
    borderColor: "#27405F", timeVisible: true, secondsVisible: false,
    tickMarkFormatter: (t) => new Date(t * 1000).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }),
  },
  crosshair: { mode: 0 },
  localization: {
    locale: "fr-FR",
    priceFormatter: (p) => px(p),
    timeFormatter: (t) => new Date(t * 1000).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }),
  },
};

export function candleChart(el, candles, { lines = [], markers = [], fit = true } = {}) {
  el.innerHTML = "";
  const chart = createChart(el, { ...THEME, autoSize: true });
  const s = chart.addSeries(CandlestickSeries, {
    upColor: "#3DDC97", downColor: "#FF6B6B", borderVisible: false, wickUpColor: "#3DDC97", wickDownColor: "#FF6B6B",
  });
  s.setData(candles.map((c) => ({ time: c[0], open: c[1], high: c[2], low: c[3], close: c[4] })));
  for (const l of lines) {
    s.createPriceLine({ price: l.price, color: l.color, lineWidth: l.width || 2, lineStyle: l.dashed ? LineStyle.Dashed : LineStyle.Solid,
      axisLabelVisible: true, title: l.title || "" });
  }
  if (markers.length) createSeriesMarkers(s, markers.map((m) => ({ time: m.time, position: m.position || "aboveBar",
    color: m.color || "#F2B544", shape: m.shape || "arrowDown", text: m.text || "" })));
  if (fit) chart.timeScale().fitContent();
  return chart;
}

export function levelLines({ entryLow, entryHigh, sl, tps = [] }, level = null) {
  const lines = [
    { price: sl, color: "#FF6B6B", title: "SL" },
    { price: entryHigh, color: "#F2B544", title: "Entrée", dashed: true, width: 1 },
    { price: entryLow, color: "#F2B544", title: "", dashed: true, width: 1 },
    ...tps.filter((x) => x != null).map((t, i) => ({ price: t, color: "#3DDC97", title: `TP${i + 1}`, width: 1 })),
  ];
  if (level != null) lines.push({ price: level, color: "#9DB4C8", title: "Niveau", dashed: true, width: 1 });
  return lines;
}

/**
 * Graphique « setup » lisible pour débutants :
 * - échelle de prix calée sur le PLAN (entrée, stop, objectifs) + les corps des bougies récentes :
 *   une mèche extrême isolée ne peut plus écraser le graphique (elle est simplement coupée) ;
 * - seulement les dernières heures à l'écran (on peut zoomer sur la page du signal) ;
 * - zones colorées à droite, comme l'outil « position » de TradingView : vert = gain possible, rouge = perte si stop ;
 * - scénario du bot en pointillés (vert = prévu, rouge = si ça rate).
 * Retourne { setCandles, setProjection, remove }.
 */
export function setupChart(el, s, { interactive = false, bars = 48 } = {}) {
  el.innerHTML = "";
  el.style.position = "relative";
  const bands = document.createElement("div");
  bands.className = "bandes";
  el.appendChild(bands);
  const host = document.createElement("div");
  host.className = "bandes-hote";
  el.appendChild(host);

  const chart = createChart(host, {
    ...THEME, autoSize: true,
    layout: { ...THEME.layout, background: { color: "transparent" }, fontSize: 12 },
    grid: { vertLines: { visible: false }, horzLines: { color: "rgba(39,64,95,.35)" } },
    handleScroll: interactive, handleScale: interactive,
    rightPriceScale: { ...THEME.rightPriceScale, scaleMargins: { top: 0.06, bottom: 0.06 }, minimumWidth: 78 },
    timeScale: { ...THEME.timeScale, rightOffset: 1, fixLeftEdge: false, lockVisibleTimeRangeOnResize: true },
  });

  const L = s.direction === "LONG";
  const lv = [s.sl, s.entry_low, s.entry_high, s.tp1, s.tp2, s.tp3].map(Number).filter((x) => isFinite(x) && x > 0);
  let recent = [];
  // Échelle : plan + corps (ouverture/clôture) des bougies affichées, mèches exclues.
  const range = () => {
    const vals = [...lv, ...recent];
    if (!vals.length) return null;
    let lo = Math.min(...vals), hi = Math.max(...vals);
    const pad = (hi - lo) * 0.06 || hi * 0.002;
    return { priceRange: { minValue: lo - pad, maxValue: hi + pad } };
  };
  const c = chart.addSeries(CandlestickSeries, {
    upColor: "#3DDC97", downColor: "#FF6B6B", borderVisible: false, wickUpColor: "rgba(61,220,151,.7)", wickDownColor: "rgba(255,107,107,.7)",
    priceLineColor: "#E9EFF4", priceLineWidth: 1, priceLineStyle: LineStyle.Dotted, title: "",
    autoscaleInfoProvider: range,
  });
  const line = (color, width) => chart.addSeries(LineSeries, {
    color, lineWidth: width, lineStyle: LineStyle.Dashed, lastValueVisible: false, priceLineVisible: false,
    crosshairMarkerVisible: false, pointMarkersVisible: false, autoscaleInfoProvider: () => null,
  });
  const ok = line("rgba(61,220,151,1)", 3);
  const rate = line("rgba(255,107,107,.85)", 2);
  const pl = (price, color, title, { dashed = false, width = 1, label = true } = {}) => price != null && isFinite(+price) &&
    c.createPriceLine({ price: +price, color, lineWidth: width, lineStyle: dashed ? LineStyle.Dashed : LineStyle.Solid,
      axisLabelVisible: label, title, lineVisible: true });
  pl(L ? s.entry_high : s.entry_low, "#F2B544", "Entrée", { dashed: true, width: 2 });
  pl(L ? s.entry_low : s.entry_high, "#F2B544", "", { dashed: true, width: 1, label: false });
  pl(s.sl, "#FF6B6B", "Stop", { width: 2 });
  pl(s.tp1, "#3DDC97", "Obj. 1", { width: 2 });
  pl(s.tp2, "#3DDC97", "Obj. 2");
  pl(s.tp3, "#3DDC97", "Obj. 3");

  let lastTime = null, n = 0, projLen = 0, ranged = false;
  const nb = () => ((el.clientWidth || 600) < 520 ? Math.min(bars, 32) : bars); // téléphone : moins de bougies, plus lisibles
  const entry = (+s.entry_low + +s.entry_high) / 2;

  // Zones colorées dessinées sous les bougies (div en arrière-plan, graphique transparent par-dessus).
  function paint() {
    if (!el.isConnected) return;
    const ts = chart.timeScale();
    const w = ts.width(), h = (host.clientHeight || el.clientHeight) - ts.height();
    const y = (p) => c.priceToCoordinate(+p);
    const x0 = lastTime != null ? ts.timeToCoordinate(lastTime) : null;
    const box = (yA, yB, xA, cls, txt = "") => {
      if (yA == null || yB == null) return "";
      let top = Math.max(0, Math.min(yA, yB)), bot = Math.min(h, Math.max(yA, yB));
      if (bot - top < 3) { const m = (top + bot) / 2; top = m - 1.5; bot = m + 1.5; }
      if (bot <= 0 || top >= h) return "";
      const left = Math.max(0, xA ?? 0);
      return `<div class="${cls}" style="top:${top}px;height:${bot - top}px;left:${left}px;width:${Math.max(0, w - left)}px">${txt}</div>`;
    };
    const xs = x0 == null ? w * 0.7 : x0;
    bands.innerHTML =
      box(y(s.entry_low), y(s.entry_high), 0, "b-zone") +
      box(y(entry), y(s.tp3), xs, "b-gain", '<span>gain possible</span>') +
      box(y(entry), y(s.sl), xs, "b-perte", '<span>perte si stop</span>');
  }
  let raf = 0;
  const later = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(() => requestAnimationFrame(paint)); };
  chart.timeScale().subscribeVisibleLogicalRangeChange(later);
  chart.timeScale().subscribeSizeChange(later);
  const ro = new ResizeObserver(later);
  ro.observe(el);

  function frame() {
    // À l'écran : les « bars » dernières bougies + toute la projection. Sur la page signal, on fixe la vue une seule fois
    // (l'utilisateur peut ensuite zoomer / se déplacer sans être ramené).
    if (ranged && interactive) return;
    if (interactive && !projLen) return; // on attend le scénario pour cadrer la vue une fois pour toutes
    const total = n + Math.max(0, projLen - 1);
    chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - nb()) - 0.5, to: total + 0.5 });
    ranged = true;
  }

  return {
    setCandles(candles) {
      const data = candles.slice(-300).map((k) => ({ time: +k[0], open: +k[1], high: +k[2], low: +k[3], close: +k[4] }));
      c.setData(data);
      n = data.length;
      lastTime = data.at(-1)?.time ?? null;
      recent = data.slice(-nb()).flatMap((d) => [d.open, d.close]);
      frame();
      later();
    },
    setProjection(p) {
      ok.setData(p.ok || []);
      rate.setData(p.rate || []);
      projLen = (p.ok || []).length;
      frame();
      later();
    },
    remove() { ro.disconnect(); cancelAnimationFrame(raf); chart.remove(); },
    get bars() { return n; },
  };
}
