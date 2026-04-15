"""
Infraestructura RPA: SalesforceAttachmentsScraper
Extrae los documentos adjuntos de un caso desde Salesforce Lightning CRM.

Flujo:
  1. Carga storageState desde SSM via SalesforceSession
  2. Navega a /lightning/r/Case/{sf_record_id}/related/CombinedAttachments/view
  3. Espera que la tabla de attachments renderice (SPA polling)
  4. Extrae cada fila: title, content_document_id, file_type, last_modified,
     created_by, size

Re-login automático:
- Si la sesión expiró Playwright termina en la página de login (#username visible)
- Se invoca refresh_login() via orbika-login
- El nuevo storageState queda en SSM y se reintenta la navegación

Selectores validados contra HTML de:
  surapa.lightning.force.com/lightning/r/Case/.../related/CombinedAttachments/view
"""
import logging
import re
from typing import Any

from src.shared.browser.session import SalesforceSession

logger = logging.getLogger(__name__)

_SF_BASE_URL = "https://surapa.lightning.force.com"
_SEL_LOGIN = "#username"

_MAX_POLL_ATTEMPTS = 10
_RE_WHITESPACE = re.compile(r"\s+")

# Extrae el ContentDocument ID del href de cada fila
# Ejemplo: /lightning/r/ContentDocument/069VY00000eY8CHYA0/view
_RE_DOC_HREF = re.compile(r"/lightning/r/ContentDocument/([A-Za-z0-9]+)/view")

# Selector del thead — señal de que la página terminó de renderizar
_SEL_TABLE_THEAD = (
    "table.uiVirtualDataTable thead, "
    "table[role='grid'] thead"
)

# Selector de filas de datos
_SEL_TABLE_ROWS = (
    "table.uiVirtualDataTable tbody tr, "
    "table[role='grid'] tbody tr"
)


class SalesforceAttachmentsScraper:
    """
    Navega a la vista CombinedAttachments de un caso de Salesforce
    y retorna la lista completa de documentos adjuntos.
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

    def obtener_documentos(self, case_number: str) -> dict:
        """
        Resuelve case_number → sf_record_id y navega a la vista de attachments.

        Args:
            case_number: Número de caso visible (ej. "CF0975"). El sf_record_id
                         se resuelve internamente vía búsqueda global de Salesforce.

        Returns:
            {
                "sf_record_id": str,
                "imagen_count": int,   # len(documentos) — compatible con validate_documentos
                "documentos": [
                    {
                        "title":                str,
                        "content_document_id":  str,
                        "file_type":            str,  # "pdf" | "image" | "word" | "excel" | "unknown"
                        "last_modified":        str,
                        "created_by":           str,
                        "size":                 str,  # "67 KB"
                    }
                ]
            }
        """
        from playwright.sync_api import sync_playwright
        from src.shared.browser.salesforce_case_resolver import resolve_sf_record_id

        logger.info(
            "Extrayendo documentos CRM para case_number=%s", case_number,
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

            # Resolver case_number → sf_record_id via búsqueda global
            sf_record_id = resolve_sf_record_id(page, case_number)

            url = (
                f"{_SF_BASE_URL}/lightning/r/Case/{sf_record_id}"
                f"/related/CombinedAttachments/view"
            )
            logger.info(
                "Navegando a attachments del caso",
                extra={"url": url, "sf_record_id": sf_record_id},
            )
            page.goto(url, wait_until="domcontentloaded")

            self._esperar_tabla_cargada(page)
            documentos = self._extraer_documentos(page)
            browser.close()

        logger.info(
            "Documentos CRM extraidos",
            extra={"sf_record_id": sf_record_id, "total": len(documentos)},
        )
        return {
            "sf_record_id": sf_record_id,
            "imagen_count": len(documentos),
            "documentos": documentos,
        }

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

    def _esperar_tabla_cargada(self, page) -> None:
        """
        Espera hasta que el thead de la tabla de attachments sea visible.

        Salesforce Lightning usa SPA — domcontentloaded llega antes de que
        el componente Lightning renderice la tabla de archivos.
        """
        for attempt in range(_MAX_POLL_ATTEMPTS):
            page.wait_for_timeout(2_000)
            if page.query_selector(_SEL_TABLE_THEAD):
                return
            logger.debug(
                "Intento %d/%d — esperando tabla de attachments",
                attempt + 1,
                _MAX_POLL_ATTEMPTS,
            )
        logger.warning(
            "Tabla de attachments no encontrada tras polling — "
            "puede haber 0 documentos o error de carga"
        )

    def _extraer_documentos(self, page) -> list[dict]:
        """Extrae todos los documentos de las filas de la tabla."""
        rows = page.query_selector_all(_SEL_TABLE_ROWS)
        documentos = []
        for row in rows:
            doc = self._parsear_fila(row)
            if doc:
                documentos.append(doc)
        return documentos

    def _parsear_fila(self, row) -> dict | None:
        """
        Extrae los campos de una fila de la tabla de attachments.

        Estructura HTML de cada <tr>:
          td (error col) | th[scope='row'] (título + ID) | td (last_mod) |
          td (created_by) | td (size) | td (source) | td (actions)
        """
        # ContentDocument ID desde el href del link en th[scope='row']
        title_link = row.query_selector("th[scope='row'] a")
        if not title_link:
            return None

        href = title_link.get_attribute("href") or ""
        match = _RE_DOC_HREF.search(href)
        if not match:
            return None
        content_document_id = match.group(1)

        # Título del documento (atributo title preferido; inner_text como fallback)
        title_el = title_link.query_selector("span.itemTitle")
        title = ""
        if title_el:
            title = (
                title_el.get_attribute("title") or title_el.inner_text()
            ).strip()

        # Tipo de archivo desde el texto del ícono (span.slds-assistive-text)
        type_el = title_link.query_selector("span.slds-assistive-text")
        file_type_raw = type_el.inner_text().strip() if type_el else ""
        file_type = _normalizar_tipo(file_type_raw)

        # Última modificación (primer uiOutputDateTime en las celdas td)
        last_mod_el = row.query_selector("td span.uiOutputDateTime")
        last_modified = last_mod_el.inner_text().strip() if last_mod_el else ""

        # Creado por (atributo title preferido; inner_text como fallback)
        created_by_el = row.query_selector("td a.forceOutputLookup")
        created_by = ""
        if created_by_el:
            created_by = (
                created_by_el.get_attribute("title") or created_by_el.inner_text()
            ).strip()

        # Tamaño del archivo
        size_num_el = row.query_selector(".fileSizeAmount")
        size_unit_el = row.query_selector(".fileSizeUnits")
        size = ""
        if size_num_el and size_unit_el:
            size = f"{size_num_el.inner_text().strip()} {size_unit_el.inner_text().strip()}"

        return {
            "title": title,
            "content_document_id": content_document_id,
            "file_type": file_type,
            "last_modified": last_modified,
            "created_by": created_by,
            "size": size,
        }


def _normalizar_tipo(raw: str) -> str:
    """Normaliza el tipo de archivo desde el texto del ícono asistivo de Salesforce."""
    lower = raw.lower()
    if "pdf" in lower:
        return "pdf"
    if "image" in lower or "photo" in lower or "imagen" in lower:
        return "image"
    if "word" in lower or "doc" in lower:
        return "word"
    if "excel" in lower or "spreadsheet" in lower or "csv" in lower:
        return "excel"
    return "unknown"


def _limpiar(texto: str) -> str:
    if not texto:
        return ""
    return _RE_WHITESPACE.sub(" ", texto).strip()
