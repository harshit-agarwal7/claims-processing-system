from flask import Flask, Response, jsonify
from werkzeug.exceptions import HTTPException


class ClaimsError(Exception):
    """Base exception for all application errors."""

    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class BadRequestError(ClaimsError):
    """400 — malformed input, missing/invalid fields."""

    status_code = 400
    error_code = "BAD_REQUEST"


class NotFoundError(ClaimsError):
    """404 — resource not found."""

    status_code = 404
    error_code = "NOT_FOUND"


class ValidationError(ClaimsError):
    """422 — valid input that fails a business rule."""

    status_code = 422
    error_code = "VALIDATION_ERROR"


class ConflictError(ClaimsError):
    """409 — operation invalid for current resource state."""

    status_code = 409
    error_code = "CONFLICT"


class ForbiddenError(ClaimsError):
    """403 — caller lacks permission."""

    status_code = 403
    error_code = "FORBIDDEN"


def register_error_handlers(app: Flask) -> None:
    """Register JSON error handlers for ClaimsError subclasses and standard HTTP errors.

    Args:
        app: The Flask application instance.
    """

    @app.errorhandler(ClaimsError)
    def handle_claims_error(e: ClaimsError) -> tuple[Response, int]:
        return jsonify({"error": e.error_code, "message": e.message}), e.status_code

    @app.errorhandler(404)
    def handle_404(e: HTTPException) -> tuple[Response, int]:
        return jsonify({"error": "NOT_FOUND", "message": "Resource not found"}), 404

    @app.errorhandler(405)
    def handle_405(e: HTTPException) -> tuple[Response, int]:
        return jsonify({"error": "METHOD_NOT_ALLOWED", "message": "Method not allowed"}), 405

    @app.errorhandler(500)
    def handle_500(e: Exception) -> tuple[Response, int]:
        return jsonify({"error": "INTERNAL_ERROR", "message": "An internal error occurred"}), 500
