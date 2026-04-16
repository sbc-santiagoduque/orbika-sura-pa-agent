"""
DataCollector — agrega datos de SIC y Consulta Integral en un DatosReclamo.

Responsabilidad:
  - Llama a SICReclamoClient para obtener datos del evento (conductor, siniestro)
  - Llama a ConsultaIntegralScraper para obtener póliza y cobertura
  - Aplica reglas de negocio (responsabilidad, tipo siniestro, reserva)
  - Retorna DatosReclamo listo para ser usado en Phase B (Premium RPA)

NO contiene lógica HTTP ni Playwright — eso vive en infrastructure/.
"""
import logging
import os
from datetime import date

from src.tools.create_reclamo_premium.infrastructure.sic_reclamo_client import (
    SICReclamoClient,
    _determinar_tipo_siniestro,
    _determinar_reserva,
)
from src.tools.create_reclamo_premium.infrastructure.consulta_integral_scraper import (
    ConsultaIntegralScraper,
    ConsultaIntegralScraperStub,
)
from src.tools.create_reclamo_premium.service.reclamo_models import (
    DatosReclamo,
    DatosConductor,
    DatosSiniestro,
    DatosPoliza,
)

logger = logging.getLogger(__name__)


class DataCollector:
    """
    Orquesta la recolección de datos para crear un reclamo en Premium.

    Args:
        sic_client: Instancia de SICReclamoClient (o mock en tests).
        ci_scraper: Instancia de ConsultaIntegralScraper o Stub.
    """

    def __init__(self, sic_client: SICReclamoClient, ci_scraper):
        self._sic = sic_client
        self._ci  = ci_scraper

    def recolectar(self, case_number: str, placa: str, expediente: str) -> DatosReclamo:
        """
        Recolecta todos los datos necesarios para abrir el reclamo.

        Args:
            case_number: Número de caso (ej. "02195167").
            placa:       Placa del vehículo asegurado.
            expediente:  Número de expediente SIC (eventRecord).

        Returns:
            DatosReclamo con toda la información lista para Phase B.
        """
        logger.info(
            "Iniciando recolección de datos para reclamo",
            extra={"case_number": case_number, "placa": placa, "expediente": expediente},
        )

        evento      = self._sic.obtener_datos_evento(placa, expediente)
        datos_poliza = self._ci.obtener_datos_poliza(placa)

        siniestro = self._extraer_siniestro(evento)
        conductor = self._extraer_conductor(evento)
        poliza    = self._extraer_poliza(datos_poliza)

        reclamo = DatosReclamo(
            case_number=case_number,
            numero_poliza=datos_poliza.get("numero_poliza", ""),
            siniestro=siniestro,
            conductor=conductor,
            poliza=poliza,
            ajustador_interno=158,
        )

        logger.info(
            "Datos de reclamo recolectados",
            extra={
                "case_number": case_number,
                "tipo_siniestro": siniestro.tipo,
                "responsabilidad": conductor.responsabilidad,
                "reserva": poliza.reserva,
            },
        )
        return reclamo

    # ------------------------------------------------------------------
    # Helpers de extracción y transformación
    # ------------------------------------------------------------------

    @staticmethod
    def _extraer_siniestro(evento: dict) -> DatosSiniestro:
        """Mapea campos del evento SIC a DatosSiniestro."""
        fecha_raw    = evento.get("eventDate", "")
        fecha        = fecha_raw[:10] if fecha_raw else ""   # "2026-03-03T13:50:00Z" → "2026-03-03"
        hora         = evento.get("eventTime", "") or (fecha_raw[11:16] if len(fecha_raw) > 10 else "")
        descripcion  = evento.get("eventDescription", "")
        tipo         = _determinar_tipo_siniestro(descripcion)

        return DatosSiniestro(
            fecha=fecha,
            hora=hora,
            lugar=evento.get("eventLocation", "Panama"),
            tipo=tipo,
            descripcion=descripcion,
            fecha_recibo_documentos=date.today().isoformat(),
        )

    @staticmethod
    def _extraer_conductor(evento: dict) -> DatosConductor:
        """Mapea campos del evento SIC a DatosConductor."""
        driver_fault    = evento.get("driverFault", True)
        responsabilidad = "Culpable" if driver_fault else "Inocente"

        return DatosConductor(
            cedula=evento.get("driverIdNumber", ""),
            nombre=evento.get("driverFirstName", ""),
            apellido=evento.get("driverLastName", ""),
            sexo=evento.get("driverGender", "M"),
            edad=int(evento.get("driverAge", 0)),
            responsabilidad=responsabilidad,
        )

    @staticmethod
    def _extraer_poliza(datos_poliza: dict) -> DatosPoliza:
        """Determina cobertura y reserva a partir de datos de Consulta Integral."""
        cobertura = datos_poliza.get("cobertura", "")
        reserva   = _determinar_reserva(cobertura)
        return DatosPoliza(cobertura=cobertura, reserva=reserva)
