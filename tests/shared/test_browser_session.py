import json
import pytest
import boto3
from moto import mock_aws
from unittest.mock import MagicMock, patch
from src.shared.browser.session import SalesforceSession

SSM_PATH = "/agente-analista/salesforce/cookies"

COOKIES_SAMPLE = [
    {"name": "sid", "value": "abc123", "domain": ".salesforce.com"},
    {"name": "oid", "value": "xyz456", "domain": ".salesforce.com"},
]


@mock_aws
class TestSalesforceSession:
    def _put_cookies_in_ssm(self):
        """Helper: guarda cookies de prueba en SSM mockeado."""
        client = boto3.client("ssm", region_name="us-east-1")
        client.put_parameter(
            Name=SSM_PATH,
            Value=json.dumps(COOKIES_SAMPLE),
            Type="SecureString",
        )

    def test_load_cookies_retorna_lista_desde_ssm(self):
        self._put_cookies_in_ssm()
        session = SalesforceSession(ssm_path=SSM_PATH, region="us-east-1")
        cookies = session.load_cookies()

        assert len(cookies) == 2
        assert cookies[0]["name"] == "sid"

    def test_load_cookies_falla_si_ssm_no_tiene_el_path(self):
        # SSM vacío — simula que nunca se autenticó
        session = SalesforceSession(ssm_path=SSM_PATH, region="us-east-1")
        with pytest.raises(RuntimeError, match="Cookies de Salesforce no encontradas"):
            session.load_cookies()

    def test_save_cookies_persiste_en_ssm(self):
        self._put_cookies_in_ssm()
        session = SalesforceSession(ssm_path=SSM_PATH, region="us-east-1")

        nuevas_cookies = [{"name": "sid", "value": "nuevo_token", "domain": ".salesforce.com"}]
        session.save_cookies(nuevas_cookies)

        # Verificar que se guardaron
        cookies = session.load_cookies()
        assert cookies[0]["value"] == "nuevo_token"

    def test_inject_cookies_llama_context_add_cookies(self):
        self._put_cookies_in_ssm()
        session = SalesforceSession(ssm_path=SSM_PATH, region="us-east-1")

        # Mock del contexto de Playwright
        mock_context = MagicMock()
        session.inject_cookies(mock_context)

        mock_context.add_cookies.assert_called_once_with(COOKIES_SAMPLE)
