"""Integration tests for /api/claims endpoints.

Covers:
  - POST /api/claims  (happy path + all error cases)
  - GET  /api/claims/<id>
  - Sequential claims with deductible carry-over
"""

import types

from flask.testing import FlaskClient


class TestSubmitClaim:
    """POST /api/claims"""

    def test_happy_path_returns_201_with_adjudicated_status(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        resp = client.post(
            "/api/claims",
            json={
                "member_id": seed.member.id,
                "provider_id": seed.provider.id,
                "date_of_service": "2026-03-01",
                "line_items": [
                    {
                        "diagnosis_code": "M54.5",
                        "cpt_code": "99213",
                        "billed_amount": "300.00",
                    }
                ],
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["status"] in {"approved", "denied", "partially_approved", "paid"}
        assert data["id"] is not None
        assert data["member"]["id"] == seed.member.id
        assert data["provider"]["id"] == seed.provider.id
        assert len(data["line_items"]) == 1
        assert data["line_items"][0]["adjudication_result"] is not None
        assert len(data["status_history"]) >= 1

    def test_missing_member_id_returns_400(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        resp = client.post(
            "/api/claims",
            json={
                "provider_id": seed.provider.id,
                "date_of_service": "2026-03-01",
                "line_items": [
                    {"diagnosis_code": "M54.5", "cpt_code": "99213", "billed_amount": "300.00"}
                ],
            },
        )
        assert resp.status_code == 400

    def test_unknown_member_id_returns_404(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        resp = client.post(
            "/api/claims",
            json={
                "member_id": "00000000-0000-0000-0000-000000000000",
                "provider_id": seed.provider.id,
                "date_of_service": "2026-03-01",
                "line_items": [
                    {"diagnosis_code": "M54.5", "cpt_code": "99213", "billed_amount": "300.00"}
                ],
            },
        )
        assert resp.status_code == 404

    def test_date_before_policy_start_returns_422(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        resp = client.post(
            "/api/claims",
            json={
                "member_id": seed.member.id,
                "provider_id": seed.provider.id,
                "date_of_service": "2025-12-31",
                "line_items": [
                    {"diagnosis_code": "M54.5", "cpt_code": "99213", "billed_amount": "300.00"}
                ],
            },
        )
        assert resp.status_code == 422

    def test_date_after_policy_end_returns_422(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        resp = client.post(
            "/api/claims",
            json={
                "member_id": seed.member.id,
                "provider_id": seed.provider.id,
                "date_of_service": "2027-01-01",
                "line_items": [
                    {"diagnosis_code": "M54.5", "cpt_code": "99213", "billed_amount": "300.00"}
                ],
            },
        )
        assert resp.status_code == 422

    def test_empty_line_items_returns_400(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        resp = client.post(
            "/api/claims",
            json={
                "member_id": seed.member.id,
                "provider_id": seed.provider.id,
                "date_of_service": "2026-03-01",
                "line_items": [],
            },
        )
        assert resp.status_code == 400

    def test_billed_amount_zero_returns_400(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        resp = client.post(
            "/api/claims",
            json={
                "member_id": seed.member.id,
                "provider_id": seed.provider.id,
                "date_of_service": "2026-03-01",
                "line_items": [
                    {"diagnosis_code": "M54.5", "cpt_code": "99213", "billed_amount": 0}
                ],
            },
        )
        assert resp.status_code == 400

    def test_sequential_claims_carry_deductible(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        """Deductible accumulation must persist across claims.

        Seed: deductible=$500, CPT 99213 covered at 80%.

        Claim 1: $300 billed
          → applied_to_deductible=$300.00, plan_pays=$0.00  (full amount into deductible)

        Claim 2: $300 billed (deductible_met now $300; $200 remaining)
          → applied_to_deductible=$200.00, amount_after=$100, plan_pays=$80.00
        """
        resp1 = client.post(
            "/api/claims",
            json={
                "member_id": seed.member.id,
                "provider_id": seed.provider.id,
                "date_of_service": "2026-03-01",
                "line_items": [
                    {"diagnosis_code": "M54.5", "cpt_code": "99213", "billed_amount": "300.00"}
                ],
            },
        )
        assert resp1.status_code == 201
        result1 = resp1.get_json()["line_items"][0]["adjudication_result"]
        assert result1["applied_to_deductible"] == "300.00"
        assert result1["plan_pays"] == "0.00"

        resp2 = client.post(
            "/api/claims",
            json={
                "member_id": seed.member.id,
                "provider_id": seed.provider.id,
                "date_of_service": "2026-03-02",
                "line_items": [
                    {"diagnosis_code": "M54.5", "cpt_code": "99213", "billed_amount": "300.00"}
                ],
            },
        )
        assert resp2.status_code == 201
        result2 = resp2.get_json()["line_items"][0]["adjudication_result"]
        assert result2["applied_to_deductible"] == "200.00"
        assert result2["plan_pays"] == "80.00"


class TestGetClaim:
    """GET /api/claims/<id>"""

    def test_returns_full_detail_for_existing_claim(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        post_resp = client.post(
            "/api/claims",
            json={
                "member_id": seed.member.id,
                "provider_id": seed.provider.id,
                "date_of_service": "2026-03-01",
                "line_items": [
                    {"diagnosis_code": "M54.5", "cpt_code": "99213", "billed_amount": "300.00"}
                ],
            },
        )
        claim_id = post_resp.get_json()["id"]

        resp = client.get(f"/api/claims/{claim_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["id"] == claim_id
        assert "member" in data
        assert "provider" in data
        assert "policy" in data
        assert "line_items" in data
        assert "status_history" in data
        assert "payment" in data
        assert "dispute" in data

    def test_nonexistent_claim_returns_404(self, client: FlaskClient) -> None:
        resp = client.get("/api/claims/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404
