-- Tracks the follow-up calls a consultation triggers (appointment, pharmacy, excuse).
-- Run once in the Supabase SQL Editor.
create table if not exists consultation.integration_events (
  id uuid primary key default gen_random_uuid(),
  consultation_id uuid not null references consultation.consultations(id) on delete cascade,
  target text not null check (target in ('appointment','pharmacy','excuse')),
  status text not null default 'pending'
    check (status in ('pending','success','failed','skipped')),
  attempts int not null default 0,
  last_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
