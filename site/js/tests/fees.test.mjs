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

test("pas de perpétuel Kraken pour l'actif : on retombe sur le spot (frais spot, ordre en spot)", async () => {
  const { setPerps, hasPerp, venueEffective } = await import("../fees.js");
  setPerps([{ base: "BTC", api_symbol: "PF_XBTUSD" }, { base: "ETH", api_symbol: "PF_ETHUSD" }]);
  const prompt = { venue: "spot", asset_class: "crypto", base: "PROMPT", quote: "USD", display: "PROMPT/USD" };
  assert.equal(hasPerp(prompt), false);
  assert.equal(venueEffective(prompt), "spot");
  assert.equal(krakenFees(prompt).taker, 0.8);
  assert.equal(perpSymbol(prompt), null);
  assert.equal(perpSymbol({ display: "BTC/USD", base: "BTC" }), "PF_XBTUSD");
  assert.equal(krakenFees({ venue: "spot", asset_class: "crypto", base: "ETH", quote: "USD" }).taker, 0.05);
  setPerps(null); // remet « liste inconnue » pour les autres tests
});
