"""All enums and ORM models for the claims processing system.

Models are defined in FK-dependency order so SQLAlchemy can resolve
relationships without forward-reference strings:
Member → Provider → Plan → CoverageRule → Policy → Accumulator →
Claim → ClaimStatusHistory → AdjudicationResult → LineItem → Dispute → Payment
"""

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .extensions import Base

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ProviderType(enum.Enum):
    individual = "individual"
    facility = "facility"


class PolicyStatus(enum.Enum):
    active = "active"
    expired = "expired"
    cancelled = "cancelled"


class ClaimStatus(enum.Enum):
    submitted = "submitted"
    under_review = "under_review"
    approved = "approved"
    denied = "denied"
    partially_approved = "partially_approved"
    paid = "paid"


class ReviewType(enum.Enum):
    auto = "auto"
    manual = "manual"


class LineItemStatus(enum.Enum):
    pending = "pending"
    approved = "approved"
    denied = "denied"


class DisputeStatus(enum.Enum):
    pending = "pending"
    resolved = "resolved"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Member(Base):
    """An individual insured person."""

    __tablename__ = "members"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    policies: Mapped[list["Policy"]] = relationship("Policy", back_populates="member")
    claims: Mapped[list["Claim"]] = relationship("Claim", back_populates="member")
    accumulators: Mapped[list["Accumulator"]] = relationship("Accumulator", back_populates="member")


class Provider(Base):
    """A healthcare professional or facility."""

    __tablename__ = "providers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    npi: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    provider_type: Mapped[ProviderType] = mapped_column(Enum(ProviderType), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Plan(Base):
    """Benefit structure template: coverage rules and deductible amount."""

    __tablename__ = "plans"
    __table_args__ = (CheckConstraint("deductible >= 0", name="ck_plans_deductible_non_negative"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    deductible: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    coverage_rules: Mapped[list["CoverageRule"]] = relationship(
        "CoverageRule", back_populates="plan"
    )
    policies: Mapped[list["Policy"]] = relationship("Policy", back_populates="plan")


class CoverageRule(Base):
    """Coverage definition for a single CPT code on a plan.

    The (plan_id, cpt_code) uniqueness constraint for active rules is enforced
    at the service layer because SQLite lacks partial indexes without triggers.
    """

    __tablename__ = "coverage_rules"
    __table_args__ = (
        CheckConstraint(
            "coverage_percentage >= 0 AND coverage_percentage <= 1",
            name="ck_coverage_rules_percentage_range",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    plan_id: Mapped[str] = mapped_column(String(36), ForeignKey("plans.id"), nullable=False)
    cpt_code: Mapped[str] = mapped_column(String(20), nullable=False)
    is_covered: Mapped[bool] = mapped_column(Boolean, nullable=False)
    coverage_percentage: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    plan: Mapped[Plan] = relationship("Plan", back_populates="coverage_rules")


class Policy(Base):
    """A member's active instance of a plan for a specific policy period."""

    __tablename__ = "policies"
    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="ck_policies_end_after_start"),
        Index(
            "ix_policies_member_id_active",
            "member_id",
            unique=True,
            sqlite_where=text("status = 'active' AND deleted_at IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    member_id: Mapped[str] = mapped_column(String(36), ForeignKey("members.id"), nullable=False)
    plan_id: Mapped[str] = mapped_column(String(36), ForeignKey("plans.id"), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[PolicyStatus] = mapped_column(
        Enum(PolicyStatus), nullable=False, default=PolicyStatus.active
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    member: Mapped[Member] = relationship("Member", back_populates="policies")
    plan: Mapped[Plan] = relationship("Plan", back_populates="policies")
    claims: Mapped[list["Claim"]] = relationship("Claim", back_populates="policy")
    accumulator: Mapped["Accumulator | None"] = relationship(
        "Accumulator", back_populates="policy", uselist=False
    )


class Accumulator(Base):
    """Running deductible total per member per policy period."""

    __tablename__ = "accumulators"
    __table_args__ = (
        UniqueConstraint("member_id", "policy_id", name="uq_accumulator_member_policy"),
        CheckConstraint("deductible_met >= 0", name="ck_accumulators_deductible_met_non_negative"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    member_id: Mapped[str] = mapped_column(String(36), ForeignKey("members.id"), nullable=False)
    policy_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("policies.id"), unique=True, nullable=False
    )
    deductible_met: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    member: Mapped[Member] = relationship("Member", back_populates="accumulators")
    policy: Mapped[Policy] = relationship("Policy", back_populates="accumulator")


class Claim(Base):
    """A reimbursement request submitted by or on behalf of a member."""

    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    member_id: Mapped[str] = mapped_column(String(36), ForeignKey("members.id"), nullable=False)
    policy_id: Mapped[str] = mapped_column(String(36), ForeignKey("policies.id"), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(36), ForeignKey("providers.id"), nullable=False)
    date_of_service: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[ClaimStatus] = mapped_column(
        Enum(ClaimStatus), nullable=False, default=ClaimStatus.submitted
    )
    review_type: Mapped[ReviewType] = mapped_column(
        Enum(ReviewType), nullable=False, default=ReviewType.auto
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    member: Mapped[Member] = relationship("Member", back_populates="claims")
    policy: Mapped[Policy] = relationship("Policy", back_populates="claims")
    provider: Mapped[Provider] = relationship("Provider")
    line_items: Mapped[list["LineItem"]] = relationship(
        "LineItem",
        back_populates="claim",
        foreign_keys="LineItem.claim_id",
    )
    status_history: Mapped[list["ClaimStatusHistory"]] = relationship(
        "ClaimStatusHistory", back_populates="claim", order_by="ClaimStatusHistory.transitioned_at"
    )
    dispute: Mapped["Dispute | None"] = relationship(
        "Dispute", back_populates="claim", uselist=False
    )
    payment: Mapped["Payment | None"] = relationship(
        "Payment", back_populates="claim", uselist=False
    )


class ClaimStatusHistory(Base):
    """Append-only audit log of claim status transitions."""

    __tablename__ = "claim_status_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("claims.id"), nullable=False)
    from_status: Mapped[ClaimStatus | None] = mapped_column(Enum(ClaimStatus), nullable=True)
    to_status: Mapped[ClaimStatus] = mapped_column(Enum(ClaimStatus), nullable=False)
    transitioned_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    claim: Mapped[Claim] = relationship("Claim", back_populates="status_history")


class AdjudicationResult(Base):
    """Immutable record of a single adjudication pass on a line item.

    Re-adjudication appends a new row (revision + 1) rather than mutating.
    """

    __tablename__ = "adjudication_results"
    __table_args__ = (
        UniqueConstraint("line_item_id", "revision", name="uq_adjudication_line_revision"),
        CheckConstraint("revision >= 1", name="ck_adjudication_results_revision_min"),
        CheckConstraint(
            "applied_to_deductible >= 0",
            name="ck_adjudication_results_applied_non_negative",
        ),
        CheckConstraint("plan_pays >= 0", name="ck_adjudication_results_plan_pays_non_negative"),
        CheckConstraint(
            "member_owes >= 0", name="ck_adjudication_results_member_owes_non_negative"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    line_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("line_items.id"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    is_covered: Mapped[bool] = mapped_column(Boolean, nullable=False)
    applied_to_deductible: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    plan_pays: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    member_owes: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    adjudicated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    line_item: Mapped["LineItem"] = relationship(
        "LineItem", back_populates="results", foreign_keys=[line_item_id]
    )


class LineItem(Base):
    """A single billable service within a claim.

    ``latest_result_id`` uses ``use_alter=True`` to resolve the mutual FK
    cycle with ``AdjudicationResult`` (SQLAlchemy emits it as a post-creation
    ALTER TABLE statement).
    """

    __tablename__ = "line_items"
    __table_args__ = (
        CheckConstraint("billed_amount > 0", name="ck_line_items_billed_amount_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("claims.id"), nullable=False)
    diagnosis_code: Mapped[str] = mapped_column(String(20), nullable=False)
    cpt_code: Mapped[str] = mapped_column(String(20), nullable=False)
    billed_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    adjudication_status: Mapped[LineItemStatus] = mapped_column(
        Enum(LineItemStatus), nullable=False, default=LineItemStatus.pending
    )
    latest_result_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("adjudication_results.id", use_alter=True, name="fk_line_item_latest_result"),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    claim: Mapped[Claim] = relationship(
        "Claim", back_populates="line_items", foreign_keys=[claim_id]
    )
    results: Mapped[list[AdjudicationResult]] = relationship(
        "AdjudicationResult",
        back_populates="line_item",
        foreign_keys="AdjudicationResult.line_item_id",
        order_by="AdjudicationResult.revision",
    )
    latest_result: Mapped[AdjudicationResult | None] = relationship(
        "AdjudicationResult",
        foreign_keys=[latest_result_id],
        primaryjoin="LineItem.latest_result_id == AdjudicationResult.id",
    )


class Dispute(Base):
    """A member's challenge to a denied or partially-approved claim.

    One dispute per claim maximum, enforced by the unique FK constraint.
    """

    __tablename__ = "disputes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    claim_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("claims.id"), unique=True, nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[DisputeStatus] = mapped_column(
        Enum(DisputeStatus), nullable=False, default=DisputeStatus.pending
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    line_item_updates: Mapped[list[dict[str, object]] | None] = mapped_column(JSON, nullable=True)

    claim: Mapped[Claim] = relationship("Claim", back_populates="dispute")


class Payment(Base):
    """Payment record created when a claim transitions to ``paid``."""

    __tablename__ = "payments"
    __table_args__ = (CheckConstraint("amount >= 0", name="ck_payments_amount_non_negative"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    claim_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("claims.id"), unique=True, nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    paid_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    claim: Mapped[Claim] = relationship("Claim", back_populates="payment")
