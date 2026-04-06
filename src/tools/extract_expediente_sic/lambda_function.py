"""
Lambda Tool: extract_expediente_sic
Accion: F6 — Extraer expediente del caso desde SIC

Invocada por el Agente Expediente (Bedrock Action Group).
Busca por placa, navega al expediente y retorna conteo de imagenes
y URLs S3 para validacion de documentos (Opcion A) y futura
clasificacion por vision (Opcion B).
"""
import json
import logging
import os

logger = logging.getLogger(__name__)


def lambda_handler(event, context):
    function_name = event.get("function", "extract_expediente_sic")

    try:
        _validate_env_vars()
        placa = _extraer_parametro(event, "placa")
        expediente = _process(placa)
        return _format_response(function_name, expediente)

    except Exception as exc:
        logger.error("Error en extract_expediente_sic", extra={"error": str(exc)})
        return _format_error(function_name, str(exc))


def _validate_env_vars():
    required = ["SSM_SIC_STATE_PATH", "SSM_SIC_USERNAME_PATH", "SSM_SIC_PASSWORD_PATH"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        raise EnvironmentError(f"Variables de entorno faltantes: {missing}")


def _extraer_parametro(event: dict, nombre: str) -> str:
    """Extrae un parámetro del formato Bedrock Action Group."""
    params = event.get("parameters", [])
    for p in params:
        if p.get("name") == nombre:
            return p["value"]
    raise ValueError(f"Parametro requerido no encontrado: '{nombre}'")


def _process(placa: str) -> dict:
    # Import local para no bloquear tests sin Playwright
    from src.shared.browser.sic_session import SICSession
    from src.tools.extract_expediente_sic.infrastructure.sic_scraper import SICScraper

    session = SICSession(
        ssm_state_path=os.environ["SSM_SIC_STATE_PATH"],
        ssm_username_path=os.environ["SSM_SIC_USERNAME_PATH"],
        ssm_password_path=os.environ["SSM_SIC_PASSWORD_PATH"],
    )
    scraper = SICScraper(session=session)
    return scraper.obtener_expediente(placa)


def _format_response(function_name: str, expediente: dict) -> dict:
    return {
        "actionGroup": "agente-expediente-actions",
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
        "actionGroup": "agente-expediente-actions",
        "function": function_name,
        "functionResponse": {
            "responseBody": {
                "TEXT": {
                    "body": json.dumps(
                        {"error": message},
                        ensure_ascii=False,
                    )
                }
            }
        },
    }
