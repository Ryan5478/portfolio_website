# Portfolio production package

## Files
- backend/main.py
- backend/requirements.txt
- backend/.env.example
- backend/.python-version
- render.yaml
- portfolio_live_backend_toast.html

## Local run
```powershell
cd backend
python -m venv venv
.\venv\Scripts\python -m pip install --upgrade pip
.\venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env
.\venv\Scripts\python -m uvicorn main:app --reload
```

## Production email
Use Resend in production/cloud hosting:
- create a Resend API key
- set OWNER_EMAIL
- set RESEND_API_KEY
- set RESEND_FROM_EMAIL
- optionally set RESEND_FROM_NAME

## Deploy on Render
1. Push the full site folder to GitHub.
2. Create a Render Blueprint or Web Service from the repo.
3. Render will use `render.yaml` in the project root.
4. Set the secret env vars in Render:
   - OWNER_EMAIL
   - RESEND_API_KEY
   - RESEND_FROM_EMAIL
5. Set `ALLOWED_ORIGINS` to your real frontend URL.
6. After Render gives you the live API URL, update `API_BASE_URL` in `portfolio_live_backend_toast.html`.

## Important
This package still stores messages in SQLite. On free Render, local files are ephemeral, so email notifications are the reliable record unless you later move message storage to Postgres.
