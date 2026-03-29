"""Unit tests for AdjudicationEngine — math, deductible tracking, and edge cases.

All tests call the engine directly against an in-memory DB (via the conftest
fixtures) and assert on the persisted AdjudicationResult rows plus the
accumulator state.

The ``app`` fixture provides an active app context for the duration of each
test, so no nested ``with app.app_context():`` blocks are used here.
"""

import types
from datetime import date
from decimal import Decimal

from flask import Flask

from app.extensions import db
from app.models import (
    Accumulator,
    Claim,
    ClaimStatus,
    CoverageRule,
    LineItem,
    LineItemStatus,
    Policy,
    PolicyStatus,
    ReviewType,
)
from app.services.adjudication_engine import AdjudicationEngine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_claim(
    seed: types.SimpleNamespace,
    line_items: list[tuple[str, str, Decimal]],
    *,
    deductible_met: Decimal | None = None,
    date_of_service: date = date(2026, 3, 1),
) -> Claim:
    """Create a Claim with the given line items, optionally update the accumulator, and flush.

    Args:
        seed: The seed fixture namespace.
        line_items: List of (diagnosis_code, cpt_code, billed_amount) tuples.
        deductible_met: If provided, overrides ``seed.accumulator.deductible_met`` in the DB.
            Omit to leave the accumulator unchanged (e.g. for sequential claims).
        date_of_service: Date the services were rendered.

    Returns:
        The flushed (but not yet adjudicated) Claim.
    """
    if deductible_met is not None:
        seed.accumulator.deductible_met = deductible_met
        db.session.flush()

    claim = Claim(
        member_id=seed.member.id,
        policy_id=seed.policy.id,
        provider_id=seed.provider.id,
        date_of_service=date_of_service,
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
# Math scenarios
# ---------------------------------------------------------------------------


class TestAdjudicationMath:
    """Verify the per-line-item adjudication arithmetic."""

    def test_full_deductible_remaining(self, app: Flask, seed: types.SimpleNamespace) -> None:
        """billed=150, ded=500, met=0 → applied=150, plan_pays=0, member_owes=150."""
        claim = _make_claim(seed, [("M54.5", "99213", Decimal("150.00"))])
        result_claim = AdjudicationEngine().run(claim.id)

        li = result_claim.line_items[0]
        r = li.latest_result
        assert r is not None
        assert r.is_covered is True
        assert r.applied_to_deductible == Decimal("150.00")
        assert r.plan_pays == Decimal("0.00")
        assert r.member_owes == Decimal("150.00")
        assert li.adjudication_status == LineItemStatus.approved

    def test_partial_deductible_remaining(self, app: Flask, seed: types.SimpleNamespace) -> None:
        """billed=300, ded=500, met=300 → applied=200, plan_pays=80, member_owes=220."""
        claim = _make_claim(
            seed,
            [("M54.5", "99213", Decimal("300.00"))],
            deductible_met=Decimal("300.00"),
        )
        result_claim = AdjudicationEngine().run(claim.id)

        li = result_claim.line_items[0]
        r = li.latest_result
        assert r is not None
        assert r.applied_to_deductible == Decimal("200.00")
        assert r.plan_pays == Decimal("80.00")
        assert r.member_owes == Decimal("220.00")

    def test_deductible_fully_met(self, app: Flask, seed: types.SimpleNamespace) -> None:
        """billed=200, ded=500, met=500 → applied=0, plan_pays=160, member_owes=40."""
        claim = _make_claim(
            seed,
            [("M54.5", "99213", Decimal("200.00"))],
            deductible_met=Decimal("500.00"),
        )
        result_claim = AdjudicationEngine().run(claim.id)

        li = result_claim.line_items[0]
        r = li.latest_result
        assert r is not None
        assert r.applied_to_deductible == Decimal("0.00")
        assert r.plan_pays == Decimal("160.00")
        assert r.member_owes == Decimal("40.00")

    def test_cpt_not_covered_is_denied(self, app: Flask, seed: types.SimpleNamespace) -> None:
        """CPT code with is_covered=False → denied, applied=0, plan_pays=0, member_owes=billed."""
        db.session.add(
            CoverageRule(
                plan_id=seed.plan.id,
                cpt_code="99999",
                is_covered=False,
                coverage_percentage=Decimal("0.0000"),
            )
        )
        db.session.flush()

        claim = _make_claim(seed, [("M54.5", "99999", Decimal("200.00"))])
        result_claim = AdjudicationEngine().run(claim.id)

        li = result_claim.line_items[0]
        r = li.latest_result
        assert r is not None
        assert r.is_covered is False
        assert r.applied_to_deductible == Decimal("0.00")
        assert r.plan_pays == Decimal("0.00")
        assert r.member_owes == Decimal("200.00")
        assert li.adjudication_status == LineItemStatus.denied

    def test_cpt_absent_from_plan_is_denied(self, app: Flask, seed: types.SimpleNamespace) -> None:
        """CPT code with no rule on plan → denied, member owes full billed amount."""
        claim = _make_claim(seed, [("M54.5", "00000", Decimal("200.00"))])
        result_claim = AdjudicationEngine().run(claim.id)

        li = result_claim.line_items[0]
        r = li.latest_result
        assert r is not None
        assert r.is_covered is False
        assert r.plan_pays == Decimal("0.00")
        assert r.member_owes == Decimal("200.00")

    def test_multi_item_deductible_consumed_across_line_items(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """3 line items at $300 each, deductible=500, met=0.

        Item 1: remaining=500 → applied=300, plan_pays=0, member_owes=300
        Item 2: remaining=200 → applied=200, plan_pays=80, member_owes=220
        Item 3: remaining=0   → applied=0,   plan_pays=240, member_owes=60
        Accumulator after: deductible_met=500
        """
        claim = _make_claim(
            seed,
            [
                ("M54.5", "99213", Decimal("300.00")),
                ("M54.5", "99213", Decimal("300.00")),
                ("M54.5", "99213", Decimal("300.00")),
            ],
        )
        AdjudicationEngine().run(claim.id)

        refreshed = db.session.get(Claim, claim.id)
        assert refreshed is not None
        items = sorted(refreshed.line_items, key=lambda li: li.id)

        r0 = items[0].latest_result
        r1 = items[1].latest_result
        r2 = items[2].latest_result
        assert r0 is not None and r1 is not None and r2 is not None

        assert r0.applied_to_deductible == Decimal("300.00")
        assert r0.plan_pays == Decimal("0.00")
        assert r0.member_owes == Decimal("300.00")

        assert r1.applied_to_deductible == Decimal("200.00")
        assert r1.plan_pays == Decimal("80.00")
        assert r1.member_owes == Decimal("220.00")

        assert r2.applied_to_deductible == Decimal("0.00")
        assert r2.plan_pays == Decimal("240.00")
        assert r2.member_owes == Decimal("60.00")

        acc = db.session.get(Accumulator, seed.accumulator.id)
        assert acc is not None
        assert acc.deductible_met == Decimal("500.00")

    def test_explanation_denied(self, app: Flask, seed: types.SimpleNamespace) -> None:
        """Denied explanation references the CPT code."""
        claim = _make_claim(seed, [("M54.5", "00000", Decimal("100.00"))])
        result_claim = AdjudicationEngine().run(claim.id)

        r = result_claim.line_items[0].latest_result
        assert r is not None
        assert "00000" in r.explanation
        assert "not covered" in r.explanation.lower()

    def test_explanation_approved(self, app: Flask, seed: types.SimpleNamespace) -> None:
        """Approved explanation mentions coverage percentage, deductible, and amounts."""
        claim = _make_claim(
            seed,
            [("M54.5", "99213", Decimal("200.00"))],
            deductible_met=Decimal("500.00"),
        )
        result_claim = AdjudicationEngine().run(claim.id)

        r = result_claim.line_items[0].latest_result
        assert r is not None
        assert "99213" in r.explanation
        assert "80" in r.explanation  # coverage percentage

    def test_revision_increments_on_readjudication(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """Second engine run on the same claim produces revision=2 results."""
        claim = _make_claim(seed, [("M54.5", "99213", Decimal("200.00"))])
        engine = AdjudicationEngine()
        engine.run(claim.id)

        # Reset to under_review for second pass (simulates re-adjudication)
        refreshed = db.session.get(Claim, claim.id)
        assert refreshed is not None
        refreshed.status = ClaimStatus.under_review
        db.session.commit()

        engine.run(claim.id)

        final = db.session.get(Claim, claim.id)
        assert final is not None
        li = final.line_items[0]

        assert li.latest_result is not None
        assert li.latest_result.revision == 2
        assert len(li.results) == 2


# ---------------------------------------------------------------------------
# Deductible tracking across claims
# ---------------------------------------------------------------------------


class TestDeductibleTracking:
    """Deductible accumulator is updated correctly across sequential claims."""

    def test_accumulator_updated_after_claim(self, app: Flask, seed: types.SimpleNamespace) -> None:
        """First claim consuming $300 of $500 deductible → accumulator.deductible_met=300."""
        claim = _make_claim(seed, [("M54.5", "99213", Decimal("300.00"))])
        AdjudicationEngine().run(claim.id)

        acc = db.session.get(Accumulator, seed.accumulator.id)
        assert acc is not None
        assert acc.deductible_met == Decimal("300.00")

    def test_second_claim_uses_updated_accumulator(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """Claim 1 → met=300; Claim 2 uses remaining $200 then coverage kicks in."""
        claim1 = _make_claim(seed, [("M54.5", "99213", Decimal("300.00"))])
        AdjudicationEngine().run(claim1.id)

        # Second claim: billed=300, remaining ded=200
        claim2 = _make_claim(seed, [("M54.5", "99213", Decimal("300.00"))])
        AdjudicationEngine().run(claim2.id)

        refreshed2 = db.session.get(Claim, claim2.id)
        assert refreshed2 is not None
        r = refreshed2.line_items[0].latest_result

        assert r is not None
        assert r.applied_to_deductible == Decimal("200.00")
        assert r.plan_pays == Decimal("80.00")
        assert r.member_owes == Decimal("220.00")

    def test_new_policy_period_fresh_accumulator(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """A new policy period starts with deductible_met=0; old accumulator is untouched."""
        # Consume old accumulator fully
        claim1 = _make_claim(seed, [("M54.5", "99213", Decimal("500.00"))])
        AdjudicationEngine().run(claim1.id)

        old_acc = db.session.get(Accumulator, seed.accumulator.id)
        assert old_acc is not None
        assert old_acc.deductible_met == Decimal("500.00")

        # New policy period for the same member + plan
        new_policy = Policy(
            member_id=seed.member.id,
            plan_id=seed.plan.id,
            start_date=date(2027, 1, 1),
            end_date=date(2027, 12, 31),
            status=PolicyStatus.active,
        )
        db.session.add(new_policy)
        db.session.flush()

        new_acc = Accumulator(
            member_id=seed.member.id,
            policy_id=new_policy.id,
            deductible_met=Decimal("0.00"),
        )
        db.session.add(new_acc)
        db.session.commit()

        claim2 = Claim(
            member_id=seed.member.id,
            policy_id=new_policy.id,
            provider_id=seed.provider.id,
            date_of_service=date(2027, 3, 1),
            status=ClaimStatus.submitted,
            review_type=ReviewType.auto,
        )
        db.session.add(claim2)
        db.session.flush()
        db.session.add(
            LineItem(
                claim_id=claim2.id,
                diagnosis_code="M54.5",
                cpt_code="99213",
                billed_amount=Decimal("200.00"),
            )
        )
        db.session.flush()

        AdjudicationEngine().run(claim2.id)

        refreshed_new_acc = db.session.get(Accumulator, new_acc.id)
        refreshed_old_acc = db.session.get(Accumulator, seed.accumulator.id)
        assert refreshed_new_acc is not None
        assert refreshed_old_acc is not None
        # New period: applied=min(200,500)=200
        assert refreshed_new_acc.deductible_met == Decimal("200.00")
        # Old accumulator must not change
        assert refreshed_old_acc.deductible_met == Decimal("500.00")


# ---------------------------------------------------------------------------
# Claim status history audit trail
# ---------------------------------------------------------------------------


class TestStatusHistory:
    """The engine writes a complete, ordered audit trail for each claim."""

    def test_status_history_submitted_to_approved_to_paid(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """Approved claim should have submitted→under_review, under_review→approved,
        approved→paid history entries."""
        claim = _make_claim(
            seed,
            [("M54.5", "99213", Decimal("200.00"))],
            deductible_met=Decimal("500.00"),
        )
        result_claim = AdjudicationEngine().run(claim.id)

        transitions = [(h.from_status, h.to_status) for h in result_claim.status_history]
        assert (ClaimStatus.submitted, ClaimStatus.under_review) in transitions
        assert (ClaimStatus.under_review, ClaimStatus.approved) in transitions
        assert (ClaimStatus.approved, ClaimStatus.paid) in transitions

    def test_status_history_submitted_to_denied(
        self, app: Flask, seed: types.SimpleNamespace
    ) -> None:
        """Denied claim should have submitted→under_review and under_review→denied entries."""
        claim = _make_claim(seed, [("M54.5", "00000", Decimal("200.00"))])
        result_claim = AdjudicationEngine().run(claim.id)

        transitions = [(h.from_status, h.to_status) for h in result_claim.status_history]
        assert (ClaimStatus.submitted, ClaimStatus.under_review) in transitions
        assert (ClaimStatus.under_review, ClaimStatus.denied) in transitions
        assert not any(h.to_status == ClaimStatus.paid for h in result_claim.status_history)
