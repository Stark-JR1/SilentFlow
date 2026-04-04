-- Align transactions schema with current application fields.
-- Safe to run multiple times.

alter table if exists public.transactions
    add column if not exists payment_method text not null default 'account',
    add column if not exists status text not null default 'paid',
    add column if not exists due_date date null,
    add column if not exists paid_at timestamptz null,
    add column if not exists card_id uuid null,
    add column if not exists credit_card_id uuid null,
    add column if not exists invoice_id uuid null,
    add column if not exists is_installment boolean not null default false,
    add column if not exists installment_number integer null,
    add column if not exists installment_total integer null,
    add column if not exists total_installments integer null,
    add column if not exists installment_group_id uuid null;

-- Backfill legacy card_id into credit_card_id when needed.
update public.transactions
set credit_card_id = card_id
where credit_card_id is null
  and card_id is not null;

-- Keep both installment columns in sync for compatibility.
update public.transactions
set total_installments = installment_total
where total_installments is null
  and installment_total is not null;

-- Drop old constraint first so legacy rows can be normalized safely.
alter table public.transactions
  drop constraint if exists transactions_payment_method_check;

-- Normalize legacy values before recreating constraint.
update public.transactions
set payment_method = lower(trim(coalesce(payment_method, 'account')));

update public.transactions
set payment_method = case
    when payment_method in ('other', 'outro') then 'other'
    when payment_method in ('debit', 'debito', 'débito') then 'account'
    when payment_method in ('credit', 'credito', 'crédito') then 'card'
    when payment_method in ('account', 'pix', 'card', 'boleto', 'cash') then payment_method
    else 'account'
end;

-- Recreate to ensure allowed set is aligned with UI/backend.
alter table public.transactions
  add constraint transactions_payment_method_check
  check (payment_method in ('account', 'pix', 'card', 'boleto', 'cash', 'other'));

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'transactions_status_check'
  ) then
    alter table public.transactions
      add constraint transactions_status_check
      check (status in ('paid', 'pending', 'scheduled', 'cancelled'));
  end if;
end $$;

create index if not exists idx_transactions_credit_card_id
  on public.transactions (credit_card_id);

create index if not exists idx_transactions_installment_group_id
  on public.transactions (installment_group_id);
