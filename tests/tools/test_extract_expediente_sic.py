import json
import pytest
from unittest.mock import MagicMock, patch

import src.tools.extract_expediente_sic.lambda_function as handler_module

EVENT_BASE = {
    "actionGroup": "agente-expediente-actions",
    "function": "extract_expediente_sic",
    "parameters": [
        {"name": "placa", "type": "string", "value": "CU7559"}
    ],
}

ENV_VARS = {
    "SSM_SIC_STATE_PATH": "/agente-analista/sic/state",
    "SSM_SIC_USERNAME_PATH": "/agente-analista/sic/username",
    "SSM_SIC_PASSWORD_PATH": "/agente-analista/sic/password",
}

EXPEDIENTE_MOCK = {
    "expediente_url": "https://sic.connectasistencia.com/claims/591fbbdd/view",
    "imagen_count": 13,
    "imagen_urls": [
        "https://inspeccionespty.s3.us-east-2.amazonaws.com/5105712/3_1775489295790.jpg",
        "https://inspeccionespty.s3.us-east-2.amazonaws.com/5105712/3_1775489295791.jpg",
    ],
    "imagen_urls_signed": [
        "https://inspeccionespty.s3.us-east-2.amazonaws.com/5105712/3_1775489295790.jpg?X-Amz-Expires=604800",
        "https://inspeccionespty.s3.us-east-2.amazonaws.com/5105712/3_1775489295791.jpg?X-Amz-Expires=604800",
    ],
    "tiene_documentos": True,
}


class TestExtractExpedienteSicHandler:
    @patch("src.tools.extract_expediente_sic.infrastructure.sic_scraper.SICScraper")
    def test_retorna_formato_bedrock_action_group(self, mock_scraper_cls, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)

        mock_scraper_cls.return_value.obtener_expediente.return_value = EXPEDIENTE_MOCK

        resultado = handler_module.lambda_handler(EVENT_BASE, {})

        assert resultado["actionGroup"] == "agente-expediente-actions"
        assert resultado["function"] == "extract_expediente_sic"
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])
        assert "expediente" in body

    @patch("src.tools.extract_expediente_sic.infrastructure.sic_scraper.SICScraper")
    def test_retorna_conteo_imagenes_y_flag_documentos(self, mock_scraper_cls, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)

        mock_scraper_cls.return_value.obtener_expediente.return_value = EXPEDIENTE_MOCK

        resultado = handler_module.lambda_handler(EVENT_BASE, {})
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])

        assert body["expediente"]["imagen_count"] == 13
        assert body["expediente"]["tiene_documentos"] is True

    @patch("src.tools.extract_expediente_sic.infrastructure.sic_scraper.SICScraper")
    def test_sin_documentos_flag_false(self, mock_scraper_cls, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)

        mock_scraper_cls.return_value.obtener_expediente.return_value = {
            **EXPEDIENTE_MOCK,
            "imagen_count": 0,
            "imagen_urls": [],
            "tiene_documentos": False,
        }

        resultado = handler_module.lambda_handler(EVENT_BASE, {})
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])

        assert body["expediente"]["tiene_documentos"] is False
        assert body["expediente"]["imagen_count"] == 0

    def test_error_si_falta_parametro_placa(self, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)

        evento_sin_placa = {**EVENT_BASE, "parameters": []}
        resultado = handler_module.lambda_handler(evento_sin_placa, {})
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])

        assert "error" in body

    def test_error_si_faltan_env_vars(self, monkeypatch):
        for k in ENV_VARS:
            monkeypatch.delenv(k, raising=False)

        resultado = handler_module.lambda_handler(EVENT_BASE, {})
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])

        assert "error" in body
