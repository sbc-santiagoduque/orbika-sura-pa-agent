import json
import boto3
from typing import Any


class SalesforceSession:
    """
    Gestiona la sesión autenticada de Salesforce para los Lambda tools de RPA.

    Problema que resuelve: Salesforce pide 2FA en el primer login. Lambda es efímera
    y no puede mantener sesión entre invocaciones.

    Solución: tras la primera auth manual (scripts/capture_sf_session.py), el
    storageState completo (cookies + localStorage) se serializa en SSM SecureString.
    Cada Lambda lo carga al iniciar e inicializa el contexto de Playwright con él.

    Por qué storageState y no solo cookies:
        Salesforce Lightning guarda el token de "dispositivo confiable" en localStorage,
        no en cookies. Sin él, cada browser nuevo pide 2FA aunque las cookies sean válidas.
        Ver: construccion/salesforce_rpa_findings.md

    Cuando Sura Panamá habilite la API de Salesforce (ADR-U2-1), esta clase
    queda obsoleta y se reemplaza por un cliente REST directo.
    """

    def __init__(self, ssm_path: str, region: str = "us-east-1"):
        self._ssm_path = ssm_path
        self._ssm = boto3.client("ssm", region_name=region)

    def load_storage_state(self) -> dict:
        """
        Carga el storageState desde SSM Parameter Store.

        Returns:
            Dict con formato Playwright storageState:
            {"cookies": [...], "origins": [{"origin": "...", "localStorage": [...]}]}

        Raises:
            RuntimeError: si el parámetro no existe — indica que el operador
                          no ha ejecutado scripts/capture_sf_session.py todavía.
        """
        try:
            response = self._ssm.get_parameter(
                Name=self._ssm_path,
                WithDecryption=True,
            )
            return json.loads(response["Parameter"]["Value"])
        except self._ssm.exceptions.ParameterNotFound:
            raise RuntimeError(
                f"Sesión de Salesforce no encontrada en SSM '{self._ssm_path}'. "
                "Ejecuta scripts/capture_sf_session.py antes de usar el agente."
            )

    def save_storage_state(self, storage_state: dict) -> None:
        """
        Persiste el storageState actualizado en SSM.

        Llamar después de cada navegación exitosa para que Salesforce pueda
        renovar cookies de sesión sin invalidar el estado guardado.
        """
        self._ssm.put_parameter(
            Name=self._ssm_path,
            Value=json.dumps(storage_state),
            Type="SecureString",
            Overwrite=True,
        )

    def inject_storage_state(self, playwright_browser) -> Any:
        """
        Crea y retorna un contexto de Playwright inicializado con el storageState.

        Usar en lugar de browser.new_context() para obtener un contexto
        ya autenticado. El storageState incluye cookies Y localStorage,
        por lo que Salesforce no pedirá 2FA.

        Args:
            playwright_browser: instancia de Browser de Playwright

        Returns:
            BrowserContext listo para navegar a Salesforce sin login.
        """
        storage_state = self.load_storage_state()
        return playwright_browser.new_context(storage_state=storage_state)
