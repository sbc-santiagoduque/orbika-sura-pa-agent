import json
import pytest
import boto3
from moto import mock_aws
from unittest.mock import MagicMock, patch, call
from src.shared.browser.sic_session import SICSession

SSM_PATH_STATE = "/agente-analista/sic/state"
SSM_PATH_USER = "/agente-analista/sic/username"
SSM_PATH_PASS = "/agente-analista/sic/password"

STORAGE_STATE_SAMPLE = {
    "cookies": [
        {"name": "connect.sid", "value": "s%3Aabc123", "domain": "sic.connectasistencia.com",
         "path": "/", "expires": -1, "httpOnly": True, "secure": True, "sameSite": "Lax"},
    ],
    "origins": [],
}


@mock_aws
class TestSICSession:
    def _setup_ssm(self, with_state=True):
        client = boto3.client("ssm", region_name="us-east-1")
        client.put_parameter(Name=SSM_PATH_USER, Value="analista@sura.com", Type="SecureString")
        client.put_parameter(Name=SSM_PATH_PASS, Value="password123", Type="SecureString")
        if with_state:
            client.put_parameter(
                Name=SSM_PATH_STATE,
                Value=json.dumps(STORAGE_STATE_SAMPLE),
                Type="SecureString",
            )

    def test_load_storage_state_retorna_dict_desde_ssm(self):
        self._setup_ssm(with_state=True)
        session = SICSession(
            ssm_state_path=SSM_PATH_STATE,
            ssm_username_path=SSM_PATH_USER,
            ssm_password_path=SSM_PATH_PASS,
            region="us-east-1",
        )
        state = session.load_storage_state()
        assert "cookies" in state
        assert state["cookies"][0]["name"] == "connect.sid"

    def test_load_storage_state_retorna_none_si_no_existe(self):
        """Sin state en SSM retorna None — indica que hay que hacer login."""
        self._setup_ssm(with_state=False)
        session = SICSession(
            ssm_state_path=SSM_PATH_STATE,
            ssm_username_path=SSM_PATH_USER,
            ssm_password_path=SSM_PATH_PASS,
            region="us-east-1",
        )
        assert session.load_storage_state() is None

    def test_load_credentials_retorna_user_y_password(self):
        self._setup_ssm(with_state=False)
        session = SICSession(
            ssm_state_path=SSM_PATH_STATE,
            ssm_username_path=SSM_PATH_USER,
            ssm_password_path=SSM_PATH_PASS,
            region="us-east-1",
        )
        username, password = session.load_credentials()
        assert username == "analista@sura.com"
        assert password == "password123"

    def test_save_storage_state_persiste_en_ssm(self):
        self._setup_ssm(with_state=True)
        session = SICSession(
            ssm_state_path=SSM_PATH_STATE,
            ssm_username_path=SSM_PATH_USER,
            ssm_password_path=SSM_PATH_PASS,
            region="us-east-1",
        )
        nuevo_state = {**STORAGE_STATE_SAMPLE, "cookies": [
            {"name": "connect.sid", "value": "nuevo_token", "domain": "sic.connectasistencia.com",
             "path": "/", "expires": -1, "httpOnly": True, "secure": True, "sameSite": "Lax"},
        ]}
        session.save_storage_state(nuevo_state)
        assert session.load_storage_state()["cookies"][0]["value"] == "nuevo_token"

    def test_get_context_usa_storage_state_si_existe(self):
        """Si hay storageState en SSM, crea contexto con él (sin login)."""
        self._setup_ssm(with_state=True)
        session = SICSession(
            ssm_state_path=SSM_PATH_STATE,
            ssm_username_path=SSM_PATH_USER,
            ssm_password_path=SSM_PATH_PASS,
            region="us-east-1",
        )
        mock_browser = MagicMock()
        session.get_context(mock_browser)
        mock_browser.new_context.assert_called_once_with(
            storage_state=STORAGE_STATE_SAMPLE
        )

    def test_get_context_retorna_contexto_sin_state_para_login_manual(self):
        """Sin storageState, retorna contexto vacío — el scraper hará login."""
        self._setup_ssm(with_state=False)
        session = SICSession(
            ssm_state_path=SSM_PATH_STATE,
            ssm_username_path=SSM_PATH_USER,
            ssm_password_path=SSM_PATH_PASS,
            region="us-east-1",
        )
        mock_browser = MagicMock()
        session.get_context(mock_browser)
        # Sin storageState → new_context sin argumentos
        mock_browser.new_context.assert_called_once_with()
