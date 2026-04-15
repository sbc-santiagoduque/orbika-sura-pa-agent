"""
Smoke test local: valida que salesforce_case_resolver resuelve
case_number → sf_record_id correctamente usando búsqueda global de Salesforce.

Uso:
    python scripts/smoke_test_case_resolver.py \\
        --case-number CF0975 \\
        --cookies "C:/ruta/exported-cookies.json"

    # Con browser visible y pause para inspección:
    python scripts/smoke_test_case_resolver.py \\
        --case-number CF0975 \\
        --cookies "C:/ruta/exported-cookies.json" \\
        --pause

PENDIENTE: este test valida los selectores de búsqueda global de Salesforce
Lightning contra el org de Sura Panamá. Ejecutar antes del primer deploy.

Selectores a validar:
    input.global-search-box     → input de búsqueda global (o fallback con tecla /)
    a[href*='/lightning/r/Case/'] → links de resultado que exponen sf_record_id
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
_RE_RECORD_ID = re.compile(r"/lightning/r/Case/([A-Za-z0-9]{15,18})/view")

# Selectores a validar — mismos que salesforce_case_resolver.py
_SEL_SEARCH_INPUT = "input.global-search-box"
_SEL_RESULT_CASE_LINK = "a[href*='/lightning/r/Case/']"


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


def _debug_busqueda(page):
    print("\n  ── DEBUG: estado del input de búsqueda ───────────────────")
    checks = [
        ("input.global-search-box",          "input.global-search-box"),
        ("input[type='search']",             "input[type='search']"),
        ("[placeholder*='Search']",          "placeholder*=Search"),
        ("input[class*='search']",           "input class*=search"),
        ("button[class*='search']",          "button search trigger"),
        ("a[href*='/lightning/r/Case/']",    "links Case en resultados"),
    ]
    for sel, desc in checks:
        count = len(page.query_selector_all(sel))
        status = "OK" if count > 0 else "NO ENCONTRADO"
        print(f"    {desc:45s} [{count:3d}]  {status}")

    # Mostrar los primeros hrefs de Case encontrados
    case_links = page.query_selector_all("a[href*='/lightning/r/Case/']")
    if case_links:
        print(f"\n  Primeros hrefs de Case ({min(3, len(case_links))}):")
        for link in case_links[:3]:
            href = link.get_attribute("href") or ""
            text = link.inner_text().strip()[:40]
            print(f"    {href}  ({text!r})")
    print("  ──────────────────────────────────────────────────────────")


def main(case_number: str, cookies_path: str, pause: bool):
    print(f"=== Smoke test case_resolver | case_number={case_number} ===")
    print(f"Cargando cookies desde: {cookies_path}")

    with open(cookies_path, encoding="utf-8") as f:
        cookies_raw = json.load(f)
    cookies = convertir_cookies_para_playwright(cookies_raw)
    print(f"  {len(cookies)} cookies cargadas")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        context.add_cookies(cookies)
        page = context.new_page()

        # ── 1. Navegar a SF home ────────────────────────────────────────
        print(f"\n1. Navegando a {_SF_BASE_URL}...")
        page.goto(_SF_BASE_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(2_000)

        if page.locator(_SEL_LOGIN).count() > 0:
            print("\nFAIL: cookies inválidas — Salesforce redirigió al login.")
            browser.close()
            sys.exit(1)

        print(f"   URL actual: {page.url}")

        # ── 2. Localizar el input de búsqueda ───────────────────────────
        print("\n2. Localizando input de búsqueda global...")
        search_input = page.query_selector(_SEL_SEARCH_INPUT)
        if not search_input:
            print(f"   Selector {_SEL_SEARCH_INPUT!r} no encontrado — intentando tecla /")
            page.keyboard.press("/")
            page.wait_for_timeout(500)
            search_input = page.query_selector(_SEL_SEARCH_INPUT)

        if not search_input:
            print(f"\nFAIL: input de búsqueda no encontrado.")
            print("  Ajustar _SEL_SEARCH_INPUT en salesforce_case_resolver.py")
            _debug_busqueda(page)
            if pause:
                input("\n[PAUSE] Browser abierto. Presiona Enter para cerrar...")
            browser.close()
            sys.exit(1)

        print(f"   OK — input encontrado con selector {_SEL_SEARCH_INPUT!r}")

        # ── 3. Escribir case_number y esperar resultados ─────────────────
        print(f"\n3. Buscando '{case_number}'...")
        search_input.click()
        search_input.fill(case_number)
        page.wait_for_timeout(2_000)

        _debug_busqueda(page)

        # ── 4. Buscar link con sf_record_id en resultados ────────────────
        print("\n4. Buscando sf_record_id en resultados...")
        result_links = page.query_selector_all(_SEL_RESULT_CASE_LINK)
        print(f"   Links de Case encontrados: {len(result_links)}")

        sf_record_id = None
        for link in result_links:
            href = link.get_attribute("href") or ""
            match = _RE_RECORD_ID.search(href)
            if match:
                sf_record_id = match.group(1)
                text = link.inner_text().strip()
                print(f"   OK — sf_record_id={sf_record_id}  (texto: {text!r})")
                break

        if pause:
            input("\n[PAUSE] Browser abierto para inspección. Presiona Enter para cerrar...")

        browser.close()

    # ── 5. Resultado ─────────────────────────────────────────────────────
    print(f"\n{'═' * 60}")
    if sf_record_id:
        print(f"OK: {case_number} → {sf_record_id}")
        print(f"{'═' * 60}")
        print("\nSmoke test exitoso.")
        print("\nAcción: actualizar salesforce_case_resolver.py si los selectores fueron distintos.")
    else:
        print(f"FAIL: no se encontró sf_record_id para case_number={case_number!r}")
        print(f"{'═' * 60}")
        print("\nPosibles causas:")
        print("  - El selector _SEL_RESULT_CASE_LINK necesita ajuste")
        print("  - Los resultados de búsqueda tardan más de 2s en aparecer (aumentar _POLL_WAIT_MS)")
        print("  - El case_number no existe en este org de Salesforce")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Valida que salesforce_case_resolver resuelve case_number → sf_record_id"
    )
    parser.add_argument(
        "--case-number",
        required=True,
        help="Número de caso visible (ej. CF0975)",
    )
    parser.add_argument(
        "--cookies",
        default="C:/Users/Subocol/Desktop/agente-analista-panama/exported-cookies.json",
        help="Ruta al JSON de cookies exportadas del browser",
    )
    parser.add_argument(
        "--pause",
        action="store_true",
        default=False,
        help="Mantener el browser abierto para inspección visual antes de cerrar",
    )
    args = parser.parse_args()
    main(args.case_number, args.cookies, args.pause)
