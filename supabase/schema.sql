-- =====================================================================
-- LE LOUP DE KRAKEN — schéma de la base Supabase
-- À coller en entier dans Supabase → SQL Editor → New query → Run.
-- Peut être relancé sans risque (ne supprime aucune donnée).
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. Profils des membres (créés automatiquement à l'inscription)
-- ---------------------------------------------------------------------
create table if not exists public.profiles (
  id                  uuid primary key references auth.users(id) on delete cascade,
  pseudo              text not null default 'Loup',
  balance_eur         numeric(14,2) not null default 90 check (balance_eur >= 0),
  risk_pct            numeric(4,2)  not null default 1  check (risk_pct > 0 and risk_pct <= 2),
  max_open_risk_pct   numeric(4,2)  not null default 2  check (max_open_risk_pct > 0 and max_open_risk_pct <= 5),
  max_daily_loss_pct  numeric(4,2)  not null default 3  check (max_daily_loss_pct > 0 and max_daily_loss_pct <= 10),
  approved            boolean not null default false,
  is_admin            boolean not null default false,
  created_at          timestamptz not null default now()
);

create table if not exists public.balance_history (
  id          bigint generated always as identity primary key,
  user_id     uuid not null references public.profiles(id) on delete cascade,
  old_balance numeric(14,2),
  new_balance numeric(14,2),
  created_at  timestamptz not null default now()
);

-- Le premier compte créé devient administrateur (et approuvé). Les suivants attendent l'approbation.
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
declare is_first boolean;
begin
  select not exists (select 1 from public.profiles) into is_first;
  insert into public.profiles (id, pseudo, approved, is_admin)
  values (new.id,
          coalesce(nullif(trim(new.raw_user_meta_data->>'pseudo'), ''), split_part(new.email, '@', 1)),
          is_first, is_first)
  on conflict (id) do nothing;
  return new;
end $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

create or replace function public.is_approved() returns boolean
language sql stable security definer set search_path = public as $$
  select coalesce((select approved from public.profiles where id = auth.uid()), false)
$$;

create or replace function public.is_admin() returns boolean
language sql stable security definer set search_path = public as $$
  select coalesce((select approved and is_admin from public.profiles where id = auth.uid()), false)
$$;

-- Seul un admin peut changer "approved" / "is_admin" (le bot et l'éditeur SQL n'ont pas d'auth.uid()).
create or replace function public.protect_profile_flags() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if auth.uid() is not null and not public.is_admin()
     and (new.approved is distinct from old.approved or new.is_admin is distinct from old.is_admin) then
    raise exception 'Seul un administrateur peut approuver un membre';
  end if;
  if new.balance_eur is distinct from old.balance_eur then
    insert into public.balance_history (user_id, old_balance, new_balance)
    values (new.id, old.balance_eur, new.balance_eur);
  end if;
  return new;
end $$;

drop trigger if exists profiles_protect on public.profiles;
create trigger profiles_protect before update on public.profiles
  for each row execute function public.protect_profile_flags();

-- ---------------------------------------------------------------------
-- 2. Données écrites par le bot (GitHub Actions, clé "service_role")
-- ---------------------------------------------------------------------
create table if not exists public.scans (
  id            bigint generated always as identity primary key,
  created_at    timestamptz not null default now(),
  mode          text,
  verdict       text,              -- TRADE | WATCH | NONE | DATA
  report_text   text,
  reasons       jsonb default '[]',
  counts        jsonb default '{}',
  opportunities jsonb default '[]',
  news          jsonb default '[]',
  data_issues   jsonb default '[]',
  duration_s    numeric
);

create table if not exists public.signals (
  id             bigint generated always as identity primary key,
  created_at     timestamptz not null default now(),
  scan_id        bigint references public.scans(id) on delete cascade,
  status         text not null,     -- TRADE (🟢) | WATCH (🟡)
  instrument_key text not null,
  display        text not null,
  venue          text,
  api_symbol     text,
  api_asset_class text,
  asset_class    text,
  quote          text,
  direction      text not null,
  strategy       text,
  score          numeric,
  entry_low      numeric, entry_high numeric, sl numeric,
  tp1 numeric, tp2 numeric, tp3 numeric,
  rr             jsonb,             -- R brut par TP
  rr_net         jsonb,             -- R net de frais par TP (référence 90 €)
  leverage_ref   int,
  action         text,
  invalidation   text,
  catalyst       text,
  sources        jsonb default '[]',
  reasons        jsonb default '[]',
  warnings       jsonb default '[]',
  trigger_text   text,
  edge_note      text,
  fee_taker_pct  numeric, fee_maker_pct numeric,
  eur_per_quote  numeric,
  candles        jsonb default '[]', -- dernières bougies 15m pour le graphique
  expires_at     timestamptz
);
create index if not exists signals_created_idx on public.signals (created_at desc);

create table if not exists public.instruments (
  key            text primary key,
  display        text not null,
  venue          text, api_symbol text, api_asset_class text,
  asset_class    text, base text, quote text,
  can_long       boolean, can_short boolean, max_leverage int,
  ordermin       numeric, lot_decimals int, pair_decimals int,
  updated_at     timestamptz default now()
);

create table if not exists public.bot_edges (
  asset_class    text not null,
  strategy       text not null,
  status         text, score_threshold numeric, min_rr_tp2 numeric,
  oos_trades     int, oos_expectancy numeric, oos_win_rate numeric, oos_pf numeric,
  period         text, updated_at timestamptz default now(),
  primary key (asset_class, strategy)
);

-- ---------------------------------------------------------------------
-- 3. Trades des membres
-- ---------------------------------------------------------------------
create table if not exists public.trades (
  id               bigint generated always as identity primary key,
  user_id          uuid not null default auth.uid() references public.profiles(id) on delete cascade,
  signal_id        bigint references public.signals(id) on delete set null,
  instrument_key   text not null,
  display          text not null,
  venue            text, api_symbol text, api_asset_class text, asset_class text,
  quote            text not null default 'EUR',
  direction        text not null check (direction in ('LONG','SHORT')),
  mode             text not null default 'paper' check (mode in ('paper','reel')),
  entry_price      numeric not null check (entry_price > 0),
  sl               numeric not null check (sl > 0),
  tp1 numeric, tp2 numeric, tp3 numeric,
  leverage         int not null default 1 check (leverage between 1 and 10),
  qty              numeric not null check (qty > 0),
  qty_remaining    numeric not null check (qty_remaining >= 0),
  risk_eur         numeric not null check (risk_eur >= 0),
  eur_per_quote    numeric not null default 1 check (eur_per_quote > 0),
  fee_pct          numeric not null default 0.4,
  balance_at_entry numeric,
  status           text not null default 'ouvert' check (status in ('ouvert','clos','annule')),
  tp1_hit boolean not null default false,
  tp2_hit boolean not null default false,
  tp3_hit boolean not null default false,
  realized_pnl_eur numeric not null default 0,
  r_multiple       numeric,
  exit_price       numeric,
  close_reason     text,
  auto_track       boolean not null default true,
  advice           text,              -- conseil de gestion calculé par le bot (HOLD, PRENDRE TP, ...)
  advice_at        timestamptz,
  strategy         text,
  notes            text,
  events           jsonb not null default '[]',
  opened_at        timestamptz not null default now(),
  closed_at        timestamptz,
  last_checked     timestamptz not null default now()
);
alter table public.trades add column if not exists advice text;
alter table public.trades add column if not exists advice_at timestamptz;
create index if not exists trades_user_idx on public.trades (user_id, opened_at desc);
create index if not exists trades_open_idx on public.trades (status) where status = 'ouvert';

-- ---------------------------------------------------------------------
-- 4. Améliorer le bot ensemble
-- ---------------------------------------------------------------------
create table if not exists public.bot_settings (
  key         text primary key,
  value       jsonb not null,
  label       text,
  help        text,
  min_value   numeric,
  max_value   numeric,
  updated_by  uuid references public.profiles(id) on delete set null,
  updated_at  timestamptz not null default now()
);

create table if not exists public.bot_settings_log (
  id         bigint generated always as identity primary key,
  key        text not null,
  old_value  jsonb,
  new_value  jsonb,
  changed_by uuid references public.profiles(id) on delete set null,
  created_at timestamptz not null default now()
);

create or replace function public.log_bot_setting() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if new.min_value is not null and jsonb_typeof(new.value) = 'number' and (new.value)::numeric < new.min_value then
    raise exception 'Valeur trop basse pour % (minimum %)', new.key, new.min_value;
  end if;
  if new.max_value is not null and jsonb_typeof(new.value) = 'number' and (new.value)::numeric > new.max_value then
    raise exception 'Valeur trop haute pour % (maximum %)', new.key, new.max_value;
  end if;
  new.updated_at := now();
  new.updated_by := coalesce(auth.uid(), new.updated_by);
  if new.value is distinct from old.value then
    insert into public.bot_settings_log (key, old_value, new_value, changed_by)
    values (new.key, old.value, new.value, auth.uid());
  end if;
  return new;
end $$;

drop trigger if exists bot_settings_log_trg on public.bot_settings;
create trigger bot_settings_log_trg before update on public.bot_settings
  for each row execute function public.log_bot_setting();

create table if not exists public.ideas (
  id         bigint generated always as identity primary key,
  user_id    uuid not null default auth.uid() references public.profiles(id) on delete cascade,
  title      text not null check (length(title) between 3 and 140),
  body       text,
  status     text not null default 'proposée' check (status in ('proposée','en cours','faite','refusée')),
  created_at timestamptz not null default now()
);

create table if not exists public.idea_votes (
  idea_id bigint references public.ideas(id) on delete cascade,
  user_id uuid default auth.uid() references public.profiles(id) on delete cascade,
  primary key (idea_id, user_id)
);

create table if not exists public.scan_requests (
  id         bigint generated always as identity primary key,
  user_id    uuid not null default auth.uid() references public.profiles(id) on delete cascade,
  created_at timestamptz not null default now()
);

-- Réglages du bot modifiables depuis le site (bornes de sécurité incluses)
insert into public.bot_settings (key, value, label, help, min_value, max_value) values
 ('score_trade', '60', 'Score minimal pour un 🟢', 'Plus haut = moins de trades mais plus sélectifs.', 45, 85),
 ('score_watch', '40', 'Score minimal pour un 🟡', 'En dessous, le setup n''est même pas affiché.', 25, 70),
 ('min_rr_tp2', '1.5', 'R:R minimal au TP2', 'Gain potentiel minimum au TP2, en multiples du risque.', 1, 4),
 ('min_net_rr_tp2', '1.2', 'R:R net de frais minimal au TP2', 'Même chose après les frais Kraken.', 0.8, 3),
 ('max_spread_pct', '0.35', 'Spread maximal (%)', 'Écart achat/vente maximum accepté.', 0.05, 1),
 ('min_sl_atr15', '0.6', 'SL minimal (en volatilité 15m)', 'Évite les stops trop serrés qui sautent sur du bruit.', 0.3, 2),
 ('max_extension_atr15', '2.5', 'Extension maximale', 'Refuse les mouvements déjà partis trop loin.', 1, 5),
 ('universe_max_crypto', '30', 'Nombre de cryptos analysées', 'Les plus liquides.', 5, 40),
 ('universe_max_xstocks', '10', 'Nombre de xStocks analysés', '', 0, 20),
 ('universe_max_commodities', '8', 'Nombre de matières premières analysées', '', 0, 15),
 ('disabled_strategies', '[]', 'Stratégies désactivées', 'cassure_retest, rejet_sweep, tendance_pullback, news_momentum', null, null),
 ('news_enabled', 'true', 'Utiliser les news', '', null, null),
 ('use_optimized_params', 'true', 'Utiliser les réglages appris sur l''historique', '', null, null),
 ('quote_currencies', '["USD"]', 'Paires analysées', 'Devise de cotation des paires que le bot peut proposer (USD par défaut).', null, null)
on conflict (key) do nothing;

-- ---------------------------------------------------------------------
-- 5. Classement (calculé en direct)
-- ---------------------------------------------------------------------
create or replace view public.leaderboard with (security_invoker = true) as
select p.id, p.pseudo,
       count(t.id) filter (where t.status = 'clos')                                   as trades,
       count(t.id) filter (where t.status = 'clos' and t.realized_pnl_eur > 0)        as wins,
       coalesce(sum(t.realized_pnl_eur) filter (where t.status = 'clos'), 0)          as pnl_eur,
       coalesce(sum(t.r_multiple) filter (where t.status = 'clos'), 0)                as total_r,
       avg(t.r_multiple) filter (where t.status = 'clos')                             as avg_r,
       count(t.id) filter (where t.status = 'ouvert')                                 as open_trades
from public.profiles p
left join public.trades t on t.user_id = p.id
where p.approved
group by p.id, p.pseudo;

-- ---------------------------------------------------------------------
-- 6. Sécurité : Row Level Security (chacun ne modifie que ses données)
-- ---------------------------------------------------------------------
alter table public.profiles        enable row level security;
alter table public.balance_history enable row level security;
alter table public.scans           enable row level security;
alter table public.signals         enable row level security;
alter table public.instruments     enable row level security;
alter table public.bot_edges       enable row level security;
alter table public.trades          enable row level security;
alter table public.bot_settings    enable row level security;
alter table public.bot_settings_log enable row level security;
alter table public.ideas           enable row level security;
alter table public.idea_votes      enable row level security;
alter table public.scan_requests   enable row level security;

do $$
declare r record;
begin
  -- repart d'un jeu de règles propre à chaque exécution
  for r in select policyname, tablename from pg_policies where schemaname = 'public' loop
    execute format('drop policy if exists %I on public.%I', r.policyname, r.tablename);
  end loop;
end $$;

-- Profils
create policy "voir son profil ou les membres" on public.profiles for select
  using (id = auth.uid() or (public.is_approved() and approved));
create policy "modifier son profil" on public.profiles for update
  using (id = auth.uid() or public.is_admin()) with check (id = auth.uid() or public.is_admin());
create policy "admin voit les demandes" on public.profiles for select using (public.is_admin());
create policy "admin supprime" on public.profiles for delete using (public.is_admin() and id <> auth.uid());

create policy "voir son historique de solde" on public.balance_history for select using (user_id = auth.uid());

-- Données du bot : lecture pour les membres approuvés (écriture réservée au bot)
create policy "lecture scans" on public.scans for select using (public.is_approved());
create policy "lecture signaux" on public.signals for select using (public.is_approved());
create policy "lecture instruments" on public.instruments for select using (public.is_approved());
create policy "lecture edges" on public.bot_edges for select using (public.is_approved());

-- Trades : tout le club voit l'historique, chacun ne modifie que les siens
create policy "lecture trades du club" on public.trades for select using (public.is_approved());
create policy "créer ses trades" on public.trades for insert
  with check (user_id = auth.uid() and public.is_approved());
create policy "modifier ses trades" on public.trades for update
  using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy "supprimer ses trades" on public.trades for delete using (user_id = auth.uid());

-- Réglages du bot : tout membre approuvé peut les améliorer (bornes vérifiées + journal)
create policy "lecture réglages" on public.bot_settings for select using (public.is_approved());
create policy "modifier réglages" on public.bot_settings for update
  using (public.is_approved()) with check (public.is_approved());
create policy "lecture journal réglages" on public.bot_settings_log for select using (public.is_approved());

-- Idées
create policy "lecture idées" on public.ideas for select using (public.is_approved());
create policy "proposer une idée" on public.ideas for insert with check (user_id = auth.uid() and public.is_approved());
create policy "modifier son idée" on public.ideas for update
  using (user_id = auth.uid() or public.is_admin()) with check (user_id = auth.uid() or public.is_admin());
create policy "supprimer son idée" on public.ideas for delete using (user_id = auth.uid() or public.is_admin());
create policy "lecture votes" on public.idea_votes for select using (public.is_approved());
create policy "voter" on public.idea_votes for insert with check (user_id = auth.uid() and public.is_approved());
create policy "retirer son vote" on public.idea_votes for delete using (user_id = auth.uid());

-- Demandes de scan (bouton SCAN du site)
create policy "lecture demandes" on public.scan_requests for select using (public.is_approved());
create policy "demander un scan" on public.scan_requests for insert
  with check (user_id = auth.uid() and public.is_approved());

grant select on public.leaderboard to authenticated;
