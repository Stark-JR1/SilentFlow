-- Consolidated intelligence schema (legacy-friendly + idempotent)
-- Safe to run multiple times in Supabase SQL Editor.

-- -------------------------------------------------------------------
-- Core tables
-- -------------------------------------------------------------------

create table if not exists public.intelligence_settings (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    enable_suggestions boolean not null default true,
    enable_auto_fill boolean not null default false,
    enable_recurrence_detection boolean not null default true,
    learn_from_manual_edits boolean not null default true,
    learn_from_imported_transactions boolean not null default true,
    show_explanations boolean not null default true,
    min_confidence_to_suggest numeric(5,2) not null default 0.60,
    min_confidence_to_autofill numeric(5,2) not null default 0.90,
    description_similarity_threshold numeric(5,2) not null default 0.75,
    min_repetitions_for_pattern integer not null default 3,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique(user_id)
);

create table if not exists public.transaction_learning_rules (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    normalized_description text not null,
    raw_description_sample text,
    cluster_key text,
    category_id uuid null references public.categories(id) on delete set null,
    account_id uuid null references public.accounts(id) on delete set null,
    card_id uuid null references public.credit_cards(id) on delete set null,
    transaction_type text not null check (transaction_type in ('income', 'expense', 'transfer')),
    usage_count integer not null default 1,
    confidence_score numeric(5,2) not null default 0.50,
    last_used_at timestamptz,
    is_active boolean not null default true,
    is_auto_apply boolean not null default false,
    source_type text not null default 'manual' check (source_type in ('manual', 'imported', 'corrected')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.transaction_learning_feedback (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    transaction_id uuid null references public.transactions(id) on delete set null,
    input_description text not null,
    normalized_description text not null,
    suggested_category_id uuid null references public.categories(id) on delete set null,
    chosen_category_id uuid null references public.categories(id) on delete set null,
    suggested_account_id uuid null references public.accounts(id) on delete set null,
    chosen_account_id uuid null references public.accounts(id) on delete set null,
    suggested_card_id uuid null references public.credit_cards(id) on delete set null,
    chosen_card_id uuid null references public.credit_cards(id) on delete set null,
    suggested_type text null check (suggested_type in ('income', 'expense', 'transfer')),
    chosen_type text null check (chosen_type in ('income', 'expense', 'transfer')),
    accepted boolean not null default false,
    confidence_at_time numeric(5,2),
    created_at timestamptz not null default now()
);

create table if not exists public.transaction_recurrence_patterns (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    normalized_description text not null,
    category_id uuid null references public.categories(id) on delete set null,
    account_id uuid null references public.accounts(id) on delete set null,
    card_id uuid null references public.credit_cards(id) on delete set null,
    expected_amount numeric(14,2),
    amount_tolerance numeric(14,2),
    frequency_type text check (frequency_type in ('weekly', 'monthly', 'yearly')),
    expected_day_range_start integer,
    expected_day_range_end integer,
    confidence_score numeric(5,2) not null default 0.50,
    is_confirmed boolean not null default false,
    is_active boolean not null default true,
    last_detected_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.user_behavior_profile (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    avg_monthly_income decimal(15,2) default 0,
    avg_monthly_expense decimal(15,2) default 0,
    avg_monthly_savings decimal(15,2) default 0,
    avg_transaction_value decimal(15,2) default 0,
    recurring_transactions_count integer default 0,
    active_months_count integer default 0,
    top_category_id uuid references public.categories(id),
    top_category_share decimal(5,2) default 0,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create table if not exists public.user_category_behavior (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    category_id uuid not null references public.categories(id) on delete cascade,
    total_transactions integer default 0,
    total_amount decimal(15,2) default 0,
    avg_transaction_value decimal(15,2) default 0,
    monthly_avg decimal(15,2) default 0,
    usage_percentage decimal(5,2) default 0,
    last_transaction_date date,
    created_at timestamptz default now(),
    updated_at timestamptz default now(),
    unique(user_id, category_id)
);

create table if not exists public.intelligence_alerts (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    alert_type varchar(50) not null,
    severity varchar(20) not null default 'info',
    title varchar(200) not null,
    message text not null,
    reference_date date,
    reference_month date,
    amount decimal(15,2),
    is_read boolean default false,
    is_dismissed boolean default false,
    metadata jsonb default '{}'::jsonb,
    created_at timestamptz default now(),
    updated_at timestamptz default now(),
    expires_at timestamptz default (now() + interval '30 days')
);

-- -------------------------------------------------------------------
-- Compatibility backfills for previously minimal legacy table
-- -------------------------------------------------------------------

alter table public.transaction_learning_rules
    add column if not exists category_id uuid null references public.categories(id) on delete set null,
    add column if not exists account_id uuid null references public.accounts(id) on delete set null,
    add column if not exists card_id uuid null references public.credit_cards(id) on delete set null,
    add column if not exists transaction_type text,
    add column if not exists usage_count integer not null default 1,
    add column if not exists confidence_score numeric(5,2) not null default 0.50,
    add column if not exists last_used_at timestamptz,
    add column if not exists is_active boolean not null default true,
    add column if not exists is_auto_apply boolean not null default false,
    add column if not exists source_type text not null default 'manual',
    add column if not exists updated_at timestamptz not null default now();

update public.transaction_learning_rules
set transaction_type = 'expense'
where transaction_type is null;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'transaction_learning_rules_transaction_type_check'
  ) then
    alter table public.transaction_learning_rules
      add constraint transaction_learning_rules_transaction_type_check
      check (transaction_type in ('income', 'expense', 'transfer'));
  end if;
end $$;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'transaction_learning_rules_source_type_check'
  ) then
    alter table public.transaction_learning_rules
      add constraint transaction_learning_rules_source_type_check
      check (source_type in ('manual', 'imported', 'corrected'));
  end if;
end $$;

-- -------------------------------------------------------------------
-- Indexes
-- -------------------------------------------------------------------

create index if not exists idx_tlr_user_desc
  on public.transaction_learning_rules(user_id, normalized_description);

create index if not exists idx_tlr_user_active
  on public.transaction_learning_rules(user_id, is_active);

create index if not exists idx_user_behavior_profile_user_id
  on public.user_behavior_profile(user_id);

create index if not exists idx_user_category_behavior_user_id
  on public.user_category_behavior(user_id);

create index if not exists idx_user_category_behavior_category_id
  on public.user_category_behavior(category_id);

create index if not exists idx_intelligence_alerts_user_id
  on public.intelligence_alerts(user_id);

create index if not exists idx_intelligence_alerts_type
  on public.intelligence_alerts(alert_type);

create index if not exists idx_intelligence_alerts_severity
  on public.intelligence_alerts(severity);

create index if not exists idx_intelligence_alerts_created_at
  on public.intelligence_alerts(created_at);

create index if not exists idx_intelligence_alerts_expires_at
  on public.intelligence_alerts(expires_at);

-- -------------------------------------------------------------------
-- RLS
-- -------------------------------------------------------------------

alter table public.intelligence_settings enable row level security;
alter table public.transaction_learning_rules enable row level security;
alter table public.transaction_learning_feedback enable row level security;
alter table public.transaction_recurrence_patterns enable row level security;
alter table public.user_behavior_profile enable row level security;
alter table public.user_category_behavior enable row level security;
alter table public.intelligence_alerts enable row level security;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'intelligence_settings'
      and policyname = 'Users can view their own intelligence settings'
  ) then
    create policy "Users can view their own intelligence settings" on public.intelligence_settings
      for select using (auth.uid() = user_id);
  end if;
end $$;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'intelligence_settings'
      and policyname = 'Users can insert their own intelligence settings'
  ) then
    create policy "Users can insert their own intelligence settings" on public.intelligence_settings
      for insert with check (auth.uid() = user_id);
  end if;
end $$;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'intelligence_settings'
      and policyname = 'Users can update their own intelligence settings'
  ) then
    create policy "Users can update their own intelligence settings" on public.intelligence_settings
      for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
  end if;
end $$;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'transaction_learning_rules'
      and policyname = 'Users can view their own learning rules'
  ) then
    create policy "Users can view their own learning rules" on public.transaction_learning_rules
      for select using (auth.uid() = user_id);
  end if;
end $$;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'transaction_learning_rules'
      and policyname = 'Users can insert their own learning rules'
  ) then
    create policy "Users can insert their own learning rules" on public.transaction_learning_rules
      for insert with check (auth.uid() = user_id);
  end if;
end $$;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'transaction_learning_rules'
      and policyname = 'Users can update their own learning rules'
  ) then
    create policy "Users can update their own learning rules" on public.transaction_learning_rules
      for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
  end if;
end $$;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'transaction_learning_rules'
      and policyname = 'Users can delete their own learning rules'
  ) then
    create policy "Users can delete their own learning rules" on public.transaction_learning_rules
      for delete using (auth.uid() = user_id);
  end if;
end $$;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'transaction_learning_feedback'
      and policyname = 'Users can view their own learning feedback'
  ) then
    create policy "Users can view their own learning feedback" on public.transaction_learning_feedback
      for select using (auth.uid() = user_id);
  end if;
end $$;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'transaction_learning_feedback'
      and policyname = 'Users can insert their own learning feedback'
  ) then
    create policy "Users can insert their own learning feedback" on public.transaction_learning_feedback
      for insert with check (auth.uid() = user_id);
  end if;
end $$;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'transaction_recurrence_patterns'
      and policyname = 'Users can view their own recurrence patterns'
  ) then
    create policy "Users can view their own recurrence patterns" on public.transaction_recurrence_patterns
      for select using (auth.uid() = user_id);
  end if;
end $$;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'transaction_recurrence_patterns'
      and policyname = 'Users can insert their own recurrence patterns'
  ) then
    create policy "Users can insert their own recurrence patterns" on public.transaction_recurrence_patterns
      for insert with check (auth.uid() = user_id);
  end if;
end $$;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'transaction_recurrence_patterns'
      and policyname = 'Users can update their own recurrence patterns'
  ) then
    create policy "Users can update their own recurrence patterns" on public.transaction_recurrence_patterns
      for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
  end if;
end $$;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'transaction_recurrence_patterns'
      and policyname = 'Users can delete their own recurrence patterns'
  ) then
    create policy "Users can delete their own recurrence patterns" on public.transaction_recurrence_patterns
      for delete using (auth.uid() = user_id);
  end if;
end $$;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'user_behavior_profile'
      and policyname = 'Users can view their own behavior profile'
  ) then
    create policy "Users can view their own behavior profile" on public.user_behavior_profile
      for select using (auth.uid() = user_id);
  end if;
end $$;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'user_behavior_profile'
      and policyname = 'Users can insert their own behavior profile'
  ) then
    create policy "Users can insert their own behavior profile" on public.user_behavior_profile
      for insert with check (auth.uid() = user_id);
  end if;
end $$;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'user_behavior_profile'
      and policyname = 'Users can update their own behavior profile'
  ) then
    create policy "Users can update their own behavior profile" on public.user_behavior_profile
      for update using (auth.uid() = user_id);
  end if;
end $$;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'user_category_behavior'
      and policyname = 'Users can view their own category behavior'
  ) then
    create policy "Users can view their own category behavior" on public.user_category_behavior
      for select using (auth.uid() = user_id);
  end if;
end $$;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'user_category_behavior'
      and policyname = 'Users can insert their own category behavior'
  ) then
    create policy "Users can insert their own category behavior" on public.user_category_behavior
      for insert with check (auth.uid() = user_id);
  end if;
end $$;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'user_category_behavior'
      and policyname = 'Users can update their own category behavior'
  ) then
    create policy "Users can update their own category behavior" on public.user_category_behavior
      for update using (auth.uid() = user_id);
  end if;
end $$;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'intelligence_alerts'
      and policyname = 'Users can view their own alerts'
  ) then
    create policy "Users can view their own alerts" on public.intelligence_alerts
      for select using (auth.uid() = user_id);
  end if;
end $$;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'intelligence_alerts'
      and policyname = 'Users can insert their own alerts'
  ) then
    create policy "Users can insert their own alerts" on public.intelligence_alerts
      for insert with check (auth.uid() = user_id);
  end if;
end $$;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'intelligence_alerts'
      and policyname = 'Users can update their own alerts'
  ) then
    create policy "Users can update their own alerts" on public.intelligence_alerts
      for update using (auth.uid() = user_id);
  end if;
end $$;

-- -------------------------------------------------------------------
-- Triggers / helper functions
-- -------------------------------------------------------------------

create or replace function public.update_updated_at_column()
returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

drop trigger if exists update_user_behavior_profile_updated_at on public.user_behavior_profile;
create trigger update_user_behavior_profile_updated_at
before update on public.user_behavior_profile
for each row execute function public.update_updated_at_column();

drop trigger if exists update_user_category_behavior_updated_at on public.user_category_behavior;
create trigger update_user_category_behavior_updated_at
before update on public.user_category_behavior
for each row execute function public.update_updated_at_column();

drop trigger if exists update_intelligence_alerts_updated_at on public.intelligence_alerts;
create trigger update_intelligence_alerts_updated_at
before update on public.intelligence_alerts
for each row execute function public.update_updated_at_column();
