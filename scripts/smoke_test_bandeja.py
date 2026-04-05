"""
Smoke test local: valida que el scraper extrae casos del reporte de Salesforce.

Uso:
    python scripts/smoke_test_bandeja.py --cookies "C:/ruta/exported-cookies.json"

No requiere AWS ni SSM — usa el archivo de cookies directamente.
Abre el browser en modo visible para que puedas ver qué está pasando.
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

SELECTOR_CASE_LINKS = 'a[data-object-api-name="Case"]'
RE_RECORD_ID = re.compile(r"/lightning/r/([^/]+)/view")


def convertir_cookies_para_playwright(cookies_raw: list[dict]) -> list[dict]:
    """
    Convierte cookies exportadas desde el browser al formato que espera Playwright.

    El exportador del browser usa 'expirationDate' y session=True/False.
    Playwright espera 'expires' como Unix timestamp (-1 = sin expiración fija).
    """
    resultado = []
    for c in cookies_raw:
        # sameSite: Playwright acepta "Strict", "Lax", "None"
        same_site = c.get("sameSite", "Lax")
        if same_site not in ("Strict", "Lax", "None"):
            same_site = "Lax"

        playwright_cookie = {
            "name": c["name"],
            "value": c["value"],
            "domain": c["domain"],
            "path": c.get("path", "/"),
            "expires": c.get("expirationDate") or c.get("expires") or -1,
            "httpOnly": c.get("httpOnly", False),
            "secure": c.get("secure", True),
            "sameSite": same_site,
        }
        resultado.append(playwright_cookie)
    return resultado


def main(cookies_path: str, headless: bool):
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
        # Salesforce Lightning nunca llega a networkidle (requests continuos en bg)
        # Usamos "domcontentloaded" y luego esperamos el selector específico
        page.goto(REPORT_URL, wait_until="domcontentloaded", timeout=30_000)

        # Verificar si llegamos al login (cookies inválidas)
        if "login" in page.url.lower():
            print("\nFAIL: las cookies no son validas - Salesforce redirigió al login.")
            print("  Exporta las cookies con el browser abierto y sesion activa.")
            browser.close()
            sys.exit(1)

        print(f"URL actual: {page.url}")
        print("Esperando que cargue el grid del reporte...")

        # Esperar a que aparezca CUALQUIER link a un registro de Salesforce
        # (href con patrón /lightning/r/{id}/view) — más robusto que data-object-api-name
        # Salesforce Analytics carga el grid dentro de un iframe
        # Esperar a que el iframe con el reporte aparezca
        # El reporte carga dentro del iframe lightningReportApp.app
        # Esperar a que el iframe con el reporte esté disponible
        report_frame = None
        for _ in range(10):
            page.wait_for_timeout(3000)
            for f in page.frames:
                if "lightningReportApp" in f.url or "reportId" in f.url:
                    report_frame = f
                    break
            if report_frame:
                break

        if not report_frame:
            print("\nFAIL: iframe del reporte no encontrado.")
            browser.close()
            sys.exit(1)

        print(f"  Frame del reporte: {report_frame.url[:80]}")

        # Esperar hasta 30s a que aparezcan links en el frame
        found = False
        for _ in range(10):
            all_links = report_frame.query_selector_all("a[href]")
            # Los IDs de Case en Salesforce empiezan con "500"
            # Filtramos explícitamente para no incluir links a Contact (003), Account (001), Owner (00G)
            case_links = [l for l in all_links if re.search(r"/lightning/r/500[A-Za-z0-9]+/view", l.get_attribute("href") or "")]
            print(f"  Links en frame: {len(all_links)} total, {len(case_links)} de casos")
            if case_links:
                found = True
                break
            # Mostrar sample de links para diagnóstico
            for l in all_links[:3]:
                print(f"    href={l.get_attribute('href')} text={l.inner_text()[:30]!r}")
            page.wait_for_timeout(3000)

        if not found:
            print("\nFAIL: links de casos no aparecieron en el frame.")
            page.screenshot(path="smoke_test_screenshot.png")
            browser.close()
            sys.exit(1)

        links = case_links
        casos = []
        for link in links:
            case_number = link.inner_text().strip()
            href = link.get_attribute("href") or ""
            match = RE_RECORD_ID.search(href)
            if case_number and match:
                casos.append({
                    "case_number": case_number,
                    "sf_record_id": match.group(1),
                })

        browser.close()

    if not casos:
        print("\nWARN: el selector funciono pero no se encontraron casos.")
        print("  Puede que el reporte este vacio o el selector necesite ajuste.")
        sys.exit(1)

    print(f"\nOK: {len(casos)} casos extraidos:")
    for caso in casos:
        print(f"  #{caso['case_number']}  ->  {caso['sf_record_id']}")

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
    args = parser.parse_args()
    main(args.cookies, args.headless)
