# Self-Review

## What's Good

**The architecture is clean and I'm happy with how it's structured:**
- I spent good amount of time thinking about entities and their relationships. This reflects in the design.
- The adjudication engine owns the single `db.session.commit()` for the entire submission flow — this was a deliberate choice to keep transaction ownership clear and avoid subtle bugs.
- Services flush without committing; the engine commits. The boundary is explicit.
- Routes handle HTTP, services handle business logic, engine handles math. The separation held throughout the build.

**Financial correctness was a priority:**
- `Decimal` with `ROUND_HALF_UP` throughout — no floats anywhere near money.
- `AdjudicationResult` is append-only — new row per revision, never mutated. Full audit trail.
- `ClaimStatusHistory` is append-only too. You can reconstruct the full lifecycle of any claim.

**Test coverage is solid:**
- ~157 tests across unit + integration, covering error cases not just happy paths.
- Tests assert on DB state, not just HTTP status codes.
- Sequential claims with deductible carryover is tested.

**Type discipline is consistent:**
- Strict mypy, type hints on all signatures, ruff enforced. The tooling is configured and passing clean.

---

## What's Rough

**The final phases were rushed.** I was under time pressure toward the end and it shows. I only reviewed the core adjudication logic and dispute handling in real detail — the rest of the codebase hasn't had a thorough pass. A visible example of this is `datetime.utcnow()`, which is deprecated in Python 3.12+ and appears in multiple places. I noticed it but didn't prioritize fixing it.

**Soft-delete filtering is copy-pasted everywhere.** Every query has `.where(...deleted_at.is_(None))`. I didn't abstract this out, so changing the pattern would mean touching 30+ places.

**Coverage rule uniqueness is enforced at the service layer, not the DB.** SQLite can't do partial indexes on `CoverageRule(plan_id, cpt_code)`, so I validate before insert at the service level. It works, but a unique index would be safer.

**The dispute service has asymmetric transaction handling.** The "with corrections" path calls `AdjudicationEngine.run()` which commits; the "without corrections" path calls `db.session.commit()` itself. Both are correct, but I'm not fully happy with the asymmetry — it's a minor code smell.

**The frontend is very basic.** I didn't put real thought into UX or UI design. It's functional enough to demonstrate the flows, but it's not something I'd put in front of actual users.

---

## What I'd Flag

**Security is completely absent.** This wasn't an oversight I plan to revisit later — I simply didn't build it. There's no authentication, no authorization, no session management, no rate limiting, no CORS policy. Anyone who can reach the server can read any member's data, submit claims on their behalf, or trigger admin actions. This needs to be designed and built from scratch before this system touches real data.

**Admin re-adjudication is a placeholder.** When a user raises a dispute that requires manual review, the `POST /api/claims/{id}/adjudicate` endpoint exists and accepts a `reviewer_note`, but it doesn't do anything meaningful — it just re-runs the adjudication engine with the same data. There's no mechanism for a reviewer to actually examine the claim, communicate with the member, request documentation, or make a real decision. The workflow is scaffolded, not implemented.

**There is no fraud layer.** Claims are accepted entirely on the member's word. There's no verification with the provider that the procedure actually happened, no cross-referencing of CPT codes, no anomaly detection, no duplicate claim detection beyond exact matches. In a real insurance system this would be one of the most critical functions — here it's completely missing.

**SQLite in production is a real constraint.** Single-writer, no partial indexes on `CoverageRule`, no row-level locking. Two simultaneous claim submissions for the same member could race on the accumulator and produce incorrect deductible math. This needs PostgreSQL before any real load.

---

## Overall

I'm satisfied with the core of the system — the adjudication math, the immutable audit trail, the transaction discipline, and the test coverage are solid. But a lot of what surrounds it is scaffolding that I never fully built out: there's no security model, no fraud layer, the admin re-adjudication workflow is incomplete, and the frontend is a proof of concept. The final stretch was time-constrained and I know the peripheral code hasn't had the same scrutiny as the core logic. The foundation is worth building on — but what it needs next is a proper security design, a fraud strategy, and a thorough review pass over everything I didn't get to look at carefully the first time.
