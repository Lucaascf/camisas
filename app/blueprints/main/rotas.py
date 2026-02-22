"""Rotas do blueprint principal."""

from flask import render_template, send_file, abort
from flask_login import login_required, current_user
from io import BytesIO
from app.blueprints.main import main_bp
from app.models import Category, Product, ProductImage, Order, Wishlist
from app import db


@main_bp.route('/')
def home():
    """Página inicial."""
    categorias = Category.query.all()
    destaques = Product.query.filter_by(destaque=True, ativo=True).limit(4).all()
    return render_template('main/home.html', categorias=categorias, destaques=destaques)


@main_bp.route('/conta/pedidos')
@login_required
def meus_pedidos():
    """Lista de pedidos do usuário logado."""
    pedidos = Order.query.filter_by(user_id=current_user.id).order_by(Order.criado_em.desc()).all()
    return render_template('conta/pedidos.html', pedidos=pedidos)


@main_bp.route('/conta/pedidos/<int:id>')
@login_required
def meu_pedido_detalhe(id):
    """Detalhe de um pedido do usuário logado."""
    pedido = Order.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    return render_template('conta/pedido_detalhe.html', pedido=pedido)


@main_bp.route('/conta/favoritos/toggle', methods=['POST'])
@login_required
def toggle_favorito():
    """Adicionar/remover produto dos favoritos (AJAX)."""
    from flask import request, jsonify
    product_id = request.json.get('product_id')
    if not product_id:
        return jsonify(erro='product_id obrigatório'), 400

    produto = Product.query.get_or_404(product_id)
    existente = Wishlist.query.filter_by(user_id=current_user.id, product_id=produto.id).first()

    if existente:
        db.session.delete(existente)
        db.session.commit()
        return jsonify(favoritado=False)
    else:
        fav = Wishlist(user_id=current_user.id, product_id=produto.id)
        db.session.add(fav)
        db.session.commit()
        return jsonify(favoritado=True)


@main_bp.route('/conta/favoritos')
@login_required
def meus_favoritos():
    """Lista de produtos favoritos do usuário."""
    favoritos = Wishlist.query.filter_by(user_id=current_user.id).order_by(Wishlist.criado_em.desc()).all()
    return render_template('conta/favoritos.html', favoritos=favoritos)


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
