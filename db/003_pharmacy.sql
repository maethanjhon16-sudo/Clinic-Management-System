-- Pharmacy service changes. Run once in the Supabase SQL Editor (safe to re-run).
alter table pharmacy.dispensing_records add column if not exists consultation_id uuid;
alter table pharmacy.dispensing_records add column if not exists student_id uuid;
alter table pharmacy.dispensing_records add column if not exists updated_at timestamptz not null default now();

alter table pharmacy.dispensing_records drop constraint if exists dispensing_records_status_check;
alter table pharmacy.dispensing_records add constraint dispensing_records_status_check
  check (status in ('reserved','dispensed','cancelled','failed'));

-- A prescription can only have one active dispensing record (makes retries safe).
create unique index if not exists uq_active_prescription
  on pharmacy.dispensing_records (prescription_id)
  where status <> 'cancelled';

-- Sample catalog so you can test right away.
insert into pharmacy.medicines (name, unit, stock, reorder_level, expiry_date) values
  ('Paracetamol 500 mg', 'tablet', 200, 50, '2027-12-31'),
  ('Ibuprofen 200 mg', 'tablet', 100, 30, '2027-10-31'),
  ('Cetirizine 10 mg', 'tablet', 80, 20, '2027-08-31'),
  ('Oral Rehydration Salts', 'sachet', 60, 20, '2028-01-31')
on conflict (name) do nothing;
