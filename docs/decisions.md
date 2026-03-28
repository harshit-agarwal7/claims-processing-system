# Claims Processing System — Design Decisions

---

## What We Built

- **Individual member claims processing** — one member, one active policy, one insurance at a time.
- **Plan as a template** — a `Plan` holds the deductible and CPT-level coverage rules; multiple members can be on the same plan. Plan versioning is handled by creating a new `Plan` record (e.g. on yearly updates); existing policies remain tied to their original plan.
- **Single deductible per plan** — one fixed deductible amount per plan, tracked cumulatively across all claims within a policy period via an `Accumulator`.
- **Line-item-level adjudication** — each line item is evaluated independently against the member's active policy. The claim-level status is always derived from line item outcomes, never set directly.
- **Revision-based adjudication history** — `AdjudicationResult` rows are never mutated. Re-adjudication appends a new row with an incremented `revision`. The highest revision per line item is the current result; all prior revisions are preserved for audit.
- **Claim lifecycle state machine** — `submitted → under_review → approved / denied / partially_approved → paid`. All transitions are timestamped and recorded in `ClaimStatusHistory` (append-only).
- **Dispute mechanism** — a member may dispute a `denied` or `partially_approved` claim once. Disputing returns the claim to `under_review` with `review_type=manual`.
- **Human review scoped to disputes only** — the only case requiring human review is a dispute where the member believes a coverage rule was incorrectly configured. A reviewer checks the plan's `CoverageRule` entries, corrects any misconfiguration, and then triggers re-adjudication. The reviewer's findings are recorded in `Dispute.reviewer_note`.
- **`review_type` on Claim** — distinguishes `auto` (initial submission, system adjudicates immediately) from `manual` (post-dispute, waits for human reviewer before re-adjudication).
- **NPI as provider identifier** — system assumes US context; NPI (National Provider Identifier) is US-specific, consistent with the use of CPT procedure codes.

---

## What We Did Not Build

- **Riders / policy add-ons** — no per-procedure or per-category deductibles; one deductible per plan only.
- **Family or group plans** — no shared deductibles or accumulators across members.
- **Secondary insurance / Coordination of Benefits (COB)** — each member has exactly one insurance.
- **Out-of-pocket maximum** — no cap on total member spending within a period.
- **Prior authorization** — no pre-approval workflow before services are rendered.
- **Out-of-network claims** — all providers treated the same; no network tier distinction.
- **Distinction between billed amount and contracted/allowed amount** — adjudication is calculated against the billed amount only.
- **Fraud detection / clinical validation** — CPT and ICD-10 codes are taken at face value; no cross-checking of diagnosis-procedure combinations.
- **Supporting document submission** — members do not upload receipts or provider documentation.
- **Member or provider address storage** — address data plays no role in adjudication and is not stored.
- **International provider identifiers** — no abstraction for non-US provider ID schemes.

---

## Assumptions

- **Submitted codes are trusted** — CPT and ICD-10 codes submitted by the member are accepted as-is. If codes are incorrect, the member is expected to resubmit a corrected claim rather than raise a dispute.
- **Disputes are for coverage rule errors only** — a dispute is meaningful only when a coverage rule was incorrectly configured in the plan. Disputes arising from incorrect CPT codes or wrong billed amounts are handled by resubmission.
- **Re-adjudication produces a new result only if something changed** — if no coverage rule was corrected between the original adjudication and the re-run, the outcome will be identical. It is the human reviewer's responsibility to make corrections before triggering re-adjudication.
- **One deductible per plan, no per-category deductibles** — the deductible is a single flat amount applied across all line items in the policy period.
- **Plan versioning via new records** — when a plan is updated (e.g. annually), a new `Plan` row is created. Members renewing get a new `Policy` pointing to the new plan. Historical claims remain tied to the plan that was in effect at the time.
- **US context** — CPT procedure codes and NPI are US-specific standards. The system does not account for international coding or identification schemes.
- **Monetary amounts as NUMERIC(10,2)** — all money is stored and computed as `Decimal` in Python; `float` is never used.
- **Deductible tracking is transactional** — reading and updating the `Accumulator` during adjudication happens within a single DB transaction to prevent concurrent claims from double-counting deductible spend.
