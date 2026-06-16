"""
Modelos de dominio para create_reclamo_premium.

DatosReclamo es el objeto central que agrega toda la información
necesaria para abrir un reclamo en el sistema Premium.

Secciones del protocolo que corresponden a cada sub-modelo:
  DatosSiniestro  → Tab Generales(1) — fecha, hora, lugar, tipo, descripcion
                    Tab Generales(3) — descripcion_danos (InspectorObservation de SIC)
  DatosConductor  → Tab Generales(2) — cedula, nombre, apellido, sexo, edad, responsabilidad
  DatosPoliza     → Tab Reservas     — cobertura, reserva
  DatosReclamo    → Tab Generales(3) — ajustador_interno (código 158 fijo)
"""
from dataclasses import dataclass, field, asdict


@dataclass
class DatosSiniestro:
    fecha: str                     # "2026-03-03" — de SIC (eventDate)
    hora: str                      # "13:50"       — de SIC (eventTime)
    lugar: str                     # "Panama"      — de SIC (eventLocation)
    tipo: str                      # "Colision"    — inferido de descripcion
    descripcion: str               # relato del conductor — de SIC (storyDetail) → Generales 1
    fecha_recibo_documentos: str   # hoy (fecha administrativa)
    descripcion_danos: str = ""    # daños al vehículo registrados por el inspector — de SIC (VehicleInjuryA) → Generales 3


@dataclass
class DatosConductor:
    cedula: str                    # "4-702-1179"  — de SIC (driverId)
    nombre: str                    # "Alberto"     — de SIC (driverName)
    apellido: str                  # "Antonio"     — de SIC (driverLastName)
    sexo: str                      # "M" | "F"     — de SIC (driverGender)
    edad: int                      # 45            — calculado de fecha_nacimiento
    responsabilidad: str           # "Culpable" | "Inocente" | "Pendiente"
    fecha_nacimiento: str = ""     # "1960-12-08"  — de SIC (driverBirthDate)


@dataclass
class DatosPoliza:
    cobertura: str                 # "POR COLISION O VUELCO" — de SIC (coverages)
    reserva: float                 # fijo en 1300.0 por decisión del equipo (ver _RESERVA_FIJA en data_collector)


@dataclass
class DatosVehiculo:
    tarjeta_propiedad: str = ""    # número tarjeta de propiedad — de SIC (propertyCard)


@dataclass
class DatosReclamo:
    case_number: str
    numero_poliza: str
    siniestro: DatosSiniestro
    conductor: DatosConductor
    poliza: DatosPoliza
    vehiculo: DatosVehiculo = field(default_factory=DatosVehiculo)
    ajustador_interno: int = 158   # Demetrio Vega — fijo por protocolo

    def to_dict(self) -> dict:
        return asdict(self)
