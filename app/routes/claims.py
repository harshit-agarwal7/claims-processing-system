"""Blueprint for /api/claims endpoints."""

import logging

from flask import Blueprint, Response, jsonify, request

from app.errors import BadRequestError, NotFoundError
from app.extensions import db
from app.models import AdjudicationResult, Claim, Dispute, LineItem, Payment
from app.services import claim_service, dispute_service

logger = logging.getLogger(__name__)
bp = Blueprint("claims", __name__, url_prefix="/api/claims")


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def _serialize_adjudication_result(result: AdjudicationResult) -> dict[str, object]:
    """Serialise an AdjudicationResult to a JSON-safe dict.

    Args:
        result: The AdjudicationResult instance.

    Returns:
        A dict with adjudication fields.
    """
    return {
        "is_covered": result.is_covered,
        "applied_to_deductible": str(result.applied_to_deductible),
        "plan_pays": str(result.plan_pays),
        "member_owes": str(result.member_owes),
        "explanation": result.explanation,
        "revision": result.revision,
        "adjudicated_at": result.adjudicated_at.isoformat(),
    }


def _serialize_line_item(li: LineItem) -> dict[str, object]:
    """Serialise a LineItem to a JSON-safe dict.

    Args:
        li: The LineItem instance.

    Returns:
        A dict with line item fields and the latest adjudication result (or null).
    """
    return {
        "id": li.id,
        "diagnosis_code": li.diagnosis_code,
        "cpt_code": li.cpt_code,
        "billed_amount": str(li.billed_amount),
        "adjudication_status": li.adjudication_status.value,
        "adjudication_result": (
            _serialize_adjudication_result(li.latest_result)
            if li.latest_result is not None
            else None
        ),
    }


def _serialize_dispute(dispute: Dispute) -> dict[str, object]:
    """Serialise a Dispute to a JSON-safe dict.

    Args:
        dispute: The Dispute instance.

    Returns:
        A dict with dispute fields.
    """
    return {
        "id": dispute.id,
        "claim_id": dispute.claim_id,
        "reason": dispute.reason,
        "status": dispute.status.value,
        "submitted_at": dispute.submitted_at.isoformat(),
        "resolved_at": dispute.resolved_at.isoformat() if dispute.resolved_at else None,
        "reviewer_note": dispute.reviewer_note,
    }


def _serialize_payment(payment: Payment) -> dict[str, object]:
    """Serialise a Payment to a JSON-safe dict.

    Args:
        payment: The Payment instance.

    Returns:
        A dict with payment fields.
    """
    return {
        "id": payment.id,
        "claim_id": payment.claim_id,
        "amount": str(payment.amount),
        "paid_at": payment.paid_at.isoformat(),
    }


def _serialize_claim(claim: Claim) -> dict[str, object]:
    """Serialise a Claim to the full detail response shape.

    Args:
        claim: The Claim instance with all relationships loaded.

    Returns:
        A dict matching the full claim detail response spec.
    """
    active_items = [li for li in claim.line_items if li.deleted_at is None]
    return {
        "id": claim.id,
        "status": claim.status.value,
        "review_type": claim.review_type.value,
        "date_of_service": claim.date_of_service.isoformat(),
        "submitted_at": claim.submitted_at.isoformat(),
        "updated_at": claim.updated_at.isoformat(),
        "member": {"id": claim.member.id, "name": claim.member.name},
        "provider": {
            "id": claim.provider.id,
            "name": claim.provider.name,
            "npi": claim.provider.npi,
        },
        "policy": {
            "id": claim.policy.id,
            "plan_name": claim.policy.plan.name,
            "deductible": str(claim.policy.plan.deductible),
            "start_date": claim.policy.start_date.isoformat(),
            "end_date": claim.policy.end_date.isoformat(),
        },
        "line_items": [_serialize_line_item(li) for li in active_items],
        "payment": _serialize_payment(claim.payment) if claim.payment is not None else None,
        "dispute": _serialize_dispute(claim.dispute) if claim.dispute is not None else None,
        "status_history": [
            {
                "from_status": h.from_status.value if h.from_status else None,
                "to_status": h.to_status.value,
                "transitioned_at": h.transitioned_at.isoformat(),
            }
            for h in claim.status_history
        ],
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@bp.route("", methods=["POST"])
def submit_claim() -> tuple[Response, int]:
    """Submit and auto-adjudicate a new claim.

    Returns:
        201 with full claim detail, or 400/404/422 on validation failure.
    """
    data = request.get_json(silent=True) or {}
    claim = claim_service.submit_claim(data)
    return jsonify(_serialize_claim(claim)), 201


@bp.route("/<claim_id>", methods=["GET"])
def get_claim(claim_id: str) -> Response:
    """Retrieve full detail for a single claim.

    Args:
        claim_id: UUID of the claim.

    Returns:
        200 with full claim detail, or 404 if not found.
    """
    claim: Claim | None = db.session.execute(
        db.select(Claim).where(Claim.id == claim_id, Claim.deleted_at.is_(None))
    ).scalar_one_or_none()
    if claim is None:
        raise NotFoundError(f"Claim '{claim_id}' not found")
    return jsonify(_serialize_claim(claim))


@bp.route("/<claim_id>/disputes", methods=["POST"])
def submit_dispute(claim_id: str) -> tuple[Response, int]:
    """Submit a dispute for a denied or partially-approved claim.

    Args:
        claim_id: UUID of the claim.

    Returns:
        201 with dispute data, or 400/404/409 on error.
    """
    data = request.get_json(silent=True) or {}
    reason: str = data.get("reason") or ""
    if not reason:
        raise BadRequestError("reason is required")
    dispute = dispute_service.submit_dispute(claim_id, reason)
    return jsonify(_serialize_dispute(dispute)), 201


@bp.route("/<claim_id>/dispute", methods=["GET"])
def get_dispute(claim_id: str) -> Response:
    """Retrieve the dispute for a claim.

    Args:
        claim_id: UUID of the claim.

    Returns:
        200 with dispute data, or 404 if claim or dispute not found.
    """
    claim: Claim | None = db.session.execute(
        db.select(Claim).where(Claim.id == claim_id, Claim.deleted_at.is_(None))
    ).scalar_one_or_none()
    if claim is None:
        raise NotFoundError(f"Claim '{claim_id}' not found")
    if claim.dispute is None:
        raise NotFoundError(f"No dispute found for claim '{claim_id}'")
    return jsonify(_serialize_dispute(claim.dispute))


@bp.route("/<claim_id>/adjudicate", methods=["POST"])
def trigger_readjudication(claim_id: str) -> Response:
    """Trigger manual re-adjudication of a disputed claim.

    Args:
        claim_id: UUID of the claim.

    Returns:
        200 with full claim detail after re-adjudication, or 404/409 on error.
    """
    data = request.get_json(silent=True) or {}
    reviewer_note: str | None = data.get("reviewer_note")
    claim = dispute_service.trigger_readjudication(claim_id, reviewer_note)
    return jsonify(_serialize_claim(claim))


@bp.route("/<claim_id>/accept", methods=["POST"])
def accept_payment(claim_id: str) -> Response:
    """Accept partial payment for a partially-approved claim.

    Args:
        claim_id: UUID of the claim.

    Returns:
        200 with payment data, or 409 on error.
    """
    payment = dispute_service.accept_payment(claim_id)
    return jsonify(_serialize_payment(payment))


@bp.route("/<claim_id>/payment", methods=["GET"])
def get_payment(claim_id: str) -> Response:
    """Retrieve the payment record for a claim.

    Args:
        claim_id: UUID of the claim.

    Returns:
        200 with payment data, or 404 if claim or payment not found.
    """
    claim: Claim | None = db.session.execute(
        db.select(Claim).where(Claim.id == claim_id, Claim.deleted_at.is_(None))
    ).scalar_one_or_none()
    if claim is None:
        raise NotFoundError(f"Claim '{claim_id}' not found")
    if claim.payment is None:
        raise NotFoundError(f"No payment found for claim '{claim_id}'")
    return jsonify(_serialize_payment(claim.payment))
