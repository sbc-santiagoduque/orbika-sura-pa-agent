"""
Repositorio DynamoDB — obtiene y actualiza imagenes clasificadas.

Tabla: sbc-admin-cases
  Partition key : id   (String)
  Sort key      : date (String) — fecha apertura

Hace merge de las imagenes clasificadas con las existentes en DynamoDB:
- Busca cada imagen recibida por su 'nombre'
- Actualiza solo document_type, confidence y justification
- Mantiene intactos nombre, url, seccion_id y demas campos
"""
import logging
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger(__name__)

_CAMPOS_CLASIFICACION = {"document_type", "confidence", "justification"}


class ClassifierRepository:

    def __init__(self, table_name: str = None, region: str = "us-east-1"):
        name = table_name or os.environ.get("DYNAMO_TABLE_NAME", "sbc-admin-cases")
        self._table = boto3.resource("dynamodb", region_name=region).Table(name)

    def get_registro_by_id(self, record_id: str) -> dict:
        """
        Busca el registro mas reciente usando query por partition key.

        Returns:
            El item de DynamoDB con todos sus campos (incluye 'date').

        Raises:
            ValueError: si no existe ningun registro para ese id.
        """
        response = self._table.query(
            KeyConditionExpression=Key("id").eq(record_id),
            ScanIndexForward=False,  # descendente — el mas reciente primero
            Limit=1,
        )
        items = response.get("Items", [])
        if not items:
            raise ValueError(f"Registro '{record_id}' no encontrado en DynamoDB.")
        return items[0]

    def update_imagenes(self, record_id: str, date: str, imagenes_clasificadas: list[dict]) -> dict:
        """
        Hace merge de las imagenes clasificadas con las existentes en DynamoDB.

        Por cada imagen existente en el registro:
          - Si llego clasificada (match por 'nombre'): actualiza unicamente
            document_type, confidence y justification
          - Si no llego: la mantiene como estaba

        Args:
            record_id:             id del registro (partition key)
            date:                  fecha apertura (sort key)
            imagenes_clasificadas: imagenes clasificadas en este llamado

        Returns:
            dict con totales: total, clasificadas, pendientes
        """
        registro = self._get_registro(record_id, date)
        images_actuales = registro.get("images", [])

        indice = {img["nombre"]: img for img in imagenes_clasificadas}

        images_merged = []
        clasificadas = 0
        for img in images_actuales:
            nombre = str(img.get("nombre", ""))
            if nombre in indice:
                clasificacion = {k: v for k, v in indice[nombre].items() if k in _CAMPOS_CLASIFICACION}
                images_merged.append({**img, **clasificacion})
                clasificadas += 1
            else:
                images_merged.append(img)

        self._table.update_item(
            Key={"id": record_id, "date": date},
            UpdateExpression="SET images = :imgs",
            ExpressionAttributeValues={
                ":imgs": _floats_to_decimal(images_merged),
            },
        )

        pendientes = len(images_actuales) - clasificadas
        logger.info(
            "Imagenes clasificadas guardadas en DynamoDB",
            extra={"record_id": record_id, "clasificadas": clasificadas, "pendientes": pendientes},
        )
        return {
            "total":        len(images_actuales),
            "clasificadas": clasificadas,
            "pendientes":   pendientes,
        }

    def _get_registro(self, record_id: str, date: str) -> dict:
        response = self._table.get_item(Key={"id": record_id, "date": date})
        item = response.get("Item")
        if not item:
            raise ValueError(f"Registro '{record_id}' con date '{date}' no encontrado en DynamoDB.")
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
