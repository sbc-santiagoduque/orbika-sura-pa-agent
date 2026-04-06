"""
Lambda Tool: validate_documentos
Accion: F7 — Validar existencia (y futura clasificacion) de documentos del expediente

Estrategias configurables via VALIDATE_DOCS_STRATEGY:
  A (default): imagen_count > 0 -> documentos presentes. Sin dependencias externas.
  B (futura):  Bedrock Vision clasifica tipos de documento. Requiere BEDROCK_MODEL_ID.
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

_ENV_STRATEGY = "VALIDATE_DOCS_STRATEGY"
_ENV_BEDROCK_MODEL = "BEDROCK_MODEL_ID"


def lambda_handler(event, context):
    function_name = event.get("function", "validate_documentos")
    try:
        _validate_env_vars()
        expediente = _extraer_expediente(event)
        resultado = _process(expediente)
        return _format_response(function_name, resultado)
    except Exception as exc:
        logger.error("Error en validate_documentos", extra={"error": str(exc)})
        return _format_error(function_name, str(exc))


def _validate_env_vars():
    strategy = os.environ.get(_ENV_STRATEGY, "A")
    if strategy == "B" and not os.environ.get(_ENV_BEDROCK_MODEL):
        raise EnvironmentError(
            f"Variable de entorno requerida para estrategia B: {_ENV_BEDROCK_MODEL}"
        )


def _extraer_expediente(event: dict) -> dict:
    params = event.get("parameters", [])
    for p in params:
        if p.get("name") == "expediente":
            return json.loads(p["value"])
    raise ValueError("Parametro requerido no encontrado: 'expediente'")


def _process(expediente: dict) -> dict:
    from src.tools.validate_documentos.service.validate_service import ValidateDocumentosService
    from src.tools.validate_documentos.service.opcion_a_validator import OpcionAValidator
    from src.tools.validate_documentos.service.opcion_b_validator import OpcionBValidator

    strategy = os.environ.get(_ENV_STRATEGY, "A")

    if strategy == "B":
        validator = OpcionBValidator(model_id=os.environ[_ENV_BEDROCK_MODEL])
    else:
        validator = OpcionAValidator()

    return ValidateDocumentosService(validator=validator).validar(expediente)


def _format_response(function_name: str, resultado: dict) -> dict:
    return {
        "actionGroup": "agente-expediente-actions",
        "function": function_name,
        "functionResponse": {
            "responseBody": {
                "TEXT": {
                    "body": json.dumps({"validacion": resultado}, ensure_ascii=False)
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
