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

from app.errors import BadRequestError, ConflictError, NotFoundError
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


# ---------------------------------------------------------------------------
# submit_dispute with line item corrections
# ---------------------------------------------------------------------------


class TestSubmitDisputeWithLineItemUpdates:
    """Tests for the optional line_item_updates parameter in submit_dispute."""

    def test_billed_amount_correction_applied(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """Providing a corrected billed_amount updates the LineItem in-place."""
        claim = _make_claim(seed, [("M54.5", "00000", Decimal("200.00"))])
        AdjudicationEngine().run(claim.id)  # → denied
        li = claim.line_items[0]

        submit_dispute(
            claim.id,
            reason="Amount was wrong.",
            line_item_updates=[{"line_item_id": li.id, "billed_amount": "150.00"}],
        )

        db.session.refresh(li)
        assert li.billed_amount == Decimal("150.00")

    def test_cpt_code_correction_applied(self, app: Flask, seed: types.SimpleNamespace) -> None:
        """Providing a corrected cpt_code updates the LineItem in-place."""
        claim = _make_claim(seed, [("M54.5", "00000", Decimal("200.00"))])
        AdjudicationEngine().run(claim.id)  # → denied
        li = claim.line_items[0]

        submit_dispute(
            claim.id,
            reason="Wrong CPT code.",
            line_item_updates=[{"line_item_id": li.id, "cpt_code": "99213"}],
        )

        db.session.refresh(li)
        assert li.cpt_code == "99213"

    def test_both_fields_corrected_on_same_line_item(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """Both billed_amount and cpt_code can be corrected on the same line item."""
        claim = _make_claim(seed, [("M54.5", "00000", Decimal("200.00"))])
        AdjudicationEngine().run(claim.id)  # → denied
        li = claim.line_items[0]

        submit_dispute(
            claim.id,
            reason="Both fields wrong.",
            line_item_updates=[
                {"line_item_id": li.id, "cpt_code": "99213", "billed_amount": "175.00"}
            ],
        )

        db.session.refresh(li)
        assert li.cpt_code == "99213"
        assert li.billed_amount == Decimal("175.00")

    def test_multiple_line_items_corrected_independently(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """Corrections to multiple line items are each applied independently."""
        claim = _make_claim(
            seed,
            [
                ("M54.5", "00000", Decimal("200.00")),
                ("M54.5", "00001", Decimal("300.00")),
            ],
        )
        AdjudicationEngine().run(claim.id)  # → denied
        li0, li1 = claim.line_items[0], claim.line_items[1]

        submit_dispute(
            claim.id,
            reason="Both items wrong.",
            line_item_updates=[
                {"line_item_id": li0.id, "cpt_code": "99213"},
                {"line_item_id": li1.id, "billed_amount": "250.00"},
            ],
        )

        db.session.refresh(li0)
        db.session.refresh(li1)
        assert li0.cpt_code == "99213"
        assert li1.billed_amount == Decimal("250.00")

    def test_only_provided_field_is_updated(self, app: Flask, seed: types.SimpleNamespace) -> None:
        """Providing only billed_amount leaves cpt_code unchanged, and vice versa."""
        claim = _make_claim(seed, [("M54.5", "00000", Decimal("200.00"))])
        AdjudicationEngine().run(claim.id)  # → denied
        li = claim.line_items[0]
        original_cpt = li.cpt_code

        submit_dispute(
            claim.id,
            reason="Amount only.",
            line_item_updates=[{"line_item_id": li.id, "billed_amount": "100.00"}],
        )

        db.session.refresh(li)
        assert li.cpt_code == original_cpt
        assert li.billed_amount == Decimal("100.00")

    def test_unknown_line_item_id_raises_bad_request(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """A line_item_id not belonging to the claim raises BadRequestError."""
        claim = _make_claim(seed, [("M54.5", "00000", Decimal("200.00"))])
        AdjudicationEngine().run(claim.id)  # → denied

        with pytest.raises(BadRequestError):
            submit_dispute(
                claim.id,
                reason="Wrong item.",
                line_item_updates=[
                    {"line_item_id": "00000000-0000-0000-0000-000000000000", "cpt_code": "99213"}
                ],
            )

    def test_zero_billed_amount_raises_bad_request(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """A billed_amount of zero raises BadRequestError."""
        claim = _make_claim(seed, [("M54.5", "00000", Decimal("200.00"))])
        AdjudicationEngine().run(claim.id)  # → denied
        li = claim.line_items[0]

        with pytest.raises(BadRequestError):
            submit_dispute(
                claim.id,
                reason="Amount.",
                line_item_updates=[{"line_item_id": li.id, "billed_amount": "0.00"}],
            )

    def test_negative_billed_amount_raises_bad_request(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """A negative billed_amount raises BadRequestError."""
        claim = _make_claim(seed, [("M54.5", "00000", Decimal("200.00"))])
        AdjudicationEngine().run(claim.id)  # → denied
        li = claim.line_items[0]

        with pytest.raises(BadRequestError):
            submit_dispute(
                claim.id,
                reason="Amount.",
                line_item_updates=[{"line_item_id": li.id, "billed_amount": "-50.00"}],
            )

    def test_empty_cpt_code_raises_bad_request(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """An empty cpt_code raises BadRequestError."""
        claim = _make_claim(seed, [("M54.5", "00000", Decimal("200.00"))])
        AdjudicationEngine().run(claim.id)  # → denied
        li = claim.line_items[0]

        with pytest.raises(BadRequestError):
            submit_dispute(
                claim.id,
                reason="CPT.",
                line_item_updates=[{"line_item_id": li.id, "cpt_code": ""}],
            )

    def test_whitespace_only_cpt_code_raises_bad_request(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """A whitespace-only cpt_code raises BadRequestError after stripping."""
        claim = _make_claim(seed, [("M54.5", "00000", Decimal("200.00"))])
        AdjudicationEngine().run(claim.id)  # → denied
        li = claim.line_items[0]

        with pytest.raises(BadRequestError):
            submit_dispute(
                claim.id,
                reason="CPT.",
                line_item_updates=[{"line_item_id": li.id, "cpt_code": "   "}],
            )

    def test_none_updates_behaves_as_before(self, app: Flask, seed: types.SimpleNamespace) -> None:
        """Passing line_item_updates=None creates a dispute with no mutations."""
        claim = _make_claim(seed, [("M54.5", "00000", Decimal("200.00"))])
        AdjudicationEngine().run(claim.id)  # → denied
        li = claim.line_items[0]
        original_cpt = li.cpt_code
        original_amount = li.billed_amount

        dispute = submit_dispute(claim.id, reason="No corrections.", line_item_updates=None)

        db.session.refresh(li)
        assert dispute.line_item_updates is None
        assert li.cpt_code == original_cpt
        assert li.billed_amount == original_amount

    def test_empty_list_behaves_as_before(self, app: Flask, seed: types.SimpleNamespace) -> None:
        """Passing an empty list creates a dispute with no mutations."""
        claim = _make_claim(seed, [("M54.5", "00000", Decimal("200.00"))])
        AdjudicationEngine().run(claim.id)  # → denied
        li = claim.line_items[0]
        original_amount = li.billed_amount

        dispute = submit_dispute(claim.id, reason="Empty list.", line_item_updates=[])

        db.session.refresh(li)
        assert dispute.line_item_updates is None
        assert li.billed_amount == original_amount

    def test_updates_stored_on_dispute(self, app: Flask, seed: types.SimpleNamespace) -> None:
        """The raw line_item_updates are stored on the Dispute row."""
        claim = _make_claim(seed, [("M54.5", "00000", Decimal("200.00"))])
        AdjudicationEngine().run(claim.id)  # → denied
        li = claim.line_items[0]
        updates = [{"line_item_id": li.id, "cpt_code": "99213"}]

        dispute = submit_dispute(claim.id, reason="Stored.", line_item_updates=updates)

        assert dispute.line_item_updates == updates

    def test_cpt_correction_auto_adjudicates_to_paid(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """Correcting CPT to a covered code auto-adjudicates to paid at dispute submission."""
        # Burn through deductible so plan_pays > 0 after correction
        claim = _make_claim(
            seed,
            [("M54.5", "00000", Decimal("700.00"))],
            deductible_met=Decimal("500.00"),
        )
        AdjudicationEngine().run(claim.id)  # → denied (00000 not covered)
        li = claim.line_items[0]

        submit_dispute(
            claim.id,
            reason="Wrong CPT, should be 99213.",
            line_item_updates=[{"line_item_id": li.id, "cpt_code": "99213"}],
        )

        # No manual trigger_readjudication needed — auto-adjudicated at submission.
        db.session.refresh(claim)
        assert claim.status == ClaimStatus.paid

    def test_dispute_with_corrections_not_under_review(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """After submitting a dispute with corrections, claim is not stuck at under_review."""
        claim = _make_claim(seed, [("M54.5", "00000", Decimal("200.00"))])
        AdjudicationEngine().run(claim.id)  # → denied
        li = claim.line_items[0]

        submit_dispute(
            claim.id,
            reason="Wrong CPT.",
            line_item_updates=[{"line_item_id": li.id, "cpt_code": "99213"}],
        )

        db.session.refresh(claim)
        assert claim.status != ClaimStatus.under_review

    def test_dispute_with_corrections_resolves_dispute(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """Dispute submitted with corrections is immediately resolved (no pending review)."""
        claim = _make_claim(seed, [("M54.5", "00000", Decimal("200.00"))])
        AdjudicationEngine().run(claim.id)  # → denied
        li = claim.line_items[0]

        dispute = submit_dispute(
            claim.id,
            reason="Wrong CPT.",
            line_item_updates=[{"line_item_id": li.id, "cpt_code": "99213"}],
        )

        assert dispute.status == DisputeStatus.resolved
        assert dispute.resolved_at is not None

    def test_dispute_with_corrections_sets_review_type_auto(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """Claim review_type is auto when corrections are provided."""
        claim = _make_claim(seed, [("M54.5", "00000", Decimal("200.00"))])
        AdjudicationEngine().run(claim.id)  # → denied
        li = claim.line_items[0]

        submit_dispute(
            claim.id,
            reason="Wrong CPT.",
            line_item_updates=[{"line_item_id": li.id, "cpt_code": "99213"}],
        )

        db.session.refresh(claim)
        assert claim.review_type == ReviewType.auto

    def test_trigger_readjudication_fails_after_auto_adjudication(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """trigger_readjudication raises ConflictError after auto-adjudicated dispute."""
        claim = _make_claim(seed, [("M54.5", "00000", Decimal("200.00"))])
        AdjudicationEngine().run(claim.id)  # → denied
        li = claim.line_items[0]

        submit_dispute(
            claim.id,
            reason="Wrong CPT.",
            line_item_updates=[{"line_item_id": li.id, "cpt_code": "99213"}],
        )

        with pytest.raises(ConflictError):
            trigger_readjudication(claim.id, reviewer_note=None)

    def test_only_cpt_update_uses_existing_amount_in_adjudication(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """When only cpt_code is corrected, the existing billed_amount drives adjudication."""
        claim = _make_claim(
            seed,
            [("M54.5", "00000", Decimal("300.00"))],
            deductible_met=Decimal("500.00"),
        )
        AdjudicationEngine().run(claim.id)  # → denied
        li = claim.line_items[0]

        submit_dispute(
            claim.id,
            reason="Wrong CPT, amount is correct.",
            line_item_updates=[{"line_item_id": li.id, "cpt_code": "99213"}],
        )

        db.session.refresh(li)
        assert li.cpt_code == "99213"
        assert li.billed_amount == Decimal("300.00")  # unchanged
        # adjudication result should use 300.00 as billed_amount
        assert li.latest_result is not None
        assert li.latest_result.is_covered is True

    def test_only_amount_update_uses_existing_cpt_in_adjudication(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """When only billed_amount is corrected, the existing cpt_code drives adjudication."""
        claim = _make_claim(seed, [("M54.5", "00000", Decimal("100.00"))])
        AdjudicationEngine().run(claim.id)  # → denied (00000 not covered)
        li = claim.line_items[0]
        original_cpt = li.cpt_code

        submit_dispute(
            claim.id,
            reason="Amount was wrong.",
            line_item_updates=[{"line_item_id": li.id, "billed_amount": "150.00"}],
        )

        db.session.refresh(li)
        assert li.cpt_code == original_cpt  # unchanged
        assert li.billed_amount == Decimal("150.00")
        # 00000 is still not covered, so still denied
        db.session.refresh(claim)
        assert claim.status == ClaimStatus.denied
