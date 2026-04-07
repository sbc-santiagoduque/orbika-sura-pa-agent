"""
Gestiona la sesion de Orbika (cookies + p_auth) en SSM.

Orbika es un portal Liferay. La autenticacion requiere:
  - Cookies de sesion: JSESSIONID, ID, COMPANY_ID, LFR_SESSION_STATE_*
  - p_auth: token CSRF de Liferay (Liferay.authToken), valido por sesion

Captura inicial: scripts/capture_orbika_session.py (requiere login manual).
Cuando la sesion expira la Lambda retorna error y hay que re-capturar.
"""
import json
import logging

import boto3

logger = logging.getLogger(__name__)

_COOKIE_KEYS = [
    "JSESSIONID",
    "ID",
    "COMPANY_ID",
    "GUEST_LANGUAGE_ID",
    "COOKIE_SUPPORT",
]


class OrbikaSession:
    def __init__(self, ssm_session_path: str, ssm_client=None):
        self._path = ssm_session_path
        self._ssm = ssm_client or boto3.client("ssm")

    def load(self) -> tuple[dict, str]:
        """Retorna (cookies_dict, p_auth) desde SSM."""
        response = self._ssm.get_parameter(Name=self._path, WithDecryption=True)
        data = json.loads(response["Parameter"]["Value"])
        return data["cookies"], data["p_auth"]

    def save(self, cookies: dict, p_auth: str) -> None:
        """Persiste cookies + p_auth en SSM como SecureString."""
        value = json.dumps({"cookies": cookies, "p_auth": p_auth}, ensure_ascii=False)
        self._ssm.put_parameter(
            Name=self._path,
            Value=value,
            Type="SecureString",
            Overwrite=True,
        )
        logger.info("OrbikaSession guardada en SSM", extra={"path": self._path})
