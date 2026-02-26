"""Configurações da aplicação."""

import os
from datetime import timedelta


class Config:
    """Configuração base."""
    _secret = os.environ.get('SECRET_KEY')
    if not _secret and os.environ.get('FLASK_ENV') == 'production':
        raise RuntimeError(
            'SECRET_KEY não definida. Configure a variável de ambiente antes de iniciar em produção.'
        )
    SECRET_KEY = _secret or 'chave-secreta-dev-ferrato-2026'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///ferrato.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    DEBUG = False

    # Email Configuration (Flask-Mail)
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'True').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'useferrato@gmail.com')

    # Email verification settings
    EMAIL_VERIFICATION_CODE_LENGTH = 6
    EMAIL_VERIFICATION_EXPIRY_MINUTES = 10
    EMAIL_VERIFICATION_MAX_ATTEMPTS = 5

    # Development mode - log codes instead of sending emails
    MAIL_SUPPRESS_SEND = os.environ.get('FLASK_ENV') == 'development'
    TESTING = os.environ.get('FLASK_ENV') == 'development'

    # Admin access key
    ADMIN_ACCESS_KEY = os.environ.get('ADMIN_ACCESS_KEY', '')

    # Session / cookie security flags
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_SECURE = True
    REMEMBER_COOKIE_HTTPONLY = True

    # Session lifetime
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    SESSION_REFRESH_EACH_REQUEST = True

    # Mercado Pago
    MERCADOPAGO_ACCESS_TOKEN = os.environ.get('MERCADOPAGO_ACCESS_TOKEN')
    MERCADOPAGO_WEBHOOK_SECRET = os.environ.get('MERCADOPAGO_WEBHOOK_SECRET', '')
    MERCADOPAGO_SANDBOX = os.environ.get('MERCADOPAGO_SANDBOX', 'false').lower() == 'true'
    APP_BASE_URL = os.environ.get('APP_BASE_URL', '')


class ConfigDesenvolvimento(Config):
    """Configuração para desenvolvimento."""
    DEBUG = True


class ConfigProducao(Config):
    """Configuração para produção."""
    DEBUG = False


class ConfigTeste(Config):
    """Configuração para testes automatizados."""
    TESTING = True
    WTF_CSRF_ENABLED = False          # Simplifica POST nos testes
    SESSION_COOKIE_SECURE = False     # Test client usa HTTP
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'test-secret-key'
    ADMIN_ACCESS_KEY = 'chave-teste'
    MAIL_SUPPRESS_SEND = True
