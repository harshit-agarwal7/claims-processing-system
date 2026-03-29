"""Integration tests for /api/policies endpoints."""

import types

from flask.testing import FlaskClient


class TestCreatePolicy:
    """POST /api/policies"""

    def test_happy_path_returns_201(self, client: FlaskClient, seed: types.SimpleNamespace) -> None:
        resp = client.post(
            "/api/policies",
            json={
                "member_id": seed.member.id,
                "plan_id": seed.plan.id,
                "start_date": "2027-01-01",
                "end_date": "2027-12-31",
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["member_id"] == seed.member.id
        assert data["plan_id"] == seed.plan.id
        assert data["start_date"] == "2027-01-01"
        assert data["end_date"] == "2027-12-31"
        assert data["status"] == "active"
        assert data["plan_name"] == seed.plan.name
        assert "deductible" in data
        assert "id" in data

    def test_creates_accumulator(self, client: FlaskClient, seed: types.SimpleNamespace) -> None:
        from app.extensions import db
        from app.models import Accumulator

        resp = client.post(
            "/api/policies",
            json={
                "member_id": seed.member.id,
                "plan_id": seed.plan.id,
                "start_date": "2027-01-01",
                "end_date": "2027-12-31",
            },
        )
        assert resp.status_code == 201
        policy_id = resp.get_json()["id"]

        acc = db.session.execute(
            db.select(Accumulator).where(Accumulator.policy_id == policy_id)
        ).scalar_one_or_none()
        assert acc is not None
        assert str(acc.deductible_met) == "0.00"

    def test_missing_member_id_returns_400(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        resp = client.post(
            "/api/policies",
            json={
                "plan_id": seed.plan.id,
                "start_date": "2027-01-01",
                "end_date": "2027-12-31",
            },
        )
        assert resp.status_code == 400

    def test_missing_plan_id_returns_400(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        resp = client.post(
            "/api/policies",
            json={
                "member_id": seed.member.id,
                "start_date": "2027-01-01",
                "end_date": "2027-12-31",
            },
        )
        assert resp.status_code == 400

    def test_missing_dates_returns_400(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        resp = client.post(
            "/api/policies",
            json={"member_id": seed.member.id, "plan_id": seed.plan.id},
        )
        assert resp.status_code == 400

    def test_end_before_start_returns_400(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        resp = client.post(
            "/api/policies",
            json={
                "member_id": seed.member.id,
                "plan_id": seed.plan.id,
                "start_date": "2027-12-31",
                "end_date": "2027-01-01",
            },
        )
        assert resp.status_code == 400

    def test_unknown_member_returns_404(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        resp = client.post(
            "/api/policies",
            json={
                "member_id": "ghost-member",
                "plan_id": seed.plan.id,
                "start_date": "2027-01-01",
                "end_date": "2027-12-31",
            },
        )
        assert resp.status_code == 404

    def test_unknown_plan_returns_404(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        resp = client.post(
            "/api/policies",
            json={
                "member_id": seed.member.id,
                "plan_id": "ghost-plan",
                "start_date": "2027-01-01",
                "end_date": "2027-12-31",
            },
        )
        assert resp.status_code == 404

    def test_invalid_date_format_returns_400(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        resp = client.post(
            "/api/policies",
            json={
                "member_id": seed.member.id,
                "plan_id": seed.plan.id,
                "start_date": "01-01-2027",
                "end_date": "2027-12-31",
            },
        )
        assert resp.status_code == 400


class TestGetPolicy:
    """GET /api/policies/<id>"""

    def test_returns_policy(self, client: FlaskClient, seed: types.SimpleNamespace) -> None:
        resp = client.get(f"/api/policies/{seed.policy.id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["id"] == seed.policy.id
        assert data["member_id"] == seed.member.id
        assert data["plan_name"] == seed.plan.name
        assert data["status"] == "active"

    def test_unknown_id_returns_404(self, client: FlaskClient) -> None:
        resp = client.get("/api/policies/does-not-exist")
        assert resp.status_code == 404
