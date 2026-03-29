"""Blueprint serving the frontend HTML pages."""

import logging

from flask import Blueprint, Response, current_app, send_from_directory

logger = logging.getLogger(__name__)
bp = Blueprint("pages", __name__)


@bp.route("/")
def dashboard() -> Response:
    """Serve the member dashboard page.

    Returns:
        The index.html static file.
    """
    return send_from_directory(current_app.static_folder, "index.html")  # type: ignore[arg-type]


@bp.route("/claim")
def claim() -> Response:
    """Serve the claim detail page.

    Returns:
        The claim.html static file.
    """
    return send_from_directory(current_app.static_folder, "claim.html")  # type: ignore[arg-type]


@bp.route("/admin")
def admin() -> Response:
    """Serve the admin panel page.

    Returns:
        The admin.html static file.
    """
    return send_from_directory(current_app.static_folder, "admin.html")  # type: ignore[arg-type]
