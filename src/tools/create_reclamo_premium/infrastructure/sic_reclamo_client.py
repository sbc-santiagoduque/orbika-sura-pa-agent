"""
Cliente SIC específico para recolección de datos de reclamo.

A diferencia de extract_expediente_sic_api (que extrae imágenes),
este cliente extrae los datos del evento necesarios para abrir el
reclamo en Premium:
  - Fecha, hora y lugar del siniestro
  - Datos del conductor (cédula, nombre, apellido, sexo, edad)
  - Responsabilidad (driverFault → Culpable / Inocente)
  - Descripción del siniestro (FUD)

Auth flow (igual que sic_api_client.py existente):
  1. POST /api/v1/users/auth          → accessToken + sub
  2. GET  /api/v1/users/{sub}         → userCompanyID + codPais
  3. GET  /api/v2/events/search       → lista de eventos por placa
  4. Filtrar por eventRecord == expediente

TODO: validar nombres de campos del evento contra la API real.
      Los campos (driverIdNumber, driverFirstName, etc.) se infieren
      del bundle JS del app SIC. Confirmar con un evento real en staging.
"""
import logging
import os

import requests

logger = logging.getLogger(__name__)

_SIC_API_BASE_DEFAULT = "https://api-bkp.claims-sic.apps-connectassistance.com"

# API key fija — hardcodeada en el bundle JS del app SIC
_API_KEY = "key_c5b4ad82c99e7abf75055d4095ba74c49632bf209b75f844fb2609d1e5900c17"
_API_KEY_HEADERS = {"Authorization": _API_KEY, "Accept": "application/json"}

# Reglas de reserva por cobertura (según protocolo sección 8.5)
_RESERVAS = {
    "COLISION":  1300.0,
    "VUELCO":    1300.0,
    "ROBO":      5000.0,
    "INCENDIO":  2500.0,
}
_RESERVA_DEFAULT = 1000.0

# Palabras clave para inferir tipo de siniestro desde descripción
_TIPOS_SINIESTRO = {
    "Colision":  ["colision", "colisión", "choque", "impacto"],
    "Robo":      ["robo", "hurto", "sustraccion"],
    "Incendio":  ["incendio", "fuego", "quemado"],
}


def _base_url() -> str:
    return os.environ.get("SIC_API_BASE_URL", _SIC_API_BASE_DEFAULT).rstrip("/")


def _determinar_tipo_siniestro(descripcion: str) -> str:
    """
    Infiere el tipo de siniestro a partir de la descripción del evento SIC.

    Retorna: "Colision" | "Robo" | "Incendio" | "Otro"
    """
    desc_lower = descripcion.lower()
    for tipo, palabras in _TIPOS_SINIESTRO.items():
        if any(p in desc_lower for p in palabras):
            return tipo
    return "Otro"


def _determinar_reserva(cobertura: str) -> float:
    """
    Determina el monto de reserva según la cobertura de Consulta Integral.

    Retorna el monto definido en el protocolo sección 8.5,
    o _RESERVA_DEFAULT si la cobertura no está mapeada.
    """
    cobertura_upper = cobertura.upper()
    for keyword, monto in _RESERVAS.items():
        if keyword in cobertura_upper:
            return monto
    return _RESERVA_DEFAULT


class SICReclamoClient:
    """
    Extrae datos de evento del SIC REST API para la apertura de reclamos.

    Uso:
        from src.shared.sic_api.sic_api_session import SICApiSession

        session = SICApiSession(
            ssm_username_path=os.environ["SSM_SIC_API_USERNAME_PATH"],
            ssm_password_path=os.environ["SSM_SIC_API_PASSWORD_PATH"],
        )
        client = SICReclamoClient(session)
        evento = client.obtener_datos_evento("XYZ123", "EXP001")
    """

    def __init__(self, session):
        self._session = session

    def obtener_datos_evento(self, placa: str, expediente: str) -> dict:
        """
        Retorna el dict completo del evento SIC para la placa + expediente.

        Args:
            placa:      Placa del vehículo asegurado.
            expediente: Número de expediente (= eventRecord en SIC).

        Returns:
            Dict con todos los campos del evento. Campos esperados:
              eventRecord, eventDate, eventTime, eventLocation,
              eventDescription, driverIdNumber, driverFirstName,
              driverLastName, driverGender, driverAge, driverFault

        Raises:
            ValueError: si no se encuentra el expediente para esa placa.
            RuntimeError: si falla la autenticación o la consulta HTTP.
        """
        access_token, sub = self._autenticar()
        user_company_id, country_code = self._obtener_datos_usuario(sub)
        headers = self._bearer_headers(access_token)

        evento = self._buscar_evento_por_expediente(
            placa, expediente, user_company_id, country_code, headers
        )

        logger.info(
            "Datos de evento SIC obtenidos para reclamo",
            extra={"placa": placa, "expediente": expediente},
        )
        return evento

    # ------------------------------------------------------------------
    # Internos — auth flow (mismo patrón que sic_api_client.py)
    # ------------------------------------------------------------------

    def _autenticar(self) -> tuple[str, str]:
        """POST /api/v1/users/auth → (accessToken, sub)."""
        base = _base_url()
        username, password = self._session.load_credentials()
        resp = requests.post(
            f"{base}/api/v1/users/auth",
            json={"username": username, "password": password, "mfaCode": None, "challengeSession": None},
            headers=_API_KEY_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("data") or resp.json()

        access_token = data.get("accessToken")
        if not access_token:
            raise RuntimeError(f"SIC auth: no accessToken en respuesta. Claves: {list(data.keys())}")

        sub = data.get("sub", "")
        return access_token, sub

    def _obtener_datos_usuario(self, sub: str) -> tuple[int, str]:
        """GET /api/v1/users/{sub} → (userCompanyID, codPais)."""
        resp = requests.get(
            f"{_base_url()}/api/v1/users/{sub}",
            headers=_API_KEY_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("data") or {}

        user_company_id = data.get("userCompanyID")
        if not user_company_id:
            raise RuntimeError(f"SIC usuarios: no userCompanyID. Claves: {list(data.keys())}")

        return int(user_company_id), data.get("codPais", "PAN")

    def _listar_eventos(
        self, placa: str, user_id: int, country_code: str, headers: dict
    ) -> list[dict]:
        """GET /api/v2/events/search — lista eventos por placa."""
        params = {
            "filterType":  "INSURED_PLATE",
            "filterText":  placa,
            "countryCode": country_code,
            "companyId":   15,
            "rolId":       3,
            "page":        1,
            "userId":      user_id,
        }
        resp = requests.get(
            f"{_base_url()}/api/v2/events/search",
            params=params,
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        body = resp.json()

        data = body.get("data") or {}
        if isinstance(data, dict):
            response = data.get("response") or {}
            return response.get("events") or data.get("events") or []
        elif isinstance(data, list):
            return data
        return []

    def _buscar_evento_por_expediente(
        self, placa: str, expediente: str, user_id: int, country_code: str, headers: dict
    ) -> dict:
        """Retorna el evento cuyo eventRecord == expediente."""
        eventos = self._listar_eventos(placa, user_id, country_code, headers)
        for evento in eventos:
            if str(evento.get("eventRecord", "")) == str(expediente):
                return evento
        raise ValueError(
            f"Expediente '{expediente}' no encontrado en SIC para placa '{placa}'. "
            f"Disponibles: {[e.get('eventRecord') for e in eventos]}"
        )

    @staticmethod
    def _bearer_headers(access_token: str) -> dict:
        return {
            "Authorization": f"Bearer {access_token}",
            "X-User-Type":   "sic-user",
            "Accept":        "application/json",
        }
