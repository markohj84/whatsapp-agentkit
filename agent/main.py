# agent/main.py — Servidor FastAPI + Webhook de WhatsApp
# Generado por AgentKit

"""
Servidor principal del agente de WhatsApp.
Funciona con cualquier proveedor (Meta, Twilio) gracias a la capa de providers.
"""

import os
import logging
from contextlib import asynccontextmanager
from fastapi import BackgroundTasks, FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv

from agent.brain import generar_respuesta
from agent.memory import inicializar_db, guardar_mensaje, obtener_historial
from agent.providers import obtener_proveedor
from agent import tools  # noqa: F401 — registra el modelo Ticket antes de crear tablas

load_dotenv()

# Configuración de logging según entorno
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
log_level = logging.DEBUG if ENVIRONMENT == "development" else logging.INFO
logging.basicConfig(level=log_level)
logger = logging.getLogger("agentkit")

# Proveedor de WhatsApp (se configura en .env con WHATSAPP_PROVIDER)
proveedor = obtener_proveedor()
PORT = int(os.getenv("PORT", 8000))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa la base de datos al arrancar el servidor."""
    await inicializar_db()
    logger.info("Base de datos inicializada")
    logger.info(f"Servidor AgentKit corriendo en puerto {PORT}")
    logger.info(f"Proveedor de WhatsApp: {proveedor.__class__.__name__}")
    yield


app = FastAPI(
    title="AgentKit — WhatsApp AI Agent",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/")
async def health_check():
    """Endpoint de salud para Railway/monitoreo."""
    return {"status": "ok", "service": "agentkit"}


@app.get("/webhook")
async def webhook_verificacion(request: Request):
    """Verificación GET del webhook (requerido por Meta Cloud API, no-op para otros)."""
    resultado = await proveedor.validar_webhook(request)
    if resultado is not None:
        return PlainTextResponse(str(resultado))
    return {"status": "ok"}


async def procesar_mensaje(msg):
    """Genera la respuesta y la envía. Corre en background, fuera del ciclo de vida del webhook."""
    try:
        logger.info(f"Mensaje de {msg.telefono}: {msg.texto}")

        # Obtener historial ANTES de guardar el mensaje actual
        # (brain.py agrega el mensaje actual, evitando duplicados)
        historial = await obtener_historial(msg.telefono)

        # Generar respuesta con Claude
        respuesta = await generar_respuesta(msg.texto, historial)

        # Guardar mensaje del usuario Y respuesta del agente en memoria
        await guardar_mensaje(msg.telefono, "user", msg.texto)
        await guardar_mensaje(msg.telefono, "assistant", respuesta)

        # Enviar respuesta por WhatsApp via el proveedor
        await proveedor.enviar_mensaje(msg.telefono, respuesta)

        logger.info(f"Respuesta a {msg.telefono}: {respuesta}")
    except Exception as e:
        logger.error(f"Error procesando mensaje de {msg.telefono}: {e}")


@app.post("/webhook")
async def webhook_handler(request: Request, background_tasks: BackgroundTasks):
    """
    Recibe mensajes de WhatsApp via el proveedor configurado.
    Responde 200 de inmediato y procesa en background — si Claude tarda más de
    lo que el proveedor espera, un timeout ya no dispara reintentos duplicados.
    """
    if not await proveedor.verificar_firma(request):
        logger.warning("Firma de webhook inválida — request rechazado")
        raise HTTPException(status_code=401, detail="Firma inválida")

    try:
        mensajes = await proveedor.parsear_webhook(request)
    except Exception as e:
        logger.error(f"Error parseando webhook: {e}")
        return {"status": "ok"}

    for msg in mensajes:
        # Ignorar mensajes propios o vacíos
        if msg.es_propio or not msg.texto:
            continue
        background_tasks.add_task(procesar_mensaje, msg)

    return {"status": "ok"}
