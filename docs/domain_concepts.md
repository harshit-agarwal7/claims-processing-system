# Claims Processing System — Domain Concepts

This document defines the core vocabulary and conceptual model for the system.
Behavioral requirements are in [acceptance_criteria.md](acceptance_criteria.md).

---

## Entities

### Member
An individual insured person. Has exactly one active policy at a time and exactly one insurance (no secondary coverage).

### Provider
A healthcare professional or facility that delivers services to a member.

### Plan
Defines the benefit structure: which CPT codes are covered, the coverage percentage per CPT code, and the deductible amount. A plan is a template — multiple members can be on the same plan.

### Policy
A specific member's instance of a plan. Has a defined **policy period** (start and end dates). Coverage is only valid for services rendered within the policy period.

### Claim
A request for reimbursement submitted by (or on behalf of) a member. Contains one or more **line items**, plus provider details and the date of service.

### Line Item
A single billable service within a claim. Each line item has:
- A **diagnosis code** (ICD-10) — why the service was needed
- A **procedure code** (CPT) — what service was performed
- A **billed amount** — what the provider charged; this is also the amount adjudication is calculated against

### Adjudication Result
The outcome of evaluating a line item against the member's policy. Records:
- Whether the service is covered
- The amount applied to the deductible
- The amount the plan pays
- The amount the member owes
- A human-readable explanation of the decision

### Accumulator
A running total tracked per member, per policy period. Resets when a new policy period begins. The system tracks:
- **Deductible met** — how much the member has paid toward their deductible so far this period

Accumulators are updated after each adjudication and are an input to subsequent ones.

---

## Coverage Rules

Coverage is defined at the **CPT code level**. Each CPT code on a plan has:
- Whether it is covered (yes/no)
- A **coverage percentage** — the share the plan pays after the deductible is met

If a CPT code has no rule defined on the plan, the line item is denied as not covered.

---

## Key Financial Concepts

### Billed Amount
What the provider charges for a service. This is the amount used as the basis for adjudication.

### Deductible
A fixed amount the member must pay out-of-pocket before the plan begins paying. Applied per line item against the billed amount. Tracked cumulatively across all claims in the policy period.

### Coinsurance
Once the deductible is met, the member pays a fixed percentage and the plan pays the remainder, as defined by the CPT code's coverage rule.

### Adjudication Math (per line item)
```
remaining_deductible  = deductible - deductible_met_so_far
applied_to_deductible = min(billed_amount, remaining_deductible)
amount_after_deductible = billed_amount - applied_to_deductible
plan_pays    = amount_after_deductible * coverage_percentage
member_owes  = applied_to_deductible + (amount_after_deductible * (1 - coverage_percentage))
```

---

## Codes

| Code Type | Standard | Purpose | Example |
|-----------|----------|---------|---------|
| Diagnosis | ICD-10 | Why the service was needed | `M54.5` (lower back pain) |
| Procedure | CPT | What service was performed | `99213` (office visit) |

---

## Claim Lifecycle

```
submitted → under_review → approved          → paid
                         → denied
                         → partially_approved → paid
```

- **submitted** — received, not yet evaluated
- **under_review** — adjudication in progress, or a dispute is being reviewed
- **approved** — all line items covered
- **denied** — all line items not covered
- **partially_approved** — mix of covered and not covered line items
- **paid** — plan payment has been issued

The claim-level state is always derived from line item outcomes, never set directly.

---

## Disputes

A member may dispute a `denied` or `partially_approved` claim once. Disputing returns the claim to `under_review` for re-adjudication. A claim cannot be disputed more than once.

---

## Out of Scope

- Riders / policy add-ons
- Family / group plans and shared accumulators
- Coordination of Benefits (COB) / secondary insurance
- Distinction between billed amount and contracted/allowed amount
- Out-of-pocket maximum
- Prior authorization
- Out-of-network claims
