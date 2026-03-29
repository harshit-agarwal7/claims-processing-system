# Claims Processing System

An insurance claims processing system that handles claim submission, coverage adjudication, lifecycle tracking, and dispute resolution.

## Overview

Members submit healthcare claims for reimbursement. The system evaluates each claim against the member's active policy, applies deductible and coinsurance rules per line item, and tracks the claim through its full lifecycle.

**Key entities:**

- **Member** — the insured person
- **Provider** — healthcare professional or facility (identified by NPI)
- **Plan** — template defining coverage rules, deductible, and coinsurance percentages
- **Policy** — a member's active instance of a plan with a policy period
- **Claim** — a reimbursement request containing one or more line items
- **LineItem** — a single billed service (CPT procedure code, ICD-10 diagnosis code, billed amount)

## Features

- Claim submission with one or more line items
- Line-item adjudication: deductible tracking + coinsurance calculation
- Claim lifecycle state machine: `submitted` → `under_review` → `approved` / `denied` / `partially_approved` → `paid`
- One-time dispute mechanism with re-adjudication
- Human-readable explanation for every adjudication decision
- Web UI: member dashboard, claim detail view, admin panel
- REST API (`/api/*`)

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.13 |
| Backend API | Flask |
| Database | SQLite |
| ORM | Flask-SQLAlchemy |
| Migrations | Flask-Migrate (Alembic) |
| Frontend | Vanilla JavaScript |
| Tooling | uv, ruff |

## Project Structure

```
claims-processing-system/
├── app/
│   ├── __init__.py          # Flask app factory
│   ├── models.py            # ORM models
│   ├── extensions.py        # SQLAlchemy + Migrate setup
│   ├── errors.py            # Custom errors & handlers
│   ├── routes/              # API blueprints (members, providers, plans, policies, claims)
│   ├── services/            # Business logic (adjudication, claims, disputes)
│   └── static/              # Frontend (HTML, CSS, JS)
├── tests/
│   ├── unit/                # Unit tests for services
│   └── integration/         # API integration tests
├── config/
│   └── settings.py          # Config classes
├── migrations/              # Alembic migration files
└── docs/                    # Domain concepts, acceptance criteria, decisions
```

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager

## Setup & Run

```bash
# 1. Install dependencies (creates .venv automatically)
uv sync

# 2. Apply database migrations
uv run flask --app app:create_app db upgrade

# 3. Start the development server
uv run flask --app app:create_app run
```

The app is available at **http://127.0.0.1:5000**.

| Path | Description |
|---|---|
| `/` | Member dashboard — look up members and view their claims |
| `/claim` | Claim detail — adjudication results and dispute submission |
| `/admin` | Admin panel — manage plans, policies, and disputes |
| `/api/*` | REST API |

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///claims.db` | SQLite database file path |

Create a `.env` file in the project root to override defaults:

```
DATABASE_URL=sqlite:///custom.db
```

## Running Tests

```bash
uv run pytest                    # all tests
uv run pytest tests/unit/        # unit tests only
uv run pytest tests/integration/ # integration tests only
```

## Code Quality

```bash
uv run ruff format .   # auto-format
uv run ruff check .    # lint
uv run mypy app/       # type check
```

## Documentation

- [`docs/domain-concepts.md`](docs/domain-concepts.md) — domain model, adjudication math, claim lifecycle
- [`docs/acceptance-criteria.md`](docs/acceptance-criteria.md) — functional requirements and scope
- [`docs/decisions.md`](docs/decisions.md) — design decisions, assumptions, and out-of-scope items
