"""Serviço de emails de encomenda (aviso de estoque) da loja."""

import logging

from flask import current_app, render_template
from flask_mail import Message

from app import mail

logger = logging.getLogger(__name__)


def _enviar(assunto, destinatario, template_base, **contexto):
    """Envia email HTML+TXT em background thread. Loga em dev, envia em produção."""
    if current_app.config.get('MAIL_SUPPRESS_SEND'):
        logger.info(
            "EMAIL ENCOMENDA [DEV]: assunto='%s' destinatário='%s'",
            assunto,
            destinatario,
        )
        return True

    import threading
    app = current_app._get_current_object()
    html_body = render_template(f'{template_base}.html', **contexto)
    txt_body = render_template(f'{template_base}.txt', **contexto)

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
                logger.info("EMAIL ENCOMENDA: '%s' enviado para '%s'", assunto, destinatario)
            except Exception as e:
                logger.error("EMAIL ENCOMENDA: erro ao enviar '%s' para '%s' — %s", assunto, destinatario, e)

    threading.Thread(target=_send, daemon=True).start()
    return True


def enviar_email_encomenda_confirmada(user, produto, tamanho=None):
    """Envia email confirmando o registro do aviso de estoque."""
    return _enviar(
        assunto=f'Aviso registrado — {produto.nome} | FERRATO',
        destinatario=user.email,
        template_base='email/encomenda_confirmada',
        user=user,
        produto=produto,
        tamanho=tamanho,
    )


def enviar_emails_produto_disponivel(produto, solicitacoes):
    """Envia email de disponibilidade para todos que solicitaram e marca como notificado."""
    from datetime import datetime, timezone
    from app import db

    for s in solicitacoes:
        _enviar(
            assunto=f'{produto.nome} está disponível — FERRATO',
            destinatario=s.user.email,
            template_base='email/produto_disponivel',
            user=s.user,
            produto=produto,
        )
        s.notificado = True
        s.notificado_em = datetime.now(timezone.utc)
    db.session.commit()
