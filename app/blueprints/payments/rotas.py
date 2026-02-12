"""Rotas de pagamento - Mercado Pago."""

from flask import render_template, request, jsonify, current_app, abort
from flask_login import current_user
from flask_wtf.csrf import CSRFProtect

from app.blueprints.payments import payments_bp
from app.blueprints.payments.servico import processar_webhook
from app.blueprints.payments.utils import validar_assinatura_webhook
from app.models import Order


@payments_bp.route('/success')
def sucesso():
    """Página de pagamento aprovado."""
    order_id = request.args.get('order_id', type=int)

    if not order_id:
        abort(404)

    pedido = Order.query.get_or_404(order_id)

    # Verificar se o usuário tem permissão para ver este pedido
    if pedido.user_id:
        # Pedido de usuário logado - verificar se é o dono
        if not current_user.is_authenticated or current_user.id != pedido.user_id:
            abort(403)
    # Pedidos de convidados (user_id=None) podem ser acessados por qualquer um com o link

    return render_template('payments/sucesso.html', pedido=pedido)


@payments_bp.route('/pending')
def pendente():
    """Página de pagamento pendente (PIX, boleto)."""
    order_id = request.args.get('order_id', type=int)

    if not order_id:
        abort(404)

    pedido = Order.query.get_or_404(order_id)

    # Verificar permissão
    if pedido.user_id:
        if not current_user.is_authenticated or current_user.id != pedido.user_id:
            abort(403)

    return render_template('payments/pendente.html', pedido=pedido)


@payments_bp.route('/failure')
def falha():
    """Página de pagamento recusado/falhou."""
    order_id = request.args.get('order_id', type=int)

    if not order_id:
        abort(404)

    pedido = Order.query.get_or_404(order_id)

    # Verificar permissão
    if pedido.user_id:
        if not current_user.is_authenticated or current_user.id != pedido.user_id:
            abort(403)

    # Marcar pedido como cancelado se ainda não foi
    if pedido.status == 'aguardando_pagamento':
        from app import db
        pedido.status = 'cancelado'
        db.session.commit()
        current_app.logger.info(f'Pedido #{pedido.id} cancelado após falha de pagamento')

    return render_template('payments/falha.html', pedido=pedido)


@payments_bp.route('/webhook', methods=['POST'])
def webhook():
    """
    Endpoint para receber notificações do Mercado Pago.

    IMPORTANTE: Sem proteção CSRF (webhooks externos).
    Validação feita via HMAC-SHA256.
    """
    try:
        # Validar assinatura HMAC
        if not validar_assinatura_webhook(request):
            current_app.logger.warning('Webhook com assinatura inválida')
            return jsonify({'error': 'Invalid signature'}), 401

        # Obter dados da notificação
        data_id = request.args.get('data.id')
        topic = request.args.get('topic', 'payment')

        if not data_id:
            current_app.logger.warning('Webhook sem data.id')
            return jsonify({'error': 'Missing data.id'}), 400

        current_app.logger.info(f'Webhook recebido: topic={topic}, data_id={data_id}')

        # Processar webhook
        sucesso = processar_webhook(data_id, topic)

        if sucesso:
            return jsonify({'status': 'ok'}), 200
        else:
            return jsonify({'error': 'Processing failed'}), 500

    except Exception as e:
        current_app.logger.error(f'Erro no webhook: {str(e)}')
        return jsonify({'error': 'Internal error'}), 500


# Desabilitar CSRF apenas para o webhook
csrf = CSRFProtect()


@payments_bp.before_request
def desabilitar_csrf_webhook():
    """Desabilita CSRF apenas para a rota de webhook."""
    if request.endpoint == 'payments.webhook':
        # Flask-WTF >= 1.0 usa essa abordagem
        csrf.exempt(webhook)
