"""
Cliente HTTP para la API de Orbika (Liferay JSONWS).

Flujo de autenticacion (HTTP puro, sin Playwright):
  1. GET /web/guest/login -> extraer portlet instance ID + p_auth pre-login
  2. POST credentials (multipart/form-data) -> cookies de sesion (JSESSIONID, ID, ...)
  3. Extraer Liferay.authToken de la pagina /navigation
  4. POST consultar-ultima-sesion -> restaurar contexto rol=Analista/org=Sura Panama
  5. POST /api/jsonws/invoke con cmd + p_auth

El login se ejecuta en cada invocacion (~3 requests adicionales, < 1s).
"""
import json
import logging
import re

import requests

from src.shared.orbika.orbika_session import OrbikaSession

logger = logging.getLogger(__name__)

_ORBIKA_BASE    = "https://orbika.subocol.com"
_LOGIN_PAGE_URL = f"{_ORBIKA_BASE}/web/guest/login"
_INVOKE_URL     = f"{_ORBIKA_BASE}/api/jsonws/invoke"
_ASEGURADORA    = "Sura Panama"

_RE_PORTLET_ID   = re.compile(
    r'com_subocol_orbika_login_SubocolLoginPortlet_INSTANCE_(\w+)'
)
_RE_GUEST_P_AUTH = re.compile(r'p_auth=([A-Za-z0-9_-]{8})')
_RE_AUTH_TOKEN   = re.compile(r'Liferay\.authToken\s*=\s*["\']([^"\']+)["\']')

_CMD_ULTIMA_SESION = {"/permisos.sesionaudit/consultar-ultima-sesion": {}}


class OrbikaClient:
    def __init__(self, session: OrbikaSession):
        self._session = session

    def listar_avisos(self, placa: str) -> list[dict]:
        """
        Busca todos los avisos en Orbika para una placa dada.

        Args:
            placa: Numero de placa del vehiculo (ej. "422644")

        Returns:
            Lista de avisos. Lista vacia si no hay resultados.
        """
        http, p_auth = self._login()
        self._restaurar_sesion(http, p_auth)

        cmd = {
            "/adminAvisos.aviso/Listar-avisos-talleres": {
                "aseguradora": _ASEGURADORA,
                "cobertura": [], "regional": [], "estado": [], "taller": [],
                "tipofecha": None, "fechaini": None, "tipoVehiculo": [],
                "buscador": "placa",
                "valorBuscado": placa,
                "imprevistos": False,
            }
        }
        response = http.post(
            _INVOKE_URL,
            data={"cmd": json.dumps(cmd), "p_auth": p_auth},
            headers={"X-Requested-With": "XMLHttpRequest"},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()

        if isinstance(data, dict) and "exception" in data:
            raise RuntimeError(f"Error Orbika API: {data['exception']}")

        return data if isinstance(data, list) else []

    def _login(self) -> tuple[requests.Session, str]:
        """
        Realiza el login HTTP completo.
        Retorna (requests.Session con cookies, p_auth autenticado).
        """
        username, password = self._session.load_credentials()

        http = requests.Session()
        http.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "es-ES,es;q=0.9",
        })

        # Paso 1: GET login page -> portlet instance ID + p_auth pre-login
        resp0 = http.get(_LOGIN_PAGE_URL, timeout=15)
        resp0.raise_for_status()

        m_pid = _RE_PORTLET_ID.search(resp0.text)
        m_pa  = _RE_GUEST_P_AUTH.search(resp0.text)
        if not m_pid or not m_pa:
            raise RuntimeError("No se pudo extraer portlet ID o p_auth de la pagina de login")

        portlet_instance = (
            f"com_subocol_orbika_login_SubocolLoginPortlet_INSTANCE_{m_pid.group(1)}"
        )
        prefix        = f"_{portlet_instance}_"
        pre_p_auth    = m_pa.group(1)

        # Paso 2: POST credenciales (multipart/form-data)
        login_url = (
            f"{_LOGIN_PAGE_URL}"
            f"?p_p_id={portlet_instance}"
            f"&p_p_lifecycle=1&p_p_state=normal&p_p_mode=view"
            f"&{prefix}javax.portlet.action=%2Flogin"
            f"&{prefix}mvcRenderCommandName=%2Flogin"
            f"&p_auth={pre_p_auth}"
        )
        resp1 = http.post(
            login_url,
            files={
                f"{prefix}username": (None, username),
                f"{prefix}password": (None, password),
                f"{prefix}terminos": (None, "on"),
            },
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "X-PJAX": "true",
                "Origin": _ORBIKA_BASE,
                "Referer": _LOGIN_PAGE_URL,
            },
            allow_redirects=True,
            timeout=15,
        )
        resp1.raise_for_status()

        if "ID" not in http.cookies:
            raise RuntimeError("Login Orbika fallido: cookie 'ID' no obtenida")

        # Paso 3: extraer p_auth autenticado de /navigation
        m_auth = _RE_AUTH_TOKEN.search(resp1.text)
        if not m_auth:
            m_auth = re.search(r'p_auth=([A-Za-z0-9_-]{8})', resp1.text)
        if not m_auth:
            raise RuntimeError("No se pudo extraer Liferay.authToken de /navigation")

        p_auth = m_auth.group(1)
        logger.info("Login Orbika exitoso", extra={"url": resp1.url})
        return http, p_auth

    def _restaurar_sesion(self, http: requests.Session, p_auth: str) -> None:
        """
        Llama a consultar-ultima-sesion para restaurar el contexto
        rol=Analista Aseguradora / org=Sura Panama sin interaccion manual.
        """
        resp = http.post(
            _INVOKE_URL,
            data={"cmd": json.dumps(_CMD_ULTIMA_SESION), "p_auth": p_auth},
            headers={"X-Requested-With": "XMLHttpRequest"},
            timeout=15,
        )
        resp.raise_for_status()
        sesion = resp.json()
        if isinstance(sesion, dict) and "rolName" in sesion:
            logger.info(
                "Sesion Orbika restaurada",
                extra={"rol": sesion.get("rolName"), "org": sesion.get("organizationName")},
            )
