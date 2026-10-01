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
console.log("✓ premier compte admin, suivants en attente");

r = await as(U2, "select id from public.profiles");
assert.equal(r.rows.length, 1);
await fails(as(U2, "update public.profiles set approved = true where id = $1", [U2]), /administrateur/);
await as(U2, "update public.profiles set balance_eur = 120 where id = $1", [U2]);
r = await as(U2, "select new_balance from public.balance_history");
assert.equal(+r.rows[0].new_balance, 120);
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

await fails(as(U2, "update public.bot_settings set value = '99' where key = 'score_trade'"), /trop haute/);
await as(U2, "update public.bot_settings set value = '65' where key = 'score_trade'");
r = await as(U2, "select key, new_value, changed_by from public.bot_settings_log");
assert.equal(r.rows[0].changed_by, U2);
await fails(as(U2, "insert into public.signals (status, instrument_key, display, direction) values ('TRADE','k','d','LONG')"), /row-level security/);
console.log("✓ réglages du bot : bornes respectées + journal ; signaux réservés au bot");

await as(U2, "update public.trades set status = 'clos', realized_pnl_eur = 3, r_multiple = 1.5 where id = $1", [t2.id]);
r = await as(U1, "select pseudo, trades, wins, pnl_eur from public.leaderboard order by pseudo");
assert.equal(+r.rows.find((x) => x.pseudo === "b").pnl_eur, 3);
console.log("✓ classement calculé");

await as(U2, "insert into public.ideas (title) values ('Alerte Telegram')");
const idea = (await as(U1, "select id from public.ideas")).rows[0].id;
await as(U1, "insert into public.idea_votes (idea_id) values ($1)", [idea]);
await fails(as(U2, "update public.profiles set is_admin = true where id = $1", [U2]), /administrateur/);
r = await as(U2, "select count(*)::int n from public.idea_votes");
assert.equal(r.rows[0].n, 1);
console.log("✓ idées et votes");
console.log("\nSCHÉMA OK");
