# Expense Tracker SaaS — Architecture & Roadmap

**Turning the local Telegram expense bot into a multi-tenant, hosted product.**

Version 0.1 · Status: design · Owner: Yash

---

## 1. What we're building

A hosted service where anyone can sign up, connect their own Telegram bot, and
get the expense tracker we already prototyped — message-driven logging, an IOU
ledger, budgets, recurring bills, and a live dashboard — without running any code
on their own machine.

The single-user prototype already nails the hard product logic (natural-language
parsing, categories, IOU math, insights). This document is about the *platform*
that wraps it: accounts, secure token storage, a webhook-based bot fabric that
serves thousands of users, and a real web dashboard.

### Chosen direction (decisions already made)

| Decision | Choice | Consequence |
|---|---|---|
| Telegram connection | **Bring-your-own bot token** | Each user creates their own bot in BotFather and pastes the token. We must store it **encrypted** and run a webhook per bot. Great for white-label/branding; heavier onboarding and infra than a shared bot. |
| This deliverable | **Architecture + roadmap** | Design only, no code in this pass. |
| Scale target | **Built to scale** | Webhooks (not polling), a queue, stateless autoscaling workers, managed Postgres, a real secrets manager/KMS. |

### Goals

The platform should let a user go from signup to logging their first expense in
under five minutes, keep every user's financial data and bot token strictly
isolated and encrypted, stay correct under retries and duplicate Telegram
deliveries, and scale horizontally from one user to tens of thousands without an
architecture rewrite.

### Non-goals (for now)

We are not building our own Telegram client, a mobile app, bank/UPI
integrations, or receipt OCR in the first cut. Those are roadmap items, not
foundations.

---

## 2. The core challenge of BYO-token

Because every user brings their **own** bot, the platform is really a fleet
manager for N independent Telegram bots that all funnel into one shared backend.
Three problems fall out of that and shape the whole design:

1. **Secret custody.** A bot token is a bearer credential — whoever holds it
   controls that bot. We store thousands of them. They must be encrypted at rest
   with a managed key, never logged, and never sent to a browser.
2. **Inbound routing.** When a message hits one of our webhook endpoints, we must
   know *which tenant* it belongs to **without** decrypting anything, so receiving
   is cheap and fast.
3. **Outbound fan-out.** To reply, we need that tenant's token decrypted briefly,
   used, and discarded — at message rates, across many bots, within Telegram's
   per-bot rate limits.

Everything below is organized around solving these cleanly.

---

## 3. High-level architecture

```
                         ┌─────────────────────────────────────────────┐
   Telegram  ── HTTPS ──▶│  Webhook Ingress (stateless, autoscaled)     │
  (N user bots)          │  POST /tg/{routing_id}                       │
                         │  • verify X-Telegram secret header           │
                         │  • look up tenant by routing_id (no decrypt) │
                         │  • dedupe by update_id                        │
                         │  • enqueue {tenant_id, update} → return 200   │
                         └───────────────┬─────────────────────────────┘
                                         │ (message queue: SQS / Redis Streams / Kafka)
                                         ▼
                         ┌─────────────────────────────────────────────┐
                         │  Worker fleet (stateless, autoscaled on lag) │
                         │  • parse (reuses parser.py logic)            │
                         │  • write txn (tenant-scoped)                 │
                         │  • recompute aggregates / IOU balances       │
                         │  • decrypt token (short-TTL cache) → reply   │
                         └───────┬──────────────────────┬──────────────┘
                                 │                      │
              ┌──────────────────▼───────┐   ┌──────────▼───────────────┐
              │ PostgreSQL (managed,      │   │ KMS  +  Token Vault       │
              │ multi-tenant, replicas)   │   │ (envelope/wrapped tokens) │
              └──────────────────┬───────┘   └──────────────────────────┘
                                 │
   Browser ── HTTPS ──▶ ┌────────▼─────────────────────┐      ┌──────────────┐
  (dashboard, React)    │  API Backend (stateless)      │◀────▶│ Redis cache  │
                        │  • auth / sessions            │      │ sessions,    │
                        │  • bot connect + setWebhook   │      │ dedupe, hot  │
                        │  • transactions / analytics   │      │ aggregates   │
                        │  • billing (Stripe)           │      └──────────────┘
                        └───────────────────────────────┘
```

The split that matters: **ingress is dumb and fast** (receive, authenticate,
route, enqueue, ack), **workers are smart and idempotent** (the real
parse/store/reply logic), and the **API + dashboard** is a conventional
authenticated web app reading the same database. Each tier scales independently.

### Components

**Web dashboard (frontend).** A React/Next.js app — the marketing site, signup,
the "Connect your bot" wizard, and the analytics dashboard. The prototype's
inline-SVG charts port directly to React components; the offline `data.js` trick
is replaced by authenticated API calls.

**API backend.** A stateless FastAPI service handling auth, the bot-connection
lifecycle (validate token → register webhook), CRUD for transactions, analytics
endpoints, settings, and billing webhooks. Reuses the prototype's `parser.py` and
insight logic as a shared library.

**Webhook ingress.** A thin, separately-deployable service whose only job is to
absorb Telegram traffic safely and enqueue it. Kept separate from the API so a
traffic spike on bots can't starve the dashboard, and vice versa.

**Worker fleet.** Stateless consumers that do the parse → store → reply pipeline.
Autoscale on queue depth. This is where token decryption happens, briefly.

**Token vault + KMS.** Encrypted storage of bot tokens, with the master key held
in a managed KMS that never exposes key material. Detailed in §6.

**PostgreSQL.** One managed cluster, multi-tenant by `user_id`, with read
replicas and partitioning for the large `txns` table.

**Redis.** Sessions, `update_id` dedupe set, hot dashboard aggregates, and a
short-TTL decrypted-token cache to avoid a KMS call on every single reply.

**Message queue.** SQS (managed, simplest) or Redis Streams to start; Kafka only
if/when throughput demands it. Decouples ingress from processing and gives us
retries + a dead-letter queue for poison messages.

---

## 4. Onboarding flow — connecting a bot (BYO token)

This is the flow we must make feel effortless, because it's the one place we push
work onto the user. The dashboard wizard walks them through BotFather and then
does all the wiring automatically.

```
Step 1  User signs up (email+password or Google OAuth) → tenant created.
Step 2  Dashboard: "Connect Telegram" wizard shows, with copy-paste steps:
          • Open Telegram, search @BotFather
          • Send /newbot → choose a name + username
          • BotFather replies with a token like 8994…:AAE…
Step 3  User pastes the token into the wizard.
Step 4  Backend validates it: calls Telegram getMe.
          • invalid → friendly error, nothing stored
          • valid   → capture bot id/username, continue
Step 5  Backend encrypts the token (KMS) and stores the ciphertext + a random
        routing_id for this bot.
Step 6  Backend registers the webhook with Telegram:
          setWebhook(url = https://api.ourapp.com/tg/{routing_id},
                     secret_token = <random per-bot secret>,
                     allowed_updates = ["message"])
Step 7  Dashboard shows "Send /start to your bot to finish."
        User messages their bot → first webhook arrives → we link the Telegram
        chat_id to the tenant and reply "✅ You're connected."
Step 8  Done. User logs expenses; dashboard updates live.
```

The in-app BotFather instructions (the "tell the user how to generate the key"
requirement) live in §11 as ready-to-use copy.

Two subtleties worth calling out. First, the **routing_id** in the webhook URL is
a random opaque token, *not* the bot id and *not* the secret — it lets ingress
find the tenant with a single indexed lookup and no decryption. Second, the
**secret_token** is a separate per-bot value Telegram echoes back in the
`X-Telegram-Bot-Api-Secret-Token` header on every call; ingress rejects anything
whose header doesn't match, which stops forged webhook calls cold.

---

## 5. Multi-tenant data model

One Postgres database, every domain row stamped with `user_id`. Application code
always filters by the authenticated tenant; Postgres Row-Level Security is enabled
as defense-in-depth so a missed `WHERE user_id = …` can't leak across tenants.

```
users
  id              uuid  pk
  email           text  unique
  password_hash   text            -- or null if OAuth-only
  plan            text            -- free | pro | business
  created_at      timestamptz

telegram_bots                     -- one (or more) per user
  id              uuid  pk
  user_id         uuid  fk → users
  bot_telegram_id bigint          -- from getMe, not secret
  bot_username    text
  routing_id      text  unique     -- random; used in webhook URL
  webhook_secret  text            -- per-bot secret_token (stored encrypted too)
  token_ciphertext bytea          -- ENCRYPTED bot token (never plaintext)
  token_key_id    text            -- KMS key/version used (for rotation)
  token_nonce     bytea           -- AES-GCM nonce
  status          text            -- pending | active | revoked | error
  linked_chat_id  bigint          -- set after user sends /start
  created_at      timestamptz

txns                              -- the core ledger (partition by user hash/date)
  id              bigint pk
  user_id         uuid  fk → users
  date            date
  category        text
  amount          numeric(14,2)
  note            text
  type            text            -- expense | income | lent | borrowed |
                                  --   repaid_to_me | repaid_by_me
  person          text            -- IOU counterparty, nullable
  source          text            -- telegram | manual | recurring
  tg_update_id    bigint          -- for idempotency/dedupe
  created_at      timestamptz
  indexes: (user_id, date), (user_id, type), unique(user_id, tg_update_id)

budgets
  user_id, category, monthly_cap   -- plus a row for the overall monthlyBudget

categories                         -- per-user editable keyword lists
  user_id, name, keywords[]        -- ships with sensible defaults

recurring
  user_id, day, category, amount, note, active

settings
  user_id, currency, daily_recap_hour, monthly_review, timezone

audit_log
  user_id, actor, action, target, metadata jsonb, created_at
```

Two design notes. The `unique(user_id, tg_update_id)` constraint is what makes
duplicate Telegram deliveries harmless — a retried update simply violates the
constraint and is skipped. And `txns` is the only table that grows without bound,
so it's partitioned (by `user_id` hash, or by month) with indexes on
`(user_id, date)`; everything else stays small and unpartitioned.

IOU balances are **derived**, never stored as a mutable running total — the same
`lent − repaid_to_me − borrowed + repaid_by_me` aggregation from the prototype,
computed per person on read (and cached in Redis). Derived balances can't drift
out of sync with the underlying entries.

---

## 6. Secrets & token encryption (the heart of BYO-token)

The bot token is the most sensitive thing we hold. The design principle is
simple: **plaintext tokens exist only in memory, only on a worker, only for the
milliseconds it takes to call Telegram.** They never touch logs, never reach the
browser, and never sit unencrypted at rest.

### Encryption approach

We use a managed KMS (AWS KMS, GCP KMS, or HashiCorp Vault Transit). The master
key (KEK) lives inside the KMS and **cannot be exported** — we can only ask the
KMS to encrypt/decrypt with it.

A Telegram token is tiny (~50 bytes), so the simplest correct design is **direct
KMS encryption**: on connect, call `KMS.Encrypt(token, encryptionContext={user_id})`
and store the returned ciphertext blob. To use it, call `KMS.Decrypt`. The
`encryptionContext` cryptographically binds the ciphertext to that tenant — a
ciphertext copied into another tenant's row will fail to decrypt, which kills
ciphertext-swapping attacks.

If per-message KMS calls become a cost/latency concern at scale, switch to
**envelope encryption**: generate a random 256-bit data key (DEK) per bot,
encrypt the token locally with AES-256-GCM, and store the DEK *wrapped* by the
KMS KEK. Decryption then unwraps the DEK once and caches it briefly. Either way
the at-rest record is `{ciphertext, nonce, key_id, wrapped_dek?}` and the KEK
never leaves the KMS.

### What's stored where

| Item | At rest | In transit | In browser |
|---|---|---|---|
| Bot token | Encrypted (KMS), `token_ciphertext` | TLS only, worker↔Telegram | **Never** |
| Webhook secret | Encrypted | TLS | Never |
| User password | Argon2id/bcrypt hash | TLS | Never |
| Financial txns | DB encryption at rest + per-tenant isolation | TLS | Yes, the user's own only |

### Operational rules

A short-TTL (e.g. 60s) **decrypted-token cache** in worker memory (or Redis,
itself encrypted) avoids a KMS round-trip on every reply while keeping exposure
small. Tokens are scrubbed from memory after use. Logging redacts anything that
looks like a token (`\d+:[A-Za-z0-9_-]{30,}`). **Key rotation** is handled by the
KMS rotating the KEK; because the `key_id`/version is stored per row, old
ciphertexts stay decryptable and can be lazily re-encrypted. If a user's token is
compromised they revoke it in BotFather and reconnect — we also expose a
"disconnect bot" button that deletes the ciphertext and calls `deleteWebhook`.

### Threat model (abbreviated)

| Threat | Mitigation |
|---|---|
| DB dump leaked | Tokens are KMS-encrypted; attacker also needs KMS access |
| Stolen ciphertext reused in another tenant | KMS `encryptionContext` binding fails |
| Forged webhook calls | Per-bot `secret_token` header check + random routing_id URL |
| Token in logs/traces | Redaction filter + lint rule; never serialize the field |
| Cross-tenant data access | App-layer `user_id` filter + Postgres RLS |
| Compromised worker | Least-privilege IAM; only workers can call KMS Decrypt; short token TTL |

---

## 7. Telegram webhook handling & correctness

**Webhooks, not polling.** Long-polling (what the prototype uses) needs a live
connection per bot — unworkable for thousands of bots. Each bot is registered
with `setWebhook` pointing at `…/tg/{routing_id}`, so Telegram pushes updates to
us and we hold zero idle connections.

**Receiving safely.** Ingress validates the `X-Telegram-Bot-Api-Secret-Token`
header against the bot's stored secret, looks up the tenant by `routing_id`
(indexed, no decryption), and must **return 200 within seconds** or Telegram
retries. So ingress does no heavy work — it enqueues and acks. Real processing is
async on the workers.

**Idempotency.** Telegram can deliver the same `update_id` more than once
(retries, redeliveries). We dedupe twice: a fast Redis "seen update_id" check at
ingress, and the hard `unique(user_id, tg_update_id)` DB constraint at write
time. Processing is therefore at-least-once delivery made effectively-once.

**Failure handling.** A message that fails processing is retried with backoff;
after N attempts it lands in a dead-letter queue and alerts us, rather than
blocking the bot. If `setWebhook` drifts (Telegram reports webhook errors via
`getWebhookInfo`), a periodic reconciler re-registers it.

---

## 8. Scaling design

Each tier scales on its own signal, which is the whole point of the ingress /
queue / worker / API separation.

**Ingress** is CPU-trivial and scales horizontally behind a load balancer on
request rate. **Workers** autoscale on **queue depth / consumer lag** — the
honest signal for "are we keeping up." The **queue** absorbs bursts so a flood of
messages becomes latency, not dropped data or a melted database.

**Database** is the usual bottleneck, addressed by: connection pooling
(PgBouncer) so thousands of workers don't exhaust Postgres connections; **read
replicas** for the dashboard's analytics queries (writes go to primary, reads to
replicas); and **partitioning** of `txns`. Hot dashboard aggregates are cached in
Redis and recomputed on write, so opening the dashboard is a cache hit, not a
table scan.

**Telegram rate limits** work in our favor here: limits are *per bot*
(~30 messages/sec, 1/sec per chat), and every tenant has their own bot, so one
noisy user can't rate-limit another. We just need per-bot outbound pacing to stay
under those ceilings.

Rough capacity intuition: a single small worker handling parse+store+reply in
tens of milliseconds clears hundreds of messages/sec; expense logging is bursty
and low-volume per user, so even tens of thousands of users generate a modest
sustained rate. We scale workers and replicas well before any of this is tight.

---

## 9. API surface (dashboard ↔ backend)

A conventional authenticated REST/JSON API. Every endpoint is tenant-scoped via
the session; there is no endpoint that can read another user's data.

```
Auth
  POST /auth/signup            email+password → session
  POST /auth/login
  POST /auth/logout
  GET  /auth/me

Bot connection
  POST /bots/connect           { token } → validate(getMe) → encrypt → setWebhook
  GET  /bots                   list connected bots + status
  POST /bots/{id}/disconnect   delete ciphertext + deleteWebhook
  POST /tg/{routing_id}        (Telegram-only webhook; not user-facing)

Data
  GET  /txns?month=YYYY-MM&type=…      paginated ledger
  POST /txns                            manual add (mirror of a chat message)
  PATCH /txns/{id}                      edit (the /edit feature)
  DELETE /txns/{id}
  GET  /analytics/summary?month=        spent vs budget, projection, net
  GET  /analytics/categories?month=     donut + ledger data
  GET  /analytics/people                IOU balances
  GET  /analytics/insights?month=       the auto-generated insights
  GET  /export?format=csv|xlsx          download

Settings & billing
  GET/PUT /settings                     currency, budgets, recurring, schedules
  POST /billing/checkout                Stripe checkout session
  POST /billing/webhook                 Stripe events (plan changes)
```

The dashboard stays a thin client: the same chart components from the prototype,
now fed by `/analytics/*` instead of a local `data.js`.

---

## 10. Reliability, billing & operations

**Billing.** Stripe subscriptions with plan gating (e.g. Free = 1 bot + current
month; Pro = history, exports, scheduled summaries; Business = multiple/white-label
bots). The Stripe webhook updates `users.plan`; feature checks read it.

**Backups & DR.** Managed Postgres with automated backups and point-in-time
recovery, multi-AZ. The KMS key is regionally replicated; losing it means losing
all tokens (users would simply reconnect), but data stays safe.

**Observability.** Structured logs (token-redacted), metrics (queue lag, webhook
2xx rate, KMS latency, DB pool saturation), traces across ingress→queue→worker,
and Sentry for exceptions. Alert on queue lag, DLQ growth, and webhook failure
rate.

**Compliance.** It's financial PII: TLS everywhere, encryption at rest, GDPR-style
data export and "delete my account" (purges txns + token + calls `deleteWebhook`),
an audit log, and least-privilege IAM (only workers can call KMS Decrypt).

---

## 11. In-app onboarding copy (BotFather guide)

Ready-to-ship wizard text for the "Connect your bot" screen:

> **Connect your Telegram bot — 2 minutes**
> 1. Open Telegram and search for **@BotFather** (the one with the blue check).
> 2. Send **`/newbot`**. Pick a display name, then a username ending in `bot`
>    (e.g. `yash_expense_bot`).
> 3. BotFather replies with a line like
>    `Use this token to access the HTTP API:` followed by a token such as
>    `8994455176:AAE_EJ…`. **Copy the whole token**, including the part before the
>    colon.
> 4. Paste it below and click **Connect**. We'll verify it and set everything up.
> 5. Open your new bot and send **`/start`** — that links it to your account.
>
> *Your token is encrypted and stored securely. We never display it again and you
> can disconnect any time.*

The wizard validates with `getMe` on paste and shows the detected bot username as
confirmation before storing.

---

## 12. Recommended stack & infrastructure

Opinionated defaults that reuse the prototype's Python logic and fit the
"built to scale" target. None are load-bearing — swap freely.

| Layer | Recommendation | Why / alternatives |
|---|---|---|
| Frontend | Next.js (React) + Tailwind | Reuse prototype SVG charts; SSR for marketing. Alt: SvelteKit |
| API + workers | FastAPI (Python, async) | **Reuses `parser.py` + insights as-is.** Alt: Node/NestJS |
| Bot ingress | FastAPI or a tiny Go/Node service | Hot path; keep it minimal. Alt: AWS Lambda behind API Gateway |
| Database | PostgreSQL (RDS/Cloud SQL/Neon) | RLS, partitioning, replicas |
| Cache | Redis (ElastiCache/Upstash) | Sessions, dedupe, hot aggregates, token TTL cache |
| Queue | SQS or Redis Streams → Kafka later | Managed + DLQ. Start simple |
| Secrets/keys | AWS KMS + Secrets Manager | Token encryption + app secrets |
| Auth | Clerk/Supabase Auth early, or own (Authlib) | Ship faster; own it later |
| Payments | Stripe | Subscriptions + webhooks |
| Hosting | Containers on ECS Fargate / Cloud Run / Fly.io | Stateless, autoscaling. K8s only if needed |
| IaC + CI/CD | Terraform + GitHub Actions | Reproducible infra, gated deploys |
| Observability | OpenTelemetry + Grafana/Datadog + Sentry | Lag, errors, traces |

**Illustrative early-stage cost** (rough, *not* a quote — verify against current
provider pricing): a managed Postgres (~$30–60/mo), small Redis (~$15/mo), a few
container instances (~$40–80/mo), KMS + queue (a few dollars at low volume), plus
Stripe's per-transaction fee. Call it **~$100–200/month** to run for the first
chunk of users, scaling roughly with active workers and DB size.

---

## 13. Migration from the prototype, roadmap & risks

### What carries over directly

The prototype isn't thrown away — its **product logic is the crown jewel**.
`parser.py` (amount/category/IOU/person extraction) becomes a shared library used
by the workers verbatim. The DB schema generalizes by adding `user_id`. The IOU
balance math, insights generation, and the dashboard's SVG chart components all
port over. What changes is *plumbing*: polling → webhooks, single SQLite file →
multi-tenant Postgres, `config.json` → per-user settings rows, `data.js` →
authenticated API.

### Phased roadmap

**Phase 0 — Foundations (MVP).** Accounts + auth, the BYO-token connect wizard
with KMS-encrypted storage, webhook ingress + one queue + workers, multi-tenant
`txns`, core logging + IOU + `/total`/`/owed`, and a basic hosted dashboard. One
region, modest scale. *Goal: a stranger can sign up and use it end-to-end.*

**Phase 1 — Product depth.** Budgets, recurring bills, scheduled summaries,
edit/search, CSV/XLSX export, settings UI, and Stripe billing with plan gating.

**Phase 2 — Scale hardening.** Queue + DLQ tuning, worker autoscaling on lag, DB
read replicas + `txns` partitioning, the webhook reconciler, full observability,
and load testing to a target (e.g. 10k active bots).

**Phase 3 — Differentiation.** White-label bot branding, shared/household
ledgers and bill-splitting, mobile-friendly PWA, receipt-photo OCR, and optional
bank/UPI import.

### Key risks & open questions

The biggest risk is **token custody** — get §6 wrong and it's a breach, so it
deserves a security review before launch. **Onboarding friction** is the product
risk of BYO-token (the BotFather dance); the wizard mitigates it, and offering a
shared bot later (the option we set aside) remains the escape hatch if conversion
suffers. Open questions to settle before Phase 0: pricing and free-tier limits,
data residency/region, whether to support group chats, and build-vs-buy on auth.

---

*End of design v0.1. Next step on request: a Phase-0 repo scaffold (FastAPI +
Postgres + KMS token vault + webhook ingress) wiring these pieces into runnable
code.*

