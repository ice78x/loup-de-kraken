// Test du schéma dans un vrai PostgreSQL embarqué (PGlite), avec une émulation minimale de Supabase Auth.
// Lancer : npm i @electric-sql/pglite && node supabase/test_schema.mjs
import { PGlite } from "@electric-sql/pglite";
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";

const db = new PGlite();
const U1 = "11111111-1111-1111-1111-111111111111";
const U2 = "22222222-2222-2222-2222-222222222222";

await db.exec(`
  create schema auth;
  create table auth.users (id uuid primary key, email text, raw_user_meta_data jsonb default '{}');
  create function auth.uid() returns uuid language sql stable as
    $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
  create role anon nologin; create role authenticated nologin; create role service_role nologin bypassrls;
`);
const schema = readFileSync(new URL("./schema.sql", import.meta.url), "utf8");
await db.exec(schema);
await db.exec(schema); // idempotent
await db.exec(`
  grant usage on schema public to anon, authenticated, service_role;
  grant all on all tables in schema public to anon, authenticated, service_role;
  grant all on all sequences in schema public to anon, authenticated, service_role;
`);

async function as(uid, sql, params) {
  await db.exec(`reset role; select set_config('request.jwt.claim.sub', '${uid ?? ""}', false);`);
  if (uid) await db.exec("set role authenticated");
  try { return await db.query(sql, params); } finally { await db.exec("reset role"); }
}
const fails = async (p, re) => { await assert.rejects(p, re); };

await db.query(`insert into auth.users (id, email, raw_user_meta_data) values ($1, 'a@x.fr', '{"pseudo":"Ice"}')`, [U1]);
await db.query(`insert into auth.users (id, email) values ($1, 'b@x.fr')`, [U2]);
let r = await db.query("select pseudo, approved, is_admin from public.profiles order by created_at, pseudo");
assert.deepEqual(r.rows.find((x) => x.pseudo === "Ice"), { pseudo: "Ice", approved: true, is_admin: true });
assert.deepEqual(r.rows.find((x) => x.pseudo === "b"), { pseudo: "b", approved: false, is_admin: false });
assert.equal((await db.query("select bool_or(guardrails) as g from public.profiles")).rows[0].g, false); // garde-fous coupés par défaut
assert.equal((await db.query("select min(trade_mode) as m from public.profiles")).rows[0].m, "futures"); // futures perpétuels par défaut
console.log("✓ premier compte admin, suivants en attente");

r = await as(U2, "select id from public.profiles");
assert.equal(r.rows.length, 1);
await fails(as(U2, "update public.profiles set approved = true where id = $1", [U2]), /administrateur/);
await as(U2, "update public.profiles set balance_eur = 120 where id = $1", [U2]);
r = await as(U2, "select new_balance from public.balance_history");
assert.equal(+r.rows[0].new_balance, 120);
await as(U2, "update public.profiles set guardrails = false, risk_pct = 10, max_open_risk_pct = 50, max_daily_loss_pct = 100 where id = $1", [U2]);
r = await as(U2, "select guardrails, risk_pct from public.profiles where id = $1", [U2]);
assert.equal(r.rows[0].guardrails, false); assert.equal(+r.rows[0].risk_pct, 10);
await fails(as(U2, "update public.profiles set risk_pct = 150 where id = $1", [U2]), /check/);
await as(U2, "update public.profiles set guardrails = true, risk_pct = 1, max_open_risk_pct = 2, max_daily_loss_pct = 3 where id = $1", [U2]);
console.log("✓ membre en attente : ne voit que lui, ne peut pas s'auto-approuver, solde modifiable + historisé");

const tradeSql = `insert into public.trades (instrument_key, display, direction, entry_price, sl, qty, qty_remaining, risk_eur)
  values ('spot:X', 'X/EUR', 'LONG', 100, 98, 1, 1, 2) returning id, user_id`;
await fails(as(U2, tradeSql), /row-level security/);
r = await as(U2, "select * from public.signals");
assert.equal(r.rows.length, 0);
console.log("✓ membre non approuvé : pas de trade, pas de signaux");

await as(U1, "update public.profiles set approved = true where id = $1", [U2]);
const t2 = (await as(U2, tradeSql)).rows[0];
assert.equal(t2.user_id, U2);
r = await as(U1, "update public.trades set sl = 50 where id = $1 returning id", [t2.id]);
assert.equal(r.rows.length, 0);
r = await as(U1, "select id from public.trades");
assert.equal(r.rows.length, 1);
console.log("✓ admin approuve ; chacun voit les trades du club mais ne modifie que les siens");

// Un membre ne peut PAS changer les réglages (la mise à jour ne touche aucune ligne)
await as(U2, "update public.bot_settings set value = '65' where key = 'score_trade'");
r = await as(U1, "select value from public.bot_settings where key = 'score_trade'");
assert.notEqual(String(r.rows[0].value), "65");
await fails(as(U1, "update public.bot_settings set value = '99' where key = 'score_trade'"), /trop haute/);
await as(U1, "update public.bot_settings set value = '65' where key = 'score_trade'");
r = await as(U1, "select key, new_value, changed_by from public.bot_settings_log");
assert.equal(r.rows[0].changed_by, U1);
assert.equal((await as(U2, "select count(*)::int n from public.bot_settings_log")).rows[0].n, 0);
await fails(as(U2, "insert into public.signals (status, instrument_key, display, direction) values ('TRADE','k','d','LONG')"), /row-level security/);
console.log("✓ réglages du bot : admin seulement, bornes respectées + journal ; signaux réservés au bot");

await as(U2, "update public.trades set status = 'clos', realized_pnl_eur = 3, r_multiple = 1.5 where id = $1", [t2.id]);
r = await as(U1, "select pseudo, trades, wins, pnl_eur from public.leaderboard order by pseudo");
assert.equal(+r.rows.find((x) => x.pseudo === "b").pnl_eur, 3);
console.log("✓ classement calculé");
await as(U2, "insert into public.trades (instrument_key, display, direction, entry_price, sl, liq_price, leverage, qty, qty_remaining, risk_eur) values ('spot:X', 'X/USD', 'LONG', 100, null, 84, 5, 1, 1, 20)");
console.log("✓ marge isolée : trade sans stop accepté (liquidation enregistrée)");

await as(U2, "insert into public.ideas (title, body, category) values ('Alerte Telegram', 'quand un 🟢 sort', 'site')");
await as(U1, "insert into public.ideas (title) values ('Idée de l''admin')");
r = await as(U2, "select title from public.ideas");
assert.deepEqual(r.rows.map((x) => x.title), ["Alerte Telegram"]);           // un membre ne voit que ses idées
const idea = (await as(U1, "select id from public.ideas where title = 'Alerte Telegram'")).rows[0].id;  // l'admin les voit toutes
await as(U2, "update public.ideas set status = 'faite' where id = $1", [idea]);  // le membre ne peut pas changer le statut
assert.equal((await as(U1, "select status from public.ideas where id = $1", [idea])).rows[0].status, "proposée");
await as(U1, "update public.ideas set status = 'en cours', seen = true, admin_reply = 'Bonne idée' where id = $1", [idea]);
assert.equal((await as(U2, "select admin_reply from public.ideas")).rows[0].admin_reply, "Bonne idée");
await fails(as(U2, "insert into public.ideas (title, admin_reply) values ('Triche', 'auto')"), /row-level security/);
await fails(as(U2, "update public.profiles set is_admin = true where id = $1", [U2]), /administrateur/);
// Pseudo : le membre demande, l'admin valide
await fails(as(U2, "update public.profiles set pseudo = 'Hacker' where id = $1", [U2]), /validé par un administrateur/);
await as(U2, "update public.profiles set pseudo_pending = 'Bob' where id = $1", [U2]);
assert.equal((await as(U2, "select pseudo, pseudo_pending from public.profiles where id = $1", [U2])).rows[0].pseudo, "b");
await as(U1, "update public.profiles set pseudo = pseudo_pending, pseudo_pending = null where id = $1", [U2]);
assert.equal((await as(U2, "select pseudo from public.profiles where id = $1", [U2])).rows[0].pseudo, "Bob");
await as(U1, "update public.profiles set pseudo = 'Ice2' where id = $1", [U1]); // l'admin change le sien directement
await fails(as(U2, "update public.profiles set pseudo_pending = 'x' where id = $1", [U2]), /check/);
console.log("✓ pseudo : demande du membre, validation par l'admin");
console.log("✓ boîte à idées privée : le membre voit les siennes, l'admin les reçoit toutes et répond");
console.log("\nSCHÉMA OK");
