"""Dispute service — submit and manage member disputes on claims."""

import logging
from datetime import datetime
from decimal import Decimal

from app.errors import ConflictError, NotFoundError
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


def submit_dispute(claim_id: str, reason: str) -> Dispute:
    """Submit a dispute for a denied or partially-approved claim.

    Transitions the claim to ``under_review`` with ``review_type=manual`` and
    creates a ``Dispute`` row with ``status=pending``.

    Args:
        claim_id: UUID string of the claim to dispute.
        reason: The member's reason for disputing the claim.

    Returns:
        The newly created Dispute.

    Raises:
        NotFoundError: If no claim with *claim_id* exists.
        ConflictError: If the claim status does not allow a dispute (not
            ``denied`` or ``partially_approved``), or if the claim has already
            been disputed.
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
    claim.review_type = ReviewType.manual

    db.session.add(
        ClaimStatusHistory(
            claim_id=claim.id,
            from_status=old_status,
            to_status=ClaimStatus.under_review,
            note="Dispute submitted by member.",
        )
    )

    dispute = Dispute(claim_id=claim.id, reason=reason)
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
