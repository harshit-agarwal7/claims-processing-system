import logging
from decimal import Decimal

from flask import Flask
from flask.json.provider import DefaultJSONProvider

from config.settings import Config

from .errors import register_error_handlers
from .extensions import db, migrate
from .routes import register_routes


class DecimalJSONProvider(DefaultJSONProvider):
    """JSON provider that serialises Decimal values as strings."""

    def default(self, o: object) -> object:
        """Serialise Decimal to string; delegate all other types to the default handler.

        Args:
            o: The object to serialise.

        Returns:
            A JSON-serialisable representation.
        """
        if isinstance(o, Decimal):
            return str(o)
        return super().default(o)


def create_app(config_object: object = Config) -> Flask:
    """Application factory.

    Args:
        config_object: A configuration class or object passed to ``app.config.from_object``.

    Returns:
        A configured Flask application instance.
    """
    logging.basicConfig(level=logging.INFO)

    app = Flask(__name__, static_folder="static")
    app.json_provider_class = DecimalJSONProvider
    app.config.from_object(config_object)

    db.init_app(app)
    migrate.init_app(app, db)

    register_routes(app)
    register_error_handlers(app)

    return app
