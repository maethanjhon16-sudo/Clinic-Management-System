-- Integrated School Clinic System: one Postgres database, one schema per service.
-- Run once in the Supabase SQL Editor.

create schema if not exists student;
create schema if not exists appointments;
create schema if not exists consultation;
create schema if not exists pharmacy;
create schema if not exists excuse;
create schema if not exists notification;

-- Student service
create table if not exists student.students (
  id uuid primary key default gen_random_uuid(),
  student_number text not null unique,
  full_name text not null,
  email text not null unique,
  date_of_birth date,
  program text,
  year_level int check (year_level between 1 and 8),
  contact_number text,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Appointments service (includes doctors)
create table if not exists appointments.doctors (
  id uuid primary key default gen_random_uuid(),
  full_name text not null,
  specialization text,
  email text unique,
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists appointments.appointments (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null,
  doctor_id uuid not null references appointments.doctors(id),
  scheduled_at timestamptz not null,
  reason text,
  status text not null default 'scheduled'
    check (status in ('scheduled','completed','cancelled')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
-- Database-level double-booking protection
create unique index if not exists uq_doctor_slot
  on appointments.appointments (doctor_id, scheduled_at)
  where status <> 'cancelled';

-- Consultation service
create table if not exists consultation.consultations (
  id uuid primary key default gen_random_uuid(),
  appointment_id uuid not null unique,
  student_id uuid not null,
  doctor_id uuid not null,
  notes text,
  needs_excuse boolean not null default false,
  rest_days int check (rest_days >= 0),
  completed_at timestamptz not null default now()
);

create table if not exists consultation.prescriptions (
  id uuid primary key default gen_random_uuid(),
  consultation_id uuid not null references consultation.consultations(id) on delete cascade,
  medicine_id uuid not null,
  quantity int not null check (quantity > 0),
  instructions text
);

-- Pharmacy service
create table if not exists pharmacy.medicines (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  unit text,
  stock int not null default 0 check (stock >= 0),
  reorder_level int not null default 10,
  expiry_date date
);

create table if not exists pharmacy.dispensing_records (
  id uuid primary key default gen_random_uuid(),
  prescription_id uuid not null,
  medicine_id uuid not null references pharmacy.medicines(id),
  quantity int not null check (quantity > 0),
  status text not null default 'reserved'
    check (status in ('reserved','dispensed','failed')),
  created_at timestamptz not null default now()
);

-- Excuse & Clearance service (unique feature)
create table if not exists excuse.excuse_slips (
  id uuid primary key default gen_random_uuid(),
  consultation_id uuid not null unique,
  student_id uuid not null,
  token text not null unique,
  valid_from date not null,
  valid_until date not null check (valid_until >= valid_from),
  status text not null default 'valid' check (status in ('valid','revoked')),
  issued_at timestamptz not null default now(),
  revoked_at timestamptz,
  revoke_reason text
);

create table if not exists excuse.slip_recipients (
  id uuid primary key default gen_random_uuid(),
  slip_id uuid not null references excuse.excuse_slips(id) on delete cascade,
  instructor_name text not null,
  instructor_email text not null
);

-- Notification service
create table if not exists notification.notifications (
  id uuid primary key default gen_random_uuid(),
  recipient_email text not null,
  type text not null,
  subject text not null,
  body text not null,
  related_id uuid,
  status text not null default 'pending' check (status in ('pending','sent','failed')),
  attempts int not null default 0,
  last_error text,
  created_at timestamptz not null default now(),
  sent_at timestamptz
);
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
