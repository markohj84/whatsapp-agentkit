# agent/tools.py — Herramientas del agente
# Generado por AgentKit

"""
Herramientas específicas del negocio de 3dev.
Casos de uso: preguntas frecuentes (via /knowledge) y soporte post-venta (tickets).
"""

import os
import yaml
import logging
import uuid
from datetime import datetime
from sqlalchemy import String, Text, DateTime, select
from sqlalchemy.orm import Mapped, mapped_column

from agent.memory import Base, async_session

logger = logging.getLogger("agentkit")


def cargar_info_negocio() -> dict:
    """Carga la información del negocio desde business.yaml."""
    try:
        with open("config/business.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logger.error("config/business.yaml no encontrado")
        return {}


def obtener_horario() -> dict:
    """Retorna el horario de atención del negocio."""
    info = cargar_info_negocio()
    return {
        "horario": info.get("negocio", {}).get("horario", "No disponible"),
        "esta_abierto": True,
    }


def buscar_en_knowledge(consulta: str) -> str:
    """
    Busca información relevante en los archivos de /knowledge.
    Retorna el contenido más relevante encontrado.
    """
    resultados = []
    knowledge_dir = "knowledge"

    if not os.path.exists(knowledge_dir):
        return "No hay archivos de conocimiento disponibles."

    for archivo in os.listdir(knowledge_dir):
        ruta = os.path.join(knowledge_dir, archivo)
        if archivo.startswith(".") or not os.path.isfile(ruta):
            continue
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                contenido = f.read()
                if consulta.lower() in contenido.lower():
                    resultados.append(f"[{archivo}]: {contenido[:500]}")
        except (UnicodeDecodeError, IOError):
            continue

    if resultados:
        return "\n---\n".join(resultados)
    return "No encontré información específica sobre eso en mis archivos."


# ════════════════════════════════════════════════════════════
# Soporte post-venta — tickets
# ════════════════════════════════════════════════════════════

class Ticket(Base):
    """Ticket de soporte post-venta."""
    __tablename__ = "tickets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    telefono: Mapped[str] = mapped_column(String(50), index=True)
    problema: Mapped[str] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(String(20), default="abierto")  # abierto | escalado | cerrado
    razon_escalamiento: Mapped[str] = mapped_column(Text, nullable=True)
    creado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


async def crear_ticket(telefono: str, problema: str) -> str:
    """Crea un ticket de soporte y retorna su ID."""
    ticket_id = str(uuid.uuid4())[:8]
    async with async_session() as session:
        session.add(Ticket(id=ticket_id, telefono=telefono, problema=problema))
        await session.commit()
    logger.info(f"Ticket creado {ticket_id} para {telefono}")
    return ticket_id


async def consultar_ticket(ticket_id: str) -> dict | None:
    """Consulta el estado de un ticket por su ID."""
    async with async_session() as session:
        result = await session.execute(select(Ticket).where(Ticket.id == ticket_id))
        ticket = result.scalar_one_or_none()
        if not ticket:
            return None
        return {
            "id": ticket.id,
            "telefono": ticket.telefono,
            "problema": ticket.problema,
            "estado": ticket.estado,
        }


async def escalar_ticket(ticket_id: str, razon: str) -> bool:
    """Marca un ticket como escalado al equipo humano."""
    async with async_session() as session:
        result = await session.execute(select(Ticket).where(Ticket.id == ticket_id))
        ticket = result.scalar_one_or_none()
        if not ticket:
            return False
        ticket.estado = "escalado"
        ticket.razon_escalamiento = razon
        await session.commit()
    logger.info(f"Ticket {ticket_id} escalado: {razon}")
    return True
