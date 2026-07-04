# Running Jasmin Platform locally (for reviewers)

A self-contained, Docker-based setup to get the app running on your machine so
you can click through it. Everything (database, backend, frontend, mail) runs
in containers — you do **not** need Python, Node, or Postgres installed.

## 1. Prerequisites

- **Docker Desktop** (or Docker Engine) with **Compose v2** — check with
  `docker compose version`.
- **git**, and `make`.
- ~3 GB free disk. The first build takes a few minutes; later starts are fast.

## 2. Get the code + dev config

```bash
git clone <REPO_URL> jasmin-platform
cd jasmin-platform
cp .env.dev.example .env.dev
```

The dev defaults in `.env.dev` work out of the box — there are no secrets to
fill in for a local review.

## 3. Map the tenant hostnames

The platform is multi-tenant and resolves the tenant from the **subdomain**, so
you reach a tenant via `test.localhost`, not bare `localhost`. macOS/Linux don't
auto-resolve `*.localhost`, so add these to `/etc/hosts` (once):

```bash
sudo sh -c 'printf "127.0.0.1 test.localhost\n127.0.0.1 marillen.localhost\n" >> /etc/hosts'
```

## 4. Start everything

```bash
make dev-up
```

This builds the images (first run only) and starts Postgres, Redis, the Django
backend, the Vite frontend, an nginx gateway, and MailHog. On startup it
**automatically runs migrations and seeds a ready-to-use test tenant** with
logins — so there's nothing else to set up.

Wait until the backend logs show `Starting Django dev server ...`. Watch logs
any time with `make dev-logs`.

## 5. Log in

Open **http://test.localhost:3000** and sign in:

| Role         | Email                           | Password   |
| ------------ | ------------------------------- | ---------- |
| **Admin**    | `admin@test.localhost`          | `Test-Test-2026` |
| Member       | `test-member@example.com`       | `Test-Test-2026` |
| Customer     | `test-customer@example.com`     | `Test-Test-2026` |
| Staff        | `test-staff@example.com`        | `Test-Test-2026` |
| Office       | `test-office@example.com`       | `Test-Test-2026` |
| Staff+Member | `test-staff-member@example.com` | `Test-Test-2026` |

Start with **Admin** for the full picture.

## Other URLs

| What                         | URL                            |
| ---------------------------- | ------------------------------ |
| Tenant app                   | http://test.localhost:3000     |
| Outgoing email (MailHog)     | http://localhost:8025          |
| Backend API + docs           | http://localhost:8000/api/docs |
| Super-admin / platform (opt) | http://marillen.localhost:3000 |

- **MailHog** catches every email the app sends (invitations, password resets,
  …) — nothing leaves your machine. Check it to grab links the UI would email.
- **Super-admin** is optional (tenant management). It needs its own account:
  `make dev-bash`, then `python manage.py createsuperadmin`.

## Handy commands

| Command          | Does                                                      |
| ---------------- | --------------------------------------------------------- |
| `make dev-logs`  | Tail all container logs                                   |
| `make dev-down`  | Stop the stack (keeps the database)                       |
| `make dev-reset` | Wipe the database and restart fresh (re-seeds the tenant) |
| `make dev-seed`  | Re-seed the test tenant manually                          |
| `make dev-bash`  | Open a shell in the backend container                     |

## Seeding the base data

When setting up a tenant from scratch (or after a `make dev-reset`), fill in the
core configuration **in this order**. Each step builds on the entities created in
the ones before it, so working top-to-bottom means you always have something to
link to — jumping ahead leaves you with empty dropdowns.

1. **Create the share types and their sizes** — (http://test.localhost:3000/configuration/subscriptions)
   (`ConfigurationSubscriptions`).
   Define every share type the CSA offers (e.g. harvest share, bread share) along
   with its size variations (e.g. S / M / L). These are the products members
   subscribe to, and everything downstream — forecasts, planning, packing,
   invoicing — is built on top of them, so they come first.

2. **Create the delivery days** — (http://test.localhost:3000/configuration/time-management)
   (`ConfigurationTimeManagement`).
   Set up the weekly days on which shares are handed out. They define the rhythm
   of the season and are referenced by stations, tours, and the harvest/packing
   lists, so they need to exist before any of those.

3. **Fill the master lists** — the produce and the pickup points:
   - **Share articles** — the actual goods that make up a share (vegetables,
     bread, …) — in (http://test.localhost:3000/commissioning/list-harvest-share-articles) (`ListShareArticles`).
   - **Delivery stations** — the physical points where members collect their
     shares — in _List Delivery Stations_ (`ListDeliveryStation`).

4. **Assign delivery days to each station** — via the station modal in
   (http://test.localhost:3000/commissioning/list-delivery-stations)
   (`ListDeliveryStation` → modal).
   A station only operates on certain delivery days; linking the two tells the
   system which station is active on which day (this is what the harvest/packing
   and station-overview screens scope by).

5. **Assign the stations to tours** — http://test.localhost:3000/commissioning/delivery-tours
   Group the stations into the routes a driver actually takes. Tours drive the
   per-tour breakdowns shown in the packing list and the station overview, so
   they come last, once every station exists and has its delivery days.



## Terminology

The `Share*` family is the #1 source of naming confusion. Two axes cause it:
(1) **`Share` vs `CoopShare` are unrelated models** — `Share` is a weekly
produce delivery; `CoopShare` is a legal capital share (Geschäftsanteil). Never
conflate them (function names use `share` vs `coop_share` deliberately).
(2) **Type → Variation → Share → Content is a containment chain**, each level a
narrower scope. Everything below lives in `apps/commissioning/models/`.

| Term | Model | One-liner |
|------|-------|-----------|
| **ShareOption** | `shares.py` enum (`ShareOption`) | Hardcoded produce categories (`HARVEST_SHARE`, `OIL_SHARE`, …). Extended only from code, never per-tenant. |
| **ShareType** | `shares.py:49` (TimeBound) | A time-bound *kind* of share offering, e.g. Ernte-Anteil (harvest), Honig-Anteil (honey). One open per `ShareOption`. |
| **ShareTypeVariation** | `shares.py:205` (TimeBound) | A *size* child of a ShareType, e.g. "Ernte-Anteil S". This is what a member actually subscribes to and what gets priced. |
| **Subscription** | `members.py:584` (TimeBound) | A member's time-bound agreement to receive one ShareTypeVariation (`valid_from → valid_until`; trial / term / renewal chain). Links Member ↔ Variation. |
| **Share** | `shares.py:579` | One **weekly delivery instance**: a `(year, delivery_week, delivery_day, share_type_variation)` row. Purely operational; no member link. |
| **ShareContent** | `shares.py:734` | The produce line(s) for one Share **at one delivery station** — "2 kg spinach S at Station A, W23". Finalizable + archivable. |
| **ShareDelivery** | `shares.py:912` | Per-member confirm/skip record for a Share: joker (skip), donation-joker, opt-in state. Links Subscription ↔ Share. |
| **CoopShare** | `members.py:384` | **Legal/financial, NOT produce.** A cooperative equity share (Geschäftsanteil, GenG) — `amount_of_coop_shares` × `value_one_coop_share`, with statutory retention + payback on exit. Belongs to a Member. |

**Hierarchy (policy → execution):**

```
ShareOption (enum)
└─ ShareType                "harvest share, valid 2024"
   └─ ShareTypeVariation    "harvest share S, valid 2024"   ← members subscribe to THIS
      ├─ Subscription       "Alice: harvest-S, 2024"
      │  └─ ShareDelivery   "Alice, W23: deliver? joker? opted-in?"
      └─ Share              "W23/2024, harvest-S, Saturday"  ← one row per week
         └─ ShareContent    "W23 harvest-S @ Station A: 2kg spinach S"
```

**Share vs CoopShare (the critical one):** `Share`/`ShareContent`/`ShareDelivery`
answer *"what produce is delivered this week, and to whom?"* — ephemeral, weekly,
archived as the season passes. `CoopShare` answers *"how much of the co-op does
this member own, and when is it refundable?"* — persistent capital that a member
must hold a minimum of to be active, divested only on cancellation + payback.
They share a prefix and nothing else.
