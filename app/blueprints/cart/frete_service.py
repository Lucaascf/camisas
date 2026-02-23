"""Serviço de cálculo de frete via Melhor Envio."""

import logging
import os

import requests

logger = logging.getLogger(__name__)

TOKEN      = os.environ.get('MELHOR_ENVIO_TOKEN', '')
SANDBOX    = os.environ.get('MELHOR_ENVIO_SANDBOX', 'True').lower() == 'true'
BASE       = 'https://sandbox.melhorenvio.com.br' if SANDBOX else 'https://melhorenvio.com.br'
CEP_ORIGEM = os.environ.get('LOJA_CEP_ORIGEM', '')

# Dimensões padrão de uma camisa
DIMS = {'height': 5, 'width': 25, 'length': 30}
PESO_POR_ITEM = 0.3  # kg por camisa

# Apenas estes serviços são exibidos no checkout
SERVICOS_PERMITIDOS = {'PAC', 'SEDEX', '.Package'}


def calcular_frete(cep_destino: str, qtd_itens: int = 1) -> list:
    """
    Chama a API do Melhor Envio e retorna lista de opções de frete.
    Cada item: {'id', 'nome', 'transportadora', 'preco', 'prazo'}
    Retorna lista vazia em caso de erro ou configuração ausente.
    """
    if not TOKEN or not CEP_ORIGEM:
        logger.error("FRETE: variáveis não carregadas — TOKEN=%s, CEP_ORIGEM=%s",
                     bool(TOKEN), bool(CEP_ORIGEM))
        return []

    cep_clean = cep_destino.replace('-', '').strip()
    peso = max(PESO_POR_ITEM * qtd_itens, 0.1)

    payload = {
        'from': {'postal_code': CEP_ORIGEM.replace('-', '')},
        'to':   {'postal_code': cep_clean},
        'package': {**DIMS, 'weight': round(peso, 2)},
        'options': {'insurance_value': 0, 'receipt': False, 'own_hand': False},
    }

    headers = {
        'Authorization': f'Bearer {TOKEN}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': 'FERRATO E-commerce (useferrato@gmail.com)',
    }

    logger.info("FRETE: chamando %s/api/v2/me/shipment/calculate — sandbox=%s, TOKEN_ok=%s",
                BASE, SANDBOX, bool(TOKEN))
    try:
        r = requests.post(
            f'{BASE}/api/v2/me/shipment/calculate',
            json=payload,
            headers=headers,
            timeout=8,
        )
        r.raise_for_status()
        data = r.json()
    except requests.HTTPError:
        logger.error("FRETE: HTTP %s — %s", r.status_code, r.text[:500])
        return []
    except requests.RequestException as e:
        logger.error("FRETE: erro de conexão — %s", e)
        return []
    except Exception as e:
        logger.error("FRETE: exceção inesperada — %s", e)
        return []

    opcoes = []
    for s in data:
        if s.get('error'):
            continue
        preco = float(s.get('price') or 0)
        if preco <= 0:
            continue
        dr = s.get('delivery_range') or {}
        prazo_min = dr.get('min', s.get('delivery_time', '?'))
        prazo_max = dr.get('max', prazo_min)
        if prazo_min != prazo_max:
            prazo = f'{prazo_min}–{prazo_max} dias úteis'
        else:
            prazo = f'{prazo_min} dias úteis'
        empresa = (s.get('company') or {}).get('name', '')
        nome_servico = s.get('name', '')
        if nome_servico not in SERVICOS_PERMITIDOS:
            continue
        opcoes.append({
            'id':             f'{empresa} - {nome_servico}',
            'nome':           nome_servico,
            'transportadora': empresa,
            'preco':          preco,
            'prazo':          prazo,
        })

    opcoes.sort(key=lambda x: x['preco'])
    return opcoes


def is_salvador_lf(cidade: str, estado: str) -> bool:
    """Retorna True se a cidade for Salvador ou Lauro de Freitas, BA."""
    cidades_locais = {'salvador', 'lauro de freitas'}
    return estado.upper() == 'BA' and cidade.lower().strip() in cidades_locais


def calcular_frete_local(subtotal: float) -> list:
    """Frete fixo para Salvador / Lauro de Freitas, grátis se subtotal >= limiar."""
    from app.models import ConfigFrete
    config = ConfigFrete.get()
    eh_gratis = (
        config.local_gratis_acima is not None
        and subtotal >= config.local_gratis_acima
    )
    preco = 0.0 if eh_gratis else config.local_valor
    return [{
        'id':             'Entrega Local',
        'nome':           'Entrega',
        'transportadora': 'Entrega Local',
        'preco':          preco,
        'prazo':          '1–3 dias úteis',
    }]
