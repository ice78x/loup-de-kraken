// Prix en direct (via la fonction Netlify /api/market qui interroge l'API publique Kraken).
import { DEMO } from "./data.js";
import { fakeCandles } from "./demo.js";

export function refOf(x) {
  // x : un trade, un signal ou un instrument
  return { venue: x.venue || "spot", symbol: x.api_symbol, tok: x.api_asset_class === "tokenized_asset" };
}

/** Récupère les prix d'une liste d'objets (trades/signaux/instruments). Retourne { get(obj) → prix|null, eurPerUsd, error }. */
export async function prices(items, { fx = true } = {}) {
  const spot = new Set(), tok = new Set(), fut = new Set();
  for (const it of items) {
    const r = refOf(it);
    if (!r.symbol) continue;
    (r.venue === "futures" ? fut : r.tok ? tok : spot).add(r.symbol);
  }
  const res = { data: null, error: null };
  if (DEMO) {
    res.error = "Mode démo : pas de prix réels";
  } else {
    try {
      const qs = new URLSearchParams({ type: "prices", spot: [...spot].join(","), tok: [...tok].join(","), fut: [...fut].join(","), ...(fx ? { fx: 1 } : {}) });
      const r = await fetch(`/api/market?${qs}`);
      const b = await r.json();
      if (!r.ok) throw new Error(b.error || `Erreur ${r.status}`);
      res.data = b;
      if (b.errors?.length) res.error = b.errors.join(" ; ");
    } catch (e) {
      res.error = e.message;
    }
  }
  return {
    error: res.error,
    eurPerUsd: res.data?.eur_per_usd ?? (DEMO ? 0.86 : null), // démo : taux fictif
    get(it) {
      const r = refOf(it);
      const p = r.venue === "futures" ? res.data?.futures?.[r.symbol] : res.data?.spot?.[r.symbol];
      if (p?.last > 0) return p;
      // Démo : dernier cours fictif des bougies du signal
      if (DEMO) {
        const c = it.candles?.length ? it.candles.at(-1)[4] : it.entry_price ? +it.entry_price * 1.006 : null;
        if (c) return { last: c, bid: c, ask: c, demo: true };
      }
      return null;
    },
  };
}

export function eurPerQuote(quote, fx) {
  if (quote === "EUR") return 1;
  if (quote === "USD") return fx?.eurPerUsd || null;
  return null;
}

export async function ohlc(it, interval = 15) {
  if (DEMO) return it.candles?.length ? it.candles : fakeCandles(String(it.id).length * 7 + 3, +it.entry_price * 0.985, 120, 0.003);
  const r = refOf(it);
  const qs = new URLSearchParams({ type: "ohlc", venue: r.venue, symbol: r.symbol, interval, ...(r.tok ? { asset_class: "tokenized_asset" } : {}) });
  const res = await fetch(`/api/market?${qs}`);
  const b = await res.json();
  if (!res.ok) throw new Error(b.error || "bougies indisponibles");
  return b.candles;
}

/** Lien vers la paire sur Kraken Pro (web/app). */
export function krakenLink(it) {
  const d = (it.display || "").toLowerCase().replace("/", "-");
  if ((it.venue || "spot") === "futures") return "https://pro.kraken.com/app/trade/futures";
  return `https://pro.kraken.com/app/trade/${d}`;
}
