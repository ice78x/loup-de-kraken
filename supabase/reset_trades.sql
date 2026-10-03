-- ============================================================
--  REMISE À ZÉRO DES TRADES (à lancer UNE fois dans Supabase → SQL Editor → Run)
--  Supprime TOUS les trades du site (tous les membres), SAUF le dernier trade OUVERT sur TAO et le dernier OUVERT sur PUMP.
--  Sécurité : si le script ne trouve pas exactement ces 2 trades, il s'arrête et NE SUPPRIME RIEN.
--  ⚠ Irréversible. Les signaux du bot, les membres, les réglages et les idées ne sont pas touchés.
-- ============================================================
do $$
declare
  garder bigint[];
  n_garde int;
  n_suppr int;
begin
  select array_agg(id) into garder from (
    select distinct on (actif) id
    from (
      select id, opened_at,
             case when upper(display) like '%PUMP%' then 'PUMP'
                  when upper(display) like '%TAO%'  then 'TAO' end as actif
      from public.trades
      where status = 'ouvert'
    ) x
    where actif is not null
    order by actif, opened_at desc
  ) g;

  n_garde := coalesce(array_length(garder, 1), 0);
  if n_garde <> 2 then
    raise exception 'Je trouve % trade(s) ouvert(s) sur TAO/PUMP au lieu de 2 : RIEN n''a été supprimé.', n_garde;
  end if;

  delete from public.trades where not (id = any (garder));
  get diagnostics n_suppr = row_count;
  raise notice 'OK : % trade(s) supprimé(s), 2 gardés (TAO et PUMP).', n_suppr;
end $$;

-- Ce qui reste (doit afficher exactement 2 lignes : TAO et PUMP)
select t.id, p.pseudo, t.display, t.direction, t.status, t.entry_price, t.qty, t.leverage, t.opened_at
from public.trades t left join public.profiles p on p.id = t.user_id
order by t.opened_at desc;
