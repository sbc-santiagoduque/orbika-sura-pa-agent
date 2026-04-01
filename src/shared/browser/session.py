import json
import boto3
from typing import Any

class SalesforceSession:
    """
    Gestiona la sesión autenticada de Salesforce para los Lambda tools de RPA.

    Problema que resuelve: Salesforce pide 2FA en el primer login. Lambda es efímera
    y no puede mantener sesión entre invocaciones. Solución: tras la primera auth
    manual, las cookies se serializan y guardan en SSM SecureString. Cada Lambda
    las carga al iniciar y las inyecta en el contexto de Playwright — evitando 2FA.

    Cuando Sura Panamá habilite la API de Salesforce (ADR-U2-1), esta clase
    queda obsoleta y se reemplaza por un cliente REST directo.
    """

    def __init__(self, ssm_path: str, region: str = "us-east-1"):
        # Inyectar ssm_path y region facilita tests con moto sin monkey-patching
        self._ssm_path = ssm_path
        self._ssm = boto3.client("ssm", region_name=region)

    def load_cookies(self) -> list[dict[str, Any]]:
        """
        Carga las cookies de sesión desde SSM Parameter Store.

        Raises:
            RuntimeError: si el parámetro no existe — indica que el analista
                          no ha realizado la autenticación inicial todavía.
        """
        try:
            response = self._ssm.get_parameter(
                Name=self._ssm_path,
                WithDecryption=True,  # SecureString requiere decriptado explícito
            )
            return json.loads(response["Parameter"]["Value"])
        except self._ssm.exceptions.ParameterNotFound:
            raise RuntimeError(
                f"Cookies de Salesforce no encontradas en SSM '{self._ssm_path}'. "
                "Ejecuta el script de autenticación inicial antes de usar el agente."
            )

    def save_cookies(self, cookies: list[dict[str, Any]]) -> None:
        """
        Persiste cookies actualizadas en SSM. Útil para refrescar la sesión
        si Salesforce renueva cookies durante la navegación.
        """
        self._ssm.put_parameter(
            Name=self._ssm_path,
            Value=json.dumps(cookies),
            Type="SecureString",
            Overwrite=True,
        )

    def inject_cookies(self, playwright_context: Any) -> None:
        """
        Inyecta las cookies en un contexto de Playwright ya creado.
        Llamar antes de navegar a cualquier URL de Salesforce.
        """
        cookies = self.load_cookies()
        playwright_context.add_cookies(cookies)
