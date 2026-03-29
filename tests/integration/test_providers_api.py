"""Integration tests for /api/providers endpoints."""

import types

from flask.testing import FlaskClient


class TestCreateProvider:
    """POST /api/providers"""

    def test_happy_path_returns_201(self, client: FlaskClient) -> None:
        resp = client.post(
            "/api/providers",
            json={"name": "Dr. House", "npi": "9876543210", "provider_type": "individual"},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["name"] == "Dr. House"
        assert data["npi"] == "9876543210"
        assert data["provider_type"] == "individual"
        assert "id" in data
        assert "created_at" in data

    def test_facility_provider_type(self, client: FlaskClient) -> None:
        resp = client.post(
            "/api/providers",
            json={"name": "City Hospital", "npi": "1111111111", "provider_type": "facility"},
        )
        assert resp.status_code == 201
        assert resp.get_json()["provider_type"] == "facility"

    def test_missing_name_returns_400(self, client: FlaskClient) -> None:
        resp = client.post(
            "/api/providers",
            json={"npi": "9999999999", "provider_type": "individual"},
        )
        assert resp.status_code == 400

    def test_missing_npi_returns_400(self, client: FlaskClient) -> None:
        resp = client.post(
            "/api/providers",
            json={"name": "Dr. X", "provider_type": "individual"},
        )
        assert resp.status_code == 400

    def test_invalid_provider_type_returns_400(self, client: FlaskClient) -> None:
        resp = client.post(
            "/api/providers",
            json={"name": "Dr. X", "npi": "0000000001", "provider_type": "unknown"},
        )
        assert resp.status_code == 400

    def test_duplicate_npi_returns_409(self, client: FlaskClient) -> None:
        payload = {"name": "Dr. A", "npi": "2222222222", "provider_type": "individual"}
        client.post("/api/providers", json=payload)
        resp = client.post("/api/providers", json={**payload, "name": "Dr. B"})
        assert resp.status_code == 409


class TestGetProvider:
    """GET /api/providers/<id>"""

    def test_returns_provider(self, client: FlaskClient, seed: types.SimpleNamespace) -> None:
        resp = client.get(f"/api/providers/{seed.provider.id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["id"] == seed.provider.id
        assert data["name"] == seed.provider.name
        assert data["npi"] == seed.provider.npi

    def test_unknown_id_returns_404(self, client: FlaskClient) -> None:
        resp = client.get("/api/providers/does-not-exist")
        assert resp.status_code == 404
