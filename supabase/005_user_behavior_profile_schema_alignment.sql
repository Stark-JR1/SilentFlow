-- Align user_behavior_profile with current Intelligence implementation.
-- Safe to run multiple times.

alter table if exists public.user_behavior_profile
    add column if not exists most_used_account_id uuid null,
    add column if not exists most_used_card_id uuid null;

create index if not exists idx_user_behavior_profile_most_used_account_id
    on public.user_behavior_profile (most_used_account_id);

create index if not exists idx_user_behavior_profile_most_used_card_id
    on public.user_behavior_profile (most_used_card_id);
