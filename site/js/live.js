// Mise à jour en direct des cartes « setup » : vraies bougies Kraken + prix toutes les 30 s.
// Économe : 1 seul appel « prix » pour toutes les cartes, bougies rechargées seulement à chaque nouvelle bougie 15 min,
// rien quand l'onglet est caché ou la carte hors de l'écran.
import { setupChart } from "./charts.js";
import { DEMO } from "./data.js";
import { ohlc, prices } from "./market.js";
import { phase, phaseHtml, projection } from "./setup.js";

const TICK_MS = 30_000;

/**
 * items : [{ s, chartEl, phaseEl, noteEl? }] — un par signal affiché.
 * opts.interactive / opts.bars passés au graphique. Retourne une fonction d'arrêt.
 */
export function goLive(items, { interactive = false, bars = 48, onPhase = null } = {}) {
  const st = items.map((it) => ({ ...it, chart: null, candles: null, price: null, visible: !("IntersectionObserver" in window), loading: null }));
  let stopped = false;

  async function load(x) {
    if (x.loading) return x.loading;
    x.lastLoad = Date.now();
    x.loading = (async () => {
      let candles = null, live = true;
      try { candles = await ohlc(x.s, 15); } catch { /* repli ci-dessous */ }
      if (!candles?.length) { candles = x.s.candles || []; live = false; }
      if (stopped || !x.chartEl.isConnected) return;
      x.candles = candles.map((k) => [...k]);
      x.live = live;
      if (!x.chart) x.chart = setupChart(x.chartEl, x.s, { interactive, bars });
      x.chart.setCandles(x.candles);
      if (x.noteEl) x.noteEl.textContent = DEMO ? "Mode démo : bougies fictives." : live ? "Bougies 15 min Kraken en direct (mise à jour toutes les 30 s)."
        : "Prix en direct indisponible : graphique au moment du scan.";
      draw(x);
    })().finally(() => { x.loading = null; });
    return x.loading;
  }

  function draw(x) {
    // Prix actuel = dernier prix Kraken, sinon clôture de la bougie en cours (si les bougies sont en direct).
    // Bougies du scan seulement (pas en direct) → on n'affirme rien sur le prix « actuel ».
    const now = x.price ?? (x.live && x.candles?.length ? +x.candles.at(-1)[4] : null);
    const ph = phase(x.s, now, { candles: x.live ? x.candles : [] });
    x.phaseEl.className = `feu ${ph.ton}`;
    x.phaseEl.innerHTML = phaseHtml(ph);
    x.ph = ph;
    onPhase?.(x.s, ph);
    if (x.chart && x.candles?.length) x.chart.setProjection(projection(x.s, x.candles, x.price));
  }

  function applyPrice(x, p) {
    if (p == null) return;
    x.price = p;
    if (!x.candles?.length) return; // graphique pas encore chargé (carte hors écran) : le feu se met quand même à jour
    const last = x.candles.at(-1);
    const nowBar = Math.floor(Date.now() / 1000 / 900) * 900;
    if (+last[0] < nowBar) { // nouvelle bougie 15 min : on recharge les vraies bougies (au plus 1 fois / 2 min)
      if (x.visible && Date.now() - (x.lastLoad || 0) > (x.live ? 60_000 : 300_000)) load(x);
      return;
    }
    last[4] = p; last[2] = Math.max(+last[2], p); last[3] = Math.min(+last[3], p);
    x.chart?.setCandles(x.candles);
  }

  async function tick() {
    if (stopped || document.hidden) return;
    // Un seul appel de prix pour toutes les cartes (même hors écran) : sert à les ranger (imminent, etc.).
    try {
      const fx = await prices(st.map((x) => x.s), { fx: false });
      for (const x of st) {
        applyPrice(x, fx.get(x.s)?.last ?? null);
        draw(x);
      }
    } catch { /* on réessaie au prochain tour */ }
  }

  let io = null;
  if ("IntersectionObserver" in window) {
    io = new IntersectionObserver((entries) => {
      for (const e of entries) {
        const x = st.find((y) => y.chartEl === e.target);
        if (!x) continue;
        x.visible = e.isIntersecting;
        if (x.visible && !x.candles) load(x);
      }
    }, { rootMargin: "200px" });
    st.forEach((x) => io.observe(x.chartEl));
  } else {
    st.forEach(load);
  }
  tick();
  const timer = setInterval(tick, TICK_MS);
  const onVis = () => { if (!document.hidden) tick(); };
  document.addEventListener("visibilitychange", onVis);

  return () => {
    stopped = true;
    clearInterval(timer);
    io?.disconnect();
    document.removeEventListener("visibilitychange", onVis);
    st.forEach((x) => x.chart?.remove());
  };
}
