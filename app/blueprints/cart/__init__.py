"""Blueprint do carrinho de compras."""

from flask import Blueprint

cart_bp = Blueprint('cart', __name__, url_prefix='/cart')

from app.blueprints.cart import rotas  # noqa: E402, F401
