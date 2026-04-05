"""
Lambda Tool: get_bandeja_crm
Acción: F1 — Obtener lista de casos del reporte de Salesforce

Invocada por el Agente Ingesta (Bedrock Action Group).
Retorna los casos en el orden del reporte — Sura Panamá define la prioridad
configurando el reporte directamente en Salesforce.
"""
import json
import logging
import os

logger = logging.getLogger(__name__)


def lambda_handler(event, context):
    """
    Punto de entrada para Bedrock Action Group.

    El agente invoca esta función con:
    {
        "actionGroup": "agente-ingesta-actions",
        "function": "get_bandeja_crm",
        "parameters": []
    }
    """
    function_name = event.get("function", "get_bandeja_crm")

    logger.info("get_bandeja_crm invocada", extra={
        "action_group": event.get("actionGroup"),
    })

    try:
        _validate_env_vars()
        casos = _process()
        return _format_response(function_name, casos)

    except Exception as exc:
        logger.error("Error en get_bandeja_crm", extra={"error": str(exc)})
        return _format_error(function_name, str(exc))


def _validate_env_vars():
    required = ["SSM_SF_COOKIES_PATH", "SF_REPORT_URL"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        raise EnvironmentError(f"Variables de entorno faltantes: {missing}")


def _process() -> list[dict]:
    # Import local para no bloquear tests sin Playwright instalado
    from src.tools.get_bandeja_crm.infrastructure.salesforce_scraper import SalesforceScraper

    scraper = SalesforceScraper(
        ssm_cookies_path=os.environ["SSM_SF_COOKIES_PATH"],
        report_url=os.environ["SF_REPORT_URL"],
    )
    return scraper.obtener_bandeja()


def _format_response(function_name: str, casos: list[dict]) -> dict:
    return {
        "actionGroup": "agente-ingesta-actions",
        "function": function_name,
        "functionResponse": {
            "responseBody": {
                "TEXT": {
                    "body": json.dumps({
                        "casos": casos,
                        "total": len(casos),
                    }, ensure_ascii=False)
                }
            }
        }
    }


def _format_error(function_name: str, message: str) -> dict:
    return {
        "actionGroup": "agente-ingesta-actions",
        "function": function_name,
        "functionResponse": {
            "responseBody": {
                "TEXT": {
                    "body": json.dumps({
                        "error": message,
                        "casos": [],
                        "total": 0,
                    }, ensure_ascii=False)
                }
            }
        }
    }
