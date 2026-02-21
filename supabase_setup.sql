-- AusMoneySaver Supabase setup
-- Run this in Supabase SQL Editor.
-- This script is idempotent and safe to re-run.

create table if not exists public.exchange_rates (
  id            bigserial primary key,
  run_id        text,
  provider      text not null,
  provider_type text not null,
  currency      text not null,
  send_rate     double precision,
  receive_rate  double precision,
  fee           double precision,
  scraped_at    timestamptz not null default now(),
  created_at    timestamptz not null default now()
);

alter table public.exchange_rates add column if not exists run_id text;
alter table public.exchange_rates add column if not exists created_at timestamptz not null default now();
update public.exchange_rates
set run_id = coalesce(run_id, 'legacy-' || id::text)
where run_id is null;
alter table public.exchange_rates alter column run_id set not null;
alter table public.exchange_rates alter column run_id set default 'manual';

-- Normalize legacy provider_type values so the new constraint can be applied safely.
update public.exchange_rates
set provider_type = case
  when lower(trim(provider_type)) in ('bank', 'banks') then 'Bank'
  when lower(trim(provider_type)) in ('fintech', 'fin-tech', 'fin tech') then 'Fintech'
  when lower(replace(trim(provider_type), ' ', '_')) in (
    'offline', 'offline_exchange', 'offline_exchanges', 'cash_exchange', 'money_changer'
  ) then 'Offline'
  when lower(provider) in ('anz', 'commbank') then 'Bank'
  when lower(provider) in ('wise', 'remitly') then 'Fintech'
  when lower(provider) in ('unitedcurrency', 'united currency', 'travelmoneyoz') then 'Offline'
  when lower(trim(provider_type)) like '%bank%' then 'Bank'
  when lower(trim(provider_type)) like '%fin%' then 'Fintech'
  else 'Offline'
end
where provider_type is distinct from case
  when lower(trim(provider_type)) in ('bank', 'banks') then 'Bank'
  when lower(trim(provider_type)) in ('fintech', 'fin-tech', 'fin tech') then 'Fintech'
  when lower(replace(trim(provider_type), ' ', '_')) in (
    'offline', 'offline_exchange', 'offline_exchanges', 'cash_exchange', 'money_changer'
  ) then 'Offline'
  when lower(provider) in ('anz', 'commbank') then 'Bank'
  when lower(provider) in ('wise', 'remitly') then 'Fintech'
  when lower(provider) in ('unitedcurrency', 'united currency', 'travelmoneyoz') then 'Offline'
  when lower(trim(provider_type)) like '%bank%' then 'Bank'
  when lower(trim(provider_type)) like '%fin%' then 'Fintech'
  else 'Offline'
end;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'exchange_rates_provider_type_chk'
  ) then
    alter table public.exchange_rates
      add constraint exchange_rates_provider_type_chk
      check (provider_type in ('Bank', 'Fintech', 'Offline'));
  end if;
end $$;

create index if not exists idx_rates_currency on public.exchange_rates (currency);
create index if not exists idx_rates_provider on public.exchange_rates (provider);
create index if not exists idx_rates_scraped on public.exchange_rates (scraped_at desc);
create index if not exists idx_rates_run_id on public.exchange_rates (run_id);
create unique index if not exists uq_rates_run_provider_currency
  on public.exchange_rates (run_id, provider, currency);
create index if not exists idx_rates_provider_currency_scraped
  on public.exchange_rates (provider, currency, scraped_at desc);

create table if not exists public.scrape_runs (
  run_id        text primary key,
  started_at    timestamptz not null,
  completed_at  timestamptz not null default now(),
  success_count integer not null default 0,
  failure_count integer not null default 0,
  rows_inserted integer not null default 0,
  status        text not null check (status in ('success', 'partial', 'failed')),
  details       jsonb not null default '{}'::jsonb,
  created_at    timestamptz not null default now()
);

create index if not exists idx_scrape_runs_completed_at on public.scrape_runs (completed_at desc);
create index if not exists idx_scrape_runs_status on public.scrape_runs (status);

-- Security model:
-- - anon/authenticated: read-only
-- - service_role: write
alter table public.exchange_rates enable row level security;
alter table public.scrape_runs enable row level security;

drop policy if exists exchange_rates_select_policy on public.exchange_rates;
create policy exchange_rates_select_policy
  on public.exchange_rates
  for select
  to anon, authenticated
  using (true);

drop policy if exists exchange_rates_insert_service_policy on public.exchange_rates;
create policy exchange_rates_insert_service_policy
  on public.exchange_rates
  for insert
  to service_role
  with check (true);

drop policy if exists scrape_runs_select_policy on public.scrape_runs;
create policy scrape_runs_select_policy
  on public.scrape_runs
  for select
  to authenticated
  using (true);

drop policy if exists scrape_runs_insert_service_policy on public.scrape_runs;
create policy scrape_runs_insert_service_policy
  on public.scrape_runs
  for insert
  to service_role
  with check (true);

drop policy if exists scrape_runs_update_service_policy on public.scrape_runs;
create policy scrape_runs_update_service_policy
  on public.scrape_runs
  for update
  to service_role
  using (true)
  with check (true);

revoke all on table public.exchange_rates from anon, authenticated;
revoke all on table public.scrape_runs from anon, authenticated;
revoke all on sequence public.exchange_rates_id_seq from anon, authenticated;

grant usage on schema public to anon, authenticated, service_role;
grant select on public.exchange_rates to anon, authenticated;
grant insert on public.exchange_rates to service_role;
grant usage, select on sequence public.exchange_rates_id_seq to service_role;

grant select on public.scrape_runs to authenticated;
grant insert, update on public.scrape_runs to service_role;

-- View: latest row per (provider, currency) for UI.
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

grant select on public.latest_exchange_rates to anon, authenticated;
