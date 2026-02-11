"""Blueprint administrativo."""

from flask import Blueprint

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

from app.blueprints.admin import rotas  # noqa: F401, E402
