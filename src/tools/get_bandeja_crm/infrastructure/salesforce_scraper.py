"""
Infraestructura RPA: SalesforceScraper
Extrae la bandeja de casos activos de Salesforce usando Playwright.

Nota: Esta implementación será reemplazada por un cliente REST cuando
Sura Panamá habilite la API de Salesforce (ADR-U2-1).
"""
from playwright.sync_api import sync_playwright

from src.shared.browser.session import SalesforceSession


class SalesforceScraper:
    """
    Scrapea la vista "Mis Casos Abiertos" de Salesforce y retorna
    los casos en formato crudo (sin priorizar).

    Usa cookies persistidas en SSM para evitar re-autenticación con 2FA.
    """

    # Selectores CSS de la lista de casos en Salesforce Lightning
    _SELECTOR_TABLA = "table.slds-table"
    _SELECTOR_FILAS = "tbody tr"

    def __init__(self, ssm_cookies_path: str, base_url: str):
        self._session = SalesforceSession(ssm_path=ssm_cookies_path)
        self._base_url = base_url
        # URL de la vista de bandeja — ajustar según la org de Sura Panamá
        self._bandeja_url = f"{base_url}/lightning/o/Case/list?filterName=Mis_Casos_Abiertos"

    def obtener_bandeja(self) -> list[dict]:
        """
        Navega a Salesforce y extrae los casos de la bandeja.

        Returns:
            Lista de dicts con: case_id, placa, canal,
            fecha_siniestro, fecha_recepcion, sla_alert
        """
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context()

            # Inyectar cookies para saltar el 2FA
            self._session.inject_cookies(context)

            page = context.new_page()
            page.goto(self._bandeja_url, wait_until="networkidle")

            # Esperar a que la tabla cargue
            page.wait_for_selector(self._SELECTOR_TABLA, timeout=15_000)

            casos = self._extraer_casos(page)

            browser.close()

        return casos

    def _extraer_casos(self, page) -> list[dict]:
        """
        Extrae cada fila de la tabla y la mapea al modelo de dominio.

        Los índices de columna asumen la configuración de Salesforce de Sura Panamá:
        0: Case ID, 1: Placa, 2: Canal, 3: Fecha Siniestro,
        4: Fecha Recepción, 5: SLA
        """
        casos = []
        filas = page.query_selector_all(self._SELECTOR_FILAS)

        for fila in filas:
            celdas = fila.query_selector_all("td")
            if len(celdas) < 6:
                continue

            # SLA en riesgo: la celda suele tener un ícono de alerta
            sla_alert = "sla-alert" in (celdas[5].get_attribute("class") or "")

            casos.append({
                "case_id": celdas[0].inner_text().strip(),
                "placa": celdas[1].inner_text().strip(),
                "canal": celdas[2].inner_text().strip(),
                "fecha_siniestro": celdas[3].get_attribute("data-value") or celdas[3].inner_text().strip(),
                "fecha_recepcion": celdas[4].get_attribute("data-value") or celdas[4].inner_text().strip(),
                "sla_alert": sla_alert,
            })

        return casos
