"""
Smoke test Vision B via SIC API (sin Playwright).

Flujo:
  1. Auth SIC API + datos usuario + busqueda por placa (4 requests HTTP)
  2. Captura imagen URLs firmadas del evento mas reciente
  3. Descarga las primeras N imagenes y las envia a Bedrock Vision
  4. Imprime clasificacion por imagen + resumen de tokens

Uso:
    python scripts/smoke_test_vision_b_api.py --placa 422644
    python scripts/smoke_test_vision_b_api.py --placa 422644 --model amazon.nova-lite-v1:0 --n 5

Lee credenciales desde .env en la raiz del proyecto.
Requiere: AWS_PROFILE o credenciales en entorno para Bedrock.
"""
import argparse
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock


def _load_env():
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        print(f"FAIL: no se encontro .env en {env_path}")
        sys.exit(1)
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


_load_env()
sys.path.insert(0, str(Path(__file__).parent.parent))

import boto3
import requests

from src.shared.sic_api.sic_api_session import SICApiSession
from src.tools.extract_expediente_sic_api.infrastructure.sic_api_client import SICApiClient


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

_DOCS_OBLIGATORIOS = {"fud", "resolucion", "ruv", "foto_danio"}


def _session_desde_env() -> SICApiSession:
    username = os.environ.get("SIC_USERNAME")
    password = os.environ.get("SIC_PASSWORD")
    if not username or not password:
        print("FAIL: SIC_USERNAME / SIC_PASSWORD no en .env")
        sys.exit(1)
    mock_ssm = MagicMock()
    mock_ssm.get_parameter.side_effect = [
        {"Parameter": {"Value": username}},
        {"Parameter": {"Value": password}},
    ]
    return SICApiSession(
        ssm_username_path="/local/username",
        ssm_password_path="/local/password",
        ssm_client=mock_ssm,
    )


def _obtener_signed_urls(placa: str) -> tuple[str, list[dict]]:
    """
    Llama al SICApiClient y retorna (evento_id, imagenes).
    imagenes = [{"nombre": str, "url": str, "seccion_id": int}, ...]
    """
    session = _session_desde_env()
    client  = SICApiClient(session=session)

    print(f"[SIC API] Obteniendo expediente para placa {placa}...")
    expediente = client.obtener_expediente(placa)

    evento_id = expediente.get("evento_id")
    imagenes  = expediente.get("imagenes", [])
    fecha     = expediente.get("fecha_evento", "?")

    if not evento_id:
        print(f"[SIC API] Sin eventos para placa {placa}")
        return "", []

    print(f"[SIC API] Evento mas reciente: {evento_id} ({fecha})")
    print(f"[SIC API] {len(imagenes)} imagen(es) encontradas")
    return evento_id, imagenes


def _clasificar_imagen(bedrock, model_id: str, url: str) -> tuple[str, dict]:
    """Descarga la imagen y la clasifica via Bedrock Vision."""
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    image_bytes = resp.content

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
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "image": {
                            "format": fmt,
                            "source": {"bytes": image_bytes},
                        }
                    },
                    {"text": _PROMPT_CLASIFICACION},
                ],
            }
        ],
    )
    texto = response["output"]["message"]["content"][0]["text"].strip()
    usage = response.get("usage", {})
    return texto, {
        "input":  usage.get("inputTokens", 0),
        "output": usage.get("outputTokens", 0),
        "total":  usage.get("totalTokens", 0),
    }


def main(placa: str, model_id: str, n: int, aws_profile: str):
    print(f"=== Smoke test Vision B (API) | placa={placa} | model={model_id} | n={n} ===")
    print()

    # 1. Obtener URLs firmadas desde SIC API
    evento_id, imagenes = _obtener_signed_urls(placa)
    if not imagenes:
        print("Sin imagenes — terminando.")
        return

    imagenes_a_probar = imagenes[:n]

    # 2. Inicializar cliente Bedrock
    session = boto3.Session(profile_name=aws_profile) if aws_profile else boto3.Session()
    bedrock = session.client("bedrock-runtime", region_name="us-east-1")

    # 3. Clasificar cada imagen
    print(f"\n[Bedrock] Clasificando {len(imagenes_a_probar)} imagen(es) con {model_id}...")
    print()

    resultados      = []
    tokens_total    = {"input": 0, "output": 0, "total": 0}

    for i, img in enumerate(imagenes_a_probar):
        nombre = img["nombre"]
        url    = img["url"]
        try:
            raw, usage = _clasificar_imagen(bedrock, model_id, url)
            tokens_total["input"]  += usage["input"]
            tokens_total["output"] += usage["output"]
            tokens_total["total"]  += usage["total"]
            try:
                parsed = json.loads(raw)
                tipo      = parsed.get("tipo", "?")
                confianza = parsed.get("confianza", "?")
                razon     = parsed.get("razon", "")
            except json.JSONDecodeError:
                tipo, confianza, razon = raw, "?", ""
                parsed = {"tipo": tipo}
            resultados.append({"imagen": nombre, "seccion_id": img.get("seccion_id"), **parsed})
            print(f"  [{i+1}] {nombre}  (seccion={img.get('seccion_id')})")
            print(f"       -> {tipo} ({confianza}) — {razon}")
            print(f"       tokens: in={usage['input']} out={usage['output']}")
        except Exception as e:
            print(f"  [{i+1}] {nombre}")
            print(f"       -> ERROR: {e}")
            resultados.append({"imagen": nombre, "tipo": "error", "error": str(e)})

    tipos_encontrados = {r.get("tipo") for r in resultados if r.get("tipo") not in ("error", None)}

    print()
    print("=== Resumen clasificacion ===")
    for r in resultados:
        print(f"  {r['imagen']}: {r.get('tipo', '?')}")

    print()
    print("=== Documentos obligatorios (sobre muestra de imagenes) ===")
    for doc in sorted(_DOCS_OBLIGATORIOS):
        estado = "OK" if doc in tipos_encontrados else "NO detectado en muestra"
        print(f"  {doc}: {estado}")

    print()
    print("=== Tokens consumidos ===")
    print(f"  Input:  {tokens_total['input']:,}")
    print(f"  Output: {tokens_total['output']:,}")
    print(f"  Total:  {tokens_total['total']:,}")
    print(f"  Promedio por imagen: {tokens_total['total'] // max(len(resultados), 1):,}")
    if len(imagenes) > len(resultados):
        extrap = tokens_total["total"] * len(imagenes) // len(resultados)
        print(f"  Extrapolado a {len(imagenes)} imagenes: ~{extrap:,} tokens")

    print()
    print(f"NOTA: Se analizaron {len(resultados)} de {len(imagenes)} imagenes del evento {evento_id}.")
    print("      Para validacion completa usar --n <total>")
    print()
    print("Smoke test Vision B (API) completado.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--placa", required=True, help="Placa a buscar en SIC")
    parser.add_argument(
        "--model",
        default="amazon.nova-lite-v1:0",
        help="Model ID de Bedrock (default: amazon.nova-lite-v1:0)",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=3,
        help="Numero de imagenes a clasificar (default: 3)",
    )
    parser.add_argument(
        "--profile",
        default=os.environ.get("AWS_PROFILE", "orbika-admin-panama-agent"),
        help="AWS profile (default: orbika-admin-panama-agent)",
    )
    args = parser.parse_args()
    main(args.placa, args.model, args.n, args.profile)
