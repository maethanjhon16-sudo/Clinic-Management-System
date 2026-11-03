# Integrated School Clinic Management System

REST API-based system integration project (SIA final project).

- `db/schema.sql` : Postgres schemas, one per service (run in Supabase SQL Editor)
- `services/student` : Student service (FastAPI)
- `services/appointments` : Appointments service (clinic time slots, student self-booking, validates students via the Student service)
- `services/consultation` : Consultation service (completes appointments, triggers pharmacy and excuse follow-ups)
- `services/pharmacy` : Pharmacy service (medicine catalog, stock, /dispense, student medicine inquiries)
- `services/excuse` : Excuse & Clearance service (signed tokens, QR codes, public verification)
- `services/notification` : Notification service (stores, sends and retries messages)
- `frontend` : React + TypeScript web app
- `DEPLOY_CHECKLIST.md` : the ordered deployment steps
- `gateway` : API gateway (routing, retries, CORS, /warmup)
- `render.yaml` : Render Blueprint for deployment

## Run locally
```
cd services/student
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="postgresql://..."
uvicorn main:app --reload --port 8001
```
In a second terminal:
```
cd gateway
pip install -r requirements.txt
export STUDENT_SERVICE_URL="http://localhost:8001"
uvicorn main:app --reload --port 8000
```
Docs: http://localhost:8001/docs (service), http://localhost:8000/docs (gateway)

## Appointments service (local)
```
cd services/appointments
pip install -r requirements.txt
export DATABASE_URL="postgresql://..."
export STUDENT_SERVICE_URL="http://localhost:8001"
uvicorn main:app --reload --port 8002
```
Then in the gateway terminal also set `APPOINTMENT_SERVICE_URL="http://localhost:8002"`.
Business rules: the student must exist and be active, the time must be in the future, inside clinic hours and on a
30-minute slot, with room left in that slot (SLOT_CAPACITY). Bookings for the same time wait for each other
(a database advisory lock), so a slot can never be oversold. A student can have at most 3 upcoming appointments.

## Consultation service
Env: DATABASE_URL, APPOINTMENT_SERVICE_URL (required); PHARMACY_SERVICE_URL, EXCUSE_SERVICE_URL (optional until built).
Run `db/002_consultation_events.sql` once in Supabase. Follow-up contracts used by this service:
- Pharmacy: `POST /dispense` {consultation_id, student_id, items:[{prescription_id, medicine_id, quantity}]}
- Excuse:   `POST /excuses` {consultation_id, student_id, rest_days, issued_on}
Any 2xx counts as success. Failed or skipped follow-ups are re-run with `POST /consultations/{id}/retry`.

## Pharmacy service
Env: DATABASE_URL. Run `db/003_pharmacy.sql` once in Supabase (adds columns, a safety index, and sample medicines).
`POST /dispense` is called by the Consultation service (set PHARMACY_SERVICE_URL there). It is all-or-nothing,
locks stock rows to prevent overselling, and is safe to repeat: a prescription is never deducted twice.
Reservations become `dispensed` with `PATCH /dispensing/{id}/confirm`, or are released with `/cancel`.

## Security model (gateway)
Staff and students sign in at `POST /auth/login` and receive a JWT. The gateway checks the token and the role
(admin, nurse, student) before forwarding any request. `POST /api/excuses` and `POST /api/notifications`
are internal only. Students can only list their own appointments and excuse slips. The QR verification endpoint
`GET /api/excuses/verify/{token}` is public and shows validity only, never medical details.
