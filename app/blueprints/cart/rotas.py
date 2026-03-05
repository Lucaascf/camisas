"""Rotas do carrinho de compras."""

import logging
import secrets
import uuid
from datetime import datetime, timezone, timedelta

from flask import current_app, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user

from app import db, csrf, limiter
from app.blueprints.cart import cart_bp
from app.blueprints.cart import mercadopago_service
from app.blueprints.cart.email_pedido_service import enviar_email_pedido_confirmado
from app.forms import CheckoutForm
from app.models import CartItem, Cupom, EnderecoSalvo, Order, OrderItem, Product, ProductVariant

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
@limiter.limit("30 per minute")
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
@limiter.limit("30 per minute")
def atualizar():
    """Atualiza a quantidade de um item no carrinho (AJAX)."""
    dados = request.get_json(silent=True) or {}
    item_id = dados.get('item_id')
    quantidade = dados.get('quantidade')

    if item_id is None or quantidade is None:
        return jsonify(sucesso=False, mensagem='Dados incompletos.'), 400

    # Verificar ownership diretamente na query (evita IDOR)
    if current_user.is_authenticated:
        item = CartItem.query.filter_by(id=item_id, user_id=current_user.id).first()
    else:
        item = CartItem.query.filter_by(id=item_id, session_id=obter_session_id()).first()
    if not item:
        return jsonify(sucesso=False, mensagem='Item não encontrado.'), 404

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
@limiter.limit("30 per minute")
def remover(item_id):
    """Remove um item do carrinho (AJAX)."""
    # Verificar ownership diretamente na query (evita IDOR)
    if current_user.is_authenticated:
        item = CartItem.query.filter_by(id=item_id, user_id=current_user.id).first()
    else:
        item = CartItem.query.filter_by(id=item_id, session_id=obter_session_id()).first()
    if not item:
        return jsonify(sucesso=False, mensagem='Item não encontrado.'), 404

    db.session.delete(item)
    db.session.commit()

    itens = obter_itens_carrinho()
    total = sum(i.product.preco_final * i.quantidade for i in itens)

    return jsonify(
        sucesso=True,
        cart_count=contar_itens_carrinho(),
        total=f'{total:.2f}'.replace('.', ','),
    )


@cart_bp.route('/aplicar-cupom', methods=['POST'])
@limiter.limit("20 per minute")
def aplicar_cupom():
    """Valida e aplica um cupom de desconto (AJAX)."""
    dados = request.get_json() or {}
    codigo = (dados.get('codigo') or '').strip().upper()

    cupom = Cupom.query.filter_by(codigo=codigo, ativo=True).first()
    agora = datetime.now(timezone.utc)

    if not cupom:
        return jsonify({'valido': False, 'mensagem': 'Cupom inválido.'})
    if cupom.validade:
        validade = cupom.validade.replace(tzinfo=timezone.utc) if cupom.validade.tzinfo is None else cupom.validade
        if validade < agora:
            return jsonify({'valido': False, 'mensagem': 'Cupom expirado.'})
    if cupom.usos_maximos and cupom.usos_atuais >= cupom.usos_maximos:
        return jsonify({'valido': False, 'mensagem': 'Cupom esgotado.'})

    # Recalcular subtotal a partir do banco — nunca confiar no valor enviado pelo cliente
    itens = obter_itens_carrinho()
    subtotal = sum(item.product.preco_final * item.quantidade for item in itens)
    desconto = round(subtotal * cupom.desconto_percentual / 100, 2)
    return jsonify({
        'valido': True,
        'desconto_percentual': cupom.desconto_percentual,
        'desconto_valor': desconto,
        'mensagem': f'{cupom.desconto_percentual:.0f}% de desconto aplicado!'
    })


@cart_bp.route('/calcular-frete', methods=['POST'])
def calcular_frete():
    """Calcula opções de frete (local ou Melhor Envio) com suporte a frete grátis (AJAX)."""
    from app.blueprints.cart.frete_service import (
        calcular_frete as calc_api,
        is_salvador_lf, calcular_frete_local, dados_do_cep,
    )
    from app.models import ConfigFrete
    data     = request.get_json() or {}
    cep      = data.get('cep', '').replace('-', '')
    try:
        qtd      = max(1, int(data.get('qtd', 1)))
        subtotal = max(0.0, float(data.get('subtotal', 0)))
    except (ValueError, TypeError):
        return jsonify(erro='Dados inválidos'), 400

    if len(cep) != 8:
        return jsonify(erro='CEP inválido'), 400

    # Detectar cidade/estado diretamente no backend (independente do cliente)
    _dados = dados_do_cep(cep)
    cidade = _dados.get('localidade', '')
    estado = _dados.get('uf', '')
    if not cidade:
        cidade = data.get('cidade', '')
        estado = data.get('estado', '')

    if is_salvador_lf(cidade, estado):
        opcoes = calcular_frete_local(subtotal)
    else:
        opcoes = calc_api(cep, qtd)
        # Se subtotal atingir limiar, substituir todas as opções por "Frete Grátis"
        if opcoes:
            config = ConfigFrete.get()
            if config.fora_gratis_acima is not None and subtotal >= config.fora_gratis_acima:
                opcoes = [{
                    'id':             'Frete Grátis',
                    'nome':           'Grátis',
                    'transportadora': '',
                    'preco':          0.0,
                    'prazo':          '',
                }]

    if not opcoes:
        return jsonify(erro='Não foi possível calcular o frete para este CEP'), 503
    return jsonify(opcoes=opcoes, endereco=_dados)


@cart_bp.route('/checkout')
def checkout():
    """Página de checkout."""
    itens = obter_itens_carrinho()

    if not itens:
        flash('Seu carrinho está vazio.', 'warning')
        return redirect(url_for('shop.listagem'))

    form = CheckoutForm()

    # Pré-preencher dados do usuário se estiver logado
    enderecos_salvos = []
    if current_user.is_authenticated:
        form.nome.data = current_user.nome
        form.email.data = current_user.email
        enderecos_salvos = EnderecoSalvo.query.filter_by(
            user_id=current_user.id
        ).order_by(EnderecoSalvo.criado_em.desc()).all()

    total = sum(item.product.preco_final * item.quantidade for item in itens)
    mp_public_key = current_app.config.get('MERCADOPAGO_PUBLIC_KEY', '')

    return render_template(
        'cart/checkout.html',
        form=form,
        itens=itens,
        total=total,
        enderecos_salvos=enderecos_salvos,
        mp_public_key=mp_public_key,
    )


@cart_bp.route('/processar-pagamento', methods=['POST'])
@limiter.limit("5 per minute")
def processar_pagamento():
    """Processa pagamento via Payment Brick (endpoint JSON)."""
    dados = request.get_json(silent=True) or {}
    form_data = dados.get('form', {})
    payment_data = dados.get('payment', {})

    # Validar campos obrigatórios
    for campo in ('nome', 'email', 'cep', 'endereco', 'numero', 'bairro', 'cidade', 'estado', 'frete_tipo'):
        if not str(form_data.get(campo, '')).strip():
            return jsonify(ok=False, error=f'Campo obrigatório não preenchido: {campo}'), 400

    if not payment_data.get('payment_method_id'):
        return jsonify(ok=False, error='Dados de pagamento inválidos.'), 400

    itens = obter_itens_carrinho()
    if not itens:
        return jsonify(ok=False, error='Carrinho vazio.'), 400

    # Recalcular frete no backend
    from app.blueprints.cart.frete_service import (
        calcular_frete as calc_api,
        is_salvador_lf, calcular_frete_local, cidade_do_cep,
    )
    from app.models import ConfigFrete

    subtotal = sum(item.product.preco_final * item.quantidade for item in itens)
    frete_tipo = form_data['frete_tipo']
    _cep = form_data['cep'].replace('-', '')
    _qtd = sum(item.quantidade for item in itens)

    _cidade, _estado = cidade_do_cep(_cep)
    if not _cidade:
        _cidade = form_data.get('cidade', '')
        _estado = form_data.get('estado', '')

    if is_salvador_lf(_cidade, _estado):
        _opcoes_frete = calcular_frete_local(subtotal)
    else:
        _opcoes_frete = calc_api(_cep, _qtd)
        if _opcoes_frete:
            config = ConfigFrete.get()
            if config.fora_gratis_acima is not None and subtotal >= config.fora_gratis_acima:
                _opcoes_frete = [{'id': 'Frete Grátis', 'nome': 'Grátis', 'transportadora': '', 'preco': 0.0, 'prazo': ''}]

    _opcao = next((o for o in (_opcoes_frete or []) if o['id'] == frete_tipo), None)
    if _opcao is None and _opcoes_frete and len(_opcoes_frete) == 1:
        _opcao = _opcoes_frete[0]
    if _opcao is None:
        return jsonify(ok=False, error='Opção de frete inválida. Recarregue a página e tente novamente.'), 400

    frete_valor = float(_opcao['preco'])

    # Revalidar cupom no backend
    cupom_codigo_form = str(form_data.get('cupom_codigo', '')).strip().upper()
    desconto_valor = 0.0
    cupom_aplicado = None
    if cupom_codigo_form:
        cupom_obj = Cupom.query.filter_by(codigo=cupom_codigo_form, ativo=True).first()
        agora = datetime.now(timezone.utc)
        if cupom_obj:
            validade_ok = True
            if cupom_obj.validade:
                val = cupom_obj.validade.replace(tzinfo=timezone.utc) if cupom_obj.validade.tzinfo is None else cupom_obj.validade
                validade_ok = val >= agora
            usos_ok = not cupom_obj.usos_maximos or cupom_obj.usos_atuais < cupom_obj.usos_maximos
            if validade_ok and usos_ok:
                desconto_valor = round(subtotal * cupom_obj.desconto_percentual / 100, 2)
                cupom_aplicado = cupom_obj

    total = subtotal + frete_valor - desconto_valor

    # Verificar estoque
    for item in itens:
        estoque_disponivel = item.variant.estoque if item.variant else item.product.estoque
        if item.quantidade > estoque_disponivel:
            tamanho_info = f' (tamanho {item.variant.tamanho})' if item.variant else ''
            return jsonify(ok=False, error=f'Estoque insuficiente para {item.product.nome}{tamanho_info}. Disponível: {estoque_disponivel}.'), 400

    # Criar pedido
    pedido = Order(
        user_id=current_user.id if current_user.is_authenticated else None,
        total=total,
        nome=form_data['nome'].strip(),
        email=form_data['email'].strip(),
        telefone=str(form_data.get('telefone', '')).strip(),
        endereco=form_data['endereco'].strip(),
        numero=form_data['numero'].strip(),
        complemento=str(form_data.get('complemento', '')).strip() or None,
        bairro=form_data['bairro'].strip(),
        cidade=form_data['cidade'].strip(),
        estado=form_data['estado'].strip(),
        cep=form_data['cep'].strip(),
        frete_tipo=frete_tipo,
        frete_valor=frete_valor,
        cupom_codigo=cupom_aplicado.codigo if cupom_aplicado else None,
        desconto_valor=desconto_valor,
        status='aguardando_pagamento',
    )
    pedido.token_anonimo = secrets.token_urlsafe(32)
    db.session.add(pedido)
    db.session.flush()

    _data = datetime.now(timezone.utc).strftime('%y%m%d')
    _sufixo = 1000 + secrets.randbelow(9000)
    pedido.codigo_cliente = f'{_data}-{_sufixo}'

    for item in itens:
        db.session.add(OrderItem(
            order_id=pedido.id,
            product_id=item.product_id,
            variant_id=item.variant_id,
            tamanho=item.variant.tamanho if item.variant else None,
            cor=item.variant.cor if item.variant else None,
            quantidade=item.quantidade,
            preco_unitario=item.product.preco_final,
        ))

    db.session.commit()
    session['ultimo_pedido_id'] = pedido.id
    session['ultimo_pedido_token'] = pedido.token_anonimo

    # Salvar endereço (usuários autenticados)
    if current_user.is_authenticated and form_data.get('salvar_endereco') == '1':
        ja_existe = EnderecoSalvo.query.filter_by(
            user_id=current_user.id,
            cep=form_data['cep'],
            numero=form_data['numero'],
        ).first()
        if not ja_existe:
            db.session.add(EnderecoSalvo(
                user_id=current_user.id,
                apelido=str(form_data.get('apelido_endereco', '')).strip() or None,
                cep=form_data['cep'].strip(),
                endereco=form_data['endereco'].strip(),
                numero=form_data['numero'].strip(),
                complemento=str(form_data.get('complemento', '')).strip() or None,
                bairro=form_data['bairro'].strip(),
                cidade=form_data['cidade'].strip(),
                estado=form_data['estado'].strip(),
            ))
            db.session.commit()

    # Chamar API de pagamento
    try:
        resposta = mercadopago_service.criar_pagamento(pedido, payment_data)
    except Exception as e:
        pedido.status = 'cancelado'
        db.session.commit()
        logger.error('[PAGAMENTO] Erro na API MP: %s', e)
        return jsonify(ok=False, error='Erro ao conectar com o serviço de pagamento. Tente novamente.'), 502

    mp_status = resposta.get('status', '')
    mp_payment_id = str(resposta.get('id', ''))
    pedido.mercadopago_payment_id = mp_payment_id

    if mp_status == 'approved':
        # Cartão aprovado: baixar estoque de forma atômica (evita overselling em race conditions)
        for item in pedido.items:
            if item.variant:
                resultado = db.session.execute(
                    db.update(ProductVariant)
                    .where(ProductVariant.id == item.variant_id)
                    .where(ProductVariant.estoque >= item.quantidade)
                    .values(estoque=ProductVariant.estoque - item.quantidade)
                )
            else:
                resultado = db.session.execute(
                    db.update(Product)
                    .where(Product.id == item.product_id)
                    .where(Product.estoque >= item.quantidade)
                    .values(estoque=Product.estoque - item.quantidade)
                )
            if resultado.rowcount == 0:
                # Estoque insuficiente no momento do commit — cancelar pedido
                pedido.status = 'cancelado'
                db.session.commit()
                tamanho_info = f' (tamanho {item.variant.tamanho})' if item.variant else ''
                return jsonify(ok=False, error=f'Estoque insuficiente para {item.product.nome}{tamanho_info}. Tente novamente.'), 409

        pedido.status = 'pago'

        if current_user.is_authenticated:
            CartItem.query.filter_by(user_id=current_user.id).delete()
        elif 'cart_session_id' in session:
            CartItem.query.filter_by(session_id=session['cart_session_id']).delete()

        if cupom_aplicado:
            db.session.execute(
                db.update(Cupom)
                .where(Cupom.id == cupom_aplicado.id)
                .values(usos_atuais=Cupom.usos_atuais + 1)
            )

        db.session.commit()

        try:
            enviar_email_pedido_confirmado(pedido)
        except Exception as e:
            logger.error('[PAGAMENTO] Erro ao enviar email: %s', e)

        return jsonify(ok=True, order_id=pedido.id, status='pago')

    elif mp_status in ('pending', 'in_process'):
        # PIX ou pagamento pendente: salvar QR code se disponível
        poi = resposta.get('point_of_interaction', {})
        td = poi.get('transaction_data', {})
        pedido.pix_qr_code = td.get('qr_code')
        pedido.pix_qr_code_base64 = td.get('qr_code_base64')
        pedido.mercadopago_payment_id = str(resposta.get('id', ''))
        db.session.commit()

        tz_br = timezone(timedelta(hours=-3))
        pix_expires_at = int((datetime.now(tz_br) + timedelta(minutes=15)).timestamp())

        return jsonify(
            ok=True,
            order_id=pedido.id,
            status='aguardando_pagamento',
            pix_qr=pedido.pix_qr_code,
            pix_img=pedido.pix_qr_code_base64,
            pix_expires_at=pix_expires_at,
        )

    else:
        # Rejeitado
        pedido.status = 'cancelado'
        db.session.commit()
        status_detail = resposta.get('status_detail', '')
        msg = _mensagem_rejeicao(status_detail)
        return jsonify(ok=False, error=msg)


def _mensagem_rejeicao(status_detail):
    """Converte status_detail do MP em mensagem amigável."""
    mapa = {
        'cc_rejected_insufficient_amount': 'Saldo insuficiente no cartão.',
        'cc_rejected_bad_filled_card_number': 'Número do cartão incorreto.',
        'cc_rejected_bad_filled_date': 'Data de validade incorreta.',
        'cc_rejected_bad_filled_security_code': 'Código de segurança incorreto.',
        'cc_rejected_blacklist': 'Cartão bloqueado. Contate sua operadora.',
        'cc_rejected_call_for_authorize': 'Pagamento não autorizado. Contate sua operadora.',
        'cc_rejected_card_disabled': 'Cartão desativado. Contate sua operadora.',
        'cc_rejected_duplicated_payment': 'Pagamento duplicado detectado.',
        'cc_rejected_high_risk': 'Pagamento recusado por segurança.',
        'cc_rejected_max_attempts': 'Excedeu as tentativas permitidas. Tente outro cartão.',
    }
    return mapa.get(status_detail, 'Pagamento não aprovado. Verifique os dados do cartão e tente novamente.')


@cart_bp.route('/pix-status/<int:order_id>')
def pix_status(order_id):
    """Retorna o status atual do pedido para polling de PIX."""
    pedido = Order.query.get_or_404(order_id)

    # Mesma verificação de acesso da página de confirmação
    if current_user.is_authenticated:
        if pedido.user_id != current_user.id:
            return jsonify(status='error'), 403
    elif pedido.user_id is not None:
        return jsonify(status='error'), 403
    else:
        token_sessao = session.get('ultimo_pedido_token')
        if not token_sessao or not pedido.token_anonimo or not secrets.compare_digest(str(pedido.token_anonimo), str(token_sessao)):
            return jsonify(status='error'), 403

    # Se ainda pendente e temos o payment_id, consultar MP
    if pedido.status == 'aguardando_pagamento' and pedido.mercadopago_payment_id:
        try:
            resultado = mercadopago_service.consultar_pagamento_por_id(
                pedido.mercadopago_payment_id
            )
            if resultado and resultado['status'] == 'approved':
                pedido.status = 'pago'
                db.session.commit()
        except Exception as e:
            current_app.logger.warning('[pix_status] erro ao consultar MP: %s', e)

    return jsonify(status=pedido.status)


@cart_bp.route('/regenerar-pix/<int:order_id>')
def regenerar_pix(order_id):
    """Gera um novo código PIX para um pedido expirado ou pendente."""
    pedido = Order.query.get_or_404(order_id)

    if current_user.is_authenticated:
        if pedido.user_id != current_user.id:
            return jsonify(ok=False, error='Acesso negado'), 403
    elif pedido.user_id is not None:
        return jsonify(ok=False, error='Acesso negado'), 403
    else:
        token_sessao = session.get('ultimo_pedido_token')
        if not token_sessao or not pedido.token_anonimo or not secrets.compare_digest(str(pedido.token_anonimo), str(token_sessao)):
            return jsonify(ok=False, error='Acesso negado'), 403

    if pedido.status not in ('aguardando_pagamento', 'cancelado'):
        return jsonify(ok=False, error='Pedido não pode ser reprocessado'), 400

    payment_data = {"payment_method_id": "pix", "payer": {"email": pedido.email}}
    try:
        resposta = mercadopago_service.criar_pagamento(pedido, payment_data)
    except Exception as e:
        current_app.logger.error('[regenerar_pix] %s', e)
        return jsonify(ok=False, error='Erro ao gerar novo PIX'), 500

    poi = resposta.get('point_of_interaction', {})
    td = poi.get('transaction_data', {})
    pedido.pix_qr_code = td.get('qr_code')
    pedido.pix_qr_code_base64 = td.get('qr_code_base64')
    pedido.mercadopago_payment_id = str(resposta.get('id', ''))
    pedido.status = 'aguardando_pagamento'
    db.session.commit()

    tz_br = timezone(timedelta(hours=-3))
    pix_expires_at = int((datetime.now(tz_br) + timedelta(minutes=15)).timestamp())

    return jsonify(
        ok=True,
        pix_qr=pedido.pix_qr_code,
        pix_img=pedido.pix_qr_code_base64,
        pix_expires_at=pix_expires_at,
    )


@cart_bp.route('/confirmacao/<int:order_id>')
def confirmacao(order_id):
    """Página de confirmação do pedido."""
    pedido = Order.query.get_or_404(order_id)

    if current_user.is_authenticated:
        if pedido.user_id != current_user.id:
            flash('Pedido não encontrado.', 'error')
            return redirect(url_for('main.home'))
    elif pedido.user_id is not None:
        # Pedido pertence a um usuário cadastrado — exigir login
        flash('Faça login para ver este pedido.', 'error')
        return redirect(url_for('auth.login'))
    else:
        # Pedido anônimo — validar por token seguro (evita IDOR por ID sequencial)
        token_sessao = session.get('ultimo_pedido_token')
        if not token_sessao or not pedido.token_anonimo or not secrets.compare_digest(str(pedido.token_anonimo), str(token_sessao)):
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
                # Validar que o pagamento pertence a este pedido (evita payment_id injection)
                if resultado and resultado.get('order_id') != pedido.id:
                    logger.warning('[CONFIRMACAO] payment_id %s não pertence ao pedido %s', payment_id_param, pedido.id)
                    resultado = None
            elif pedido.mercadopago_preference_id:
                resultado = mercadopago_service.consultar_pagamento(pedido.mercadopago_preference_id)
            else:
                resultado = {'status': 'pending', 'payment_id': None}

            if resultado and resultado['status'] == 'approved':
                # Atualização atômica: só aplica se o pedido ainda está aguardando pagamento
                resultado_update = db.session.execute(
                    db.update(Order)
                    .where(Order.id == pedido.id, Order.status == 'aguardando_pagamento')
                    .values(status='pago', mercadopago_payment_id=resultado['payment_id'])
                )
                if resultado_update.rowcount == 0:
                    # Já processado por outro request (webhook ou chamada paralela)
                    db.session.refresh(pedido)
                else:
                    db.session.refresh(pedido)
                    for item in pedido.items:
                        if item.variant:
                            item.variant.estoque -= item.quantidade
                        else:
                            item.product.estoque -= item.quantidade

                    if current_user.is_authenticated:
                        CartItem.query.filter_by(user_id=current_user.id).delete()
                    elif 'cart_session_id' in session:
                        CartItem.query.filter_by(session_id=session['cart_session_id']).delete()

                    # Incrementar uso do cupom (atômico para evitar race condition)
                    if pedido.cupom_codigo:
                        cupom_usado = Cupom.query.filter_by(codigo=pedido.cupom_codigo).first()
                        if cupom_usado:
                            db.session.execute(
                                db.update(Cupom)
                                .where(Cupom.id == cupom_usado.id)
                                .values(usos_atuais=Cupom.usos_atuais + 1)
                            )

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

    mostrar_dados_pessoais = current_user.is_authenticated
    return render_template('cart/confirmacao.html', pedido=pedido,
                           mostrar_dados_pessoais=mostrar_dados_pessoais)


@cart_bp.route('/webhook/mercadopago', methods=['POST'])
@csrf.exempt
def webhook_mercadopago():
    """Recebe notificações do Mercado Pago e confirma pagamentos."""
    if not mercadopago_service.validar_assinatura_webhook(request):
        logger.warning('[WEBHOOK MP] Assinatura inválida — requisição rejeitada')
        return jsonify(status='unauthorized'), 401

    try:
        data = request.get_json(silent=True) or {}
        topic = request.args.get('topic') or data.get('type', '')
        data_id = request.args.get('id') or request.args.get('data.id') or (data.get('data') or {}).get('id')

        logger.info(f'[WEBHOOK MP] topic={topic}, data_id={data_id}')

        if not data_id or topic != 'payment':
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
                    res = db.session.execute(
                        db.update(ProductVariant)
                        .where(ProductVariant.id == item.variant_id)
                        .where(ProductVariant.estoque >= item.quantidade)
                        .values(estoque=ProductVariant.estoque - item.quantidade)
                    )
                else:
                    res = db.session.execute(
                        db.update(Product)
                        .where(Product.id == item.product_id)
                        .where(Product.estoque >= item.quantidade)
                        .values(estoque=Product.estoque - item.quantidade)
                    )
                if res.rowcount == 0:
                    logger.warning('[WEBHOOK MP] Estoque insuficiente para item %s no pedido %s', item.id, pedido.id)

            pedido.status = 'pago'
            pedido.mercadopago_payment_id = resultado['payment_id']

            # Limpar carrinho do usuário autenticado
            if pedido.user_id:
                CartItem.query.filter_by(user_id=pedido.user_id).delete()

            # Incrementar uso do cupom (atômico para evitar race condition)
            if pedido.cupom_codigo:
                cupom_usado = Cupom.query.filter_by(codigo=pedido.cupom_codigo).first()
                if cupom_usado:
                    db.session.execute(
                        db.update(Cupom)
                        .where(Cupom.id == cupom_usado.id)
                        .values(usos_atuais=Cupom.usos_atuais + 1)
                    )

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
