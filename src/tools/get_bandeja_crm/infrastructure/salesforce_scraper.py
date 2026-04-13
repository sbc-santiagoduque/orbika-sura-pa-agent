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
- La tabla tiene thead con headers y tbody con filas de datos

Columnas extraídas del reporte:
  case_number, sf_record_id, opened_date, last_modified, subestado_autos,
  placa, contact_name, account_name, case_origin, expediente_sic,
  numero_reclamo_core

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

# Mapeo de headers del reporte (lowercase, sin tildes) → nombre de campo output.
# Incluye variantes en inglés y español por si cambia el idioma del org.
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

# Campos que siempre deben estar presentes en cada caso (con valor vacío si no se encontraron)
_REQUIRED_FIELDS = [
    "case_number",
    "sf_record_id",
    "opened_date",
    "last_modified",
    "subestado_autos",
    "placa",
    "contact_name",
    "account_name",
    "case_origin",
    "expediente_sic",
    "numero_reclamo_core",
]


class SalesforceScraper:
    """
    Scrapea el reporte de bandeja de Salesforce y retorna los casos
    en el orden definido por el reporte con todos sus campos.
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
        Navega al reporte y extrae todos los casos con sus campos completos.

        Si detecta que la sesión expiró, ejecuta re-login automático via
        orbika-login y reintenta la navegación.

        Returns:
            Lista ordenada de dicts con todos los campos del reporte:
            case_number, sf_record_id, opened_date, last_modified,
            subestado_autos, placa, contact_name, account_name,
            case_origin, expediente_sic, numero_reclamo_core.
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
            casos = self._extraer_casos(report_frame)
            browser.close()

        logger.info(
            "Bandeja extraida",
            extra={"total_casos": len(casos), "report_url": self._report_url},
        )
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
                    case_links = [
                        l for l in links
                        if _RE_CASE_HREF.search(l.get_attribute("href") or "")
                    ]
                    if case_links:
                        return frame

        raise TimeoutError(
            f"El iframe del reporte no cargó los casos en "
            f"{_MAX_POLL_ATTEMPTS * 3}s. URL: {self._report_url}"
        )

    # ------------------------------------------------------------------
    # Extracción de tabla
    # ------------------------------------------------------------------

    def _extraer_casos(self, frame) -> list[dict]:
        """
        Extrae todos los campos de cada fila del reporte.

        Estrategia:
        1. Leer headers del thead → construir mapping columna_index → nombre_campo
        2. Por cada fila del tbody → extraer celdas, mapear a campos
        3. Obtener sf_record_id del primer link con href de Case en la fila

        Selectores con fallback para distintas versiones del grid de Salesforce:
          - table > thead/tbody  (tabular report clásico)
          - [role=grid] > [role=row]  (ARIA grid)
        """
        column_map = self._leer_columnas(frame)

        if not column_map:
            logger.warning(
                "No se encontraron headers en el reporte — "
                "fallback a extracción solo por links de caso"
            )
            return self._extraer_casos_fallback(frame)

        logger.debug("Columnas mapeadas: %s", column_map)

        rows = self._obtener_filas_datos(frame)
        casos = []

        for row in rows:
            caso = self._parsear_fila(row, column_map)
            if caso:
                casos.append(caso)

        return casos

    def _leer_columnas(self, frame) -> dict[int, str]:
        """
        Lee los headers del reporte y retorna {index: field_name}.

        Intenta múltiples selectores de header para adaptarse a distintas
        versiones del reporte de Salesforce Lightning.
        """
        # Intentar con thead > tr > th
        header_cells = frame.query_selector_all("thead tr th")
        if not header_cells:
            # Fallback: primera fila de la tabla
            header_cells = frame.query_selector_all("table tr:first-child td, table tr:first-child th")
        if not header_cells:
            # Fallback ARIA grid
            header_cells = frame.query_selector_all("[role='columnheader']")

        column_map = {}
        for idx, cell in enumerate(header_cells):
            label = _normalizar(cell.inner_text())
            field = _HEADER_TO_FIELD.get(label)
            if field:
                column_map[idx] = field
                logger.debug("Columna %d: %r → %s", idx, label, field)
            else:
                logger.debug("Columna %d: %r → sin mapeo", idx, label)

        return column_map

    def _obtener_filas_datos(self, frame) -> list:
        """
        Retorna los elementos de fila del cuerpo del reporte.
        """
        # Intentar tbody > tr
        rows = frame.query_selector_all("tbody tr")
        if rows:
            return rows

        # Fallback ARIA grid: filas de datos (excluir la fila de headers)
        all_rows = frame.query_selector_all("[role='row']")
        # La primera suele ser el header — filtrar las que tienen gridcell
        data_rows = [
            r for r in all_rows
            if r.query_selector("[role='gridcell']") is not None
        ]
        return data_rows

    def _parsear_fila(self, row, column_map: dict[int, str]) -> dict | None:
        """
        Extrae los campos de una fila usando el mapeo de columnas.

        Busca el sf_record_id en cualquier link de la fila con href de Case.
        """
        # Obtener todas las celdas de la fila
        cells = row.query_selector_all("td, [role='gridcell']")
        if not cells:
            return None

        caso = {field: "" for field in _REQUIRED_FIELDS}

        # Extraer texto de cada celda según columna mapeada
        for idx, cell in enumerate(cells):
            field = column_map.get(idx)
            if not field:
                continue
            caso[field] = cell.inner_text().strip()

        # Extraer sf_record_id del primer link de Case en la fila
        sf_record_id = ""
        for link in row.query_selector_all("a[href]"):
            href = link.get_attribute("href") or ""
            match = _RE_CASE_HREF.search(href)
            if match:
                sf_record_id = match.group(1)
                # Si case_number no fue extraído por columna, usar el texto del link
                if not caso.get("case_number"):
                    caso["case_number"] = link.inner_text().strip()
                break

        if not sf_record_id:
            # Fila sin case link — probablemente totales o separador, descartar
            return None

        caso["sf_record_id"] = sf_record_id
        return caso

    def _extraer_casos_fallback(self, frame) -> list[dict]:
        """
        Fallback cuando no hay headers de tabla detectados.
        Extrae solo case_number y sf_record_id (comportamiento original).
        """
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


def _normalizar(texto: str) -> str:
    """
    Normaliza el texto de un header para el lookup en _HEADER_TO_FIELD.
    Lowercase + colapsar espacios. No elimina tildes para no perder información,
    el dict incluye variantes con y sin tildes.
    """
    if not texto:
        return ""
    return re.sub(r"\s+", " ", texto).strip().lower()
