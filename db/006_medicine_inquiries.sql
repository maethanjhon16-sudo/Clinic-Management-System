-- Medicine inquiries: students ask if a medicine is available, the nurse answers with a pick-up date.
-- Run once in the Supabase SQL Editor (safe to re-run).

-- What each medicine is commonly used for (comma-separated symptoms). The nurse can edit these in the app.
alter table pharmacy.medicines add column if not exists treats text;

create table if not exists pharmacy.medicine_inquiries (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null,
  symptoms text not null,
  details text,
  status text not null default 'pending'
    check (status in ('pending','ready','unavailable','collected','cancelled')),
  medicine_id uuid references pharmacy.medicines(id),
  quantity int check (quantity > 0),
  pickup_date date,
  response_note text,
  handled_by_id uuid,
  handled_by_name text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists ix_inquiries_student on pharmacy.medicine_inquiries (student_id);
create index if not exists ix_inquiries_status on pharmacy.medicine_inquiries (status);

-- Sample catalog. Replace or edit these so they match the medicine your clinic really keeps.
insert into pharmacy.medicines (name, unit, stock, reorder_level, expiry_date, treats) values
  ('Ambroxol 30 mg', 'tablet', 60, 20, '2027-09-30', 'cough, phlegm')
on conflict (name) do nothing;
update pharmacy.medicines set treats = 'headache, fever, body pain' where name = 'Paracetamol 500 mg' and treats is null;
update pharmacy.medicines set treats = 'headache, body pain, fever' where name = 'Ibuprofen 200 mg' and treats is null;
update pharmacy.medicines set treats = 'runny nose, allergy' where name = 'Cetirizine 10 mg' and treats is null;
update pharmacy.medicines set treats = 'stomach ache, diarrhea' where name = 'Oral Rehydration Salts' and treats is null;
