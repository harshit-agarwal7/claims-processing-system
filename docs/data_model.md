# Claims Processing System — Data Model

---

## Domain Entities

### Member
| Attribute | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `name` | str | |
| `date_of_birth` | date | |
| `email` | str | unique |
| `phone` | str | nullable |
| `created_at` | datetime | |

---

### Provider
| Attribute | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `name` | str | individual or facility |
| `npi` | str | National Provider Identifier, unique |
| `provider_type` | enum | `individual`, `facility` |
| `created_at` | datetime | |

---

### Plan
| Attribute | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `name` | str | |
| `deductible` | Decimal(10,2) | fixed per-period amount |
| `created_at` | datetime | |

Plan is a **template** — no member-specific data lives here. When a plan changes (e.g. yearly update), a new `Plan` row is created; existing policies remain tied to the original plan.

---

### CoverageRule
| Attribute | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `plan_id` | FK → Plan | |
| `cpt_code` | str | e.g. `99213` |
| `is_covered` | bool | |
| `coverage_percentage` | Decimal(5,4) | 0.0–1.0; e.g. `0.8000` |
| `created_at` | datetime | |

**Unique constraint:** `(plan_id, cpt_code)`. A CPT code absent from this table → denied (not covered).

---

### Policy
| Attribute | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `member_id` | FK → Member | |
| `plan_id` | FK → Plan | |
| `start_date` | date | |
| `end_date` | date | |
| `status` | enum | `active`, `expired`, `cancelled` |
| `created_at` | datetime | |

**Constraint:** A member may have only one `active` policy at a time (partial unique index on `member_id` where `status = active`).

---

### Accumulator
| Attribute | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `member_id` | FK → Member | |
| `policy_id` | FK → Policy | defines the period |
| `deductible_met` | Decimal(10,2) | running total, starts at `0.00` |
| `updated_at` | datetime | |

**Unique constraint:** `(member_id, policy_id)`. Resets (new row) when policy period changes.

---

### Claim
| Attribute | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `member_id` | FK → Member | |
| `policy_id` | FK → Policy | policy active at date_of_service |
| `provider_id` | FK → Provider | |
| `date_of_service` | date | must fall within policy period |
| `status` | enum | see state machine below |
| `review_type` | enum | `auto` (initial), `manual` (post-dispute) |
| `submitted_at` | datetime | |
| `dispute_count` | int | 0 or 1; enforces one-dispute rule |
| `updated_at` | datetime | |

---

### ClaimStatusHistory
| Attribute | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `claim_id` | FK → Claim | |
| `from_status` | enum | nullable for initial `submitted` |
| `to_status` | enum | |
| `transitioned_at` | datetime | |
| `note` | str | optional, e.g. "dispute submitted" |

Append-only. Never mutated — provides full audit trail per AC §3.

---

### LineItem
| Attribute | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `claim_id` | FK → Claim | |
| `diagnosis_code` | str | ICD-10, e.g. `M54.5` |
| `procedure_code` | str | CPT, e.g. `99213` |
| `billed_amount` | Decimal(10,2) | provider's charge; adjudication basis |
| `adjudication_status` | enum | `pending`, `approved`, `denied` |

On re-adjudication after a dispute, `adjudication_status` is reset to `pending` before the rules engine runs again.

---

### AdjudicationResult
| Attribute | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `line_item_id` | FK → LineItem | |
| `revision` | int | starts at 1; increments on re-adjudication |
| `is_covered` | bool | |
| `applied_to_deductible` | Decimal(10,2) | portion of billed amount applied toward deductible |
| `plan_pays` | Decimal(10,2) | |
| `member_owes` | Decimal(10,2) | |
| `explanation` | text | human-readable, references rule applied |
| `adjudicated_at` | datetime | |

**Unique constraint:** `(line_item_id, revision)`. Re-adjudication appends a new row; original results are never mutated. The highest revision per `line_item_id` is the current result.

---

### Dispute
| Attribute | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `claim_id` | FK → Claim | **one-to-one** (at most one per claim) |
| `reason` | text | member's stated reason |
| `reviewer_note` | text | nullable; human reviewer's findings/decision |
| `submitted_at` | datetime | |
| `status` | enum | `pending`, `resolved` |

---

## Relationships

```
Member ──< Policy >── Plan
                 │
                 └──< CoverageRule (cpt_code, coverage_percentage)

Member ──< Accumulator (one per policy period)
Policy ──< Accumulator

Member ──< Claim >── Policy
                     Claim >── Provider
                     Claim ──< LineItem ──< AdjudicationResult (revision-based)
                     Claim ──< ClaimStatusHistory
                     Claim ──── Dispute (0..1)
```

Key cardinalities:

| Relationship | Cardinality |
|---|---|
| Member → Policies | 1 : N (one active at a time) |
| Plan → Policies | 1 : N |
| Plan → CoverageRules | 1 : N |
| Policy → Accumulator | 1 : 1 (per period) |
| Member → Claims | 1 : N |
| Claim → LineItems | 1 : N (at least 1) |
| LineItem → AdjudicationResults | 1 : N (revision-based; highest revision is current) |
| Claim → ClaimStatusHistory | 1 : N |
| Claim → Dispute | 1 : 0..1 |

---

## State Machines

### Claim Status

```
                   ┌─────────────────────────────────────┐
                   │ [dispute, dispute_count == 0]        │
                   ▼                                      │
submitted ──► under_review ──► approved ──► paid         │
                   │                                      │
                   ├──► denied ──────────────────────────►┤
                   │                                      │
                   └──► partially_approved ──► paid ──────┘
```

| From | To | Trigger | Guard |
|---|---|---|---|
| `submitted` | `under_review` | adjudication begins (`review_type=auto`) | — |
| `under_review` | `approved` | adjudication complete | all line items `approved` |
| `under_review` | `denied` | adjudication complete | all line items `denied` |
| `under_review` | `partially_approved` | adjudication complete | mixed `approved`/`denied` |
| `approved` | `paid` | payment issued | — |
| `partially_approved` | `paid` | payment issued | — |
| `denied` | `under_review` | dispute submitted (`review_type=manual`) | `dispute_count == 0` |
| `partially_approved` | `under_review` | dispute submitted (`review_type=manual`) | `dispute_count == 0` |

**Terminal states:** `paid` (normal path), `denied` after exhausting dispute (`dispute_count == 1`).

**Derived rule:** Claim status is never set directly — it is computed from `LineItem.adjudication_status` values after each adjudication run.

**`review_type` distinction:** When `review_type=auto` the system adjudicates immediately on entering `under_review`. When `review_type=manual` (post-dispute) the claim waits for a human reviewer to check coverage rule configuration before re-adjudication is triggered.

---

### LineItem Adjudication Status

```
pending ──► approved
        └──► denied
```

| From | To | Trigger |
|---|---|---|
| `pending` | `approved` | CPT code covered + `date_of_service` within policy period |
| `pending` | `denied` | CPT code absent/not covered, or service outside policy period |

On re-adjudication after a dispute, `adjudication_status` is reset to `pending` and a new `AdjudicationResult` row (next revision) is created.

---

### Policy Status

```
active ──► expired
       └──► cancelled
```

| From | To | Trigger |
|---|---|---|
| `active` | `expired` | `end_date < today` (time-based) |
| `active` | `cancelled` | manual admin action |

Both `expired` and `cancelled` are terminal.

---

## Design Notes

1. **Deductible concurrency** (AC §8): The `Accumulator` update and the adjudication that reads it must happen in the same DB transaction to prevent double-spend under concurrent submissions.
2. **Claim status derivation**: A DB view or a computed property on `Claim` that aggregates `LineItem.adjudication_status` removes any risk of the stored status diverging from the actual line item outcomes.
3. **Dispute re-adjudication**: Re-adjudication appends new `AdjudicationResult` rows (incrementing `revision`) rather than mutating existing ones. The highest `revision` per `line_item_id` is the current result. Original decisions are preserved for audit.
4. **Monetary precision**: Store all amounts as `NUMERIC(10, 2)` in SQLite (mapped to `Decimal` in Python). Never use `float`.
