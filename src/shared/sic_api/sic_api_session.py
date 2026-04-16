"""
Gestiona las credenciales del SIC REST API en SSM.

A diferencia de SICSession (Playwright), esta sesion no necesita
almacenar storageState porque el JWT se obtiene con un POST simple.
El cliente hace login automaticamente en cada invocacion.
"""
import boto3


class SICApiSession:
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
