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
    if (u.includes("/tickers")) return reply({ tickers: [{ symbol: "PF_SOLUSD", last: 150, bid: 149.9, ask: 150.1, markPrice: 150, open24h: 140 }] });
    return reply({}, 404);
  };
  const r = await market(new Request("https://x/api/market?type=prices&spot=XXBTZEUR&fut=PF_SOLUSD&fx=1"));
  const b = await r.json();
  assert.equal(b.spot.XXBTZEUR.last, 100);
  assert.equal(b.futures.PF_SOLUSD.last, 150);
  assert.equal(b.futures.PF_SOLUSD.open, 140);
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
  // Vérification express d'un setup : limite séparée (2 min), symbole obligatoire et contrôlé
  const cible = (b) => new Request("https://x/api/scan", { method: "POST", headers: { authorization: "Bearer tok" }, body: JSON.stringify(b) });
  assert.equal((await scan(cible({ mode: "cible", symbol: "../../x" }))).status, 400);
  last = [{ created_at: new Date(Date.now() - 3 * 60000).toISOString(), mode: "normal" }];
  calls.length = 0;
  const v = await scan(cible({ mode: "cible", symbol: "futures:PF_TAOUSD" }));
  assert.equal(v.status, 200);
  const gh = calls.find(([u]) => u.includes("api.github.com"));
  assert.ok(gh);
  last = [{ created_at: new Date(Date.now() - 60000).toISOString(), mode: "cible" }];
  assert.equal((await scan(cible({ mode: "cible", symbol: "futures:PF_TAOUSD" }))).status, 429);
});

test("bouton BACKTEST : admin seulement, 1 par heure, workflow backtest.yml avec bornes", async () => {
  Object.assign(process.env, { SUPABASE_URL: "https://sb", SUPABASE_ANON_KEY: "anon", GH_TOKEN: "gh", GH_REPO: "moi/loup" });
  let admin = false, last = [], sent = null;
  globalThis.fetch = async (url, opt = {}) => {
    const u = String(url);
    calls.push([u, opt.method || "GET"]);
    if (u.endsWith("/auth/v1/user")) return reply({ id: "u1" });
    if (u.includes("/profiles")) return reply([{ approved: true, is_admin: admin }]);
    if (u.includes("/scan_requests") && (opt.method || "GET") === "GET") return reply(last);
    if (u.includes("api.github.com")) { sent = [u, JSON.parse(opt.body)]; return new Response(null, { status: 204 }); }
    return new Response(null, { status: 201 });
  };
  const bt = (b) => new Request("https://x/api/scan", { method: "POST", headers: { authorization: "Bearer tok" }, body: JSON.stringify(b) });
  assert.equal((await scan(bt({ mode: "backtest" }))).status, 403);
  admin = true;
  last = [{ created_at: new Date(Date.now() - 3 * 60000).toISOString(), mode: "normal" }];   // un scan récent ne bloque pas
  const r = await scan(bt({ mode: "backtest", days: 9999, instruments: 2 }));
  assert.equal(r.status, 200);
  assert.match(sent[0], /workflows\/backtest\.yml\/dispatches/);
  assert.deepEqual(sent[1].inputs, { days: "365", instruments: "3" });
  last = [{ created_at: new Date(Date.now() - 20 * 60000).toISOString(), mode: "backtest" }];
  assert.equal((await scan(bt({ mode: "backtest" }))).status, 429);
});

test("horloge des scans (toutes les 15 min) : déclenche GitHub, et ne plante pas sans configuration", async () => {
  const { default: tick, config } = await import("../functions/scan-tick.mjs");
  assert.equal(config.schedule, "1,16,31,46 * * * *");
  delete process.env.GH_TOKEN;
  assert.equal((await tick()).status, 503);
  Object.assign(process.env, { GH_TOKEN: "gh", GH_REPO: "moi/loup" });
  let sent;
  globalThis.fetch = async (url, init) => { sent = { url: String(url), body: JSON.parse(init.body) }; return new Response(null, { status: 204 }); };
  assert.equal((await tick()).status, 200);
  assert.match(sent.url, /moi\/loup\/actions\/workflows\/scan\.yml\/dispatches/);
  assert.deepEqual(sent.body, { ref: "main", inputs: { mode: "normal" } });
  globalThis.fetch = async () => new Response("bad", { status: 401 });
  assert.equal((await tick()).status, 502);
});
