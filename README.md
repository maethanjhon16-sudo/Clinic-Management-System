# Integrated School Clinic Management System

REST API-based system integration project (SIA final project).

- `db/schema.sql` : Postgres schemas, one per service (run in Supabase SQL Editor)
- `services/student` : Student service (FastAPI)
- `services/appointments` : Appointments + doctors service (validates students via the Student service)
- `services/consultation` : Consultation service (completes appointments, triggers pharmacy and excuse follow-ups)
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
Business rules: student must exist and be active, doctor must exist and be active, time must be in the future,
no overlap within SLOT_MINUTES (default 30) for the same doctor, plus a database unique index as a safety net.

## Consultation service
Env: DATABASE_URL, APPOINTMENT_SERVICE_URL (required); PHARMACY_SERVICE_URL, EXCUSE_SERVICE_URL (optional until built).
Run `db/002_consultation_events.sql` once in Supabase. Follow-up contracts used by this service:
- Pharmacy: `POST /dispense` {consultation_id, student_id, items:[{prescription_id, medicine_id, quantity}]}
- Excuse:   `POST /excuses` {consultation_id, student_id, rest_days, issued_on}
Any 2xx counts as success. Failed or skipped follow-ups are re-run with `POST /consultations/{id}/retry`.
