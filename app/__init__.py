"""Fábrica da aplicação FERRATO."""

from dotenv import load_dotenv
load_dotenv()  # DEVE ser chamado ANTES de importar config

from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, flash, has_request_context, redirect, render_template, request, session, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager, current_user
from flask_mail import Mail
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

from app.config import ConfigDesenvolvimento

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Faça login para acessar esta página.'
csrf = CSRFProtect()
mail = Mail()
limiter = Limiter(key_func=get_remote_address, default_limits=[], storage_uri="memory://")


def criar_app(config_class=ConfigDesenvolvimento):
    """Cria e configura a aplicação Flask."""

    app = Flask(__name__)
    app.config.from_object(config_class)

    # --- Inicializar extensões ---
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    mail.init_app(app)
    limiter.init_app(app)

    # --- Importar models e criar tabelas ---
    from app import models  # noqa: F401

    with app.app_context():
        db.create_all()
        from sqlalchemy import text
        try:
            db.session.execute(text("ALTER TABLE product ADD COLUMN marca_id INTEGER REFERENCES marca(id)"))
            db.session.commit()
        except Exception:
            db.session.rollback()
        try:
            db.session.execute(text("ALTER TABLE product ADD COLUMN tecido_id INTEGER REFERENCES tecido(id)"))
            db.session.commit()
        except Exception:
            db.session.rollback()

    # --- User loader para Flask-Login ---
    @login_manager.user_loader
    def load_user(user_id):
        return models.User.query.get(int(user_id))

    # --- Registrar Blueprints ---
    from app.blueprints.main import main_bp
    app.register_blueprint(main_bp)

    from app.blueprints.shop import shop_bp
    app.register_blueprint(shop_bp)

    from app.blueprints.cart import cart_bp
    app.register_blueprint(cart_bp)

    from app.blueprints.auth import auth_bp
    app.register_blueprint(auth_bp)

    from app.blueprints.admin import admin_bp
    app.register_blueprint(admin_bp)

    # --- Comandos CLI ---
    from app.seed import register_commands
    register_commands(app)

    # --- Filtros Jinja2 ---
    def hora_brasilia(dt, fmt='%d/%m/%Y %H:%M'):
        """Converte datetime UTC para horário de Brasília e formata."""
        if dt is None:
            return ''
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo('UTC'))
        return dt.astimezone(ZoneInfo('America/Sao_Paulo')).strftime(fmt)

    app.jinja_env.filters['hora_brasilia'] = hora_brasilia

    # --- Context Processors ---
    @app.context_processor
    def variaveis_globais():
        """Injeta variáveis disponíveis em todos os templates."""
        from app.models import Category, CartItem

        # Contagem de itens no carrinho
        cart_count = 0
        if has_request_context() and current_user.is_authenticated:
            cart_count = db.session.query(
                db.func.coalesce(db.func.sum(CartItem.quantidade), 0)
            ).filter_by(user_id=current_user.id).scalar()
        elif has_request_context() and 'cart_session_id' in session:
            cart_count = db.session.query(
                db.func.coalesce(db.func.sum(CartItem.quantidade), 0)
            ).filter_by(session_id=session['cart_session_id']).scalar()

        from app.models import ConfigFrete
        return {
            'ano_atual':          datetime.now().year,
            'nav_categories':     Category.query.all(),
            'cart_item_count':    cart_count,
            'frete_gratis_acima': ConfigFrete.get().fora_gratis_acima,
        }

    # --- Headers de segurança ---
    @app.after_request
    def security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://sdk.mercadopago.com https://*.mercadopago.com https://*.mercadopago.com.br https://*.mlstatic.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://*.mercadopago.com https://*.mercadopago.com.br https://*.mlstatic.com; "
            "font-src 'self' https://fonts.gstatic.com https://*.mercadopago.com https://*.mlstatic.com; "
            "img-src 'self' data: blob: https:; "
            "connect-src 'self' https://api.mercadopago.com https://*.mercadopago.com https://*.mercadopago.com.br https://*.mlstatic.com; "
            "frame-src https://*.mercadopago.com https://*.mercadopago.com.br https://*.mercadolibre.com https://*.mercadolivre.com.br https://*.mlstatic.com; "
            "worker-src blob: 'self'; "
            "child-src blob: https://*.mercadopago.com https://*.mercadopago.com.br https://*.mlstatic.com; "
        )
        return response

    # --- Handlers de erro ---
    @app.errorhandler(404)
    def pagina_nao_encontrada(e):
        return render_template('404.html'), 404

    @app.errorhandler(500)
    def erro_interno(e):
        return render_template('500.html'), 500

    @app.errorhandler(429)
    def muitas_tentativas(e):
        flash('Muitas tentativas. Aguarde um momento.', 'error')
        return redirect(request.referrer or url_for('main.home')), 429

    return app
