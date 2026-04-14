"""
Smoke test local: valida que el scraper extrae documentos adjuntos de un caso
desde la vista CombinedAttachments de Salesforce Lightning.

Uso:
    python scripts/smoke_test_extract_expediente_crm.py \\
        --record-id 500VY00000YWjzMYAT \\
        --cookies "C:/ruta/exported-cookies.json"

    # Con browser visible y debug de selectores:
    python scripts/smoke_test_extract_expediente_crm.py \\
        --record-id 500VY00000YWjzMYAT \\
        --cookies "C:/ruta/exported-cookies.json" \\
        --debug

No requiere AWS ni SSM — usa el archivo de cookies exportado directamente.
Abre el browser en modo visible por defecto para diagnostico.

Selectores a validar:
    table.uiVirtualDataTable                → tabla principal de attachments
    tbody tr                                → filas de documentos
    th[scope='row'] a                       → link con ContentDocument ID
    span.itemTitle[title]                   → nombre del documento
    span.slds-assistive-text                → tipo de archivo (ej. "Adobe PDF")
    td span.uiOutputDateTime                → fecha de modificacion
    td a.forceOutputLookup                  → creado por
    .fileSizeAmount + .fileSizeUnits        → tamaño del archivo
"""
import argparse
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

_SF_BASE_URL = "https://surapa.lightning.force.com"
_SEL_LOGIN = "#username"

_RE_DOC_HREF = re.compile(r"/lightning/r/ContentDocument/([A-Za-z0-9]+)/view")

# Pares (selector, descripcion) que deben estar presentes en la pagina
_SELECTORES_REQUERIDOS = [
    ("table.uiVirtualDataTable",          "Tabla principal (uiVirtualDataTable)"),
    ("table.uiVirtualDataTable thead",    "Header de la tabla"),
    ("table.uiVirtualDataTable tbody tr", "Filas de datos"),
]

# Selectores a verificar por fila
_SELECTORES_POR_FILA = [
    ("th[scope='row'] a",         "Link del documento (ContentDocument)"),
    ("span.itemTitle",            "Título del documento"),
    ("span.slds-assistive-text",  "Tipo de archivo (ícono asistivo)"),
    ("td span.uiOutputDateTime",  "Fecha de modificación"),
    ("td a.forceOutputLookup",    "Creado por"),
    (".fileSizeAmount",           "Número de tamaño"),
    (".fileSizeUnits",            "Unidad de tamaño"),
]


def convertir_cookies_para_playwright(cookies_raw: list[dict]) -> list[dict]:
    resultado = []
    for c in cookies_raw:
        same_site = c.get("sameSite", "Lax")
        if same_site not in ("Strict", "Lax", "None"):
            same_site = "Lax"
        resultado.append({
            "name":     c["name"],
            "value":    c["value"],
            "domain":   c["domain"],
            "path":     c.get("path", "/"),
            "expires":  c.get("expirationDate") or c.get("expires") or -1,
            "httpOnly": c.get("httpOnly", False),
            "secure":   c.get("secure", True),
            "sameSite": same_site,
        })
    return resultado


def _normalizar_tipo(raw: str) -> str:
    lower = raw.lower()
    if "pdf" in lower:
        return "pdf"
    if "image" in lower or "photo" in lower:
        return "image"
    if "word" in lower or "doc" in lower:
        return "word"
    if "excel" in lower or "spreadsheet" in lower or "csv" in lower:
        return "excel"
    return "unknown"


def _debug_estructura(page, label: str = ""):
    """Imprime diagnostico completo de selectores en la pagina."""
    if label:
        print(f"\n  ── DEBUG: {label} ─────────────────────────────────────────")
    else:
        print("\n  ── DEBUG: estructura de la pagina ─────────────────────────")

    checks = [
        ("table.uiVirtualDataTable",           "tabla principal"),
        ("table[role='grid']",                  "tabla ARIA grid"),
        ("table.uiVirtualDataTable thead",      "thead tabla"),
        ("table.uiVirtualDataTable tbody",      "tbody tabla"),
        ("table.uiVirtualDataTable tbody tr",   "filas datos"),
        ("th[scope='row'] a",                   "links ContentDocument"),
        ("span.itemTitle",                      "títulos documentos"),
        ("span.slds-assistive-text",            "textos asistivos (tipos)"),
        ("td span.uiOutputDateTime",            "fechas modificación"),
        ("td a.forceOutputLookup",              "links creado por"),
        (".fileSizeAmount",                     "números de tamaño"),
        (".fileSizeUnits",                      "unidades de tamaño"),
    ]
    for sel, label_sel in checks:
        count = len(page.query_selector_all(sel))
        status = "OK" if count > 0 else "⚠  NO ENCONTRADO"
        print(f"    {label_sel:40s} [{count:3d}]  {status}")

    # Mostrar los primeros hrefs de ContentDocument encontrados
    links = page.query_selector_all("th[scope='row'] a")
    if links:
        print(f"\n  Primeros hrefs de documentos ({min(3, len(links))}):")
        for link in links[:3]:
            href = link.get_attribute("href") or ""
            print(f"    {href}")

    # Mostrar los primeros textos asistivos (tipos de archivo)
    type_spans = page.query_selector_all("span.slds-assistive-text")
    if type_spans:
        print(f"\n  Primeros textos de ícono asistivo ({min(5, len(type_spans))}):")
        for span in type_spans[:5]:
            texto = span.inner_text().strip()
            if texto:
                print(f"    {texto!r}")

    print("  ─────────────────────────────────────────────────────────────")


def _esperar_tabla(page, max_intentos: int = 10) -> bool:
    """Espera hasta que el thead de la tabla sea visible. Retorna True si lo encontró."""
    for intento in range(max_intentos):
        page.wait_for_timeout(2_000)
        if page.query_selector("table.uiVirtualDataTable thead, table[role='grid'] thead"):
            print(f"   OK - tabla cargada (intento {intento + 1})")
            return True
        print(f"   Intento {intento + 1}/{max_intentos} — esperando tabla...")
    return False


def _parsear_fila(row) -> dict | None:
    """Extrae campos de una fila — misma logica que el scraper de produccion."""
    title_link = row.query_selector("th[scope='row'] a")
    if not title_link:
        return None

    href = title_link.get_attribute("href") or ""
    match = _RE_DOC_HREF.search(href)
    if not match:
        return None
    content_document_id = match.group(1)

    title_el = title_link.query_selector("span.itemTitle")
    title = ""
    if title_el:
        title = (title_el.get_attribute("title") or title_el.inner_text()).strip()

    type_el = title_link.query_selector("span.slds-assistive-text")
    file_type_raw = type_el.inner_text().strip() if type_el else ""
    file_type = _normalizar_tipo(file_type_raw)

    last_mod_el = row.query_selector("td span.uiOutputDateTime")
    last_modified = last_mod_el.inner_text().strip() if last_mod_el else ""

    created_by_el = row.query_selector("td a.forceOutputLookup")
    created_by = ""
    if created_by_el:
        created_by = (
            created_by_el.get_attribute("title") or created_by_el.inner_text()
        ).strip()

    size_num_el = row.query_selector(".fileSizeAmount")
    size_unit_el = row.query_selector(".fileSizeUnits")
    size = ""
    if size_num_el and size_unit_el:
        size = f"{size_num_el.inner_text().strip()} {size_unit_el.inner_text().strip()}"

    return {
        "title": title,
        "content_document_id": content_document_id,
        "file_type": file_type,
        "file_type_raw": file_type_raw,
        "last_modified": last_modified,
        "created_by": created_by,
        "size": size,
    }


def _verificar_selectores_por_fila(row, idx: int):
    """Imprime el estado de cada selector esperado en una fila."""
    print(f"\n    Fila {idx} — verificacion de selectores:")
    for sel, desc in _SELECTORES_POR_FILA:
        el = row.query_selector(sel)
        if el:
            texto = (el.get_attribute("title") or el.inner_text()).strip()[:50]
            print(f"      OK  {desc:40s} = {texto!r}")
        else:
            print(f"      ⚠   {desc:40s} → NO ENCONTRADO")


def main(record_id: str, cookies_path: str, headless: bool, debug: bool, save_output: str | None):
    print(f"=== Smoke test extract_expediente_crm | record_id={record_id} ===")
    print(f"Cargando cookies desde: {cookies_path}")

    with open(cookies_path, encoding="utf-8") as f:
        cookies_raw = json.load(f)

    cookies = convertir_cookies_para_playwright(cookies_raw)
    print(f"  {len(cookies)} cookies cargadas")

    url = f"{_SF_BASE_URL}/lightning/r/Case/{record_id}/related/CombinedAttachments/view"
    print(f"\nAbriendo browser (headless={headless})...")
    print(f"URL destino: {url}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context()
        context.add_cookies(cookies)

        page = context.new_page()

        # ── 1. Navegar ──────────────────────────────────────────────────
        print("\n1. Navegando a CombinedAttachments...")
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)

        if page.locator(_SEL_LOGIN).count() > 0:
            print("\nFAIL: las cookies no son válidas — Salesforce redirigió al login.")
            print("  Exporta las cookies con el browser abierto y sesion activa.")
            browser.close()
            sys.exit(1)

        print(f"   URL actual: {page.url}")

        if debug:
            print("\n  [DEBUG inmediato tras navegación]")
            _debug_estructura(page, "tras domcontentloaded")

        # ── 2. Esperar que la tabla renderice ───────────────────────────
        print("\n2. Esperando que la tabla de attachments renderice...")
        tabla_encontrada = _esperar_tabla(page)

        if debug:
            _debug_estructura(page, "tras polling")

        if not tabla_encontrada:
            print("\nWARN: tabla no encontrada tras polling.")
            page.screenshot(path="smoke_crm_attachments_fail.png")
            print("  Screenshot: smoke_crm_attachments_fail.png")
            print("  Puede que:")
            print("    - El caso no tenga documentos adjuntos")
            print("    - El selector necesite ajuste para este org")
            print("    - La pagina tarde mas de 20s en renderizar")
            browser.close()
            sys.exit(1)

        # ── 3. Verificar selectores ─────────────────────────────────────
        print("\n3. Verificando selectores de la tabla...")
        for sel, desc in _SELECTORES_REQUERIDOS:
            count = len(page.query_selector_all(sel))
            status = "OK" if count > 0 else "WARN — no encontrado"
            print(f"   {desc:45s} [{count}]  {status}")

        # ── 4. Extraer documentos ────────────────────────────────────────
        print("\n4. Extrayendo documentos...")
        rows = page.query_selector_all(
            "table.uiVirtualDataTable tbody tr, table[role='grid'] tbody tr"
        )
        print(f"   Filas encontradas: {len(rows)}")

        if not rows:
            print("\nWARN: tabla cargada pero sin filas de datos.")
            print("  El caso puede no tener adjuntos o los selectores de tbody tr necesitan ajuste.")
            browser.close()
            sys.exit(1)

        documentos = []
        for idx, row in enumerate(rows):
            if debug:
                _verificar_selectores_por_fila(row, idx)
            doc = _parsear_fila(row)
            if doc:
                documentos.append(doc)
            else:
                print(f"   WARN: fila {idx} no pudo parsearse (sin link ContentDocument)")

        browser.close()

    # ── 5. Mostrar resultados ──────────────────────────────────────────
    print(f"\n{'═' * 60}")
    print(f"OK: {len(documentos)} documento(s) extraído(s)")
    print(f"{'═' * 60}")

    for i, doc in enumerate(documentos, 1):
        print(f"\n  Documento {i}:")
        print(f"    title                : {doc['title']}")
        print(f"    content_document_id  : {doc['content_document_id']}")
        print(f"    file_type            : {doc['file_type']}  (raw: {doc['file_type_raw']!r})")
        print(f"    last_modified        : {doc['last_modified']}")
        print(f"    created_by           : {doc['created_by']}")
        print(f"    size                 : {doc['size']}")

    # ── 6. Validaciones ─────────────────────────────────────────────────
    print(f"\n{'─' * 60}")
    print("Cobertura de campos (% documentos con valor):")
    campos = ["title", "content_document_id", "file_type", "last_modified", "created_by", "size"]
    warns = []
    for campo in campos:
        con_valor = sum(1 for d in documentos if d.get(campo))
        pct = con_valor / len(documentos) * 100 if documentos else 0
        status = "OK" if pct > 0 else "WARN — selector posiblemente incorrecto"
        print(f"  {campo:25s}: {pct:5.0f}%  {status}")
        if pct == 0:
            warns.append(campo)

    if warns:
        print(f"\nWARN: los siguientes campos no se extrajeron en ningún documento:")
        for w in warns:
            print(f"  - {w}")
        print("  Revisar selectores en salesforce_attachments_scraper.py")

    # ── 7. Output JSON ───────────────────────────────────────────────────
    resultado = {
        "sf_record_id": record_id,
        "imagen_count": len(documentos),
        "documentos": [{k: v for k, v in d.items() if k != "file_type_raw"} for d in documentos],
    }

    if save_output:
        out = Path(save_output)
        out.write_text(
            json.dumps(resultado, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nSalida guardada en: {out.resolve()}")

    if warns:
        print("\nSmoke test completado con advertencias.")
        sys.exit(0)  # No es un fallo bloqueante — puede ser que el caso no tenga esos campos

    print("\nSmoke test exitoso.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Valida la extraccion de adjuntos de un caso Salesforce"
    )
    parser.add_argument(
        "--record-id",
        required=True,
        help="ID del registro del caso en Salesforce (ej. 500VY00000YWjzMYAT)",
    )
    parser.add_argument(
        "--cookies",
        default="C:/Users/Subocol/Desktop/agente-analista-panama/exported-cookies.json",
        help="Ruta al JSON de cookies exportadas del browser",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=False,
        help="Correr sin browser visible (por defecto: visible)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Mostrar diagnostico completo de selectores por fila",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Ruta donde guardar el JSON con los documentos extraidos",
    )
    args = parser.parse_args()
    main(args.record_id, args.cookies, args.headless, args.debug, args.output)
