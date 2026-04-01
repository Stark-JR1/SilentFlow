alter table if exists public.transactions
    add column if not exists payment_method text not null default 'account',
    add column if not exists status text not null default 'paid',
    add column if not exists due_date date null,
    add column if not exists paid_at timestamptz null,
    add column if not exists card_id uuid null,
    add column if not exists invoice_id uuid null,
    add column if not exists is_installment boolean not null default false,
    add column if not exists installment_number integer null,
    add column if not exists installment_total integer null,
    add column if not exists installment_group_id uuid null;

alter table if exists public.transactions
    add constraint transactions_payment_method_check
    check (payment_method in ('account', 'pix', 'card', 'boleto', 'cash'));

alter table if exists public.transactions
    add constraint transactions_status_check
    check (status in ('paid', 'pending', 'scheduled', 'cancelled'));

create table if not exists public.cards (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    name text not null,
    brand text null,
    limit_amount numeric(14,2) not null default 0 check (limit_amount >= 0),
    closing_day integer not null check (closing_day between 1 and 31),
    due_day integer not null check (due_day between 1 and 31),
    account_id uuid null,
    is_active boolean not null default true,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.card_invoices (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    card_id uuid not null,
    reference_month date not null,
    closing_date date not null,
    due_date date not null,
    total_amount numeric(14,2) not null default 0,
    paid_amount numeric(14,2) not null default 0,
    status text not null,
    unique (card_id, reference_month),
    constraint card_invoices_status_check check (status in ('open', 'closed', 'partially_paid', 'paid', 'overdue'))
);

create table if not exists public.invoice_payments (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    invoice_id uuid not null,
    account_id uuid not null,
    amount numeric(14,2) not null,
    payment_date date not null,
    notes text null,
    created_at timestamptz not null default timezone('utc', now())
);
