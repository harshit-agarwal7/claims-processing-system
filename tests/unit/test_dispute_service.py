"""Unit tests for dispute_service guard rails.

Covers the validation and conflict checks in submit_dispute,
trigger_readjudication, and accept_payment.  All tests call service
functions directly against an in-memory SQLite DB provided by the
``app`` and ``seed`` fixtures.
"""

import types
from datetime import date, datetime
from decimal import Decimal

import pytest
from flask import Flask

from app.errors import ConflictError, NotFoundError
from app.extensions import db
from app.models import (
    Claim,
    ClaimStatus,
    ClaimStatusHistory,
    DisputeStatus,
    LineItem,
    ReviewType,
)
from app.services.adjudication_engine import AdjudicationEngine
from app.services.dispute_service import accept_payment, submit_dispute, trigger_readjudication

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_claim(
    seed: types.SimpleNamespace,
    line_items: list[tuple[str, str, Decimal]],
    *,
    deductible_met: Decimal | None = None,
) -> Claim:
    """Create and flush a Claim with line items.

    Args:
        seed: The conftest seed namespace.
        line_items: List of (diagnosis_code, cpt_code, billed_amount).
        deductible_met: If provided, overrides accumulator.deductible_met.

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
# submit_dispute guard rails
# ---------------------------------------------------------------------------


class TestSubmitDisputeGuards:
    """Validation checks for dispute_service.submit_dispute."""

    def test_approved_claim_raises_conflict(self, app: Flask, seed: types.SimpleNamespace) -> None:
        """Disputing a claim in 'approved' status raises ConflictError."""
        claim = _make_claim(seed, [("M54.5", "99213", Decimal("200.00"))])
        claim.status = ClaimStatus.approved
        db.session.commit()

        with pytest.raises(ConflictError):
            submit_dispute(claim.id, reason="Should not be allowed.")

    def test_paid_claim_raises_conflict(self, app: Flask, seed: types.SimpleNamespace) -> None:
        """Disputing a claim in 'paid' status raises ConflictError."""
        claim = _make_claim(seed, [("M54.5", "99213", Decimal("200.00"))])
        claim.status = ClaimStatus.paid
        db.session.commit()

        with pytest.raises(ConflictError):
            submit_dispute(claim.id, reason="Should not be allowed.")

    def test_duplicate_dispute_raises_conflict(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """A claim can only be disputed once; second attempt raises ConflictError."""
        claim = _make_claim(seed, [("M54.5", "00000", Decimal("200.00"))])
        AdjudicationEngine().run(claim.id)  # → denied

        submit_dispute(claim.id, reason="First dispute.")

        with pytest.raises(ConflictError):
            submit_dispute(claim.id, reason="Second dispute attempt.")


# ---------------------------------------------------------------------------
# trigger_readjudication guard rails
# ---------------------------------------------------------------------------


class TestTriggerReadjudicationGuards:
    """Validation checks for dispute_service.trigger_readjudication."""

    def test_non_under_review_claim_raises_conflict(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """Calling trigger_readjudication on a claim not in under_review raises ConflictError."""
        claim = _make_claim(seed, [("M54.5", "00000", Decimal("200.00"))])
        AdjudicationEngine().run(claim.id)  # → denied, review_type stays auto

        with pytest.raises(ConflictError):
            trigger_readjudication(claim.id, reviewer_note=None)

    def test_no_dispute_raises_not_found(self, app: Flask, seed: types.SimpleNamespace) -> None:
        """trigger_readjudication on a claim with no Dispute row raises NotFoundError."""
        claim = _make_claim(seed, [("M54.5", "00000", Decimal("200.00"))])
        # Manually put claim into under_review/manual without creating a Dispute
        claim.status = ClaimStatus.under_review
        claim.review_type = ReviewType.manual
        db.session.add(
            ClaimStatusHistory(
                claim_id=claim.id,
                from_status=ClaimStatus.submitted,
                to_status=ClaimStatus.under_review,
            )
        )
        db.session.commit()

        with pytest.raises(NotFoundError):
            trigger_readjudication(claim.id, reviewer_note=None)

    def test_resolved_dispute_raises_conflict(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """trigger_readjudication when the dispute is already resolved raises ConflictError."""
        claim = _make_claim(seed, [("M54.5", "00000", Decimal("200.00"))])
        AdjudicationEngine().run(claim.id)  # → denied

        submit_dispute(claim.id, reason="First dispute.")

        # Manually mark the dispute as resolved (simulates a prior readjudication)
        refreshed = db.session.get(Claim, claim.id)
        assert refreshed is not None and refreshed.dispute is not None
        refreshed.dispute.status = DisputeStatus.resolved
        refreshed.dispute.resolved_at = datetime.utcnow()
        db.session.commit()

        with pytest.raises(ConflictError):
            trigger_readjudication(claim.id, reviewer_note=None)


# ---------------------------------------------------------------------------
# accept_payment guard rails
# ---------------------------------------------------------------------------


class TestAcceptPaymentGuards:
    """Validation checks for dispute_service.accept_payment."""

    def test_denied_claim_raises_conflict(self, app: Flask, seed: types.SimpleNamespace) -> None:
        """accept_payment on a denied claim raises ConflictError."""
        claim = _make_claim(seed, [("M54.5", "00000", Decimal("200.00"))])
        AdjudicationEngine().run(claim.id)  # → denied

        with pytest.raises(ConflictError):
            accept_payment(claim.id)

    def test_dispute_already_filed_raises_conflict(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """accept_payment when a Dispute exists for the claim raises ConflictError."""
        claim = _make_claim(
            seed,
            [
                ("M54.5", "99213", Decimal("200.00")),  # covered
                ("M54.5", "00000", Decimal("200.00")),  # not covered
            ],
            deductible_met=Decimal("500.00"),
        )
        AdjudicationEngine().run(claim.id)  # → partially_approved

        submit_dispute(claim.id, reason="I want full coverage.")

        with pytest.raises(ConflictError):
            accept_payment(claim.id)
