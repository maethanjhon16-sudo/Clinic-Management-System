# Integrated School Clinic Management System

REST API-based system integration project (SIA final project).

- `db/schema.sql` : Postgres schemas, one per service (run in Supabase SQL Editor)
- `services/student` : Student service (FastAPI)
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
