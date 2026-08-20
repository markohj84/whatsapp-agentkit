# tests/test_webhook_security.py — Self-check de la firma de Twilio y el desacople del background task
#
# Corre: python tests/test_webhook_security.py
# Verifica dos cosas que si se rompen, rompen el agente en silencio:
#   1. una firma X-Twilio-Signature invalida se rechaza con 401
#   2. si el procesamiento en background falla (Claude, envio), el webhook igual responde 200
#      (no queda esperando ni propaga el error — asi Twilio no reintenta de mas)

import base64
import hashlib
import hmac
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["WHATSAPP_PROVIDER"] = "twilio"
os.environ["TWILIO_ACCOUNT_SID"] = "test_sid"
os.environ["TWILIO_AUTH_TOKEN"] = "test_token"
os.environ["TWILIO_PHONE_NUMBER"] = "+10000000000"
os.environ["ANTHROPIC_API_KEY"] = "test_key"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_agentkit.db"

from fastapi.testclient import TestClient  # noqa: E402
from agent import main as main_module  # noqa: E402
from agent.main import app  # noqa: E402

PARAMS = {"From": "whatsapp:+521234567890", "Body": "hola", "MessageSid": "SM123"}


def firmar(url: str, params: dict, token: str) -> str:
    base = url + "".join(f"{k}{v}" for k, v in sorted(params.items()))
    return base64.b64encode(hmac.new(token.encode(), base.encode(), hashlib.sha1).digest()).decode()


def test_firma_invalida_rechazada():
    with TestClient(app) as client:
        r = client.post("/webhook", data=PARAMS, headers={"X-Twilio-Signature": "firma-falsa"})
    assert r.status_code == 401, f"esperaba 401, obtuve {r.status_code}"


def test_falla_en_background_no_tumba_el_webhook():
    # Parcheo la referencia que agent.main realmente usa (la importo por nombre con `from`),
    # no agent.brain — y nunca golpea la red real de Anthropic/Twilio.
    async def falla(*a, **kw):
        raise RuntimeError("boom")

    original = main_module.generar_respuesta
    main_module.generar_respuesta = falla
    try:
        with TestClient(app) as client:
            url = str(client.base_url) + "/webhook"
            firma = firmar(url, PARAMS, "test_token")
            r = client.post("/webhook", data=PARAMS, headers={"X-Twilio-Signature": firma})
    finally:
        main_module.generar_respuesta = original

    assert r.status_code == 200, f"esperaba 200 aunque el procesamiento fallara, obtuve {r.status_code}: {r.text}"


if __name__ == "__main__":
    test_firma_invalida_rechazada()
    test_falla_en_background_no_tumba_el_webhook()
    if os.path.exists("test_agentkit.db"):
        os.remove("test_agentkit.db")
    print("OK — firma invalida rechazada (401) y una falla en background no tumba el webhook (200)")
