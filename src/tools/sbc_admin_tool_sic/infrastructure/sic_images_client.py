"""
Cliente SIC de imagenes para la lambda sbc-admin-tool-sic-lambda.

Implementacion autocontenida del flujo SIC REST API (4 requests):
  1. POST /api/v1/users/auth          -> accessToken + sub (Cognito)
  2. GET  /api/v1/users/{sub}         -> userCompanyID + codPais
  3. GET  /api/v2/events/search       -> lista de eventos por placa
  4. GET  /api/v1/images/PAN/all/{eventRecord} -> URLs firmadas S3

Credenciales leidas directamente desde variables de entorno:
    SIC_API_BASE_URL   — URL base del API
    SIC_API_USERNAME   — usuario SIC
    SIC_API_PASSWORD   — contrasena SIC
"""
import logging
import os
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

# API key fija — hardcodeada en el bundle JS del app (sic.connectasistencia.com)
_API_KEY = "key_c5b4ad82c99e7abf75055d4095ba74c49632bf209b75f844fb2609d1e5900c17"
_API_KEY_HEADERS = {"Authorization": _API_KEY, "Accept": "application/json"}


def _build_urls() -> tuple[str, str, str, str]:
    base = os.environ["SIC_API_BASE_URL"].rstrip("/")
    return (
        f"{base}/api/v1/users/auth",
        f"{base}/api/v1/users",
        f"{base}/api/v2/events/search",
        f"{base}/api/v1/images/PAN/all",
    )


class SicImagesClient:

    def obtener_imagenes(self, placa: str, expediente: str) -> list[dict]:
        """
        Retorna las imagenes del evento que coincide con placa + expediente (eventRecord).

        Args:
            placa:      placa del vehiculo asegurado
            expediente: numero de expediente = eventRecord en SIC

        Returns:
            [{"nombre": str, "url": str, "seccion_id": int}, ...]
            Lista vacia si no hay coincidencia.

        Raises:
            ValueError: si no existe ningun evento con ese eventRecord para la placa.
        """
        access_token, sub = self._autenticar()
        user_company_id, country_code = self._obtener_datos_usuario(sub)
        headers = self._bearer_headers(access_token)

        evento = self._buscar_evento_por_expediente(placa, expediente, user_company_id, country_code, headers)
        imagenes = self._obtener_imagenes(expediente, headers)

        logger.info(
            "Imagenes SIC obtenidas",
            extra={"placa": placa, "expediente": expediente, "total": len(imagenes)},
        )
        return imagenes

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _autenticar(self) -> tuple[str, str]:
        auth_url, _, _, _ = _build_urls()
        username = os.environ["SIC_API_USERNAME"]
        password = os.environ["SIC_API_PASSWORD"]
        resp = requests.post(
            auth_url,
            json={"username": username, "password": password, "mfaCode": None, "challengeSession": None},
            headers=_API_KEY_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        try:
            body = resp.json()
        except Exception:
            raise RuntimeError(f"SIC auth: respuesta no-JSON (status {resp.status_code}): {resp.text[:300]}")

        data = body.get("data") or body
        access_token = data.get("accessToken")
        if not access_token:
            raise RuntimeError(f"SIC auth: no se encontro accessToken. Body: {body}")

        sub = data.get("sub", "")
        logger.info("SIC API auth exitosa", extra={"sub": sub})
        return access_token, sub

    def _obtener_datos_usuario(self, sub: str) -> tuple[int, str]:
        _, user_url, _, _ = _build_urls()
        resp = requests.get(f"{user_url}/{sub}", headers=_API_KEY_HEADERS, timeout=10)
        resp.raise_for_status()
        try:
            body = resp.json()
        except Exception:
            raise RuntimeError(f"SIC usuarios: respuesta no-JSON (status {resp.status_code}): {resp.text[:300]}")

        data = body.get("data") or {}
        user_company_id = data.get("userCompanyID")
        country_code    = data.get("codPais", "PAN")

        if not user_company_id:
            raise RuntimeError(f"SIC usuarios: no se encontro userCompanyID. Body: {body}")

        return int(user_company_id), country_code

    def _buscar_evento_por_expediente(
        self, placa: str, expediente: str, user_id: int, country_code: str, headers: dict
    ) -> dict:
        """
        Busca eventos por placa y retorna el que coincide con eventRecord == expediente.

        Raises:
            ValueError: si no se encuentra el expediente para esa placa.
        """
        _, _, search_url, _ = _build_urls()
        params = {
            "filterType":  "INSURED_PLATE",
            "filterText":  placa,
            "countryCode": country_code,
            "companyId":   15,
            "rolId":       3,
            "page":        1,
            "userId":      user_id,
        }
        resp = requests.get(search_url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        try:
            body = resp.json()
        except Exception:
            raise RuntimeError(f"SIC search: respuesta no-JSON (status {resp.status_code}): {resp.text[:300]}")

        data = body.get("data") or {}
        if isinstance(data, dict):
            response = data.get("response") or {}
            eventos = response.get("events") or data.get("events") or []
        elif isinstance(data, list):
            eventos = data
        else:
            eventos = []

        for evento in eventos:
            if str(evento.get("eventRecord", "")) == str(expediente):
                return evento

        raise ValueError(
            f"Expediente '{expediente}' no encontrado en SIC para la placa '{placa}'. "
            f"Eventos disponibles: {[e.get('eventRecord') for e in eventos]}"
        )

    def _obtener_imagenes(self, event_record: str, headers: dict) -> list[dict]:
        _, _, _, images_url = _build_urls()
        url  = f"{images_url}/{event_record}"
        resp = requests.get(url, params={"forceUpdate": "true"}, headers=headers, timeout=20)
        resp.raise_for_status()
        try:
            body = resp.json()
        except Exception:
            raise RuntimeError(f"SIC images: respuesta no-JSON (status {resp.status_code}): {resp.text[:300]}")

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
