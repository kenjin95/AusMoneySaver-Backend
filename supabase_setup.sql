-- AusMoneySaver Supabase setup
-- Run this in Supabase SQL Editor once.

create table if not exists public.exchange_rates (
  id            bigserial primary key,
  provider      text not null,
  provider_type text not null,
  currency      text not null,
  send_rate     double precision,
  receive_rate  double precision,
  fee           double precision,
  scraped_at    timestamptz not null default now()
);

create index if not exists idx_rates_currency on public.exchange_rates (currency);
create index if not exists idx_rates_provider on public.exchange_rates (provider);
create index if not exists idx_rates_scraped  on public.exchange_rates (scraped_at desc);

-- Keep API access simple for current MVP (anon key usage).
alter table public.exchange_rates disable row level security;

grant usage on schema public to anon, authenticated;
grant select, insert on public.exchange_rates to anon, authenticated;
grant usage, select on sequence public.exchange_rates_id_seq to anon, authenticated;

