import json
import pytest
from unittest.mock import MagicMock, patch

import src.tools.check_orbika.lambda_function as handler_module

EVENT_BASE = {
    "actionGroup": "agente-orbika-actions",
    "function": "check_orbika",
    "parameters": [
        {"name": "placa", "type": "string", "value": "422644"}
    ],
}

ENV_VARS = {
    "SSM_ORBIKA_USERNAME_PATH": "/agente-analista/orbika/username",
    "SSM_ORBIKA_PASSWORD_PATH": "/agente-analista/orbika/password",
}

AVISO_MOCK = {
    "nro_aviso": "71034",
    "estado": "Ajustado",
    "cobertura": "RC",
    "especialidad": "Colision",
    "placa_asegurado": "BT1526",
    "placa_tercero": "422644",
    "fecha_creacion_aviso": "2023-06-23 00:00:00",
    "nombre_comercial": "TALLER OMAR",
    "valorador": "Orbika",
}

AVISOS_MOCK = [AVISO_MOCK]


class TestCheckOrbikaHandler:
    @patch("src.tools.check_orbika.infrastructure.orbika_client.OrbikaClient")
    def test_retorna_formato_bedrock_action_group(self, mock_client_cls, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)
        mock_client_cls.return_value.listar_avisos.return_value = AVISOS_MOCK

        resultado = handler_module.lambda_handler(EVENT_BASE, {})

        assert resultado["actionGroup"] == "agente-orbika-actions"
        assert resultado["function"] == "check_orbika"
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])
        assert "orbika" in body

    @patch("src.tools.check_orbika.infrastructure.orbika_client.OrbikaClient")
    def test_tiene_aviso_true_cuando_hay_resultados(self, mock_client_cls, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)
        mock_client_cls.return_value.listar_avisos.return_value = AVISOS_MOCK

        resultado = handler_module.lambda_handler(EVENT_BASE, {})
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])

        assert body["orbika"]["tiene_aviso"] is True
        assert body["orbika"]["aviso_count"] == 1

    @patch("src.tools.check_orbika.infrastructure.orbika_client.OrbikaClient")
    def test_tiene_aviso_false_cuando_lista_vacia(self, mock_client_cls, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)
        mock_client_cls.return_value.listar_avisos.return_value = []

        resultado = handler_module.lambda_handler(EVENT_BASE, {})
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])

        assert body["orbika"]["tiene_aviso"] is False
        assert body["orbika"]["aviso_count"] == 0
        assert body["orbika"]["aviso_reciente"] is None

    @patch("src.tools.check_orbika.infrastructure.orbika_client.OrbikaClient")
    def test_retorna_aviso_mas_reciente(self, mock_client_cls, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)
        avisos = [
            {**AVISO_MOCK, "nro_aviso": "71034", "fecha_creacion_aviso": "2023-06-23 00:00:00"},
            {**AVISO_MOCK, "nro_aviso": "54887", "fecha_creacion_aviso": "2023-01-06 00:00:00"},
        ]
        mock_client_cls.return_value.listar_avisos.return_value = avisos

        resultado = handler_module.lambda_handler(EVENT_BASE, {})
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])

        assert body["orbika"]["aviso_reciente"]["nro_aviso"] == "71034"

    @patch("src.tools.check_orbika.infrastructure.orbika_client.OrbikaClient")
    def test_retorna_campos_relevantes_del_aviso(self, mock_client_cls, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)
        mock_client_cls.return_value.listar_avisos.return_value = AVISOS_MOCK

        resultado = handler_module.lambda_handler(EVENT_BASE, {})
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])

        aviso = body["orbika"]["aviso_reciente"]
        assert aviso["nro_aviso"] == "71034"
        assert aviso["estado"] == "Ajustado"
        assert aviso["cobertura"] == "RC"

    def test_error_si_falta_parametro_placa(self, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)

        evento = {**EVENT_BASE, "parameters": []}
        resultado = handler_module.lambda_handler(evento, {})
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])

        assert "error" in body

    def test_error_si_faltan_env_vars(self, monkeypatch):
        monkeypatch.delenv("SSM_ORBIKA_USERNAME_PATH", raising=False)
        monkeypatch.delenv("SSM_ORBIKA_PASSWORD_PATH", raising=False)

        resultado = handler_module.lambda_handler(EVENT_BASE, {})
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])

        assert "error" in body


class TestOrbikaSession:
    def test_carga_credenciales_desde_ssm(self):
        from src.shared.orbika.orbika_session import OrbikaSession

        mock_ssm = MagicMock()
        mock_ssm.get_parameter.side_effect = [
            {"Parameter": {"Value": "monicamolina"}},
            {"Parameter": {"Value": "supersecret"}},
        ]
        session = OrbikaSession(
            ssm_username_path="/test/username",
            ssm_password_path="/test/password",
            ssm_client=mock_ssm,
        )
        username, password = session.load_credentials()

        assert username == "monicamolina"
        assert password == "supersecret"
