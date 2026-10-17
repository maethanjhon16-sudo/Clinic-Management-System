# Deployment checklist (do each part once, in order)

## 0. Secrets to make up first (keep them private, never paste them in chat or GitHub)
- JWT_SECRET: a random string of 32+ characters
- EXCUSE_SIGNING_SECRET: a different random string of 32+ characters
- ADMIN_EMAIL / ADMIN_PASSWORD: your first administrator login (password 8+ characters)
Generate a secret with: python -c "import secrets; print(secrets.token_urlsafe(32))"

## 1. Push the code
git add . && git commit -m "Excuse, notifications, login and frontend" && git push

## 2. Supabase: run db/004_excuse_accounts.sql in the SQL Editor

## 3. Render: create two new services (+ New -> Web Service -> Public Git Repository)
clinic-excuse-service      Root Directory: services/excuse
clinic-notification-service Root Directory: services/notification
Build: pip install -r requirements.txt
Start: uvicorn main:app --host 0.0.0.0 --port $PORT      Instance: Free

Environment variables
  notification: PYTHON_VERSION=3.12.3, DATABASE_URL
  excuse:       PYTHON_VERSION=3.12.3, DATABASE_URL, EXCUSE_SIGNING_SECRET,
                STUDENT_SERVICE_URL=https://clinic-student-service.onrender.com,
                NOTIFICATION_SERVICE_URL=<notification service address>
Check <address>/health on both.

## 4. Render: add variables to the existing services
  clinic-appointments-service: NOTIFICATION_SERVICE_URL=<notification address>   then Manual Deploy (new code)
  clinic-consultation-service: EXCUSE_SERVICE_URL=<excuse address>                (redeploys by itself)
  clinic-gateway: EXCUSE_SERVICE_URL, NOTIFICATION_SERVICE_URL, DATABASE_URL (same as others),
                  JWT_SECRET, ADMIN_EMAIL, ADMIN_PASSWORD     then Manual Deploy (new code)
Addresses never end with / or /health.
Check https://<gateway>/health shows "version":"2.0.0" and /warmup shows every service ok.

## 5. Frontend (Render Static Site: + New -> Static Site -> Public Git Repository)
Root Directory: frontend     Build Command: npm install && npm run build     Publish Directory: dist
Environment variable: VITE_API_URL=https://<gateway address>
Then: gateway ALLOWED_ORIGINS=<static site address>,http://localhost:5173  (no spaces, no trailing /)
      excuse service FRONTEND_URL=<static site address>   (so QR codes open the verify page)
Local test first: copy .env.example to .env, set VITE_API_URL, run npm install then npm run dev.

## 6. First login
Open the site, sign in with ADMIN_EMAIL / ADMIN_PASSWORD, then create doctor, nurse and student users on the Users page.
