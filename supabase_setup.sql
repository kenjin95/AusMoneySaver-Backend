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
  when lower(provider) in ('anz', 'commbank', 'nab', 'westpac') then 'Bank'
  when lower(provider) in ('wise', 'remitly', 'ofx') then 'Fintech'
  when lower(provider) in ('unitedcurrency', 'united currency', 'travelmoneyoz', 'travelex') then 'Offline'
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
  when lower(provider) in ('anz', 'commbank', 'nab', 'westpac') then 'Bank'
  when lower(provider) in ('wise', 'remitly', 'ofx') then 'Fintech'
  when lower(provider) in ('unitedcurrency', 'united currency', 'travelmoneyoz', 'travelex') then 'Offline'
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

create table if not exists public.rate_alerts (
  id               bigserial primary key,
  email            text not null,
  currency         text not null,
  target_rate      double precision not null,
  direction        text not null default 'gte',
  is_active        boolean not null default true,
  created_at       timestamptz not null default now(),
  last_notified_at timestamptz
);

alter table public.rate_alerts add column if not exists email text;
alter table public.rate_alerts add column if not exists currency text;
alter table public.rate_alerts add column if not exists target_rate double precision;
alter table public.rate_alerts add column if not exists direction text;
alter table public.rate_alerts add column if not exists is_active boolean;
alter table public.rate_alerts add column if not exists created_at timestamptz not null default now();
alter table public.rate_alerts add column if not exists last_notified_at timestamptz;
alter table public.rate_alerts alter column direction set default 'gte';
alter table public.rate_alerts alter column is_active set default true;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'rate_alerts_target_rate_chk'
  ) then
    alter table public.rate_alerts
      add constraint rate_alerts_target_rate_chk
      check (target_rate > 0) not valid;
  end if;
end $$;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'rate_alerts_direction_chk'
  ) then
    alter table public.rate_alerts
      add constraint rate_alerts_direction_chk
      check (direction in ('gte', 'lte')) not valid;
  end if;
end $$;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'rate_alerts_currency_chk'
  ) then
    alter table public.rate_alerts
      add constraint rate_alerts_currency_chk
      check (currency ~ '^[A-Z]{3}$') not valid;
  end if;
end $$;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'rate_alerts_email_chk'
  ) then
    alter table public.rate_alerts
      add constraint rate_alerts_email_chk
      check (position('@' in email) > 1) not valid;
  end if;
end $$;

create index if not exists idx_rate_alerts_active_currency
  on public.rate_alerts (is_active, currency);
create index if not exists idx_rate_alerts_created_at
  on public.rate_alerts (created_at desc);
create unique index if not exists uq_rate_alerts_active
  on public.rate_alerts (email, currency, target_rate, direction)
  where is_active;

-- Security model:
-- - anon/authenticated: read exchange rates, write rate alerts
-- - service_role: scraper writes + alert processing
alter table public.exchange_rates enable row level security;
alter table public.scrape_runs enable row level security;
alter table public.rate_alerts enable row level security;

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

drop policy if exists rate_alerts_insert_public_policy on public.rate_alerts;
create policy rate_alerts_insert_public_policy
  on public.rate_alerts
  for insert
  to anon, authenticated
  with check (
    target_rate > 0
    and direction in ('gte', 'lte')
    and currency ~ '^[A-Z]{3}$'
    and position('@' in email) > 1
  );

drop policy if exists rate_alerts_select_service_policy on public.rate_alerts;
create policy rate_alerts_select_service_policy
  on public.rate_alerts
  for select
  to service_role
  using (true);

drop policy if exists rate_alerts_update_service_policy on public.rate_alerts;
create policy rate_alerts_update_service_policy
  on public.rate_alerts
  for update
  to service_role
  using (true)
  with check (true);

revoke all on table public.exchange_rates from anon, authenticated;
revoke all on table public.scrape_runs from anon, authenticated;
revoke all on table public.rate_alerts from anon, authenticated;
revoke all on sequence public.exchange_rates_id_seq from anon, authenticated;

do $$
begin
  if exists (
    select 1
    from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public'
      and c.relname = 'rate_alerts_id_seq'
      and c.relkind = 'S'
  ) then
    revoke all on sequence public.rate_alerts_id_seq from anon, authenticated;
  end if;
end $$;

grant usage on schema public to anon, authenticated, service_role;
grant select on public.exchange_rates to anon, authenticated;
grant insert on public.exchange_rates to service_role;
grant usage, select on sequence public.exchange_rates_id_seq to service_role;

grant select on public.scrape_runs to authenticated;
grant insert, update on public.scrape_runs to service_role;

grant insert on public.rate_alerts to anon, authenticated;
grant select, insert, update on public.rate_alerts to service_role;

do $$
begin
  if exists (
    select 1
    from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public'
      and c.relname = 'rate_alerts_id_seq'
      and c.relkind = 'S'
  ) then
    grant usage, select on sequence public.rate_alerts_id_seq to anon, authenticated, service_role;
  end if;
end $$;

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
