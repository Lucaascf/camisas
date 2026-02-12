"""Blueprint de pagamentos - Mercado Pago."""

from flask import Blueprint

payments_bp = Blueprint('payments', __name__, url_prefix='/payments')

from app.blueprints.payments import rotas
