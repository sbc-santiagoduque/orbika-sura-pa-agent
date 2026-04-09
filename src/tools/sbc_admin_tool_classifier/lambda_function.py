"""
Lambda Tool: sbc-admin-tool-classifier-lambda
Accion: Persistir clasificacion de imagenes realizada por el agente

Recibe el caso, la fecha y el array de imagenes enriquecidas con el
analisis de vision del agente (document_type, confidence, justification)
y actualiza el registro en DynamoDB.

Parametros de entrada (Bedrock Action Group):
    caso     — numero de caso
    date     — fecha apertura del caso (sort key DynamoDB, formato YYYY-MM-DD)
    imagenes — JSON string con array de imagenes enriquecidas:
               [{nombre, url, seccion_id, document_type, confidence, justification}, ...]

Variables de entorno requeridas:
    DYNAMO_TABLE_NAME — nombre de la tabla DynamoDB (default: sbc-admin-cases)
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

_ACTION_GROUP     = "sbc-admin-tool-actions"
_FUNCTION_DEFAULT = "sbc-admin-tool-classifier-lambda"


def lambda_handler(event, context):
    function_name = event.get("function", _FUNCTION_DEFAULT)
    logger.info("EVENT RAW: %s", json.dumps(event, ensure_ascii=False, default=str))

    try:
        params = _extraer_parametros(event, ["caso", "date", "imagenes"])
        caso     = params["caso"]
        date     = params["date"]
        imagenes = _parsear_imagenes(params["imagenes"])
        totales  = _process(caso, date, imagenes)
        return _format_response(function_name, caso, totales)

    except Exception as exc:
        logger.error("Error en sbc-admin-tool-classifier-lambda", extra={"error": str(exc)})
        return _format_error(function_name, str(exc))


def _extraer_parametros(event: dict, nombres: list[str]) -> dict:
    params = {p["name"]: p["value"] for p in event.get("parameters", [])}
    missing = [n for n in nombres if n not in params]
    if missing:
        raise ValueError(f"Parametros requeridos no encontrados: {missing}")
    return {n: params[n] for n in nombres}


def _parsear_imagenes(imagenes_raw) -> list[dict]:
    """Parsea el array de imagenes desde string JSON o lista ya parseada.
    Elimina caracteres de control que el console de AWS puede introducir."""
    if isinstance(imagenes_raw, list):
        data = imagenes_raw
    else:
        try:
            cleaned = "".join(c for c in imagenes_raw if ord(c) >= 32 or c in "\t")
            data = json.loads(cleaned)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"El parametro 'imagenes' no es un JSON valido: {exc}")

    if not isinstance(data, list):
        raise ValueError("El parametro 'imagenes' debe ser un array JSON.")

    _validar_imagenes(data)
    return data


def _validar_imagenes(imagenes: list[dict]) -> None:
    campos_requeridos = {"nombre", "url", "document_type", "confidence", "justification"}
    for i, img in enumerate(imagenes):
        faltantes = campos_requeridos - set(img.keys())
        if faltantes:
            raise ValueError(f"Imagen [{i}] le faltan campos: {faltantes}")


def _process(caso: str, date: str, imagenes: list[dict]) -> dict:
    from src.tools.sbc_admin_tool_classifier.infrastructure.dynamo_repository import ClassifierRepository

    return ClassifierRepository().update_imagenes(caso=caso, date=date, imagenes_clasificadas=imagenes)


def _format_response(function_name: str, caso: str, totales: dict) -> dict:
    return {
        "actionGroup": _ACTION_GROUP,
        "function": function_name,
        "functionResponse": {
            "responseBody": {
                "TEXT": {
                    "body": json.dumps(
                        {
                            "status": "ok",
                            "caso":        caso,
                            "total":       totales["total"],
                            "clasificadas": totales["clasificadas"],
                            "pendientes":  totales["pendientes"],
                        },
                        ensure_ascii=False,
                    )
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
