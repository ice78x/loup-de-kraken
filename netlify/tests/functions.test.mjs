// Tests des fonctions Netlify avec un fetch simulé : node --test netlify/tests/*.test.mjs
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import market from "../functions/market.mjs";
import scan from "../functions/scan.mjs";

let calls;
const reply = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
beforeEach(() => { calls = []; });

test("prix spot + futures + taux EUR/USD", async () => {
  globalThis.fetch = async (url) => {
    const u = String(url);
    calls.push(u);
    if (u.includes("/Ticker") && u.includes("EURUSD")) return reply({ error: [], result: { ZEURZUSD: { a: ["1.10"], b: ["1.10"], c: ["1.10"] } } });
    if (u.includes("/Ticker")) return reply({ error: [], result: { XXBTZEUR: { a: ["101"], b: ["99"], c: ["100"], o: "98", h: ["1", "105"], l: ["1", "95"] } } });
    if (u.includes("/tickers")) return reply({ tickers: [{ symbol: "PF_SOLUSD", last: 150, bid: 149.9, ask: 150.1, markPrice: 150 }] });
    return reply({}, 404);
  };
  const r = await market(new Request("https://x/api/market?type=prices&spot=XXBTZEUR&fut=PF_SOLUSD&fx=1"));
  const b = await r.json();
  assert.equal(b.spot.XXBTZEUR.last, 100);
  assert.equal(b.futures.PF_SOLUSD.last, 150);
  assert.ok(Math.abs(b.eur_per_usd - 1 / 1.1) < 1e-9);
});

test("paramètres dangereux ignorés, erreur Kraken remontée sans inventer", async () => {
  globalThis.fetch = async (url) => { calls.push(String(url)); return reply({ error: ["EGeneral:Unavailable"] }); };
  const r = await market(new Request("https://x/api/market?type=ohlc&symbol=../../etc&interval=15"));
  assert.equal(r.status, 400);
  const r2 = await market(new Request("https://x/api/market?type=ohlc&symbol=XXBTZEUR&interval=15"));
  assert.equal(r2.status, 502);
  assert.match((await r2.json()).error, /Kraken indisponible/);
});

test("bouton SCAN : refuse sans connexion, limite à 1 toutes les 10 min, déclenche GitHub", async () => {
  Object.assign(process.env, { SUPABASE_URL: "https://sb", SUPABASE_ANON_KEY: "anon", GH_TOKEN: "gh", GH_REPO: "moi/loup" });
  assert.equal((await scan(new Request("https://x/api/scan", { method: "POST" }))).status, 401);
  let last = [];
  globalThis.fetch = async (url, opt = {}) => {
    const u = String(url);
    calls.push([u, opt.method || "GET"]);
    if (u.endsWith("/auth/v1/user")) return reply({ id: "u1" });
    if (u.includes("/profiles")) return reply([{ approved: true }]);
    if (u.includes("/scan_requests") && (opt.method || "GET") === "GET") return reply(last);
    if (u.includes("api.github.com")) return new Response(null, { status: 204 });
    return new Response(null, { status: 201 });
  };
  const req = () => new Request("https://x/api/scan", { method: "POST", headers: { authorization: "Bearer tok" }, body: "{}" });
  const ok = await scan(req());
  assert.equal(ok.status, 200);
  assert.ok(calls.some(([u]) => u.includes("api.github.com/repos/moi/loup/actions/workflows/scan.yml/dispatches")));
  last = [{ created_at: new Date(Date.now() - 3 * 60000).toISOString() }];
  const tooSoon = await scan(req());
  assert.equal(tooSoon.status, 429);
});
