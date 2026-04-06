import json
import boto3
from typing import Any


class SICSession:
    """
    Gestiona la sesión autenticada de SIC (sic.connectasistencia.com).

    A diferencia de SalesforceSession, el refresh es completamente automático
    — SIC no tiene 2FA, solo usuario + contraseña. El flujo es:

      1. Intentar cargar storageState desde SSM (sesión previa)
      2. Si existe → inyectar en el contexto de Playwright (sin login)
      3. Si no existe o expiró → el scraper hace login con user/pass desde SSM
                                → guarda el nuevo storageState en SSM

    Las credenciales (usuario/contraseña) viven en SSM SecureString.
    En desarrollo local se leen desde .env vía variables de entorno.
    """

    def __init__(
        self,
        ssm_state_path: str,
        ssm_username_path: str,
        ssm_password_path: str,
        region: str = "us-east-1",
    ):
        self._ssm_state_path = ssm_state_path
        self._ssm_username_path = ssm_username_path
        self._ssm_password_path = ssm_password_path
        self._ssm = boto3.client("ssm", region_name=region)

    def load_storage_state(self) -> dict | None:
        """
        Carga el storageState desde SSM.

        Returns:
            Dict con storageState si existe, None si no hay sesión guardada.
            None indica que el scraper debe hacer login con user/pass.
        """
        try:
            response = self._ssm.get_parameter(
                Name=self._ssm_state_path,
                WithDecryption=True,
            )
            return json.loads(response["Parameter"]["Value"])
        except self._ssm.exceptions.ParameterNotFound:
            return None

    def load_credentials(self) -> tuple[str, str]:
        """
        Carga usuario y contraseña desde SSM.

        Returns:
            Tupla (username, password).
        """
        username = self._ssm.get_parameter(
            Name=self._ssm_username_path,
            WithDecryption=True,
        )["Parameter"]["Value"]

        password = self._ssm.get_parameter(
            Name=self._ssm_password_path,
            WithDecryption=True,
        )["Parameter"]["Value"]

        return username, password

    def save_storage_state(self, storage_state: dict) -> None:
        """Persiste el storageState actualizado en SSM."""
        self._ssm.put_parameter(
            Name=self._ssm_state_path,
            Value=json.dumps(storage_state),
            Type="SecureString",
            Overwrite=True,
        )

    def get_context(self, playwright_browser: Any) -> Any:
        """
        Crea un contexto de Playwright con storageState si existe,
        o vacío si no hay sesión guardada (el scraper hará login).

        Args:
            playwright_browser: instancia Browser de Playwright

        Returns:
            BrowserContext listo para usar.
        """
        storage_state = self.load_storage_state()
        if storage_state:
            return playwright_browser.new_context(storage_state=storage_state)
        return playwright_browser.new_context()
