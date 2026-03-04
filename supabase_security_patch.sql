-- Tighten public exposure for exchange rate data.
-- Run this in Supabase SQL Editor once.

drop policy if exists exchange_rates_select_policy on public.exchange_rates;
create policy exchange_rates_select_policy
  on public.exchange_rates
  for select
  to service_role
  using (true);

revoke select on public.exchange_rates from anon, authenticated;
grant select on public.exchange_rates to service_role;

create or replace view public.latest_exchange_rates as
select distinct on (er.provider, er.currency)
  er.id,
  er.run_id,
  er.provider,
  er.provider_type,
  er.currency,
  er.send_rate,
  er.receive_rate,
  er.fee,
  er.scraped_at,
  er.created_at
from public.exchange_rates er
order by er.provider, er.currency, er.scraped_at desc, er.id desc;

grant select on public.latest_exchange_rates to anon, authenticated, service_role;
