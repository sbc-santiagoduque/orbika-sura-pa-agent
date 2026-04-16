"""
Scraper de Consulta Integral para obtener número de póliza y cobertura.

Consulta Integral es un web app que requiere VPN activa (FortiClient).
Provee: número de póliza, coberturas, suma asegurada, datos del vehículo.

Estado actual:
  PHASE A — Interfaz definida, implementación pendiente de:
    1. Confirmación de CLI VPN (FortiClient) para automatización
    2. Mapeo de selectores HTML de Consulta Integral

  Para desarrollo y pruebas sin VPN, usar ConsultaIntegralScraperStub.

Cuando esté implementado, el flujo será:
  1. Conectar VPN via FortiClient CLI (si no está activa)
  2. Playwright: navegar a CI → buscar por placa → extraer póliza + coberturas
  3. Retornar DatosPoliza estructurado

TODO: implementar _navegar_y_extraer() con Playwright una vez:
  - FortiClient CLI esté confirmado (en investigación)
  - Selectores de CI estén mapeados (requiere sesión con acceso a VPN)
"""
import logging

logger = logging.getLogger(__name__)


class ConsultaIntegralScraper:
    """
    Extrae número de póliza y coberturas desde Consulta Integral.

    Args:
        ci_base_url: URL base de Consulta Integral (desde variable de entorno CI_BASE_URL).
    """

    def __init__(self, ci_base_url: str):
        self._base_url = ci_base_url

    def obtener_datos_poliza(self, placa: str) -> dict:
        """
        Navega a Consulta Integral y extrae los datos de póliza para la placa.

        Args:
            placa: Placa del vehículo asegurado.

        Returns:
            {
                "numero_poliza": str,   — ej. "02-37-1252419-0"
                "cobertura": str,       — ej. "POR COLISION O VUELCO"
                "suma_asegurada": float — ej. 25000.0
            }

        Raises:
            NotImplementedError: mientras la implementación esté pendiente.
            RuntimeError: si Consulta Integral no es accesible (VPN inactiva).
        """
        # TODO: implementar con Playwright cuando FortiClient CLI esté confirmado
        #
        # Flujo esperado:
        #   page = await browser.new_page()
        #   await page.goto(f"{self._base_url}/consulta")
        #   await page.fill("#placa-input", placa)
        #   await page.click("#buscar-btn")
        #   poliza = await page.inner_text("#numero-poliza")
        #   cobertura = await page.inner_text(".cobertura-activa")
        #   ...
        #
        raise NotImplementedError(
            "ConsultaIntegralScraper pendiente de implementación. "
            "Requiere FortiClient CLI activo y selectores HTML mapeados. "
            "Usa ConsultaIntegralScraperStub para desarrollo."
        )


class ConsultaIntegralScraperStub:
    """
    Stub para desarrollo y pruebas sin VPN.

    Retorna datos hardcodeados basados en la placa. Útil para:
    - Tests unitarios
    - Desarrollo local sin VPN
    - Validar el flujo completo con datos conocidos

    NO usar en producción.
    """

    def __init__(self, datos_fijos: dict | None = None):
        self._datos = datos_fijos or {
            "numero_poliza": "02-37-0000000-0",
            "cobertura":     "POR COLISION O VUELCO",
            "suma_asegurada": 25000.0,
        }

    def obtener_datos_poliza(self, placa: str) -> dict:
        logger.warning(
            "ConsultaIntegralScraperStub activo — datos NO reales",
            extra={"placa": placa},
        )
        return {**self._datos}
