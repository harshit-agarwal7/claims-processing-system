"""Integration tests for dispute-related /api/claims endpoints.

Covers:
  - POST /api/claims/<id>/disputes
  - POST /api/claims/<id>/adjudicate
  - GET  /api/claims/<id>/dispute
  - POST /api/claims/<id>/accept
"""

import types
from datetime import date

from flask.testing import FlaskClient

from app.extensions import db
from app.models import Claim, ClaimStatus, ClaimStatusHistory, ReviewType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _submit_denied_claim(client: FlaskClient, seed: types.SimpleNamespace) -> str:
    """Submit a claim with an uncovered CPT code so it ends up denied.

    Args:
        client: The Flask test client.
        seed: The conftest seed namespace.

    Returns:
        The claim ID string.
    """
    resp = client.post(
        "/api/claims",
        json={
            "member_id": seed.member.id,
            "provider_id": seed.provider.id,
            "date_of_service": "2026-03-01",
            "line_items": [
                {"diagnosis_code": "M54.5", "cpt_code": "00000", "billed_amount": "200.00"}
            ],
        },
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["status"] == "denied"
    return str(data["id"])


def _submit_partially_approved_claim(client: FlaskClient, seed: types.SimpleNamespace) -> str:
    """Submit a claim with one covered and one uncovered item → partially_approved.

    Args:
        client: The Flask test client.
        seed: The conftest seed namespace.

    Returns:
        The claim ID string.
    """
    resp = client.post(
        "/api/claims",
        json={
            "member_id": seed.member.id,
            "provider_id": seed.provider.id,
            "date_of_service": "2026-03-01",
            "line_items": [
                {"diagnosis_code": "M54.5", "cpt_code": "99213", "billed_amount": "200.00"},
                {"diagnosis_code": "M54.5", "cpt_code": "00000", "billed_amount": "200.00"},
            ],
        },
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["status"] == "partially_approved"
    return str(data["id"])


# ---------------------------------------------------------------------------
# POST /api/claims/<id>/disputes
# ---------------------------------------------------------------------------


class TestSubmitDisputeAPI:
    """POST /api/claims/<id>/disputes"""

    def test_denied_claim_returns_201_and_claim_under_review(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        """Disputing a denied claim returns 201 and transitions it to under_review."""
        claim_id = _submit_denied_claim(client, seed)
        resp = client.post(
            f"/api/claims/{claim_id}/disputes",
            json={"reason": "I believe this service is covered."},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["status"] == "pending"
        assert data["claim_id"] == claim_id
        assert data["reason"] == "I believe this service is covered."

        # Verify claim transitioned to under_review
        claim_resp = client.get(f"/api/claims/{claim_id}")
        assert claim_resp.get_json()["status"] == "under_review"

    def test_partially_approved_returns_201(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        """Disputing a partially_approved claim returns 201."""
        claim_id = _submit_partially_approved_claim(client, seed)
        resp = client.post(
            f"/api/claims/{claim_id}/disputes",
            json={"reason": "I want full coverage."},
        )
        assert resp.status_code == 201
        assert resp.get_json()["status"] == "pending"

    def test_paid_claim_returns_409(self, client: FlaskClient, seed: types.SimpleNamespace) -> None:
        """Disputing a paid claim returns 409."""
        # A covered claim (CPT 99213) goes approved → paid
        resp = client.post(
            "/api/claims",
            json={
                "member_id": seed.member.id,
                "provider_id": seed.provider.id,
                "date_of_service": "2026-03-01",
                "line_items": [
                    {"diagnosis_code": "M54.5", "cpt_code": "99213", "billed_amount": "200.00"}
                ],
            },
        )
        assert resp.status_code == 201
        claim_id = resp.get_json()["id"]

        dispute_resp = client.post(
            f"/api/claims/{claim_id}/disputes",
            json={"reason": "Should fail."},
        )
        assert dispute_resp.status_code == 409

    def test_duplicate_dispute_returns_409(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        """Filing a second dispute on the same claim returns 409."""
        claim_id = _submit_denied_claim(client, seed)

        first = client.post(
            f"/api/claims/{claim_id}/disputes",
            json={"reason": "First dispute."},
        )
        assert first.status_code == 201

        second = client.post(
            f"/api/claims/{claim_id}/disputes",
            json={"reason": "Second attempt."},
        )
        assert second.status_code == 409

    def test_missing_reason_returns_400(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        """Submitting a dispute without a reason returns 400."""
        claim_id = _submit_denied_claim(client, seed)
        resp = client.post(f"/api/claims/{claim_id}/disputes", json={})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/claims/<id>/dispute
# ---------------------------------------------------------------------------


class TestGetDisputeAPI:
    """GET /api/claims/<id>/dispute"""

    def test_returns_dispute_for_disputed_claim(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        """Returns 200 with the dispute data after a dispute is filed."""
        claim_id = _submit_denied_claim(client, seed)
        client.post(
            f"/api/claims/{claim_id}/disputes",
            json={"reason": "My reason."},
        )

        resp = client.get(f"/api/claims/{claim_id}/dispute")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["reason"] == "My reason."
        assert data["status"] == "pending"

    def test_no_dispute_returns_404(self, client: FlaskClient, seed: types.SimpleNamespace) -> None:
        """Returns 404 when no dispute exists for the claim."""
        claim_id = _submit_denied_claim(client, seed)
        resp = client.get(f"/api/claims/{claim_id}/dispute")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/claims/<id>/adjudicate
# ---------------------------------------------------------------------------


class TestTriggerReadjudicationAPI:
    """POST /api/claims/<id>/adjudicate"""

    def test_no_dispute_returns_404(self, client: FlaskClient, seed: types.SimpleNamespace) -> None:
        """Adjudicating a claim in under_review/manual with no Dispute row → 404."""
        claim = Claim(
            member_id=seed.member.id,
            policy_id=seed.policy.id,
            provider_id=seed.provider.id,
            date_of_service=date(2026, 3, 1),
            status=ClaimStatus.under_review,
            review_type=ReviewType.manual,
        )
        db.session.add(claim)
        db.session.flush()  # assign claim.id before referencing it
        db.session.add(
            ClaimStatusHistory(
                claim_id=claim.id,
                from_status=ClaimStatus.submitted,
                to_status=ClaimStatus.under_review,
            )
        )
        db.session.commit()

        resp = client.post(f"/api/claims/{claim.id}/adjudicate", json={})
        assert resp.status_code == 404

    def test_pending_dispute_returns_200_with_new_state(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        """Re-adjudicating a disputed claim returns 200 and resolves the dispute."""
        claim_id = _submit_denied_claim(client, seed)
        client.post(
            f"/api/claims/{claim_id}/disputes",
            json={"reason": "Please re-review."},
        )

        resp = client.post(
            f"/api/claims/{claim_id}/adjudicate",
            json={"reviewer_note": "Reviewed and re-adjudicated."},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] in {"approved", "denied", "partially_approved", "paid"}
        assert data["dispute"]["status"] == "resolved"
        assert data["dispute"]["reviewer_note"] == "Reviewed and re-adjudicated."

    def test_non_under_review_claim_returns_409(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        """Calling adjudicate on a claim that is not under_review/manual → 409."""
        claim_id = _submit_denied_claim(client, seed)
        # Claim is denied, not under_review/manual
        resp = client.post(f"/api/claims/{claim_id}/adjudicate", json={})
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# POST /api/claims/<id>/accept
# ---------------------------------------------------------------------------


class TestAcceptPaymentAPI:
    """POST /api/claims/<id>/accept"""

    def test_partially_approved_no_dispute_returns_200_with_payment(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        """Accepting partial payment creates a Payment and transitions claim to paid."""
        claim_id = _submit_partially_approved_claim(client, seed)

        resp = client.post(f"/api/claims/{claim_id}/accept")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["claim_id"] == claim_id
        assert data["amount"] is not None
        assert data["paid_at"] is not None

        # Claim must now be paid
        claim_resp = client.get(f"/api/claims/{claim_id}")
        assert claim_resp.get_json()["status"] == "paid"

    def test_partially_approved_with_dispute_returns_409(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        """accept when a dispute is already filed returns 409."""
        claim_id = _submit_partially_approved_claim(client, seed)
        client.post(
            f"/api/claims/{claim_id}/disputes",
            json={"reason": "Disputing partial coverage."},
        )

        resp = client.post(f"/api/claims/{claim_id}/accept")
        assert resp.status_code == 409

    def test_denied_claim_returns_409(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        """accept on a denied claim returns 409."""
        claim_id = _submit_denied_claim(client, seed)
        resp = client.post(f"/api/claims/{claim_id}/accept")
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# GET /api/claims?disputed=true
# ---------------------------------------------------------------------------


class TestListDisputedClaims:
    """GET /api/claims?disputed=true"""

    def test_returns_empty_list_when_no_disputes(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        """Returns an empty list when no claims are under manual review."""
        resp = client.get("/api/claims?disputed=true")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_returns_disputed_claim_in_list(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        """Returns a claim that is under_review/manual with a pending dispute."""
        claim_id = _submit_denied_claim(client, seed)
        client.post(
            f"/api/claims/{claim_id}/disputes",
            json={"reason": "I believe this is covered."},
        )

        resp = client.get("/api/claims?disputed=true")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["id"] == claim_id
        assert data[0]["status"] == "under_review"
        assert data[0]["review_type"] == "manual"
        assert data[0]["dispute"]["status"] == "pending"
        assert data[0]["member"]["name"] == seed.member.name

    def test_does_not_return_non_disputed_claims(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        """Claims that are not under manual review with a pending dispute are excluded."""
        client.post(
            "/api/claims",
            json={
                "member_id": seed.member.id,
                "provider_id": seed.provider.id,
                "date_of_service": "2026-03-01",
                "line_items": [
                    {"diagnosis_code": "M54.5", "cpt_code": "99213", "billed_amount": "200.00"}
                ],
            },
        )

        resp = client.get("/api/claims?disputed=true")
        assert resp.status_code == 200
        assert resp.get_json() == []


# ---------------------------------------------------------------------------
# POST /api/claims/<id>/disputes — line item corrections
# ---------------------------------------------------------------------------


class TestSubmitDisputeWithLineItemUpdatesAPI:
    """POST /api/claims/<id>/disputes with line_item_updates."""

    def test_line_item_updates_applied_and_visible_in_claim(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        """Corrections are applied to the line item and returned in the claim detail."""
        claim_id = _submit_denied_claim(client, seed)
        claim_data = client.get(f"/api/claims/{claim_id}").get_json()
        li_id = claim_data["line_items"][0]["id"]

        resp = client.post(
            f"/api/claims/{claim_id}/disputes",
            json={
                "reason": "Wrong CPT code.",
                "line_item_updates": [{"line_item_id": li_id, "cpt_code": "99213"}],
            },
        )
        assert resp.status_code == 201

        updated_claim = client.get(f"/api/claims/{claim_id}").get_json()
        assert updated_claim["line_items"][0]["cpt_code"] == "99213"

    def test_line_item_updates_stored_on_dispute(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        """The submitted line_item_updates are returned in the dispute resource."""
        claim_id = _submit_denied_claim(client, seed)
        li_id = client.get(f"/api/claims/{claim_id}").get_json()["line_items"][0]["id"]
        updates = [{"line_item_id": li_id, "billed_amount": "180.00"}]

        client.post(
            f"/api/claims/{claim_id}/disputes",
            json={"reason": "Amount wrong.", "line_item_updates": updates},
        )

        dispute_data = client.get(f"/api/claims/{claim_id}/dispute").get_json()
        assert dispute_data["line_item_updates"] == updates

    def test_unknown_line_item_id_returns_400(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        """An unknown line_item_id returns 400."""
        claim_id = _submit_denied_claim(client, seed)
        resp = client.post(
            f"/api/claims/{claim_id}/disputes",
            json={
                "reason": "Bad ID.",
                "line_item_updates": [
                    {
                        "line_item_id": "00000000-0000-0000-0000-000000000000",
                        "cpt_code": "99213",
                    }
                ],
            },
        )
        assert resp.status_code == 400

    def test_zero_billed_amount_returns_400(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        """A billed_amount of zero returns 400."""
        claim_id = _submit_denied_claim(client, seed)
        li_id = client.get(f"/api/claims/{claim_id}").get_json()["line_items"][0]["id"]
        resp = client.post(
            f"/api/claims/{claim_id}/disputes",
            json={
                "reason": "Amount.",
                "line_item_updates": [{"line_item_id": li_id, "billed_amount": "0.00"}],
            },
        )
        assert resp.status_code == 400

    def test_negative_billed_amount_returns_400(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        """A negative billed_amount returns 400."""
        claim_id = _submit_denied_claim(client, seed)
        li_id = client.get(f"/api/claims/{claim_id}").get_json()["line_items"][0]["id"]
        resp = client.post(
            f"/api/claims/{claim_id}/disputes",
            json={
                "reason": "Amount.",
                "line_item_updates": [{"line_item_id": li_id, "billed_amount": "-10.00"}],
            },
        )
        assert resp.status_code == 400

    def test_empty_cpt_code_returns_400(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        """An empty cpt_code returns 400."""
        claim_id = _submit_denied_claim(client, seed)
        li_id = client.get(f"/api/claims/{claim_id}").get_json()["line_items"][0]["id"]
        resp = client.post(
            f"/api/claims/{claim_id}/disputes",
            json={
                "reason": "CPT.",
                "line_item_updates": [{"line_item_id": li_id, "cpt_code": ""}],
            },
        )
        assert resp.status_code == 400

    def test_no_line_item_updates_still_works(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        """Submitting without line_item_updates is backward-compatible and returns 201."""
        claim_id = _submit_denied_claim(client, seed)
        resp = client.post(
            f"/api/claims/{claim_id}/disputes",
            json={"reason": "No corrections needed."},
        )
        assert resp.status_code == 201
        assert resp.get_json()["line_item_updates"] is None

    def test_cpt_correction_auto_adjudicates_to_paid(
        self, client: FlaskClient, seed: types.SimpleNamespace
    ) -> None:
        """Full flow: denied claim with corrected CPT → auto-adjudicates to paid at submission."""
        # Use a large billed amount to exceed the $500 deductible so plan pays something
        resp = client.post(
            "/api/claims",
            json={
                "member_id": seed.member.id,
                "provider_id": seed.provider.id,
                "date_of_service": "2026-03-01",
                "line_items": [
                    {"diagnosis_code": "M54.5", "cpt_code": "00000", "billed_amount": "700.00"}
                ],
            },
        )
        assert resp.status_code == 201
        claim_id = resp.get_json()["id"]
        assert resp.get_json()["status"] == "denied"

        li_id = client.get(f"/api/claims/{claim_id}").get_json()["line_items"][0]["id"]

        dispute_resp = client.post(
            f"/api/claims/{claim_id}/disputes",
            json={
                "reason": "Correct CPT should be 99213.",
                "line_item_updates": [{"line_item_id": li_id, "cpt_code": "99213"}],
            },
        )
        assert dispute_resp.status_code == 201

        # Claim should already be paid — no manual adjudication step needed.
        claim_data = client.get(f"/api/claims/{claim_id}").get_json()
        assert claim_data["status"] == "paid"

        # Manually triggering adjudication on an auto-resolved claim returns 409.
        adj_resp = client.post(f"/api/claims/{claim_id}/adjudicate", json={})
        assert adj_resp.status_code == 409
