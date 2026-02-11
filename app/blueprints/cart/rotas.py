"""Rotas do carrinho de compras."""

import uuid

from flask import jsonify, render_template, request, session
from flask_login import current_user

from app import db
from app.blueprints.cart import cart_bp
from app.models import CartItem, Product


# ── Helpers ──────────────────────────────────────────────

def obter_session_id():
    """Retorna (ou cria) o session_id do carrinho anônimo."""
    if 'cart_session_id' not in session:
        session['cart_session_id'] = str(uuid.uuid4())
    return session['cart_session_id']


def obter_itens_carrinho():
    """Retorna os CartItems da sessão/usuário atual."""
    if current_user.is_authenticated:
        return CartItem.query.filter_by(user_id=current_user.id).all()
    return CartItem.query.filter_by(session_id=obter_session_id()).all()


def contar_itens_carrinho():
    """Retorna a soma das quantidades no carrinho."""
    if current_user.is_authenticated:
        total = db.session.query(
            db.func.coalesce(db.func.sum(CartItem.quantidade), 0)
        ).filter_by(user_id=current_user.id).scalar()
    else:
        total = db.session.query(
            db.func.coalesce(db.func.sum(CartItem.quantidade), 0)
        ).filter_by(session_id=obter_session_id()).scalar()
    return total


# ── Rotas ────────────────────────────────────────────────

@cart_bp.route('/')
def ver_carrinho():
    """Página do carrinho."""
    itens = obter_itens_carrinho()
    total = sum(item.product.preco_final * item.quantidade for item in itens)
    return render_template('cart/carrinho.html', itens=itens, total=total)


@cart_bp.route('/adicionar', methods=['POST'])
def adicionar():
    """Adiciona um produto ao carrinho (AJAX)."""
    dados = request.get_json(silent=True) or {}
    product_id = dados.get('product_id')
    quantidade = dados.get('quantidade', 1)

    if not product_id:
        return jsonify(sucesso=False, mensagem='Produto não informado.'), 400

    produto = Product.query.get(product_id)
    if not produto or not produto.ativo:
        return jsonify(sucesso=False, mensagem='Produto não encontrado.'), 404

    if quantidade < 1:
        return jsonify(sucesso=False, mensagem='Quantidade inválida.'), 400

    # Buscar item existente
    if current_user.is_authenticated:
        item = CartItem.query.filter_by(
            user_id=current_user.id, product_id=product_id
        ).first()
    else:
        item = CartItem.query.filter_by(
            session_id=obter_session_id(), product_id=product_id
        ).first()

    nova_qty = (item.quantidade if item else 0) + quantidade

    if nova_qty > produto.estoque:
        return jsonify(
            sucesso=False,
            mensagem=f'Estoque insuficiente. Disponível: {produto.estoque}.'
        ), 400

    if item:
        item.quantidade = nova_qty
    else:
        item = CartItem(
            product_id=product_id,
            quantidade=quantidade,
            user_id=current_user.id if current_user.is_authenticated else None,
            session_id=None if current_user.is_authenticated else obter_session_id(),
        )
        db.session.add(item)

    db.session.commit()

    return jsonify(
        sucesso=True,
        cart_count=contar_itens_carrinho(),
        mensagem='Produto adicionado ao carrinho.',
    )


@cart_bp.route('/atualizar', methods=['POST'])
def atualizar():
    """Atualiza a quantidade de um item no carrinho (AJAX)."""
    dados = request.get_json(silent=True) or {}
    item_id = dados.get('item_id')
    quantidade = dados.get('quantidade')

    if item_id is None or quantidade is None:
        return jsonify(sucesso=False, mensagem='Dados incompletos.'), 400

    item = CartItem.query.get(item_id)
    if not item:
        return jsonify(sucesso=False, mensagem='Item não encontrado.'), 404

    # Verificar que o item pertence à sessão atual
    if current_user.is_authenticated:
        if item.user_id != current_user.id:
            return jsonify(sucesso=False, mensagem='Acesso negado.'), 403
    else:
        if item.session_id != obter_session_id():
            return jsonify(sucesso=False, mensagem='Acesso negado.'), 403

    if quantidade < 1:
        db.session.delete(item)
        db.session.commit()
        itens = obter_itens_carrinho()
        total = sum(i.product.preco_final * i.quantidade for i in itens)
        return jsonify(
            sucesso=True,
            removido=True,
            cart_count=contar_itens_carrinho(),
            total=f'{total:.2f}'.replace('.', ','),
        )

    if quantidade > item.product.estoque:
        return jsonify(
            sucesso=False,
            mensagem=f'Estoque insuficiente. Disponível: {item.product.estoque}.'
        ), 400

    item.quantidade = quantidade
    db.session.commit()

    item_subtotal = item.product.preco_final * item.quantidade
    itens = obter_itens_carrinho()
    total = sum(i.product.preco_final * i.quantidade for i in itens)

    return jsonify(
        sucesso=True,
        cart_count=contar_itens_carrinho(),
        total=f'{total:.2f}'.replace('.', ','),
        item_subtotal=f'{item_subtotal:.2f}'.replace('.', ','),
    )


@cart_bp.route('/remover/<int:item_id>', methods=['POST'])
def remover(item_id):
    """Remove um item do carrinho (AJAX)."""
    item = CartItem.query.get(item_id)
    if not item:
        return jsonify(sucesso=False, mensagem='Item não encontrado.'), 404

    # Verificar que o item pertence à sessão atual
    if current_user.is_authenticated:
        if item.user_id != current_user.id:
            return jsonify(sucesso=False, mensagem='Acesso negado.'), 403
    else:
        if item.session_id != obter_session_id():
            return jsonify(sucesso=False, mensagem='Acesso negado.'), 403

    db.session.delete(item)
    db.session.commit()

    itens = obter_itens_carrinho()
    total = sum(i.product.preco_final * i.quantidade for i in itens)

    return jsonify(
        sucesso=True,
        cart_count=contar_itens_carrinho(),
        total=f'{total:.2f}'.replace('.', ','),
    )
