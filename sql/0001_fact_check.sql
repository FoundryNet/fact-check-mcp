-- Fact Verification — schema for fact-check-mcp. Standalone Supabase project.
-- Idempotent. On-demand server: tables are an answer cache (24h-fresh) + the
-- free-tier counter + the x402 payment ledger. No aggregator/cron tables.

create extension if not exists pg_trgm;

-- ── fact_checks (verify_claim answer cache, keyed by normalized-claim hash) ────
create table if not exists fact_checks (
  claim_hash   text primary key,         -- sha256 of normalized(claim||context)
  claim        text,
  domain       text,                      -- company | finance | patents | regulation | general
  verdict      text,                      -- supported | disputed | unverifiable
  confidence   integer,                   -- 0-100
  result       jsonb not null,            -- full verify_claim payload (sources, explanation, …)
  checked_at   timestamptz not null default now(),
  created_at   timestamptz not null default now()
);
create index if not exists idx_fc_checked on fact_checks (checked_at desc nulls last);
create index if not exists idx_fc_verdict on fact_checks (verdict);
create index if not exists idx_fc_domain on fact_checks (domain);
create index if not exists idx_fc_claim_trgm on fact_checks using gin (claim gin_trgm_ops);

-- ── source_checks (source_check answer cache, keyed by url hash) ──────────────
create table if not exists source_checks (
  url_hash     text primary key,          -- sha256 of normalized url
  url          text,
  domain       text,
  trust_score  integer,                   -- 0-100 heuristic
  result       jsonb not null,            -- full source_check payload
  checked_at   timestamptz not null default now(),
  created_at   timestamptz not null default now()
);
create index if not exists idx_sc_checked on source_checks (checked_at desc nulls last);
create index if not exists idx_sc_domain on source_checks (domain);

-- ── free-tier counter + payments ─────────────────────────────────────────────
create table if not exists fact_query_usage (
  agent_key text not null, day date not null,
  count integer not null default 0, updated_at timestamptz not null default now(),
  primary key (agent_key, day)
);
create or replace function fact_claim_free_query(p_agent_key text, p_day date, p_cap integer)
returns jsonb language plpgsql as $$
declare cur integer; ok boolean;
begin
  insert into fact_query_usage (agent_key, day, count, updated_at)
  values (p_agent_key, p_day, 0, now())
  on conflict (agent_key, day) do nothing;
  select count into cur from fact_query_usage
    where agent_key = p_agent_key and day = p_day for update;
  if cur < p_cap then
    update fact_query_usage set count = count + 1, updated_at = now()
      where agent_key = p_agent_key and day = p_day;
    ok := true; cur := cur + 1;
  else ok := false; end if;
  return jsonb_build_object('allowed', ok, 'count', cur, 'cap', p_cap);
end; $$;

create table if not exists fact_payments (
  tx_signature text primary key, intent text, agent_key text, tool text,
  amount_usdc numeric, payer_wallet text, recipient text, status text,
  block_time bigint, created_at timestamptz not null default now()
);
