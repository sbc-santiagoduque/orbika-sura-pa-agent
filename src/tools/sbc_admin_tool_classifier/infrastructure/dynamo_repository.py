"""
Repositorio DynamoDB — actualiza imagenes clasificadas por el agente.

Tabla: sbc-admin-cases
  Partition key : id   (String) — numero de caso
  Sort key      : date (String) — fecha apertura

Hace merge de las imagenes clasificadas con las existentes en DynamoDB:
- Busca cada imagen recibida por su 'nombre'
- Actualiza solo las que llegaron con clasificacion
- Mantiene intactas las que no fueron clasificadas en este llamado
"""
import logging
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger(__name__)


class ClassifierRepository:

    def __init__(self, table_name: str = None, region: str = "us-east-1"):
        name = table_name or os.environ.get("DYNAMO_TABLE_NAME", "sbc-admin-cases")
        self._table = boto3.resource("dynamodb", region_name=region).Table(name)

    def update_imagenes(self, caso: str, date: str, imagenes_clasificadas: list[dict]) -> dict:
        """
        Hace merge de las imagenes clasificadas con las existentes en DynamoDB.

        Por cada imagen existente en el registro:
          - Si llego clasificada (match por 'nombre'): la actualiza con
            document_type, confidence y justification
          - Si no llego: la mantiene como estaba

        Args:
            caso:                 numero de caso (partition key)
            date:                 fecha apertura (sort key)
            imagenes_clasificadas: imagenes que el agente clasifico en este llamado

        Returns:
            dict con totales: total, clasificadas, pendientes
        """
        registro = self._get_registro(caso, date)
        imagenes_actuales = registro.get("imagenes", [])

        indice = {img["nombre"]: img for img in imagenes_clasificadas}

        _CAMPOS_CLASIFICACION = {"document_type", "confidence", "justification"}

        imagenes_merged = []
        clasificadas = 0
        for img in imagenes_actuales:
            nombre = str(img.get("nombre", ""))
            if nombre in indice:
                clasificacion = {k: v for k, v in indice[nombre].items() if k in _CAMPOS_CLASIFICACION}
                imagenes_merged.append({**img, **clasificacion})
                clasificadas += 1
            else:
                imagenes_merged.append(img)

        self._table.update_item(
            Key={"id": caso, "date": date},
            UpdateExpression="SET imagenes = :imgs",
            ExpressionAttributeValues={
                ":imgs": _floats_to_decimal(imagenes_merged),
            },
        )

        pendientes = len(imagenes_actuales) - clasificadas
        logger.info(
            "Imagenes clasificadas guardadas en DynamoDB",
            extra={"caso": caso, "clasificadas": clasificadas, "pendientes": pendientes},
        )
        return {
            "total":        len(imagenes_actuales),
            "clasificadas": clasificadas,
            "pendientes":   pendientes,
        }

    def _get_registro(self, caso: str, date: str) -> dict:
        response = self._table.get_item(Key={"id": caso, "date": date})
        item = response.get("Item")
        if not item:
            raise ValueError(f"Caso '{caso}' con date '{date}' no encontrado en DynamoDB.")
        return item


def _floats_to_decimal(obj):
    """Convierte recursivamente floats a Decimal para compatibilidad con DynamoDB."""
    if isinstance(obj, list):
        return [_floats_to_decimal(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, float):
        return Decimal(str(obj))
    return obj
