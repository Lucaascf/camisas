"""Rotas de autenticação."""

from flask import render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, current_user

from app import db
from app.blueprints.auth import auth_bp
from app.forms import LoginForm, RegistroForm
from app.models import User, CartItem


@auth_bp.route('/login', methods=['GET', 'POST'])
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
            return redirect(next_page) if next_page else redirect(url_for('main.home'))
        else:
            flash('Email ou senha incorretos.', 'error')

    return render_template('auth/login.html', form=form)


@auth_bp.route('/registro', methods=['GET', 'POST'])
def registro():
    """Página de registro de novo usuário."""
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))

    form = RegistroForm()
    if form.validate_on_submit():
        user = User(
            nome=form.nome.data,
            email=form.email.data.lower()
        )
        user.set_senha(form.senha.data)

        db.session.add(user)
        db.session.commit()

        flash('Conta criada com sucesso! Faça login para continuar.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html', form=form)


@auth_bp.route('/logout')
def logout():
    """Faz logout do usuário."""
    logout_user()
    flash('Você saiu da sua conta.', 'info')
    return redirect(url_for('main.home'))


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
