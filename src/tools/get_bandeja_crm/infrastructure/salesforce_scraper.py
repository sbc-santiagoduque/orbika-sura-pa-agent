"""
Infraestructura RPA: SalesforceScraper
Extrae la lista de casos del reporte de Salesforce Analytics.

El reporte ya viene filtrado por Sura Panamá (solo casos a resolver),
por lo que no se aplica ningún filtro adicional. El orden del reporte
es el orden de procesamiento.

Hallazgos del smoke test (2026-04-05):
- El reporte carga dentro de un iframe: reports/lightningReportApp.app
- El iframe tarda ~6-9s en renderizar el grid (2 intentos de polling)
- Los links a Cases tienen IDs que empiezan con "500" (prefijo Salesforce)
- Los links a Contact (003), Account (001) y Owner (00G) se descartan

Nota: Esta implementación será reemplazada por un cliente REST cuando
Sura Panamá habilite la API de Salesforce (ADR-U2-1).
"""
import re

from src.shared.browser.session import SalesforceSession

# Patrón del href de un registro Case: /lightning/r/500{id}/view
# El prefijo "500" es el key prefix de objetos Case en Salesforce
_RE_CASE_HREF = re.compile(r"/lightning/r/(500[A-Za-z0-9]+)/view")

# Tiempo máximo de espera para que el iframe del reporte aparezca
_IFRAME_TIMEOUT_MS = 30_000

# Polling: cuántas veces intentar antes de rendirse (cada intento = 3s)
_MAX_POLL_ATTEMPTS = 10


class SalesforceScraper:
    """
    Scrapea el reporte de bandeja de Salesforce y retorna los casos
    en el orden definido por el reporte.
    """

    def __init__(self, ssm_cookies_path: str, report_url: str):
        self._session = SalesforceSession(ssm_path=ssm_cookies_path)
        self._report_url = report_url

    def obtener_bandeja(self) -> list[dict]:
        """
        Navega al reporte y extrae todos los casos visibles.

        Returns:
            Lista ordenada de dicts con ``case_number`` y ``sf_record_id``.
        """
        from playwright.sync_api import sync_playwright  # lazy: no bloquea tests sin Playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            # new_context con storageState — incluye cookies + localStorage
            # (el localStorage tiene el token de dispositivo confiable para omitir 2FA)
            context = self._session.inject_storage_state(browser)

            page = context.new_page()
            # domcontentloaded porque Lightning nunca llega a networkidle
            page.goto(self._report_url, wait_until="domcontentloaded")

            report_frame = self._esperar_iframe_reporte(page)
            casos = self._extraer_casos(page, report_frame)

            browser.close()

        return casos

    def _esperar_iframe_reporte(self, page):
        """
        Espera a que el iframe de lightningReportApp cargue y tenga casos.
        Usa polling porque el SPA de Salesforce no emite eventos cuando el
        grid termina de renderizar.
        """
        for _ in range(_MAX_POLL_ATTEMPTS):
            page.wait_for_timeout(3_000)
            for frame in page.frames:
                if "lightningReportApp" in frame.url or "reportId" in frame.url:
                    links = frame.query_selector_all("a[href]")
                    case_links = [l for l in links if _RE_CASE_HREF.search(l.get_attribute("href") or "")]
                    if case_links:
                        return frame

        raise TimeoutError(
            f"El iframe del reporte no cargó los casos en "
            f"{_MAX_POLL_ATTEMPTS * 3}s. URL: {self._report_url}"
        )

    def _extraer_casos(self, page, report_frame) -> list[dict]:
        """
        Extrae case_number y sf_record_id de cada link de caso en el iframe.

        Filtra por prefijo "500" para excluir links a Contact, Account y Owner
        que también aparecen en el mismo reporte.
        """
        links = report_frame.query_selector_all("a[href]")
        casos = []

        for link in links:
            href = link.get_attribute("href") or ""
            match = _RE_CASE_HREF.search(href)
            if not match:
                continue

            case_number = link.inner_text().strip()
            if not case_number:
                continue

            casos.append({
                "case_number": case_number,
                "sf_record_id": match.group(1),
            })

        return casos
