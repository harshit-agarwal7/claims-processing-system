# Claims Processing System — Implementation Plan

## Context

Building a complete insurance claims processing system from scratch. The system allows members to submit claims for reimbursement, auto-adjudicates them against plan coverage rules and deductible accumulators, tracks the claim through a lifecycle state machine, and supports a single-round dispute mechanism. The stack is Flask + SQLite + SQLAlchemy + Vanilla JS.

---

## Directory Structure

```
claims-processing-system/
├── app/
│   ├── __init__.py                  # create_app() factory
│   ├── extensions.py                # db = SQLAlchemy()
│   ├── models.py                    # All enums and models in one file
│   ├── routes/
│   │   ├── __init__.py              # register_routes(app)
│   │   ├── members.py               # Blueprint /api/members
│   │   ├── providers.py             # Blueprint /api/providers
│   │   ├── plans.py                 # Blueprint /api/plans
│   │   ├── policies.py              # Blueprint /api/policies
│   │   └── claims.py                # Blueprint /api/claims (includes disputes + payments)
│   └── services/
│       ├── __init__.py
│       ├── claim_service.py         # Claim submission + retrieval
│       ├── adjudication_engine.py   # Core adjudication logic (transactional)
│       └── dispute_service.py       # Dispute submission + re-adjudication trigger
├── tests/
│   ├── conftest.py                  # App, db, client, seed-data fixtures
│   ├── unit/
│   │   ├── test_adjudication_engine.py  # Math + deductible tracking (mirrors adjudication_engine.py)
│   │   ├── test_claim_service.py        # Claim submission validation (mirrors claim_service.py)
│   │   ├── test_dispute_service.py      # Dispute/re-adjudication guards (mirrors dispute_service.py)
│   │   └── test_state_machine.py        # Cross-service state transition coverage
│   └── integration/
│       ├── test_members_api.py
│       ├── test_plans_api.py
│       ├── test_policies_api.py
│       ├── test_claims_api.py
│       └── test_disputes_api.py
├── config/
│   └── settings.py                  # Config, TestingConfig classes
├── migrations/                       # Flask-Migrate managed; do not edit by hand
├── app/static/
│   ├── index.html                   # Dashboard (claim list + submission)
│   ├── claim.html                   # Claim detail page
│   ├── admin.html                   # Admin: plans, policies, re-adjudication
│   ├── css/styles.css
│   └── js/
│       ├── api.js                   # Fetch wrapper
│       ├── dashboard.js
│       ├── claim-detail.js
│       └── admin.js
├── pyproject.toml
└── .env.example
```

## Phase 1: Project Scaffolding

### `pyproject.toml`
```toml
[project]
name = "claims-processing-system"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "flask>=3.1.0",
    "flask-sqlalchemy>=3.1.1",
    "flask-migrate>=4.0.7",
]

[tool.uv]
dev-dependencies = [
    "pytest>=8.0.0",
    "pytest-flask>=1.3.0",
    "mypy>=1.13.0",
    "ruff>=0.8.0",
]

[tool.ruff]
target-version = "py313"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP"]

[tool.mypy]
python_version = "3.13"
strict = true
plugins = ["sqlalchemy.ext.mypy.plugin"]
```

### `config/settings.py`
```python
import os

class Config:
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///claims.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
```

### `app/extensions.py`
```python
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

db: SQLAlchemy = SQLAlchemy()
migrate: Migrate = Migrate()
```

### `app/__init__.py` — App factory
```python
import logging
from decimal import Decimal

from flask import Flask
from flask.json.provider import DefaultJSONProvider
from config.settings import Config
from .extensions import db, migrate
from .routes import register_routes
from .errors import register_error_handlers


class DecimalJSONProvider(DefaultJSONProvider):
    def default(self, o: object) -> object:
        if isinstance(o, Decimal):
            return str(o)
        return super().default(o)


def create_app(config_object: object = Config) -> Flask:
    app = Flask(__name__, static_folder="static")
    app.json_provider_class = DecimalJSONProvider
    app.config.from_object(config_object)
    db.init_app(app)
    migrate.init_app(app, db)
    register_routes(app)
    register_error_handlers(app)
    return app
```

## Phase 2: Models

### `app/models.py`

All enums and models live in this single file. At 12 models this is manageable (~500 lines), avoids circular import issues entirely (all classes are in scope simultaneously so relationships use direct class references, not strings), and guarantees every model is registered before `db.create_all()` is called.

**Enums** — defined at the top of the file:

```python
import enum

class ProviderType(enum.Enum):
    individual = "individual"
    facility = "facility"

class PolicyStatus(enum.Enum):
    active = "active"
    expired = "expired"
    cancelled = "cancelled"

class ClaimStatus(enum.Enum):
    submitted = "submitted"
    under_review = "under_review"
    approved = "approved"
    denied = "denied"
    partially_approved = "partially_approved"
    paid = "paid"

class ReviewType(enum.Enum):
    auto = "auto"
    manual = "manual"

class LineItemStatus(enum.Enum):
    pending = "pending"
    approved = "approved"
    denied = "denied"

class DisputeStatus(enum.Enum):
    pending = "pending"
    resolved = "resolved"
```

**Model classes** — defined below the enums in this order (respects FK dependencies top-down):
`Member` → `Provider` → `Plan` → `CoverageRule` → `Policy` → `Accumulator` → `Claim` → `ClaimStatusHistory` → `AdjudicationResult` → `LineItem` → `Dispute` → `Payment`

> **Circular FK note:** `LineItem.latest_result_id` → `AdjudicationResult` and `AdjudicationResult.line_item_id` → `LineItem` form a mutual FK reference. Resolve with `use_alter=True` on `LineItem.latest_result_id` so SQLAlchemy emits it as a post-creation `ALTER TABLE` rather than failing on the forward reference.

### Model Specifications

All UUIDs stored as `String(36)` with `default=lambda: str(uuid.uuid4())`.
All monetary amounts stored as `Numeric(10, 2)` mapped to Python `Decimal`.
All models carry `deleted_at: Mapped[datetime | None]` except `ClaimStatusHistory` and `AdjudicationResult` (append-only, no soft delete).

**Member** — `id, name, date_of_birth(Date), email(unique), phone(nullable), created_at, deleted_at`
Relationships: `policies`, `claims`, `accumulators`

**Provider** — `id, name, npi(unique), provider_type(ProviderType enum), created_at, deleted_at`

**Plan** — `id, name, deductible(Numeric 10,2), created_at, deleted_at`
Relationships: `coverage_rules`, `policies`

**CoverageRule** — `id, plan_id(FK), cpt_code(str), is_covered(bool), coverage_percentage(Numeric 5,4), created_at, deleted_at`
UniqueConstraint: `(plan_id, cpt_code)` on active rules only — enforced at service layer since SQLite lacks partial indexes without triggers.

**Policy** — `id, member_id(FK), plan_id(FK), start_date(Date), end_date(Date), status(PolicyStatus), created_at, deleted_at`
Constraint: at most one `active` policy per member — enforced at service layer.
Relationships: `member`, `plan`, `claims`, `accumulator`

**Accumulator** — `id, member_id(FK), policy_id(FK unique), deductible_met(Numeric 10,2 default 0.00), created_at, updated_at, deleted_at`
UniqueConstraint: `(member_id, policy_id)`. One row per policy period per member.

**Claim** — `id, member_id(FK), policy_id(FK), provider_id(FK), date_of_service(Date), status(ClaimStatus default submitted), review_type(ReviewType default auto), submitted_at, updated_at, deleted_at`
Relationships: `member`, `policy`, `provider`, `line_items`, `status_history`, `dispute`, `payment`

**ClaimStatusHistory** — `id, claim_id(FK), from_status(ClaimStatus nullable), to_status(ClaimStatus), transitioned_at, note(nullable)`
No `deleted_at`. Append-only. Full audit trail per AC §3.

**LineItem** — `id, claim_id(FK), diagnosis_code(str), cpt_code(str), billed_amount(Numeric 10,2), adjudication_status(LineItemStatus default pending), latest_result_id(FK → AdjudicationResult nullable), updated_at, deleted_at`
`latest_result_id` is a foreign key back to `AdjudicationResult` — avoids correlated subqueries on reads (Design Note §3).

**AdjudicationResult** — `id, line_item_id(FK), revision(int), is_covered(bool), applied_to_deductible(Numeric 10,2), plan_pays(Numeric 10,2), member_owes(Numeric 10,2), explanation(Text), adjudicated_at`
UniqueConstraint: `(line_item_id, revision)`. No `deleted_at`. Append-only. Re-adjudication adds revision N+1, never mutates.

**Dispute** — `id, claim_id(FK unique — one per claim), reason(Text), reviewer_note(Text nullable), submitted_at, resolved_at(nullable), status(DisputeStatus default pending), deleted_at`
One-dispute rule enforced by presence of this row, not a counter on Claim (Design Note §5 from domain-model).

**Payment** — `id, claim_id(FK unique), amount(Numeric 10,2), paid_at, deleted_at`
Created automatically when claim transitions to `paid`.

---

## Phase 3: Error Handling

### `app/errors.py`

```python
class ClaimsError(Exception):
    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

class BadRequestError(ClaimsError):  # 400, "BAD_REQUEST"   — malformed input, missing/invalid fields
class NotFoundError(ClaimsError):    # 404, "NOT_FOUND"
class ValidationError(ClaimsError):  # 422, "VALIDATION_ERROR" — valid input, business rule violation
class ConflictError(ClaimsError):    # 409, "CONFLICT"      — operation invalid for current resource state
class ForbiddenError(ClaimsError):   # 403, "FORBIDDEN"
```

**When to use each:**
- `BadRequestError` (400): missing required fields, zero/negative billed amounts, empty line_items list — the request itself is malformed.
- `ValidationError` (422): structurally valid request that fails a business rule — e.g. no active policy covers the date of service, date of service outside policy period.
- `ConflictError` (409): the resource exists and is valid, but its current state prevents the operation — e.g. disputing a claim that is already disputed, operating on a claim in the wrong status.

`register_error_handlers(app)` handles all `ClaimsError` subclasses and generic Flask 404/405/500, always returning:
```json
{"error": "ERROR_CODE", "message": "Human-readable message"}
```

---

## Phase 4: Adjudication Engine (Critical — TDD)

### `app/services/adjudication_engine.py`

**Contract:** `AdjudicationEngine.run(claim_id: str) -> Claim`

All DB writes occur in a **single transaction** (Design Note §1 from domain-model):

1. Load `Accumulator` for the claim's policy
2. Transition claim `submitted → under_review`, `INSERT ClaimStatusHistory`; log at INFO
3. For each active `LineItem` (ordered by id for determinism):
   - Reset: `adjudication_status = pending`, `latest_result_id = None`
   - Lookup `CoverageRule` for `(plan_id, cpt_code)` where `deleted_at IS NULL` using `.one_or_none()` — raises if duplicate active rules exist
   - If no rule or `is_covered=False` → **denied result**
   - Else → **approved result**: apply adjudication math with `effective_deductible_remaining = plan.deductible - accumulator.deductible_met - total_consumed_this_run`
   - `INSERT AdjudicationResult` (revision = max existing + 1, or 1 if none)
   - `db.session.flush()` to get result.id
   - Update `LineItem.latest_result_id`, `adjudication_status`; log adjudication decision at INFO
4. `UPDATE Accumulator.deductible_met += total_deductible_consumed`
5. Derive `ClaimStatus` from line item outcomes:
   - All approved → `approved` | All denied → `denied` | Mix → `partially_approved`
6. Transition `under_review → <final_status>`, `INSERT ClaimStatusHistory`; log at INFO
7. If `approved`: transition to `paid`, `INSERT ClaimStatusHistory`; create `Payment` only if `sum(plan_pays) > 0.00` (skip when entire billed amount was applied to deductible)
8. If `partially_approved` AND resolved `Dispute` exists (re-adjudication path): create `Payment`, transition to `paid`
9. `db.session.commit()`

**Adjudication Math (per line item):**
```python
remaining = plan.deductible - accumulator.deductible_met - total_consumed_so_far
applied_to_deductible = min(billed_amount, max(Decimal("0.00"), remaining))
amount_after_deductible = billed_amount - applied_to_deductible
plan_pays = (amount_after_deductible * coverage_percentage).quantize(Decimal("0.01"), ROUND_HALF_UP)
member_owes = (billed_amount - plan_pays).quantize(Decimal("0.01"), ROUND_HALF_UP)
```

**Explanation generation:** Built deterministically inline — no external calls, no failure modes:
```python
# Denied
explanation = f"Service {cpt_code} is not covered under your plan."
# Approved
explanation = (
    f"Service {cpt_code} covered at {coverage_percentage * 100:.4g}%. "
    f"${applied_to_deductible} applied to deductible. "
    f"Plan pays ${plan_pays}; you owe ${member_owes}."
)
```

**Logging (AC §9):** `logger = logging.getLogger(__name__)` at module level.
```python
# After each ClaimStatusHistory insert:
logger.info("claim %s transitioned %s → %s", claim.id, from_status.value, to_status.value)

# After each AdjudicationResult insert:
logger.info(
    "claim %s line_item %s cpt=%s covered=%s applied_deductible=%s plan_pays=%s",
    claim.id, line_item.id, cpt_code, is_covered, applied_to_deductible, plan_pays,
)
```
Same pattern in `claim_service.py` and `dispute_service.py` — log at INFO on state changes, ERROR (with `exc_info=True`) before re-raising any caught exception.

---

## Phase 5: Services

### `app/services/claim_service.py`

**`submit_claim(data: dict) -> Claim`**:
1. Validate required fields: `member_id`, `provider_id`, `date_of_service` (must be a valid ISO 8601 date string — raise **400** `BadRequestError` if unparseable), `line_items` (non-empty; each must have `diagnosis_code`, `cpt_code`, `billed_amount > 0`) — **400** `BadRequestError` on any failure
2. Load Member — 404 if not found or soft-deleted
3. Find Policy where `member_id` matches, `status=active`, `start_date <= date_of_service <= end_date` — **422** `ValidationError` if none ("No active policy covers this date of service")
4. Load Provider — 404 if not found
5. Create `Claim(status=submitted, review_type=auto)` + `LineItem` rows
6. Create `ClaimStatusHistory(from_status=None, to_status=submitted)`
7. `db.session.flush()` — assigns IDs without committing; adjudication engine owns the single commit
8. Call `AdjudicationEngine().run(claim.id)` — runs adjudication and commits the entire transaction atomically
9. Return refreshed claim

> `Accumulator` is created by `POST /api/policies` when the policy is created. `submit_claim` does not create or upsert it — the engine loads the existing row in step 1. A missing accumulator is a data integrity error (policy was created incorrectly), not a recoverable condition.

### `app/services/dispute_service.py`

**`submit_dispute(claim_id: str, reason: str) -> Dispute`**:
1. Load Claim — 404 if not found
2. Guard: `claim.status` must be `denied` or `partially_approved` — **409** `ConflictError` otherwise ("Cannot dispute a claim with status {status}")
3. Guard: no existing `Dispute` row for this claim — **409** `ConflictError` if one exists ("Claim has already been disputed")
4. Create `Dispute(reason=reason, status=pending)`
5. Set `claim.review_type = manual`
6. Transition claim to `under_review`, `INSERT ClaimStatusHistory`
7. Reset all active LineItems: `adjudication_status=pending`, `latest_result_id=None`
8. `db.session.commit()`

**`trigger_readjudication(claim_id: str, reviewer_note: str | None) -> Claim`**:
1. Load Claim — must be `under_review` with `review_type=manual` — **409** `ConflictError` otherwise ("Claim is not awaiting manual review")
2. Load Dispute — 404 if no `Dispute` row exists; **409** `ConflictError` if dispute exists but `status != pending` ("Dispute is already resolved")
3. Update `Dispute.reviewer_note` if provided
4. Set `Dispute.status=resolved`, `Dispute.resolved_at=now()`
5. `db.session.flush()` — no commit; adjudication engine owns the single commit
6. Call `AdjudicationEngine().run(claim.id)` — engine auto-pays if result is `partially_approved` (Dispute already resolved, no further dispute possible)
7. Return refreshed claim

**`accept_payment(claim_id: str) -> Payment`**:
1. Load Claim — must be `partially_approved` — **409** `ConflictError` otherwise ("Cannot accept payment for a claim with status {status}")
2. Guard: no `Dispute` row exists — **409** `ConflictError` if one does ("Dispute already filed; cannot accept partial payment")
3. Create `Payment(amount=sum(plan_pays for approved line items))`
4. Transition claim to `paid`, `INSERT ClaimStatusHistory`
5. `db.session.commit()`

---

## Phase 6: API Routes

All endpoints return `application/json`. Errors: `{"error": "CODE", "message": "..."}`.

| Method | Path | Handler | Response |
|--------|------|---------|----------|
| POST | `/api/members` | create member | 201 |
| GET | `/api/members/<id>` | get member | 200 / 404 |
| GET | `/api/members/<id>/claims` | list member claims (summary) | 200 |
| GET | `/api/members/<id>/policies/active` | get active policy | 200 / 404 |
| POST | `/api/providers` | create provider | 201 |
| GET | `/api/providers/<id>` | get provider | 200 / 404 |
| POST | `/api/plans` | create plan + coverage rules | 201 |
| GET | `/api/plans/<id>` | get plan + active rules | 200 / 404 |
| PUT | `/api/plans/<id>/coverage-rules/<cpt_code>` | upsert rule (soft-delete old, insert new) | 200 |
| DELETE | `/api/plans/<id>/coverage-rules/<cpt_code>` | soft-delete rule | 204 |
| POST | `/api/policies` | create policy (creates Accumulator) | 201 |
| GET | `/api/policies/<id>` | get policy | 200 / 404 |
| POST | `/api/claims` | submit + auto-adjudicate | 201 (full detail) |
| GET | `/api/claims/<id>` | get full claim detail | 200 / 404 |
| POST | `/api/claims/<id>/disputes` | submit dispute | 201 |
| GET | `/api/claims/<id>/dispute` | get dispute | 200 / 404 |
| POST | `/api/claims/<id>/adjudicate` | trigger re-adjudication (reviewer) | 200 |
| POST | `/api/claims/<id>/accept` | accept partial payment | 200 |
| GET | `/api/claims/<id>/payment` | get payment | 200 / 404 |

### Full Claim Detail Response Shape (`GET /api/claims/<id>`)
```json
{
  "id": "...",
  "status": "approved",
  "review_type": "auto",
  "date_of_service": "2026-03-01",
  "submitted_at": "...",
  "updated_at": "...",
  "member": {"id": "...", "name": "Jane Doe"},
  "provider": {"id": "...", "name": "Dr. Smith", "npi": "1234567890"},
  "policy": {"id": "...", "plan_name": "Gold Plan", "deductible": "500.00", "start_date": "...", "end_date": "..."},
  "line_items": [
    {
      "id": "...",
      "diagnosis_code": "M54.5",
      "cpt_code": "99213",
      "billed_amount": "300.00",
      "adjudication_status": "approved",
      "adjudication_result": {
        "is_covered": true,
        "applied_to_deductible": "300.00",
        "plan_pays": "0.00",
        "member_owes": "300.00",
        "explanation": "Service 99213 covered at 80%. $300.00 applied to your deductible. Plan pays $0.00; you owe $300.00.",
        "revision": 1,
        "adjudicated_at": "..."
      }
    }
  ],
  "payment": {"id": "...", "amount": "160.00", "paid_at": "..."},
  "dispute": null,
  "status_history": [
    {"from_status": null, "to_status": "submitted", "transitioned_at": "..."},
    {"from_status": "submitted", "to_status": "under_review", "transitioned_at": "..."},
    {"from_status": "under_review", "to_status": "approved", "transitioned_at": "..."},
    {"from_status": "approved", "to_status": "paid", "transitioned_at": "..."}
  ]
}
```

---

## Phase 7: Tests

### `tests/conftest.py`
```python
@pytest.fixture
def app():
    from config.settings import TestingConfig
    app = create_app(TestingConfig)
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def seed(app):
    """
    Creates and returns a SimpleNamespace with:
      .plan       — Plan(deductible=500.00)
      .rule       — CoverageRule(cpt_code="99213", is_covered=True, coverage_percentage=0.8)
      .member     — Member
      .provider   — Provider
      .policy     — Policy(status=active, covers 2026-01-01 to 2026-12-31)
      .accumulator — Accumulator(deductible_met=0.00)
    """
```

### `tests/unit/test_adjudication_engine.py`

Covers all adjudication math and deductible tracking. Tests call the engine directly against an in-memory DB with seed data.

**Math scenarios:**
| Scenario | billed | deductible | met_before | applied | plan_pays | member_owes |
|---|---|---|---|---|---|---|
| Full deductible remaining | 150 | 500 | 0 | 150 | 0 | 150 |
| Partial deductible remaining | 300 | 500 | 300 | 200 | 80 | 220 |
| Deductible fully met | 200 | 500 | 500 | 0 | 160 | 40 |
| CPT not covered (is_covered=False) | 200 | 500 | 0 | 0 | 0 | 200 |
| CPT absent from plan | 200 | 500 | 0 | 0 | 0 | 200 |
| Multi-item: 3 items, deductible consumed across them | — | 500 | 0 | per-item cumulative | — | — |

**Deductible tracking scenarios:**
- Claim 1 consumes $300 of $500 deductible → `accumulator.deductible_met = $300`
- Claim 2 (same period) applies remaining $200, then coverage kicks in
- New policy period → new `Policy` row → fresh `Accumulator` starts at `$0`; old accumulator unchanged

### `tests/unit/test_claim_service.py`

Covers `claim_service.submit_claim` validation at unit level (no HTTP layer):
- Missing `member_id` → `BadRequestError`
- Missing `line_items` / empty list → `BadRequestError`
- `billed_amount = 0` or negative → `BadRequestError`
- Unknown `member_id` → `NotFoundError`
- Unknown `provider_id` → `NotFoundError`
- `date_of_service` before `policy.start_date` → `ValidationError`
- `date_of_service` after `policy.end_date` → `ValidationError`
- No active policy for member → `ValidationError`
- Valid submission → patch `AdjudicationEngine.run` with `unittest.mock.patch` to no-op; assert returned `Claim.status == submitted`

### `tests/unit/test_dispute_service.py`

Covers `dispute_service` validation at unit level:
- `submit_dispute` on `approved` claim → `ConflictError`
- `submit_dispute` on `paid` claim → `ConflictError`
- `submit_dispute` twice on same claim → `ConflictError`
- `trigger_readjudication` when claim not `under_review` → `ConflictError`
- `trigger_readjudication` when no dispute exists → `NotFoundError`
- `trigger_readjudication` when dispute already resolved → `ConflictError`
- `accept_payment` on `denied` claim → `ConflictError`
- `accept_payment` when dispute already filed → `ConflictError`

### `tests/unit/test_state_machine.py`

Covers full end-to-end state transitions through the engine and dispute service:
- All approved → `approved` → auto `paid`, Payment created
- All denied → `denied`, no Payment
- Mixed → `partially_approved`, no Payment
- `partially_approved` → dispute → `under_review` (review_type=manual)
- `under_review` (manual) → re-adjudicate → `approved` → auto `paid`
- `under_review` (manual) → re-adjudicate → `partially_approved` → auto `paid` (Dispute resolved)
- `denied` → dispute → `under_review` → re-adjudicate → `approved` → `paid`
- Second dispute attempt → `ConflictError`
- Dispute on `approved` claim → `ConflictError`

### `tests/integration/test_claims_api.py`

- `POST /api/claims` happy path → 201, status is `approved`/`denied`/`partially_approved`/`paid`, adjudication_result populated
- Missing `member_id` → **400**
- Unknown `member_id` → 404
- `date_of_service` before `policy.start_date` → **422**
- `date_of_service` after `policy.end_date` → **422**
- `line_items` empty list → **400**
- `billed_amount` = 0 → **400**
- Two sequential claims in same period: deductible correctly carried in second claim

### `tests/integration/test_disputes_api.py`

- `POST /api/claims/<id>/disputes` on `denied` claim → 201, claim now `under_review`
- `POST /api/claims/<id>/disputes` on `partially_approved` → 201
- `POST /api/claims/<id>/disputes` on `approved` → **409**
- `POST /api/claims/<id>/disputes` twice → **409**
- `POST /api/claims/<id>/adjudicate` with no Dispute → 404
- `POST /api/claims/<id>/adjudicate` with pending Dispute → 200, claim reaches new state
- `POST /api/claims/<id>/accept` on `partially_approved` (no dispute) → 200, Payment created, status=`paid`
- `POST /api/claims/<id>/accept` on `partially_approved` (dispute exists) → **409**

---

## Phase 8: Frontend (Vanilla JS)

### `index.html` — Dashboard
- Member ID input + "Load Claims" button
- Claims table: ID (link to detail), date of service, status badge (color-coded), provider name, total billed, plan pays
- "New Claim" button → inline form to submit a claim (member, provider, date, line items with add/remove)

### `claim.html?id=<id>` — Claim Detail
- Claim header: claim ID, status badge, date of service, member name, provider name
- Line items table: CPT code, diagnosis code, billed amount, applied to deductible, plan pays, member owes, status badge, explanation (expandable row)
- Summary row: total plan pays, total member owes
- Payment card (shown if status=`paid`): amount, date paid
- Dispute card (shown if status=`denied` or `partially_approved` and no existing dispute): reason textarea + "Submit Dispute" button
- Re-adjudication card (shown if status=`under_review` and `review_type=manual`): reviewer note textarea + "Trigger Re-adjudication" button
- Accept Payment button (shown if status=`partially_approved` and no dispute)

### `admin.html` — Admin
- Plans panel: create plan (name, deductible), list plans, edit coverage rules per plan
- Providers panel: create provider
- Policies panel: create policy (member, plan, dates)

### `js/api.js` — Fetch Wrapper
```javascript
const BASE = "/api";

async function request(method, path, body = null) {
    const opts = { method, headers: { "Content-Type": "application/json" } };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(BASE + path, opts);
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.message || `HTTP ${res.status}`);
    }
    return res.status === 204 ? null : res.json();
}

export const api = {
    // Members
    createMember: (data) => request("POST", "/members", data),
    getMember: (id) => request("GET", `/members/${id}`),
    getMemberClaims: (id) => request("GET", `/members/${id}/claims`),
    getActivePolicyForMember: (id) => request("GET", `/members/${id}/policies/active`),

    // Providers
    createProvider: (data) => request("POST", "/providers", data),

    // Plans
    createPlan: (data) => request("POST", "/plans", data),
    getPlan: (id) => request("GET", `/plans/${id}`),
    upsertCoverageRule: (planId, cptCode, data) => request("PUT", `/plans/${planId}/coverage-rules/${cptCode}`, data),

    // Policies
    createPolicy: (data) => request("POST", "/policies", data),

    // Claims
    submitClaim: (data) => request("POST", "/claims", data),
    getClaim: (id) => request("GET", `/claims/${id}`),
    submitDispute: (id, reason) => request("POST", `/claims/${id}/disputes`, { reason }),
    adjudicate: (id, reviewerNote) => request("POST", `/claims/${id}/adjudicate`, { reviewer_note: reviewerNote }),
    acceptPayment: (id) => request("POST", `/claims/${id}/accept`),
    getPayment: (id) => request("GET", `/claims/${id}/payment`),
};
```

---

## Implementation Order

| Step | What | Why |
|---|---|---|
| 1 | `pyproject.toml`, `config/settings.py`, `app/extensions.py`, `app/errors.py`, `app/__init__.py` | `errors.py` must exist before `__init__.py` imports it |
| 2 | `app/models.py` — all enums + 12 models | Models before any service or route |
| 3 | `app/routes/__init__.py` (stub); run `flask db init && flask db migrate -m "initial schema" && flask db upgrade` | Establish DB schema via migrations before any service work |
| 4 | `tests/conftest.py` + seed fixture | Test infrastructure before any test |
| 5 | `tests/unit/test_adjudication_engine.py` → `app/services/adjudication_engine.py` | Core logic, TDD |
| 6 | `tests/unit/test_state_machine.py` | Cover full state transition paths through the engine |
| 7 | `tests/unit/test_claim_service.py` → `app/services/claim_service.py` + `tests/integration/test_claims_api.py` + `app/routes/claims.py` | Main claim flow, unit then integration |
| 8 | `tests/unit/test_dispute_service.py` → `app/services/dispute_service.py` + `tests/integration/test_disputes_api.py` | Dispute + re-adjudication flow, unit then integration |
| 9 | Remaining routes (members, providers, plans, policies) + their integration tests | CRUD endpoints |
| 10 | `ruff format`, `ruff check --fix`, `mypy` | Quality gate |
| 11 | Frontend: `static/` pages | UI layer |

---

## Verification

```bash
# Install deps
uv sync

# Database migrations (first time)
uv run flask --app "app:create_app()" db init
uv run flask --app "app:create_app()" db migrate -m "initial schema"
uv run flask --app "app:create_app()" db upgrade

# Apply new migrations after model changes
uv run flask --app "app:create_app()" db migrate -m "<description>"
uv run flask --app "app:create_app()" db upgrade

# Run all tests
uv run pytest tests/ -v

# Type check
uv run mypy app/

# Lint + format
uv run ruff check app/ tests/
uv run ruff format app/ tests/

# Run server
uv run flask --app "app:create_app()" run
```

### End-to-End Smoke Test Scenario

1. Create plan: deductible=$500, CPT 99213 covered at 80%
2. Create member + provider
3. Create policy for member (active, `2026-01-01` to `2026-12-31`)
4. Submit claim with 2 line items (both 99213):
   - Item 1 billed $300: `applied=$300, plan_pays=$0, member_owes=$300`
   - Item 2 billed $400: `applied=$200, amount_after=$200, plan_pays=$160, member_owes=$240`
   - Claim: `status=approved`, `Payment.amount=$160`, `Accumulator.deductible_met=$500`
5. Submit second claim (99213 $200): `applied=$0, plan_pays=$160, member_owes=$40`
6. Submit third claim for uncovered CPT → `status=denied`
7. Dispute denied claim → `status=under_review`, `review_type=manual`
8. `POST /api/claims/<id>/adjudicate` → claim reaches new final state, `AdjudicationResult.revision=2`
9. Attempt second dispute → 409 Conflict
