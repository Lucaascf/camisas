"""Rotas do carrinho de compras."""

import uuid

from flask import flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user

from app import db
from app.blueprints.cart import cart_bp
from app.forms import CheckoutForm
from app.models import CartItem, Order, OrderItem, Product, ProductVariant


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
    variant_id = dados.get('variant_id')
    quantidade = dados.get('quantidade', 1)

    if not product_id:
        return jsonify(sucesso=False, mensagem='Produto não informado.'), 400

    produto = Product.query.get(product_id)
    if not produto or not produto.ativo:
        return jsonify(sucesso=False, mensagem='Produto não encontrado.'), 404

    if quantidade < 1:
        return jsonify(sucesso=False, mensagem='Quantidade inválida.'), 400

    # Verificar variante se fornecida
    variante = None
    estoque_disponivel = produto.estoque

    if variant_id:
        variante = ProductVariant.query.get(variant_id)
        if not variante or variante.product_id != produto.id or not variante.ativo:
            return jsonify(sucesso=False, mensagem='Variante não encontrada.'), 404
        estoque_disponivel = variante.estoque
    elif produto.tem_variantes:
        return jsonify(sucesso=False, mensagem='Por favor, selecione um tamanho.'), 400

    # Buscar item existente
    if current_user.is_authenticated:
        item = CartItem.query.filter_by(
            user_id=current_user.id,
            product_id=product_id,
            variant_id=variant_id
        ).first()
    else:
        item = CartItem.query.filter_by(
            session_id=obter_session_id(),
            product_id=product_id,
            variant_id=variant_id
        ).first()

    nova_qty = (item.quantidade if item else 0) + quantidade

    if nova_qty > estoque_disponivel:
        return jsonify(
            sucesso=False,
            mensagem=f'Estoque insuficiente. Disponível: {estoque_disponivel}.'
        ), 400

    if item:
        item.quantidade = nova_qty
    else:
        item = CartItem(
            product_id=product_id,
            variant_id=variant_id,
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

    # Verificar estoque disponível
    estoque_disponivel = item.variant.estoque if item.variant else item.product.estoque

    if quantidade > estoque_disponivel:
        return jsonify(
            sucesso=False,
            mensagem=f'Estoque insuficiente. Disponível: {estoque_disponivel}.'
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


@cart_bp.route('/checkout', methods=['GET', 'POST'])
def checkout():
    """Página de checkout."""
    itens = obter_itens_carrinho()

    if not itens:
        flash('Seu carrinho está vazio.', 'warning')
        return redirect(url_for('shop.listagem'))

    form = CheckoutForm()

    # Pré-preencher dados do usuário se estiver logado
    if current_user.is_authenticated and request.method == 'GET':
        form.nome.data = current_user.nome
        form.email.data = current_user.email

    if form.validate_on_submit():
        # Calcular total
        total = sum(item.product.preco_final * item.quantidade for item in itens)

        # Verificar estoque antes de criar o pedido
        for item in itens:
            estoque_disponivel = item.variant.estoque if item.variant else item.product.estoque
            if item.quantidade > estoque_disponivel:
                tamanho_info = f' (tamanho {item.variant.tamanho})' if item.variant else ''
                flash(f'Estoque insuficiente para {item.product.nome}{tamanho_info}. Disponível: {estoque_disponivel}', 'error')
                return redirect(url_for('cart.ver_carrinho'))

        # Criar pedido
        pedido = Order(
            user_id=current_user.id if current_user.is_authenticated else None,
            total=total,
            nome=form.nome.data,
            email=form.email.data,
            telefone=form.telefone.data,
            endereco=form.endereco.data,
            numero=form.numero.data,
            complemento=form.complemento.data,
            bairro=form.bairro.data,
            cidade=form.cidade.data,
            estado=form.estado.data,
            cep=form.cep.data,
            status='pendente'
        )
        db.session.add(pedido)
        db.session.flush()  # Para obter o ID do pedido

        # Criar itens do pedido e atualizar estoque
        for item in itens:
            order_item = OrderItem(
                order_id=pedido.id,
                product_id=item.product_id,
                variant_id=item.variant_id,
                tamanho=item.variant.tamanho if item.variant else None,
                quantidade=item.quantidade,
                preco_unitario=item.product.preco_final
            )
            db.session.add(order_item)

            # Atualizar estoque
            if item.variant:
                item.variant.estoque -= item.quantidade
            else:
                item.product.estoque -= item.quantidade

        # Limpar carrinho
        for item in itens:
            db.session.delete(item)

        db.session.commit()

        flash('Pedido realizado com sucesso!', 'success')
        return redirect(url_for('cart.confirmacao', order_id=pedido.id))

    # Calcular total para exibição
    total = sum(item.product.preco_final * item.quantidade for item in itens)

    return render_template('cart/checkout.html', form=form, itens=itens, total=total)


@cart_bp.route('/confirmacao/<int:order_id>')
def confirmacao(order_id):
    """Página de confirmação do pedido."""
    pedido = Order.query.get_or_404(order_id)

    # Verificar se o pedido pertence ao usuário atual (se logado) ou foi criado nesta sessão
    if current_user.is_authenticated:
        if pedido.user_id != current_user.id:
            flash('Pedido não encontrado.', 'error')
            return redirect(url_for('main.home'))

    return render_template('cart/confirmacao.html', pedido=pedido)
