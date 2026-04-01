-- Legacy intelligence v1 schema (kept for compatibility with regression tests)
create table if not exists public.transaction_learning_rules (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    normalized_description text not null,
    raw_description_sample text,
    cluster_key text,
    created_at timestamptz not null default now()
);

alter table public.transaction_learning_rules enable row level security;

create policy "Users can view their own learning rules" on public.transaction_learning_rules
    for select using (auth.uid() = user_id);

create policy "Users can insert their own learning rules" on public.transaction_learning_rules
    for insert with check (auth.uid() = user_id);

create policy "Users can update their own learning rules" on public.transaction_learning_rules
    for update using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy "Users can delete their own learning rules" on public.transaction_learning_rules
    for delete using (auth.uid() = user_id);
