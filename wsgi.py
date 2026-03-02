"""Ponto de entrada WSGI para servidores de produção (Gunicorn/uWSGI).

Uso:
    gunicorn wsgi:app --bind 0.0.0.0:8000 --workers 2
"""

from app import criar_app
from app.config import ConfigProducao

app = criar_app(ConfigProducao)
