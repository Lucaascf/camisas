"""Rotas do blueprint principal."""

from flask import render_template, send_file, abort
from io import BytesIO
from app.blueprints.main import main_bp
from app.models import Category, Product, ProductImage


@main_bp.route('/')
def home():
    """Página inicial."""
    categorias = Category.query.all()
    destaques = Product.query.filter_by(destaque=True, ativo=True).limit(4).all()
    return render_template('main/home.html', categorias=categorias, destaques=destaques)


@main_bp.route('/produto/imagem/<int:image_id>')
def servir_imagem(image_id):
    """Serve uma imagem de produto armazenada no banco de dados."""
    imagem = ProductImage.query.get_or_404(image_id)
    return send_file(
        BytesIO(imagem.data),
        mimetype=imagem.mimetype,
        as_attachment=False,
        download_name=imagem.filename
    )
