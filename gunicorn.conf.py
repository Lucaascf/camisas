"""Configuração do Gunicorn para produção (Hostinger VPS).

Uso:
    gunicorn -c gunicorn.conf.py wsgi:app
"""

import multiprocessing
import os

# --- Binding ---
bind = "127.0.0.1:8000"

# --- Workers ---
# Regra: (2 × CPUs) + 1  — sane default para I/O-bound Flask
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "sync"
threads = 2
worker_connections = 1000

# --- Timeouts ---
timeout = 120          # requisições lentas (upload de imagens no admin)
keepalive = 5
graceful_timeout = 30

# --- Logging ---
_log_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(_log_dir, exist_ok=True)

accesslog = os.path.join(_log_dir, "gunicorn_access.log")
errorlog  = os.path.join(_log_dir, "gunicorn_error.log")
loglevel  = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)sus'

# --- Processo ---
proc_name = "ferrato"
daemon = False          # deixar False — systemd cuida do processo
preload_app = True      # carrega app antes de forkar (economiza RAM)

# --- Segurança ---
limit_request_line   = 8190
limit_request_fields = 100
