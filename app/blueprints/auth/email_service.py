"""Serviço de envio e validação de emails de verificação."""

import secrets
from datetime import datetime, timedelta, timezone

from flask import current_app, render_template
from flask_mail import Message
from werkzeug.security import generate_password_hash

from app import db, mail
from app.models import EmailVerificationToken, PasswordResetToken


def gerar_codigo_verificacao():
    """Gera um código de verificação de 6 dígitos criptograficamente seguro."""
    return ''.join([str(secrets.randbelow(10)) for _ in range(6)])


def limpar_tokens_expirados():
    """Remove tokens expirados e não verificados do banco de dados."""
    agora = datetime.now(timezone.utc)
    EmailVerificationToken.query.filter(
        EmailVerificationToken.expira_em < agora,
        EmailVerificationToken.verificado == False
    ).delete()
    db.session.commit()


def criar_token_verificacao(email, nome, senha):
    """
    Cria um novo token de verificação de email.

    Remove automaticamente tokens antigos do mesmo email.

    Args:
        email: Email do usuário
        nome: Nome completo do usuário
        senha: Senha em texto plano (será hasheada)

    Returns:
        EmailVerificationToken: Token criado
    """
    # Limpar tokens antigos deste email (não verificados)
    EmailVerificationToken.query.filter_by(
        email=email.lower(),
        verificado=False
    ).delete()

    # Limpar tokens muito antigos de forma geral
    limpar_tokens_expirados()

    # Gerar código
    codigo = gerar_codigo_verificacao()

    # Calcular expiração
    expiry_minutes = current_app.config.get('EMAIL_VERIFICATION_EXPIRY_MINUTES', 10)
    expira_em = datetime.now(timezone.utc) + timedelta(minutes=expiry_minutes)

    # Criar token
    token = EmailVerificationToken(
        email=email.lower(),
        codigo=codigo,
        nome=nome,
        senha_hash=generate_password_hash(senha),
        expira_em=expira_em
    )

    db.session.add(token)
    db.session.commit()

    return token


def enviar_email_verificacao(email, codigo):
    """
    Envia email com código de verificação.

    Em modo desenvolvimento (TESTING=True), apenas loga o código no console.

    Args:
        email: Email destino
        codigo: Código de 6 dígitos

    Returns:
        bool: True se enviado com sucesso, False caso contrário
    """
    if current_app.config.get('TESTING'):
        current_app.logger.warning(
            f'[MODO DEV] Código de verificação para {email}: {codigo}'
        )
        return True

    import threading
    app = current_app._get_current_object()
    html_body = render_template('auth/email_verificacao.html', codigo=codigo)
    txt_body = render_template('auth/email_verificacao.txt', codigo=codigo)

    def _send():
        with app.app_context():
            try:
                msg = Message(
                    subject='Verifique seu email - FERRATO',
                    recipients=[email],
                    sender=app.config.get('MAIL_DEFAULT_SENDER')
                )
                msg.html = html_body
                msg.body = txt_body
                mail.send(msg)
                app.logger.info(f'Email de verificação enviado para {email}')
            except Exception as e:
                app.logger.error(f'Erro ao enviar email para {email}: {str(e)}')

    threading.Thread(target=_send, daemon=True).start()
    return True


def criar_token_reset_senha(email):
    """
    Cria (ou substitui) um token de redefinição de senha para o email.

    Returns:
        str: O token gerado
    """
    # Invalidar tokens anteriores deste email
    PasswordResetToken.query.filter_by(email=email.lower(), usado=False).delete()
    db.session.flush()

    token_str = secrets.token_urlsafe(32)
    expiry_minutes = current_app.config.get('PASSWORD_RESET_EXPIRY_MINUTES', 30)
    expira_em = datetime.now(timezone.utc) + timedelta(minutes=expiry_minutes)

    reset_token = PasswordResetToken(
        email=email.lower(),
        token=token_str,
        expira_em=expira_em,
    )
    db.session.add(reset_token)
    db.session.commit()

    return token_str


def enviar_email_reset_senha(email, nome, token):
    """
    Envia email com link de redefinição de senha em background thread.

    Returns:
        bool: True (imediato — envio ocorre em background)
    """
    import threading
    from flask import url_for
    link = url_for('auth.redefinir_senha', token=token, _external=True)

    if current_app.config.get('TESTING'):
        current_app.logger.warning(
            f'[MODO DEV] Link de reset de senha para {email}: {link}'
        )
        return True

    # Capturar referência real ao app e renderizar templates antes de lançar a thread
    # (proxies Flask não funcionam fora do request context)
    app = current_app._get_current_object()
    html_body = render_template('auth/email_reset_senha.html', nome=nome, link=link)
    txt_body = render_template('auth/email_reset_senha.txt', nome=nome, link=link)

    def _send():
        with app.app_context():
            try:
                msg = Message(
                    subject='Redefinição de senha - FERRATO',
                    recipients=[email],
                    sender=app.config.get('MAIL_DEFAULT_SENDER'),
                )
                msg.html = html_body
                msg.body = txt_body
                mail.send(msg)
                app.logger.info(f'Email de reset de senha enviado para {email}')
            except Exception as e:
                app.logger.error(f'Erro ao enviar email de reset para {email}: {e}')

    threading.Thread(target=_send, daemon=True).start()
    return True


def enviar_cupom_usuarios(cupom, usuarios):
    """
    Envia email com cupom de desconto para uma lista de usuários.

    Em modo desenvolvimento (TESTING=True), apenas loga no console.

    Args:
        cupom: instância de Cupom
        usuarios: lista de User
    """
    import threading

    if current_app.config.get('TESTING'):
        for u in usuarios:
            current_app.logger.warning(
                f'[MODO DEV] Cupom {cupom.codigo} ({cupom.desconto_percentual:.0f}%) → {u.email}'
            )
        return

    app = current_app._get_current_object()
    cupom_codigo = cupom.codigo
    cupom_pct = cupom.desconto_percentual
    cupom_validade = cupom.validade

    destinatarios = [(u.nome, u.email) for u in usuarios]

    def _send():
        with app.app_context():
            for nome, email in destinatarios:
                try:
                    html_body = render_template(
                        'auth/email_cupom.html',
                        nome=nome,
                        codigo=cupom_codigo,
                        desconto_percentual=cupom_pct,
                        validade=cupom_validade,
                    )
                    txt_body = render_template(
                        'auth/email_cupom.txt',
                        nome=nome,
                        codigo=cupom_codigo,
                        desconto_percentual=cupom_pct,
                        validade=cupom_validade,
                    )
                    msg = Message(
                        subject=f'Seu cupom exclusivo FERRATO: {cupom_codigo}',
                        recipients=[email],
                        sender=app.config.get('MAIL_DEFAULT_SENDER'),
                    )
                    msg.html = html_body
                    msg.body = txt_body
                    mail.send(msg)
                    app.logger.info(f'Email de cupom enviado para {email}')
                except Exception as e:
                    app.logger.error(f'Erro ao enviar cupom para {email}: {e}')

    threading.Thread(target=_send, daemon=True).start()


def verificar_codigo(email, codigo):
    """
    Verifica se o código informado é válido para o email.

    Valida:
    - Se existe token para o email
    - Se o código está correto
    - Se não expirou
    - Se não excedeu tentativas
    - Se não foi já verificado

    Args:
        email: Email do usuário
        codigo: Código de 6 dígitos informado

    Returns:
        tuple: (sucesso: bool, mensagem: str, token: EmailVerificationToken ou None)
    """
    # Buscar token ativo
    token = EmailVerificationToken.query.filter_by(
        email=email.lower(),
        verificado=False
    ).order_by(EmailVerificationToken.criado_em.desc()).first()

    if not token:
        return False, 'Código de verificação não encontrado. Solicite um novo código.', None

    # Verificar expiração
    agora = datetime.now(timezone.utc)
    expira_em = token.expira_em.replace(tzinfo=timezone.utc) if token.expira_em.tzinfo is None else token.expira_em
    if agora > expira_em:
        return False, 'Código expirado. Solicite um novo código.', None

    # Verificar tentativas
    max_tentativas = current_app.config.get('EMAIL_VERIFICATION_MAX_ATTEMPTS', 5)
    if token.tentativas >= max_tentativas:
        return False, f'Número máximo de tentativas excedido ({max_tentativas}). Solicite um novo código.', None

    # Verificar código
    if token.codigo != codigo:
        token.tentativas += 1
        db.session.commit()
        tentativas_restantes = max_tentativas - token.tentativas
        return False, f'Código incorreto. {tentativas_restantes} tentativa(s) restante(s).', None

    # Código correto - marcar como verificado
    token.verificado = True
    db.session.commit()

    return True, 'Código verificado com sucesso!', token
