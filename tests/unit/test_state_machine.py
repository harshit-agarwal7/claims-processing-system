"""Unit tests for the full claim state machine.

Covers all lifecycle transitions driven by AdjudicationEngine and
dispute_service.submit_dispute, calling services directly (no HTTP layer).

The ``app`` fixture provides an active app context for the duration of each
test, so no nested ``with app.app_context():`` blocks are used here.
"""

import types
from datetime import date, datetime
from decimal import Decimal

import pytest
from flask import Flask

from app.errors import ConflictError
from app.extensions import db
from app.models import (
    Claim,
    ClaimStatus,
    CoverageRule,
    DisputeStatus,
    LineItem,
    LineItemStatus,
    ReviewType,
)
from app.services.adjudication_engine import AdjudicationEngine
from app.services.dispute_service import submit_dispute

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_claim(
    seed: types.SimpleNamespace,
    line_items: list[tuple[str, str, Decimal]],
    *,
    deductible_met: Decimal | None = None,
) -> Claim:
    """Create and flush a Claim with line items, then return it.

    Args:
        seed: The conftest seed namespace.
        line_items: List of (diagnosis_code, cpt_code, billed_amount).
        deductible_met: If provided, overrides ``seed.accumulator.deductible_met`` in the DB.

    Returns:
        The flushed Claim.
    """
    if deductible_met is not None:
        seed.accumulator.deductible_met = deductible_met
        db.session.flush()

    claim = Claim(
        member_id=seed.member.id,
        policy_id=seed.policy.id,
        provider_id=seed.provider.id,
        date_of_service=date(2026, 3, 1),
        status=ClaimStatus.submitted,
        review_type=ReviewType.auto,
    )
    db.session.add(claim)
    db.session.flush()

    for diag, cpt, billed in line_items:
        db.session.add(
            LineItem(
                claim_id=claim.id,
                diagnosis_code=diag,
                cpt_code=cpt,
                billed_amount=billed,
            )
        )
    db.session.flush()
    return claim


# ---------------------------------------------------------------------------
# Happy path transitions
# ---------------------------------------------------------------------------


class TestHappyPathTransitions:
    """Core engine transitions without disputes."""

    def test_all_approved_transitions_to_paid_with_payment(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """All covered line items → approved → paid; Payment created."""
        claim = _make_claim(
            seed,
            [("M54.5", "99213", Decimal("200.00"))],
            deductible_met=Decimal("500.00"),  # deductible fully met → plan pays 160
        )
        result = AdjudicationEngine().run(claim.id)

        assert result.status == ClaimStatus.paid
        assert result.payment is not None
        assert result.payment.amount == Decimal("160.00")
        assert all(li.adjudication_status == LineItemStatus.approved for li in result.line_items)

    def test_all_denied_transitions_to_denied_no_payment(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """All uncovered line items → denied; no Payment created."""
        claim = _make_claim(seed, [("M54.5", "00000", Decimal("200.00"))])
        result = AdjudicationEngine().run(claim.id)

        assert result.status == ClaimStatus.denied
        assert result.payment is None

    def test_mixed_line_items_partially_approved_no_payment(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """Mix of covered and uncovered items → partially_approved; no Payment."""
        claim = _make_claim(
            seed,
            [
                ("M54.5", "99213", Decimal("200.00")),  # covered
                ("M54.5", "00000", Decimal("200.00")),  # not covered
            ],
            deductible_met=Decimal("500.00"),
        )
        result = AdjudicationEngine().run(claim.id)

        assert result.status == ClaimStatus.partially_approved
        assert result.payment is None

    def test_approved_with_zero_plan_pays_transitions_to_paid_without_payment_record(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """Covered but entire amount goes to deductible (plan_pays=0) → paid, no Payment row."""
        # billed=100, deductible=500, met=0 → applied=100, plan_pays=0
        claim = _make_claim(seed, [("M54.5", "99213", Decimal("100.00"))])
        result = AdjudicationEngine().run(claim.id)

        assert result.status == ClaimStatus.paid
        assert result.payment is None


# ---------------------------------------------------------------------------
# Dispute flow transitions
# ---------------------------------------------------------------------------


class TestDisputeFlowTransitions:
    """Transitions involving dispute submission and re-adjudication."""

    def test_partially_approved_dispute_transitions_to_under_review(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """partially_approved → dispute filed → under_review with review_type=manual."""
        claim = _make_claim(
            seed,
            [
                ("M54.5", "99213", Decimal("200.00")),  # covered
                ("M54.5", "00000", Decimal("200.00")),  # not covered
            ],
            deductible_met=Decimal("500.00"),
        )
        AdjudicationEngine().run(claim.id)

        dispute = submit_dispute(claim.id, reason="I believe this service is covered.")

        refreshed = db.session.get(Claim, claim.id)
        assert refreshed is not None

        assert dispute.status == DisputeStatus.pending
        assert refreshed.status == ClaimStatus.under_review
        assert refreshed.review_type == ReviewType.manual

    def test_denied_dispute_transitions_to_under_review(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """denied → dispute filed → under_review."""
        claim = _make_claim(seed, [("M54.5", "00000", Decimal("200.00"))])
        AdjudicationEngine().run(claim.id)

        submit_dispute(claim.id, reason="The procedure was necessary.")

        refreshed = db.session.get(Claim, claim.id)
        assert refreshed is not None

        assert refreshed.status == ClaimStatus.under_review
        assert refreshed.review_type == ReviewType.manual

    def test_under_review_readjudicate_to_approved_then_paid(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """under_review (manual) → re-adjudicate → approved → paid."""
        # Start with denied (no coverage rule for cpt 88888)
        claim = _make_claim(seed, [("M54.5", "88888", Decimal("200.00"))])
        AdjudicationEngine().run(claim.id)

        submit_dispute(claim.id, reason="Service should be covered.")

        # Add coverage rule so re-adjudication results in approved
        db.session.add(
            CoverageRule(
                plan_id=seed.plan.id,
                cpt_code="88888",
                is_covered=True,
                coverage_percentage=Decimal("0.8000"),
            )
        )

        # Mark dispute resolved before re-adjudication (as dispute_service.re_adjudicate will do)
        refreshed = db.session.get(Claim, claim.id)
        assert refreshed is not None and refreshed.dispute is not None
        refreshed.dispute.status = DisputeStatus.resolved
        refreshed.dispute.resolved_at = datetime.utcnow()
        db.session.commit()

        # Set deductible met so plan_pays > 0
        seed.accumulator.deductible_met = Decimal("500.00")
        db.session.commit()

        result = AdjudicationEngine().run(claim.id)

        assert result.status == ClaimStatus.paid
        assert result.payment is not None
        assert result.payment.amount == Decimal("160.00")

    def test_under_review_readjudicate_to_partially_approved_still_paid(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """under_review (manual) → re-adjudicate → partially_approved + resolved dispute → paid."""
        claim = _make_claim(
            seed,
            [
                ("M54.5", "99213", Decimal("200.00")),  # covered → plan pays 160
                ("M54.5", "00000", Decimal("200.00")),  # not covered
            ],
            deductible_met=Decimal("500.00"),
        )
        AdjudicationEngine().run(claim.id)

        submit_dispute(claim.id, reason="I'd like a second review.")

        # Mark dispute resolved
        refreshed = db.session.get(Claim, claim.id)
        assert refreshed is not None and refreshed.dispute is not None
        refreshed.dispute.status = DisputeStatus.resolved
        refreshed.dispute.resolved_at = datetime.utcnow()
        db.session.commit()

        result = AdjudicationEngine().run(claim.id)

        assert result.status == ClaimStatus.paid
        assert result.payment is not None
        # Only the covered item pays out
        assert result.payment.amount == Decimal("160.00")

    def test_denied_dispute_readjudicate_to_approved_paid(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """denied → dispute → under_review → re-adjudicate (now covered) → approved → paid."""
        claim = _make_claim(seed, [("M54.5", "77777", Decimal("200.00"))])
        AdjudicationEngine().run(claim.id)

        submit_dispute(claim.id, reason="Coverage was erroneously denied.")

        db.session.add(
            CoverageRule(
                plan_id=seed.plan.id,
                cpt_code="77777",
                is_covered=True,
                coverage_percentage=Decimal("0.8000"),
            )
        )

        refreshed = db.session.get(Claim, claim.id)
        assert refreshed is not None and refreshed.dispute is not None
        refreshed.dispute.status = DisputeStatus.resolved
        refreshed.dispute.resolved_at = datetime.utcnow()
        db.session.commit()

        # deductible fully consumed so plan pays
        seed.accumulator.deductible_met = Decimal("500.00")
        db.session.commit()

        result = AdjudicationEngine().run(claim.id)

        assert result.status == ClaimStatus.paid
        assert result.payment is not None


# ---------------------------------------------------------------------------
# Dispute guard rails
# ---------------------------------------------------------------------------


class TestDisputeGuardRails:
    """Ensure dispute submission enforces business rules."""

    def test_second_dispute_raises_conflict(self, app: Flask, seed: types.SimpleNamespace) -> None:
        """A claim can only be disputed once; second attempt raises ConflictError."""
        claim = _make_claim(seed, [("M54.5", "00000", Decimal("200.00"))])
        AdjudicationEngine().run(claim.id)

        submit_dispute(claim.id, reason="First dispute.")

        with pytest.raises(ConflictError):
            submit_dispute(claim.id, reason="Second dispute attempt.")

    def test_dispute_on_approved_claim_raises_conflict(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """Disputing a paid/approved claim raises ConflictError."""
        claim = _make_claim(
            seed,
            [("M54.5", "99213", Decimal("200.00"))],
            deductible_met=Decimal("500.00"),
        )
        AdjudicationEngine().run(claim.id)

        # Claim lands on paid after approval
        refreshed = db.session.get(Claim, claim.id)
        assert refreshed is not None
        assert refreshed.status == ClaimStatus.paid

        with pytest.raises(ConflictError):
            submit_dispute(claim.id, reason="Disputing a paid claim.")

    def test_dispute_stores_reason(self, app: Flask, seed: types.SimpleNamespace) -> None:
        """Dispute reason is persisted."""
        claim = _make_claim(seed, [("M54.5", "00000", Decimal("200.00"))])
        AdjudicationEngine().run(claim.id)

        dispute = submit_dispute(claim.id, reason="My reason is X.")

        assert dispute.reason == "My reason is X."
        assert dispute.claim_id == claim.id
