"""Integration tests for /api/members endpoints."""

import types

from flask.testing import FlaskClient


class TestCreateMember:
    """POST /api/members"""

    def test_happy_path_returns_201(self, client: FlaskClient) -> None:
        resp = client.post(
            "/api/members",
            json={
                "name": "Alice Smith",
                "date_of_birth": "1990-04-20",
                "email": "alice@example.com",
                "phone": "555-0200",
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["name"] == "Alice Smith"
        assert data["email"] == "alice@example.com"
        assert data["date_of_birth"] == "1990-04-20"
        assert data["phone"] == "555-0200"
        assert "id" in data
        assert "created_at" in data

    def test_happy_path_without_phone(self, client: FlaskClient) -> None:
        resp = client.post(
            "/api/members",
            json={
                "name": "Bob Jones",
                "date_of_birth": "1975-11-03",
                "email": "bob@example.com",
            },
        )
        assert resp.status_code == 201
        assert resp.get_json()["phone"] is None

    def test_missing_name_returns_400(self, client: FlaskClient) -> None:
        resp = client.post(
            "/api/members",
            json={"date_of_birth": "1990-04-20", "email": "alice@example.com"},
        )
        assert resp.status_code == 400

    def test_missing_email_returns_400(self, client: FlaskClient) -> None:
        resp = client.post(
            "/api/members",
            json={"name": "Alice", "date_of_birth": "1990-04-20"},
        )
        assert resp.status_code == 400

    def test_missing_date_of_birth_returns_400(self, client: FlaskClient) -> None:
        resp = client.post(
            "/api/members",
            json={"name": "Alice", "email": "alice@example.com"},
        )
        assert resp.status_code == 400

    def test_invalid_date_of_birth_returns_400(self, client: FlaskClient) -> None:
        resp = client.post(
            "/api/members",
            json={
                "name": "Alice",
                "date_of_birth": "not-a-date",
                "email": "alice@example.com",
            },
        )
        assert resp.status_code == 400

    def test_duplicate_email_returns_409(self, client: FlaskClient) -> None:
        payload = {
            "name": "Alice",
            "date_of_birth": "1990-04-20",
            "email": "dup@example.com",
        }
        client.post("/api/members", json=payload)
        resp = client.post("/api/members", json={**payload, "name": "Alice 2"})
        assert resp.status_code == 409


class TestGetMember:
    """GET /api/members/<id>"""

    def test_returns_member(self, client: FlaskClient, seed: types.SimpleNamespace) -> None:
        resp = client.get(f"/api/members/{seed.member.id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["id"] == seed.member.id
        assert data["name"] == seed.member.name
        assert data["email"] == seed.member.email

    def test_unknown_id_returns_404(self, client: FlaskClient) -> None:
        resp = client.get("/api/members/does-not-exist")
        assert resp.status_code == 404


class TestListMemberClaims:
    """GET /api/members/<id>/claims"""

    def test_returns_empty_list_when_no_claims(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        resp = client.get(f"/api/members/{seed.member.id}/claims")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_unknown_member_returns_404(self, client: FlaskClient) -> None:
        resp = client.get("/api/members/ghost/claims")
        assert resp.status_code == 404


class TestLookupMemberByEmail:
    """GET /api/members/lookup?email=<email>"""

    def test_returns_member_for_known_email(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        resp = client.get(f"/api/members/lookup?email={seed.member.email}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["id"] == seed.member.id
        assert data["email"] == seed.member.email
        assert data["name"] == seed.member.name

    def test_missing_email_param_returns_400(self, client: FlaskClient) -> None:
        resp = client.get("/api/members/lookup")
        assert resp.status_code == 400

    def test_unknown_email_returns_404(self, client: FlaskClient) -> None:
        resp = client.get("/api/members/lookup?email=nobody@example.com")
        assert resp.status_code == 404


class TestGetActivePolicyForMember:
    """GET /api/members/<id>/policies/active"""

    def test_returns_active_policy(self, client: FlaskClient, seed: types.SimpleNamespace) -> None:
        resp = client.get(f"/api/members/{seed.member.id}/policies/active")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["id"] == seed.policy.id
        assert data["status"] == "active"
        assert data["plan_name"] == seed.plan.name
        assert "deductible" in data

    def test_member_without_policy_returns_404(self, client: FlaskClient) -> None:
        # Create a member with no policy
        resp = client.post(
            "/api/members",
            json={
                "name": "No Policy Person",
                "date_of_birth": "2000-01-01",
                "email": "nopolicy@example.com",
            },
        )
        member_id = resp.get_json()["id"]
        resp = client.get(f"/api/members/{member_id}/policies/active")
        assert resp.status_code == 404

    def test_unknown_member_returns_404(self, client: FlaskClient) -> None:
        resp = client.get("/api/members/ghost/policies/active")
        assert resp.status_code == 404
