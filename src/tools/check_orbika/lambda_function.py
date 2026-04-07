"""
Lambda Tool: check_orbika
Accion: F8 — Consultar estado del aviso en Orbika

Invocada por el Agente Orbika (Bedrock Action Group).
Busca avisos por placa y retorna el mas reciente con campos relevantes
para la clasificacion de responsabilidad (F9).
"""
import json
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)


def lambda_handler(event, context):
    function_name = event.get("function", "check_orbika")
    try:
        _validate_env_vars()
        placa = _extraer_parametro(event, "placa")
        resultado = _process(placa)
        return _format_response(function_name, resultado)
    except Exception as exc:
        logger.error("Error en check_orbika", extra={"error": str(exc)})
        return _format_error(function_name, str(exc))


def _validate_env_vars():
    required = ["SSM_ORBIKA_SESSION_PATH"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        raise EnvironmentError(f"Variables de entorno faltantes: {missing}")


def _extraer_parametro(event: dict, nombre: str) -> str:
    for p in event.get("parameters", []):
        if p.get("name") == nombre:
            return p["value"]
    raise ValueError(f"Parametro requerido no encontrado: '{nombre}'")


def _process(placa: str) -> dict:
    from src.shared.orbika.orbika_session import OrbikaSession
    from src.tools.check_orbika.infrastructure.orbika_client import OrbikaClient

    session = OrbikaSession(ssm_session_path=os.environ["SSM_ORBIKA_SESSION_PATH"])
    client = OrbikaClient(session=session)
    avisos = client.listar_avisos(placa)

    aviso_reciente = _aviso_mas_reciente(avisos)

    return {
        "placa": placa,
        "tiene_aviso": len(avisos) > 0,
        "aviso_count": len(avisos),
        "aviso_reciente": _campos_relevantes(aviso_reciente) if aviso_reciente else None,
    }


def _aviso_mas_reciente(avisos: list) -> dict | None:
    if not avisos:
        return None
    def _fecha(a):
        try:
            return datetime.strptime(a.get("fecha_creacion_aviso", ""), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return datetime.min
    return max(avisos, key=_fecha)


def _campos_relevantes(aviso: dict) -> dict:
    return {
        "nro_aviso":            aviso.get("nro_aviso"),
        "estado":               aviso.get("estado"),
        "cobertura":            aviso.get("cobertura"),
        "especialidad":         aviso.get("especialidad"),
        "placa_asegurado":      aviso.get("placa_asegurado"),
        "placa_tercero":        aviso.get("placa_tercero"),
        "fecha_creacion_aviso": aviso.get("fecha_creacion_aviso"),
        "nombre_comercial":     aviso.get("nombre_comercial"),
        "valorador":            aviso.get("valorador"),
    }


def _format_response(function_name: str, resultado: dict) -> dict:
    return {
        "actionGroup": "agente-orbika-actions",
        "function": function_name,
        "functionResponse": {
            "responseBody": {
                "TEXT": {
                    "body": json.dumps({"orbika": resultado}, ensure_ascii=False)
                }
            }
        },
    }


def _format_error(function_name: str, message: str) -> dict:
    return {
        "actionGroup": "agente-orbika-actions",
        "function": function_name,
        "functionResponse": {
            "responseBody": {
                "TEXT": {
                    "body": json.dumps({"error": message}, ensure_ascii=False)
                }
            }
        },
    }
