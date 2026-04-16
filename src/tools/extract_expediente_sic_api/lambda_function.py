"""
Lambda Tool: extract_expediente_sic_api
Accion: F6 (API) — Extraer expediente del caso desde SIC via REST API

Recibe placa + expediente del orquestador Bedrock, consulta SIC para obtener
las imagenes del expediente especifico y actualiza el registro en DynamoDB.
Sin Playwright, sin storageState, login automatico en cada invocacion.

Parametros de entrada (Bedrock Action Group):
    placa      — placa del vehiculo asegurado
    expediente — numero de expediente (= eventRecord en SIC)

Variables de entorno requeridas:
    SSM_SIC_API_USERNAME_PATH  — ruta SSM del usuario SIC
    SSM_SIC_API_PASSWORD_PATH  — ruta SSM de la contrasena SIC
    SIC_API_BASE_URL           — URL base del SIC REST API
    DYNAMO_TABLE_NAME          — nombre de la tabla DynamoDB (default: sbc-admin-cases)
"""
import json
import logging
import os

logger = logging.getLogger(__name__)


def lambda_handler(event, context):
    function_name = event.get("function", "extract_expediente_sic_api")
    action_group  = event.get("actionGroup", "agente-expediente-actions")

    try:
        _validate_env_vars()
        placa      = _extraer_parametro(event, "placa")
        expediente = _extraer_parametro(event, "expediente")
        resultado  = _process(placa, expediente)
        return _format_response(function_name, action_group, resultado)

    except Exception as exc:
        logger.error("Error en extract_expediente_sic_api", extra={"error": str(exc)})
        return _format_error(function_name, action_group, str(exc))


def _validate_env_vars():
    required = [
        "SSM_SIC_API_USERNAME_PATH",
        "SSM_SIC_API_PASSWORD_PATH",
        "SIC_API_BASE_URL",
    ]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        raise EnvironmentError(f"Variables de entorno faltantes: {missing}")


def _extraer_parametro(event: dict, nombre: str) -> str:
    for p in event.get("parameters", []):
        if p.get("name") == nombre:
            return p["value"]
    raise ValueError(f"Parametro requerido no encontrado: '{nombre}'")


def _process(placa: str, expediente: str) -> dict:
    from src.shared.sic_api.sic_api_session import SICApiSession
    from src.tools.extract_expediente_sic_api.infrastructure.sic_api_client import SICApiClient
    from src.tools.extract_expediente_sic_api.infrastructure.dynamo_repository import AdminCasesRepository

    session = SICApiSession(
        ssm_username_path=os.environ["SSM_SIC_API_USERNAME_PATH"],
        ssm_password_path=os.environ["SSM_SIC_API_PASSWORD_PATH"],
    )
    client = SICApiClient(session=session)
    repo   = AdminCasesRepository()

    # 1. Buscar registro en DynamoDB
    registro = repo.find_by_plate_expediente(placa, expediente)

    # 2. Obtener imagenes desde SIC para ese expediente especifico
    imagenes = client.obtener_imagenes_por_expediente(placa, expediente)

    # 3. Actualizar imagenes en DynamoDB
    repo.update_images(
        record_id=registro["id"],
        date=registro["date"],
        images=imagenes,
    )

    return {
        "placa":       placa,
        "expediente":  expediente,
        "image_count": len(imagenes),
        "images":      imagenes,
    }


def _format_response(function_name: str, action_group: str, resultado: dict) -> dict:
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": action_group,
            "function": function_name,
            "functionResponse": {
                "responseBody": {
                    "TEXT": {
                        "body": json.dumps(resultado, ensure_ascii=False)
                    }
                }
            },
        },
    }


def _format_error(function_name: str, action_group: str, message: str) -> dict:
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": action_group,
            "function": function_name,
            "functionResponse": {
                "responseBody": {
                    "TEXT": {
                        "body": json.dumps({"error": message}, ensure_ascii=False)
                    }
                }
            },
        },
    }
