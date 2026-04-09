"""
Lambda Tool: sbc-admin-tool-classifier-lambda
Accion: Clasificar imagenes pendientes de un caso via Bedrock Vision y persistir en DynamoDB

Busca el registro del caso en DynamoDB, clasifica las imagenes que aun no tienen
document_type usando Bedrock Vision, y guarda el resultado haciendo merge.

Parametros de entrada (Bedrock Action Group):
    caso — numero de caso (partition key DynamoDB)

Variables de entorno requeridas:
    DYNAMO_TABLE_NAME — nombre de la tabla DynamoDB (default: sbc-admin-cases)
    BEDROCK_MODEL_ID  — model ID de Bedrock Vision (default: amazon.nova-lite-v1:0)
    BEDROCK_REGION    — region de Bedrock (default: us-east-1)
"""
import json
import logging
import os
import urllib.request

import boto3

logger = logging.getLogger(__name__)

_ACTION_GROUP     = "sbc-admin-tool-actions"
_FUNCTION_DEFAULT = "sbc-admin-tool-classifier-lambda"
_DEFAULT_MODEL    = "amazon.nova-lite-v1:0"
_DEFAULT_REGION   = "us-east-1"

_PROMPT_CLASIFICACION = """Eres un asistente especializado en siniestros de vehiculos en Panama.
Analiza esta imagen. Si contiene texto, leelo para identificar el tipo de documento.

Clasifica la imagen en UNA de las siguientes categorias:

- fud: Formato Unico de Denuncia (formulario policial de accidente de transito)
- resolucion: Resolucion oficial de autoridad (MOP, ATTT, policia, etc.)
- ruv: Registro Unico Vehicular (documento oficial de registro del vehiculo)
- foto_danio: Fotografia de danios fisicos al vehiculo (abolladuras, rayones, roturas)
- otro: cualquier otro documento o imagen

Responde SOLO en JSON con este formato exacto:
{"tipo": "<categoria>", "confianza": "<alta|media|baja>", "razon": "<max 10 palabras>"}
"""


def lambda_handler(event, context):
    function_name = event.get("function", _FUNCTION_DEFAULT)
    action_group  = event.get("actionGroup", _ACTION_GROUP)

    try:
        params = _extraer_parametros(event, ["caso"])
        caso   = params["caso"]

        registro  = _get_registro(caso)
        date      = registro["date"]
        imagenes  = registro.get("imagenes", [])
        pendientes = [img for img in imagenes if not img.get("document_type")]

        if not pendientes:
            total = len(imagenes)
            return _format_response(function_name, caso, {
                "total": total, "clasificadas": 0, "pendientes": 0
            }, action_group)

        clasificadas  = _clasificar_todas(pendientes)
        totales       = _process(caso, date, clasificadas)

        return _format_response(function_name, caso, totales, action_group)

    except Exception as exc:
        logger.error("Error en sbc-admin-tool-classifier-lambda", extra={"error": str(exc)})
        return _format_error(function_name, str(exc), action_group)


def _extraer_parametros(event: dict, nombres: list[str]) -> dict:
    params  = {p["name"]: p["value"] for p in event.get("parameters", [])}
    missing = [n for n in nombres if n not in params]
    if missing:
        raise ValueError(f"Parametros requeridos no encontrados: {missing}")
    return {n: params[n] for n in nombres}


def _get_registro(caso: str) -> dict:
    from src.tools.sbc_admin_tool_classifier.infrastructure.dynamo_repository import ClassifierRepository
    return ClassifierRepository().get_registro_by_caso(caso)


def _clasificar_todas(imagenes: list[dict]) -> list[dict]:
    """Clasifica cada imagen via Bedrock Vision y retorna el array enriquecido."""
    model_id = os.environ.get("BEDROCK_MODEL_ID", _DEFAULT_MODEL)
    region   = os.environ.get("BEDROCK_REGION", _DEFAULT_REGION)
    bedrock  = boto3.client("bedrock-runtime", region_name=region)

    resultado = []
    for img in imagenes:
        nombre = img.get("nombre", "")
        url    = img.get("url", "")
        try:
            clasificacion = _clasificar_imagen(bedrock, model_id, url, nombre)
        except Exception as exc:
            logger.warning(f"No se pudo clasificar '{nombre}': {exc}")
            clasificacion = {
                "tipo":      "otro",
                "confianza": "baja",
                "razon":     f"Error al clasificar: {str(exc)[:50]}",
            }

        resultado.append({
            **img,
            "document_type": clasificacion.get("tipo",      "otro"),
            "confidence":    clasificacion.get("confianza", "baja"),
            "justification": clasificacion.get("razon",     ""),
        })

    return resultado


def _clasificar_imagen(bedrock, model_id: str, url: str, nombre: str) -> dict:
    """Descarga la imagen y la clasifica via Bedrock Vision.
    Los PDFs no se pueden analizar como imagen — se marcan como otro."""
    url = "".join(url.split())  # elimina espacios y saltos de linea embebidos
    if nombre.lower().endswith(".pdf"):
        return {"tipo": "otro", "confianza": "alta", "razon": "Archivo PDF no analizable como imagen"}

    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=15) as resp:
        image_bytes = resp.read()

    url_lower = url.lower().split("?")[0]
    if url_lower.endswith(".png"):
        fmt = "png"
    elif url_lower.endswith(".gif"):
        fmt = "gif"
    elif url_lower.endswith(".webp"):
        fmt = "webp"
    else:
        fmt = "jpeg"

    response = bedrock.converse(
        modelId=model_id,
        messages=[{
            "role": "user",
            "content": [
                {"image": {"format": fmt, "source": {"bytes": image_bytes}}},
                {"text": _PROMPT_CLASIFICACION},
            ],
        }],
    )

    texto = response["output"]["message"]["content"][0]["text"].strip()
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        return {"tipo": "otro", "confianza": "baja", "razon": texto[:50]}


def _process(caso: str, date: str, imagenes: list[dict]) -> dict:
    from src.tools.sbc_admin_tool_classifier.infrastructure.dynamo_repository import ClassifierRepository
    return ClassifierRepository().update_imagenes(caso=caso, date=date, imagenes_clasificadas=imagenes)


def _format_response(function_name: str, caso: str, totales: dict, action_group: str) -> dict:
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": action_group,
            "function": function_name,
            "functionResponse": {
                "responseBody": {
                    "TEXT": {
                        "body": json.dumps(
                            {
                                "status":       "ok",
                                "caso":         caso,
                                "total":        totales["total"],
                                "clasificadas": totales["clasificadas"],
                                "pendientes":   totales["pendientes"],
                            },
                            ensure_ascii=False,
                        )
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
