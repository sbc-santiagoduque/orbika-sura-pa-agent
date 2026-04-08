"""
Lambda Tool: extract_expediente_sic_api
Accion: F6 (API) — Extraer expediente del caso desde SIC via REST API

Implementacion alternativa a extract_expediente_sic (Playwright).
Usa el SIC REST API directamente: auth JWT -> busqueda por placa -> imagenes.
Sin Playwright, sin storageState, login automatico en cada invocacion.

Variables de entorno requeridas:
    SSM_SIC_API_USERNAME_PATH  — ruta SSM del usuario SIC
    SSM_SIC_API_PASSWORD_PATH  — ruta SSM de la contrasena SIC
"""
import json
import logging
import os

logger = logging.getLogger(__name__)


def lambda_handler(event, context):
    function_name = event.get("function", "extract_expediente_sic_api")

    try:
        _validate_env_vars()
        placa = _extraer_parametro(event, "placa")
        expediente = _process(placa)
        return _format_response(function_name, expediente)

    except Exception as exc:
        logger.error("Error en extract_expediente_sic_api", extra={"error": str(exc)})
        return _format_error(function_name, str(exc))


def _validate_env_vars():
    required = ["SSM_SIC_API_USERNAME_PATH", "SSM_SIC_API_PASSWORD_PATH"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        raise EnvironmentError(f"Variables de entorno faltantes: {missing}")


def _extraer_parametro(event: dict, nombre: str) -> str:
    for p in event.get("parameters", []):
        if p.get("name") == nombre:
            return p["value"]
    raise ValueError(f"Parametro requerido no encontrado: '{nombre}'")


def _process(placa: str) -> dict:
    from src.shared.sic_api.sic_api_session import SICApiSession
    from src.tools.extract_expediente_sic_api.infrastructure.sic_api_client import SICApiClient

    session = SICApiSession(
        ssm_username_path=os.environ["SSM_SIC_API_USERNAME_PATH"],
        ssm_password_path=os.environ["SSM_SIC_API_PASSWORD_PATH"],
    )
    client = SICApiClient(session=session)
    return client.obtener_expediente(placa)


def _format_response(function_name: str, expediente: dict) -> dict:
    return {
        "actionGroup": "agente-expediente-actions",
        "function": function_name,
        "functionResponse": {
            "responseBody": {
                "TEXT": {
                    "body": json.dumps({"expediente": expediente}, ensure_ascii=False)
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
                    "body": json.dumps({"error": message}, ensure_ascii=False)
                }
            }
        },
    }
