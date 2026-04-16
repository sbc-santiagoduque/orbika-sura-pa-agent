"""
Repositorio DynamoDB — consulta de casos por id.

Tabla: sbc-admin-cases
  Partition key : id   (String) — numero de caso
  Sort key      : date (String) — fecha apertura
"""
import logging
import os

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger(__name__)


class GetCaseRepository:

    def __init__(self, table_name: str = None, region: str = "us-east-1"):
        name = table_name or os.environ.get("DYNAMO_TABLE_NAME", "sbc-admin-cases")
        self._table = boto3.resource("dynamodb", region_name=region).Table(name)

    def get_by_caso(self, caso: str) -> dict | None:
        """
        Retorna el registro del caso desde DynamoDB.

        Usa query por partition key (id = caso) ya que el caso es unico.
        Retorna el primer item encontrado, o None si no existe.
        """
        response = self._table.query(
            KeyConditionExpression=Key("id").eq(caso)
        )
        items = response.get("Items", [])
        if not items:
            logger.info("Caso no encontrado en DynamoDB", extra={"caso": caso})
            return None

        logger.info("Caso encontrado en DynamoDB", extra={"caso": caso})
        return items[0]
