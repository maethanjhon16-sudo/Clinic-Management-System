-- Nurse-only clinic: removes doctors, records which nurse attended a visit,
-- and limits login roles to admin, nurse and student.
-- Run once in the Supabase SQL Editor (safe to re-run).

-- Appointments no longer belong to a doctor
drop index if exists appointments.uq_doctor_slot;
alter table appointments.appointments drop column if exists doctor_id;
drop table if exists appointments.doctors;

-- Consultations record the nurse who attended instead of a doctor
alter table consultation.consultations drop column if exists doctor_id;
alter table consultation.consultations add column if not exists attended_by_id uuid;
alter table consultation.consultations add column if not exists attended_by_name text;

-- Login roles
update accounts.users set role = 'nurse' where role = 'doctor';
alter table accounts.users drop constraint if exists users_role_check;
alter table accounts.users add constraint users_role_check check (role in ('admin','nurse','student'));
