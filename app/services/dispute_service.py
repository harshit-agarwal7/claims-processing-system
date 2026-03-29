"""Dispute service — submit and manage member disputes on claims.

Phase 6 implements ``submit_dispute`` (the guard-rail logic needed by the
state-machine tests).  Re-adjudication orchestration is added in Phase 8.
"""

import logging

from app.errors import ConflictError, NotFoundError
from app.extensions import db
from app.models import Claim, ClaimStatus, ClaimStatusHistory, Dispute, ReviewType

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
