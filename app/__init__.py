"""Fábrica da aplicação FERRATO."""

from datetime import datetime
from flask import Flask
from app.config import ConfigDesenvolvimento


def criar_app(config_class=ConfigDesenvolvimento):
    """Cria e configura a aplicação Flask."""

    app = Flask(__name__)
    app.config.from_object(config_class)

    # --- Registrar Blueprints ---
    from app.blueprints.main import main_bp
    app.register_blueprint(main_bp)

    # --- Context Processors ---
    @app.context_processor
    def variaveis_globais():
        """Injeta variáveis disponíveis em todos os templates."""
        return {
            'ano_atual': datetime.now().year,
        }

    return app
