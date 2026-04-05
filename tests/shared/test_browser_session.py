import json
import pytest
import boto3
from moto import mock_aws
from unittest.mock import MagicMock
from src.shared.browser.session import SalesforceSession

SSM_PATH = "/agente-analista/salesforce/state"

# storageState completo (cookies + localStorage) tal como lo genera Playwright
STORAGE_STATE_SAMPLE = {
    "cookies": [
        {"name": "sid", "value": "abc123", "domain": "surapa.lightning.force.com",
         "path": "/", "expires": -1, "httpOnly": True, "secure": True, "sameSite": "Lax"},
    ],
    "origins": [
        {
            "origin": "https://surapa.lightning.force.com",
            "localStorage": [
                {"name": "trusted_device_token", "value": "tok_xyz"},
            ],
        }
    ],
}


@mock_aws
class TestSalesforceSession:
    def _put_state_in_ssm(self):
        client = boto3.client("ssm", region_name="us-east-1")
        client.put_parameter(
            Name=SSM_PATH,
            Value=json.dumps(STORAGE_STATE_SAMPLE),
            Type="SecureString",
        )

    def test_load_storage_state_retorna_dict_desde_ssm(self):
        self._put_state_in_ssm()
        session = SalesforceSession(ssm_path=SSM_PATH, region="us-east-1")
        state = session.load_storage_state()

        assert "cookies" in state
        assert "origins" in state
        assert state["cookies"][0]["name"] == "sid"
        assert state["origins"][0]["localStorage"][0]["name"] == "trusted_device_token"

    def test_load_storage_state_falla_si_ssm_no_tiene_el_path(self):
        session = SalesforceSession(ssm_path=SSM_PATH, region="us-east-1")
        with pytest.raises(RuntimeError, match="capture_sf_session.py"):
            session.load_storage_state()

    def test_save_storage_state_persiste_en_ssm(self):
        self._put_state_in_ssm()
        session = SalesforceSession(ssm_path=SSM_PATH, region="us-east-1")

        nuevo_state = {**STORAGE_STATE_SAMPLE, "cookies": [
            {"name": "sid", "value": "nuevo_token", "domain": "surapa.lightning.force.com",
             "path": "/", "expires": -1, "httpOnly": True, "secure": True, "sameSite": "Lax"},
        ]}
        session.save_storage_state(nuevo_state)

        state = session.load_storage_state()
        assert state["cookies"][0]["value"] == "nuevo_token"

    def test_inject_storage_state_crea_contexto_con_state(self):
        self._put_state_in_ssm()
        session = SalesforceSession(ssm_path=SSM_PATH, region="us-east-1")

        mock_browser = MagicMock()
        session.inject_storage_state(mock_browser)

        mock_browser.new_context.assert_called_once_with(
            storage_state=STORAGE_STATE_SAMPLE
        )
