"""
Smoke test local: valida que el scraper extrae comentarios de un caso
desde la vista CaseComments de Salesforce Lightning.

Uso:
    python scripts/smoke_test_review_historial_crm.py \\
        --case-number CF0975 \\
        --cookies "C:/ruta/exported-cookies.json"

    # Con browser visible y pause para inspección:
    python scripts/smoke_test_review_historial_crm.py \\
        --case-number CF0975 \\
        --cookies "C:/ruta/exported-cookies.json" \\
        --pause

    # Con record-id directo (sin resolver):
    python scripts/smoke_test_review_historial_crm.py \\
        --record-id 500VY00000YWjzMYAT \\
        --cookies "C:/ruta/exported-cookies.json"

No requiere AWS ni SSM — usa el archivo de cookies exportado directamente.
Abre el browser en modo visible por defecto para diagnóstico.

Selectores validados contra HTML real (Sura Panamá, 2026-04-15):
    table.slds-table                          → tabla CaseComments
    table.slds-table thead                    → header de la tabla
    table.slds-table tbody tr                 → filas de comentarios
    th[scope='row'] a.forceOutputLookup       → autor del comentario
    span.uiOutputCheckbox img[aria-checked]   → campo Public
    span.uiOutputDateTime                     → fecha del comentario
    span.forceListViewManagerGridWrapText     → texto del comentario
"""
import argparse
import json
import re
import sys
from pathlib import Path

# Agregar el root del proyecto al path para imports de src.*
sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.sync_api import sync_playwright

_SF_BASE_URL = "https://surapa.lightning.force.com"
_SEL_LOGIN = "#username"

# Pares (selector, descripcion) para verificación global de la página
_SELECTORES_REQUERIDOS = [
    ("table.slds-table",          "Tabla principal (slds-table)"),
    ("table.slds-table thead",    "Header de la tabla (thead)"),
    ("table.slds-table tbody tr", "Filas de comentarios (tbody tr)"),
]

# Selectores a verificar dentro de cada fila
_SELECTORES_POR_FILA = [
    ("th[scope='row'] a.forceOutputLookup",    "Autor (forceOutputLookup)"),
    ("span.uiOutputCheckbox img",              "Campo Public (checkbox img)"),
    ("span.uiOutputDateTime",                  "Fecha (uiOutputDateTime)"),
    ("span.forceListViewManagerGridWrapText",  "Texto comentario (WrapText)"),
]

_RE_WHITESPACE = re.compile(r"\s+")
_RE_SPACES = re.compile(r"[ \t]+")
_RE_EXCESS_NEWLINES = re.compile(r"\n{3,}")


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


def _limpiar(texto: str) -> str:
    if not texto:
        return ""
    return _RE_WHITESPACE.sub(" ", texto).strip()


def _limpiar_texto(texto: str) -> str:
    """Preserva \\n de <br> — significativos en comentarios multilínea."""
    if not texto:
        return ""
    texto = _RE_SPACES.sub(" ", texto)
    texto = _RE_EXCESS_NEWLINES.sub("\n\n", texto)
    return texto.strip()


def _debug_estructura(page, label: str = ""):
    titulo = f"DEBUG: {label}" if label else "DEBUG: estructura de la página"
    print(f"\n  ── {titulo} ──────────────────────────────────")
    checks = [
        ("table.slds-table",                       "tabla slds-table"),
        ("table[role='grid']",                      "tabla ARIA grid"),
        ("table.slds-table thead",                  "thead"),
        ("table.slds-table tbody",                  "tbody"),
        ("table.slds-table tbody tr",               "filas (tbody tr)"),
        ("th[scope='row'] a.forceOutputLookup",     "links autor"),
        ("span.uiOutputCheckbox img",               "checkboxes Public"),
        ("span.uiOutputDateTime",                   "fechas"),
        ("span.forceListViewManagerGridWrapText",   "textos comentario"),
    ]
    for sel, label_sel in checks:
        count = len(page.query_selector_all(sel))
        status = "OK" if count > 0 else "NO ENCONTRADO"
        print(f"    {label_sel:45s} [{count:3d}]  {status}")

    # Mostrar primeros textos de comentario para confirmar extracción
    texto_spans = page.query_selector_all("span.forceListViewManagerGridWrapText")
    if texto_spans:
        print(f"\n  Primeros textos ({min(3, len(texto_spans))}):")
        for span in texto_spans[:3]:
            texto = span.inner_text().strip()[:80]
            print(f"    {texto!r}")
    print("  ─────────────────────────────────────────────────────────────")


def _esperar_tabla(page, max_intentos: int = 10) -> bool:
    """Espera a que el thead de la tabla sea visible."""
    for intento in range(max_intentos):
        page.wait_for_timeout(2_000)
        if page.query_selector("table.slds-table thead"):
            print(f"   OK — tabla cargada (intento {intento + 1})")
            return True
        print(f"   Intento {intento + 1}/{max_intentos} — esperando tabla...")
    return False


def _esperar_filas(page, max_intentos: int = 8) -> int:
    """
    Espera a que tbody tenga filas.
    Salesforce SPA renderiza thead antes que tbody — necesita polling extra.
    """
    sel_filas = "table.slds-table tbody tr"
    for intento in range(max_intentos):
        count = len(page.query_selector_all(sel_filas))
        if count > 0:
            print(f"   OK — {count} fila(s) encontrada(s) (intento {intento + 1})")
            return count
        print(f"   Intento {intento + 1}/{max_intentos} — esperando filas del tbody...")
        page.wait_for_timeout(2_000)
    return 0


def _dump_tabla_html(page):
    print("\n  ── DUMP HTML tabla ─────────────────────────────────────")
    tbody = page.query_selector("table.slds-table tbody")
    if tbody:
        html = tbody.inner_html()
        print(f"  [tbody innerHTML, primeros 3000 chars]\n{html[:3000]}")
    else:
        print("  tbody no encontrado. HTML del body (primeros 2000 chars):")
        print(page.inner_html("body")[:2000])
    print("  ──────────────────────────────────────────────────────────")


def _parsear_fila(row) -> dict | None:
    """Extrae autor, fecha, texto y es_publico de una fila — misma lógica que el scraper."""
    user_link = row.query_selector("th[scope='row'] a.forceOutputLookup")
    if not user_link:
        return None

    autor = _limpiar(user_link.get_attribute("title") or user_link.inner_text())

    public_img = row.query_selector("span.uiOutputCheckbox img")
    es_publico = False
    if public_img:
        aria_checked = public_img.get_attribute("aria-checked") or ""
        es_publico = aria_checked.lower() == "true"

    fecha_el = row.query_selector("span.uiOutputDateTime")
    fecha = _limpiar(fecha_el.inner_text()) if fecha_el else ""

    texto_el = row.query_selector("span.forceListViewManagerGridWrapText")
    texto = _limpiar_texto(texto_el.inner_text()) if texto_el else ""

    if not texto:
        return None

    return {
        "autor":      autor,
        "fecha":      fecha,
        "texto":      texto[:2000],
        "es_publico": es_publico,
    }


def _verificar_selectores_por_fila(row, idx: int):
    print(f"\n    Fila {idx} — verificación de selectores:")
    for sel, desc in _SELECTORES_POR_FILA:
        el = row.query_selector(sel)
        if el:
            valor = ""
            try:
                valor = (el.get_attribute("title") or el.get_attribute("aria-checked") or el.inner_text()).strip()[:60]
            except Exception:
                pass
            print(f"      OK  {desc:50s} = {valor!r}")
        else:
            print(f"      ⚠   {desc:50s} → NO ENCONTRADO")


def main(
    record_id: str | None,
    case_number: str | None,
    cookies_path: str,
    storage_state_path: str | None,
    headless: bool,
    debug: bool,
    pause: bool,
    save_output: str | None,
):
    label = f"record_id={record_id}" if record_id else f"case_number={case_number}"
    print(f"=== Smoke test review_historial_crm | {label} ===")

    cookies = []
    if storage_state_path:
        print(f"Usando storageState (cookies + localStorage): {storage_state_path}")
    else:
        print(f"Cargando cookies desde: {cookies_path}")
        with open(cookies_path, encoding="utf-8") as f:
            cookies_raw = json.load(f)
        cookies = convertir_cookies_para_playwright(cookies_raw)
        print(f"  {len(cookies)} cookies cargadas")

    print(f"\nAbriendo browser (headless={headless})...")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)

        if storage_state_path:
            with open(storage_state_path, encoding="utf-8") as f:
                state = json.load(f)
            context = browser.new_context(storage_state=state)
        else:
            context = browser.new_context()
            context.add_cookies(cookies)

        page = context.new_page()

        # ── 1. Resolver case_number → sf_record_id ───────────────────────
        if case_number and not record_id:
            print(f"\n1. Resolviendo case_number={case_number!r} → sf_record_id...")
            from src.shared.browser.salesforce_case_resolver import resolve_sf_record_id
            try:
                record_id = resolve_sf_record_id(page, case_number)
                print(f"   OK — sf_record_id={record_id}")
            except RuntimeError as e:
                print(f"\nFAIL al resolver case_number: {e}")
                if pause:
                    input("\n[PAUSE] Browser abierto. Presiona Enter para cerrar...")
                browser.close()
                sys.exit(1)
        else:
            print(f"\n1. Usando sf_record_id directo: {record_id}")

        # ── 2. Navegar a CaseComments ────────────────────────────────────
        url = (
            f"{_SF_BASE_URL}/lightning/r/Case/{record_id}"
            "/related/CaseComments/view"
        )
        print(f"\n2. Navegando a CaseComments...")
        print(f"   URL destino: {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        print(f"   URL actual:  {page.url}")

        if page.locator(_SEL_LOGIN).count() > 0:
            print("\nFAIL: Salesforce redirigió al login — cookies inválidas o expiradas.")
            browser.close()
            sys.exit(1)

        if debug:
            _debug_estructura(page, "tras domcontentloaded")

        # ── 3. Esperar tabla ─────────────────────────────────────────────
        print("\n3. Esperando que la tabla de comentarios renderice...")
        tabla_encontrada = _esperar_tabla(page)

        if debug:
            _debug_estructura(page, "tras polling de tabla")

        if not tabla_encontrada:
            print("\nWARN: tabla no encontrada tras polling.")
            print("  Posibles causas:")
            print("    - El caso no tiene CaseComments")
            print("    - El selector table.slds-table necesita ajuste")
            print("    - La página tarda más de 20s en renderizar")
            if debug:
                _dump_tabla_html(page)
            if pause:
                input("\n[PAUSE] Browser abierto. Presiona Enter para cerrar...")
            browser.close()
            sys.exit(1)

        # ── 4. Verificar selectores de la tabla ──────────────────────────
        print("\n4. Verificando selectores de la tabla...")
        for sel, desc in _SELECTORES_REQUERIDOS:
            count = len(page.query_selector_all(sel))
            status = "OK" if count > 0 else "WARN — no encontrado"
            print(f"   {desc:45s} [{count}]  {status}")

        # ── 5. Esperar filas tbody ───────────────────────────────────────
        print("\n5. Esperando filas del tbody (SPA Lightning: thead antes que tbody)...")
        n_filas = _esperar_filas(page)

        if debug or n_filas == 0:
            _debug_estructura(page, "tras polling de filas")

        if n_filas == 0:
            print("\nWARN: tabla cargada pero sin filas de datos.")
            print("  Posibles causas:")
            print("    - El caso no tiene comentarios en CaseComments")
            print("    - Las filas aún no renderizaron (aumentar polling)")
            if debug:
                _dump_tabla_html(page)
            if pause:
                input("\n[PAUSE] Browser abierto. Presiona Enter para cerrar...")
            browser.close()
            sys.exit(1)

        # ── 6. Extraer comentarios ───────────────────────────────────────
        print("\n6. Extrayendo comentarios...")
        rows = page.query_selector_all("table.slds-table tbody tr")
        print(f"   Filas encontradas: {len(rows)}")

        comentarios = []
        for idx, row in enumerate(rows):
            if debug:
                _verificar_selectores_por_fila(row, idx)
            comentario = _parsear_fila(row)
            if comentario:
                comentarios.append(comentario)
            else:
                print(f"   WARN: fila {idx} no pudo parsearse")

        if pause:
            input("\n[PAUSE] Browser abierto para inspección. Presiona Enter para cerrar...")

        browser.close()

    # ── 7. Mostrar resultados ────────────────────────────────────────────
    print(f"\n{'═' * 60}")
    print(f"OK: {len(comentarios)} comentario(s) extraído(s)")
    print(f"{'═' * 60}")

    for i, c in enumerate(comentarios, 1):
        publico = "Público" if c["es_publico"] else "Interno"
        print(f"\n  Comentario {i} [{publico}]:")
        print(f"    autor  : {c['autor']}")
        print(f"    fecha  : {c['fecha']}")
        # Texto puede ser multilínea — indentar cada línea
        texto_lines = c["texto"].split("\n")
        print(f"    texto  : {texto_lines[0][:100]}")
        for linea in texto_lines[1:]:
            if linea.strip():
                print(f"             {linea[:100]}")

    # ── 8. Cobertura de campos ───────────────────────────────────────────
    print(f"\n{'─' * 60}")
    print("Cobertura de campos (% comentarios con valor):")
    campos = ["autor", "fecha", "texto"]
    warns = []
    for campo in campos:
        con_valor = sum(1 for c in comentarios if c.get(campo))
        pct = con_valor / len(comentarios) * 100 if comentarios else 0
        status = "OK" if pct > 0 else "WARN — selector posiblemente incorrecto"
        print(f"  {campo:15s}: {pct:5.0f}%  {status}")
        if pct == 0:
            warns.append(campo)

    if warns:
        print(f"\nWARN: campos sin datos en ningún comentario: {warns}")
        print("  Revisar selectores en salesforce_case_scraper.py")

    # ── 9. Output JSON ───────────────────────────────────────────────────
    resultado = {
        "sf_record_id": record_id,
        "case_number":  case_number,
        "comments":     comentarios,
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
        sys.exit(0)

    print("\nSmoke test exitoso.")
    print("\nAcción: si los selectores coinciden con lo esperado, F2 está listo para deploy.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Valida la extraccion de comentarios (CaseComments) de Salesforce"
    )
    parser.add_argument(
        "--record-id",
        default=None,
        help="ID del registro del caso (ej. 500VY00000YWjzMYAT). Alternativa a --case-number.",
    )
    parser.add_argument(
        "--case-number",
        default=None,
        help="Número de caso visible (ej. CF0975). Resuelve sf_record_id via reporte de bandeja.",
    )
    parser.add_argument(
        "--storage-state",
        default=None,
        metavar="RUTA",
        help="Ruta al storageState de Playwright (cookies + localStorage). Recomendado.",
    )
    parser.add_argument(
        "--cookies",
        default="C:/Users/Subocol/Desktop/agente-analista-panama/exported-cookies.json",
        help="Ruta al JSON de cookies exportadas del browser.",
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
        help="Mostrar diagnóstico completo de selectores por fila y dump de HTML",
    )
    parser.add_argument(
        "--pause",
        action="store_true",
        default=False,
        help="Mantener el browser abierto para inspección visual antes de cerrar",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Ruta donde guardar el JSON con los comentarios extraídos",
    )
    args = parser.parse_args()
    if not args.record_id and not args.case_number:
        parser.error("Se requiere --record-id o --case-number")
    main(
        args.record_id,
        args.case_number,
        args.cookies,
        args.storage_state,
        args.headless,
        args.debug,
        args.pause,
        args.output,
    )
