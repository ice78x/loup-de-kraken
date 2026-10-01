// Graphiques en chandeliers (TradingView Lightweight Charts, licence Apache 2.0, intégré au site).
import { createChart, CandlestickSeries, LineStyle, createSeriesMarkers } from "../vendor/lightweight-charts.mjs";

const THEME = {
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
