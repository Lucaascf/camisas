"""Configurações da aplicação."""

import os


class Config:
    """Configuração base."""
    SECRET_KEY = os.environ.get('SECRET_KEY', 'chave-secreta-dev-ferrato-2026')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///ferrato.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    DEBUG = False

    # Email Configuration (Flask-Mail)
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'True').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@ferrato.com.br')

    # Email verification settings
    EMAIL_VERIFICATION_CODE_LENGTH = 6
    EMAIL_VERIFICATION_EXPIRY_MINUTES = 10
    EMAIL_VERIFICATION_MAX_ATTEMPTS = 5

    # Development mode - log codes instead of sending emails
    MAIL_SUPPRESS_SEND = os.environ.get('FLASK_ENV') == 'development'
    TESTING = os.environ.get('FLASK_ENV') == 'development'

    # Mercado Pago
    MERCADOPAGO_ACCESS_TOKEN = os.environ.get('MERCADOPAGO_ACCESS_TOKEN')
    MERCADOPAGO_SANDBOX = os.environ.get('MERCADOPAGO_SANDBOX', 'false').lower() == 'true'
    APP_BASE_URL = os.environ.get('APP_BASE_URL', '')


class ConfigDesenvolvimento(Config):
    """Configuração para desenvolvimento."""
    DEBUG = True


class ConfigProducao(Config):
    """Configuração para produção."""
    DEBUG = False
