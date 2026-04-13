"""
Smoke test local: valida que el scraper extrae casos del reporte de Salesforce
con todos los campos del reporte.

Uso:
    python scripts/smoke_test_bandeja.py --cookies "C:/ruta/exported-cookies.json"

No requiere AWS ni SSM — usa el archivo de cookies directamente.
Abre el browser en modo visible para que puedas ver qué está pasando.

Columnas esperadas en el reporte:
    Opened Date | Case Date/Time Last Modified | Subestados Autos | Placa |
    Case Number | Contact Name | Account Name | Case Origin |
    Expediente SIC | Número de reclamo en el core
"""
import argparse
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

REPORT_URL = (
    "https://surapa.lightning.force.com/lightning/r/Report/"
    "00OS6000006Sz9xMAC/view"
)

# Patrón de href de un registro Case
_RE_CASE_HREF = re.compile(r"/lightning/r/(500[A-Za-z0-9]+)/view")

# Mismo mapeo que el scraper de producción
_HEADER_TO_FIELD = {
    "case number": "case_number",
    "número de caso": "case_number",
    "numero de caso": "case_number",
    "opened date": "opened_date",
    "fecha de apertura": "opened_date",
    "fecha apertura": "opened_date",
    "case date/time last modified": "last_modified",
    "fecha hora última modificación": "last_modified",
    "fecha hora ultima modificacion": "last_modified",
    "última modificación": "last_modified",
    "ultima modificacion": "last_modified",
    "subestados autos": "subestado_autos",
    "subestado autos": "subestado_autos",
    "placa": "placa",
    "contact name": "contact_name",
    "nombre de contacto": "contact_name",
    "account name": "account_name",
    "nombre de cuenta": "account_name",
    "case origin": "case_origin",
    "origen del caso": "case_origin",
    "expediente sic": "expediente_sic",
    "expediente": "expediente_sic",
    "número de reclamo en el core": "numero_reclamo_core",
    "numero de reclamo en el core": "numero_reclamo_core",
    "número de reclamo": "numero_reclamo_core",
    "numero de reclamo": "numero_reclamo_core",
}

_REQUIRED_FIELDS = [
    "case_number", "sf_record_id", "opened_date", "last_modified",
    "subestado_autos", "placa", "contact_name", "account_name",
    "case_origin", "expediente_sic", "numero_reclamo_core",
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


def _normalizar(texto: str) -> str:
    if not texto:
        return ""
    return re.sub(r"\s+", " ", texto).strip().lower()


def _leer_columnas(frame) -> dict[int, str]:
    column_map = {}

    # ── Prioridad 1: Lightning report grid ────────────────────────────
    header_spans = frame.query_selector_all(
        "span.lightning-table-cell-measure-header-value"
    )
    if header_spans:
        print(f"\n  Headers detectados via Lightning grid ({len(header_spans)}):")
        for span in header_spans:
            id_attr = span.get_attribute("id") or ""
            col_match = re.search(r"col(\d+)-value", id_attr)
            if not col_match:
                print(f"    (sin col-index en id={id_attr!r})")
                continue
            col_idx = int(col_match.group(1))
            label = _normalizar(span.inner_text())
            field = _HEADER_TO_FIELD.get(label)
            status = f"→ {field}" if field else "← sin mapeo"
            print(f"    col{col_idx:02d}  {span.inner_text().strip()!r:50s} {status}")
            if field:
                column_map[col_idx] = field
        return column_map

    # ── Fallback: th / columnheader ───────────────────────────────────
    header_cells = frame.query_selector_all("thead tr th")
    if not header_cells:
        header_cells = frame.query_selector_all(
            "table tr:first-child td, table tr:first-child th"
        )
    if not header_cells:
        header_cells = frame.query_selector_all("[role='columnheader']")

    print(f"\n  Headers detectados via th/ARIA ({len(header_cells)}):")
    for idx, cell in enumerate(header_cells):
        label = _normalizar(cell.inner_text())
        field = _HEADER_TO_FIELD.get(label)
        status = f"→ {field}" if field else "← sin mapeo"
        print(f"    [{idx}] {cell.inner_text().strip()!r:50s} {status}")
        if field:
            column_map[idx] = field

    return column_map


def _debug_estructura_frame(frame):
    """Imprime información diagnóstica del frame para identificar selectores."""
    print("\n  ── DEBUG: estructura del frame ──────────────────────────────")

    checks = [
        ("tbody tr",                                    "filas tbody"),
        ("[role='row']",                                "ARIA rows"),
        ("[role='gridcell']",                           "ARIA gridcells"),
        ("span.lightning-table-cell-measure-header-value", "Lightning headers"),
        ("span[id*='-row'][id*='-col'][id*='-value']",  "Lightning data cells"),
        ("a[href]",                                     "links totales"),
    ]
    for selector, label in checks:
        count = len(frame.query_selector_all(selector))
        print(f"    {label:40s}: {count}")

    # Mostrar id de las primeras 3 celdas de datos para confirmar patrón
    data_spans = frame.query_selector_all("span[id*='-row'][id*='-col'][id*='-value']")
    if data_spans:
        print(f"\n  Primeras celdas de datos (muestra):")
        for span in data_spans[:6]:
            id_attr = span.get_attribute("id") or ""
            text = span.inner_text().strip()[:40]
            print(f"    id={id_attr!r:70s}  text={text!r}")

    print("  ─────────────────────────────────────────────────────────────")


def _extraer_grid_lightning(frame, column_map: dict[int, str]) -> list[dict]:
    """
    Extrae filas del Lightning report grid buscando spans con id row{R}-col{C}-value.
    """
    _RE_DATA_CELL = re.compile(r"-row(\d+)-col(\d+)-value$")

    all_spans = frame.query_selector_all(
        "span[id*='-row'][id*='-col'][id*='-value']"
    )
    if not all_spans:
        return []

    rows_dict: dict[int, dict] = {}
    for span in all_spans:
        id_attr = span.get_attribute("id") or ""
        m = _RE_DATA_CELL.search(id_attr)
        if not m:
            continue
        row_idx = int(m.group(1))
        col_idx = int(m.group(2))
        rows_dict.setdefault(row_idx, {})[col_idx] = span

    print(f"\n  Filas Lightning grid detectadas: {len(rows_dict)}")

    casos = []
    for row_idx in sorted(rows_dict.keys()):
        cols = rows_dict[row_idx]
        caso = {field: "" for field in _REQUIRED_FIELDS}

        for col_idx, span in cols.items():
            field = column_map.get(col_idx)
            # Buscar link de Case en la celda
            link = None
            try:
                link = span.query_selector("a[href]")
            except Exception:
                pass
            if link:
                href = link.get_attribute("href") or ""
                match = _RE_CASE_HREF.search(href)
                if match:
                    caso["sf_record_id"] = match.group(1)
                    if field:
                        caso[field] = link.inner_text().strip() or span.inner_text().strip()
                    continue
            if field:
                caso[field] = span.inner_text().strip()

        if not caso.get("sf_record_id"):
            # Último intento: buscar link en cualquier span del row
            for span in cols.values():
                try:
                    for link in span.query_selector_all("a[href]"):
                        href = link.get_attribute("href") or ""
                        match = _RE_CASE_HREF.search(href)
                        if match:
                            caso["sf_record_id"] = match.group(1)
                            break
                except Exception:
                    pass
                if caso.get("sf_record_id"):
                    break

        if not caso.get("sf_record_id"):
            continue

        casos.append(caso)

    return casos


def _extraer_casos_tabla(frame, debug: bool = False) -> list[dict]:
    if debug:
        _debug_estructura_frame(frame)

    column_map = _leer_columnas(frame)

    if not column_map:
        print("\n  WARN: sin column_map — usando fallback por links")
        return _extraer_casos_fallback(frame)

    # Intentar tbody/tr
    rows = frame.query_selector_all("tbody tr")
    if not rows:
        all_rows = frame.query_selector_all("[role='row']")
        rows = [r for r in all_rows if r.query_selector("[role='gridcell']")]

    if rows:
        print(f"\n  Filas tbody/ARIA detectadas: {len(rows)}")
        casos = []
        for row in rows:
            cells = row.query_selector_all("td, [role='gridcell']")
            if not cells:
                continue
            caso = {field: "" for field in _REQUIRED_FIELDS}
            for idx, cell in enumerate(cells):
                field = column_map.get(idx)
                if field:
                    caso[field] = cell.inner_text().strip()
            sf_record_id = ""
            for link in row.query_selector_all("a[href]"):
                href = link.get_attribute("href") or ""
                match = _RE_CASE_HREF.search(href)
                if match:
                    sf_record_id = match.group(1)
                    if not caso.get("case_number"):
                        caso["case_number"] = link.inner_text().strip()
                    break
            if not sf_record_id:
                continue
            caso["sf_record_id"] = sf_record_id
            casos.append(caso)
        if casos:
            return casos

    # Intentar Lightning grid por span-id
    print("\n  Sin tbody/tr — intentando Lightning grid por span-id...")
    casos = _extraer_grid_lightning(frame, column_map)
    if casos:
        return casos

    print("\n  WARN: todas las estrategias fallaron — usando fallback por links")
    return _extraer_casos_fallback(frame)


def _extraer_casos_fallback(frame) -> list[dict]:
    links = frame.query_selector_all("a[href]")
    casos = []
    for link in links:
        href = link.get_attribute("href") or ""
        match = _RE_CASE_HREF.search(href)
        if not match:
            continue
        case_number = link.inner_text().strip()
        if not case_number:
            continue
        caso = {field: "" for field in _REQUIRED_FIELDS}
        caso["case_number"] = case_number
        caso["sf_record_id"] = match.group(1)
        casos.append(caso)
    return casos


def main(cookies_path: str, headless: bool, save_output: str | None, debug: bool = False):
    print(f"Cargando cookies desde: {cookies_path}")
    with open(cookies_path, encoding="utf-8") as f:
        cookies_raw = json.load(f)

    cookies = convertir_cookies_para_playwright(cookies_raw)
    print(f"  {len(cookies)} cookies cargadas")

    print(f"\nAbriendo browser (headless={headless})...")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context()
        context.add_cookies(cookies)

        page = context.new_page()
        print(f"Navegando al reporte...")
        page.goto(REPORT_URL, wait_until="domcontentloaded", timeout=30_000)

        if "login" in page.url.lower():
            print("\nFAIL: las cookies no son válidas — Salesforce redirigió al login.")
            print("  Exporta las cookies con el browser abierto y sesión activa.")
            browser.close()
            sys.exit(1)

        print(f"URL actual: {page.url}")
        print("Esperando que cargue el grid del reporte...")

        report_frame = None
        for attempt in range(10):
            page.wait_for_timeout(3_000)
            for f in page.frames:
                if "lightningReportApp" in f.url or "reportId" in f.url:
                    links = f.query_selector_all("a[href]")
                    case_links = [
                        l for l in links
                        if _RE_CASE_HREF.search(l.get_attribute("href") or "")
                    ]
                    if case_links:
                        report_frame = f
                        print(f"  Frame listo (intento {attempt + 1}): {f.url[:80]}")
                        break
            if report_frame:
                break
            print(f"  Intento {attempt + 1}/10 — esperando casos en frame...")

        if not report_frame:
            print("\nFAIL: iframe del reporte no encontrado.")
            page.screenshot(path="smoke_test_screenshot.png")
            browser.close()
            sys.exit(1)

        casos = _extraer_casos_tabla(report_frame, debug=args.debug)
        browser.close()

    if not casos:
        print("\nWARN: el selector funcionó pero no se encontraron casos.")
        print("  Puede que el reporte esté vacío o los selectores necesiten ajuste.")
        sys.exit(1)

    # ──────────────────────────────────────────────────────────────────
    # Mostrar resultados
    # ──────────────────────────────────────────────────────────────────
    print(f"\n{'═' * 60}")
    print(f"OK: {len(casos)} casos extraídos")
    print(f"{'═' * 60}")

    for i, caso in enumerate(casos, 1):
        print(f"\n  Caso {i}:")
        print(f"    case_number        : {caso['case_number']}")
        print(f"    sf_record_id       : {caso['sf_record_id']}")
        print(f"    opened_date        : {caso['opened_date']}")
        print(f"    last_modified      : {caso['last_modified']}")
        print(f"    subestado_autos    : {caso['subestado_autos']}")
        print(f"    placa              : {caso['placa']}")
        print(f"    contact_name       : {caso['contact_name']}")
        print(f"    account_name       : {caso['account_name']}")
        print(f"    case_origin        : {caso['case_origin']}")
        print(f"    expediente_sic     : {caso['expediente_sic']}")
        print(f"    numero_reclamo_core: {caso['numero_reclamo_core']}")

    # Verificar campos vacíos sospechosos
    print(f"\n{'─' * 60}")
    print("Cobertura de campos (% casos con valor):")
    for field in _REQUIRED_FIELDS:
        con_valor = sum(1 for c in casos if c.get(field))
        pct = con_valor / len(casos) * 100
        status = "OK" if pct > 0 else "WARN — sin datos"
        print(f"  {field:30s}: {pct:5.0f}%  {status}")

    if save_output:
        out = Path(save_output)
        out.write_text(
            json.dumps({"casos": casos, "total": len(casos)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nSalida guardada en: {out.resolve()}")

    print("\nSmoke test exitoso.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cookies",
        default="C:/Users/Subocol/Desktop/agente analista panama/exported-cookies.json",
        help="Ruta al archivo JSON de cookies exportadas del browser",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=False,
        help="Correr sin browser visible (por defecto: visible)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Ruta donde guardar el JSON con los casos extraídos",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Mostrar diagnóstico de selectores y estructura del frame",
    )
    args = parser.parse_args()
    main(args.cookies, args.headless, args.output, args.debug)
