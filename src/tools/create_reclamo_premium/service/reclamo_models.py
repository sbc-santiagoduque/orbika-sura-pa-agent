"""
Modelos de dominio para create_reclamo_premium.

DatosReclamo es el objeto central que agrega toda la información
necesaria para abrir un reclamo en el sistema Premium.

Secciones del protocolo que corresponden a cada sub-modelo:
  DatosSiniestro  → Tab Generales(1) — fecha, hora, lugar, tipo, descripcion
  DatosConductor  → Tab Generales(2) — cedula, nombre, apellido, sexo, edad, responsabilidad
  DatosPoliza     → Tab Reservas     — cobertura, reserva
  DatosReclamo    → Tab Generales(3) — ajustador_interno (código 158 fijo)
"""
from dataclasses import dataclass, asdict


@dataclass
class DatosSiniestro:
    fecha: str                     # "2026-03-03" — de SIC (eventDate)
    hora: str                      # "13:50"       — de SIC (eventTime)
    lugar: str                     # "Panama"      — de SIC (eventLocation)
    tipo: str                      # "Colision"    — inferido de descripcion
    descripcion: str               # texto libre del FUD/SIC
    fecha_recibo_documentos: str   # hoy (fecha administrativa)


@dataclass
class DatosConductor:
    cedula: str                    # "4-702-1179"  — de SIC
    nombre: str                    # "Alberto"
    apellido: str                  # "Antonio"
    sexo: str                      # "M" | "F"
    edad: int                      # 45
    responsabilidad: str           # "Culpable" | "Inocente"  — de SIC (driverFault)


@dataclass
class DatosPoliza:
    cobertura: str                 # "POR COLISION O VUELCO" — de Consulta Integral
    reserva: float                 # 1300.0 — determinado por regla de negocio


@dataclass
class DatosReclamo:
    case_number: str
    numero_poliza: str
    siniestro: DatosSiniestro
    conductor: DatosConductor
    poliza: DatosPoliza
    ajustador_interno: int = 158   # Demetrio Vega — fijo por protocolo

    def to_dict(self) -> dict:
        return asdict(self)
