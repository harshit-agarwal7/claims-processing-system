"""Adjudication engine — evaluates claim line items against plan coverage rules.

All DB writes in ``AdjudicationEngine.run`` occur inside a single transaction
that is committed at the end of the method.  No other service should call
``db.session.commit()`` while the engine is running.
"""

import logging
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select

from app.extensions import db
from app.models import (
    Accumulator,
    AdjudicationResult,
    Claim,
    ClaimStatus,
    ClaimStatusHistory,
    CoverageRule,
    Dispute,
    DisputeStatus,
    LineItemStatus,
    Payment,
)

logger = logging.getLogger(__name__)


class AdjudicationEngine:
    """Evaluate a claim's line items and drive it to a final status.

    The engine is stateless; instantiate a new one per adjudication run.
    """

    def run(self, claim_id: str) -> Claim:
        """Adjudicate all active line items on *claim_id* and commit the result.

        Steps (all in one transaction):
        1. Load the Accumulator for the claim's policy.
        2. Transition ``submitted → under_review`` (skip if already ``under_review``).
        3. For each active LineItem (ordered by id):
           - Reset adjudication_status + latest_result_id.
           - Look up CoverageRule; derive approved/denied result.
           - INSERT AdjudicationResult; flush to get its id.
           - Update LineItem.latest_result_id / adjudication_status.
        4. Update Accumulator.deductible_met.
        5. Derive ClaimStatus from line item outcomes.
        6. Transition ``under_review → <final_status>``.
        7. If ``approved``: transition to ``paid``; create Payment when plan_pays > 0.
        8. If ``partially_approved`` AND a resolved Dispute exists: create Payment,
           transition to ``paid``.
        9. Commit.

        Args:
            claim_id: UUID string of the claim to adjudicate.

        Returns:
            The refreshed Claim with its final status and updated relationships.

        Raises:
            ValueError: If the claim does not exist.
            RuntimeError: If the policy has no Accumulator (data-integrity error).
        """
        claim = db.session.get(Claim, claim_id)
        if claim is None:
            raise ValueError(f"Claim {claim_id!r} not found")

        # 1. Load accumulator
        accumulator: Accumulator | None = db.session.scalar(
            select(Accumulator).where(Accumulator.policy_id == claim.policy_id)
        )
        if accumulator is None:
            raise RuntimeError(
                f"No Accumulator found for policy {claim.policy_id!r} — "
                "policy was not created correctly"
            )

        plan = claim.policy.plan

        # 2. Transition submitted → under_review (idempotent for re-adjudication)
        if claim.status == ClaimStatus.submitted:
            self._transition(claim, ClaimStatus.submitted, ClaimStatus.under_review)

        # 3. Process each active line item in deterministic order
        active_items = sorted(
            (li for li in claim.line_items if li.deleted_at is None),
            key=lambda li: li.id,
        )
        total_consumed: Decimal = Decimal("0.00")

        for line_item in active_items:
            # Reset for (re-)adjudication
            line_item.adjudication_status = LineItemStatus.pending
            line_item.latest_result_id = None

            cpt_code = line_item.cpt_code
            billed = line_item.billed_amount

            # Look up coverage rule — raises MultipleResultsFound if duplicate active rules exist
            rule: CoverageRule | None = db.session.scalar(
                select(CoverageRule).where(
                    CoverageRule.plan_id == plan.id,
                    CoverageRule.cpt_code == cpt_code,
                    CoverageRule.deleted_at.is_(None),
                )
            )

            revision = max((r.revision for r in line_item.results), default=0) + 1

            if rule is None or not rule.is_covered:
                result = AdjudicationResult(
                    line_item_id=line_item.id,
                    revision=revision,
                    is_covered=False,
                    applied_to_deductible=Decimal("0.00"),
                    plan_pays=Decimal("0.00"),
                    member_owes=billed,
                    explanation=f"Service {cpt_code} is not covered under your plan.",
                )
                line_item.adjudication_status = LineItemStatus.denied
            else:
                remaining = plan.deductible - accumulator.deductible_met - total_consumed
                applied_to_deductible = min(billed, max(Decimal("0.00"), remaining))
                amount_after_deductible = billed - applied_to_deductible
                coverage_pct: Decimal = rule.coverage_percentage
                plan_pays = (amount_after_deductible * coverage_pct).quantize(
                    Decimal("0.01"), ROUND_HALF_UP
                )
                member_owes = (billed - plan_pays).quantize(Decimal("0.01"), ROUND_HALF_UP)
                total_consumed += applied_to_deductible

                pct_display = float(coverage_pct) * 100
                explanation = (
                    f"Service {cpt_code} covered at {pct_display:.4g}%. "
                    f"${applied_to_deductible} applied to deductible. "
                    f"Plan pays ${plan_pays}; you owe ${member_owes}."
                )
                result = AdjudicationResult(
                    line_item_id=line_item.id,
                    revision=revision,
                    is_covered=True,
                    applied_to_deductible=applied_to_deductible,
                    plan_pays=plan_pays,
                    member_owes=member_owes,
                    explanation=explanation,
                )
                line_item.adjudication_status = LineItemStatus.approved

            db.session.add(result)
            db.session.flush()  # get result.id

            line_item.latest_result_id = result.id
            logger.info(
                "claim %s line_item %s cpt=%s covered=%s applied_deductible=%s plan_pays=%s",
                claim.id,
                line_item.id,
                cpt_code,
                result.is_covered,
                result.applied_to_deductible,
                result.plan_pays,
            )

        # 4. Update accumulator
        accumulator.deductible_met += total_consumed

        # 5. Derive claim-level status from line item outcomes
        statuses = {li.adjudication_status for li in active_items}
        if statuses == {LineItemStatus.approved}:
            final_status = ClaimStatus.approved
        elif statuses == {LineItemStatus.denied}:
            final_status = ClaimStatus.denied
        else:
            final_status = ClaimStatus.partially_approved

        # 6. Transition under_review → final status
        self._transition(claim, ClaimStatus.under_review, final_status)

        # 7. approved → paid  (Payment only when plan actually pays something)
        if final_status == ClaimStatus.approved:
            self._transition(claim, ClaimStatus.approved, ClaimStatus.paid)
            total_plan_pays: Decimal = sum(  # type: ignore[assignment]
                li.latest_result.plan_pays for li in active_items if li.latest_result is not None
            )
            if total_plan_pays > Decimal("0.00"):
                db.session.add(Payment(claim_id=claim.id, amount=total_plan_pays))

        # 8. partially_approved + resolved dispute → paid
        elif final_status == ClaimStatus.partially_approved:
            dispute: Dispute | None = claim.dispute
            if dispute is not None and dispute.status == DisputeStatus.resolved:
                approved_pays: Decimal = sum(  # type: ignore[assignment]
                    li.latest_result.plan_pays
                    for li in active_items
                    if li.adjudication_status == LineItemStatus.approved
                    and li.latest_result is not None
                )
                self._transition(claim, ClaimStatus.partially_approved, ClaimStatus.paid)
                db.session.add(Payment(claim_id=claim.id, amount=approved_pays))

        # 9. Commit
        db.session.commit()
        db.session.refresh(claim)
        return claim

    def _transition(
        self,
        claim: Claim,
        from_status: ClaimStatus,
        to_status: ClaimStatus,
    ) -> None:
        """Update claim status and append a ClaimStatusHistory row.

        Args:
            claim: The claim to transition.
            from_status: The status being left.
            to_status: The status being entered.
        """
        claim.status = to_status
        db.session.add(
            ClaimStatusHistory(
                claim_id=claim.id,
                from_status=from_status,
                to_status=to_status,
            )
        )
        db.session.flush()
        logger.info(
            "claim %s transitioned %s → %s",
            claim.id,
            from_status.value,
            to_status.value,
        )
