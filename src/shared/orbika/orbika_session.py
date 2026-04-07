"""
Gestiona las credenciales de Orbika en SSM.

Orbika permite login HTTP puro (sin Playwright):
  GET /web/guest/login -> extraer portlet ID + pre-login p_auth
  POST credentials (multipart/form-data) -> cookies de sesion
  Extraer Liferay.authToken de /navigation
  POST consultar-ultima-sesion -> restaurar rol/org (Sura Panama / Analista)

No se necesita captura manual ni storageState. El cliente hace login
automaticamente en cada invocacion.
"""
import json
import logging

import boto3

logger = logging.getLogger(__name__)


class OrbikaSession:
    def __init__(
        self,
        ssm_username_path: str,
        ssm_password_path: str,
        ssm_client=None,
    ):
        self._username_path = ssm_username_path
        self._password_path = ssm_password_path
        self._ssm = ssm_client or boto3.client("ssm")

    def load_credentials(self) -> tuple[str, str]:
        """Retorna (username, password) desde SSM."""
        username = self._ssm.get_parameter(
            Name=self._username_path, WithDecryption=True
        )["Parameter"]["Value"]
        password = self._ssm.get_parameter(
            Name=self._password_path, WithDecryption=True
        )["Parameter"]["Value"]
        return username, password
