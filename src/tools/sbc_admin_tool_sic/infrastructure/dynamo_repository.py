"""
Repositorio DynamoDB para sbc-admin-tool-sic-lambda.

Tabla: sbc-admin-cases
  Partition key : id   (String) — numero de caso
  Sort key      : date (String) — fecha apertura (YYYY-MM-DD)

GSI "caso" indexa por: insurer, plate, claim, coverage
"""
import logging
import os
from datetime import datetime, timezone

import boto3

logger = logging.getLogger(__name__)


class AdminCasesRepository:

    def __init__(self, table_name: str = None, region: str = "us-east-1"):
        name = table_name or os.environ.get("DYNAMO_TABLE_NAME", "sbc-admin-cases")
        self._table = boto3.resource("dynamodb", region_name=region).Table(name)

    def save(
        self,
        caso: str,
        placa: str,
        expediente: str,
        siniestro: str,
        imagenes: list[dict],
        fecha_apertura: str = None,
        insurer: str = "SURA",
    ) -> None:
        """
        Escribe o sobreescribe el registro del caso en DynamoDB.

        Mapeo de campos:
            id          <- caso          (partition key)
            date        <- fecha_apertura o fecha actual  (sort key)
            plate       <- placa         (GSI)
            claim       <- siniestro     (GSI)
            insurer     <- "SURA"        (GSI, fijo por ahora)
            expediente  <- expediente
            images      <- lista de {nombre, url, seccion_id}
        """
        now = datetime.now(timezone.utc)
        date_value = fecha_apertura or now.strftime("%Y-%m-%d")

        item = {
            "id":          caso,
            "date":        date_value,
            "plate":       placa,
            "claim":       siniestro,
            "insurer":     insurer,
            "expediente":  expediente,
            "image_count": len(imagenes),
            "images":      imagenes,
            "updated_at":  now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        self._table.put_item(Item=item)
        logger.info("Caso guardado en DynamoDB", extra={"caso": caso, "date": date_value, "images": len(imagenes)})
