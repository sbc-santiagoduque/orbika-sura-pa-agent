"""
Cliente SIC para recolección de datos de reclamo.

Flujo real (4 requests — mismo auth que sic_api_client.py en extract_expediente_sic_api):
  1. POST /api/v1/users/auth          → accessToken + sub
  2. GET  /api/v1/users/{sub}         → userCompanyID + codPais
  3. GET  /api/v2/events/search       → lista eventos por placa → obtener EventId
  4. GET  /api/v1/events/{EventId}    → detalle completo del evento

El endpoint de detalle (/api/v1/events/{EventId}) provee prácticamente todo:
  - noPoliza          → número de póliza (evita necesidad de Consulta Integral)
  - eventDateSinister / timeSinister / placeDirectionSinister → fecha/hora/lugar
  - storyDetail       → descripción del conductor
  - driverId / driverName / driverLastName / driverGender / driverBirthDate
  - coverages[0].coverageName → cobertura para calcular reserva
  - IndResponsible    → responsabilidad (vacío si no determinada aún)

Nota sobre driverGender:
  Observado en API real: Cristobal (masculino) → driverGender = 2
  TODO: confirmar con SIC/ConnectAssistance el mapping exacto.
  Asumiendo 1=F, 2=M hasta confirmación.

Nota sobre IndResponsible:
  Campo vacío ("") cuando no está determinada la responsabilidad.
  El DataCollector lo mapea a "Pendiente" para indicar revisión manual.
"""
import logging
import os

import requests

logger = logging.getLogger(__name__)

_SIC_API_BASE_DEFAULT = "https://api-bkp.claims-sic.apps-connectassistance.com"

# API key fija — hardcodeada en el bundle JS del app SIC (sic.connectasistencia.com)
_API_KEY = "key_c5b4ad82c99e7abf75055d4095ba74c49632bf209b75f844fb2609d1e5900c17"
_API_KEY_HEADERS = {"Authorization": _API_KEY, "Accept": "application/json"}

# Reglas de reserva por cobertura (protocolo sección 8.5)
_RESERVAS = {
    "COLISI":    1300.0,   # Colisión o Vuelco
    "VUELCO":    1300.0,
    "ROBO":      5000.0,
    "INCENDIO":  2500.0,
}
_RESERVA_DEFAULT = 1000.0

# Inferencia de tipo de siniestro desde nombre de cobertura o descripción
_TIPOS_SINIESTRO = {
    "Colision":  ["colisi", "vuelco", "choque", "impacto"],
    "Robo":      ["robo", "hurto", "sustraccion"],
    "Incendio":  ["incendio", "fuego", "quemado"],
}

# Mapping de driverGender (código numérico SIC → M/F)
# TODO: confirmar con SIC/ConnectAssistance — observado: Cristobal(M) → 2
_GENDER_MAP = {1: "F", 2: "M"}


def _base_url() -> str:
    return os.environ.get("SIC_API_BASE_URL", _SIC_API_BASE_DEFAULT).rstrip("/")


def _determinar_tipo_siniestro(texto: str) -> str:
    """
    Infiere el tipo de siniestro desde el nombre de cobertura o descripción.

    Retorna: "Colision" | "Robo" | "Incendio" | "Otro"
    """
    texto_lower = (texto or "").lower()
    for tipo, palabras in _TIPOS_SINIESTRO.items():
        if any(p in texto_lower for p in palabras):
            return tipo
    return "Otro"


def _determinar_reserva(cobertura: str) -> float:
    """
    Retorna el monto de reserva según la cobertura (protocolo sección 8.5).
    Default $1000 si la cobertura no está mapeada.
    """
    cobertura_upper = (cobertura or "").upper()
    for keyword, monto in _RESERVAS.items():
        if keyword in cobertura_upper:
            return monto
    return _RESERVA_DEFAULT


class SICReclamoClient:
    """
    Extrae todos los datos necesarios para crear un reclamo en Premium
    desde el SIC REST API.

    Uso:
        from src.shared.sic_api.sic_api_session import SICApiSession

        session = SICApiSession(
            ssm_username_path=os.environ["SSM_SIC_API_USERNAME_PATH"],
            ssm_password_path=os.environ["SSM_SIC_API_PASSWORD_PATH"],
        )
        client = SICReclamoClient(session)
        evento = client.obtener_datos_evento("EJ1949", "5134134")
    """

    def __init__(self, session):
        self._session = session

    def obtener_datos_evento(self, placa: str, expediente: str) -> dict:
        """
        Retorna el dict completo del detalle de evento para placa + expediente.

        Flujo interno:
          1. Auth → token
          2. Datos de usuario → userCompanyID
          3. Search por placa → filtrar por eventRecord → extraer EventId
          4. GET /api/v1/events/{EventId} → dict completo

        Args:
            placa:      Placa del vehículo asegurado (ej. "EJ1949").
            expediente: EventRecord del SIC (ej. "5134134").

        Returns:
            Dict del campo data.event de la respuesta. Incluye noPoliza,
            driverName, driverId, driverGender, driverBirthDate,
            eventDateSinister, timeSinister, placeDirectionSinister,
            storyDetail, coverages, IndResponsible, etc.

        Raises:
            ValueError: si el expediente no existe para esa placa.
            RuntimeError: si falla auth, permisos o el API responde error.
        """
        access_token, sub = self._autenticar()
        user_company_id, country_code = self._obtener_datos_usuario(sub)
        headers = self._bearer_headers(access_token)

        event_id = self._buscar_event_id_por_expediente(
            placa, expediente, user_company_id, country_code, headers
        )
        evento = self._obtener_detalle_evento(event_id, headers)

        logger.info(
            "Detalle de evento SIC obtenido para reclamo",
            extra={
                "placa": placa,
                "expediente": expediente,
                "event_id": event_id,
                "no_poliza": evento.get("noPoliza"),
            },
        )
        return evento

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _autenticar(self) -> tuple[str, str]:
        """POST /api/v1/users/auth → (accessToken, sub)."""
        username, password = self._session.load_credentials()
        resp = requests.post(
            f"{_base_url()}/api/v1/users/auth",
            json={"username": username, "password": password, "mfaCode": None, "challengeSession": None},
            headers=_API_KEY_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("data") or resp.json()

        access_token = data.get("accessToken")
        if not access_token:
            raise RuntimeError(f"SIC auth: no accessToken. Claves: {list(data.keys())}")

        return access_token, data.get("sub", "")

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

    def _buscar_event_id_por_expediente(
        self, placa: str, expediente: str, user_id: int, country_code: str, headers: dict
    ) -> int:
        """
        Busca el EventId (entero) para el eventRecord == expediente.

        El EventId es necesario para llamar /api/v1/events/{EventId}.
        """
        eventos = self._listar_eventos(placa, user_id, country_code, headers)
        for evento in eventos:
            if str(evento.get("eventRecord", "")) == str(expediente):
                # El campo puede llamarse EventId, eventId o id según la versión de la API
                event_id = (
                    evento.get("EventId")
                    or evento.get("eventId")
                    or evento.get("id")
                )
                if not event_id:
                    raise RuntimeError(
                        f"Evento '{expediente}' encontrado pero sin EventId. "
                        f"Claves disponibles: {list(evento.keys())}"
                    )
                return int(event_id)

        raise ValueError(
            f"Expediente '{expediente}' no encontrado para placa '{placa}'. "
            f"Expedientes disponibles: {[e.get('eventRecord') for e in eventos]}"
        )

    def _obtener_detalle_evento(self, event_id: int, headers: dict) -> dict:
        """
        GET /api/v1/events/{EventId} → data.event completo.

        Retorna el dict interno del evento (no el wrapper de la respuesta).
        """
        resp = requests.get(
            f"{_base_url()}/api/v1/events/{event_id}",
            headers=headers,
            timeout=20,
        )
        resp.raise_for_status()
        body = resp.json()

        if not body.get("success"):
            raise RuntimeError(
                f"SIC /api/v1/events/{event_id}: success=false. "
                f"Error: {body.get('error')}"
            )

        return body["data"]["event"]

    @staticmethod
    def _bearer_headers(access_token: str) -> dict:
        return {
            "Authorization": f"Bearer {access_token}",
            "X-User-Type":   "sic-user",
            "Accept":        "application/json",
        }
