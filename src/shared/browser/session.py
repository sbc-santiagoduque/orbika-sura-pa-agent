import asyncio
import json
import logging
from typing import Any

import boto3

logger = logging.getLogger(__name__)


class SalesforceSession:
    """
    Gestiona la sesión autenticada de Salesforce para los Lambda tools de RPA.

    Problema que resuelve: Salesforce pide 2FA en el primer login. Lambda es efímera
    y no puede mantener sesión entre invocaciones.

    Solución: tras la primera auth manual (scripts/capture_sf_session.py), el
    storageState completo (cookies + localStorage) se serializa en SSM SecureString.
    Cada Lambda lo carga al iniciar e inicializa el contexto de Playwright con él.

    Cuando la sesión expira, refresh_login() ejecuta un login fresco via orbika-login
    (incluyendo verificación SMS si Salesforce lo requiere) y actualiza SSM.

    Por qué storageState y no solo cookies:
        Salesforce Lightning guarda el token de "dispositivo confiable" en localStorage,
        no en cookies. Sin él, cada browser nuevo pide 2FA aunque las cookies sean válidas.
        Ver: construccion/salesforce_rpa_findings.md

    Cuando Sura Panamá habilite la API de Salesforce (ADR-U2-1), esta clase
    queda obsoleta y se reemplaza por un cliente REST directo.
    """

    def __init__(self, ssm_path: str, region: str = "us-east-1", ssm_client=None):
        self._ssm_path = ssm_path
        self._ssm = ssm_client or boto3.client("ssm", region_name=region)

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
        """Persiste el storageState actualizado en SSM."""
        self._ssm.put_parameter(
            Name=self._ssm_path,
            Value=json.dumps(storage_state),
            Type="SecureString",
            Overwrite=True,
        )

    def inject_storage_state(self, playwright_browser) -> Any:
        """
        Crea y retorna un contexto de Playwright inicializado con el storageState.

        El storageState incluye cookies Y localStorage (token de dispositivo confiable),
        por lo que Salesforce no pedirá 2FA.
        """
        storage_state = self.load_storage_state()
        return playwright_browser.new_context(storage_state=storage_state)

    def refresh_login(
        self,
        sf_url: str,
        ssm_username_path: str,
        ssm_password_path: str,
        telegram_bot=None,
    ) -> None:
        """
        Ejecuta un login fresco en Salesforce via orbika-login y actualiza SSM.

        Llama al flujo completo (restore → login → SMS si aplica) usando async
        Playwright internamente. Al terminar, SSM tiene el nuevo storageState y
        inject_storage_state() funcionará con la sesión renovada.

        Args:
            sf_url:             URL de Salesforce — puede ser login o la app directamente.
            ssm_username_path:  Path SSM del usuario de Salesforce.
            ssm_password_path:  Path SSM de la contraseña de Salesforce.
            telegram_bot:       Bot de Telegram para recibir el código SMS (opcional).
                                Si es None y Salesforce pide SMS, el login fallará por timeout.
        """
        from login import SalesforceAuth
        from src.shared.browser.ssm_storage import SSMStorageBackend

        username = self._ssm.get_parameter(
            Name=ssm_username_path, WithDecryption=True,
        )["Parameter"]["Value"]
        password = self._ssm.get_parameter(
            Name=ssm_password_path, WithDecryption=True,
        )["Parameter"]["Value"]

        storage = SSMStorageBackend(ssm_path=self._ssm_path, ssm_client=self._ssm)
        auth = SalesforceAuth(url=sf_url, storage=storage, telegram_bot=telegram_bot)

        async def _run():
            try:
                await auth.login(user=username, password=password)
            finally:
                await auth.close()

        asyncio.run(_run())
        logger.info("Re-login Salesforce completado — estado actualizado en SSM '%s'", self._ssm_path)
