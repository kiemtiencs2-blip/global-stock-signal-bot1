create table if not exists public.signals (
    signal_id text primary key,
    ticker text not null,
    side text not null check (side in ('LONG', 'SHORT')),
    timestamp timestamptz not null,
    entry double precision not null,
    tp double precision not null,
    sl double precision not null,
    status text not null default 'OPEN' check (status in ('OPEN', 'WIN', 'LOSS')),
    pnl double precision not null default 0,
    source text not null default 'V3 CHECK',
    created_at timestamptz not null default timezone('utc', now()),
    closed_at timestamptz
);

create unique index if not exists signals_active_setup_idx
on public.signals (ticker, side, entry, tp, sl)
where status = 'OPEN';

alter table public.signals enable row level security;

create policy "service role manages signals"
on public.signals for all
using (true)
with check (true);
