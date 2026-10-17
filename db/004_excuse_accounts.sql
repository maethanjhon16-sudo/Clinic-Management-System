-- Excuse tracking + login accounts. Run once in the Supabase SQL Editor (safe to re-run).
-- Note: the schema is called "accounts" because Supabase already owns a schema named "auth".
alter table excuse.excuse_slips add column if not exists student_notified boolean not null default false;

create schema if not exists accounts;
create table if not exists accounts.users (
  id uuid primary key default gen_random_uuid(),
  email text not null unique,
  password_hash text not null,
  full_name text not null,
  role text not null check (role in ('admin','doctor','nurse','student')),
  student_id uuid,
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);
