"""
Smoke test Opcion B: valida clasificacion de documentos via Bedrock Vision.

Flujo:
  1. Login SIC + busqueda por placa (igual que smoke_test_sic.py)
  2. Captura imagen_urls_signed del expediente mas reciente
  3. Descarga las primeras N imagenes y las envia a Bedrock
  4. Imprime clasificacion por imagen

Uso:
    python scripts/smoke_test_vision_b.py --placa CU7559
    python scripts/smoke_test_vision_b.py --placa CU7559 --model amazon.nova-lite-v1:0 --n 5

Lee credenciales desde .env en la raiz del proyecto.
Requiere: AWS_PROFILE o credenciales en entorno para Bedrock.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

_MESES_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}
_RE_FECHA_ES = re.compile(
    r'(\d{1,2})\s+(' + '|'.join(_MESES_ES) + r')[,\s]+(\d{4})',
    re.IGNORECASE,
)
_RE_FECHA_NUM = re.compile(r'\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2}')


def _parsear_fecha(texto):
    m = _RE_FECHA_ES.search(texto)
    if m:
        return datetime(int(m.group(3)), _MESES_ES[m.group(2).lower()], int(m.group(1)))
    m = _RE_FECHA_NUM.search(texto)
    if m:
        for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(m.group(), fmt)
            except ValueError:
                continue
    return None


def _idx_mas_reciente(filas) -> int:
    mejor_idx, mejor_fecha = 0, None
    for i, fila in enumerate(filas):
        for celda in fila.query_selector_all("td"):
            fecha = _parsear_fecha(celda.inner_text().strip())
            if fecha and (mejor_fecha is None or fecha > mejor_fecha):
                mejor_fecha = fecha
                mejor_idx = i
    return mejor_idx


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

import boto3
import requests
from playwright.sync_api import sync_playwright

SIC_BASE_URL = os.environ.get("SIC_URL", "https://sic.connectasistencia.com")
SIC_SEARCH_URL = f"{SIC_BASE_URL}/events-claims"

_SEL_USERNAME    = "input#username"
_SEL_PASSWORD    = "input#password"
_SEL_SUBMIT      = "button[type='submit']"
_SEL_FILTER_COMBO = "div[role='combobox']"
_SEL_PLATE_INPUT  = "input[placeholder='Buscar Placa Asegurado']"
_SEL_RESULT_ROWS  = "table[aria-label='simple table'] tbody tr"
_SEL_GALLERY_IMG  = "img[src*='amazonaws']"

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


def _obtener_signed_urls(placa: str) -> list[str]:
    """Corre el flujo SIC completo y retorna imagen_urls_signed."""
    username = os.environ.get("SIC_USERNAME")
    password = os.environ.get("SIC_PASSWORD")
    if not username or not password:
        print("FAIL: SIC_USERNAME o SIC_PASSWORD no encontrados en .env")
        sys.exit(1)

    print(f"[SIC] Login como {username}...")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        page.goto(SIC_BASE_URL, wait_until="domcontentloaded")
        page.wait_for_selector(_SEL_USERNAME, timeout=10_000)
        page.fill(_SEL_USERNAME, username)
        page.fill(_SEL_PASSWORD, password)
        page.click(_SEL_SUBMIT)
        page.wait_for_url(
            lambda url: url.rstrip("/") != SIC_BASE_URL.rstrip("/"),
            timeout=15_000,
        )
        print(f"[SIC] Login OK. Buscando placa {placa}...")

        page.goto(SIC_SEARCH_URL, wait_until="domcontentloaded")
        page.wait_for_selector(_SEL_FILTER_COMBO, timeout=10_000)
        page.click(_SEL_FILTER_COMBO)
        page.wait_for_selector("li[role='option']:has-text('Placa Asegurado')", timeout=5_000)
        page.click("li[role='option']:has-text('Placa Asegurado')")
        page.wait_for_selector(_SEL_PLATE_INPUT, timeout=5_000)
        page.fill(_SEL_PLATE_INPUT, placa)
        page.press(_SEL_PLATE_INPUT, "Enter")

        page.wait_for_selector(_SEL_RESULT_ROWS, timeout=10_000)
        page.wait_for_timeout(4_000)  # dejar que React conecte listeners de ventana

        filas = page.query_selector_all(_SEL_RESULT_ROWS)
        idx = _idx_mas_reciente(filas)
        print(f"[SIC] Abriendo fila {idx} (la mas reciente)...")

        # Retry: a veces el listener de nueva ventana no esta listo en el primer click
        exp = None
        for intento in range(3):
            try:
                with context.expect_page(timeout=8_000) as new_page_info:
                    page.locator(_SEL_RESULT_ROWS).nth(idx).click()
                exp = new_page_info.value
                break
            except Exception:
                print(f"[SIC] Reintento {intento + 1}/3 apertura expediente...")
                page.wait_for_timeout(2_000)
        if exp is None:
            raise RuntimeError("No se pudo abrir el expediente en 3 intentos")
        exp.wait_for_load_state("domcontentloaded")
        # Navegar al tab Inspeccion — el expediente abre en el paso actual del flujo
        exp.wait_for_selector("button[role='tab']:has-text('Inspección')", timeout=10_000)
        exp.click("button[role='tab']:has-text('Inspección')")
        exp.wait_for_selector(_SEL_GALLERY_IMG, timeout=30_000, state="attached")

        imgs = exp.query_selector_all(_SEL_GALLERY_IMG)
        signed_urls = [img.get_attribute("src") for img in imgs if img.get_attribute("src")]
        browser.close()

    print(f"[SIC] {len(signed_urls)} imagenes encontradas.")
    return signed_urls


def _clasificar_imagen(bedrock, model_id: str, signed_url: str) -> tuple[str, dict]:
    """Descarga la imagen y la clasifica via Bedrock Vision.
    Retorna (texto_respuesta, usage) donde usage = {input, output, total tokens}.
    """
    resp = requests.get(signed_url, timeout=15)
    resp.raise_for_status()
    image_bytes = resp.content

    url_lower = signed_url.lower()
    if ".png" in url_lower:
        fmt = "png"
    elif ".gif" in url_lower:
        fmt = "gif"
    elif ".webp" in url_lower:
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
    print(f"=== Smoke test Vision B | placa={placa} | model={model_id} | n={n} ===")
    print()

    # 1. Obtener URLs firmadas desde SIC
    signed_urls = _obtener_signed_urls(placa)
    urls_a_probar = signed_urls[:n]

    # 2. Inicializar cliente Bedrock
    session = boto3.Session(profile_name=aws_profile) if aws_profile else boto3.Session()
    bedrock = session.client("bedrock-runtime", region_name="us-east-1")

    # 3. Clasificar cada imagen
    print(f"\n[Bedrock] Clasificando {len(urls_a_probar)} imagen(es) con {model_id}...")
    print()

    resultados = []
    tokens_total = {"input": 0, "output": 0, "total": 0}

    for i, url in enumerate(urls_a_probar):
        nombre = url.split("?")[0].split("/")[-1]
        try:
            raw, usage = _clasificar_imagen(bedrock, model_id, url)
            tokens_total["input"]  += usage["input"]
            tokens_total["output"] += usage["output"]
            tokens_total["total"]  += usage["total"]
            try:
                parsed = json.loads(raw)
                tipo = parsed.get("tipo", "?")
                confianza = parsed.get("confianza", "?")
                razon = parsed.get("razon", "")
            except json.JSONDecodeError:
                tipo, confianza, razon = raw, "?", ""
                parsed = {"tipo": tipo}
            resultados.append({"imagen": nombre, **parsed})
            print(f"  [{i+1}] {nombre}")
            print(f"       -> {tipo} ({confianza}) — {razon}")
            print(f"       tokens: in={usage['input']} out={usage['output']}")
        except Exception as e:
            print(f"  [{i+1}] {nombre}")
            print(f"       -> ERROR: {e}")
            resultados.append({"imagen": nombre, "tipo": "error", "error": str(e)})

    _DOCS_OBLIGATORIOS = {"fud", "resolucion", "ruv", "foto_danio"}
    tipos_encontrados = {r.get("tipo") for r in resultados if r.get("tipo") not in ("error", None)}

    print()
    print("=== Resumen clasificacion ===")
    for r in resultados:
        print(f"  {r['imagen']}: {r.get('tipo','?')}")

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
    if len(signed_urls) > len(resultados):
        extrap = tokens_total['total'] * len(signed_urls) // len(resultados)
        print(f"  Extrapolado a {len(signed_urls)} imagenes: ~{extrap:,} tokens")

    print()
    print(f"NOTA: Se analizaron {len(resultados)} de {len(signed_urls)} imagenes.")
    print("      Para validacion completa usar --n <total>")
    print()
    print("Smoke test Vision B completado.")


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
