"""
Repositorio DynamoDB para extract_expediente_sic_api.

Tabla configurada via DYNAMO_TABLE_NAME (default: sbc-admin-cases).
  Partition key : id   (String) — UUID del registro
  Sort key      : date (String) — fecha apertura (YYYY-MM-DD)

Operaciones:
  - find_by_plate_expediente : scan con filtro por plate + expediente
  - update_images            : actualiza images, image_count y updated_at
"""
import logging
import os
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Attr

logger = logging.getLogger(__name__)


class AdminCasesRepository:

    def __init__(self, table_name: str = None, region: str = "us-east-1"):
        name = table_name or os.environ.get("DYNAMO_TABLE_NAME", "sbc-admin-cases")
        self._table = boto3.resource("dynamodb", region_name=region).Table(name)

    def find_by_plate_expediente(self, plate: str, expediente: str) -> dict:
        """
        Busca el registro por placa y expediente usando Scan con filtro.

        NOTE: Para tablas grandes, reemplazar con Query en GSI sobre 'plate'
              cuando se confirme el nombre del indice.

        Raises:
            ValueError: si no existe el registro.
        """
        response = self._table.scan(
            FilterExpression=Attr("plate").eq(plate) & Attr("expediente").eq(expediente),
        )
        items = response.get("Items", [])
        if not items:
            raise ValueError(
                f"No se encontro registro para plate='{plate}' expediente='{expediente}'."
            )
        return items[0]

    def update_images(self, record_id: str, date: str, images: list[dict]) -> None:
        """
        Actualiza unicamente images, image_count y updated_at en el registro existente.

        Args:
            record_id : partition key (UUID)
            date      : sort key (YYYY-MM-DD)
            images    : lista de imagenes obtenidas desde SIC
        """
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._table.update_item(
            Key={"id": record_id, "date": date},
            UpdateExpression="SET images = :imgs, image_count = :cnt, updated_at = :upd",
            ExpressionAttributeValues={
                ":imgs": images,
                ":cnt":  len(images),
                ":upd":  now,
            },
        )
        logger.info(
            "Images actualizadas en DynamoDB",
            extra={"id": record_id, "date": date, "image_count": len(images)},
        )
