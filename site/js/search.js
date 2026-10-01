// Recherche d'une paire Kraken : tolérante (majuscules, « btc », « btcusd », « XBT », « tesla »…), meilleurs résultats d'abord.
const norm = (s) => String(s || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
const ALIAS = { BTC: "XBT", XBT: "BTC" }; // Kraken appelle parfois le bitcoin « XBT »

/** Retourne au plus `limit` instruments correspondant à `query`, triés du plus pertinent au moins pertinent. */
export function searchInstruments(insts, query, limit = 12) {
  const f = norm(query);
  if (!f) return [];
  const variants = [f];
  for (const [a, b] of Object.entries(ALIAS)) if (f.startsWith(a)) variants.push(b + f.slice(a.length));
  const scored = [];
  for (const i of insts || []) {
    const d = norm(i.display), b = norm(i.base), sym = norm(i.api_symbol);
    let best = Infinity;
    for (const v of variants) {
      const s = b === v ? 0 : d === v ? 0 : d.startsWith(v) ? 1 : b.startsWith(v) ? 2 : d.includes(v) || sym.includes(v) ? 3 : Infinity;
      best = Math.min(best, s);
    }
    if (best === Infinity) continue;
    const venue = i.venue === "futures" ? 1 : 0; // le spot d'abord : c'est le plus simple
    const quote = ["USD", "EUR"].includes(String(i.quote).toUpperCase()) ? 0 : 1;
    scored.push([best, quote, venue, String(i.display), i]);
  }
  scored.sort((x, y) => x[0] - y[0] || x[1] - y[1] || x[2] - y[2] || x[3].localeCompare(y[3]));
  return scored.slice(0, limit).map((x) => x[4]);
}
