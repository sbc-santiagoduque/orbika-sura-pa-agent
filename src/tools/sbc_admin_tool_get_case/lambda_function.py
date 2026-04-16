"""
Lambda Tool: sbc-admin-tool-get-case-lambda
Accion: Consultar caso en DynamoDB por numero de caso

Retorna el registro completo del caso incluyendo las imagenes almacenadas.

Parametros de entrada (Bedrock Action Group):
    caso — numero de caso

Variables de entorno requeridas:
    DYNAMO_TABLE_NAME — nombre de la tabla DynamoDB (default: sbc-admin-cases)
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

_ACTION_GROUP     = "sbc-admin-tool-actions"
_FUNCTION_DEFAULT = "sbc-admin-tool-get-case-lambda"


def lambda_handler(event, context):
    function_name = event.get("function", _FUNCTION_DEFAULT)

    try:
        caso = _extraer_parametro(event, "caso")
        resultado = _process(caso)
        return _format_response(function_name, resultado)

    except Exception as exc:
        logger.error("Error en sbc-admin-tool-get-case-lambda", extra={"error": str(exc)})
        return _format_error(function_name, str(exc))


def _extraer_parametro(event: dict, nombre: str) -> str:
    for p in event.get("parameters", []):
        if p.get("name") == nombre:
            return p["value"]
    raise ValueError(f"Parametro requerido no encontrado: '{nombre}'")


def _process(caso: str) -> dict:
    from src.tools.sbc_admin_tool_get_case.infrastructure.dynamo_repository import GetCaseRepository

    registro = GetCaseRepository().get_by_caso(caso)
    if not registro:
        raise ValueError(f"Caso '{caso}' no encontrado en la base de datos.")
    return registro


def _format_response(function_name: str, resultado: dict) -> dict:
    return {
        "actionGroup": _ACTION_GROUP,
        "function": function_name,
        "functionResponse": {
            "responseBody": {
                "TEXT": {
                    "body": json.dumps(resultado, ensure_ascii=False, default=str)
                }
            }
        },
    }


def _format_error(function_name: str, message: str) -> dict:
    return {
        "actionGroup": _ACTION_GROUP,
        "function": function_name,
        "functionResponse": {
            "responseBody": {
                "TEXT": {
                    "body": json.dumps({"error": message}, ensure_ascii=False)
                }
            }
        },
    }
