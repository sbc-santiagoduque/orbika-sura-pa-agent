"""
Infraestructura RPA: SalesforceCaseScraper
Extrae los comentarios (CaseComments) de un caso de Salesforce Lightning.

Flujo:
  1. Carga storageState desde SSM via SalesforceSession
  2. Resuelve case_number → sf_record_id via reporte de bandeja
  3. Navega a /lightning/r/Case/{sf_record_id}/related/CaseComments/view
  4. Extrae la tabla de comentarios (misma estructura uiVirtualDataTable que
     usa la pantalla de attachments — thead/tbody con selectores idénticos)

Re-login automático:
- Si la sesión expiró Playwright termina en la página de login (#username visible)
- Se invoca refresh_login() via orbika-login (async, incluye SMS/Telegram)
- El nuevo storageState queda en SSM y se reintenta la navegación

Selectores validados contra el org real (Sura Panamá, 2026-04-15):
  th[scope='row'] a.forceOutputLookup  → autor del comentario
  span.uiOutputCheckbox img            → campo Public (aria-checked)
  span.uiOutputDateTime                → fecha del comentario
  span.forceListViewManagerGridWrapText → texto del comentario
"""
import logging
import re
from typing import Any

from src.shared.browser.session import SalesforceSession

logger = logging.getLogger(__name__)

# Prefijo URL del org de Sura Panamá
_SF_BASE_URL = "https://surapa.lightning.force.com"

# Selector que identifica la página de login de Salesforce
_SEL_LOGIN = "#username"

# Selectores de la tabla CaseComments (uiVirtualDataTable)
_SEL_TABLE_READY = "table.slds-table thead"
_SEL_ROWS = "table.slds-table tbody tr"
_SEL_USER_LINK = "th[scope='row'] a.forceOutputLookup"
_SEL_PUBLIC_IMG = "span.uiOutputCheckbox img"
_SEL_FECHA = "span.uiOutputDateTime"
_SEL_TEXTO = "span.forceListViewManagerGridWrapText"

# Polling
_MAX_POLL_ATTEMPTS = 10
_POLL_WAIT_MS = 2_000

# Polling extra para filas tbody (SPA Lightning renderiza thead antes que tbody)
_MAX_ROW_ATTEMPTS = 8
_ROW_WAIT_MS = 2_000

# Máximo de comentarios a retornar (más recientes primero)
_MAX_COMMENTS = 10

# Regex para normalización de whitespace
_RE_WHITESPACE = re.compile(r"\s+")
_RE_SPACES = re.compile(r"[ \t]+")
_RE_EXCESS_NEWLINES = re.compile(r"\n{3,}")


class SalesforceCaseScraper:
    """
    Navega a la vista de CaseComments de un caso de Salesforce
    y extrae los comentarios de la tabla.
    """

    def __init__(
        self,
        ssm_cookies_path: str,
        ssm_username_path: str | None = None,
        ssm_password_path: str | None = None,
        sf_login_url: str | None = None,
        telegram_bot: Any | None = None,
    ):
        self._session = SalesforceSession(ssm_path=ssm_cookies_path)
        self._ssm_username_path = ssm_username_path
        self._ssm_password_path = ssm_password_path
        self._sf_login_url = sf_login_url
        self._telegram_bot = telegram_bot

    def obtener_historial(self, case_number: str) -> dict:
        """
        Resuelve case_number → sf_record_id, navega a CaseComments
        y retorna los comentarios del caso.

        Args:
            case_number: Número de caso visible (ej. "CF0975").

        Returns:
            {
                "sf_record_id": str,
                "case_number":  str,
                "comments": [
                    {
                        "autor":      str,
                        "fecha":      str,
                        "texto":      str,
                        "es_publico": bool,
                    },
                    ...
                ]
            }
        """
        from playwright.sync_api import sync_playwright
        from src.shared.browser.salesforce_case_resolver import resolve_sf_record_id

        logger.info(
            "Extrayendo comentarios CRM para case_number=%s", case_number,
            extra={"case_number": case_number},
        )

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = self._session.inject_storage_state(browser)
            page = context.new_page()

            if self._es_pagina_login(page):
                logger.info("Sesion Salesforce expirada — ejecutando re-login automatico")
                context.close()
                self._refresh_login()
                context = self._session.inject_storage_state(browser)
                page = context.new_page()

            sf_record_id = resolve_sf_record_id(page, case_number)

            url = (
                f"{_SF_BASE_URL}/lightning/r/Case/{sf_record_id}"
                "/related/CaseComments/view"
            )
            logger.info(
                "Navegando a CaseComments",
                extra={"url": url, "sf_record_id": sf_record_id},
            )
            page.goto(url, wait_until="domcontentloaded")

            self._esperar_tabla_cargada(page)
            comments = self._extraer_comentarios(page)
            browser.close()

        resultado = {
            "sf_record_id": sf_record_id,
            "case_number": case_number,
            "comments": comments,
        }

        logger.info(
            "Comentarios extraidos",
            extra={
                "sf_record_id": sf_record_id,
                "comments_count": len(comments),
            },
        )
        return resultado

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

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _esperar_tabla_cargada(self, page) -> None:
        """
        Espera a que el thead de la tabla CaseComments sea visible.

        Salesforce Lightning SPA — domcontentloaded llega antes de que
        el componente de la tabla renderice. Misma estrategia que
        attachments scraper.
        """
        for attempt in range(_MAX_POLL_ATTEMPTS):
            page.wait_for_timeout(_POLL_WAIT_MS)
            if page.query_selector(_SEL_TABLE_READY):
                logger.debug("Tabla CaseComments lista (intento %d)", attempt + 1)
                return
            logger.debug(
                "Intento %d/%d — esperando tabla CaseComments...",
                attempt + 1,
                _MAX_POLL_ATTEMPTS,
            )
        logger.warning(
            "Tabla CaseComments no encontrada tras %d intentos — continuando",
            _MAX_POLL_ATTEMPTS,
        )

    def _esperar_filas(self, page) -> list:
        """
        Espera a que tbody tenga filas (SPA renderiza thead antes que tbody).
        Retorna las filas encontradas o lista vacía si se agota el polling.
        """
        for attempt in range(_MAX_ROW_ATTEMPTS):
            page.wait_for_timeout(_ROW_WAIT_MS)
            rows = page.query_selector_all(_SEL_ROWS)
            if rows:
                logger.debug("Filas tbody listas (intento %d): %d filas", attempt + 1, len(rows))
                return rows
            logger.debug(
                "Intento %d/%d — esperando filas tbody...",
                attempt + 1,
                _MAX_ROW_ATTEMPTS,
            )
        logger.warning("No se encontraron filas en tbody tras polling")
        return []

    def _extraer_comentarios(self, page) -> list[dict]:
        """
        Extrae los comentarios de la tabla CaseComments.
        """
        rows = self._esperar_filas(page)
        comentarios = []
        for row in rows:
            comentario = self._parsear_fila(row)
            if comentario:
                comentarios.append(comentario)
            if len(comentarios) >= _MAX_COMMENTS:
                break
        return comentarios

    def _parsear_fila(self, row) -> dict | None:
        """
        Extrae autor, fecha, texto y es_publico de una fila <tr> de CaseComments.

        Estructura de la tabla (validada 2026-04-15):
          th[scope='row'] a.forceOutputLookup  → autor (attr title o inner_text)
          span.uiOutputCheckbox img            → es_publico (attr aria-checked)
          span.uiOutputDateTime                → fecha (inner_text)
          span.forceListViewManagerGridWrapText → texto (inner_text, puede tener \\n de <br>)

        Retorna None si la fila no tiene link de usuario o texto vacío.
        """
        try:
            user_link = row.query_selector(_SEL_USER_LINK)
            if not user_link:
                return None

            autor = _limpiar(
                user_link.get_attribute("title") or user_link.inner_text()
            )

            public_img = row.query_selector(_SEL_PUBLIC_IMG)
            es_publico = False
            if public_img:
                aria_checked = public_img.get_attribute("aria-checked") or ""
                es_publico = aria_checked.lower() == "true"

            fecha_el = row.query_selector(_SEL_FECHA)
            fecha = _limpiar(fecha_el.inner_text()) if fecha_el else ""

            texto_el = row.query_selector(_SEL_TEXTO)
            texto = _limpiar_texto(texto_el.inner_text()) if texto_el else ""

            if not texto:
                return None

            return {
                "autor": autor,
                "fecha": fecha,
                "texto": texto[:2000],
                "es_publico": es_publico,
            }
        except Exception as exc:
            logger.debug("Error parseando fila CaseComment: %s", exc)
            return None


def _limpiar(texto: str) -> str:
    """Normaliza whitespace y elimina caracteres de control."""
    if not texto:
        return ""
    return _RE_WHITESPACE.sub(" ", texto).strip()


def _limpiar_texto(texto: str) -> str:
    """
    Normaliza texto de comentario preservando saltos de línea significativos.

    Playwright convierte <br> en \\n — estos son relevantes para formatear
    comentarios multilínea (ej. notas con bullet points).
    """
    if not texto:
        return ""
    # Normalizar espacios/tabs dentro de cada línea (sin tocar newlines)
    texto = _RE_SPACES.sub(" ", texto)
    # Colapsar 3+ newlines consecutivos a 2
    texto = _RE_EXCESS_NEWLINES.sub("\n\n", texto)
    return texto.strip()
