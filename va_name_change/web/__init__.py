"""Flask application factory for the VA Name Change web UI."""

from __future__ import annotations

import os

from flask import Flask

from va_name_change.config import config


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.getenv("VNC_SECRET_KEY", "dev-secret-change-in-production")

    # Ensure output directory exists
    os.makedirs(config.output_dir, exist_ok=True)

    from va_name_change.web.app import bp
    app.register_blueprint(bp)

    return app
