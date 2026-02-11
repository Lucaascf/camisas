"""Rotas do blueprint principal."""

from flask import render_template
from app.blueprints.main import main_bp
from app.models import Category, Product


@main_bp.route('/')
def home():
    """Página inicial."""
    categorias = Category.query.all()
    destaques = Product.query.filter_by(destaque=True, ativo=True).limit(4).all()
    return render_template('main/home.html', categorias=categorias, destaques=destaques)
