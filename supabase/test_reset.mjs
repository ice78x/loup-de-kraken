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

// Anciens trades clos / annulés de 2 membres + des trades ouverts → seuls les ouverts restent
const V = "22222222-2222-2222-2222-222222222222";
await db.query(`insert into auth.users (id, email, raw_user_meta_data) values ($1, 'b@x.fr', '{"pseudo":"Nora"}')`, [V]);
await add("PF_TAOUSD", "ouvert", 10); await add("PF_XBTUSD", "clos", 100); await add("PF_PUMPUSD", "annule", 50);
await db.query(`update public.trades set user_id = $1 where display = 'PF_XBTUSD'`, [V]);
await add("PF_ETHUSD", "clos", 300); await add("PF_UNIUSD", "ouvert", 5);
await db.exec(reset);
const reste = (await db.query("select display, status from public.trades order by display")).rows;
assert.deepEqual(reste, [{ display: "PF_TAOUSD", status: "ouvert" }, { display: "PF_UNIUSD", status: "ouvert" }]);
assert.equal((await db.query("select count(*)::int n from public.profiles")).rows[0].n, 2);   // membres intacts
console.log("RESET OK : trades terminés supprimés (tous les membres), trades ouverts gardés");
