"""Serviços de integração com Mercado Pago."""

import mercadopago
from flask import current_app, url_for
from app import db
from app.models import Order


def obter_sdk_mp():
    """
    Retorna instância configurada do SDK do Mercado Pago.

    Returns:
        mercadopago.SDK: Instância do SDK configurada
    """
    access_token = current_app.config['MP_ACCESS_TOKEN']

    if not access_token:
        raise ValueError('MP_ACCESS_TOKEN não configurado')

    sdk = mercadopago.SDK(access_token)
    return sdk


def criar_preferencia_pagamento(pedido):
    """
    Cria uma preferência de pagamento no Mercado Pago para o pedido.

    Args:
        pedido: Instância do modelo Order

    Returns:
        str: URL (init_point) para redirecionar o cliente

    Raises:
        Exception: Se houver erro ao criar a preferência
    """
    try:
        sdk = obter_sdk_mp()
        base_url = current_app.config['BASE_URL']

        # Preparar items da preferência
        items = []
        for item in pedido.items:
            descricao = item.product.nome
            if item.tamanho:
                descricao += f' - Tamanho {item.tamanho}'

            items.append({
                'title': descricao,
                'quantity': item.quantidade,
                'unit_price': float(item.preco_unitario),
                'currency_id': 'BRL'
            })

        # Preparar dados do comprador (payer)
        payer = {
            'name': pedido.nome,
            'email': pedido.email,
        }

        if pedido.telefone:
            payer['phone'] = {
                'number': pedido.telefone
            }

        # URLs de retorno
        back_urls = {
            'success': f"{base_url}{url_for('payments.sucesso', order_id=pedido.id, _external=False)}",
            'failure': f"{base_url}{url_for('payments.falha', order_id=pedido.id, _external=False)}",
            'pending': f"{base_url}{url_for('payments.pendente', order_id=pedido.id, _external=False)}"
        }

        # URL de notificação (webhook)
        notification_url = f"{base_url}{url_for('payments.webhook', _external=False)}"

        # Dados da preferência
        preference_data = {
            'items': items,
            'payer': payer,
            'back_urls': back_urls,
            'auto_return': 'approved',  # Redireciona automaticamente quando aprovado
            'notification_url': notification_url,
            'external_reference': str(pedido.id),  # Referência ao nosso pedido
            'statement_descriptor': 'FERRATO',  # Nome que aparece na fatura do cartão
        }

        # Criar preferência no MP
        response = sdk.preference().create(preference_data)

        if response['status'] != 201:
            raise Exception(f"Erro ao criar preferência: {response}")

        # Salvar preference_id no pedido
        preference_id = response['response']['id']
        init_point = response['response']['init_point']

        pedido.mp_preference_id = preference_id
        db.session.commit()

        current_app.logger.info(f'Preferência criada: {preference_id} para pedido #{pedido.id}')

        return init_point

    except Exception as e:
        current_app.logger.error(f'Erro ao criar preferência de pagamento: {str(e)}')
        raise


def processar_webhook(data_id, topic):
    """
    Processa notificação do webhook do Mercado Pago.

    Args:
        data_id: ID do recurso notificado (payment_id, merchant_order_id, etc)
        topic: Tipo de notificação (payment, merchant_order, etc)

    Returns:
        bool: True se processado com sucesso, False caso contrário
    """
    try:
        # Só processar notificações de payment
        if topic != 'payment':
            current_app.logger.info(f'Ignorando webhook topic={topic}')
            return True

        sdk = obter_sdk_mp()

        # Buscar informações do pagamento
        payment_info = sdk.payment().get(data_id)

        if payment_info['status'] != 200:
            current_app.logger.error(f'Erro ao buscar payment {data_id}: {payment_info}')
            return False

        payment = payment_info['response']

        # Obter external_reference (ID do nosso pedido)
        external_reference = payment.get('external_reference')
        if not external_reference:
            current_app.logger.warning(f'Payment {data_id} sem external_reference')
            return False

        # Buscar pedido no banco
        pedido = Order.query.get(int(external_reference))
        if not pedido:
            current_app.logger.error(f'Pedido #{external_reference} não encontrado')
            return False

        # Atualizar dados do pedido
        pedido.mp_payment_id = str(data_id)
        pedido.mp_status = payment.get('status')

        # Mapear status do MP para status do nosso pedido
        mp_status = payment.get('status')

        if mp_status == 'approved':
            pedido.status = 'pago'
            current_app.logger.info(f'Pedido #{pedido.id} marcado como PAGO')

        elif mp_status in ['rejected', 'cancelled']:
            pedido.status = 'cancelado'
            current_app.logger.info(f'Pedido #{pedido.id} marcado como CANCELADO')

        elif mp_status in ['in_process', 'in_mediation', 'pending']:
            pedido.status = 'pendente'
            current_app.logger.info(f'Pedido #{pedido.id} marcado como PENDENTE')

        else:
            current_app.logger.warning(f'Status desconhecido do MP: {mp_status}')

        db.session.commit()

        current_app.logger.info(
            f'Webhook processado: payment={data_id}, pedido=#{pedido.id}, '
            f'mp_status={mp_status}, novo_status={pedido.status}'
        )

        return True

    except Exception as e:
        current_app.logger.error(f'Erro ao processar webhook: {str(e)}')
        db.session.rollback()
        return False
