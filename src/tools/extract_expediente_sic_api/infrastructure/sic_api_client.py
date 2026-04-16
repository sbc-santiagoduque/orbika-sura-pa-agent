"""
Cliente HTTP para el SIC REST API (Claims SIC / ConnectAssistance).

Flujo real (4 requests, sin Playwright):
  1. POST /api/v1/users/auth          -> accessToken (Cognito JWT) + sub (UUID)
  2. GET  /api/v1/users/{sub}         -> userCompanyID (int), codPais — con API key
  3. GET  /api/v2/events/search       -> lista de eventos por placa (userId=int, countryCode, page)
  4. GET  /api/v1/images/PAN/all/{eventRecord} -> URLs firmadas S3 por seccion

Auth headers:
  Paso 1-2: Authorization: key_c5b4... (API key fija, hardcodeada en bundle JS)
  Paso 3-4: Authorization: Bearer {accessToken}

URL base leida desde la variable de entorno SIC_API_BASE_URL.
"""
import base64
import json
import logging
import os
from datetime import datetime

import requests

from src.shared.sic_api.sic_api_session import SICApiSession

logger = logging.getLogger(__name__)

_SIC_API_BASE_DEFAULT = "https://api-bkp.claims-sic.apps-connectassistance.com"


def _base_url() -> str:
    return os.environ.get("SIC_API_BASE_URL", _SIC_API_BASE_DEFAULT).rstrip("/")

# API key fija — hardcodeada en el bundle JS del app (sic.connectasistencia.com)
_API_KEY = "key_c5b4ad82c99e7abf75055d4095ba74c49632bf209b75f844fb2609d1e5900c17"

_API_KEY_HEADERS = {"Authorization": _API_KEY, "Accept": "application/json"}


class SICApiClient:
    def __init__(self, session: SICApiSession):
        self._session = session

    def obtener_expediente(self, placa: str) -> dict:
        """
        Busca el expediente mas reciente en SIC para una placa.

        Returns:
            {
                "placa": str,
                "evento_id": str,
                "fecha_evento": str,
                "imagen_count": int,
                "imagenes": [{"nombre": str, "url": str, "seccion_id": int}, ...]
            }
        """
        access_token, sub = self._autenticar()
        user_company_id, country_code = self._obtener_datos_usuario(sub)
        headers = self._bearer_headers(access_token)

        evento = self._buscar_evento_reciente(placa, user_company_id, country_code, headers)
        if not evento:
            return {
                "placa": placa,
                "evento_id": None,
                "fecha_evento": None,
                "imagen_count": 0,
                "imagenes": [],
            }

        event_record = str(evento.get("eventRecord", ""))
        fecha_evento  = evento.get("eventDate", "")
        imagenes      = self._obtener_imagenes(event_record, headers)

        logger.info(
            "Expediente SIC obtenido via API",
            extra={"placa": placa, "event_record": event_record, "imagenes": len(imagenes)},
        )

        return {
            "placa":        placa,
            "evento_id":    event_record,
            "fecha_evento": fecha_evento,
            "imagen_count": len(imagenes),
            "imagenes":     imagenes,
        }

    def obtener_imagenes_por_expediente(self, placa: str, expediente: str) -> list[dict]:
        """
        Obtiene las imagenes del expediente especifico (eventRecord == expediente).

        A diferencia de obtener_expediente(), no busca el mas reciente sino el que
        coincide exactamente con el numero de expediente recibido del orquestador.

        Args:
            placa:      placa del vehiculo asegurado
            expediente: numero de expediente (= eventRecord en SIC)

        Returns:
            [{"nombre": str, "url": str, "seccion_id": int}, ...]

        Raises:
            ValueError: si no existe ningun evento con ese eventRecord para la placa.
        """
        access_token, sub = self._autenticar()
        user_company_id, country_code = self._obtener_datos_usuario(sub)
        headers = self._bearer_headers(access_token)

        self._buscar_evento_por_expediente(placa, expediente, user_company_id, country_code, headers)
        imagenes = self._obtener_imagenes(expediente, headers)

        logger.info(
            "Imagenes SIC obtenidas por expediente",
            extra={"placa": placa, "expediente": expediente, "total": len(imagenes)},
        )
        return imagenes

    # ------------------------------------------------------------------
    # Internos
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
            raise RuntimeError(f"SIC auth: no se encontro accessToken. Claves: {list(data.keys())}")

        sub = data.get("sub", "")
        logger.info("SIC API auth exitosa", extra={"sub": sub})
        return access_token, sub

    def _obtener_datos_usuario(self, sub: str) -> tuple[int, str]:
        """GET /api/v1/users/{sub} → (userCompanyID, codPais)."""
        base = _base_url()
        resp = requests.get(
            f"{base}/api/v1/users/{sub}",
            headers=_API_KEY_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("data") or {}

        user_company_id = data.get("userCompanyID")
        country_code    = data.get("codPais", "PAN")

        if not user_company_id:
            raise RuntimeError(f"SIC usuarios: no se encontro userCompanyID. Claves: {list(data.keys())}")

        logger.info("SIC usuario obtenido", extra={"userCompanyID": user_company_id, "codPais": country_code})
        return int(user_company_id), country_code

    def _buscar_evento_reciente(
        self, placa: str, user_id: int, country_code: str, headers: dict
    ) -> dict | None:
        """
        Retorna el evento con la fecha mas reciente para una placa, o None si no hay resultados.
        """
        eventos = self._listar_eventos(placa, user_id, country_code, headers)
        if not eventos:
            return None
        return max(eventos, key=lambda e: _parsear_fecha(e.get("eventDate", "")))

    def _buscar_evento_por_expediente(
        self, placa: str, expediente: str, user_id: int, country_code: str, headers: dict
    ) -> dict:
        """
        Retorna el evento cuyo eventRecord coincide con expediente.

        Raises:
            ValueError: si no se encuentra el expediente para esa placa.
        """
        eventos = self._listar_eventos(placa, user_id, country_code, headers)
        for evento in eventos:
            if str(evento.get("eventRecord", "")) == str(expediente):
                return evento
        raise ValueError(
            f"Expediente '{expediente}' no encontrado en SIC para la placa '{placa}'. "
            f"Eventos disponibles: {[e.get('eventRecord') for e in eventos]}"
        )

    def _listar_eventos(
        self, placa: str, user_id: int, country_code: str, headers: dict
    ) -> list[dict]:
        """GET /api/v2/events/search — retorna lista de eventos para la placa."""
        base = _base_url()
        params = {
            "filterType":  "INSURED_PLATE",
            "filterText":  placa,
            "countryCode": country_code,
            "companyId":   15,
            "rolId":       3,
            "page":        1,
            "userId":      user_id,
        }
        resp = requests.get(f"{base}/api/v2/events/search", params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        body = resp.json()

        data = body.get("data") or {}
        if isinstance(data, dict):
            response = data.get("response") or {}
            return response.get("events") or data.get("events") or []
        elif isinstance(data, list):
            return data
        return []

    def _obtener_imagenes(self, event_record: str, headers: dict) -> list[dict]:
        """GET /api/v1/images/PAN/all/{eventRecord}?forceUpdate=true"""
        base = _base_url()
        url  = f"{base}/api/v1/images/PAN/all/{event_record}"
        resp = requests.get(url, params={"forceUpdate": "true"}, headers=headers, timeout=20)
        resp.raise_for_status()
        body = resp.json()

        items = body.get("data") if isinstance(body, dict) else body
        if not isinstance(items, list):
            return []

        return [
            {
                "nombre":     img.get("imageName", ""),
                "url":        img.get("imageUrl", ""),
                "seccion_id": img.get("imageSectionId"),
            }
            for img in items
            if img.get("imageUrl")
        ]

    @staticmethod
    def _bearer_headers(access_token: str) -> dict:
        return {
            "Authorization": f"Bearer {access_token}",
            "X-User-Type":   "sic-user",
            "Accept":        "application/json",
            "Content-Type":  "application/json",
        }


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _decode_user_id(token: str) -> int:
    """Extrae userId del payload JWT (sin verificar firma)."""
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        for field in ("userId", "user_id", "sub", "cognito:username"):
            if field in payload:
                val = payload[field]
                if field not in ("sub", "cognito:username"):
                    return int(val)
        raise RuntimeError(f"userId no encontrado en JWT payload. Campos: {list(payload.keys())}")
    except Exception as exc:
        raise RuntimeError(f"Error decodificando JWT: {exc}") from exc


def _parsear_fecha(fecha_str: str) -> datetime:
    """Parsea eventDate en formatos ISO o retorna datetime.min si falla."""
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(fecha_str, fmt)
        except ValueError:
            continue
    return datetime.min
