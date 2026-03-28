"""Shared pytest fixtures for the claims processing test suite."""

import types
from collections.abc import Generator
from datetime import date
from decimal import Decimal

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app import create_app
from app.extensions import db as _db
from app.models import (
    Accumulator,
    CoverageRule,
    Member,
    Plan,
    Policy,
    PolicyStatus,
    Provider,
    ProviderType,
)
from config.settings import TestingConfig


@pytest.fixture()
def app() -> Generator[Flask, None, None]:
    """Create an application instance backed by an in-memory SQLite database.

    Yields:
        A configured Flask app with all tables created and dropped around each test.
    """
    application = create_app(TestingConfig)
    with application.app_context():
        _db.create_all()
        yield application
        _db.drop_all()


@pytest.fixture()
def client(app: Flask) -> FlaskClient:
    """Return a test client for the given app fixture.

    Args:
        app: The Flask application fixture.

    Returns:
        A Flask test client.
    """
    return app.test_client()


@pytest.fixture()
def seed(app: Flask) -> types.SimpleNamespace:
    """Populate the database with a minimal but complete set of seed objects.

    Creates and commits the following records:
      - plan       — Plan(deductible=500.00)
      - rule       — CoverageRule(cpt_code="99213", is_covered=True, coverage_percentage=0.8)
      - member     — Member
      - provider   — Provider
      - policy     — Policy(status=active, 2026-01-01 to 2026-12-31)
      - accumulator — Accumulator(deductible_met=0.00)

    Args:
        app: The Flask application fixture (provides active app context).

    Returns:
        A SimpleNamespace with attributes: plan, rule, member, provider, policy, accumulator.
    """
    plan = Plan(name="Standard Plan", deductible=Decimal("500.00"))
    _db.session.add(plan)
    _db.session.flush()

    rule = CoverageRule(
        plan_id=plan.id,
        cpt_code="99213",
        is_covered=True,
        coverage_percentage=Decimal("0.8000"),
    )
    _db.session.add(rule)

    member = Member(
        name="Jane Doe",
        date_of_birth=date(1985, 6, 15),
        email="jane.doe@example.com",
        phone="555-0100",
    )
    _db.session.add(member)

    provider = Provider(
        name="City Medical Group",
        npi="1234567890",
        provider_type=ProviderType.individual,
    )
    _db.session.add(provider)
    _db.session.flush()

    policy = Policy(
        member_id=member.id,
        plan_id=plan.id,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        status=PolicyStatus.active,
    )
    _db.session.add(policy)
    _db.session.flush()

    accumulator = Accumulator(
        member_id=member.id,
        policy_id=policy.id,
        deductible_met=Decimal("0.00"),
    )
    _db.session.add(accumulator)
    _db.session.commit()

    return types.SimpleNamespace(
        plan=plan,
        rule=rule,
        member=member,
        provider=provider,
        policy=policy,
        accumulator=accumulator,
    )
