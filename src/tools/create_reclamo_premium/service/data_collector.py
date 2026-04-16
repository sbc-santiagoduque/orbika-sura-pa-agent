"""
DataCollector — agrega datos del SIC detail endpoint en un DatosReclamo.

Fuente principal: GET /api/v1/events/{EventId} (via SICReclamoClient).
Fuente secundaria: ConsultaIntegralScraper (fallback para póliza/cobertura
si SIC no los tiene, o para validación cruzada).

Mappings desde campos reales de la API SIC:
  noPoliza                → numero_poliza
  eventDateSinister       → siniestro.fecha
  timeSinister            → siniestro.hora (truncar a HH:MM)
  placeDirectionSinister  → siniestro.lugar
  storyDetail             → siniestro.descripcion
  coverages[0].coverageName → tipo de siniestro + cobertura para reserva
  driverId                → conductor.cedula
  driverName/driverLastName → conductor.nombre/apellido
  driverGender            → conductor.sexo (ver TODO en sic_reclamo_client.py)
  driverBirthDate         → conductor.edad (calculado)
  IndResponsible          → conductor.responsabilidad ("" → "Pendiente")
"""
import logging
from datetime import date

from src.tools.create_reclamo_premium.infrastructure.sic_reclamo_client import (
    SICReclamoClient,
    _GENDER_MAP,
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


def _calcular_edad(birth_date_str: str) -> int:
    """
    Calcula la edad en años a partir de una fecha ISO ('1960-12-08').
    Retorna 0 si la fecha no es válida o está vacía.
    """
    if not birth_date_str:
        return 0
    try:
        birth = date.fromisoformat(birth_date_str[:10])
        today = date.today()
        return today.year - birth.year - (
            (today.month, today.day) < (birth.month, birth.day)
        )
    except (ValueError, TypeError):
        return 0


def _mapear_genero(gender_code) -> str:
    """
    Convierte el código numérico de género SIC a 'M' o 'F'.
    TODO: confirmar con SIC/ConnectAssistance — observado: driverGender=2 para masculino.
    """
    try:
        return _GENDER_MAP.get(int(gender_code), "M")
    except (ValueError, TypeError):
        return "M"


def _mapear_responsabilidad(ind_responsible: str) -> str:
    """
    Mapea IndResponsible de SIC a los valores de Premium.

    Valores observados:
      "" → no determinada aún (requiere revisión manual)
      TODO: confirmar valores "1"/"2" con equipo de operaciones.
    """
    mapping = {"1": "Culpable", "2": "Inocente"}
    return mapping.get(str(ind_responsible or "").strip(), "Pendiente")


class DataCollector:
    """
    Orquesta la recolección de datos para crear un reclamo en Premium.

    La fuente primaria es SICReclamoClient (endpoint de detalle de evento).
    ConsultaIntegralScraper es fallback — solo se usa si SIC no tiene
    número de póliza o cobertura.
    """

    def __init__(self, sic_client: SICReclamoClient, ci_scraper=None):
        self._sic = sic_client
        self._ci  = ci_scraper

    def recolectar(self, case_number: str, placa: str, expediente: str) -> DatosReclamo:
        """
        Recolecta todos los datos necesarios para abrir el reclamo.

        Args:
            case_number: Número de caso (ej. "02195167").
            placa:       Placa del vehículo asegurado (ej. "EJ1949").
            expediente:  EventRecord del SIC (ej. "5134134").

        Returns:
            DatosReclamo listo para Phase B (Premium RPA).
        """
        logger.info(
            "Iniciando recolección de datos para reclamo",
            extra={"case_number": case_number, "placa": placa, "expediente": expediente},
        )

        # Fuente primaria: SIC detail endpoint
        evento = self._sic.obtener_datos_evento(placa, expediente)

        # Fuente secundaria: Consulta Integral (fallback)
        datos_ci = None
        if self._ci and (not evento.get("noPoliza") or not self._tiene_cobertura(evento)):
            try:
                datos_ci = self._ci.obtener_datos_poliza(placa)
            except NotImplementedError:
                logger.warning("ConsultaIntegralScraper no implementado — usando solo datos SIC")

        siniestro    = self._extraer_siniestro(evento)
        conductor    = self._extraer_conductor(evento)
        numero_poliza, poliza = self._extraer_poliza(evento, datos_ci)

        reclamo = DatosReclamo(
            case_number=case_number,
            numero_poliza=numero_poliza,
            siniestro=siniestro,
            conductor=conductor,
            poliza=poliza,
            ajustador_interno=158,
        )

        logger.info(
            "Datos de reclamo recolectados",
            extra={
                "case_number":     case_number,
                "no_poliza":       numero_poliza,
                "tipo_siniestro":  siniestro.tipo,
                "responsabilidad": conductor.responsabilidad,
                "reserva":         poliza.reserva,
            },
        )
        return reclamo

    # ------------------------------------------------------------------
    # Helpers de extracción
    # ------------------------------------------------------------------

    @staticmethod
    def _tiene_cobertura(evento: dict) -> bool:
        coverages = evento.get("coverages") or []
        return bool(coverages and coverages[0].get("coverageName"))

    @staticmethod
    def _extraer_siniestro(evento: dict) -> DatosSiniestro:
        """Mapea campos del detalle de evento SIC a DatosSiniestro."""
        # Fecha y hora del siniestro (campos específicos del siniestro, no de la inspección)
        fecha = evento.get("eventDateSinister") or (evento.get("eventDate", ""))[:10]
        hora_raw = evento.get("timeSinister") or evento.get("time", "")
        hora = hora_raw[:5] if hora_raw else ""  # "12:14:00" → "12:14"

        lugar = (
            evento.get("placeDirectionSinister")
            or evento.get("placeDirection", "")
            or "Panamá"
        ).strip()

        # Descripción: preferir relato del conductor sobre observación del inspector
        descripcion = (
            evento.get("storyDetail")
            or evento.get("InspectorObservation", "")
            or ""
        ).strip()

        # Tipo: inferir desde nombre de cobertura, luego desde descripción
        coverages = evento.get("coverages") or []
        cobertura_nombre = coverages[0].get("coverageName", "") if coverages else ""
        tipo = _determinar_tipo_siniestro(cobertura_nombre or descripcion)

        return DatosSiniestro(
            fecha=fecha,
            hora=hora,
            lugar=lugar,
            tipo=tipo,
            descripcion=descripcion,
            fecha_recibo_documentos=date.today().isoformat(),
        )

    @staticmethod
    def _extraer_conductor(evento: dict) -> DatosConductor:
        """Mapea campos del detalle de evento SIC a DatosConductor."""
        cedula   = evento.get("driverId", "")
        nombre   = evento.get("driverName", "")
        apellido = (evento.get("driverLastName") or "").strip()
        sexo     = _mapear_genero(evento.get("driverGender"))
        edad     = _calcular_edad(evento.get("driverBirthDate", ""))
        responsabilidad = _mapear_responsabilidad(evento.get("IndResponsible", ""))

        return DatosConductor(
            cedula=cedula,
            nombre=nombre,
            apellido=apellido,
            sexo=sexo,
            edad=edad,
            responsabilidad=responsabilidad,
        )

    @staticmethod
    def _extraer_poliza(evento: dict, datos_ci: dict | None) -> tuple[str, DatosPoliza]:
        """
        Extrae póliza y cobertura desde SIC (fuente primaria) o CI (fallback).
        """
        # Número de póliza: SIC lo tiene en noPoliza
        numero_poliza = evento.get("noPoliza", "")
        if not numero_poliza and datos_ci:
            numero_poliza = datos_ci.get("numero_poliza", "")

        # Cobertura: SIC en coverages[0].coverageName
        coverages = evento.get("coverages") or []
        cobertura = coverages[0].get("coverageName", "") if coverages else ""
        if not cobertura and datos_ci:
            cobertura = datos_ci.get("cobertura", "")

        reserva = _determinar_reserva(cobertura)
        return numero_poliza, DatosPoliza(cobertura=cobertura, reserva=reserva)
