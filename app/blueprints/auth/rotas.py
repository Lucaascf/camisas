"""Rotas de autenticação."""

from urllib.parse import urlparse

from flask import render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, current_user

from app import db, limiter
from app.blueprints.auth import auth_bp
from app.forms import LoginForm, RegistroForm, RegistroEmailForm, VerificarEmailForm, EsqueceuSenhaForm, RedefinirSenhaForm
from app.models import User, CartItem


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    """Página de login."""
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()

        if user and user.check_senha(form.senha.data):
            login_user(user, remember=form.lembrar.data)

            # Merge do carrinho anônimo para o usuário autenticado
            merge_anonymous_cart_to_user(user.id)

            flash('Login realizado com sucesso!', 'success')
            next_page = request.args.get('next')
            if next_page:
                parsed = urlparse(next_page)
                if parsed.scheme or parsed.netloc:
                    next_page = None
            return redirect(next_page or url_for('main.home'))
        else:
            flash('Email ou senha incorretos.', 'error')

    return render_template('auth/login.html', form=form)


@auth_bp.route('/registro', methods=['GET', 'POST'])
def registro():
    """Página de registro - Etapa 1: Nome, Email e Senha."""
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))

    from app.blueprints.auth.email_service import criar_token_verificacao, enviar_email_verificacao
    from werkzeug.security import generate_password_hash

    form = RegistroEmailForm()
    if form.validate_on_submit():
        email = form.email.data.lower()
        nome = form.nome.data
        senha = form.senha.data

        # Criar token de verificação
        token = criar_token_verificacao(email, nome, senha)

        # Enviar email
        email_enviado = enviar_email_verificacao(email, token.codigo)

        if email_enviado:
            # Armazenar dados na sessão para etapa 2 e reenvio
            session['email_pendente'] = email
            session['nome_pendente'] = nome
            session['senha_hash_pendente'] = generate_password_hash(senha)

            flash(
                f'Código de verificação enviado para {email}. '
                'Verifique sua caixa de entrada (e spam).',
                'success'
            )
            return redirect(url_for('auth.verificar_email'))
        else:
            flash(
                'Erro ao enviar email de verificação. Tente novamente mais tarde.',
                'error'
            )

    return render_template('auth/registro_step1.html', form=form)


@auth_bp.route('/verificar-email', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def verificar_email():
    """Página de registro - Etapa 2: Verificar Código."""
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))

    # Verificar se há dados pendentes na sessão
    email = session.get('email_pendente')
    nome = session.get('nome_pendente')
    senha_hash = session.get('senha_hash_pendente')

    if not all([email, nome, senha_hash]):
        flash('Sessão expirada. Por favor, inicie o registro novamente.', 'error')
        return redirect(url_for('auth.registro'))

    from app.blueprints.auth.email_service import verificar_codigo

    form = VerificarEmailForm()
    if form.validate_on_submit():
        codigo = form.codigo.data

        sucesso, mensagem, token = verificar_codigo(email, codigo)

        if sucesso:
            # Criar usuário com dados da sessão
            user = User(
                nome=nome,
                email=email
            )
            user.senha_hash = senha_hash  # Usar hash armazenado na sessão

            db.session.add(user)
            db.session.commit()

            # Fazer login automático
            login_user(user)

            # Merge do carrinho anônimo para o usuário autenticado
            merge_anonymous_cart_to_user(user.id)

            # Limpar sessão
            session.pop('email_pendente', None)
            session.pop('nome_pendente', None)
            session.pop('senha_hash_pendente', None)

            flash('Conta criada com sucesso! Você já está logado.', 'success')
            return redirect(url_for('main.home'))
        else:
            flash(mensagem, 'error')

    return render_template('auth/registro_step2.html', form=form, email=email)


@auth_bp.route('/reenviar-codigo', methods=['POST'])
@limiter.limit("3 per 10 minutes")
def reenviar_codigo():
    """Reenvia código de verificação."""
    from app.blueprints.auth.email_service import criar_token_verificacao, enviar_email_verificacao
    from werkzeug.security import generate_password_hash

    email = session.get('email_pendente')
    nome = session.get('nome_pendente')
    senha_hash = session.get('senha_hash_pendente')

    if not all([email, nome, senha_hash]):
        flash('Sessão expirada. Por favor, inicie o registro novamente.', 'error')
        return redirect(url_for('auth.registro'))

    # Criar novo token (remove o anterior automaticamente)
    # Nota: usar senha_hash já existente, não precisamos da senha original
    token = criar_token_verificacao(email, nome, 'dummy')  # Senha dummy
    token.senha_hash = senha_hash  # Sobrescrever com hash correto da sessão
    db.session.commit()

    # Enviar novo código
    email_enviado = enviar_email_verificacao(email, token.codigo)

    if email_enviado:
        flash('Novo código enviado! Verifique seu email.', 'success')
    else:
        flash('Erro ao reenviar código. Tente novamente.', 'error')

    return redirect(url_for('auth.verificar_email'))


@auth_bp.route('/logout')
def logout():
    """Faz logout do usuário."""
    logout_user()
    flash('Você saiu da sua conta.', 'info')
    return redirect(url_for('main.home'))


@auth_bp.route('/esqueci-senha', methods=['GET', 'POST'])
@limiter.limit("5 per 10 minutes")
def esqueci_senha():
    """Solicitar redefinição de senha."""
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))

    from app.blueprints.auth.email_service import enviar_email_reset_senha, criar_token_reset_senha

    form = EsqueceuSenhaForm()
    if form.validate_on_submit():
        email = form.email.data.lower()
        user = User.query.filter_by(email=email).first()

        # Sempre mostrar a mesma mensagem para não revelar se o email existe
        flash(
            'Se este email estiver cadastrado, você receberá as instruções de redefinição em instantes.',
            'success'
        )

        if user:
            token = criar_token_reset_senha(user.email)
            enviar_email_reset_senha(user.email, user.nome, token)

        return redirect(url_for('auth.login'))

    return render_template('auth/esqueci_senha.html', form=form)


@auth_bp.route('/redefinir-senha/<token>', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def redefinir_senha(token):
    """Redefinir senha com token válido."""
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))

    from app.models import PasswordResetToken
    from datetime import datetime, timezone

    reset_token = PasswordResetToken.query.filter_by(token=token, usado=False).first()

    agora = datetime.now(timezone.utc)
    if not reset_token:
        flash('Link de redefinição inválido ou já utilizado.', 'error')
        return redirect(url_for('auth.esqueci_senha'))

    expira_em = reset_token.expira_em
    if expira_em.tzinfo is None:
        expira_em = expira_em.replace(tzinfo=timezone.utc)
    if agora > expira_em:
        flash('Link de redefinição expirado. Solicite um novo.', 'error')
        return redirect(url_for('auth.esqueci_senha'))

    form = RedefinirSenhaForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=reset_token.email).first()
        if user:
            user.set_senha(form.senha.data)
            reset_token.usado = True
            db.session.commit()
            flash('Senha redefinida com sucesso! Faça login com sua nova senha.', 'success')
            return redirect(url_for('auth.login'))
        else:
            flash('Usuário não encontrado.', 'error')
            return redirect(url_for('auth.esqueci_senha'))

    return render_template('auth/redefinir_senha.html', form=form, token=token)


def merge_anonymous_cart_to_user(user_id):
    """
    Transfere itens do carrinho anônimo para o carrinho do usuário autenticado.

    Args:
        user_id: ID do usuário autenticado
    """
    cart_session_id = session.get('cart_session_id')

    if not cart_session_id:
        return

    # Buscar itens anônimos
    anonymous_items = CartItem.query.filter_by(session_id=cart_session_id).all()

    for anon_item in anonymous_items:
        # Verificar se o usuário já tem este produto no carrinho
        existing_item = CartItem.query.filter_by(
            user_id=user_id,
            product_id=anon_item.product_id
        ).first()

        if existing_item:
            # Somar as quantidades
            existing_item.quantidade += anon_item.quantidade
            db.session.delete(anon_item)
        else:
            # Transferir o item para o usuário
            anon_item.user_id = user_id
            anon_item.session_id = None

    db.session.commit()

    # Limpar o session_id do carrinho
    session.pop('cart_session_id', None)
