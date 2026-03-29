"""Dispute service — submit and manage member disputes on claims."""

import logging
from datetime import datetime
from decimal import Decimal

from app.errors import BadRequestError, ConflictError, NotFoundError
from app.extensions import db
from app.models import (
    Claim,
    ClaimStatus,
    ClaimStatusHistory,
    Dispute,
    DisputeStatus,
    LineItemStatus,
    Payment,
    ReviewType,
)

logger = logging.getLogger(__name__)


def submit_dispute(
    claim_id: str,
    reason: str,
    line_item_updates: list[dict[str, object]] | None = None,
) -> Dispute:
    """Submit a dispute for a denied or partially-approved claim.

    Transitions the claim to ``under_review`` with ``review_type=manual`` and
    creates a ``Dispute`` row with ``status=pending``.

    If *line_item_updates* is provided, the corrections are applied to the
    matching ``LineItem`` rows in-place before the status transition, so that
    re-adjudication uses the corrected data automatically.

    Args:
        claim_id: UUID string of the claim to dispute.
        reason: The member's reason for disputing the claim.
        line_item_updates: Optional list of per-line-item corrections.  Each
            entry must include ``line_item_id`` and at least one of
            ``billed_amount`` (positive Decimal-compatible string) or
            ``cpt_code`` (non-empty string).

    Returns:
        The newly created Dispute.

    Raises:
        NotFoundError: If no claim with *claim_id* exists.
        ConflictError: If the claim status does not allow a dispute (not
            ``denied`` or ``partially_approved``), or if the claim has already
            been disputed.
        BadRequestError: If any *line_item_id* does not belong to the claim,
            *billed_amount* is not positive, or *cpt_code* is empty.
    """
    claim: Claim | None = db.session.get(Claim, claim_id)
    if claim is None:
        raise NotFoundError(f"Claim {claim_id!r} not found")

    if claim.status not in (ClaimStatus.denied, ClaimStatus.partially_approved):
        raise ConflictError(
            f"Cannot dispute a claim with status '{claim.status.value}'. "
            "Only 'denied' or 'partially_approved' claims may be disputed."
        )

    if claim.dispute is not None:
        raise ConflictError("This claim has already been disputed and cannot be disputed again.")

    old_status = claim.status
    claim.status = ClaimStatus.under_review

    if line_item_updates:
        # Apply corrections in-place so re-adjudication uses the corrected data.
        # Only provided fields are updated; omitted fields retain their current values.
        li_index = {li.id: li for li in claim.line_items if li.deleted_at is None}
        for upd in line_item_updates:
            li_id = upd.get("line_item_id")
            if not li_id or li_id not in li_index:
                raise BadRequestError(f"Line item {li_id!r} does not belong to claim {claim_id!r}")
            li = li_index[str(li_id)]
            if "billed_amount" in upd:
                try:
                    amount = Decimal(str(upd["billed_amount"]))
                except Exception:
                    raise BadRequestError("billed_amount must be a valid number")
                if amount <= Decimal("0"):
                    raise BadRequestError("billed_amount must be greater than 0")
                li.billed_amount = amount
            if "cpt_code" in upd:
                cpt = str(upd["cpt_code"]).strip()
                if not cpt:
                    raise BadRequestError("cpt_code must be a non-empty string")
                li.cpt_code = cpt

        # Corrections provided — auto-adjudicate immediately; no manual review needed.
        claim.review_type = ReviewType.auto
        db.session.add(
            ClaimStatusHistory(
                claim_id=claim.id,
                from_status=old_status,
                to_status=ClaimStatus.under_review,
                note="Dispute submitted by member with corrections; auto-adjudicating.",
            )
        )
        dispute = Dispute(
            claim_id=claim.id,
            reason=reason,
            line_item_updates=line_item_updates,
            status=DisputeStatus.resolved,
            resolved_at=datetime.utcnow(),
        )
        # Assign via relationship so SQLAlchemy back-populates claim.dispute in-memory,
        # allowing the adjudication engine to detect the resolved dispute in step 8.
        claim.dispute = dispute
        db.session.flush()

        # Import here to avoid circular imports at module load time
        from app.services.adjudication_engine import AdjudicationEngine

        AdjudicationEngine().run(claim.id)

        db.session.refresh(dispute)
        logger.info(
            "claim %s dispute with corrections submitted; auto-adjudicated; final status=%s",
            claim.id,
            claim.status.value,
        )
        return dispute

    # No corrections — manual review required.
    claim.review_type = ReviewType.manual
    db.session.add(
        ClaimStatusHistory(
            claim_id=claim.id,
            from_status=old_status,
            to_status=ClaimStatus.under_review,
            note="Dispute submitted by member.",
        )
    )
    dispute = Dispute(
        claim_id=claim.id,
        reason=reason,
        line_item_updates=None,
    )
    db.session.add(dispute)
    db.session.commit()

    logger.info(
        "claim %s dispute submitted; transitioned %s → under_review",
        claim.id,
        old_status.value,
    )
    return dispute


def trigger_readjudication(claim_id: str, reviewer_note: str | None) -> Claim:
    """Resolve a pending dispute and trigger re-adjudication.

    Marks the dispute as resolved, then delegates to AdjudicationEngine which
    commits the entire transaction.  The engine auto-pays if the re-adjudication
    result is ``partially_approved`` (dispute already resolved, no further
    dispute is possible).

    Args:
        claim_id: UUID string of the claim to re-adjudicate.
        reviewer_note: Optional note from the reviewer; stored on the Dispute.

    Returns:
        The refreshed Claim with its new final status.

    Raises:
        ConflictError: If the claim is not ``under_review`` with
            ``review_type=manual``, or if the dispute is already resolved.
        NotFoundError: If no claim or no dispute exists for *claim_id*.
    """
    claim: Claim | None = db.session.get(Claim, claim_id)
    if claim is None:
        raise NotFoundError(f"Claim {claim_id!r} not found")

    if claim.status != ClaimStatus.under_review or claim.review_type != ReviewType.manual:
        raise ConflictError("Claim is not awaiting manual review")

    dispute: Dispute | None = claim.dispute
    if dispute is None:
        raise NotFoundError(f"No dispute found for claim {claim_id!r}")
    if dispute.status != DisputeStatus.pending:
        raise ConflictError("Dispute is already resolved")

    if reviewer_note is not None:
        dispute.reviewer_note = reviewer_note
    dispute.status = DisputeStatus.resolved
    dispute.resolved_at = datetime.utcnow()
    db.session.flush()

    # Import here to avoid circular imports at module load time
    from app.services.adjudication_engine import AdjudicationEngine

    AdjudicationEngine().run(claim.id)

    db.session.refresh(claim)
    logger.info("claim %s re-adjudicated; final status=%s", claim.id, claim.status.value)
    return claim


def accept_payment(claim_id: str) -> Payment:
    """Accept partial payment for a partially-approved claim (no active dispute).

    Creates a Payment row for the sum of plan_pays on approved line items and
    transitions the claim to ``paid``.

    Args:
        claim_id: UUID string of the claim.

    Returns:
        The newly created Payment.

    Raises:
        ConflictError: If the claim is not ``partially_approved``, or if a
            Dispute row already exists for this claim.
        NotFoundError: If no claim exists for *claim_id*.
    """
    claim: Claim | None = db.session.get(Claim, claim_id)
    if claim is None:
        raise NotFoundError(f"Claim {claim_id!r} not found")

    if claim.status != ClaimStatus.partially_approved:
        raise ConflictError(f"Cannot accept payment for a claim with status '{claim.status.value}'")

    if claim.dispute is not None:
        raise ConflictError("Dispute already filed; cannot accept partial payment")

    approved_pays: Decimal = sum(  # type: ignore[assignment]
        li.latest_result.plan_pays
        for li in claim.line_items
        if li.deleted_at is None
        and li.adjudication_status == LineItemStatus.approved
        and li.latest_result is not None
    )

    payment = Payment(claim_id=claim.id, amount=approved_pays)
    db.session.add(payment)

    old_status = claim.status
    claim.status = ClaimStatus.paid
    db.session.add(
        ClaimStatusHistory(
            claim_id=claim.id,
            from_status=old_status,
            to_status=ClaimStatus.paid,
        )
    )
    db.session.commit()

    logger.info("claim %s accepted partial payment; amount=%s", claim.id, approved_pays)
    return payment
