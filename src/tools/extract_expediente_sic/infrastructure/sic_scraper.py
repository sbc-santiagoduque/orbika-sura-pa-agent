"""
Infraestructura RPA: SICScraper
Extrae el expediente de un caso desde sic.connectasistencia.com.

Flujo:
  1. Intentar sesión previa (storageState desde SSM)
  2. Si redirige a login → hacer login automático con user/pass
  3. Buscar por placa (MUI Select + input)
  4. Click en fila más reciente → nueva ventana
  5. Extraer conteo de imágenes y URLs S3

Ver: construccion/sic_rpa_findings.md
"""
from __future__ import annotations

import re
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page

from src.shared.browser.sic_session import SICSession

logger = logging.getLogger(__name__)

SIC_BASE_URL = "https://sic.connectasistencia.com"
SIC_LOGIN_URL = SIC_BASE_URL
SIC_SEARCH_URL = f"{SIC_BASE_URL}/events-claims"

# Selectores del login
_SEL_USERNAME = "input#username"
_SEL_PASSWORD = "input#password"
_SEL_SUBMIT = "button[type='submit']"

# Selectores de búsqueda
_SEL_FILTER_COMBO = "div[role='combobox']"
_SEL_PLATE_INPUT = "input[placeholder='Buscar Placa Asegurado']"
_SEL_RESULT_ROWS = "table[aria-label='simple table'] tbody tr"

# Selectores del expediente
_SEL_GALLERY_IMG    = "img[src*='amazonaws']"
_SEL_INSPECCION_TAB = "button[role='tab']:has-text('Inspección')"
_SEL_DOWNLOAD_BTN   = "button.claim-button"

# Opción del select que necesitamos
_FILTER_OPTION_TEXT = "Placa Asegurado"

# Patrón URL S3 de imágenes
_RE_S3_URL = re.compile(r"https://inspeccionespty\.s3[^\"' ]+\.jpg[^\"' ]*")


class SICScraper:
    """
    Scrapea el expediente de un siniestro en SIC dado el número de placa.
    """

    def __init__(self, session: SICSession):
        self._session = session

    def obtener_expediente(self, placa: str) -> dict:
        """
        Busca el expediente más reciente para la placa dada.

        Args:
            placa: Número de placa del vehículo (ej. "CU7559")

        Returns:
            Dict con:
              - placa: str
              - imagen_count: int  (Opción A — existencia)
              - imagen_urls: list[str]  (URLs S3 para Opción B futura — vision)
              - expediente_url: str
              - tiene_documentos: bool
        """
        from playwright.sync_api import sync_playwright  # lazy: no bloquea tests sin Playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = self._session.get_context(browser)
            page = context.new_page()

            # Navegar a búsqueda — puede redirigir a login si sesión expirada
            page.goto(SIC_SEARCH_URL, wait_until="domcontentloaded")

            if self._es_pagina_login(page):
                logger.info("Sesion SIC expirada — haciendo login automatico")
                self._hacer_login(page)
                # Guardar nuevo storageState para próximas invocaciones
                self._session.save_storage_state(context.storage_state())
                page.goto(SIC_SEARCH_URL, wait_until="domcontentloaded")

            resultado = self._buscar_y_extraer(page, context, placa)
            browser.close()

        return resultado

    def _es_pagina_login(self, page: Page) -> bool:
        return page.url.rstrip("/") == SIC_BASE_URL.rstrip("/")

    def _hacer_login(self, page: Page) -> None:
        """Completa el formulario de login con las credenciales de SSM."""
        username, password = self._session.load_credentials()

        page.goto(SIC_LOGIN_URL, wait_until="domcontentloaded")
        page.wait_for_selector(_SEL_USERNAME)
        page.fill(_SEL_USERNAME, username)
        page.fill(_SEL_PASSWORD, password)
        page.click(_SEL_SUBMIT)

        # Esperar a que navegue fuera del login
        page.wait_for_url(
            lambda url: url.rstrip("/") != SIC_BASE_URL.rstrip("/"),
            timeout=15_000,
        )

    def _buscar_y_extraer(self, page: Page, context, placa: str) -> dict:
        """Busca la placa y extrae el expediente de la primera fila."""
        self._buscar_placa(page, placa)

        # Esperar resultados y dejar que React reemplace skeletons con datos reales
        page.wait_for_selector(_SEL_RESULT_ROWS, timeout=10_000)
        page.wait_for_timeout(2_500)

        # Click en la primera fila → abre el expediente en nueva pestaña
        with context.expect_page() as new_page_info:
            page.locator(_SEL_RESULT_ROWS).first.click()
        expediente_page = new_page_info.value
        expediente_page.wait_for_load_state("domcontentloaded")
        # Navegar al tab Inspeccion — el expediente abre en el paso actual del flujo
        expediente_page.wait_for_selector(_SEL_INSPECCION_TAB, timeout=10_000)
        expediente_page.click(_SEL_INSPECCION_TAB)
        expediente_page.wait_for_selector(_SEL_GALLERY_IMG, timeout=30_000, state="attached")

        return self._extraer_datos_expediente(expediente_page)

    def _buscar_placa(self, page: Page, placa: str) -> None:
        """
        Interactúa con el MUI Select y el input para buscar por placa.
        MUI Select requiere click + esperar el listbox + click en la opción.
        """
        page.wait_for_selector(_SEL_FILTER_COMBO, timeout=10_000)

        # Abrir el dropdown
        page.click(_SEL_FILTER_COMBO)

        # Esperar y clickear la opción "Placa Asegurado"
        page.wait_for_selector(f"li[role='option']:has-text('{_FILTER_OPTION_TEXT}')")
        page.click(f"li[role='option']:has-text('{_FILTER_OPTION_TEXT}')")

        # Escribir la placa y presionar Enter para buscar
        page.wait_for_selector(_SEL_PLATE_INPUT)
        page.fill(_SEL_PLATE_INPUT, placa)
        page.press(_SEL_PLATE_INPUT, "Enter")

    def _extraer_datos_expediente(self, page: Page) -> dict:
        """Extrae conteo e URLs de imágenes del expediente.

        imagen_urls: URLs base S3 (sin firma) — referencia estable, no expira.
        imagen_urls_signed: URLs pre-firmadas (X-Amz-Expires=604800, 7 dias) —
            listas para pasar a Bedrock Vision (Opcion B) sin re-autenticacion.
        """
        imgs = page.query_selector_all(_SEL_GALLERY_IMG)

        imagen_urls = []
        imagen_urls_signed = []
        for img in imgs:
            src = img.get_attribute("src") or ""
            url_base = src.split("?")[0]
            if url_base:
                imagen_urls.append(url_base)
                imagen_urls_signed.append(src)

        return {
            "expediente_url": page.url,
            "imagen_count": len(imagen_urls),
            "imagen_urls": imagen_urls,
            "imagen_urls_signed": imagen_urls_signed,
            "tiene_documentos": len(imagen_urls) > 0,
        }
