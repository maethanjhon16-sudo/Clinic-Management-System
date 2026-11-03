-- Excuse slips issued at medicine pick-up, plus an instructor list.
-- Run once in the Supabase SQL Editor (safe to re-run).

-- A slip can now come from a medicine inquiry as well as from a consultation
alter table excuse.excuse_slips alter column consultation_id drop not null;
alter table excuse.excuse_slips add column if not exists inquiry_id uuid;
create unique index if not exists uq_slip_inquiry on excuse.excuse_slips (inquiry_id) where inquiry_id is not null;
alter table excuse.excuse_slips drop constraint if exists slip_has_source;
alter table excuse.excuse_slips add constraint slip_has_source check (consultation_id is not null or inquiry_id is not null);

-- Instructors (filled in once, using their school email addresses)
create table if not exists excuse.instructors (
  id uuid primary key default gen_random_uuid(),
  full_name text not null,
  email text not null unique,
  department text,
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

-- The nurse's check at pick-up
alter table pharmacy.medicine_inquiries add column if not exists fit_for_class boolean;
alter table pharmacy.medicine_inquiries add column if not exists rest_days int;
alter table pharmacy.medicine_inquiries add column if not exists excuse_slip_id uuid;
alter table pharmacy.medicine_inquiries add column if not exists excuse_error text;
