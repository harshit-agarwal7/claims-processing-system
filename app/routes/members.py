"""Blueprint for /api/members endpoints."""

import logging
from datetime import date

from flask import Blueprint, Response, jsonify, request

from app.errors import BadRequestError, ConflictError, NotFoundError
from app.extensions import db
from app.models import Claim, Member, Policy, PolicyStatus

logger = logging.getLogger(__name__)
bp = Blueprint("members", __name__, url_prefix="/api/members")


def _serialize_member(member: Member) -> dict[str, object]:
    """Serialise a Member ORM object to a JSON-safe dict.

    Args:
        member: The Member instance to serialise.

    Returns:
        A dict with member fields.
    """
    return {
        "id": member.id,
        "name": member.name,
        "date_of_birth": member.date_of_birth.isoformat(),
        "email": member.email,
        "phone": member.phone,
        "created_at": member.created_at.isoformat(),
    }


def _serialize_policy(policy: Policy) -> dict[str, object]:
    """Serialise a Policy ORM object to a JSON-safe dict.

    Args:
        policy: The Policy instance to serialise.

    Returns:
        A dict with policy and plan fields.
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
def create_member() -> tuple[Response, int]:
    """Create a new member.

    Returns:
        201 with the created member, or 400/409 on error.
    """
    data = request.get_json(silent=True) or {}

    name = data.get("name")
    date_of_birth_str = data.get("date_of_birth")
    email = data.get("email")

    if not name or not date_of_birth_str or not email:
        raise BadRequestError("name, date_of_birth, and email are required")

    try:
        dob = date.fromisoformat(date_of_birth_str)
    except ValueError as exc:
        raise BadRequestError("date_of_birth must be a valid ISO 8601 date (YYYY-MM-DD)") from exc

    existing = db.session.execute(
        db.select(Member).where(Member.email == email, Member.deleted_at.is_(None))
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(f"A member with email '{email}' already exists")

    member = Member(name=name, date_of_birth=dob, email=email, phone=data.get("phone"))
    db.session.add(member)
    db.session.commit()

    logger.info("member %s created", member.id)
    return jsonify(_serialize_member(member)), 201


@bp.route("/lookup", methods=["GET"])
def lookup_member_by_email() -> Response:
    """Look up a member by email address.

    Query params:
        email: The member's email address.

    Returns:
        200 with member data, 400 if email is missing, or 404 if not found.
    """
    email = request.args.get("email", "").strip()
    if not email:
        raise BadRequestError("email query parameter is required")

    member = db.session.execute(
        db.select(Member).where(Member.email == email, Member.deleted_at.is_(None))
    ).scalar_one_or_none()
    if member is None:
        raise NotFoundError(f"No member found with email '{email}'")

    return jsonify(_serialize_member(member))


@bp.route("/<member_id>", methods=["GET"])
def get_member(member_id: str) -> Response:
    """Retrieve a single member by ID.

    Args:
        member_id: UUID of the member.

    Returns:
        200 with member data, or 404 if not found.
    """
    member = db.session.execute(
        db.select(Member).where(Member.id == member_id, Member.deleted_at.is_(None))
    ).scalar_one_or_none()
    if member is None:
        raise NotFoundError(f"Member '{member_id}' not found")
    return jsonify(_serialize_member(member))


@bp.route("/<member_id>/claims", methods=["GET"])
def list_member_claims(member_id: str) -> Response:
    """List claim summaries for a member.

    Args:
        member_id: UUID of the member.

    Returns:
        200 with a list of claim summaries, or 404 if member not found.
    """
    member = db.session.execute(
        db.select(Member).where(Member.id == member_id, Member.deleted_at.is_(None))
    ).scalar_one_or_none()
    if member is None:
        raise NotFoundError(f"Member '{member_id}' not found")

    claims = (
        db.session.execute(
            db.select(Claim).where(Claim.member_id == member_id, Claim.deleted_at.is_(None))
        )
        .scalars()
        .all()
    )

    result = []
    for claim in claims:
        active_items = [li for li in claim.line_items if li.deleted_at is None]
        total_billed = sum(li.billed_amount for li in active_items)
        total_plan_pays = sum(
            li.latest_result.plan_pays for li in active_items if li.latest_result is not None
        )
        result.append(
            {
                "id": claim.id,
                "status": claim.status.value,
                "date_of_service": claim.date_of_service.isoformat(),
                "provider_name": claim.provider.name,
                "total_billed": str(total_billed),
                "total_plan_pays": str(total_plan_pays),
                "submitted_at": claim.submitted_at.isoformat(),
            }
        )

    return jsonify(result)


@bp.route("/<member_id>/policies/active", methods=["GET"])
def get_active_policy(member_id: str) -> Response:
    """Get the currently active policy for a member.

    Args:
        member_id: UUID of the member.

    Returns:
        200 with policy data, or 404 if member or active policy not found.
    """
    member = db.session.execute(
        db.select(Member).where(Member.id == member_id, Member.deleted_at.is_(None))
    ).scalar_one_or_none()
    if member is None:
        raise NotFoundError(f"Member '{member_id}' not found")

    today = date.today()
    policy = db.session.execute(
        db.select(Policy).where(
            Policy.member_id == member_id,
            Policy.status == PolicyStatus.active,
            Policy.start_date <= today,
            Policy.end_date >= today,
            Policy.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    if policy is None:
        raise NotFoundError(f"No active policy found for member '{member_id}'")

    return jsonify(_serialize_policy(policy))
