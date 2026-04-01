import boto3
from datetime import datetime, timezone, timedelta
from typing import Any

# Valores válidos para decision_final según el diseño AAP-I1
_VALID_DECISIONS = {"falta_docs", "espera_cotizacion", "pasa_a_analista", "escalado", "error"}

# TTL por escenario de cierre (en segundos)
# - Cierres normales: 24h — el caso ya terminó, limpiar rápido
# - Error: 3 días — el analista necesita tiempo para revisarlo
_TTL_SECONDS = {
    "falta_docs": 86_400,       # 24h
    "espera_cotizacion": 86_400,
    "pasa_a_analista": 86_400,
    "escalado": 86_400,
    "error": 259_200,           # 3 días
}


class ResultadoCasoRepository:
    """
    Persiste el resultado final de cada caso procesado en DynamoDB.

    Es el único punto de escritura de ResultadoCaso — lo invoca U5 Agente Cierre
    al terminar el flujo. En modo dry_run=True, el ítem se persiste igual pero
    con ese flag para distinguirlo en las métricas del piloto.
    """

    def __init__(self, table_name: str, region: str = "us-east-1"):
        # Inyectamos table_name y region para facilitar tests con moto
        self._table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    def save(self, payload: dict[str, Any]) -> None:
        """
        Persiste un ResultadoCaso en DynamoDB.

        Calcula el TTL automáticamente según la decision_final para que DynamoDB
        limpie los ítems expirados sin intervención manual.

        Args:
            payload: dict con los campos del ResultadoCaso (ver domain model U6)

        Raises:
            ValueError: si decision_final no es un valor del catálogo
        """
        decision = payload.get("decision_final")
        if decision not in _VALID_DECISIONS:
            raise ValueError(
                f"decision_final inválido: '{decision}'. "
                f"Válidos: {sorted(_VALID_DECISIONS)}"
            )

        # Calcular TTL como unix timestamp para el atributo nativo de DynamoDB
        ttl = int((datetime.now(timezone.utc) + timedelta(seconds=_TTL_SECONDS[decision])).timestamp())

        item = {**payload, "ttl_expiry": ttl}
        self._table.put_item(Item=item)
