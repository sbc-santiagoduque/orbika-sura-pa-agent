"""
Infraestructura RPA: SalesforceCaseScraper
Extrae metadata y comentarios recientes de un caso de Salesforce Lightning.

Flujo:
  1. Carga storageState desde SSM via SalesforceSession
  2. Navega a /lightning/r/Case/{sf_record_id}/view
  3. Extrae: estado, asunto, fecha y comentarios del activity timeline

Re-login automático:
- Si la sesión expiró Playwright termina en la página de login (#username visible)
- Se invoca refresh_login() via orbika-login (async, incluye SMS/Telegram si está configurado)
- El nuevo storageState queda en SSM y se reintenta la navegación

Nota: Los selectores requieren validación con smoke test contra el org real.
      Ver scripts/smoke_test_review_historial_crm.py
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

# Tiempo máximo de espera para que el detalle del caso renderice
_PAGE_TIMEOUT_MS = 30_000

# Polling: cuántas veces intentar antes de rendirse (cada intento = 2s)
_MAX_POLL_ATTEMPTS = 10

# Máximo de comentarios a retornar (más recientes primero)
_MAX_COMMENTS = 10

# Patrón para limpiar espacios internos del texto scrapeado
_RE_WHITESPACE = re.compile(r"\s+")


class SalesforceCaseScraper:
    """
    Navega a un caso de Salesforce y extrae su metadata y comentarios.
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
        Resuelve case_number → sf_record_id, navega al caso y retorna su historial.

        Args:
            case_number: Número de caso visible (ej. "CF0975"). El sf_record_id
                         se resuelve internamente vía búsqueda global de Salesforce.

        Returns:
            {
                "sf_record_id": str,
                "case_number":  str,
                "status":       str,
                "subject":      str,
                "account_name": str,
                "created_date": str,
                "comments":     [{"fecha": str, "autor": str, "texto": str}, ...]
            }
        """
        from playwright.sync_api import sync_playwright
        from src.shared.browser.salesforce_case_resolver import resolve_sf_record_id

        logger.info(
            "Extrayendo historial CRM para case_number=%s", case_number,
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

            url = f"{_SF_BASE_URL}/lightning/r/Case/{sf_record_id}/view"
            logger.info(
                "Navegando a caso Salesforce",
                extra={"url": url, "sf_record_id": sf_record_id},
            )
            page.goto(url, wait_until="domcontentloaded")

            self._esperar_caso_cargado(page)

            resultado = {
                "sf_record_id": sf_record_id,
                **self._extraer_campos(page),
                "comments": self._extraer_comentarios(page),
            }

            browser.close()

        logger.info(
            "Historial extraido",
            extra={
                "sf_record_id": sf_record_id,
                "status": resultado.get("status"),
                "comments_count": len(resultado.get("comments", [])),
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

    def _esperar_caso_cargado(self, page) -> None:
        """
        Espera a que el encabezado del caso sea visible.

        Salesforce Lightning usa SPA — domcontentloaded llega antes de que
        el componente Lightning renderice los campos del caso.

        SMOKE_TEST_VALIDATE: confirmar que el selector 'h1' o el título del
        record page es visible y contiene el número de caso.
        """
        for attempt in range(_MAX_POLL_ATTEMPTS):
            page.wait_for_timeout(2_000)
            # El header de un record page en Lightning tiene el número de caso
            # en el elemento h1 dentro de .slds-page-header o similar
            header = page.query_selector("h1.slds-page-header__title, "
                                         "h1[class*='title'], "
                                         ".slds-page-header__name-title h1")
            if header and header.inner_text().strip():
                return
            # Fallback: buscar cualquier h1 con contenido
            all_h1 = page.query_selector_all("h1")
            for h1 in all_h1:
                text = h1.inner_text().strip()
                if text and len(text) > 2:
                    return
            logger.debug("Intento %d/%d — esperando header del caso", attempt + 1, _MAX_POLL_ATTEMPTS)

        logger.warning("Header del caso no encontrado tras polling — continuando de todas formas")

    def _extraer_campos(self, page) -> dict:
        """
        Extrae campos clave del detail panel del caso.

        Salesforce Lightning renderiza los campos en componentes
        'records-record-layout-item' con etiquetas en spans internos.

        SMOKE_TEST_VALIDATE: ajustar selectores según el layout real del org.
        Campos esperados: Case Number, Status, Subject, Account Name, Created Date.
        """
        campos = {
            "case_number": "",
            "status": "",
            "subject": "",
            "account_name": "",
            "created_date": "",
        }

        # Intentar extraer número de caso desde el header de la página
        # Salesforce muestra el Case Number como título del record
        h1_elements = page.query_selector_all("h1")
        for h1 in h1_elements:
            text = _limpiar(h1.inner_text())
            # Números de caso en Salesforce suelen ser all-digits, ej. "00001234"
            if re.match(r"^\d{5,10}$", text):
                campos["case_number"] = text
                break

        # Extraer campos del detail view usando el patrón de layout items
        # SMOKE_TEST_VALIDATE: el selector puede variar según la versión del org
        # Opciones comunes:
        #   - records-record-layout-item
        #   - force-record-layout-item
        #   - .slds-form__item
        layout_items = page.query_selector_all(
            "records-record-layout-item, force-record-layout-item, .slds-form__item"
        )

        for item in layout_items:
            # Etiqueta del campo (ej. "Status", "Subject")
            label_el = item.query_selector(
                "span.test-id__field-label, "
                ".slds-form-element__label span, "
                "label.slds-form-element__label"
            )
            # Valor del campo
            value_el = item.query_selector(
                "span.test-id__field-value lightning-formatted-text, "
                "lightning-formatted-text, "
                ".slds-form-element__control span, "
                "p.fieldComponent"
            )

            if not label_el or not value_el:
                continue

            label = _limpiar(label_el.inner_text()).lower()
            value = _limpiar(value_el.inner_text())

            if not value:
                continue

            # SMOKE_TEST_VALIDATE: confirmar que estos labels coinciden con el org
            if "status" in label or "estado" in label:
                campos["status"] = value
            elif "subject" in label or "asunto" in label:
                campos["subject"] = value
            elif "account" in label or "cuenta" in label:
                campos["account_name"] = value
            elif "created" in label or "creado" in label or "apertura" in label:
                campos["created_date"] = value

        return campos

    def _extraer_comentarios(self, page) -> list[dict]:
        """
        Extrae comentarios del Activity Timeline del caso.

        Salesforce Lightning muestra actividad en un timeline con items
        que pueden ser: Emails, Tareas, Notas, Comentarios de Caso.

        Nos interesan principalmente los Case Comments (notas del analista).

        SMOKE_TEST_VALIDATE: el selector del timeline puede variar.
        Opciones conocidas:
          - ul.slds-timeline > li  (timeline clásico)
          - c-activity-timeline  (LWC timeline moderno)
          - .activityAccordion  (accordion de actividad)
        """
        comentarios = []

        # Intentar con el timeline de Lightning Experience
        # SMOKE_TEST_VALIDATE: ajustar selector según versión del org
        timeline_items = page.query_selector_all(
            "ul.slds-timeline li, "
            ".slds-timeline__item, "
            "article.slds-card"
        )

        for item in timeline_items[:_MAX_COMMENTS * 2]:  # candidatos extra por si hay filtros
            comentario = self._parsear_item_timeline(item)
            if comentario:
                comentarios.append(comentario)
            if len(comentarios) >= _MAX_COMMENTS:
                break

        if not comentarios:
            logger.debug("Timeline vacío — buscando comentarios directos")
            # Fallback: buscar Case Comments directamente
            # SMOKE_TEST_VALIDATE: confirmar selector de case comments list
            comment_els = page.query_selector_all(
                ".slds-feed__item, "
                "[data-component-id*='comment'], "
                ".caseComment"
            )
            for el in comment_els[:_MAX_COMMENTS]:
                texto = _limpiar(el.inner_text())
                if texto:
                    comentarios.append({"fecha": "", "autor": "", "texto": texto[:500]})

        return comentarios

    def _parsear_item_timeline(self, item) -> dict | None:
        """
        Extrae fecha, autor y texto de un item del timeline.

        Retorna None si el item no tiene contenido relevante.
        """
        try:
            # Fecha del item
            fecha_el = item.query_selector(
                "abbr[title], time, .slds-timeline__date, a[title]"
            )
            fecha = _limpiar(fecha_el.get_attribute("title") or fecha_el.inner_text()) if fecha_el else ""

            # Autor
            autor_el = item.query_selector(
                ".slds-timeline__trigger .slds-truncate, "
                "a.slds-truncate, "
                "span.user-link"
            )
            autor = _limpiar(autor_el.inner_text()) if autor_el else ""

            # Texto principal del item
            texto_el = item.query_selector(
                ".slds-timeline__item-detail p, "
                ".emailBody, "
                ".noteBody, "
                ".slds-note__text, "
                "p.slds-text-body--regular"
            )
            texto = _limpiar(texto_el.inner_text()) if texto_el else _limpiar(item.inner_text())

            # Filtrar items sin contenido útil (headers de sección, etc.)
            if not texto or len(texto) < 5:
                return None

            return {
                "fecha": fecha[:50],
                "autor": autor[:100],
                "texto": texto[:500],
            }
        except Exception as exc:
            logger.debug("Error parseando item timeline: %s", exc)
            return None


def _limpiar(texto: str) -> str:
    """Normaliza whitespace y elimina caracteres de control."""
    if not texto:
        return ""
    return _RE_WHITESPACE.sub(" ", texto).strip()
