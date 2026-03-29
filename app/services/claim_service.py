"""Claim service — validate and persist a new claim, then trigger adjudication.

The adjudication engine owns the single ``db.session.commit()`` call for the
entire submit transaction.  This service flushes intermediate state but never
commits directly.
"""

import logging
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select

from app.errors import BadRequestError, NotFoundError, ValidationError
from app.extensions import db
from app.models import (
    Claim,
    ClaimStatus,
    ClaimStatusHistory,
    LineItem,
    Member,
    Policy,
    PolicyStatus,
    Provider,
    ReviewType,
)
from app.services.adjudication_engine import AdjudicationEngine

logger = logging.getLogger(__name__)


def submit_claim(data: dict[str, Any]) -> Claim:
    """Validate, persist, and auto-adjudicate a new claim.

    Steps:
    1. Validate required fields and line-item values (raises 400 on failure).
    2. Load Member — 404 if not found or soft-deleted.
    3. Find active Policy covering date_of_service — 422 if none.
    4. Load Provider — 404 if not found or soft-deleted.
    5. Create Claim(status=submitted, review_type=auto) + LineItem rows.
    6. Append ClaimStatusHistory(from_status=None, to_status=submitted).
    7. flush() — assigns IDs without committing; engine owns the commit.
    8. Call AdjudicationEngine().run(claim.id) — adjudicates and commits.
    9. Return refreshed claim.

    Args:
        data: Raw input dict with keys:
            - member_id (str, required)
            - provider_id (str, required)
            - date_of_service (str, ISO 8601 date, required)
            - line_items (list, required, non-empty; each item must have
              diagnosis_code, cpt_code, and billed_amount > 0)

    Returns:
        The refreshed Claim with its final adjudicated status.

    Raises:
        BadRequestError: If required fields are missing, date is unparseable,
            line_items is empty, or any line item has billed_amount <= 0.
        NotFoundError: If member_id or provider_id does not exist.
        ValidationError: If no active policy covers the date of service.
    """
    member_id: str | None = data.get("member_id")
    provider_id: str | None = data.get("provider_id")
    date_of_service_str: str | None = data.get("date_of_service")
    line_items_data = data.get("line_items")

    # 1. Validate required top-level fields
    if not member_id:
        raise BadRequestError("member_id is required")
    if not provider_id:
        raise BadRequestError("provider_id is required")
    if not date_of_service_str:
        raise BadRequestError("date_of_service is required")
    if line_items_data is None:
        raise BadRequestError("line_items is required and must be a non-empty list")
    if not isinstance(line_items_data, list) or len(line_items_data) == 0:
        raise BadRequestError("line_items must be a non-empty list")

    try:
        dos = date.fromisoformat(str(date_of_service_str))
    except ValueError as exc:
        raise BadRequestError("date_of_service must be a valid ISO 8601 date (YYYY-MM-DD)") from exc

    for item in line_items_data:
        if not item.get("diagnosis_code"):
            raise BadRequestError("Each line item must have a diagnosis_code")
        if not item.get("cpt_code"):
            raise BadRequestError("Each line item must have a cpt_code")
        billed_raw = item.get("billed_amount")
        if billed_raw is None:
            raise BadRequestError("Each line item must have a billed_amount")
        try:
            billed = Decimal(str(billed_raw))
        except InvalidOperation as exc:
            raise BadRequestError("billed_amount must be a valid number") from exc
        if billed <= Decimal("0"):
            raise BadRequestError("billed_amount must be greater than 0")

    # 2. Load Member
    member: Member | None = db.session.execute(
        select(Member).where(Member.id == member_id, Member.deleted_at.is_(None))
    ).scalar_one_or_none()
    if member is None:
        raise NotFoundError(f"Member '{member_id}' not found")

    # 3. Find active policy covering date of service
    policy: Policy | None = db.session.execute(
        select(Policy).where(
            Policy.member_id == member_id,
            Policy.status == PolicyStatus.active,
            Policy.start_date <= dos,
            Policy.end_date >= dos,
            Policy.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if policy is None:
        raise ValidationError("No active policy covers this date of service")

    # 4. Load Provider
    provider: Provider | None = db.session.execute(
        select(Provider).where(Provider.id == provider_id, Provider.deleted_at.is_(None))
    ).scalar_one_or_none()
    if provider is None:
        raise NotFoundError(f"Provider '{provider_id}' not found")

    # 5. Create Claim (flush to get claim.id before adding related rows)
    claim = Claim(
        member_id=member_id,
        policy_id=policy.id,
        provider_id=provider_id,
        date_of_service=dos,
        status=ClaimStatus.submitted,
        review_type=ReviewType.auto,
    )
    db.session.add(claim)
    db.session.flush()

    for item in line_items_data:
        db.session.add(
            LineItem(
                claim_id=claim.id,
                diagnosis_code=item["diagnosis_code"],
                cpt_code=item["cpt_code"],
                billed_amount=Decimal(str(item["billed_amount"])),
            )
        )

    # 6. Append initial status history
    db.session.add(
        ClaimStatusHistory(
            claim_id=claim.id,
            from_status=None,
            to_status=ClaimStatus.submitted,
        )
    )

    # 7. Flush to assign IDs — engine owns the single commit
    db.session.flush()

    # 8. Run adjudication (engine commits the entire transaction)
    AdjudicationEngine().run(claim.id)

    # 9. Return refreshed claim
    db.session.refresh(claim)
    logger.info("claim %s submitted; final status=%s", claim.id, claim.status.value)
    return claim
