import test from "node:test";
import assert from "node:assert/strict";
import { krakenFees, perpSymbol, setMode, XSTOCK_CHANGE } from "../fees.js";

test("mode futures (par défaut) : une paire crypto se trade sur son perpétuel, frais 0,02 / 0,05 %", () => {
  const btc = krakenFees({ venue: "spot", asset_class: "crypto", base: "BTC", quote: "USD", display: "BTC/USD" });
  assert.deepEqual([btc.taker, btc.maker], [0.05, 0.02]);
  assert.equal(perpSymbol({ display: "BTC/USD" }), "PF_XBTUSD");
  assert.equal(krakenFees({ venue: "spot", asset_class: "xstock" }, XSTOCK_CHANGE).taker, 0.08); // xStocks : leur grille
});

test("grille Kraken par type de marché (mode spot)", () => {
  setMode("spot");
  assert.deepEqual([krakenFees({ venue: "futures" }).taker, krakenFees({ venue: "futures" }).maker], [0.05, 0.02]);
  const btc = krakenFees({ venue: "spot", asset_class: "crypto", base: "BTC", quote: "USD" });
  assert.deepEqual([btc.taker, btc.maker], [0.8, 0.4]);
  assert.equal(krakenFees({ venue: "spot", display: "USDT/EUR" }).taker, 0.2);
  assert.equal(krakenFees({ venue: "spot", asset_class: "xstock" }, XSTOCK_CHANGE - 1).taker, 0.1);
  assert.equal(krakenFees({ venue: "spot", asset_class: "xstock" }, XSTOCK_CHANGE).taker, 0.08);
  setMode("futures");
});
