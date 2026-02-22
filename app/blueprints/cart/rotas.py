"""Rotas do carrinho de compras."""

import logging
import secrets
import uuid
from datetime import datetime, timezone

from flask import flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user

from app import db, csrf
from app.blueprints.cart import cart_bp
from app.blueprints.cart import mercadopago_service
from app.blueprints.cart.email_pedido_service import enviar_email_pedido_confirmado
from app.forms import CheckoutForm
from app.models import CartItem, Order, OrderItem, Product, ProductVariant

logger = logging.getLogger(__name__)


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


@cart_bp.route('/calcular-frete', methods=['POST'])
def calcular_frete():
    """Calcula opções de frete via Melhor Envio (AJAX)."""
    from app.blueprints.cart.frete_service import calcular_frete as calc
    data = request.get_json() or {}
    cep = data.get('cep', '').replace('-', '')
    qtd = int(data.get('qtd', 1))
    if len(cep) != 8:
        return jsonify(erro='CEP inválido'), 400
    opcoes = calc(cep, qtd)
    if not opcoes:
        return jsonify(erro='Não foi possível calcular o frete para este CEP'), 503
    return jsonify(opcoes=opcoes)


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
        subtotal    = sum(item.product.preco_final * item.quantidade for item in itens)
        frete_valor = float(request.form.get('frete_valor') or 0)
        frete_tipo  = request.form.get('frete_tipo', '')
        total       = subtotal + frete_valor

        # Verificar estoque antes de criar o pedido
        for item in itens:
            estoque_disponivel = item.variant.estoque if item.variant else item.product.estoque
            if item.quantidade > estoque_disponivel:
                tamanho_info = f' (tamanho {item.variant.tamanho})' if item.variant else ''
                flash(f'Estoque insuficiente para {item.product.nome}{tamanho_info}. Disponível: {estoque_disponivel}', 'error')
                return redirect(url_for('cart.ver_carrinho'))

        # Criar pedido (sem atualizar estoque ainda - aguardando pagamento)
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
            frete_tipo=frete_tipo,
            frete_valor=frete_valor,
            status='aguardando_pagamento'
        )
        db.session.add(pedido)
        db.session.flush()  # Para obter o ID do pedido

        # Gerar código amigável para o cliente (ex: 260221-4839)
        _data = datetime.now(timezone.utc).strftime('%y%m%d')
        _sufixo = 1000 + secrets.randbelow(9000)
        pedido.codigo_cliente = f'{_data}-{_sufixo}'

        # Criar itens do pedido (SEM atualizar estoque ainda)
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

        db.session.commit()

        # Criar preferência no Mercado Pago
        try:
            preference_id, init_point = mercadopago_service.criar_preferencia(pedido, itens)

            # Salvar preference_id no pedido
            pedido.mercadopago_preference_id = preference_id
            db.session.commit()

            # Redirecionar para o Mercado Pago
            return redirect(init_point)

        except Exception as e:
            # Se falhar, cancelar o pedido
            pedido.status = 'cancelado'
            db.session.commit()
            flash(f'Erro ao processar pagamento: {str(e)}', 'error')
            return redirect(url_for('cart.ver_carrinho'))

    # Calcular total para exibição
    total = sum(item.product.preco_final * item.quantidade for item in itens)

    return render_template('cart/checkout.html', form=form, itens=itens, total=total)


@cart_bp.route('/confirmacao/<int:order_id>')
def confirmacao(order_id):
    """Página de confirmação do pedido."""
    pedido = Order.query.get_or_404(order_id)

    if current_user.is_authenticated:
        if pedido.user_id != current_user.id:
            flash('Pedido não encontrado.', 'error')
            return redirect(url_for('main.home'))

    # Webhook pode ter confirmado antes do usuário chegar — limpar carrinho se já pago
    if pedido.status == 'pago':
        if current_user.is_authenticated:
            CartItem.query.filter_by(user_id=current_user.id).delete()
        elif 'cart_session_id' in session:
            CartItem.query.filter_by(session_id=session['cart_session_id']).delete()
        db.session.commit()

    elif pedido.status == 'aguardando_pagamento':
        # Usar payment_id dos query params (redirect do MP) se disponível — mais direto
        payment_id_param = request.args.get('payment_id') or request.args.get('collection_id')

        try:
            if payment_id_param:
                resultado = mercadopago_service.consultar_pagamento_por_id(payment_id_param)
            elif pedido.mercadopago_preference_id:
                resultado = mercadopago_service.consultar_pagamento(pedido.mercadopago_preference_id)
            else:
                resultado = {'status': 'pending', 'payment_id': None}

            if resultado and resultado['status'] == 'approved':
                for item in pedido.items:
                    if item.variant:
                        item.variant.estoque -= item.quantidade
                    else:
                        item.product.estoque -= item.quantidade

                if current_user.is_authenticated:
                    CartItem.query.filter_by(user_id=current_user.id).delete()
                elif 'cart_session_id' in session:
                    CartItem.query.filter_by(session_id=session['cart_session_id']).delete()

                pedido.status = 'pago'
                pedido.mercadopago_payment_id = resultado['payment_id']
                db.session.commit()

                try:
                    enviar_email_pedido_confirmado(pedido)
                except Exception as e:
                    logger.error("EMAIL PEDIDO: erro ao enviar confirmação — %s", e)

                flash('Pagamento aprovado! Pedido confirmado com sucesso.', 'success')

            elif resultado and resultado['status'] in ('rejected', 'cancelled'):
                pedido.status = 'cancelado'
                db.session.commit()
                flash('Pagamento não foi aprovado. Por favor, tente novamente.', 'error')

        except Exception as e:
            logger.error("CONFIRMACAO: erro ao consultar pagamento — %s", e)
            flash('Verificando status do pagamento...', 'info')

    return render_template('cart/confirmacao.html', pedido=pedido)


@cart_bp.route('/webhook/mercadopago', methods=['POST'])
@csrf.exempt
def webhook_mercadopago():
    """Recebe notificações do Mercado Pago e confirma pagamentos."""
    try:
        data = request.get_json(silent=True) or {}
        topic = request.args.get('topic') or data.get('type', '')
        data_id = request.args.get('id') or request.args.get('data.id') or (data.get('data') or {}).get('id')

        logger.info(f'[WEBHOOK MP] topic={topic}, data_id={data_id}')

        if not data_id or topic not in ('payment', 'merchant_order'):
            return jsonify(status='ignored'), 200

        resultado = mercadopago_service.consultar_pagamento_por_id(str(data_id))
        if not resultado or not resultado.get('order_id'):
            return jsonify(status='not_found'), 200

        pedido = Order.query.get(resultado['order_id'])
        if not pedido:
            return jsonify(status='order_not_found'), 200

        if resultado['status'] == 'approved' and pedido.status == 'aguardando_pagamento':
            for item in pedido.items:
                if item.variant:
                    item.variant.estoque -= item.quantidade
                else:
                    item.product.estoque -= item.quantidade

            pedido.status = 'pago'
            pedido.mercadopago_payment_id = resultado['payment_id']
            db.session.commit()

            try:
                enviar_email_pedido_confirmado(pedido)
            except Exception as e:
                logger.error('EMAIL PEDIDO (webhook): erro — %s', e)

            logger.info(f'[WEBHOOK MP] Pedido #{pedido.id} marcado como PAGO')

        elif resultado['status'] in ('rejected', 'cancelled') and pedido.status == 'aguardando_pagamento':
            pedido.status = 'cancelado'
            db.session.commit()
            logger.info(f'[WEBHOOK MP] Pedido #{pedido.id} CANCELADO')

        return jsonify(status='ok'), 200

    except Exception as e:
        logger.error(f'[WEBHOOK MP] Erro: {e}')
        return jsonify(status='error'), 500
