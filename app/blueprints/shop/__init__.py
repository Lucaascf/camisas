"""Blueprint da loja (listagem e detalhe de produtos)."""

from flask import Blueprint

shop_bp = Blueprint('shop', __name__, url_prefix='/shop')

from app.blueprints.shop import rotas  # noqa: E402, F401
