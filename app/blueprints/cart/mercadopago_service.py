"""Serviço de integração com Mercado Pago."""

import hashlib
import hmac
import json
import mercadopago
from flask import current_app, url_for


def _get_sdk():
    """Retorna instância configurada do SDK Mercado Pago."""
    token = current_app.config.get('MERCADOPAGO_ACCESS_TOKEN')
    if not token:
        raise ValueError('MERCADOPAGO_ACCESS_TOKEN não configurado')
    return mercadopago.SDK(token)


def validar_assinatura_webhook(request) -> bool:
    """
    Valida a assinatura HMAC-SHA256 enviada pelo Mercado Pago no header x-signature.

    Formato do header: ts=<timestamp>,v1=<hmac_sha256(ts + "." + data_id, secret)>

    Retorna True se a assinatura for válida (ou se MERCADOPAGO_WEBHOOK_SECRET não estiver
    configurado, para compatibilidade com modo desenvolvimento).
    """
    secret = current_app.config.get('MERCADOPAGO_WEBHOOK_SECRET', '')
    if not secret:
        return True  # modo dev: aceitar tudo

    sig_header = request.headers.get('x-signature', '')
    if not sig_header:
        return False

    # Extrair ts e v1 do header
    ts = None
    v1 = None
    for part in sig_header.split(','):
        part = part.strip()
        if part.startswith('ts='):
            ts = part[3:]
        elif part.startswith('v1='):
            v1 = part[3:]

    if not ts or not v1:
        return False

    # data.id vem de query string ou corpo JSON
    data = request.get_json(silent=True) or {}
    data_id = (
        request.args.get('data.id')
        or request.args.get('id')
        or (data.get('data') or {}).get('id')
        or ''
    )

    # Payload assinado: ts + "." + data_id
    manifest = f'{ts}.{data_id}'
    expected = hmac.new(
        secret.encode('utf-8'),
        manifest.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, v1)


def criar_preferencia(pedido, itens):
    """
    Cria preferência de pagamento no Mercado Pago.

    Args:
        pedido: Instância de Order
        itens: Lista de CartItem

    Returns:
        tuple: (preference_id, init_point)

    Raises:
        Exception: Se houver erro na criação da preferência
    """
    sdk = _get_sdk()

    # Preparar items para o MP
    mp_items = []
    for item in itens:
        # Título limitado a 255 caracteres (limite do MP)
        titulo = item.product.nome[:255]

        # Descrição com informação de tamanho
        descricao = ''
        if item.variant and item.variant.tamanho:
            descricao = f'Tamanho: {item.variant.tamanho}'

        mp_items.append({
            'id': str(item.product_id),
            'title': titulo,
            'description': descricao or 'Camisa FERRATO',
            'quantity': item.quantidade,
            'unit_price': float(item.product.preco_final),
            'currency_id': 'BRL'
        })

    # Preparar dados do comprador
    # Extrair código de área do telefone (primeiros 2 dígitos)
    telefone = pedido.telefone or ''
    telefone_limpo = ''.join(filter(str.isdigit, telefone))
    area_code = telefone_limpo[:2] if len(telefone_limpo) >= 2 else '00'
    number = telefone_limpo[2:] if len(telefone_limpo) > 2 else telefone_limpo

    payer = {
        'name': pedido.nome,
        'email': pedido.email,
    }

    # Adicionar telefone se disponível
    if telefone_limpo:
        payer['phone'] = {
            'area_code': area_code,
            'number': number
        }

    # Adicionar endereço
    payer['address'] = {
        'street_name': pedido.endereco,
        'street_number': pedido.numero,
        'zip_code': pedido.cep.replace('-', '')
    }

    # Construir back_urls usando APP_BASE_URL se configurado, senão url_for
    base_url = current_app.config.get('APP_BASE_URL', '').rstrip('/')
    if base_url:
        confirmacao_url = f'{base_url}/cart/confirmacao/{pedido.id}'
    else:
        confirmacao_url = url_for('cart.confirmacao', order_id=pedido.id, _external=True)

    back_urls = {
        'success': confirmacao_url,
        'pending': confirmacao_url,
        'failure': confirmacao_url,
    }

    # auto_return exige URL pública — omitir em desenvolvimento (localhost)
    is_localhost = 'localhost' in confirmacao_url or '127.0.0.1' in confirmacao_url

    # Preparar dados da preferência
    preference_data = {
        'items': mp_items,
        'payer': payer,
        'external_reference': f'FERRATO-{pedido.id}',
        'statement_descriptor': 'FERRATO',
        'back_urls': back_urls,
    }

    if not is_localhost:
        preference_data['auto_return'] = 'approved'

    # Webhook: só quando há URL pública configurada (não localhost)
    if base_url and not is_localhost:
        preference_data['notification_url'] = f'{base_url}/cart/webhook/mercadopago'

    # Criar preferência no MP
    current_app.logger.info("[MP] Criando preferência para pedido %s", pedido.id)
    resultado = sdk.preference().create(preference_data)

    if resultado['status'] not in [200, 201]:
        raise Exception(f"Erro ao criar preferência no Mercado Pago: {resultado}")

    response_data = resultado['response']
    preference_id = response_data['id']
    is_sandbox = current_app.config.get('MERCADOPAGO_SANDBOX', False)
    init_point = response_data['sandbox_init_point'] if is_sandbox else response_data['init_point']

    return preference_id, init_point


def calcular_parcelas(preco: float) -> list:
    """
    Consulta a API do Mercado Pago para obter opções de parcelamento.
    Retorna lista de dicts: {parcelas, valor_parcela, total, sem_juros}
    """
    import requests
    token = current_app.config.get('MERCADOPAGO_ACCESS_TOKEN', '')
    if not token:
        return []

    try:
        resp = requests.get(
            'https://api.mercadopago.com/v1/payment_methods/installments',
            params={
                'payment_method_id': 'master',
                'amount': str(round(preco, 2)),
                'bin': '503143',  # BIN Mastercard representativo
            },
            headers={'Authorization': f'Bearer {token}'},
            timeout=5
        )
        if resp.status_code != 200:
            return []

        data = resp.json()
        if not data:
            return []

        payer_costs = data[0].get('payer_costs', [])
        parcelas = []
        for pc in payer_costs:
            n = pc.get('installments', 1)
            valor = pc.get('installment_amount', preco)
            total = pc.get('total_amount', preco)
            sem_juros = pc.get('installment_rate', 0) == 0
            parcelas.append({
                'parcelas': n,
                'valor_parcela': round(valor, 2),
                'total': round(total, 2),
                'sem_juros': sem_juros,
            })
        return parcelas

    except Exception as e:
        current_app.logger.warning(f'[MP] Erro ao calcular parcelas: {e}')
        return []


def consultar_pagamento_por_id(payment_id):
    """Busca pagamento direto pelo ID. Retorna status e order_id."""
    sdk = _get_sdk()
    result = sdk.payment().get(payment_id)
    if result['status'] != 200:
        return None
    payment = result['response']
    external_ref = payment.get('external_reference', '')  # 'FERRATO-{order_id}'
    order_id = None
    if external_ref.startswith('FERRATO-'):
        try:
            order_id = int(external_ref.split('-')[1])
        except (IndexError, ValueError):
            pass
    status_map = {
        'approved': 'approved', 'pending': 'pending', 'in_process': 'pending',
        'rejected': 'rejected', 'cancelled': 'cancelled',
        'refunded': 'cancelled', 'charged_back': 'cancelled',
    }
    return {
        'status': status_map.get(payment.get('status', ''), 'pending'),
        'payment_id': str(payment.get('id')),
        'order_id': order_id,
    }


def consultar_pagamento(preference_id):
    """
    Consulta status do pagamento via preference_id.

    Args:
        preference_id: ID da preferência do Mercado Pago

    Returns:
        dict: {
            'status': 'approved'|'pending'|'rejected'|'cancelled'|'not_found',
            'payment_id': str ou None,
            'total': float ou None
        }
    """
    sdk = _get_sdk()

    try:
        # Buscar preference para obter external_reference
        preference_result = sdk.preference().get(preference_id)

        if preference_result['status'] != 200:
            return {
                'status': 'not_found',
                'payment_id': None,
                'total': None
            }

        external_reference = preference_result['response'].get('external_reference')

        if not external_reference:
            return {
                'status': 'not_found',
                'payment_id': None,
                'total': None
            }

        # Buscar pagamentos pela external_reference
        filters = {
            'external_reference': external_reference
        }

        payment_result = sdk.payment().search(filters=filters)

        if payment_result['status'] != 200:
            return {
                'status': 'pending',
                'payment_id': None,
                'total': None
            }

        results = payment_result['response'].get('results', [])

        if not results:
            # Sem pagamentos ainda = aguardando
            return {
                'status': 'pending',
                'payment_id': None,
                'total': None
            }

        # Pegar o primeiro resultado (mais recente)
        payment = results[0]

        status_map = {
            'approved': 'approved',
            'pending': 'pending',
            'in_process': 'pending',
            'rejected': 'rejected',
            'cancelled': 'cancelled',
            'refunded': 'cancelled',
            'charged_back': 'cancelled',
        }

        mp_status = payment.get('status', 'pending')
        status = status_map.get(mp_status, 'pending')

        return {
            'status': status,
            'payment_id': str(payment.get('id')),
            'total': float(payment.get('transaction_amount', 0))
        }

    except Exception as e:
        current_app.logger.error(f'Erro ao consultar pagamento MP: {e}')
        return {
            'status': 'pending',
            'payment_id': None,
            'total': None
        }
