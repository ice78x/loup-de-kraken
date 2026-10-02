// Frais Kraken Pro par défaut. Miroir de bot/src/kraken_assistant/risk/fees.py.
// Grille officielle vérifiée le 01/10/2026 (https://www.kraken.com/features/fee-schedule), niveau d'entrée :
//  - Futures (perpétuels) : maker 0,02 % · taker 0,05 %
//  - xStocks : taker 0,10 % (0,08 % dès le 05/10/2026), maker 0 % (en fait -0,02 % avant le 05/10 : on ne compte pas ce bonus)
//  - Paires stablecoin / devises : 0,20 %
//  - Spot crypto (depuis le 09/07/2026) : maker 0,40 % · taker 0,80 %
// Tes frais réels peuvent être plus bas si ton volume sur 30 jours est élevé.
export const XSTOCK_CHANGE = Date.UTC(2026, 9, 5);
const STABLES = new Set(["USDT", "USDC", "DAI", "PYUSD", "USDG", "EURC", "RLUSD", "USDS", "FDUSD", "TUSD", "USDE", "EUROP", "EURQ", "EURR",
  "USD", "EUR", "GBP", "CHF", "CAD", "AUD", "JPY"]);

// Comment le membre trade sur Kraken (Mon compte) : « futures » (perpétuels, par défaut) ou « spot ».
// En futures, une paire crypto du bot (ex. BTC/USD) se trade sur son perpétuel (PF_XBTUSD) : frais, levier, short et liquidation des futures.
let MODE = "futures";
export const setMode = (m) => { MODE = m === "spot" ? "spot" : "futures"; };
export const getMode = () => MODE;

const isStable = (inst) => {
  const [b0, q0] = String(inst?.display || "").split("/");
  return STABLES.has(String(inst?.base || b0 || "").toUpperCase()) && STABLES.has(String(inst?.quote || q0 || "").toUpperCase());
};

/** Marché réellement utilisé pour ce trade : le perpétuel en mode futures (sauf xStocks et stablecoins), sinon celui de la paire. */
export function venueEffective(inst) {
  if (inst?.venue === "futures") return "futures";
  if (MODE === "futures" && inst?.asset_class !== "xstock" && !isStable(inst)) return "futures";
  return "spot";
}

/** Symbole du perpétuel Kraken correspondant (indicatif) : BTC/USD → PF_XBTUSD. */
export function perpSymbol(inst) {
  if (inst?.venue === "futures") return inst.api_symbol || inst.display;
  const base = String(inst?.base || String(inst?.display || "").split("/")[0]).toUpperCase().replace(/^BTC$/, "XBT");
  return base ? `PF_${base}USD` : null;
}

/** { taker, maker, label } en % par côté. inst : { venue, asset_class, base, quote, display }. */
export function krakenFees(inst, now = Date.now()) {
  const venue = venueEffective(inst);
  if (venue === "futures") return { taker: 0.05, maker: 0.02, label: "futures perpétuels Kraken" };
  if (inst?.asset_class === "xstock") return { taker: now >= XSTOCK_CHANGE ? 0.08 : 0.1, maker: 0, label: "xStocks Kraken Pro" };
  if (isStable(inst)) return { taker: 0.2, maker: 0.2, label: "paire stablecoin / devise" };
  return { taker: 0.8, maker: 0.4, label: "spot Kraken Pro" };
}
