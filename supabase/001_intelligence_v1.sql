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

create index if not exists idx_tlr_user_desc
on public.transaction_learning_rules(user_id, normalized_description);

create index if not exists idx_tlr_user_active
on public.transaction_learning_rules(user_id, is_active);

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

-- Enable RLS on all intelligence tables
alter table public.intelligence_settings enable row level security;
alter table public.transaction_learning_rules enable row level security;
alter table public.transaction_learning_feedback enable row level security;
alter table public.transaction_recurrence_patterns enable row level security;

-- Policies for intelligence_settings
create policy "Users can view their own intelligence settings" on public.intelligence_settings
    for select using (auth.uid() = user_id);

create policy "Users can insert their own intelligence settings" on public.intelligence_settings
    for insert with check (auth.uid() = user_id);

create policy "Users can update their own intelligence settings" on public.intelligence_settings
    for update using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- Policies for transaction_learning_rules
create policy "Users can view their own learning rules" on public.transaction_learning_rules
    for select using (auth.uid() = user_id);

create policy "Users can insert their own learning rules" on public.transaction_learning_rules
    for insert with check (auth.uid() = user_id);

create policy "Users can update their own learning rules" on public.transaction_learning_rules
    for update using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy "Users can delete their own learning rules" on public.transaction_learning_rules
    for delete using (auth.uid() = user_id);

-- Policies for transaction_learning_feedback
create policy "Users can view their own learning feedback" on public.transaction_learning_feedback
    for select using (auth.uid() = user_id);

create policy "Users can insert their own learning feedback" on public.transaction_learning_feedback
    for insert with check (auth.uid() = user_id);

-- Policies for transaction_recurrence_patterns
create policy "Users can view their own recurrence patterns" on public.transaction_recurrence_patterns
    for select using (auth.uid() = user_id);

create policy "Users can insert their own recurrence patterns" on public.transaction_recurrence_patterns
    for insert with check (auth.uid() = user_id);

create policy "Users can update their own recurrence patterns" on public.transaction_recurrence_patterns
    for update using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy "Users can delete their own recurrence patterns" on public.transaction_recurrence_patterns
    for delete using (auth.uid() = user_id);
