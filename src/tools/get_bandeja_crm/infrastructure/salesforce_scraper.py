"""
Infraestructura RPA: SalesforceScraper
Extrae la lista de casos del reporte de Salesforce.

El reporte ya viene filtrado por Sura Panamá (solo casos a resolver),
por lo que no se aplica ningún filtro adicional. El orden del reporte
es el orden de procesamiento.

Nota: Esta implementación será reemplazada por un cliente REST cuando
Sura Panamá habilite la API de Salesforce (ADR-U2-1).
"""
import re

from playwright.sync_api import sync_playwright

from src.shared.browser.session import SalesforceSession

# Selector de los links de casos en el reporte.
# El atributo data-object-api-name="Case" es estable — lo genera
# Salesforce automáticamente para todos los links a registros Case.
_SELECTOR_CASE_LINKS = 'a[data-object-api-name="Case"]'

# Patrón del href de un registro Case en Salesforce Lightning:
# /lightning/r/{sf_record_id}/view
_RE_RECORD_ID = re.compile(r"/lightning/r/([^/]+)/view")


class SalesforceScraper:
    """
    Scrapea el reporte de bandeja de Salesforce y retorna los casos
    en el orden definido por el reporte.

    Usa cookies persistidas en SSM para evitar re-autenticación con 2FA.
    """

    def __init__(self, ssm_cookies_path: str, report_url: str):
        self._session = SalesforceSession(ssm_path=ssm_cookies_path)
        self._report_url = report_url

    def obtener_bandeja(self) -> list[dict]:
        """
        Navega al reporte y extrae todos los casos visibles.

        Returns:
            Lista ordenada de dicts con ``case_number`` y ``sf_record_id``.
            El orden refleja el orden del reporte en Salesforce.
        """
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context()
            self._session.inject_cookies(context)

            page = context.new_page()
            page.goto(self._report_url, wait_until="networkidle")

            # Esperar a que el grid del reporte termine de renderizar
            page.wait_for_selector(_SELECTOR_CASE_LINKS, timeout=20_000)

            casos = self._extraer_casos(page)
            browser.close()

        return casos

    def _extraer_casos(self, page) -> list[dict]:
        """
        Extrae case_number y sf_record_id de cada link de caso en el reporte.

        El DOM de Salesforce Analytics expone los links con:
          - texto: número de caso legible (ej. "02188582")
          - href:  /lightning/r/{sf_record_id}/view
          - data-object-api-name="Case" (selector estable)
        """
        links = page.query_selector_all(_SELECTOR_CASE_LINKS)
        casos = []

        for link in links:
            case_number = link.inner_text().strip()
            href = link.get_attribute("href") or ""
            match = _RE_RECORD_ID.search(href)

            if not case_number or not match:
                continue

            casos.append({
                "case_number": case_number,
                "sf_record_id": match.group(1),
            })

        return casos
