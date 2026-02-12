"""Utilitários para validação de webhooks do Mercado Pago."""

import hmac
import hashlib
from flask import current_app


def validar_assinatura_webhook(request):
    """
    Valida a assinatura HMAC-SHA256 do webhook do Mercado Pago.

    Args:
        request: objeto Request do Flask

    Returns:
        bool: True se a assinatura é válida, False caso contrário

    Documentação: https://www.mercadopago.com.br/developers/pt/docs/your-integrations/notifications/webhooks
    """
    try:
        # Obter o header x-signature
        x_signature = request.headers.get('x-signature', '')
        x_request_id = request.headers.get('x-request-id', '')

        if not x_signature:
            current_app.logger.warning('Webhook sem x-signature')
            return False

        # Parsear o header x-signature: ts=123456,v1=hash
        parts = {}
        for part in x_signature.split(','):
            if '=' in part:
                key, value = part.split('=', 1)
                parts[key.strip()] = value.strip()

        ts = parts.get('ts')
        hash_recebido = parts.get('v1')

        if not ts or not hash_recebido:
            current_app.logger.warning('x-signature malformado')
            return False

        # Obter data_id do query string
        data_id = request.args.get('data.id', '')

        # Montar manifest conforme documentação MP
        # Formato: id:{data.id};request-id:{x-request-id};ts:{ts};
        manifest = f'id:{data_id};request-id:{x_request_id};ts:{ts};'

        # Calcular HMAC-SHA256
        secret = current_app.config['MP_WEBHOOK_SECRET']

        if not secret:
            current_app.logger.error('MP_WEBHOOK_SECRET não configurado')
            return False

        hash_calculado = hmac.new(
            secret.encode('utf-8'),
            manifest.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        # Comparar usando timing-safe comparison
        valido = hmac.compare_digest(hash_calculado, hash_recebido)

        if not valido:
            current_app.logger.warning(f'Assinatura inválida. Manifest: {manifest}')

        return valido

    except Exception as e:
        current_app.logger.error(f'Erro ao validar assinatura webhook: {str(e)}')
        return False
