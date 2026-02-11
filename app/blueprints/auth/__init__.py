"""Blueprint de autenticação."""

from flask import Blueprint

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

from app.blueprints.auth import rotas  # noqa: F401, E402
