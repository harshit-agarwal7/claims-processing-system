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
| `deleted_at` | datetime | nullable; soft delete |

---

### Provider
| Attribute | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `name` | str | individual or facility |
| `npi` | str | National Provider Identifier, unique |
| `provider_type` | enum | `individual`, `facility` |
| `created_at` | datetime | |
| `deleted_at` | datetime | nullable; soft delete |

---

### Plan
| Attribute | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `name` | str | |
| `deductible` | Decimal(10,2) | fixed per-period amount |
| `created_at` | datetime | |
| `deleted_at` | datetime | nullable; soft delete |

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
| `deleted_at` | datetime | nullable; soft delete |

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
| `deleted_at` | datetime | nullable; soft delete |

**Constraint:** A member may have only one `active` policy at a time (partial unique index on `member_id` where `status = active`).

---

### Accumulator
| Attribute | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `member_id` | FK → Member | intentionally denormalized from `Policy.member_id`; see Design Note §6 |
| `policy_id` | FK → Policy | defines the period |
| `deductible_met` | Decimal(10,2) | running total, starts at `0.00` |
| `created_at` | datetime | |
| `updated_at` | datetime | |
| `deleted_at` | datetime | nullable; soft delete |

**Unique constraint:** `(member_id, policy_id)`. Resets (new row) when policy period changes.

---

### Claim
| Attribute | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `member_id` | FK → Member | |
| `policy_id` | FK → Policy | policy active at date_of_service |
| `provider_id` | FK → Provider | |
| `date_of_service` | date | must fall within policy period; enforced at application layer |
| `status` | enum | see state machine below; stored, written only by adjudication engine and dispute handler |
| `review_type` | enum | `auto` (initial), `manual` (post-dispute) |
| `submitted_at` | datetime | |
| `updated_at` | datetime | |
| `deleted_at` | datetime | nullable; soft delete |

The one-dispute rule is enforced by checking whether a `Dispute` row exists for the claim, not by a counter on `Claim`.

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

Append-only. Never mutated — provides full audit trail per AC §3. No soft delete.

---

### LineItem
| Attribute | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `claim_id` | FK → Claim | |
| `diagnosis_code` | str | ICD-10, e.g. `M54.5` |
| `cpt_code` | str | CPT, e.g. `99213` |
| `billed_amount` | Decimal(10,2) | provider's charge; adjudication basis |
| `adjudication_status` | enum | `pending`, `approved`, `denied` |
| `latest_result_id` | FK → AdjudicationResult | nullable; updated atomically on each new adjudication; see Design Note §3 |
| `updated_at` | datetime | |
| `deleted_at` | datetime | nullable; soft delete |

On re-adjudication after a dispute, `adjudication_status` is reset to `pending` and `latest_result_id` is cleared before the rules engine runs again.

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

**Unique constraint:** `(line_item_id, revision)`. Re-adjudication appends a new row; original results are never mutated. Append-only. No soft delete.

---

### Dispute
| Attribute | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `claim_id` | FK → Claim | **one-to-one** (at most one per claim) |
| `reason` | text | member's stated reason |
| `reviewer_note` | text | nullable; human reviewer's findings/decision |
| `submitted_at` | datetime | |
| `resolved_at` | datetime | nullable; set when `status` transitions to `resolved` |
| `status` | enum | `pending`, `resolved` |
| `deleted_at` | datetime | nullable; soft delete |

---

### Payment
| Attribute | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `claim_id` | FK → Claim | **one-to-one** |
| `amount` | Decimal(10,2) | sum of `plan_pays` across approved line items |
| `paid_at` | datetime | |
| `deleted_at` | datetime | nullable; soft delete |

Created automatically at the end of the adjudication transaction when claim status resolves to `approved`. For `partially_approved` claims, created when the claim is explicitly accepted or when re-adjudication after a dispute completes and no further dispute is possible.

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
                                LineItem ──── AdjudicationResult (latest_result_id, 0..1)
                     Claim ──< ClaimStatusHistory
                     Claim ──── Dispute (0..1)
                     Claim ──── Payment (0..1)
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
| LineItem → AdjudicationResults | 1 : N (revision-based; `latest_result_id` points to current) |
| Claim → ClaimStatusHistory | 1 : N |
| Claim → Dispute | 1 : 0..1 |
| Claim → Payment | 1 : 0..1 |

---

## State Machines

### Claim Status

```
                   ┌──────────────────────────────────────────┐
                   │ [dispute, no existing Dispute]            │
                   ▼                                           │
submitted ──► under_review ──► approved ──► paid (auto)       │
                   │                                           │
                   ├──► denied ──────────────────────────────►┤
                   │                                           │
                   └──► partially_approved ──► paid ───────────┘
                              │ [dispute, no existing Dispute]
                              └──► under_review
```

| From | To | Trigger | Guard |
|---|---|---|---|
| `submitted` | `under_review` | adjudication begins (`review_type=auto`) | — |
| `under_review` | `approved` | adjudication complete | all line items `approved` |
| `under_review` | `denied` | adjudication complete | all line items `denied` |
| `under_review` | `partially_approved` | adjudication complete | mixed `approved`/`denied` |
| `approved` | `paid` | adjudication complete (automatic) | all line items `approved` |
| `partially_approved` | `paid` | payment accepted | no existing `Dispute`, or re-adjudication complete with no further dispute possible |
| `denied` | `under_review` | dispute submitted (`review_type=manual`) | no existing `Dispute` |
| `partially_approved` | `under_review` | dispute submitted (`review_type=manual`) | no existing `Dispute` |

**Terminal states:** `paid` (normal path), `denied` when no `Dispute` exists and re-adjudication is complete.

**`approved → paid` is automatic:** When adjudication completes and all line items are `approved`, the claim transitions to `paid` and a `Payment` record is created within the same DB transaction. No separate trigger is needed.

**`partially_approved → paid`:** Not automatic. The member may dispute (moves to `under_review`) or the claim transitions to `paid` once no further dispute is possible (i.e. a `Dispute` record exists and has been resolved).

**`Claim.status` is a stored column**, updated by the adjudication engine and dispute handler only, never directly by API callers. It is derived from `LineItem.adjudication_status` values at the end of each adjudication run and persisted within the same transaction.

**`review_type` distinction:** When `review_type=auto` the system adjudicates immediately on entering `under_review`. When `review_type=manual` (post-dispute) the claim waits for a human reviewer to check coverage rule configuration before re-adjudication is triggered.

---

### LineItem Adjudication Status

```
pending ──► approved ──► pending  [trigger: dispute re-adjudication]
        └──► denied  ──► pending  [trigger: dispute re-adjudication]
```

| From | To | Trigger |
|---|---|---|
| `pending` | `approved` | CPT code covered + `date_of_service` within policy period |
| `pending` | `denied` | CPT code absent/not covered, or service outside policy period |
| `approved` | `pending` | dispute re-adjudication begins |
| `denied` | `pending` | dispute re-adjudication begins |

On re-adjudication after a dispute, `adjudication_status` is reset to `pending`, `latest_result_id` is cleared, and a new `AdjudicationResult` row (next revision) is created when the engine runs.

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

1. **Adjudication transaction boundary** (AC §8): The following writes must occur in a single DB transaction to guarantee consistency and prevent deductible double-spend under concurrent submissions:
   - UPDATE `LineItem.adjudication_status` (× N line items)
   - INSERT `AdjudicationResult` (× N)
   - UPDATE `LineItem.latest_result_id` (× N)
   - UPDATE `Accumulator.deductible_met`
   - UPDATE `Claim.status`
   - INSERT `ClaimStatusHistory`
   - INSERT `Payment` (only when result is `approved`)

2. **`Claim.status` is stored, not derived**: The status column is written exclusively by the adjudication engine and dispute handler within the adjudication transaction (see Note §1). It must never be written directly by API endpoint handlers. This is enforced by code convention, not a DB constraint.

3. **`latest_result_id` on `LineItem`**: Points to the most recent `AdjudicationResult` row for that line item. Updated atomically during each adjudication transaction. Allows loading a claim with all current adjudication results via a single join, avoiding a correlated subquery per line item.

4. **Dispute re-adjudication**: Re-adjudication appends new `AdjudicationResult` rows (incrementing `revision`) rather than mutating existing ones. `LineItem.latest_result_id` is updated to the new row. Original decisions are preserved for audit.

5. **Monetary precision**: Store all amounts as `NUMERIC(10, 2)` in SQLite (mapped to `Decimal` in Python). Never use `float`.

6. **`Accumulator.member_id` denormalization**: `member_id` is carried on `Accumulator` even though it is derivable via `Policy`. This allows direct member-scoped accumulator queries without a join and is intentional.

7. **`date_of_service` validation**: The constraint that `date_of_service` must fall within `[policy.start_date, policy.end_date]` is enforced at the application layer (claim submission validation). SQLite does not support cross-table check constraints without triggers.

8. **State transition enforcement**: State transition sequencing and the one-dispute rule are enforced by the application service layer, not by DB constraints. `ClaimStatusHistory` provides the immutable audit trail.

9. **Soft delete**: All primary entities carry `deleted_at DATETIME nullable`. A `NULL` value means the record is active. Application queries must filter `WHERE deleted_at IS NULL` by default. `ClaimStatusHistory` and `AdjudicationResult` are append-only audit tables and do not carry `deleted_at`.

10. **UUID storage**: All UUIDs are stored as `TEXT(36)` in SQLite, mapped to `String(36)` in SQLAlchemy with `default=uuid.uuid4`.
