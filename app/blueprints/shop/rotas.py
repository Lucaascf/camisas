"""Rotas do blueprint shop."""

from flask import abort, render_template

from app.blueprints.shop import shop_bp
from app.models import Category, Product


@shop_bp.route('/')
@shop_bp.route('/<slug>')
def listagem(slug=None):
    """Listagem de produtos — todos ou filtrados por categoria."""
    categoria = None

    if slug:
        categoria = Category.query.filter_by(slug=slug).first_or_404()
        produtos = Product.query.filter_by(
            categoria_id=categoria.id, ativo=True
        ).all()
    else:
        produtos = Product.query.filter_by(ativo=True).all()

    return render_template(
        'shop/listagem.html',
        categoria=categoria,
        produtos=produtos,
    )


@shop_bp.route('/produto/<slug>')
def produto(slug):
    """Página de detalhe de um produto."""
    produto = Product.query.filter_by(slug=slug, ativo=True).first_or_404()
    return render_template('shop/produto.html', produto=produto)
