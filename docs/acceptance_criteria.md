# Claims Processing System — Acceptance Criteria

## 0. Scope

**In scope:**
- Individual plans only — no family or group plans
- Each member has exactly one active policy at a time
- Each member has exactly one insurance (no secondary insurance)
- Line items adjudicate against the **billed amount**; deductible and coinsurance are calculated against the billed amount
- Adjudication result records what the plan pays and what the member owes — this single record serves all purposes (no distinction between member-facing and provider-facing documents)

**Out of scope:**
- Riders / policy add-ons
- Family or shared deductibles / accumulators
- Coordination of Benefits (COB) / secondary insurance
- Distinction between billed amount and contracted/allowed amount
- Distinction between member-facing EOB and provider-facing remittance advice

---

## 1. Claim Submission
- A member can submit a claim with one or more line items
- Each line item includes: diagnosis code, service type, provider details, and billed amount
- Submission returns a unique claim ID and initial status of `submitted`
- Invalid submissions (missing required fields, unknown member/policy) are rejected with clear error messages

## 2. Coverage Adjudication
- Adjudication happens at the **line item level** — each line item is evaluated independently
- For each line item, the system determines:
  - Whether the service type is covered under the member's active policy
  - The payable amount after applying the remaining deductible and coverage percentage
  - An explanation referencing the specific rule applied (e.g., *"Service covered at 80%; $200 applied to deductible. Payable: $160"*)
- Deductible consumption is tracked **across all prior claims** in the same policy period
- Adjudication results are stored and retrievable per claim

## 3. Claim Lifecycle
- Claims transition through states in this order:

  ```
  submitted → under_review → approved
                           → denied
                           → partially_approved → paid
                                    ↓
                                   paid
  ```

- The claim-level state is derived from line item outcomes:
  - All line items approved → `approved`
  - All line items denied → `denied`
  - Mix of approved and denied → `partially_approved`
- No state can be skipped; transitions are timestamped and auditable
- The paid amount is the **sum of approved line items only**

## 4. Decision Transparency
- Every line item adjudication has a human-readable explanation
- The explanation references the policy rule applied and shows the deductible/coverage calculation
- A member can retrieve the full decision rationale for any of their claims

## 5. Disputes
- A member can dispute a `denied` or `partially_approved` claim
- Disputing moves the claim back to `under_review`
- The dispute records the member's reason
- After re-adjudication, the claim reaches a new final state (`approved`, `denied`, or `partially_approved`)
- A claim can only be disputed once (no infinite dispute loops)

## 6. Policy & Coverage Rules
- A policy defines: covered service types, coverage percentage, deductible amount, and policy period (start/end dates)
- A member can only submit a claim against a policy that was **active at the time of service**
- The deductible is applied first; the coverage percentage applies only to the amount exceeding the deductible
- Once the deductible is fully consumed across claims in the policy period, subsequent claims are paid at the coverage percentage with no further deductible applied

## 7. API Correctness
- All endpoints return appropriate HTTP status codes (200, 201, 400, 404, 422, 500)
- Error responses include a machine-readable error code and human-readable message
- All responses are valid JSON

## 8. Data Integrity
- A member cannot submit a claim against a policy they do not hold
- Monetary amounts are stored and returned to 2 decimal places
- Concurrent claim submissions do not corrupt deductible tracking

## 9. Observability
- All state transitions logged at `INFO` level with claim ID and timestamp
- All adjudication decisions logged with claim ID, line item, rule applied, and outcome
- Errors logged at `ERROR` level with enough context to reproduce the issue

## 10. Non-Functional
- All API responses complete within 2 seconds under normal load
- Test coverage for: adjudication logic, deductible tracking, state machine transitions, and API endpoints
