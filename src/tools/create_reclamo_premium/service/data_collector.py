"""
DataCollector — agrega datos del SIC detail endpoint en un DatosReclamo.

Fuente principal: GET /api/v1/events/{EventId} (via SICReclamoClient).
Fuente secundaria: ConsultaIntegralScraper (fallback para póliza/cobertura
si SIC no los tiene, o para validación cruzada).

Mappings desde campos reales de la API SIC:
  noPoliza                  → numero_poliza
  eventDateSinister         → siniestro.fecha
  timeSinister              → siniestro.hora (truncar a HH:MM)
  cantonDirectionSinister   → siniestro.lugar (lookup en _PANAMA_CANTONS; fallback placeDirectionSinister)
  storyDetail               → siniestro.descripcion (Generales 1)
  VehicleInjuryA            → siniestro.descripcion_danos (Generales 3)
  coverages[0].coverageName → tipo de siniestro + cobertura para reserva
  driverId                  → conductor.cedula
  driverName/driverLastName → conductor.nombre/apellido
  driverGender              → conductor.sexo (ver TODO en sic_reclamo_client.py)
  driverBirthDate           → conductor.edad (calculado)
  IndResponsible            → conductor.responsabilidad ("2" → "Inocente"; todo lo demás → "Culpable")
"""
import logging
from datetime import date

from src.tools.create_reclamo_premium.infrastructure.sic_reclamo_client import (
    SICReclamoClient,
    _GENDER_MAP,
    _determinar_tipo_siniestro,
    _tipo_desde_collision_type,
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
    DatosVehiculo,
)

logger = logging.getLogger(__name__)

# Monto de reserva fijo por decisión del equipo de operaciones de Sura Panamá.
# El algoritmo de inferencia por cobertura (_determinar_reserva en sic_reclamo_client)
# queda disponible para referencia pero NO se usa — el equipo es quien decide el monto.
_RESERVA_FIJA = 1300.0

# Panamá: código de provincia → nombre (confirmado desde dropdown SIC).
# cantonDirectionSinister tiene formato PDD (3 dígitos: provincia 1-9)
# o PPDD (4 dígitos: provincias/comarcas 10-12). Los últimos 2 dígitos son
# el ordinal del distrito dentro de la provincia — se descartan para el lugar.
_PANAMA_PROVINCES: dict[str, str] = {
    "1":  "Bocas del Toro",
    "2":  "Coclé",
    "3":  "Colón",
    "4":  "Chiriquí",
    "5":  "Darién",
    "6":  "Herrera",
    "7":  "Los Santos",
    "8":  "Panamá",
    "9":  "Veraguas",
    "10": "Comarca Kuna Yala",
    "11": "Comarca Ngabe Bugle",
    "12": "Panamá Oeste",
}


def _canton_code_to_province(canton_code: str) -> str | None:
    """'411' → 'Chiriquí', '1201' → 'Panamá Oeste'. None si código desconocido."""
    code = canton_code.strip()
    if len(code) == 3:
        return _PANAMA_PROVINCES.get(code[0])
    if len(code) == 4:
        return _PANAMA_PROVINCES.get(code[:2])
    return None


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

    Protocolo: "Culpable" si hay documento que lo acredita ("1") o si la
    resolución está pendiente (""). Solo "Inocente" cuando SIC confirma
    explícitamente ("2").
    """
    if str(ind_responsible or "").strip() == "2":
        return "Inocente"
    return "Culpable"


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

        # Fuente primaria de póliza: Consulta Integral
        # CI es la fuente de verdad para numero_poliza — determina qué póliza
        # estaba vigente a la fecha del siniestro. SIC es fallback si CI no está disponible.
        datos_ci = None
        if self._ci:
            fecha_siniestro = (
                evento.get("eventDateSinister") or evento.get("eventDate", "")
            )[:10] or None
            try:
                datos_ci = self._ci.obtener_datos_poliza(placa, fecha_siniestro)
            except (NotImplementedError, RuntimeError) as exc:
                logger.warning("CI no disponible — fallback a noPoliza de SIC: %s", exc)

        siniestro    = self._extraer_siniestro(evento)
        conductor    = self._extraer_conductor(evento)
        numero_poliza, poliza = self._extraer_poliza(evento, datos_ci)

        reclamo = DatosReclamo(
            case_number=case_number,
            numero_poliza=numero_poliza,
            siniestro=siniestro,
            conductor=conductor,
            poliza=poliza,
            vehiculo=self._extraer_vehiculo(evento),
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
        fecha = evento.get("eventDateSinister") or (evento.get("eventDate", ""))[:10]
        hora_raw = evento.get("timeSinister") or evento.get("time", "")
        hora = hora_raw[:5] if hora_raw else ""  # "12:14:00" → "12:14"

        canton_code = str(evento.get("cantonDirectionSinister") or "").strip()
        lugar = (
            _canton_code_to_province(canton_code)
            or (evento.get("placeDirectionSinister") or "Panamá").strip()
        )

        # Relato del conductor → Generales 1
        descripcion = (evento.get("storyDetail") or "").strip()

        # Daños al vehículo registrados por el inspector → Generales 3
        descripcion_danos = (evento.get("VehicleInjuryA") or "").strip()

        # Tipo: CollisionType (campo numérico directo del SIC) es fuente primaria.
        # Fallback: coverageName, luego storyDetail vía _determinar_tipo_siniestro.
        coverages = evento.get("coverages") or []
        cobertura_nombre = coverages[0].get("coverageName", "") if coverages else ""
        fallback_texto = cobertura_nombre or descripcion
        tipo = _tipo_desde_collision_type(evento.get("CollisionType"), fallback_texto)

        return DatosSiniestro(
            fecha=fecha,
            hora=hora,
            lugar=lugar,
            tipo=tipo,
            descripcion=descripcion,
            fecha_recibo_documentos=date.today().isoformat(),
            descripcion_danos=descripcion_danos,
        )

    @staticmethod
    def _extraer_conductor(evento: dict) -> DatosConductor:
        """Mapea campos del detalle de evento SIC a DatosConductor.

        Premium espera dos casillas de nombre:
          [Primer nombre]  [Segundo nombre + Apellido]
        driverName puede venir con uno o dos nombres ("JUAN" o "JUAN CARLOS"),
        así que se toma solo la primera palabra como primer nombre y el resto
        se antepone al apellido.
        """
        fecha_nacimiento = (evento.get("driverBirthDate") or "")[:10]
        cedula   = evento.get("driverId", "")
        apellido_raw = (evento.get("driverLastName") or "").strip()

        nombre_parts = (evento.get("driverName") or "").split()
        nombre  = nombre_parts[0] if nombre_parts else ""
        segundo = " ".join(nombre_parts[1:]) if len(nombre_parts) > 1 else ""
        apellido = " ".join(filter(None, [segundo, apellido_raw]))

        sexo    = _mapear_genero(evento.get("driverGender"))
        edad    = _calcular_edad(fecha_nacimiento)
        responsabilidad = _mapear_responsabilidad(evento.get("IndResponsible", ""))

        return DatosConductor(
            cedula=cedula,
            nombre=nombre,
            apellido=apellido,
            sexo=sexo,
            edad=edad,
            responsabilidad=responsabilidad,
            fecha_nacimiento=fecha_nacimiento,
        )

    # Nombres de campo que usa SIC para tarjeta de propiedad (distintas versiones/entornos).
    # Si ninguno está presente, retorna vacío — se descubrirá con --dump-raw.
    _TARJETA_FIELDS = ("propertyCard", "cardProperty", "vehicleCard", "nroTarjeta", "tarjetaPropiedad")

    @classmethod
    def _extraer_vehiculo(cls, evento: dict) -> DatosVehiculo:
        """Extrae tarjeta de propiedad del vehículo desde el evento SIC."""
        tarjeta = ""
        for campo in cls._TARJETA_FIELDS:
            val = (evento.get(campo) or "").strip()
            if val:
                tarjeta = val
                break
        return DatosVehiculo(tarjeta_propiedad=tarjeta)

    @staticmethod
    def _extraer_poliza(evento: dict, datos_ci: dict | None) -> tuple[str, DatosPoliza]:
        """
        Extrae póliza y cobertura.

        numero_poliza: CI es fuente primaria. SIC (noPoliza) es fallback si CI no disponible.
        cobertura: solo viene de SIC (coverages[0].coverageName) — CI no la expone.
        """
        # Número de póliza: CI primario, SIC fallback
        numero_poliza = (
            datos_ci.get("numero_poliza", "") if datos_ci
            else evento.get("noPoliza", "")
        )

        # Cobertura: solo SIC
        coverages = evento.get("coverages") or []
        cobertura = coverages[0].get("coverageName", "") if coverages else ""

        return numero_poliza, DatosPoliza(cobertura=cobertura, reserva=_RESERVA_FIJA)
