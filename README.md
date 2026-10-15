# SwasthyaAI

A multilingual health-awareness chatbot. Ask health questions in any of 12
Indian languages and get clear, non-diagnostic guidance powered by Google
Gemini. Includes email/password and Google sign-in, with saved chat history for
signed-in users.

## Setup

```bash
# 1. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure secrets
cp .env.example .env            # then fill in real values in .env

# 4. Run
python app.py
```

Open http://localhost:5000

`python app.py` listens on localhost only. To use Flask's debugger run
`FLASK_DEBUG=1 python app.py` (never expose it publicly), and set `HOST=0.0.0.0` only if you
really need other machines to reach it.

Run the tests with `pip install -r requirements-dev.txt && pytest`.

## Environment variables

See `.env.example`. You need at minimum a `SECRET_KEY` and a `GEMINI_API_KEY`.
The app refuses to start without `SECRET_KEY` (unless `FLASK_DEBUG=1`, for throwaway local use),
because a guessable key would let anyone forge a login session.
Google sign-in also needs `GOOGLE_OAUTH_CLIENT_ID` and
`GOOGLE_OAUTH_CLIENT_SECRET`. For local OAuth over http, set
`OAUTHLIB_INSECURE_TRANSPORT=1` (never in production).

## Project structure

```
app.py                  Flask app: pages, auth, chat API, history API
chatbot.py              Gemini wrapper (prompt + call)
models.py               SQLAlchemy models (User, Message)
templates/index.html    Landing page + guest chat + auth modal
templates/dashboard.html  Signed-in chat with saved history
requirements.txt        Python dependencies
.env.example            Config template (copy to .env)
```

## Notes

- Guests can chat without an account; those messages are **not** saved.
- Signed-in users get saved history, and recent turns are fed back to the model
  for context.
- This app is for health **awareness** only. It does not diagnose and is not a
  substitute for professional medical care.

## Security

Never commit your real `.env`. If an API key or OAuth secret has ever been
shared or committed, rotate it immediately.

## Deploying to Render (free)

This project is deploy-ready (`Procfile`, `render.yaml`, gunicorn, Postgres driver).

1. Push the project to a **GitHub** repo (the `.gitignore` keeps `.env` and the
   local db out — good).
2. On https://render.com, click **New → Blueprint** and pick your repo. Render
   reads `render.yaml` and creates a web service **plus a free PostgreSQL
   database**, already wired via `DATABASE_URL`.
3. In the service's **Environment** tab, fill in the secrets marked `sync:false`:
   - `GEMINI_API_KEY` — your key from aistudio.google.com
   - `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` — optional; only
     for Google sign-in. Leave blank to use email/password only.
   (`SECRET_KEY` is generated automatically; `DATABASE_URL` is injected.)
4. Deploy. Your app will be at `https://<name>.onrender.com`.

### Enabling Google sign-in in production
In Google Cloud Console → Credentials → your OAuth client, add this
**Authorized redirect URI** (note the `/login/google/authorized` path):
```
https://<your-app>.onrender.com/login/google/authorized
```
Do **not** set `OAUTHLIB_INSECURE_TRANSPORT` in production — it's only for local
http testing.

### Notes
- Tables are created automatically on first boot.
- Render's free tier sleeps after inactivity, so the first request after idle
  takes a few seconds to wake.
- The same setup works on any container/PaaS host: build with
  `pip install -r requirements.txt`, start with
  `gunicorn app:app --bind 0.0.0.0:$PORT`, and provide the env vars above.
