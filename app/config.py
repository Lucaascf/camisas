"""Configurações da aplicação."""

import os


class Config:
    """Configuração base."""
    SECRET_KEY = os.environ.get('SECRET_KEY', 'chave-secreta-dev-ferrato-2026')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///ferrato.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    DEBUG = False


class ConfigDesenvolvimento(Config):
    """Configuração para desenvolvimento."""
    DEBUG = True


class ConfigProducao(Config):
    """Configuração para produção."""
    DEBUG = False
