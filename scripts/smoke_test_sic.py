"""
Smoke test local: valida el scraper de SIC contra el sistema real.

Uso:
    python scripts/smoke_test_sic.py --placa CU7559

Lee credenciales desde .env en la raiz del proyecto.
Abre el browser en modo visible para diagnostico.
"""
import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path

_RE_FECHA_NUMERICA = re.compile(r'\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2}|\d{2}-\d{2}-\d{4}')
_FORMATOS_FECHA = ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"]
_MESES_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}
_RE_FECHA_ES = re.compile(
    r'(\d{1,2})\s+(' + '|'.join(_MESES_ES) + r')[,\s]+(\d{4})',
    re.IGNORECASE,
)


def _parsear_fecha(texto: str):
    # Formato espanol: "24 Diciembre, 2024 03:01 PM"
    m = _RE_FECHA_ES.search(texto)
    if m:
        dia, mes_str, anio = int(m.group(1)), _MESES_ES[m.group(2).lower()], int(m.group(3))
        return datetime(anio, mes_str, dia)
    # Formatos numericos: DD/MM/YYYY, YYYY-MM-DD, DD-MM-YYYY
    m = _RE_FECHA_NUMERICA.search(texto)
    if m:
        for fmt in _FORMATOS_FECHA:
            try:
                return datetime.strptime(m.group(), fmt)
            except ValueError:
                continue
    return None


def _fila_mas_reciente(filas):
    """Retorna (fila, indice) con la mayor fecha encontrada en cualquier celda.
    Si no hay fechas, retorna la primera fila.
    """
    mejor_fila, mejor_idx, mejor_fecha = filas[0], 0, None
    for i, fila in enumerate(filas):
        for celda in fila.query_selector_all("td"):
            fecha = _parsear_fecha(celda.inner_text().strip())
            if fecha and (mejor_fecha is None or fecha > mejor_fecha):
                mejor_fecha = fecha
                mejor_fila = fila
                mejor_idx = i
    return mejor_fila, mejor_idx, mejor_fecha

# Cargar .env antes de cualquier import del proyecto
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

from playwright.sync_api import sync_playwright

SIC_BASE_URL = os.environ.get("SIC_URL", "https://sic.connectasistencia.com")
SIC_LOGIN_URL = SIC_BASE_URL
SIC_SEARCH_URL = f"{SIC_BASE_URL}/events-claims"

_SEL_USERNAME    = "input#username"
_SEL_PASSWORD    = "input#password"
_SEL_SUBMIT      = "button[type='submit']"
_SEL_FILTER_COMBO = "div[role='combobox']"
_SEL_PLATE_INPUT  = "input[placeholder='Buscar Placa Asegurado']"
_SEL_RESULT_ROWS  = "table[aria-label='simple table'] tbody tr"
_SEL_GALLERY_IMG  = "img[src*='amazonaws']"


def main(placa: str, headless: bool):
    username = os.environ.get("SIC_USERNAME")
    password = os.environ.get("SIC_PASSWORD")

    if not username or not password:
        print("FAIL: SIC_USERNAME o SIC_PASSWORD no encontrados en .env")
        sys.exit(1)

    print(f"=== Smoke test SIC | placa={placa} | headless={headless} ===")
    print(f"Usuario: {username}")
    print()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()

        # --- LOGIN ---
        print("1. Navegando a login...")
        page.goto(SIC_LOGIN_URL, wait_until="domcontentloaded")
        page.wait_for_selector(_SEL_USERNAME, timeout=10_000)

        page.fill(_SEL_USERNAME, username)
        page.fill(_SEL_PASSWORD, password)
        page.click(_SEL_SUBMIT)

        try:
            page.wait_for_url(
                lambda url: url.rstrip("/") != SIC_BASE_URL.rstrip("/"),
                timeout=15_000,
            )
            print(f"   OK - login exitoso. URL: {page.url}")
        except Exception:
            page.screenshot(path="smoke_sic_login_fail.png")
            print("FAIL: login no completado en 15s. Screenshot: smoke_sic_login_fail.png")
            browser.close()
            sys.exit(1)

        # Guardar storageState para uso futuro
        state = context.storage_state()
        print(f"   storageState: {len(state.get('cookies',[]))} cookies capturadas")

        # --- BUSQUEDA ---
        print(f"\n2. Buscando placa {placa}...")
        page.goto(SIC_SEARCH_URL, wait_until="domcontentloaded")
        page.screenshot(path="smoke_sic_search_state.png")
        print(f"   URL actual: {page.url}")
        page.wait_for_selector(_SEL_FILTER_COMBO, timeout=30_000)

        # Abrir MUI Select
        page.click(_SEL_FILTER_COMBO)
        page.wait_for_selector("li[role='option']:has-text('Placa Asegurado')", timeout=5_000)
        page.click("li[role='option']:has-text('Placa Asegurado')")

        # Escribir placa
        page.wait_for_selector(_SEL_PLATE_INPUT, timeout=5_000)
        page.fill(_SEL_PLATE_INPUT, placa)
        page.press(_SEL_PLATE_INPUT, "Enter")

        try:
            page.wait_for_selector(_SEL_RESULT_ROWS, timeout=10_000)
            # Esperar a que React reemplace skeletons con datos reales
            page.wait_for_timeout(2_500)
        except Exception:
            page.screenshot(path="smoke_sic_search_fail.png")
            print(f"FAIL: sin resultados para placa {placa}. Screenshot: smoke_sic_search_fail.png")
            browser.close()
            sys.exit(1)

        # Re-consultar filas DESPUES del wait (los skeletons ya se reemplazaron)
        filas = page.query_selector_all(_SEL_RESULT_ROWS)
        print(f"   OK - {len(filas)} fila(s) encontrada(s):")
        for i, fila in enumerate(filas):
            celdas = fila.query_selector_all("td")
            valores = [c.inner_text().strip() for c in celdas]
            print(f"   [{i}] {valores}")

        _, idx_target, fecha_target = _fila_mas_reciente(filas)
        print(f"\n3. Abriendo expediente (fila {idx_target}, fecha={fecha_target})...")
        try:
            # El click abre el expediente en una NUEVA pestana
            with context.expect_page(timeout=10_000) as new_page_info:
                page.locator(_SEL_RESULT_ROWS).nth(idx_target).click()
            exp = new_page_info.value
            exp.wait_for_load_state("domcontentloaded")
            print(f"   URL expediente: {exp.url}")
            exp.screenshot(path="smoke_sic_expediente_loaded.png")
            exp.wait_for_selector(_SEL_GALLERY_IMG, timeout=30_000, state="attached")
        except Exception as e:
            page.screenshot(path="smoke_sic_expediente_fail.png")
            print(f"FAIL: no se pudo abrir el expediente: {e}")
            print(f"  URL actual: {page.url}")
            print("  Screenshot: smoke_sic_expediente_fail.png")
            browser.close()
            sys.exit(1)

        imgs = exp.query_selector_all(_SEL_GALLERY_IMG)
        urls = [(img.get_attribute("src") or "").split("?")[0] for img in imgs if img.get_attribute("src")]
        print(f"   OK - {len(imgs)} imagenes encontradas")
        for url in urls[:3]:
            print(f"     {url}")
        if len(urls) > 3:
            print(f"     ... y {len(urls)-3} mas")

        browser.close()

    print()
    print("Smoke test SIC exitoso.")
    print()
    print("Para guardar el storageState en SSM cuando este aprovisionado:")
    print("  Agregar --save-state al script (pendiente implementar)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--placa", required=True, help="Placa a buscar en SIC")
    parser.add_argument("--headless", action="store_true", default=False)
    args = parser.parse_args()
    main(args.placa, args.headless)
