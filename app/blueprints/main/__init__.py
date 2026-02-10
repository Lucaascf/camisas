"""Blueprint principal (home, páginas estáticas)."""

from flask import Blueprint

main_bp = Blueprint('main', __name__, url_prefix='/')

from app.blueprints.main import rotas  # noqa: E402, F401
