# Update: nurse-only clinic, student booking, new interface

## What changed
- Doctors are removed. The nurse now does everything the doctor did (complete visits, issue excuse slips).
  Roles are now: admin, nurse, student.
- Students can book and cancel their own appointments, choosing from the clinic's available time slots.
- Appointments are limited to clinic hours (default Mon-Fri, 8:00 AM-5:00 PM, 30-minute slots, one student per slot,
  at most 3 upcoming appointments per student). Change these with environment variables on the Appointments service:
  CLINIC_OPEN, CLINIC_CLOSE, CLINIC_DAYS (0=Monday), SLOT_MINUTES, SLOT_CAPACITY, MAX_UPCOMING_PER_STUDENT, CLINIC_TIMEZONE.
- Consultations record which nurse attended the visit.
- The whole web interface has a new, more formal design.

## Files changed
db/005_nurse_only.sql (new), db/schema.sql
services/appointments/main.py, services/consultation/main.py
gateway/main.py, gateway/auth.py
frontend/ (everything under src/, plus styles)

## To apply
1. Push the code to GitHub.
2. Supabase SQL Editor: run db/005_nurse_only.sql once.
3. Render: Manual Deploy (Deploy latest commit) for clinic-appointments-service, clinic-consultation-service, clinic-gateway.
4. Frontend: redeploy the static site (or restart npm run dev).


# Update 2: medicine inquiries replace student booking
- Students no longer book appointments. They send a medicine inquiry (symptoms such as headache, cough, runny nose).
- The nurse sees the inquiry with matching medicines from stock, then either confirms availability with a pick-up date
  (the stock is set aside) or answers that it is not available. The student is notified by email either way.
- Nurses still schedule appointments and record consultations (excuse slips depend on them).
- New: db/006_medicine_inquiries.sql. Changed: services/pharmacy, gateway, frontend.
- Pharmacy service needs two more variables: STUDENT_SERVICE_URL and NOTIFICATION_SERVICE_URL.

# Update 3: excuse slip at pick-up, instructor list, hidden scheduled visits
- When the student comes for the medicine, the nurse records whether the student is fit to continue classes.
  If not, an excuse slip is issued from the inquiry (days of rest), and the student is notified.
- New Instructors page: add instructors once with their school emails (one by one or several at once).
  The slip is then sent by ticking instructors from the list. Optional: set INSTRUCTOR_EMAIL_DOMAIN on the Excuse service
  (for example school.edu.ph) to accept only school email addresses.
- Appointments and Consultations are still available but hidden under "Scheduled visits" in the menu.
- New: db/007_pickup_excuse_instructors.sql. Changed: services/pharmacy, services/excuse, gateway, frontend.
- Pharmacy service needs one more variable: EXCUSE_SERVICE_URL.
