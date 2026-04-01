import boto3
from boto3.dynamodb.conditions import Attr
from datetime import datetime, timezone, timedelta
from typing import Any

# Fase inicial de todo run nuevo
_FASE_INICIAL = "ingesta"

# Valores válidos para decision_final al cerrar un run
_VALID_DECISIONS = {"falta_docs", "espera_cotizacion", "pasa_a_analista", "escalado", "error"}

# TTL de seguridad mientras el run está activo (7 días)
# Si el agente crashea sin llamar a close(), DynamoDB limpia el registro igualmente
_TTL_ACTIVO_SEGUNDOS = 604_800  # 7 días

# TTL al cierre según el tipo de decisión (ver ADR-U1-2)
_TTL_CIERRE_SEGUNDOS = {
    "falta_docs": 86_400,        # 24h — caso cerrado normalmente
    "espera_cotizacion": 86_400,
    "pasa_a_analista": 86_400,
    "escalado": 86_400,
    "error": 259_200,            # 3 días — analista necesita tiempo para revisar
}


class EstadoFlujoRepository:
    """
    Gestiona el estado activo de cada caso en DynamoDB tabla EstadoFlujo.

    El Orchestrador lee el estado al INICIO del run para detectar runs previos
    con error. Durante el run usa memoria de sesión Bedrock para decisiones
    intermedias (sin latencia DynamoDB). Escribe a DynamoDB solo en checkpoints
    clave (al completar cada fase) y al cerrar el caso.

    Ver ADR-U1-1 y ADR-U1-3 en el diseño general para el razonamiento completo.
    """

    def __init__(self, table_name: str, region: str = "us-east-1"):
        self._table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    def get(self, case_id: str) -> dict[str, Any] | None:
        """
        Lee el EstadoFlujo de un caso.

        Returns:
            El ítem DynamoDB si existe, None si el caso no tiene run activo.
        """
        response = self._table.get_item(Key={"case_id": case_id})
        return response.get("Item")

    def create(self, caso: dict[str, Any]) -> None:
        """
        Crea un nuevo run para el caso con estado inicial `ingesta`.

        Usa ConditionExpression para fallar si ya existe un run activo —
        previene duplicados si el trigger se ejecuta dos veces para el mismo caso.

        Args:
            caso: dict con los datos del ItemBandeja (case_id, placa, canal, etc.)

        Raises:
            ValueError: si ya existe un run activo para este case_id
        """
        ttl = _ttl_unix(_TTL_ACTIVO_SEGUNDOS)
        item = {
            **caso,
            "fase_actual": _FASE_INICIAL,
            "fases_completadas": [],
            "flags": {},
            "escalamientos": [],
            "ttl_expiry": ttl,
        }
        try:
            self._table.put_item(
                Item=item,
                # Solo inserta si NO existe ya un ítem con ese case_id
                ConditionExpression=Attr("case_id").not_exists(),
            )
        except self._table.meta.client.exceptions.ConditionalCheckFailedException:
            raise ValueError(f"ya existe un run activo para case_id='{caso['case_id']}'")

    def update_fase(
        self,
        case_id: str,
        fase_actual: str,
        fase_completada: dict[str, Any],
        flags_update: dict[str, Any],
    ) -> None:
        """
        Checkpoint: actualiza la fase actual, agrega la fase completada y mergea flags.

        Los flags se mergean (no reemplazan) para que cada sub-agente pueda
        añadir su propio flag sin borrar los de los demás.

        Args:
            case_id: identificador del caso
            fase_actual: nueva fase en curso (ej: "expediente")
            fase_completada: dict con {fase, status, duracion_ms} de la fase que terminó
            flags_update: dict con los flags a agregar/actualizar (ej: {"documentos_ok": True})
        """
        # Leer flags actuales para mergear sin sobrescribir
        estado = self.get(case_id) or {}
        flags_merged = {**estado.get("flags", {}), **flags_update}

        self._table.update_item(
            Key={"case_id": case_id},
            UpdateExpression=(
                "SET fase_actual = :fa, "
                "flags = :fl, "
                "fases_completadas = list_append(fases_completadas, :fc)"
            ),
            ExpressionAttributeValues={
                ":fa": fase_actual,
                ":fl": flags_merged,
                # list_append requiere lista — DynamoDB la concatena a la existente
                ":fc": [fase_completada],
            },
        )

    def close(self, case_id: str, decision_final: str) -> None:
        """
        Cierra el run marcando fase_actual=completado y ajustando el TTL según
        la decisión final (24h para cierres normales, 3 días para errores).

        Args:
            case_id: identificador del caso
            decision_final: resultado del procesamiento

        Raises:
            ValueError: si decision_final no está en el catálogo
        """
        if decision_final not in _VALID_DECISIONS:
            raise ValueError(
                f"decision_final inválido: '{decision_final}'. "
                f"Válidos: {sorted(_VALID_DECISIONS)}"
            )

        ttl = _ttl_unix(_TTL_CIERRE_SEGUNDOS[decision_final])
        self._table.update_item(
            Key={"case_id": case_id},
            UpdateExpression="SET fase_actual = :fa, ttl_expiry = :ttl",
            ExpressionAttributeValues={
                ":fa": "completado",
                ":ttl": ttl,
            },
        )


def _ttl_unix(seconds: int) -> int:
    """Calcula un TTL como unix timestamp a partir de ahora + segundos dados."""
    return int((datetime.now(timezone.utc) + timedelta(seconds=seconds)).timestamp())
