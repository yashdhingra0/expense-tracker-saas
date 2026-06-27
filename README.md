# Ledgerly — Expense Tracker SaaS (Phase 0)

A multi-tenant, hosted version of the Telegram expense tracker. Users sign up,
connect their **own** Telegram bot (token stored **encrypted**), and get a
polished web dashboard plus message-driven logging — same parsing engine, IOU
ledger, budgets, and insights as the local prototype.

This repo is the **Phase-0 MVP** from `ARCHITECTURE.md`: a runnable FastAPI app
with a single-file dashboard SPA. It runs on SQLite locally and on Postgres in
production by changing one env var.

---

## Quick start (local, SQLite)

```bash
cd expense-tracker-saas
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # the defaults work out of the box for dev
uvicorn app.main:app --reload
```

Open **http://localhost:8000**, create an account, and start logging — type
`spent 500 on ola` in the quick-add bar. Everything works without Telegram; the
**Connect Bot** tab wires up the bot when you're ready.

> Generate real secrets before sharing:
> ```
> python -c "import secrets;print(secrets.token_hex(32))"          # SECRET_KEY
> python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"  # TOKEN_ENC_KEY
> ```

---

## Which database?

| Use | Choice | Notes |
|---|---|---|
| **Local dev** | **SQLite** (default) | Zero setup; the `.db` file is created for you. |
| **Production** | **PostgreSQL** | Multi-tenant isolation (RLS), partitioning, concurrency. |
| Easiest managed Postgres | **Neon** or **Supabase** | Generous free tiers, instant setup. |
| On a cloud already | **RDS** (AWS) / **Cloud SQL** (GCP) | Backups, replicas, multi-AZ. |

Switch by setting `DATABASE_URL`:

```
# dev
DATABASE_URL=sqlite:///./expense_saas.db
# prod (example)
DATABASE_URL=postgresql+psycopg://user:pass@host:5432/ledgerly
```

SQLAlchemy handles both; no code changes. (Use Alembic for migrations once you're
on Postgres — `create_all` is fine for dev.)

---

## What's implemented

- **Accounts & auth** — signup/login, hashed passwords, signed session cookie.
- **Multi-tenant data model** — every row scoped by `user_id`; you only ever see
  your own data.
- **Message logging** — the proven parser turns `lent 1000 to rahul` /
  `got salary 75000` / `swiggy 420` into structured transactions.
- **Analytics API** — summary, categories, IOU balances, month-over-month,
  budgets, insights.
- **Bring-your-own-token** — `/bots/connect` validates with `getMe`, **encrypts**
  the token, and registers the Telegram webhook.
- **Webhook receiver** — `/tg/{routing_id}` with secret-header check and
  `update_id` idempotency.
- **Dashboard SPA** — login, quick-add, KPI cards, donut, month bars, People/IOU
  panel, budgets, insights, recent activity, connect-bot wizard, settings.

## Project layout

```
app/
  main.py            FastAPI app + serves the SPA
  config.py          env settings
  db.py  models.py   SQLAlchemy engine + multi-tenant tables
  security.py        passwords, sessions, token encryption (KMS stand-in)
  parser.py          NL → {amount, category, note, type, person}
  analytics.py       tenant-scoped aggregations + insights
  telegram_api.py    getMe / setWebhook / sendMessage
  routers/           auth, txns, analytics, bots, settings, telegram(webhook)
web/
  index.html         the dashboard (single file, no build step)
ARCHITECTURE.md      full system design + roadmap
```

## API (all under `/api/v1`, session-authenticated)

```
POST /auth/signup | /auth/login | /auth/logout      GET /auth/me
POST /txns  (log from a message)   GET /txns   PATCH /txns/{id}   DELETE /txns/{id}
GET  /analytics/summary | categories | people | months | budgets | insights
POST /bots/connect      GET /bots      POST /bots/{id}/disconnect
GET/PUT /settings
POST /tg/{routing_id}   (Telegram webhook; not user-facing)
```

---

## Going to production (next steps)

Phase 0 runs the webhook inline for simplicity. The path to "built to scale"
(see `ARCHITECTURE.md`): swap token encryption to a real **KMS**, put a **queue +
worker fleet** behind the webhook, move to **managed Postgres** with replicas,
add **Stripe** billing, and deploy the stateless services on Cloud Run / ECS /
Fly.io behind a load balancer.

> Security note: `DEV_ALLOW_UNVERIFIED_TOKENS=true` lets you connect a bot
> offline during dev. Set it to `false` in production so only tokens Telegram
> accepts are stored.
