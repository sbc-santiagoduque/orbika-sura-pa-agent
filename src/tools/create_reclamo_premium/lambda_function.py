"""
Lambda Tool: create_reclamo_premium — Phase A: Recolección de datos
Acción: Recopilar todos los datos necesarios para abrir un reclamo en Premium.

Esta Lambda es el entry point del flujo RPA de apertura de reclamos.
NO abre el reclamo en Premium (eso es Phase B — Premium RPA).
Recolecta y estructura los datos desde SIC y Consulta Integral.

Entrada (event):
    {
        "case_number": "02195167",   — número de caso (requerido)
        "placa":       "XYZ123",     — placa del vehículo (requerido)
        "expediente":  "EXP001"      — expediente SIC (requerido)
    }

Salida (200):
    {
        "case_number": "02195167",
        "reclamo_data": {
            "numero_poliza": "...",
            "siniestro": {...},
            "conductor": {...},
            "poliza": {...},
            "ajustador_interno": 158
        }
    }

Variables de entorno requeridas:
    SSM_SIC_API_USERNAME_PATH  — ruta SSM del usuario SIC
    SSM_SIC_API_PASSWORD_PATH  — ruta SSM de la contraseña SIC
    SIC_API_BASE_URL           — URL base del SIC REST API

Variables opcionales:
    CI_BASE_URL                — URL de Consulta Integral (requiere VPN)
                                 Si no está presente, usa ConsultaIntegralScraperStub
    CI_STUB_POLIZA             — número de póliza fijo para el stub (desarrollo)
    CI_STUB_COBERTURA          — cobertura fija para el stub (desarrollo)
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

_ENV_REQUIRED = [
    "SSM_SIC_API_USERNAME_PATH",
    "SSM_SIC_API_PASSWORD_PATH",
    "SIC_API_BASE_URL",
]
_PARAMS_REQUIRED = ["case_number", "placa"]


def lambda_handler(event, context):
    try:
        _validate_env_vars()
        _validate_params(event)

        case_number = event["case_number"]
        placa       = event["placa"]
        expediente  = event.get("expediente", "")

        reclamo_data = _recolectar_datos(case_number, placa, expediente)

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "case_number":  case_number,
                    "reclamo_data": reclamo_data.to_dict(),
                },
                ensure_ascii=False,
            ),
        }

    except (ValueError, KeyError) as exc:
        logger.warning("Parámetro inválido en create_reclamo_premium", extra={"error": str(exc)})
        return {
            "statusCode": 400,
            "body": json.dumps({"error": str(exc)}, ensure_ascii=False),
        }
    except EnvironmentError as exc:
        logger.error("Variables de entorno faltantes", extra={"error": str(exc)})
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(exc)}, ensure_ascii=False),
        }
    except Exception as exc:
        logger.error("Error en create_reclamo_premium", extra={"error": str(exc)})
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(exc)}, ensure_ascii=False),
        }


def _validate_env_vars():
    missing = [v for v in _ENV_REQUIRED if not os.environ.get(v)]
    if missing:
        raise EnvironmentError(f"Variables de entorno faltantes: {missing}")


def _validate_params(event: dict):
    for param in _PARAMS_REQUIRED:
        if not event.get(param):
            raise ValueError(f"Parámetro requerido faltante: '{param}' (case_number y placa son obligatorios)")


def _recolectar_datos(case_number: str, placa: str, expediente: str):
    """Instancia dependencias y ejecuta la recolección de datos."""
    from src.shared.sic_api.sic_api_session import SICApiSession
    from src.tools.create_reclamo_premium.infrastructure.sic_reclamo_client import SICReclamoClient
    from src.tools.create_reclamo_premium.infrastructure.consulta_integral_scraper import (
        ConsultaIntegralScraper,
        ConsultaIntegralScraperStub,
    )
    from src.tools.create_reclamo_premium.service.data_collector import DataCollector

    session = SICApiSession(
        ssm_username_path=os.environ["SSM_SIC_API_USERNAME_PATH"],
        ssm_password_path=os.environ["SSM_SIC_API_PASSWORD_PATH"],
    )
    sic_client = SICReclamoClient(session=session)

    ci_base_url = os.environ.get("CI_BASE_URL")
    if ci_base_url:
        ci_scraper = ConsultaIntegralScraper(ci_base_url=ci_base_url)
    else:
        # Modo desarrollo: usar stub con datos fijos o desde env vars
        datos_stub = {}
        if os.environ.get("CI_STUB_POLIZA"):
            datos_stub["numero_poliza"] = os.environ["CI_STUB_POLIZA"]
        if os.environ.get("CI_STUB_COBERTURA"):
            datos_stub["cobertura"] = os.environ["CI_STUB_COBERTURA"]
        ci_scraper = ConsultaIntegralScraperStub(datos_fijos=datos_stub or None)
        logger.warning("CI_BASE_URL no configurada — usando ConsultaIntegralScraperStub")

    collector = DataCollector(sic_client=sic_client, ci_scraper=ci_scraper)
    return collector.recolectar(case_number, placa, expediente)
