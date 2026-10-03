// Test du script de remise à zéro des trades (reset_trades.sql) dans PGlite.
import { PGlite } from "@electric-sql/pglite";
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";

const db = new PGlite();
await db.exec(`
  create schema auth;
  create table auth.users (id uuid primary key, email text, raw_user_meta_data jsonb default '{}');
  create function auth.uid() returns uuid language sql stable as $$ select null::uuid $$;
  create role anon nologin; create role authenticated nologin; create role service_role nologin bypassrls;
`);
await db.exec(readFileSync(new URL("./schema.sql", import.meta.url), "utf8"));
const reset = readFileSync(new URL("./reset_trades.sql", import.meta.url), "utf8");
const U = "11111111-1111-1111-1111-111111111111";
await db.query(`insert into auth.users (id, email, raw_user_meta_data) values ($1, 'a@x.fr', '{"pseudo":"Ice"}')`, [U]);
const add = (display, status, minutes) => db.query(`insert into public.trades (user_id, instrument_key, display, direction, entry_price, sl, qty, qty_remaining, risk_eur, status, opened_at)
  values ($1, 'futures:' || $2, $2, 'LONG', 1, 0.5, 1, 1, 1, $3, now() - ($4 || ' minutes')::interval)`, [U, display, status, String(minutes)]);

// Pas encore de trade PUMP ouvert → le script refuse et ne supprime rien
await add("PF_TAOUSD", "ouvert", 10); await add("PF_XBTUSD", "clos", 100); await add("PF_PUMPUSD", "clos", 50);
await assert.rejects(db.exec(reset), /RIEN n'a été supprimé/);
assert.equal((await db.query("select count(*)::int n from public.trades")).rows[0].n, 3);

// Cas réel : anciens trades + un vieux PUMP ouvert + les 2 derniers ouverts TAO et PUMP
await add("PF_PUMPUSD", "ouvert", 300); await add("PF_PUMPUSD", "ouvert", 5); await add("PF_ETHUSD", "ouvert", 1);
const garde = (await db.query(`select id from public.trades where status='ouvert' and display in ('PF_TAOUSD') union all
  select id from (select id from public.trades where status='ouvert' and display='PF_PUMPUSD' order by opened_at desc limit 1) z`)).rows.map((r) => r.id).sort();
await db.exec(reset);
const reste = (await db.query("select id, display from public.trades order by id")).rows;
assert.deepEqual(reste.map((r) => r.id).sort(), garde);
assert.deepEqual(reste.map((r) => r.display).sort(), ["PF_PUMPUSD", "PF_TAOUSD"]);
console.log("RESET OK : seuls les 2 derniers trades ouverts TAO et PUMP restent");
