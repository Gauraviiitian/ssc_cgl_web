# SSC CGL Prep

Rule-based adaptive mock tests + Groq-powered, cached doubt explanations.

## Local development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Env vars are read from `../​.env` (one level up, at the ProjectX root):
```
GROQ_API_KEY=...
DATABASE_URL=postgresql://...   # Neon connection string
SESSION_SECRET=...              # any random string, e.g. `python3 -c "import secrets; print(secrets.token_hex(32))"`
```

Seed the question bank once (idempotent to re-run for more questions):
```bash
.venv/bin/python3 scripts/generate_questions.py
```

Run the app:
```bash
.venv/bin/uvicorn app.main:app --reload --port 8000
```

## Deploying to Render + Neon

1. **Neon** (already done for dev) — free Postgres project at neon.tech, copy its connection string.
2. **Push this folder to a GitHub repo.** `.env` is gitignored on purpose — Render never reads it; secrets are set in Render's dashboard instead.
3. **Render** → New → Web Service → connect the repo. It should auto-detect `render.yaml`:
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - Add the three env vars (`GROQ_API_KEY`, `DATABASE_URL`, `SESSION_SECRET`) in the dashboard — `render.yaml` marks them `sync: false` so Render will prompt for values instead of expecting them in the repo.
4. Deploy. The app calls `db.init_schema()` on startup (idempotent `CREATE TABLE IF NOT EXISTS`), so first boot sets up tables automatically against Neon.
5. Free-tier note: the service sleeps after 15 min idle; first request after that takes ~30-60s to wake up. Fine for friends-scale usage.

## Cost model

- MCQ grading, adaptive question selection, and score summaries are pure SQL/arithmetic — zero LLM cost.
- Explanations are cached per `question_id` in `explanation_cache` — Groq is called once per unique question, ever, regardless of how many users ask.
- `scripts/generate_questions.py` is a manual, offline seeder — it's the only other place that calls Groq, and it never runs as part of a live request.
