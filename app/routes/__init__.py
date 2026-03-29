from flask import Flask

from .claims import bp as claims_bp
from .members import bp as members_bp
from .pages import bp as pages_bp
from .plans import bp as plans_bp
from .policies import bp as policies_bp
from .providers import bp as providers_bp


def register_routes(app: Flask) -> None:
    """Register all API blueprints with the application.

    Args:
        app: The Flask application instance.
    """
    app.register_blueprint(pages_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(providers_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(policies_bp)
    app.register_blueprint(claims_bp)
