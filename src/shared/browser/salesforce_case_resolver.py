"""
Helper: resolve_sf_record_id
Resuelve case_number → sf_record_id navegando al reporte de bandeja de Salesforce.

Estrategia:
    El reporte de bandeja (el mismo que usa F1) está en un iframe de Lightning
    y contiene links a cada caso con href que expone el sf_record_id.
    Navegamos al reporte, esperamos el iframe, buscamos el link cuyo texto
    coincida con case_number y extraemos el ID del href.

Por qué esta estrategia y no búsqueda global:
    - El reporte funciona con cookies de sesión HTTP solamente (sin localStorage).
    - La búsqueda global requiere navegar al home de Salesforce, que sí necesita
      el token de dispositivo confiable en localStorage.
    - Todos los casos que procesan F2 y F6-CRM vienen de F1 (la bandeja),
      por lo que siempre estarán en el reporte.

Uso típico (dentro de un bloque sync_playwright ya autenticado):

    from src.shared.browser.salesforce_case_resolver import resolve_sf_record_id

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context()
        context.add_cookies(cookies)
        page = context.new_page()
        sf_record_id = resolve_sf_record_id(page, case_number)
"""
import logging
import os
import re

logger = logging.getLogger(__name__)

# URL del reporte de bandeja — misma que usa F1 (get_bandeja_crm)
# Configurable via env var para diferentes ambientes
_DEFAULT_REPORT_URL = (
    "https://surapa.lightning.force.com/lightning/r/Report/"
    "00OS6000006Sz9xMAC/view"
)

# Regex para extraer sf_record_id del href de un link de Case
# Ejemplo: /lightning/r/500VY00000YWjzMYAT/view
_RE_CASE_HREF = re.compile(r"/lightning/r/(500[A-Za-z0-9]+)/view")

_MAX_POLL_ATTEMPTS = 10
_POLL_WAIT_MS = 3_000


def resolve_sf_record_id(page, case_number: str) -> str:
    """
    Navega al reporte de bandeja y retorna el sf_record_id del case_number dado.

    Precondición: page debe tener cookies de sesión válidas de Salesforce.
                  No requiere localStorage (token de dispositivo confiable).

    Args:
        page:        Playwright Page con cookies de sesión inyectadas.
        case_number: Número de caso visible (ej. "02195167", "CF0975").

    Returns:
        sf_record_id (ej. "500VY00000YWjzMYAT").

    Raises:
        RuntimeError: si la sesión expiró, el reporte no carga o el case_number
                      no se encuentra en la bandeja.
    """
    report_url = os.environ.get("SF_REPORT_URL", _DEFAULT_REPORT_URL)

    logger.info(
        "Resolviendo sf_record_id via reporte de bandeja",
        extra={"case_number": case_number, "report_url": report_url},
    )

    page.goto(report_url, wait_until="domcontentloaded", timeout=30_000)

    # Detectar redirección al login (cookies expiradas)
    if page.locator("#username").count() > 0:
        raise RuntimeError(
            "Sesión de Salesforce expirada — redirigió al login. "
            "Exportar nuevas cookies con el plugin del browser."
        )

    # Esperar el iframe del reporte con links de Case
    report_frame = _esperar_iframe_con_casos(page)
    if not report_frame:
        raise RuntimeError(
            f"Iframe del reporte no encontrado tras {_MAX_POLL_ATTEMPTS} intentos. "
            "Verificar que SF_REPORT_URL sea accesible."
        )

    # Buscar el link cuyo texto coincida con case_number
    sf_record_id = _buscar_en_frame(report_frame, case_number)
    if not sf_record_id:
        raise RuntimeError(
            f"case_number={case_number!r} no encontrado en el reporte de bandeja. "
            "El caso puede no estar en la bandeja actual o el case_number no coincide."
        )

    logger.info(
        "sf_record_id resuelto via reporte",
        extra={"case_number": case_number, "sf_record_id": sf_record_id},
    )
    return sf_record_id


def _esperar_iframe_con_casos(page) -> object | None:
    """Espera hasta que el iframe del reporte tenga links de Case. Retorna el frame."""
    for attempt in range(_MAX_POLL_ATTEMPTS):
        page.wait_for_timeout(_POLL_WAIT_MS)
        for frame in page.frames:
            if "lightningReportApp" not in frame.url and "reportId" not in frame.url:
                continue
            links = frame.query_selector_all("a[href]")
            if any(_RE_CASE_HREF.search(l.get_attribute("href") or "") for l in links):
                logger.debug("Iframe del reporte listo (intento %d)", attempt + 1)
                return frame
        logger.debug("Intento %d/%d — esperando iframe del reporte...", attempt + 1, _MAX_POLL_ATTEMPTS)
    return None


def _buscar_en_frame(frame, case_number: str) -> str | None:
    """
    Busca en el frame del reporte el link cuyo texto sea case_number
    y retorna el sf_record_id del href.
    """
    for link in frame.query_selector_all("a[href]"):
        href = link.get_attribute("href") or ""
        match = _RE_CASE_HREF.search(href)
        if not match:
            continue
        text = link.inner_text().strip()
        if text == case_number:
            return match.group(1)
    return None
