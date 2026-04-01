import json
import logging
from datetime import datetime, timezone
from typing import Any

# Usar el logger del módulo para que CloudWatch capture el nombre correcto del origen
logger = logging.getLogger(__name__)

# Únicos valores válidos para el campo status de LogTool
_VALID_STATUSES = {"ok", "error"}


def log_decision(
    case_id: str,
    fase: str,
    decision: str,
    razonamiento: str | None,
    inputs: dict[str, Any],
) -> None:
    """
    Emite un LogDecision estructurado en JSON al log group de CloudWatch.

    Llamar desde sub-agentes cada vez que el agente IA toma una decisión
    que impacta el flujo del caso (ej: criterio_panama detectado, responsabilidad
    clasificada). Persiste el razonamiento para auditoría del piloto.
    """
    payload = {
        "type": "decision",
        "case_id": case_id,
        "fase": fase,
        "decision": decision,
        "razonamiento": razonamiento,  # None si la decisión es determinística
        "inputs": inputs,
        "timestamp": _now_iso(),
    }
    logger.info(json.dumps(payload, ensure_ascii=False))


def log_tool(
    case_id: str,
    fase: str,
    tool_name: str,
    input_data: dict[str, Any],
    output_data: dict[str, Any],
    duracion_ms: int,
    status: str,
) -> None:
    """
    Emite un LogTool estructurado en JSON al log group de CloudWatch.

    Llamar al inicio y fin de cada Lambda tool para trazabilidad operativa.
    Permite diagnosticar timeouts, errores de RPA y latencias por sistema externo.
    """
    if status not in _VALID_STATUSES:
        raise ValueError(f"status debe ser 'ok' o 'error', recibido: '{status}'")

    payload = {
        "type": "tool",
        "case_id": case_id,
        "fase": fase,
        "tool_name": tool_name,
        "input": input_data,
        "output": output_data,
        "duracion_ms": duracion_ms,
        "status": status,
        "timestamp": _now_iso(),
    }
    logger.info(json.dumps(payload, ensure_ascii=False))


def _now_iso() -> str:
    """Retorna el timestamp actual en formato ISO 8601 UTC."""
    return datetime.now(timezone.utc).isoformat()
