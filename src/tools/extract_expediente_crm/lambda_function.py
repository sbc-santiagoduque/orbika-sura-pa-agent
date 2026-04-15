"""
Lambda Tool: extract_expediente_crm
Accion: F6-CRM — Extraer documentos adjuntos del caso desde Salesforce CRM

Invocada por el Agente Expediente (Bedrock Action Group).
Navega a la vista CombinedAttachments del caso y retorna la lista de
documentos con título, tipo, fecha y tamaño.

El output es compatible con validate_documentos: el campo imagen_count
refleja el total de adjuntos, permitiendo que la validacion de existencia
funcione sin cambios independientemente de si los documentos vienen del
SIC o del CRM.
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

_ACTION_GROUP = "agente-expediente-actions"


def lambda_handler(event, context):
    """
    Punto de entrada para Bedrock Action Group.

    El agente invoca esta función con:
    {
        "actionGroup": "agente-expediente-actions",
        "function": "extract_expediente_crm",
        "parameters": [
            {"name": "case_number", "type": "string", "value": "CF0975"}
        ]
    }
    """
    function_name = event.get("function", "extract_expediente_crm")

    try:
        _validate_env_vars()
        case_number = _extraer_parametro(event, "case_number")
        expediente = _process(case_number)
        return _format_response(function_name, expediente)

    except Exception as exc:
        logger.error("Error en extract_expediente_crm", extra={"error": str(exc)})
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


def _process(case_number: str) -> dict:
    # Import local para no bloquear tests sin Playwright instalado
    from src.tools.extract_expediente_crm.infrastructure.salesforce_attachments_scraper import (
        SalesforceAttachmentsScraper,
    )

    scraper = SalesforceAttachmentsScraper(
        ssm_cookies_path=os.environ["SSM_SF_COOKIES_PATH"],
        ssm_username_path=os.environ.get("SSM_SF_USERNAME_PATH"),
        ssm_password_path=os.environ.get("SSM_SF_PASSWORD_PATH"),
        sf_login_url=os.environ.get("SF_LOGIN_URL"),
    )
    return scraper.obtener_documentos(case_number)


def _format_response(function_name: str, expediente: dict) -> dict:
    return {
        "actionGroup": _ACTION_GROUP,
        "function": function_name,
        "functionResponse": {
            "responseBody": {
                "TEXT": {
                    "body": json.dumps(
                        {"expediente": expediente},
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
