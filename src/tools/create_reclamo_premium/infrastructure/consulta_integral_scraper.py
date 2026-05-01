"""
Cliente REST para Consulta Integral.

Endpoints descubiertos en inspección de red (2026-04-21):

  GET /api/api/AseguradoPlaca?id={placa}
      → [{id, Nombre, identificación}]

  GET /api/api/Polizas?id={cedula}&placasn={placa}&Valor=undefined
      → [{id, CORE, Póliza, Solución, Vigi, Vigf, Estado, Suma, Saldo, Siniestros}]

Acceso: red interna únicamente (VPN FortiClient activa o VPC AWS con acceso a 10.240.3.x).
Sin autenticación adicional.

Notas:
  - CI no expone nombre de cobertura — ese campo viene de SIC (coverages[0].coverageName).
  - Vigi/Vigf en formato DD/MM/YYYY (ej: "11/02/2026" = 11 de febrero de 2026).
  - Cuando hay varios asegurados para una placa, se consultan pólizas de todos
    y se selecciona la que cubre la fecha del siniestro.
"""
import logging
from datetime import date, datetime

import requests as _requests

import json as _json

logger = logging.getLogger(__name__)

_VIGI_FMT = "%d/%m/%Y"  # Formato real de la API: DD/MM/YYYY (ej: "11/02/2026" = 11 de febrero)


def _parse_json_response(data) -> list:
    """
    CI devuelve el body como string JSON dentro de JSON:
      resp.json() → '[{"id":1,...}]'   ← string, no lista

    Si data ya es lista, la retorna directamente.
    Si es string, hace un segundo json.loads().
    """
    if isinstance(data, list):
        return data
    if isinstance(data, str):
        parsed = _json.loads(data)
        return parsed if isinstance(parsed, list) else []
    return []


def _parse_vigi(fecha_str: str) -> date | None:
    """Parsea una fecha de vigencia MM/DD/YYYY a date. Retorna None si no es válida."""
    if not fecha_str:
        return None
    try:
        return datetime.strptime(fecha_str, _VIGI_FMT).date()
    except ValueError:
        return None


class ConsultaIntegralClient:
    """
    Cliente REST para Consulta Integral.

    Encadena AseguradoPlaca + Polizas y selecciona la póliza cuya vigencia
    cubre la fecha del siniestro.
    """

    def __init__(self, ci_base_url: str, timeout: int = 5):
        self._base_url = ci_base_url.rstrip("/")
        self._timeout = timeout

    def obtener_datos_poliza(self, placa: str, fecha_siniestro: str | None = None) -> dict:
        """
        Retorna datos de la póliza vigente a la fecha del siniestro para la placa.

        Args:
            placa:           Placa del vehículo (ej. "ED1370").
            fecha_siniestro: ISO "YYYY-MM-DD". Se usa para seleccionar la póliza
                             cuya vigencia cubre esa fecha. Si es None, retorna
                             la primera póliza disponible (preferendo Estado=Vigente).

        Returns:
            {
                "numero_poliza":  "02-98-1246363-0",
                "cobertura":      "",           — CI no expone cobertura
                "suma_asegurada": 12400.0,
                "estado":         "Vigente",
                "vigi":           "2026-07-01",
                "vigf":           "2027-07-01",
            }

        Raises:
            RuntimeError: si CI no es accesible o no hay póliza para la placa.
        """
        fecha_dt = self._parse_fecha_siniestro(fecha_siniestro)

        asegurados = self._obtener_asegurados(placa)
        if not asegurados:
            raise RuntimeError(f"CI: no se encontraron asegurados para placa '{placa}'")

        polizas = self._obtener_polizas_todos(asegurados, placa)
        if not polizas:
            raise RuntimeError(f"CI: no se encontraron pólizas para placa '{placa}'")

        poliza = self._seleccionar_poliza(polizas, fecha_dt, placa)

        logger.info(
            "CI: póliza seleccionada",
            extra={
                "placa":           placa,
                "fecha_siniestro": fecha_siniestro,
                "numero_poliza":   poliza["Póliza"],
                "estado":          poliza.get("Estado", ""),
            },
        )

        return {
            "numero_poliza":  poliza["Póliza"],
            "cobertura":      "",
            "suma_asegurada": float(poliza.get("Suma") or 0),
            "estado":         poliza.get("Estado", ""),
            "vigi":           self._a_iso(poliza.get("Vigi", "")),
            "vigf":           self._a_iso(poliza.get("Vigf", "")),
        }

    # ------------------------------------------------------------------
    # Requests HTTP
    # ------------------------------------------------------------------

    # Forzar cierre de conexión tras cada request para evitar reusar sockets
    # muertos cuando el servidor CI cierra el keep-alive tras varias consultas.
    _HEADERS = {"Connection": "close"}

    def _obtener_asegurados(self, placa: str) -> list[dict]:
        """GET /api/api/AseguradoPlaca?id={placa}"""
        url = f"{self._base_url}/api/api/AseguradoPlaca"
        try:
            resp = _requests.get(url, params={"id": placa}, timeout=self._timeout,
                                 headers=self._HEADERS)
            resp.raise_for_status()
            return _parse_json_response(resp.json())
        except Exception as exc:
            raise RuntimeError(f"CI AseguradoPlaca ({placa}): {exc}") from exc

    def _obtener_polizas_cedula(self, cedula: str, placa: str) -> list[dict]:
        """GET /api/api/Polizas?id={cedula}&placasn={placa}&Valor=undefined"""
        url = f"{self._base_url}/api/api/Polizas"
        try:
            resp = _requests.get(
                url,
                params={"id": cedula, "placasn": placa, "Valor": "undefined"},
                timeout=self._timeout,
                headers=self._HEADERS,
            )
            resp.raise_for_status()
            return _parse_json_response(resp.json())
        except Exception as exc:
            logger.warning("CI Polizas (cédula=%s): %s", cedula, exc)
            return []

    def _obtener_polizas_todos(self, asegurados: list[dict], placa: str) -> list[dict]:
        """Agrega pólizas de todos los asegurados encontrados para la placa."""
        todas = []
        for asegurado in asegurados:
            cedula = asegurado.get("identificación") or asegurado.get("identificacion", "")
            if cedula:
                todas.extend(self._obtener_polizas_cedula(cedula, placa))
        return todas

    # ------------------------------------------------------------------
    # Selección de póliza
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_fecha_siniestro(fecha_str: str | None) -> date | None:
        if not fecha_str:
            return None
        try:
            return date.fromisoformat(fecha_str[:10])
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _seleccionar_poliza(polizas: list[dict], fecha_dt: date | None, placa: str) -> dict:
        """
        Selecciona la póliza correcta para la fecha del siniestro.

        Prioridad con fecha_siniestro:
          1. Pólizas donde Vigi <= fecha_siniestro <= Vigf (cobertura exacta)
             → dentro del grupo, Estado=Vigente primero.
          2. Si ninguna cubre exactamente: pólizas que iniciaron antes del
             siniestro, ordenadas por Vigf descendente (la que expiró más
             recientemente). Una póliza expirada es válida si el siniestro
             ocurrió dentro de su período.
          3. Fallback final: primera disponible (Estado=Vigente primero).

        Sin fecha_siniestro:
          - Estado=Vigente primero, luego primera disponible.
        """
        if fecha_dt:
            # 1. Cobertura exacta
            cubren = [
                p for p in polizas
                if _parse_vigi(p.get("Vigi", "")) is not None
                and _parse_vigi(p.get("Vigf", "")) is not None
                and _parse_vigi(p.get("Vigi", "")) <= fecha_dt <= _parse_vigi(p.get("Vigf", ""))
            ]
            if cubren:
                cubren.sort(key=lambda p: p.get("Estado", "") != "Vigente")
                return cubren[0]

            # 2. Iniciaron antes del siniestro → la de Vigf más reciente
            anteriores = [
                p for p in polizas
                if _parse_vigi(p.get("Vigi", "")) is not None
                and _parse_vigi(p.get("Vigi", "")) <= fecha_dt
            ]
            if anteriores:
                anteriores.sort(
                    key=lambda p: _parse_vigi(p.get("Vigf", "")) or date.min,
                    reverse=True,
                )
                logger.warning(
                    "CI: ninguna póliza cubre exactamente la fecha %s para placa '%s'"
                    " — usando la de vigencia más reciente (Vigf=%s)",
                    fecha_dt, placa, anteriores[0].get("Vigf", ""),
                )
                return anteriores[0]

            logger.warning(
                "CI: sin pólizas anteriores a la fecha %s para placa '%s'"
                " — usando primera disponible",
                fecha_dt, placa,
            )

        polizas_sorted = sorted(polizas, key=lambda p: p.get("Estado", "") != "Vigente")
        return polizas_sorted[0]

    @staticmethod
    def _a_iso(fecha_str: str) -> str:
        """Convierte 'MM/DD/YYYY' a 'YYYY-MM-DD'. Retorna '' si no es válida."""
        dt = _parse_vigi(fecha_str)
        return dt.isoformat() if dt else ""


# Alias de compatibilidad con el nombre anterior
ConsultaIntegralScraper = ConsultaIntegralClient


class ConsultaIntegralClientStub:
    """
    Stub para tests y desarrollo sin VPN.

    Retorna datos fijos sin hacer ninguna llamada HTTP.
    NO usar en producción.
    """

    def __init__(self, datos_fijos: dict | None = None):
        self._datos = datos_fijos or {
            "numero_poliza":  "02-37-0000000-0",
            "cobertura":      "",
            "suma_asegurada": 25000.0,
            "estado":         "Vigente",
            "vigi":           "2026-01-01",
            "vigf":           "2027-01-01",
        }

    def obtener_datos_poliza(self, placa: str, fecha_siniestro: str | None = None) -> dict:
        logger.warning(
            "ConsultaIntegralClientStub activo — datos NO reales",
            extra={"placa": placa},
        )
        return {**self._datos}


# Alias de compatibilidad con el nombre anterior
ConsultaIntegralScraperStub = ConsultaIntegralClientStub
