"""Unit tests for claim_service.submit_claim.

All tests run against an in-memory SQLite DB provided by the ``app`` fixture
(via the ``seed`` fixture dependency).  The ``AdjudicationEngine`` is patched
to a no-op so tests remain fast and isolated to service-layer logic.
"""

import types
from unittest.mock import patch

import pytest

from app.errors import BadRequestError, NotFoundError, ValidationError
from app.models import ClaimStatus
from app.services.claim_service import submit_claim


class TestSubmitClaimValidation:
    """Guard-rail and field-validation tests for submit_claim."""

    def test_missing_member_id_raises_bad_request(self, seed: types.SimpleNamespace) -> None:
        data: dict = {
            "provider_id": seed.provider.id,
            "date_of_service": "2026-03-01",
            "line_items": [{"diagnosis_code": "M54.5", "cpt_code": "99213", "billed_amount": 300}],
        }
        with pytest.raises(BadRequestError):
            submit_claim(data)

    def test_missing_line_items_raises_bad_request(self, seed: types.SimpleNamespace) -> None:
        data: dict = {
            "member_id": seed.member.id,
            "provider_id": seed.provider.id,
            "date_of_service": "2026-03-01",
        }
        with pytest.raises(BadRequestError):
            submit_claim(data)

    def test_empty_line_items_raises_bad_request(self, seed: types.SimpleNamespace) -> None:
        data: dict = {
            "member_id": seed.member.id,
            "provider_id": seed.provider.id,
            "date_of_service": "2026-03-01",
            "line_items": [],
        }
        with pytest.raises(BadRequestError):
            submit_claim(data)

    def test_billed_amount_zero_raises_bad_request(self, seed: types.SimpleNamespace) -> None:
        data: dict = {
            "member_id": seed.member.id,
            "provider_id": seed.provider.id,
            "date_of_service": "2026-03-01",
            "line_items": [{"diagnosis_code": "M54.5", "cpt_code": "99213", "billed_amount": 0}],
        }
        with pytest.raises(BadRequestError):
            submit_claim(data)

    def test_billed_amount_negative_raises_bad_request(self, seed: types.SimpleNamespace) -> None:
        data: dict = {
            "member_id": seed.member.id,
            "provider_id": seed.provider.id,
            "date_of_service": "2026-03-01",
            "line_items": [{"diagnosis_code": "M54.5", "cpt_code": "99213", "billed_amount": -100}],
        }
        with pytest.raises(BadRequestError):
            submit_claim(data)

    def test_unknown_member_id_raises_not_found(self, seed: types.SimpleNamespace) -> None:
        data: dict = {
            "member_id": "00000000-0000-0000-0000-000000000000",
            "provider_id": seed.provider.id,
            "date_of_service": "2026-03-01",
            "line_items": [{"diagnosis_code": "M54.5", "cpt_code": "99213", "billed_amount": 300}],
        }
        with pytest.raises(NotFoundError):
            submit_claim(data)

    def test_unknown_provider_id_raises_not_found(self, seed: types.SimpleNamespace) -> None:
        data: dict = {
            "member_id": seed.member.id,
            "provider_id": "00000000-0000-0000-0000-000000000000",
            "date_of_service": "2026-03-01",
            "line_items": [{"diagnosis_code": "M54.5", "cpt_code": "99213", "billed_amount": 300}],
        }
        with pytest.raises(NotFoundError):
            submit_claim(data)

    def test_date_of_service_before_policy_start_raises_validation_error(
        self, seed: types.SimpleNamespace
    ) -> None:
        data: dict = {
            "member_id": seed.member.id,
            "provider_id": seed.provider.id,
            "date_of_service": "2025-12-31",  # before policy start 2026-01-01
            "line_items": [{"diagnosis_code": "M54.5", "cpt_code": "99213", "billed_amount": 300}],
        }
        with pytest.raises(ValidationError):
            submit_claim(data)

    def test_date_of_service_after_policy_end_raises_validation_error(
        self, seed: types.SimpleNamespace
    ) -> None:
        data: dict = {
            "member_id": seed.member.id,
            "provider_id": seed.provider.id,
            "date_of_service": "2027-01-01",  # after policy end 2026-12-31
            "line_items": [{"diagnosis_code": "M54.5", "cpt_code": "99213", "billed_amount": 300}],
        }
        with pytest.raises(ValidationError):
            submit_claim(data)

    def test_valid_submission_returns_claim_with_submitted_status(
        self, seed: types.SimpleNamespace
    ) -> None:
        """When the adjudication engine is patched to a no-op, the returned
        claim still has status=submitted (the engine never ran to advance it)."""
        data: dict = {
            "member_id": seed.member.id,
            "provider_id": seed.provider.id,
            "date_of_service": "2026-03-01",
            "line_items": [{"diagnosis_code": "M54.5", "cpt_code": "99213", "billed_amount": 300}],
        }
        with patch("app.services.claim_service.AdjudicationEngine") as mock_cls:
            mock_cls.return_value.run.return_value = None
            claim = submit_claim(data)

        assert claim.status == ClaimStatus.submitted
