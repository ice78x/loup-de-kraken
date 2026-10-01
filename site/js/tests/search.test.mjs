import test from "node:test";
import assert from "node:assert/strict";
import { searchInstruments } from "../search.js";

const insts = [
  { display: "ETH/USD", base: "ETH", quote: "USD", venue: "spot" },
  { display: "PF_XBTUSD", base: "BTC", quote: "USD", venue: "futures", api_symbol: "PF_XBTUSD" },
  { display: "BTC/EUR", base: "BTC", quote: "EUR", venue: "spot" },
  { display: "BTC/USD", base: "BTC", quote: "USD", venue: "spot" },
  { display: "BTC/JPY", base: "BTC", quote: "JPY", venue: "spot" },
  { display: "WBTC/USD", base: "WBTC", quote: "USD", venue: "spot" },
  { display: "TSLAx/USD", base: "TSLAx", quote: "USD", venue: "spot" },
];
test("« Btc » (minuscules, comme sur un téléphone) trouve le bitcoin, spot en premier", () => {
  const r = searchInstruments(insts, "Btc").map((i) => i.display);
  assert.deepEqual(r.slice(0, 2), ["BTC/EUR", "BTC/USD"]);
  assert.ok(r.includes("PF_XBTUSD"));
  assert.ok(r.indexOf("BTC/JPY") > r.indexOf("PF_XBTUSD"));
});
test("formats tolérés : btcusd, btc/usd, xbt, tsla", () => {
  assert.equal(searchInstruments(insts, "btcusd")[0].display, "BTC/USD");
  assert.equal(searchInstruments(insts, "btc/usd")[0].display, "BTC/USD");
  assert.ok(searchInstruments(insts, "xbt").some((i) => i.display === "BTC/USD"));
  assert.equal(searchInstruments(insts, "tsla")[0].display, "TSLAx/USD");
});
test("champ vide → actifs populaires en spot (bitcoin d'abord) ; introuvable → rien", () => {
  const r = searchInstruments(insts, "  ").map((i) => i.display);
  assert.equal(r[0], "BTC/USD");
  assert.ok(!r.includes("PF_XBTUSD") && !r.includes("BTC/JPY"));
  assert.deepEqual(searchInstruments(insts, "zzz"), []);
});
