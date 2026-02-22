"""Serviço de emails de acompanhamento de pedidos."""

import logging

from flask import current_app, render_template
from flask_mail import Message

from app import mail

logger = logging.getLogger(__name__)


def _enviar(assunto, destinatario, template_base, **contexto):
    """Envia email HTML+TXT em background thread. Loga em dev, envia em produção."""
    if current_app.config.get('MAIL_SUPPRESS_SEND'):
        logger.info(
            "EMAIL PEDIDO [DEV]: assunto='%s' destinatário='%s' contexto=%s",
            assunto,
            destinatario,
            {k: v for k, v in contexto.items() if k != 'pedido'},
        )
        return True

    import threading
    app = current_app._get_current_object()
    html_body = render_template(f'email/{template_base}.html', **contexto)
    txt_body = render_template(f'email/{template_base}.txt', **contexto)

    def _send():
        with app.app_context():
            try:
                msg = Message(
                    subject=assunto,
                    recipients=[destinatario],
                    sender=app.config.get('MAIL_DEFAULT_SENDER'),
                )
                msg.html = html_body
                msg.body = txt_body
                mail.send(msg)
                logger.info("EMAIL PEDIDO: '%s' enviado para '%s'", assunto, destinatario)
            except Exception as e:
                logger.error("EMAIL PEDIDO: erro ao enviar '%s' para '%s' — %s", assunto, destinatario, e)

    threading.Thread(target=_send, daemon=True).start()
    return True


def enviar_email_pedido_confirmado(pedido):
    """Envia email de confirmação de pagamento ao cliente."""
    return _enviar(
        assunto=f'Pedido #{pedido.codigo_cliente} confirmado — FERRATO',
        destinatario=pedido.email,
        template_base='pedido_confirmado',
        pedido=pedido,
    )


def enviar_email_pedido_enviado(pedido):
    """Envia email de notificação de envio com código de rastreio ao cliente."""
    return _enviar(
        assunto=f'Seu pedido #{pedido.codigo_cliente} foi enviado — FERRATO',
        destinatario=pedido.email,
        template_base='pedido_enviado',
        pedido=pedido,
    )
