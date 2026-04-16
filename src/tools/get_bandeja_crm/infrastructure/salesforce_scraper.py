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
- Headers en span.lightning-table-cell-measure-header-value con índice en id
  Ej: id="fixed-row-data-grid-7-fixedrow0-col0-value" → col0 = columna 0

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

        # Intentar con filas de tabla (tbody/tr o ARIA grid)
        rows = self._obtener_filas_datos(frame)
        if rows:
            casos = []
            for row in rows:
                caso = self._parsear_fila(row, column_map)
                if caso:
                    casos.append(caso)
            if casos:
                return casos

        # Fallback: Lightning report grid con celdas sueltas por span-id
        logger.debug("Sin filas de tabla — intentando parseo Lightning grid por span-id")
        casos = self._parsear_grid_lightning(frame, column_map)
        if casos:
            return casos

        logger.warning("No se pudieron extraer filas con ninguna estrategia")
        return self._extraer_casos_fallback(frame)

    def _leer_columnas(self, frame) -> dict[int, str]:
        """
        Lee los headers del reporte y retorna {index: field_name}.

        Selectores en orden de prioridad:
        1. span.lightning-table-cell-measure-header-value  (Lightning report grid)
           El índice de columna se extrae del atributo id: col{N}-value
        2. thead tr th  (tabla HTML clásica)
        3. [role='columnheader']  (ARIA grid genérico)
        """
        column_map = {}

        # ── Prioridad 1: Lightning report grid ────────────────────────
        header_spans = frame.query_selector_all(
            "span.lightning-table-cell-measure-header-value"
        )
        if header_spans:
            for span in header_spans:
                id_attr = span.get_attribute("id") or ""
                col_match = re.search(r"col(\d+)-value", id_attr)
                if not col_match:
                    continue
                col_idx = int(col_match.group(1))
                # Preferir title (incluye sección, ej. "Case Information : Opened Date")
                # pero usar inner_text como base para el mapeo (label limpio)
                label = _normalizar(span.inner_text())
                field = _HEADER_TO_FIELD.get(label)
                if field:
                    column_map[col_idx] = field
                    logger.debug("Columna %d: %r → %s", col_idx, label, field)
                else:
                    logger.debug("Columna %d: %r → sin mapeo", col_idx, label)
            if column_map:
                return column_map

        # ── Prioridad 2: thead > tr > th ──────────────────────────────
        header_cells = frame.query_selector_all("thead tr th")
        if not header_cells:
            header_cells = frame.query_selector_all(
                "table tr:first-child td, table tr:first-child th"
            )
        if not header_cells:
            # ── Prioridad 3: ARIA grid ─────────────────────────────────
            header_cells = frame.query_selector_all("[role='columnheader']")

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

        Para el Lightning report grid (span.lightning-table-cell-measure-header-value),
        las filas de datos no viven en tbody/tr sino que cada celda es un span
        con id "fixed-row-data-grid-{N}-row{R}-col{C}-value".
        En ese caso retornamos la lista de filas agrupadas por row-index.
        """
        # ── Intentar tbody > tr ────────────────────────────────────────
        rows = frame.query_selector_all("tbody tr")
        if rows:
            return rows

        # ── Intentar ARIA grid con gridcell ───────────────────────────
        all_rows = frame.query_selector_all("[role='row']")
        data_rows = [
            r for r in all_rows
            if r.query_selector("[role='gridcell']") is not None
        ]
        if data_rows:
            return data_rows

        return []

    def _parsear_fila(self, row, column_map: dict[int, str]) -> dict | None:
        """
        Extrae los campos de una fila usando el mapeo de columnas.

        Busca el sf_record_id en cualquier link de la fila con href de Case.
        """
        cells = row.query_selector_all("td, [role='gridcell']")
        if not cells:
            return None

        caso = {field: "" for field in _REQUIRED_FIELDS}

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
                if not caso.get("case_number"):
                    caso["case_number"] = link.inner_text().strip()
                break

        if not sf_record_id:
            return None

        caso["sf_record_id"] = sf_record_id
        return caso

    def _parsear_grid_lightning(self, frame, column_map: dict[int, str]) -> list[dict]:
        """
        Extrae filas del Lightning report grid cuando no hay tbody/tr.

        Busca spans con id matching "row{R}-col{C}-value" (excluye fixedrow = headers).
        Agrupa por row-index y construye cada caso.

        Ejemplo de id de celda: fixed-row-data-grid-7-row0-col2-value
        """
        _RE_DATA_CELL = re.compile(r"-row(\d+)-col(\d+)-value$")

        all_spans = frame.query_selector_all(
            "span[id*='-row'][id*='-col'][id*='-value']"
        )
        if not all_spans:
            return []

        # Agrupar celdas por row-index: {row_idx: {col_idx: span}}
        rows_dict: dict[int, dict[int, Any]] = {}
        for span in all_spans:
            id_attr = span.get_attribute("id") or ""
            m = _RE_DATA_CELL.search(id_attr)
            if not m:
                continue
            row_idx = int(m.group(1))
            col_idx = int(m.group(2))
            rows_dict.setdefault(row_idx, {})[col_idx] = span

        casos = []
        for row_idx in sorted(rows_dict.keys()):
            cols = rows_dict[row_idx]
            caso = {field: "" for field in _REQUIRED_FIELDS}

            for col_idx, span in cols.items():
                field = column_map.get(col_idx)
                if not field:
                    continue
                # Preferir link text si la celda contiene un link de Case
                link = span.query_selector("a[href]") if hasattr(span, "query_selector") else None
                if link:
                    href = link.get_attribute("href") or ""
                    match = _RE_CASE_HREF.search(href)
                    if match:
                        caso["sf_record_id"] = match.group(1)
                        caso[field] = link.inner_text().strip() or span.inner_text().strip()
                        continue
                caso[field] = span.inner_text().strip()

            if not caso.get("sf_record_id"):
                # Buscar sf_record_id en cualquier link del row span
                # (puede estar en una celda no mapeada)
                for col_span in cols.values():
                    for link in (col_span.query_selector_all("a[href]") if hasattr(col_span, "query_selector_all") else []):
                        href = link.get_attribute("href") or ""
                        match = _RE_CASE_HREF.search(href)
                        if match:
                            caso["sf_record_id"] = match.group(1)
                            break
                    if caso.get("sf_record_id"):
                        break

            if not caso.get("sf_record_id"):
                continue

            casos.append(caso)

        return casos

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
