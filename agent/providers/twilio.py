# agent/providers/twilio.py — Adaptador para Twilio WhatsApp
# Generado por AgentKit

import os
import logging
import base64
import hashlib
import hmac
import httpx
from fastapi import Request
from agent.providers.base import ProveedorWhatsApp, MensajeEntrante

logger = logging.getLogger("agentkit")


class ProveedorTwilio(ProveedorWhatsApp):
    """Proveedor de WhatsApp usando Twilio."""

    def __init__(self):
        self.account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        self.phone_number = os.getenv("TWILIO_PHONE_NUMBER")

    async def verificar_firma(self, request: Request) -> bool:
        """
        Valida X-Twilio-Signature: HMAC-SHA1(auth_token, url + params_ordenados) en base64.
        https://www.twilio.com/docs/usage/webhooks/webhooks-security
        """
        if not self.auth_token:
            logger.warning("TWILIO_AUTH_TOKEN no configurado — no se puede verificar la firma")
            return True
        firma = request.headers.get("X-Twilio-Signature", "")
        if not firma:
            return False
        form = await request.form()
        base = str(request.url) + "".join(f"{k}{v}" for k, v in sorted(form.items()))
        esperada = base64.b64encode(
            hmac.new(self.auth_token.encode(), base.encode(), hashlib.sha1).digest()
        ).decode()
        # DEBUG TEMPORAL — quitar despues de diagnosticar el mismatch de firma
        logger.warning(
            f"[debug-firma] url={str(request.url)!r} token={self.auth_token[:4]!r}...{self.auth_token[-4:]!r} "
            f"token_len={len(self.auth_token)} recibida={firma!r} esperada={esperada!r}"
        )
        return hmac.compare_digest(firma, esperada)

    async def parsear_webhook(self, request: Request) -> list[MensajeEntrante]:
        """Parsea el payload form-encoded de Twilio."""
        form = await request.form()
        texto = form.get("Body", "")
        telefono = form.get("From", "").replace("whatsapp:", "")
        mensaje_id = form.get("MessageSid", "")
        if not texto:
            return []
        return [MensajeEntrante(
            telefono=telefono,
            texto=texto,
            mensaje_id=mensaje_id,
            es_propio=False,
        )]

    async def enviar_mensaje(self, telefono: str, mensaje: str) -> bool:
        """Envía mensaje via Twilio API."""
        if not all([self.account_sid, self.auth_token, self.phone_number]):
            logger.warning("Variables de Twilio no configuradas")
            return False
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        auth = base64.b64encode(f"{self.account_sid}:{self.auth_token}".encode()).decode()
        headers = {"Authorization": f"Basic {auth}"}
        data = {
            "From": f"whatsapp:{self.phone_number}",
            "To": f"whatsapp:{telefono}",
            "Body": mensaje,
        }
        async with httpx.AsyncClient() as client:
            r = await client.post(url, data=data, headers=headers)
            if r.status_code != 201:
                logger.error(f"Error Twilio: {r.status_code} — {r.text}")
            return r.status_code == 201
