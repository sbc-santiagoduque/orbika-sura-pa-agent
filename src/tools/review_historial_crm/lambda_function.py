"""
Lambda Tool: review_historial_crm
Acción: F2 — Revisar historial del caso en Salesforce CRM

Invocada por el Agente Analista (Bedrock Action Group).
Navega al caso de Salesforce por sf_record_id y retorna:
  - Metadata del caso (estado, asunto, cuenta, fecha)
  - Comentarios recientes del activity timeline

El agente usa esta información para decidir si el caso está listo
para cerrar o requiere acción adicional.
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

_ACTION_GROUP = "agente-crm-actions"


def lambda_handler(event, context):
    """
    Punto de entrada para Bedrock Action Group.

    El agente invoca esta función con:
    {
        "actionGroup": "agente-crm-actions",
        "function": "review_historial_crm",
        "parameters": [
            {"name": "sf_record_id", "type": "string", "value": "500xxxx"}
        ]
    }
    """
    function_name = event.get("function", "review_historial_crm")

    try:
        _validate_env_vars()
        sf_record_id = _extraer_parametro(event, "sf_record_id")
        resultado = _process(sf_record_id)
        return _format_response(function_name, resultado)

    except Exception as exc:
        logger.error("Error en review_historial_crm", extra={"error": str(exc)})
        return _format_error(function_name, str(exc))


def _validate_env_vars():
    required = ["SSM_SF_COOKIES_PATH"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        raise EnvironmentError(f"Variables de entorno faltantes: {missing}")


def _extraer_parametro(event: dict, nombre: str) -> str:
    for p in event.get("parameters", []):
        if p.get("name") == nombre:
            return p["value"]
    raise ValueError(f"Parametro requerido no encontrado: '{nombre}'")


def _process(sf_record_id: str) -> dict:
    # Import local para no bloquear tests sin Playwright instalado
    from src.tools.review_historial_crm.infrastructure.salesforce_case_scraper import (
        SalesforceCaseScraper,
    )

    scraper = SalesforceCaseScraper(
        ssm_cookies_path=os.environ["SSM_SF_COOKIES_PATH"],
    )
    return scraper.obtener_historial(sf_record_id)


def _format_response(function_name: str, historial: dict) -> dict:
    return {
        "actionGroup": _ACTION_GROUP,
        "function": function_name,
        "functionResponse": {
            "responseBody": {
                "TEXT": {
                    "body": json.dumps(
                        {"historial": historial},
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
