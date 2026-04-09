"""
Lambda Tool: sbc-admin-tool-classifier-lambda
Accion: Clasificar imagenes pendientes de un caso via Bedrock Vision y persistir en DynamoDB

Busca el registro en DynamoDB por su id, clasifica las imagenes que aun no tienen
document_type usando Bedrock Vision, guarda el resultado haciendo merge y retorna
el listado de imagenes clasificadas en esta ejecucion.

Parametros de entrada (Bedrock Action Group):
    id — identificador del registro en DynamoDB (partition key)

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
- cotizacion: Cotizacion o presupuesto de reparacion del vehiculo (de taller o proveedor)
- foto_danio: Fotografia de danios fisicos al vehiculo (abolladuras, rayones, roturas)
- otro: cualquier otro documento o imagen

Responde SOLO en JSON con este formato exacto:
{"tipo": "<categoria>", "confianza": "<alta|media|baja>", "razon": "<max 10 palabras>"}
"""


def lambda_handler(event, context):
    function_name = event.get("function", _FUNCTION_DEFAULT)
    action_group  = event.get("actionGroup", _ACTION_GROUP)

    logger.info("classifier entrada: %s", json.dumps(event, ensure_ascii=False, default=str))

    try:
        params    = _extraer_parametros(event, ["id"])
        record_id = params["id"]

        registro = _get_registro(record_id)
        date     = registro["date"]
        images   = registro.get("images", [])

        logger.info("registro obtenido", extra={
            "record_id":    record_id,
            "date":         date,
            "total_images": len(images),
        })

        nuevas_clasificadas = _clasificar_todas(images)
        totales = _process(record_id, date, nuevas_clasificadas)
        totales["imagenes"] = [
            {
                "nombre": img.get("nombre", ""),
                "tipo":   img.get("document_type", ""),
                "razon":  img.get("justification", ""),
            }
            for img in nuevas_clasificadas
        ]

        response = _format_response(function_name, record_id, totales, action_group)
        logger.info("classifier salida OK: %s", json.dumps(response, ensure_ascii=False, default=str))
        return response

    except Exception as exc:
        error_response = _format_error(function_name, str(exc), action_group)
        logger.error("classifier salida ERROR: %s", json.dumps(error_response, ensure_ascii=False, default=str), exc_info=True)
        return error_response


def _extraer_parametros(event: dict, nombres: list[str]) -> dict:
    params  = {p["name"]: p["value"] for p in event.get("parameters", [])}
    missing = [n for n in nombres if n not in params]
    if missing:
        raise ValueError(f"Parametros requeridos no encontrados: {missing}")
    return {n: params[n] for n in nombres}


def _get_registro(record_id: str) -> dict:
    from src.tools.sbc_admin_tool_classifier.infrastructure.dynamo_repository import ClassifierRepository
    return ClassifierRepository().get_registro_by_id(record_id)


def _clasificar_todas(imagenes: list[dict]) -> list[dict]:
    """Clasifica cada imagen via Bedrock Vision y retorna el array enriquecido."""
    model_id = os.environ.get("BEDROCK_MODEL_ID", _DEFAULT_MODEL)
    region   = os.environ.get("BEDROCK_REGION", _DEFAULT_REGION)
    bedrock  = boto3.client("bedrock-runtime", region_name=region)

    resultado = []
    for i, img in enumerate(imagenes):
        nombre = img.get("nombre", "")
        url    = img.get("url", "")
        logger.info("clasificando imagen", extra={
            "index":  i + 1,
            "total":  len(imagenes),
            "nombre": nombre,
        })
        try:
            clasificacion = _clasificar_imagen(bedrock, model_id, url, nombre)
            logger.info("imagen clasificada", extra={
                "nombre":    nombre,
                "tipo":      clasificacion.get("tipo"),
                "confianza": clasificacion.get("confianza"),
                "razon":     clasificacion.get("razon"),
            })
        except Exception as exc:
            logger.warning("error clasificando imagen", extra={
                "nombre": nombre,
                "error":  str(exc),
            }, exc_info=True)
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
    # El modelo a veces devuelve el JSON envuelto en ```json ... ```
    if texto.startswith("```"):
        lines = texto.splitlines()
        inner = [l for l in lines[1:] if l.strip() != "```"]
        texto = "\n".join(inner).strip()
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        return {"tipo": "otro", "confianza": "baja", "razon": texto[:50]}


def _process(record_id: str, date: str, imagenes: list[dict]) -> dict:
    from src.tools.sbc_admin_tool_classifier.infrastructure.dynamo_repository import ClassifierRepository
    return ClassifierRepository().update_imagenes(record_id=record_id, date=date, imagenes_clasificadas=imagenes)


def _format_response(function_name: str, record_id: str, totales: dict, action_group: str) -> dict:
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
                                "id":           record_id,
                                "total":        totales["total"],
                                "clasificadas": totales["clasificadas"],
                                "pendientes":   totales["pendientes"],
                                "imagenes":     totales["imagenes"],
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
