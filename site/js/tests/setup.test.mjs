// Logique des cartes « setup » : feu (où en est le prix), SL/TP touchés, scénario dessiné, levier conseillé, % de la mise.
import test from "node:test";
import assert from "node:assert/strict";
import { espace, etat, levierConseille, minutesToClose, ordre, phase, projection, scenario, touches } from "../setup.js";
import { setMode } from "../fees.js";

const NOW = Date.UTC(2026, 9, 1, 12, 7);
const futur = new Date(NOW + 3600e3).toISOString();
const short = { direction: "SHORT", status: "WATCH", entry_low: 100, entry_high: 101, sl: 103, tp1: 98, tp2: 96, tp3: 94,
  quote: "USD", expires_at: futur, trigger_text: "retour dans la zone 100-101", rr: [1, 2, 3] };
const long = { ...short, direction: "LONG", status: "TRADE", entry_low: 100, entry_high: 101, sl: 98, tp1: 103, tp2: 105, tp3: 107 };
const k = (c) => [0, c, c, c, c];

test("SHORT à surveiller : attendre que le prix remonte", () => {
  const p = phase(short, 99, { now: NOW });
  assert.equal(p.code, "attendre");
  assert.match(p.texte, /remonter/);
});
test("dans la zone : confirmé seulement si la dernière bougie FERMÉE a clôturé dans la zone", () => {
  assert.equal(phase(short, 100.5, { now: NOW, candles: [k(99), k(100.5)] }).code, "zone");
  assert.equal(phase(short, 100.5, { now: NOW, candles: [k(100.4), k(100.5)] }).code, "condition");
});
test("stop touché avant l'entrée = annulé ; objectif 1 déjà atteint = trop tard", () => {
  assert.equal(phase(short, 103.2, { now: NOW }).code, "stop");
  assert.equal(phase(short, 97.5, { now: NOW }).code, "parti");
  assert.equal(phase(long, 97.9, { now: NOW }).code, "stop");
  assert.equal(phase(long, 103.5, { now: NOW }).code, "tp");            // trade validé : « TP1 touché »
});
test("LONG validé dans la zone = feu vert ; au-dessus = attendre le retour ; entre zone et stop = prudence", () => {
  assert.equal(phase(long, 100.5, { now: NOW }).code, "go");
  assert.equal(phase(long, 102, { now: NOW }).code, "attendre");
  assert.equal(phase(long, 99, { now: NOW }).code, "prudence");
});
test("pas de prix = on ne dit rien ; signal expiré = n'entre pas", () => {
  assert.equal(phase(short, null, { now: NOW }).code, "nodata");
  assert.equal(phase({ ...short, expires_at: new Date(NOW - 1).toISOString() }, 100.5, { now: NOW }).code, "expire");
});
test("minutes avant clôture de la bougie 15 min", () => {
  assert.equal(minutesToClose(NOW), 8); // 12:07 → clôture 12:15
});
test("scénario : part du prix actuel, passe par la zone puis les objectifs ; une bougie de 15 min par point", () => {
  const candles = [[1000, 99, 99, 99, 99], [1900, 99, 99, 99, 99]];
  const p = projection(short, candles, 99);
  assert.equal(p.ok[0].time, 1900);
  assert.equal(p.ok[0].value, 99);
  const times = p.ok.map((x) => x.time);
  assert.ok(times.every((t, i) => i === 0 || t - times[i - 1] === 900));
  assert.equal(p.ok.at(-1).value, 94);                 // TP3
  assert.ok(p.ok.some((x) => x.value === 98));          // passe par TP1
  assert.equal(p.rate.at(-1).value, 103);               // le chemin « si ça rate » finit au stop
  assert.deepEqual(projection(short, []), { ok: [], rate: [] });
});
test("historique : SL touché / TP touché d'après les bougies depuis la détection (pas seulement le prix actuel)", () => {
  const t0 = Math.floor(NOW / 1000 / 900) * 900;
  const created = new Date(NOW).toISOString();
  const bar = (i, h, l) => [t0 + i * 900, 100, h, l, (h + l) / 2];
  const lg = { ...long, created_at: created };                      // LONG validé : entrée 100-101, SL 98, TP 103/105/107
  assert.equal(touches(lg, [bar(1, 101, 99.5), bar(2, 103.2, 100)]).hit, "tp1");
  assert.equal(touches(lg, [bar(1, 103.2, 100), bar(2, 101, 97.5)]).hit, "sl");     // TP1 puis stop
  assert.equal(touches(lg, [bar(1, 103.2, 100), bar(2, 101, 97.5)]).tpAvant, 1);
  assert.equal(touches(lg, [bar(1, 103.5, 97.5)]).hit, "sl");                        // même bougie : prudence, on compte le stop
  assert.equal(touches(lg, [bar(0, 110, 90)]).hit, null);                           // bougie de détection ignorée
  // Le prix est revenu dans la zone, mais le stop a été touché entre-temps : la carte doit le dire.
  const ph = phase(lg, 100.5, { now: NOW + 3 * 900e3, candles: [bar(1, 101, 97.5), bar(2, 101, 100)] });
  assert.equal(ph.code, "stop");
  assert.equal(ph.titre, "SL touché");
  assert.deepEqual(etat(lg, ph), ["short", "❌ SL touché"]);
  const ph2 = phase(lg, 104, { now: NOW + 2 * 900e3, candles: [bar(1, 103.3, 100.2), bar(2, 104, 103)] });
  assert.equal(ph2.titre, "TP1 touché");
  assert.equal(espace(lg, ph2), "fini");
  // Setup à surveiller : objectif atteint sans entrée confirmée = trop tard
  const sw = { ...short, created_at: created };
  assert.equal(phase(sw, 97.5, { now: NOW + 2 * 900e3, candles: [bar(1, 99.5, 97.8)] }).code, "parti");
});

test("levier conseillé : liquidation loin du stop, mise de 25 % ≈ ton risque, SHORT spot x2 minimum", () => {
  setMode("spot");
  // SL à 2 % : 1 % de risque / (25 % × ~3,2 % avec frais spot) ≈ x1
  const l = levierConseille({ ...long, entry_low: 100, entry_high: 100, sl: 98, venue: "spot" }, { risk_pct: 1 });
  assert.equal(l.lev, 1);
  // Futures, stop serré 0,5 % : ≈ x7, liquidation à ~11 % (bien après le stop)
  const f = levierConseille({ ...long, entry_low: 100, entry_high: 100, sl: 99.5, venue: "futures" }, { risk_pct: 1 });
  assert.equal(f.lev, 7);
  assert.ok(f.liqPct > 2 * f.slPct);
  assert.ok(Math.abs(f.misePct - 25) < 4);
  // Plafond de la paire
  assert.equal(levierConseille({ ...long, entry_low: 100, entry_high: 100, sl: 99.5, venue: "futures" }, { risk_pct: 1 }, 3).lev, 3);
  // SHORT spot : Kraken impose x2 minimum
  assert.ok(levierConseille({ ...short, venue: "spot", sl: 110 }, { risk_pct: 1 }).lev >= 2);
  setMode("futures");
  // En futures (par défaut), une paire spot du bot se trade sur son perpétuel : pas de x2 minimum pour le SHORT
  assert.equal(levierConseille({ ...short, venue: "spot", entry_low: 100, entry_high: 100, sl: 110 }, { risk_pct: 1 }).lev, 1);
});

test("scénario en % de la mise : le levier multiplie gains ET pertes ; liquidation avant le stop = toute la mise", () => {
  const s = { ...long, entry_low: 100, entry_high: 100, sl: 98, tp1: 103, tp2: 105, tp3: 107, venue: "futures" };
  const x1 = scenario(s, 1), x3 = scenario(s, 3);
  assert.ok(Math.abs(x1.perte - (2 + 0.02 + 0.05)) < 1e-9);
  assert.ok(Math.abs(x3.perte - 3 * x1.perte) < 1e-9);
  assert.ok(Math.abs(x3.tout - 3 * x1.tout) < 1e-9);
  assert.ok(Math.abs(x1.tp1 - 0.3 * (3 - 0.04)) < 1e-9);
  const x50 = scenario(s, 50);                                     // liquidation à 1,6 % < stop à 2 %
  assert.equal(x50.liqAvant, true);
  assert.equal(x50.perte, 100);
});

test("rangement : imminent si dans la zone ou à ≤ 0,5 % ; sinon selon la confiance ; raté/trop tard/expiré à part", () => {
  const fort = { ...short, score: 82 }, faible = { ...short, score: 70 };
  assert.equal(espace(fort, null), "solide");                         // prix pas encore lu
  assert.equal(espace(faible, null), "fragile");
  assert.equal(espace(faible, phase(faible, 100.5, { now: NOW })), "imminent");   // dans la zone
  assert.equal(espace(faible, phase(faible, 99.6, { now: NOW })), "imminent");    // 0,4 % sous la zone
  assert.equal(espace(fort, phase(fort, 99, { now: NOW })), "solide");            // 1 % : pas encore
  assert.equal(espace(fort, phase(fort, 103.5, { now: NOW })), "fini");           // stop touché
});
test("ordre : validés d'abord, puis confiance décroissante", () => {
  const l = [{ status: "WATCH", score: 90 }, { status: "TRADE", score: 70 }, { status: "WATCH", score: 95 }].sort(ordre);
  assert.deepEqual(l.map((x) => x.score), [70, 95, 90]);
});

test("frais spot plus gros que le gain : résultat négatif au TP (affiché en rouge, pas « +- »)", async () => {
  const { chiffres } = await import("../setup.js");
  const s = { ...long, entry_low: 100, entry_high: 100, sl: 99.8, tp1: 100.3, tp2: 100.5, tp3: 100.7, venue: "spot" };
  // En futures (par défaut) : frais 0,02 / 0,05 % → le même setup reste gagnant aux objectifs
  assert.ok(scenario(s, 1).tp1 > 0 && scenario(s, 1).tout > 0);
  setMode("spot");
  const r = scenario(s, 1);
  assert.ok(r.tp1 < 0 && r.tout < 0);
  const html = chiffres(s, { risk_pct: 1 });
  assert.ok(!html.includes("+-") && !html.includes("+−"));
  assert.match(html, /Les frais mangent tout le gain/);
  setMode("futures");
});

test("condition remplie puis scan qui ne valide pas : on ne redemande pas de scanner, on donne la raison", () => {
  const t0 = Math.floor(NOW / 1000 / 900) * 900;
  const bougies = [[t0 - 900, 100.5, 100.8, 100.2, 100.5], [t0, 100.5, 100.7, 100.3, 100.6]]; // avant-dernière fermée dans la zone
  const avant = { ...short, created_at: new Date((t0 - 900) * 1000).toISOString() };              // scan AVANT la clôture
  assert.equal(phase(avant, 100.6, { now: NOW, candles: bougies }).code, "condition");
  const apres = { ...short, created_at: new Date(t0 * 1000 + 60e3).toISOString(), warnings: ["volume trop faible"] };
  const ph = phase(apres, 100.6, { now: NOW, candles: bougies });
  assert.equal(ph.code, "revu");
  assert.match(ph.texte, /volume trop faible/);
});

test("paire spot tradée en perpétuel : x10 → liquidation à ≈ 5 %, pas « liquidé avant le stop » pour un stop à 2,5 %", () => {
  const s = { ...long, entry_low: 100, entry_high: 100, sl: 97.5, tp1: 103, tp2: 105, tp3: 108, venue: "spot" };
  const x1 = scenario(s, 1, 3), x10 = scenario(s, 10, 3);       // levier max de la paire SPOT = x3 (ne doit pas compter)
  assert.equal(x10.liqAvant, false);
  assert.ok(Math.abs(x10.liqPct - 5) < 1e-9);
  assert.ok(Math.abs(x10.perte - 10 * x1.perte) < 1e-9);         // même mise, position 10× plus grosse → perte 10×
  assert.ok(x10.perte > 25 && x10.perte < 26);
  assert.ok(Math.abs(levierConseille(s, { risk_pct: 1 }, 3).liqPct - (100 / levierConseille(s, { risk_pct: 1 }, 3).lev - 5)) < 1e-9);
});

test("prix collé à la zone : pas de « 0 % », on écrit l'écart en prix", () => {
  const p = phase({ ...short, entry_low: 4145.1, entry_high: 4148, sl: 4165, tp1: 4130 }, 4145, { now: NOW });
  assert.equal(p.code, "attendre");
  assert.doesNotMatch(p.texte, / 0 %/);
  assert.match(p.texte, /0,1 \$/);
  assert.equal(p.titre, "Presque dans la zone");
});

test("stop trop serré (PAXG du 03/10 : 0,06 %) → « ne pas prendre », rangé dans Terminés", async () => {
  const { phase, espace } = await import("../setup.js");
  const s = { status: "TRADE", direction: "SHORT", entry_low: 4144.8, entry_high: 4145.1, sl: 4147.3, tp1: 4140.1, tp2: 4134.2, tp3: 4117.5,
    quote: "USD", score: 80, expires_at: new Date(Date.now() + 3600e3).toISOString() };
  const ph = phase(s, 4145);
  assert.equal(ph.code, "serre");
  assert.equal(espace(s, ph), "fini");
});

test("vérification express : bouton sur « Condition remplie », setup abandonné après revérification", async () => {
  const { phase, phaseHtml, espace } = await import("../setup.js");
  const s = { status: "TRADE", direction: "LONG", entry_low: 99, entry_high: 100, sl: 97, tp1: 104, tp2: 106, tp3: 109, quote: "USD", score: 70,
    instrument_key: "futures:PF_TAOUSD", expires_at: new Date(Date.now() + 3600e3).toISOString() };
  const ab = phase({ ...s, revuSans: new Date().toISOString() }, 99.5);
  assert.equal(ab.code, "annule");
  assert.equal(espace(s, ab), "fini");
  assert.match(phaseHtml({ code: "condition", icone: "✅", titre: "Condition remplie", texte: "x", verif: "futures:PF_TAOUSD" }), /data-verif="futures:PF_TAOUSD"/);
});

test("XAUT du 04/10 : stop 14 $ au-dessus, TP1 à 1,5 $ (R:R 0,1) → « Refusé », rangé dans Terminés", async () => {
  const { phase, espace } = await import("../setup.js");
  const s = { status: "WATCH", direction: "SHORT", entry_low: 4142.1, entry_high: 4142.4, sl: 4156.7, tp1: 4140.6, tp2: 4139.4, tp3: 4138,
    rr: [0.1, 0.18, 0.28], warnings: ["mauvais ratio R:R (0.1 / 0.2 / 0.3)"], quote: "USD", score: 68, expires_at: new Date(Date.now() + 3600e3).toISOString() };
  const ph = phase(s, 4141.9);
  assert.equal(ph.code, "refuse");
  assert.equal(espace(s, ph), "fini");
});
