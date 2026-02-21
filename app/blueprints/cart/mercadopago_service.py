"""Serviço de integração com Mercado Pago."""

import json
import mercadopago
from flask import current_app, url_for


def _get_sdk():
    """Retorna instância configurada do SDK Mercado Pago."""
    token = current_app.config.get('MERCADOPAGO_ACCESS_TOKEN')
    if not token:
        raise ValueError('MERCADOPAGO_ACCESS_TOKEN não configurado')
    return mercadopago.SDK(token)


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

    # Criar preferência no MP
    current_app.logger.warning(f"[MP DIAGNÓSTICO] preference_data enviado:\n{json.dumps(preference_data, indent=2, ensure_ascii=False)}")
    resultado = sdk.preference().create(preference_data)
    current_app.logger.warning(f"[MP DIAGNÓSTICO] resultado completo:\n{json.dumps(resultado, indent=2, ensure_ascii=False)}")

    if resultado['status'] not in [200, 201]:
        raise Exception(f"Erro ao criar preferência no Mercado Pago: {resultado}")

    response_data = resultado['response']
    preference_id = response_data['id']
    init_point = response_data['init_point']

    return preference_id, init_point


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
