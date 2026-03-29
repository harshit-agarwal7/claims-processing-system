"""Blueprint for /api/plans endpoints."""

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, Response, jsonify, request

from app.errors import BadRequestError, NotFoundError
from app.extensions import db
from app.models import CoverageRule, Plan

logger = logging.getLogger(__name__)
bp = Blueprint("plans", __name__, url_prefix="/api/plans")


def _serialize_rule(rule: CoverageRule) -> dict[str, object]:
    """Serialise a CoverageRule ORM object to a JSON-safe dict.

    Args:
        rule: The CoverageRule instance to serialise.

    Returns:
        A dict with coverage rule fields.
    """
    return {
        "cpt_code": rule.cpt_code,
        "is_covered": rule.is_covered,
        "coverage_percentage": str(rule.coverage_percentage),
    }


def _serialize_plan(plan: Plan) -> dict[str, object]:
    """Serialise a Plan ORM object to a JSON-safe dict including active rules.

    Args:
        plan: The Plan instance to serialise.

    Returns:
        A dict with plan fields and active coverage rules.
    """
    active_rules = [r for r in plan.coverage_rules if r.deleted_at is None]
    return {
        "id": plan.id,
        "name": plan.name,
        "deductible": str(plan.deductible),
        "coverage_rules": [_serialize_rule(r) for r in active_rules],
        "created_at": plan.created_at.isoformat(),
    }


def _parse_coverage_percentage(raw: object, label: str) -> Decimal:
    """Parse and validate a coverage percentage value.

    Args:
        raw: The raw value from the request body.
        label: A label used in error messages (e.g. the CPT code).

    Returns:
        A Decimal in [0, 1].

    Raises:
        BadRequestError: If the value is not a valid number or out of range.
    """
    try:
        pct = Decimal(str(raw))
    except InvalidOperation as exc:
        raise BadRequestError(f"coverage_percentage for '{label}' must be a valid number") from exc
    if not (Decimal("0") <= pct <= Decimal("1")):
        raise BadRequestError(f"coverage_percentage for '{label}' must be between 0 and 1")
    return pct


@bp.route("", methods=["GET"])
def list_plans() -> Response:
    """List all active plans with their coverage rules.

    Returns:
        200 with a list of plans.
    """
    plans = db.session.execute(db.select(Plan).where(Plan.deleted_at.is_(None))).scalars().all()
    return jsonify([_serialize_plan(p) for p in plans])


@bp.route("", methods=["POST"])
def create_plan() -> tuple[Response, int]:
    """Create a new plan with optional coverage rules.

    Returns:
        201 with the created plan and its rules, or 400 on error.
    """
    data = request.get_json(silent=True) or {}

    name = data.get("name")
    deductible_raw = data.get("deductible")

    if not name or deductible_raw is None:
        raise BadRequestError("name and deductible are required")

    try:
        deductible = Decimal(str(deductible_raw))
    except InvalidOperation as exc:
        raise BadRequestError("deductible must be a valid number") from exc

    if deductible < Decimal("0"):
        raise BadRequestError("deductible must be non-negative")

    plan = Plan(name=name, deductible=deductible)
    db.session.add(plan)
    db.session.flush()

    for rule_data in data.get("coverage_rules", []):
        cpt_code = rule_data.get("cpt_code")
        is_covered = rule_data.get("is_covered")
        coverage_pct_raw = rule_data.get("coverage_percentage")

        if not cpt_code or is_covered is None or coverage_pct_raw is None:
            raise BadRequestError(
                "Each coverage rule requires cpt_code, is_covered, and coverage_percentage"
            )

        coverage_pct = _parse_coverage_percentage(coverage_pct_raw, cpt_code)
        rule = CoverageRule(
            plan_id=plan.id,
            cpt_code=cpt_code,
            is_covered=bool(is_covered),
            coverage_percentage=coverage_pct,
        )
        db.session.add(rule)

    db.session.commit()
    db.session.refresh(plan)

    logger.info("plan %s created", plan.id)
    return jsonify(_serialize_plan(plan)), 201


@bp.route("/<plan_id>", methods=["GET"])
def get_plan(plan_id: str) -> Response:
    """Retrieve a single plan with its active coverage rules.

    Args:
        plan_id: UUID of the plan.

    Returns:
        200 with plan data, or 404 if not found.
    """
    plan = db.session.execute(
        db.select(Plan).where(Plan.id == plan_id, Plan.deleted_at.is_(None))
    ).scalar_one_or_none()
    if plan is None:
        raise NotFoundError(f"Plan '{plan_id}' not found")
    return jsonify(_serialize_plan(plan))


@bp.route("/<plan_id>/coverage-rules/<cpt_code>", methods=["PUT"])
def upsert_coverage_rule(plan_id: str, cpt_code: str) -> tuple[Response, int]:
    """Upsert a coverage rule for a CPT code on a plan.

    Soft-deletes any existing active rule for the CPT code, then inserts a new one.

    Args:
        plan_id: UUID of the plan.
        cpt_code: The CPT procedure code.

    Returns:
        200 with the new rule, or 400/404 on error.
    """
    plan = db.session.execute(
        db.select(Plan).where(Plan.id == plan_id, Plan.deleted_at.is_(None))
    ).scalar_one_or_none()
    if plan is None:
        raise NotFoundError(f"Plan '{plan_id}' not found")

    data = request.get_json(silent=True) or {}
    is_covered = data.get("is_covered")
    coverage_pct_raw = data.get("coverage_percentage")

    if is_covered is None or coverage_pct_raw is None:
        raise BadRequestError("is_covered and coverage_percentage are required")

    coverage_pct = _parse_coverage_percentage(coverage_pct_raw, cpt_code)

    existing = db.session.execute(
        db.select(CoverageRule).where(
            CoverageRule.plan_id == plan_id,
            CoverageRule.cpt_code == cpt_code,
            CoverageRule.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.deleted_at = datetime.utcnow()

    new_rule = CoverageRule(
        plan_id=plan_id,
        cpt_code=cpt_code,
        is_covered=bool(is_covered),
        coverage_percentage=coverage_pct,
    )
    db.session.add(new_rule)
    db.session.commit()

    logger.info("coverage rule plan=%s cpt=%s upserted", plan_id, cpt_code)
    return jsonify(_serialize_rule(new_rule)), 200


@bp.route("/<plan_id>/coverage-rules/<cpt_code>", methods=["DELETE"])
def delete_coverage_rule(plan_id: str, cpt_code: str) -> tuple[Response, int]:
    """Soft-delete an active coverage rule for a CPT code on a plan.

    Args:
        plan_id: UUID of the plan.
        cpt_code: The CPT procedure code.

    Returns:
        204 on success, or 404 if plan or rule not found.
    """
    plan = db.session.execute(
        db.select(Plan).where(Plan.id == plan_id, Plan.deleted_at.is_(None))
    ).scalar_one_or_none()
    if plan is None:
        raise NotFoundError(f"Plan '{plan_id}' not found")

    rule = db.session.execute(
        db.select(CoverageRule).where(
            CoverageRule.plan_id == plan_id,
            CoverageRule.cpt_code == cpt_code,
            CoverageRule.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    if rule is None:
        raise NotFoundError(
            f"No active coverage rule for CPT code '{cpt_code}' on plan '{plan_id}'"
        )

    rule.deleted_at = datetime.utcnow()
    db.session.commit()

    logger.info("coverage rule plan=%s cpt=%s deleted", plan_id, cpt_code)
    return jsonify({}), 204
