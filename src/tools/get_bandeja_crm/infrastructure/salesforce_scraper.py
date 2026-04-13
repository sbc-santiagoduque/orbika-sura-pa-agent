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

Re-login automático:
- Si la sesión expiró Playwright termina en la página de login (#username visible)
- Se invoca refresh_login() via orbika-login (async, incluye SMS/Telegram si está configurado)
- El nuevo storageState queda en SSM y se reintenta la navegación

Nota: Esta implementación será reemplazada por un cliente REST cuando
Sura Panamá habilite la API de Salesforce (ADR-U2-1).
"""
import logging
import re
from typing import Any

from src.shared.browser.session import SalesforceSession

logger = logging.getLogger(__name__)

# Patrón del href de un registro Case: /lightning/r/500{id}/view
_RE_CASE_HREF = re.compile(r"/lightning/r/(500[A-Za-z0-9]+)/view")

# Selector que identifica la página de login de Salesforce
_SEL_LOGIN = "#username"

_IFRAME_TIMEOUT_MS = 30_000
_MAX_POLL_ATTEMPTS = 10


class SalesforceScraper:
    """
    Scrapea el reporte de bandeja de Salesforce y retorna los casos
    en el orden definido por el reporte.
    """

    def __init__(
        self,
        ssm_cookies_path: str,
        report_url: str,
        ssm_username_path: str | None = None,
        ssm_password_path: str | None = None,
        sf_login_url: str | None = None,
        telegram_bot: Any | None = None,
    ):
        self._session = SalesforceSession(ssm_path=ssm_cookies_path)
        self._report_url = report_url
        self._ssm_username_path = ssm_username_path
        self._ssm_password_path = ssm_password_path
        self._sf_login_url = sf_login_url
        self._telegram_bot = telegram_bot

    def obtener_bandeja(self) -> list[dict]:
        """
        Navega al reporte y extrae todos los casos visibles.

        Si detecta que la sesión expiró, ejecuta re-login automático via
        orbika-login y reintenta la navegación.

        Returns:
            Lista ordenada de dicts con ``case_number`` y ``sf_record_id``.
        """
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = self._session.inject_storage_state(browser)
            page = context.new_page()
            page.goto(self._report_url, wait_until="domcontentloaded")

            if self._es_pagina_login(page):
                logger.info("Sesion Salesforce expirada — ejecutando re-login automatico")
                context.close()
                self._refresh_login()
                context = self._session.inject_storage_state(browser)
                page = context.new_page()
                page.goto(self._report_url, wait_until="domcontentloaded")

            report_frame = self._esperar_iframe_reporte(page)
            casos = self._extraer_casos(page, report_frame)
            browser.close()

        return casos

    def _es_pagina_login(self, page) -> bool:
        return page.locator(_SEL_LOGIN).count() > 0

    def _refresh_login(self) -> None:
        if not all([self._ssm_username_path, self._ssm_password_path, self._sf_login_url]):
            raise RuntimeError(
                "Sesion Salesforce expirada y no hay credenciales configuradas para re-login. "
                "Configura SSM_SF_USERNAME_PATH, SSM_SF_PASSWORD_PATH y SF_LOGIN_URL."
            )
        self._session.refresh_login(
            sf_url=self._sf_login_url,
            ssm_username_path=self._ssm_username_path,
            ssm_password_path=self._ssm_password_path,
            telegram_bot=self._telegram_bot,
        )

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
        Filtra por prefijo "500" para excluir links a Contact, Account y Owner.
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
