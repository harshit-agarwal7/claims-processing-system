"""Blueprint for /api/policies endpoints."""

import logging
from datetime import date
from decimal import Decimal

from flask import Blueprint, Response, jsonify, request

from app.errors import BadRequestError, ConflictError, NotFoundError
from app.extensions import db
from app.models import Accumulator, Member, Plan, Policy, PolicyStatus

logger = logging.getLogger(__name__)
bp = Blueprint("policies", __name__, url_prefix="/api/policies")


def _serialize_policy(policy: Policy) -> dict[str, object]:
    """Serialise a Policy ORM object to a JSON-safe dict.

    Args:
        policy: The Policy instance to serialise.

    Returns:
        A dict with policy and associated plan fields.
    """
    return {
        "id": policy.id,
        "member_id": policy.member_id,
        "plan_id": policy.plan_id,
        "plan_name": policy.plan.name,
        "start_date": policy.start_date.isoformat(),
        "end_date": policy.end_date.isoformat(),
        "status": policy.status.value,
        "deductible": str(policy.plan.deductible),
        "created_at": policy.created_at.isoformat(),
    }


@bp.route("", methods=["POST"])
def create_policy() -> tuple[Response, int]:
    """Create a new policy and its associated accumulator.

    Returns:
        201 with the created policy, or 400/404 on error.
    """
    data = request.get_json(silent=True) or {}

    member_id = data.get("member_id")
    plan_id = data.get("plan_id")
    start_date_str = data.get("start_date")
    end_date_str = data.get("end_date")

    if not member_id or not plan_id or not start_date_str or not end_date_str:
        raise BadRequestError("member_id, plan_id, start_date, and end_date are required")

    try:
        start_date = date.fromisoformat(start_date_str)
    except ValueError as exc:
        raise BadRequestError("start_date must be a valid ISO 8601 date (YYYY-MM-DD)") from exc

    try:
        end_date = date.fromisoformat(end_date_str)
    except ValueError as exc:
        raise BadRequestError("end_date must be a valid ISO 8601 date (YYYY-MM-DD)") from exc

    if end_date < start_date:
        raise BadRequestError("end_date must be on or after start_date")

    member = db.session.execute(
        db.select(Member).where(Member.id == member_id, Member.deleted_at.is_(None))
    ).scalar_one_or_none()
    if member is None:
        raise NotFoundError(f"Member '{member_id}' not found")

    plan = db.session.execute(
        db.select(Plan).where(Plan.id == plan_id, Plan.deleted_at.is_(None))
    ).scalar_one_or_none()
    if plan is None:
        raise NotFoundError(f"Plan '{plan_id}' not found")

    existing_active = db.session.execute(
        db.select(Policy).where(
            Policy.member_id == member_id,
            Policy.status == PolicyStatus.active,
            Policy.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if existing_active is not None:
        raise ConflictError(f"Member '{member_id}' already has an active policy")

    policy = Policy(
        member_id=member_id,
        plan_id=plan_id,
        start_date=start_date,
        end_date=end_date,
        status=PolicyStatus.active,
    )
    db.session.add(policy)
    db.session.flush()

    accumulator = Accumulator(
        member_id=member_id,
        policy_id=policy.id,
        deductible_met=Decimal("0.00"),
    )
    db.session.add(accumulator)
    db.session.commit()

    db.session.refresh(policy)

    logger.info("policy %s created with accumulator %s", policy.id, accumulator.id)
    return jsonify(_serialize_policy(policy)), 201


@bp.route("/<policy_id>", methods=["GET"])
def get_policy(policy_id: str) -> Response:
    """Retrieve a single policy by ID.

    Args:
        policy_id: UUID of the policy.

    Returns:
        200 with policy data, or 404 if not found.
    """
    policy = db.session.execute(
        db.select(Policy).where(Policy.id == policy_id, Policy.deleted_at.is_(None))
    ).scalar_one_or_none()
    if policy is None:
        raise NotFoundError(f"Policy '{policy_id}' not found")
    return jsonify(_serialize_policy(policy))
