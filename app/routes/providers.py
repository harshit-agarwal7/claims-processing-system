"""Blueprint for /api/providers endpoints."""

import logging

from flask import Blueprint, Response, jsonify, request

from app.errors import BadRequestError, ConflictError, NotFoundError
from app.extensions import db
from app.models import Provider, ProviderType

logger = logging.getLogger(__name__)
bp = Blueprint("providers", __name__, url_prefix="/api/providers")


def _serialize_provider(provider: Provider) -> dict[str, object]:
    """Serialise a Provider ORM object to a JSON-safe dict.

    Args:
        provider: The Provider instance to serialise.

    Returns:
        A dict with provider fields.
    """
    return {
        "id": provider.id,
        "name": provider.name,
        "npi": provider.npi,
        "provider_type": provider.provider_type.value,
        "created_at": provider.created_at.isoformat(),
    }


@bp.route("", methods=["POST"])
def create_provider() -> tuple[Response, int]:
    """Create a new provider.

    Returns:
        201 with the created provider, or 400/409 on error.
    """
    data = request.get_json(silent=True) or {}

    name = data.get("name")
    npi = data.get("npi")
    provider_type_str = data.get("provider_type")

    if not name or not npi or not provider_type_str:
        raise BadRequestError("name, npi, and provider_type are required")

    try:
        provider_type = ProviderType(provider_type_str)
    except ValueError as exc:
        valid = [t.value for t in ProviderType]
        raise BadRequestError(f"provider_type must be one of: {valid}") from exc

    existing = db.session.execute(
        db.select(Provider).where(Provider.npi == npi, Provider.deleted_at.is_(None))
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(f"A provider with NPI '{npi}' already exists")

    provider = Provider(name=name, npi=npi, provider_type=provider_type)
    db.session.add(provider)
    db.session.commit()

    logger.info("provider %s created", provider.id)
    return jsonify(_serialize_provider(provider)), 201


@bp.route("/<provider_id>", methods=["GET"])
def get_provider(provider_id: str) -> Response:
    """Retrieve a single provider by ID.

    Args:
        provider_id: UUID of the provider.

    Returns:
        200 with provider data, or 404 if not found.
    """
    provider = db.session.execute(
        db.select(Provider).where(Provider.id == provider_id, Provider.deleted_at.is_(None))
    ).scalar_one_or_none()
    if provider is None:
        raise NotFoundError(f"Provider '{provider_id}' not found")
    return jsonify(_serialize_provider(provider))
