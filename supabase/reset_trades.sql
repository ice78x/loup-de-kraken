-- ============================================================
--  REMISE À ZÉRO DES TRADES TERMINÉS (Supabase → SQL Editor → coller → Run)
--  Supprime, pour TOUS les membres, les trades CLOS et ANNULÉS (les anciens résultats faussés).
--  Les trades encore OUVERTS sont gardés (ils continuent d'être suivis).
--  Effet sur le solde : il revient au dernier solde que chaque membre a enregistré dans « Mon compte »
--  (les gains et pertes des trades supprimés ne comptent plus). Chacun peut le corriger dans Mon compte.
--  Ne touche PAS : signaux et mémoire du bot, backtests, membres, réglages, idées.
--  ⚠ Irréversible.
-- ============================================================
do $$
declare
  n_suppr int;
  n_garde int;
begin
  delete from public.trades where status in ('clos', 'annule');
  get diagnostics n_suppr = row_count;
  select count(*) into n_garde from public.trades;
  raise notice 'OK : % trade(s) terminé(s) supprimé(s), % trade(s) ouvert(s) gardé(s).', n_suppr, n_garde;
end $$;

-- Ce qui reste : uniquement les trades ouverts
select t.id, p.pseudo, t.display, t.direction, t.status, t.entry_price, t.sl, t.opened_at
from public.trades t left join public.profiles p on p.id = t.user_id
order by t.opened_at desc;
