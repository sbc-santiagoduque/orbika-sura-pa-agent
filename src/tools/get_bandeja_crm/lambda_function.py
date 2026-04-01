"""
Lambda Tool: get_bandeja_crm
Acción: F1 — Obtener bandeja CRM de Salesforce

Invocada por el Agente Ingesta (Bedrock Action Group).
Retorna los casos activos priorizados listos para procesar.
"""
import json
import logging
import os

from src.tools.get_bandeja_crm.service.bandeja_service import BandejaService

logger = logging.getLogger(__name__)

# Bedrock Action Group espera esta firma exacta
def lambda_handler(event, context):
    """
    Punto de entrada para Bedrock Action Group.

    El agente invoca esta función con:
    {
        "actionGroup": "agente-ingesta-actions",
        "function": "get_bandeja_crm",
        "parameters": []  # sin parámetros — lee la bandeja completa
    }
    """
    action_group = event.get("actionGroup", "")
    function_name = event.get("function", "")

    logger.info("get_bandeja_crm invocada", extra={
        "action_group": action_group,
        "function": function_name,
    })

    try:
        _validate_env_vars()
        resultado = _process()
        return _format_response(function_name, resultado)

    except Exception as exc:
        logger.error("Error en get_bandeja_crm", extra={"error": str(exc)})
        return _format_error(function_name, str(exc))


def _validate_env_vars():
    """Valida que las variables de entorno requeridas estén presentes."""
    required = ["SSM_SF_COOKIES_PATH", "SF_BASE_URL"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        raise EnvironmentError(f"Variables de entorno faltantes: {missing}")


def _process() -> list[dict]:
    """Scrapea Salesforce y retorna la bandeja priorizada."""
    # Import local para que el módulo sea importable sin playwright instalado en tests
    from src.tools.get_bandeja_crm.infrastructure.salesforce_scraper import SalesforceScraper
    scraper = SalesforceScraper(
        ssm_cookies_path=os.environ["SSM_SF_COOKIES_PATH"],
        base_url=os.environ["SF_BASE_URL"],
    )
    casos_raw = scraper.obtener_bandeja()

    service = BandejaService()
    return service.priorizar(casos_raw)


def _format_response(function_name: str, casos: list[dict]) -> dict:
    """
    Formato de respuesta que espera Bedrock Action Group.
    https://docs.aws.amazon.com/bedrock/latest/userguide/agents-lambda.html
    """
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
    """Respuesta de error en formato Bedrock Action Group."""
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
