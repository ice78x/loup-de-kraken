// Prix en direct depuis l'API publique Kraken (le navigateur ne peut pas l'appeler directement).
// GET /api/market?type=prices&spot=XXBTZEUR,LINKEUR&tok=TSLAxUSD&fut=PF_SOLUSD&fx=1
// GET /api/market?type=ohlc&venue=spot|futures&symbol=XXBTZEUR&interval=15[&asset_class=tokenized_asset]
// Aucune donnée n'est inventée : si Kraken ne répond pas, la fonction renvoie une erreur explicite.

const SPOT = "https://api.kraken.com/0/public";
const FUT = "https://futures.kraken.com";
const SYM = /^[A-Za-z0-9._]{2,24}$/;
const RES = { 5: "5m", 15: "15m", 60: "1h", 240: "4h", 1440: "1d" };

const json = (data, status = 200, maxAge = 10) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json", "cache-control": `public, max-age=${maxAge}` },
  });

async function kraken(path, params) {
  const url = new URL(SPOT + path);
  Object.entries(params).forEach(([k, v]) => v && url.searchParams.set(k, v));
  const r = await fetch(url, { headers: { "user-agent": "loup-de-kraken" } });
  const body = await r.json();
  if (!r.ok || (body.error && body.error.length)) throw new Error((body.error || [r.status]).join(", "));
  return body.result;
}

function list(v) {
  return (v || "").split(",").map((s) => s.trim()).filter((s) => SYM.test(s)).slice(0, 30);
}

function spotPrice(t) {
  return { last: +t.c[0], bid: +t.b[0], ask: +t.a[0], open: +t.o, high24: +t.h[1], low24: +t.l[1] };
}

async function prices(q) {
  const out = { spot: {}, futures: {}, eur_per_usd: null, at: new Date().toISOString(), errors: [] };
  const spot = list(q.get("spot"));
  const tok = list(q.get("tok"));
  const fut = list(q.get("fut"));
  const jobs = [];
  if (spot.length) jobs.push(kraken("/Ticker", { pair: spot.join(",") })
    .then((r) => Object.entries(r).forEach(([k, t]) => (out.spot[k] = spotPrice(t)))));
  if (tok.length) jobs.push(kraken("/Ticker", { pair: tok.join(","), asset_class: "tokenized_asset" })
    .then((r) => Object.entries(r).forEach(([k, t]) => (out.spot[k] = spotPrice(t)))));
  if (fut.length) jobs.push(fetch(`${FUT}/derivatives/api/v3/tickers`).then((r) => r.json()).then((b) => {
    for (const t of b.tickers || []) {
      const s = String(t.symbol || "").toUpperCase();
      if (fut.includes(s) && !t.suspended) out.futures[s] = { last: +t.last, bid: +t.bid, ask: +t.ask, mark: +t.markPrice };
    }
  }));
  if (q.get("fx")) jobs.push(kraken("/Ticker", { pair: "EURUSD" }).then((r) => {
    const t = Object.values(r)[0];
    const usdPerEur = (+t.b[0] + +t.a[0]) / 2;
    if (usdPerEur > 0) out.eur_per_usd = 1 / usdPerEur;
  }).catch(async () => {
    // Repli : ratio de deux prix réels BTC/EUR ÷ BTC/USD
    const r = await kraken("/Ticker", { pair: "XBTEUR,XBTUSD" });
    const v = Object.entries(r);
    const eur = v.find(([k]) => k.endsWith("EUR"))?.[1];
    const usd = v.find(([k]) => k.endsWith("USD"))?.[1];
    if (eur && usd) out.eur_per_usd = +eur.c[0] / +usd.c[0];
  }));
  const res = await Promise.allSettled(jobs);
  res.filter((r) => r.status === "rejected").forEach((r) => out.errors.push(String(r.reason?.message || r.reason)));
  return json(out);
}

async function ohlc(q) {
  const venue = q.get("venue") === "futures" ? "futures" : "spot";
  const symbol = q.get("symbol") || "";
  const interval = Number(q.get("interval") || 15);
  if (!SYM.test(symbol) || !RES[interval]) return json({ error: "paramètres invalides" }, 400);
  let candles;
  if (venue === "spot") {
    const r = await kraken("/OHLC", { pair: symbol, interval, asset_class: q.get("asset_class") === "tokenized_asset" ? "tokenized_asset" : "" });
    const rows = Object.entries(r).find(([k]) => k !== "last")?.[1] || [];
    candles = rows.map((c) => [+c[0], +c[1], +c[2], +c[3], +c[4], +c[6]]);
  } else {
    const to = Math.floor(Date.now() / 1000);
    const from = to - interval * 60 * 300;
    const r = await fetch(`${FUT}/api/charts/v1/trade/${symbol}/${RES[interval]}?from=${from}&to=${to}`);
    const b = await r.json();
    candles = (b.candles || []).map((c) => [Math.floor(c.time / 1000), +c.open, +c.high, +c.low, +c.close, +c.volume]);
  }
  return json({ symbol, interval, candles: candles.slice(-300) }, 200, 30);
}

export default async (req) => {
  const q = new URL(req.url).searchParams;
  try {
    if (q.get("type") === "ohlc") return await ohlc(q);
    return await prices(q);
  } catch (e) {
    return json({ error: `Kraken indisponible : ${e.message}` }, 502, 0);
  }
};

export const config = { path: "/api/market" };
