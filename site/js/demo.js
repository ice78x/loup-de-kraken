// MODE DÉMO — utilisé uniquement tant que config.js est vide.
// Toutes les données ici sont FICTIVES (générées) pour montrer l'interface. Aucun vrai prix.

function rng(seed) {
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
}

export function fakeCandles(seed, start, n = 96, vol = 0.004, drift = 0) {
  const r = rng(seed);
  const out = [];
  let t = Math.floor(Date.now() / 900000) * 900 - n * 900;
  let c = start;
  for (let i = 0; i < n; i++) {
    const o = c;
    c = o * (1 + drift + (r() - 0.5) * vol * 2);
    const h = Math.max(o, c) * (1 + r() * vol * 0.6);
    const l = Math.min(o, c) * (1 - r() * vol * 0.6);
    out.push([t, o, h, l, c]);
    t += 900;
  }
  return out;
}

const now = () => new Date().toISOString();
const ago = (h) => new Date(Date.now() - h * 3600e3).toISOString();

function sig(id, display, direction, status, seed, price, score, strategy, extra = {}) {
  const candles = fakeCandles(seed, price * 0.97, 96, 0.004, direction === "LONG" ? 0.0003 : -0.0003);
  const last = candles.at(-1)[4];
  const s = direction === "LONG" ? 1 : -1;
  const lo = s > 0 ? last * 0.998 : last * 1.0;
  const hi = s > 0 ? last * 1.0 : last * 1.002;
  const e = s > 0 ? hi : lo;
  const sl = e * (1 - s * 0.012);
  const tps = [1.3, 2.4, 3.6].map((m) => e + s * m * Math.abs(e - sl));
  return {
    id, created_at: ago(0.4), scan_id: 1, status, instrument_key: `spot:${display.replace("/", "")}`, display,
    venue: "spot", api_symbol: display.replace("/", ""), asset_class: extra.asset_class || "crypto", quote: "USD",
    direction, strategy, score, entry_low: lo, entry_high: hi, sl, tp1: tps[0], tp2: tps[1], tp3: tps[2],
    rr: [1.3, 2.4, 3.6], rr_net: [1.0, 2.0, 3.1], leverage_ref: 1, action: "ENTRÉE (ordre limite dans la zone)",
    invalidation: `Clôture 15m ${s > 0 ? "sous" : "au-dessus de"} ${(sl * (1 + s * 0.004)).toPrecision(6)}`,
    catalyst: "Aucun catalyseur vérifié — setup purement technique", sources: [],
    reasons: ["CASSURE CONFIRMÉE + RETEST du niveau (exemple)", "structure 4h up / 1h up", "fond J up / S range"],
    warnings: ["DÉMO : données fictives"], trigger_text: status === "WATCH" ? "retest du niveau puis clôture 15m" : "",
    edge_note: "historique : pas encore optimisé (DÉMO)", fee_taker_pct: 0.4, fee_maker_pct: 0.25,
    eur_per_quote: 0.86, candles, expires_at: new Date(Date.now() + 3.5 * 3600e3).toISOString(), ...extra,
  };
}

export function demoBackend() {
  const me = { id: "demo-me", pseudo: "Ice", guardrails: false, trade_mode: "futures", balance_eur: 90, risk_pct: 1, max_open_risk_pct: 2,
    max_daily_loss_pct: 3, approved: true, is_admin: true, created_at: ago(240) };
  const hist = [{ created_at: ago(24), old_balance: 80, new_balance: 90 }];
  const members = [me,
    { id: "demo-2", pseudo: "Nora", approved: true, is_admin: false, created_at: ago(200), balance_eur: 150 },
    { id: "demo-3", pseudo: "Sam", pseudo_pending: "Samy", approved: true, is_admin: false, created_at: ago(100), balance_eur: 60 },
    { id: "demo-4", pseudo: "Léo", approved: false, is_admin: false, created_at: ago(2), balance_eur: 90 }];
  const signals = [
    sig(11, "BTC/USD", "LONG", "TRADE", 7, 71000, 72, "cassure_retest"),
    sig(12, "LINK/USD", "SHORT", "TRADE", 21, 16.5, 64, "rejet_sweep"),
    sig(13, "ETH/USD", "LONG", "WATCH", 33, 2800, 55, "tendance_pullback"),
    sig(14, "PAXG/USD", "LONG", "WATCH", 41, 2650, 48, "cassure_retest", { asset_class: "commodity" }),
    // Scan précédent (il y a ~1 h) : SOL n'est plus dans le dernier scan, BTC y est encore (doublon ignoré à l'accueil)
    sig(9, "SOL/USD", "LONG", "WATCH", 55, 160, 58, "tendance_pullback", { scan_id: 0, created_at: ago(1.1) }),
    sig(8, "BTC/USD", "LONG", "WATCH", 7, 71000, 60, "cassure_retest", { scan_id: 0, created_at: ago(1.1) }),
  ];
  // Paires fictives (démo) : celles des signaux + quelques autres pour la page Graphiques.
  const inst = (display, asset_class, demo_price, extra = {}) => ({ key: `spot:${display.replace("/", "")}`, display, venue: "spot",
    api_symbol: display.replace("/", ""), base: display.split("/")[0], asset_class, quote: "USD", can_long: true, can_short: true,
    max_leverage: 5, lot_decimals: 8, ordermin: 0, demo_price, ...extra });
  const insts = [
    ...signals.map((s) => inst(s.display, s.asset_class, s.candles.at(-1)[4])),
    inst("SOL/USD", "crypto", 160), inst("XRP/USD", "crypto", 0.62), inst("DOGE/USD", "crypto", 0.15),
    inst("TSLAx/USD", "xstock", 245, { api_asset_class: "tokenized_asset", max_leverage: 1, can_short: false }),
    inst("NVDAx/USD", "xstock", 128, { api_asset_class: "tokenized_asset", max_leverage: 1, can_short: false }),
    ...[["XBT", "BTC", 71000], ["ETH", "ETH", 2700], ["SOL", "SOL", 160], ["LINK", "LINK", 15.3], ["XRP", "XRP", 0.62], ["PAXG", "PAXG", 2650]]
      .map(([sym, b, px]) => ({ ...inst(`PF_${sym}USD`, b === "PAXG" ? "commodity" : "crypto", px), key: `futures:PF_${sym}USD`, venue: "futures",
        api_symbol: `PF_${sym}USD`, base: b, max_leverage: 10 })),
  ];
  const scan = {
    id: 1, created_at: ago(0.4), mode: "normal", verdict: "TRADE", duration_s: 96,
    counts: { tradables: 312, "analysés": 44 }, reasons: [],
    opportunities: [
      { display: "BTC/USD", state: "LONG", score: 72, asset_class: "crypto" },
      { display: "LINK/USD", state: "SHORT", score: 64, asset_class: "crypto" },
      { display: "ETH/USD", state: "SURVEILLER LONG", score: 55, asset_class: "crypto" },
      { display: "PAXG/USD", state: "SURVEILLER LONG", score: 48, asset_class: "commodity" },
      { display: "SOL/USD", state: "WAIT", score: 31, asset_class: "crypto" },
      { display: "TSLAx/USD", state: "WAIT", score: 22, asset_class: "xstock" },
    ],
    news: [{ title: "Example: Federal Reserve issues FOMC statement", title_fr: "Exemple : la Réserve fédérale publie son communiqué du FOMC",
      explain: "Les décisions de la Fed (banque centrale américaine) font bouger le dollar et presque tous les marchés. Des taux en baisse sont souvent favorables aux cryptos et aux actions, des taux en hausse les freinent. Concerne tout le marché ; le sens n'est pas clair : regarde d'abord comment le prix réagit. (DÉMO)",
      source: "Federal Reserve",
      published_at: ago(3), verified: true, impact_label: "fort", assets: [], fact: "Federal Reserve a publié : « … » (exemple)",
      interpretation: "[règles automatiques] Catégorie : Fed. Impact potentiel : fort. (DÉMO)" }],
    data_issues: [], report_text: "DÉMO",
  };
  let tid = 100;
  const trades = [
    { id: tid++, user_id: "demo-me", profiles: { pseudo: "Ice" }, signal_id: 11, instrument_key: "spot:SOLUSD", display: "SOL/USD",
      venue: "spot", api_symbol: "SOLUSD", quote: "USD", direction: "LONG", mode: "paper", entry_price: 160, sl: 156.8,
      tp1: 164.1, tp2: 167.6, tp3: 171.5, leverage: 1, qty: 0.31, qty_remaining: 0.217, risk_eur: 0.9, eur_per_quote: 0.86,
      fee_pct: 0.4, status: "ouvert", tp1_hit: true, tp2_hit: false, tp3_hit: false, realized_pnl_eur: 0.9,
      advice: "DÉPLACER SL → SL 160.7 — TP1 pris + 2 clôtures 15m confirmées → SL à break-even (DÉMO)",
      opened_at: ago(5), events: [{ at: ago(5), text: "Ouverture" }, { at: ago(2), by: "bot", text: "TP1 atteint à 164.1" }], auto_track: true },
    { id: tid++, user_id: "demo-me", profiles: { pseudo: "Ice" }, instrument_key: "spot:ETHUSD", display: "ETH/USD", quote: "USD", venue: "spot",
      direction: "SHORT", mode: "reel", entry_price: 2850, sl: 2885, tp1: 2805, tp2: 2770, tp3: 2725, leverage: 2, qty: 0.028,
      qty_remaining: 0, risk_eur: 0.9, eur_per_quote: 1, fee_pct: 0.4, status: "clos", realized_pnl_eur: 1.46, r_multiple: 1.62,
      close_reason: "TP3", opened_at: ago(50), closed_at: ago(40), events: [] },
    { id: tid++, user_id: "demo-2", profiles: { pseudo: "Nora" }, instrument_key: "spot:BTCUSD", display: "BTC/USD", quote: "USD", venue: "spot",
      direction: "LONG", mode: "paper", entry_price: 70000, sl: 69200, tp1: 71000, tp2: 71900, tp3: 72800, leverage: 3,
      qty: 0.0021, qty_remaining: 0, risk_eur: 1.5, eur_per_quote: 1, fee_pct: 0.4, status: "clos", realized_pnl_eur: -1.5,
      r_multiple: -1, close_reason: "SL", opened_at: ago(30), closed_at: ago(28), events: [] },
  ];
  const settings = [
    { key: "score_trade", value: 60, label: "Score minimal pour un 🟢", help: "Plus haut = moins de trades mais plus sélectifs.", min_value: 45, max_value: 85 },
    { key: "min_rr_tp2", value: 1.5, label: "R:R minimal au TP2", help: "Gain potentiel minimum au TP2, en multiples du risque.", min_value: 1, max_value: 4 },
    { key: "universe_max_crypto", value: 30, label: "Nombre de cryptos analysées", help: "Les plus liquides.", min_value: 5, max_value: 40 },
    { key: "disabled_strategies", value: [], label: "Stratégies désactivées", help: "", min_value: null, max_value: null },
    { key: "news_enabled", value: true, label: "Utiliser les news", help: "", min_value: null, max_value: null },
    { key: "quote_currencies", value: ["USD"], label: "Paires analysées", help: "Devise de cotation des paires que le bot peut proposer (USD par défaut).", min_value: null, max_value: null },
  ];
  const ideas = [{ id: 1, title: "Ajouter une alerte Telegram quand un 🟢 sort", body: "Pour ne pas rater les trades imminents.", status: "proposée",
    category: "site", seen: false, admin_reply: null, created_at: ago(20), user_id: "demo-2", profiles: { pseudo: "Nora" } }];
  const lb = () => members.filter((m) => m.approved).map((m) => {
    const c = trades.filter((t) => t.user_id === m.id && t.status === "clos");
    return { id: m.id, pseudo: m.pseudo, trades: c.length, wins: c.filter((t) => t.realized_pnl_eur > 0).length,
      pnl_eur: c.reduce((a, t) => a + t.realized_pnl_eur, 0), total_r: c.reduce((a, t) => a + (t.r_multiple || 0), 0),
      avg_r: c.length ? c.reduce((a, t) => a + (t.r_multiple || 0), 0) / c.length : null,
      open_trades: trades.filter((t) => t.user_id === m.id && t.status === "ouvert").length };
  }).sort((a, b) => b.pnl_eur - a.pnl_eur);
  let session = { user: { id: "demo-me" }, access_token: "demo" };
  const listeners = [];
  const ok = (x) => Promise.resolve(structuredClone(x));
  return {
    demo: true,
    session: () => ok(session),
    onAuth: (cb) => listeners.push(cb),
    signIn: () => { session = { user: { id: "demo-me" } }; listeners.forEach((l) => l(session)); return ok({}); },
    signUp: () => ok({}),
    signOut: () => { session = null; listeners.forEach((l) => l(null)); return ok({}); },
    token: () => ok("demo"),
    me: () => ok(me),
    updateMe: (_id, patch) => {
      if (patch.balance_eur != null && +patch.balance_eur !== +me.balance_eur) hist.unshift({ created_at: now(), old_balance: me.balance_eur, new_balance: patch.balance_eur });
      Object.assign(me, patch); return ok(me);
    },
    members: () => ok(members),
    setMember: (id, patch) => { Object.assign(members.find((m) => m.id === id), patch); return ok({}); },
    removeMember: (id) => { members.splice(members.findIndex((m) => m.id === id), 1); return ok({}); },
    balanceHistory: () => ok(hist),
    latestScan: () => ok(scan),
    recentScans: (n = 2) => ok([scan, { ...scan, id: 0, created_at: ago(1.1), verdict: "WATCH", news: [], opportunities: [] }].slice(0, n)),
    signalsOf: (scanId) => ok(signals.filter((s) => s.scan_id === +scanId)),
    signal: (id) => ok(signals.find((s) => s.id === +id) || null),
    recentSignals: () => ok(signals.filter((s) => s.status === "TRADE")),
    instruments: () => ok(insts),
    perps: () => ok(insts.filter((i) => i.venue === "futures")),
    instrumentsByKeys: (keys) => ok(insts.filter((i) => keys.includes(i.key))),
    instrument: (key) => ok(insts.find((i) => i.key === key) || null),
    signalsFor: (key) => ok(signals.filter((s) => s.instrument_key === key)),
    // DÉMO : statistiques fictives pour montrer la section « Ce que le bot apprend »
    signalStats: () => ok([{ status: "TRADE", strategy: "cassure_retest", asset_class: "crypto", n: 18, non_entres: 6, win_rate: 55.6, avg_r: 0.31, sum_r: 5.6 },
      { status: "TRADE", strategy: "rejet_sweep", asset_class: "crypto", n: 16, non_entres: 3, win_rate: 31.3, avg_r: -0.28, sum_r: -4.5 },
      { status: "WATCH", strategy: "tendance_pullback", asset_class: "crypto", n: 9, non_entres: 12, win_rate: 44.4, avg_r: 0.05, sum_r: 0.4 }]),
    recentOutcomes: () => ok([{ created_at: ago(5), display: "PF_ETHUSD", direction: "SHORT", status: "TRADE", outcome: "sl", r: -1.04 },
      { created_at: ago(7), display: "PF_SOLUSD", direction: "LONG", status: "TRADE", outcome: "be", r: 0.27 },
      { created_at: ago(9), display: "PF_XBTUSD", direction: "LONG", status: "WATCH", outcome: "non_entre", r: null }]),
    edges: () => ok([{ asset_class: "crypto", strategy: "cassure_retest", status: "non démontré", oos_trades: 0, period: "DÉMO" }]),
    settings: () => ok(settings),
    setSetting: (key, value) => { settings.find((s) => s.key === key).value = value; return ok({}); },
    settingsLog: () => ok([{ key: "score_trade", old_value: 55, new_value: 60, created_at: ago(12), profiles: { pseudo: "Nora" } }]),
    requestScan: () => ok("DÉMO : en vrai, le scan est lancé sur GitHub et le résultat arrive en 2 à 4 minutes."),
    trades: ({ userId, status, instrumentKey } = {}) => ok(trades.filter((t) => (!userId || t.user_id === userId) && (!status || t.status === status)
      && (!instrumentKey || t.instrument_key === instrumentKey))),
    trade: (id) => ok(trades.find((t) => t.id === +id)),
    createTrade: (row) => { const t = { id: tid++, user_id: "demo-me", profiles: { pseudo: me.pseudo }, opened_at: now(), status: "ouvert", tp1_hit: false, tp2_hit: false, tp3_hit: false, ...row }; trades.unshift(t); return ok(t); },
    updateTrade: (id, patch) => { const t = trades.find((x) => x.id === +id); Object.assign(t, patch); return ok(t); },
    deleteTrade: (id) => { trades.splice(trades.findIndex((x) => x.id === +id), 1); return ok({}); },
    leaderboard: () => ok(lb()),
    ideas: () => ok(ideas),
    addIdea: (title, body, category) => { ideas.unshift({ id: Date.now(), title, body, category, status: "proposée", seen: false, admin_reply: null,
      created_at: now(), user_id: "demo-me", profiles: { pseudo: me.pseudo } }); return ok({}); },
    setIdea: (id, patch) => { Object.assign(ideas.find((i) => i.id === id), patch); return ok({}); },
    deleteIdea: (id) => { ideas.splice(ideas.findIndex((i) => i.id === id), 1); return ok({}); },
    unseenIdeas: () => ok(ideas.filter((i) => !i.seen).length),
  };
}
