"""Rotas do blueprint principal."""

from flask import render_template
from app.blueprints.main import main_bp


@main_bp.route('/')
def home():
    """Página inicial."""
    return render_template('main/home.html')
