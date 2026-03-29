"""Integration tests for /api/plans endpoints."""

import types

from flask.testing import FlaskClient


class TestCreatePlan:
    """POST /api/plans"""

    def test_happy_path_with_rules_returns_201(self, client: FlaskClient) -> None:
        resp = client.post(
            "/api/plans",
            json={
                "name": "Gold Plan",
                "deductible": "500.00",
                "coverage_rules": [
                    {"cpt_code": "99213", "is_covered": True, "coverage_percentage": 0.8},
                    {"cpt_code": "99214", "is_covered": True, "coverage_percentage": 0.7},
                ],
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["name"] == "Gold Plan"
        assert data["deductible"] == "500.00"
        assert len(data["coverage_rules"]) == 2
        cpt_codes = {r["cpt_code"] for r in data["coverage_rules"]}
        assert cpt_codes == {"99213", "99214"}

    def test_happy_path_without_rules_returns_201(self, client: FlaskClient) -> None:
        resp = client.post(
            "/api/plans",
            json={"name": "Empty Plan", "deductible": "250.00"},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["coverage_rules"] == []

    def test_missing_name_returns_400(self, client: FlaskClient) -> None:
        resp = client.post("/api/plans", json={"deductible": "500.00"})
        assert resp.status_code == 400

    def test_missing_deductible_returns_400(self, client: FlaskClient) -> None:
        resp = client.post("/api/plans", json={"name": "Plan X"})
        assert resp.status_code == 400

    def test_negative_deductible_returns_400(self, client: FlaskClient) -> None:
        resp = client.post("/api/plans", json={"name": "Bad Plan", "deductible": "-100"})
        assert resp.status_code == 400

    def test_rule_missing_cpt_code_returns_400(self, client: FlaskClient) -> None:
        resp = client.post(
            "/api/plans",
            json={
                "name": "Plan",
                "deductible": "100",
                "coverage_rules": [{"is_covered": True, "coverage_percentage": 0.8}],
            },
        )
        assert resp.status_code == 400

    def test_rule_coverage_percentage_out_of_range_returns_400(self, client: FlaskClient) -> None:
        resp = client.post(
            "/api/plans",
            json={
                "name": "Plan",
                "deductible": "100",
                "coverage_rules": [
                    {"cpt_code": "99213", "is_covered": True, "coverage_percentage": 1.5}
                ],
            },
        )
        assert resp.status_code == 400


class TestGetPlan:
    """GET /api/plans/<id>"""

    def test_returns_plan_with_active_rules(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        resp = client.get(f"/api/plans/{seed.plan.id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["id"] == seed.plan.id
        assert data["name"] == seed.plan.name
        assert data["deductible"] == str(seed.plan.deductible)
        assert len(data["coverage_rules"]) == 1
        assert data["coverage_rules"][0]["cpt_code"] == "99213"

    def test_unknown_id_returns_404(self, client: FlaskClient) -> None:
        resp = client.get("/api/plans/does-not-exist")
        assert resp.status_code == 404


class TestUpsertCoverageRule:
    """PUT /api/plans/<id>/coverage-rules/<cpt_code>"""

    def test_inserts_new_rule_returns_200(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        resp = client.put(
            f"/api/plans/{seed.plan.id}/coverage-rules/99214",
            json={"is_covered": True, "coverage_percentage": 0.7},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["cpt_code"] == "99214"
        assert data["is_covered"] is True

    def test_updates_existing_rule(self, client: FlaskClient, seed: types.SimpleNamespace) -> None:
        # Update existing 99213 rule (coverage 0.8 → 0.6)
        resp = client.put(
            f"/api/plans/{seed.plan.id}/coverage-rules/99213",
            json={"is_covered": True, "coverage_percentage": 0.6},
        )
        assert resp.status_code == 200
        assert resp.get_json()["coverage_percentage"] == "0.6000"

        # Verify plan GET only shows one active rule
        plan_resp = client.get(f"/api/plans/{seed.plan.id}")
        rules = plan_resp.get_json()["coverage_rules"]
        assert len(rules) == 1
        assert rules[0]["coverage_percentage"] == "0.6000"

    def test_missing_fields_returns_400(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        resp = client.put(
            f"/api/plans/{seed.plan.id}/coverage-rules/99213",
            json={"is_covered": True},
        )
        assert resp.status_code == 400

    def test_unknown_plan_returns_404(self, client: FlaskClient) -> None:
        resp = client.put(
            "/api/plans/ghost/coverage-rules/99213",
            json={"is_covered": True, "coverage_percentage": 0.8},
        )
        assert resp.status_code == 404


class TestDeleteCoverageRule:
    """DELETE /api/plans/<id>/coverage-rules/<cpt_code>"""

    def test_soft_deletes_rule_returns_204(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        resp = client.delete(f"/api/plans/{seed.plan.id}/coverage-rules/99213")
        assert resp.status_code == 204

        # Verify rule no longer appears in GET
        plan_resp = client.get(f"/api/plans/{seed.plan.id}")
        assert plan_resp.get_json()["coverage_rules"] == []

    def test_nonexistent_rule_returns_404(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        resp = client.delete(f"/api/plans/{seed.plan.id}/coverage-rules/00000")
        assert resp.status_code == 404

    def test_unknown_plan_returns_404(self, client: FlaskClient) -> None:
        resp = client.delete("/api/plans/ghost/coverage-rules/99213")
        assert resp.status_code == 404
