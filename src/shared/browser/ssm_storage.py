"""SSMStorageBackend — implementacion de StorageBackend usando AWS SSM Parameter Store.

Permite que orbika-login persista el storageState de Playwright en SSM en vez de
archivos locales, haciendo el login compatible con entornos Lambda (filesystem efimero).

Uso:
    from src.shared.browser.ssm_storage import SSMStorageBackend
    from login import SalesforceAuth

    storage = SSMStorageBackend(ssm_path="/agente/sf/state")
    auth = SalesforceAuth(url=sf_url, storage=storage, telegram_bot=bot)
    context = await auth.login(user=user, password=password)
"""

from __future__ import annotations

import json
import logging

import boto3
from login.storage.base import StorageBackend

logger = logging.getLogger(__name__)


class SSMStorageBackend(StorageBackend):
    """Persiste el storageState de Playwright en AWS SSM Parameter Store (SecureString)."""

    def __init__(self, ssm_path: str, region: str = "us-east-1", ssm_client=None) -> None:
        self._ssm_path = ssm_path
        self._ssm = ssm_client or boto3.client("ssm", region_name=region)

    async def load(self) -> dict | None:
        """Carga el storageState desde SSM. Retorna None si no existe."""
        try:
            response = self._ssm.get_parameter(
                Name=self._ssm_path,
                WithDecryption=True,
            )
            state = json.loads(response["Parameter"]["Value"])
            logger.debug("StorageState cargado desde SSM '%s'", self._ssm_path)
            return state
        except self._ssm.exceptions.ParameterNotFound:
            logger.info("SSM '%s' no existe — sesion nueva requerida", self._ssm_path)
            return None
        except Exception as e:
            logger.warning("Error cargando storageState desde SSM '%s': %s", self._ssm_path, e)
            return None

    async def save(self, state: dict) -> None:
        """Persiste el storageState en SSM como SecureString."""
        self._ssm.put_parameter(
            Name=self._ssm_path,
            Value=json.dumps(state),
            Type="SecureString",
            Overwrite=True,
        )
        logger.info("StorageState guardado en SSM '%s'", self._ssm_path)
