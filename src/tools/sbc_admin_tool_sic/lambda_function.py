"""
Lambda Tool: sbc-admin-tool-sic-lambda
Accion: Obtener imagenes SIC y persistir caso en DynamoDB

Recibe los datos del caso, busca en SIC el expediente que coincide con
la placa dada, retorna las imagenes y persiste el registro en DynamoDB.

Parametros de entrada (Bedrock Action Group):
    caso        — numero de caso
    placa       — placa del vehiculo asegurado
    expediente  — numero de expediente (= eventRecord en SIC)
    siniestro   — numero de siniestro

Salida:
    JSON con placa, caso, expediente, siniestro, imagen_count e imagenes.
    El mismo registro queda persistido en la tabla DynamoDB sbc-admin-cases.

Variables de entorno requeridas:
    SIC_API_BASE_URL   — URL base del SIC REST API
    SIC_API_USERNAME   — usuario SIC
    SIC_API_PASSWORD   — contrasena SIC
    DYNAMO_TABLE_NAME  — nombre de la tabla DynamoDB (default: sbc-admin-cases)
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

_ACTION_GROUP     = "sbc-admin-tool-actions"
_FUNCTION_DEFAULT = "sbc-admin-tool-sic-lambda"
_PARAMS_REQUERIDOS = ["caso", "placa", "expediente", "siniestro"]


def lambda_handler(event, context):
    function_name = event.get("function", _FUNCTION_DEFAULT)
    action_group = event.get("actionGroup", _ACTION_GROUP)

    try:
        _validate_env_vars()
        params = _extraer_parametros(event, _PARAMS_REQUERIDOS)
        resultado = _process(**params)
        return _format_response(function_name, resultado, action_group)

    except Exception as exc:
        logger.error("Error en sbc-admin-tool-sic-lambda", extra={"error": str(exc)})
        return _format_error(function_name, str(exc), action_group)


def _validate_env_vars():
    required = ["SIC_API_BASE_URL", "SIC_API_USERNAME", "SIC_API_PASSWORD"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        raise EnvironmentError(f"Variables de entorno faltantes: {missing}")


def _extraer_parametros(event: dict, nombres: list[str]) -> dict:
    params = {p["name"]: p["value"] for p in event.get("parameters", [])}
    missing = [n for n in nombres if n not in params]
    if missing:
        raise ValueError(f"Parametros requeridos no encontrados: {missing}")
    return {n: params[n] for n in nombres}


def _process(caso: str, placa: str, expediente: str, siniestro: str) -> dict:
    from src.tools.sbc_admin_tool_sic.infrastructure.sic_images_client import SicImagesClient
    from src.tools.sbc_admin_tool_sic.infrastructure.dynamo_repository import AdminCasesRepository

    imagenes = SicImagesClient().obtener_imagenes(placa=placa, expediente=expediente)

    AdminCasesRepository().save(
        caso=caso,
        placa=placa,
        expediente=expediente,
        siniestro=siniestro,
        imagenes=imagenes,
    )

    return {
        "caso":         caso,
        "placa":        placa,
        "expediente":   expediente,
        "siniestro":    siniestro,
        "imagen_count": len(imagenes),
        "imagenes":     imagenes,
    }


def _format_response(function_name: str, resultado: dict, action_group: str) -> dict:
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


def _format_error(function_name: str, message: str, action_group: str) -> dict:
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
