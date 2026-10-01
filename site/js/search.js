// Recherche d'une paire Kraken : tolérante (majuscules, « btc », « btcusd », « XBT », « tesla »…), meilleurs résultats d'abord.
const norm = (s) => String(s || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
const ALIAS = { BTC: "XBT", XBT: "BTC" }; // Kraken appelle parfois le bitcoin « XBT »

/** Retourne au plus `limit` instruments correspondant à `query`, triés du plus pertinent au moins pertinent. */
export function searchInstruments(insts, query, limit = 12) {
  const f = norm(query);
  if (!f) return popular(insts, limit);
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

// Liste de départ (champ vide) : les actifs les plus suivis d'abord, en spot USD/EUR.
const POPULAIRES = ["BTC", "ETH", "SOL", "XRP", "LINK", "ADA", "DOGE", "AVAX", "DOT", "LTC", "PAXG", "TSLAX", "NVDAX", "AAPLX", "SPYX"];
function popular(insts, limit) {
  const rank = (i) => {
    const p = POPULAIRES.indexOf(norm(i.base));
    return p < 0 ? POPULAIRES.length : p;
  };
  return [...(insts || [])]
    .filter((i) => i.venue !== "futures" && ["USD", "EUR"].includes(String(i.quote).toUpperCase()))
    .sort((a, b) => rank(a) - rank(b) || String(a.quote).localeCompare(String(b.quote)) * -1 || String(a.display).localeCompare(String(b.display)))
    .slice(0, limit);
}
