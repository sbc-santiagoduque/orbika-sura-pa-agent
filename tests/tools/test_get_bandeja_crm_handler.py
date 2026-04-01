import json
import pytest
from unittest.mock import MagicMock, patch

import src.tools.get_bandeja_crm.lambda_function as handler_module

# Evento que Bedrock Action Group envía al Lambda
EVENT_BASE = {
    "actionGroup": "agente-ingesta-actions",
    "function": "get_bandeja_crm",
    "parameters": [],
}

ENV_VARS = {
    "SSM_SF_COOKIES_PATH": "/agente-analista/salesforce/cookies",
    "SF_BASE_URL": "https://sura-panama.my.salesforce.com",
}

CASOS_RAW = [
    {"case_id": "C-002", "placa": "XYZ", "canal": "SIC",
     "fecha_siniestro": "2026-03-11T08:00:00Z",
     "fecha_recepcion": "2026-03-19T10:00:00Z", "sla_alert": False},
    {"case_id": "C-001", "placa": "ABC", "canal": "Comunidad",
     "fecha_siniestro": "2026-03-12T08:00:00Z",
     "fecha_recepcion": "2026-03-18T08:00:00Z", "sla_alert": True},
]


class TestGetBandejaCrmHandler:
    @patch("src.tools.get_bandeja_crm.infrastructure.salesforce_scraper.SalesforceScraper")
    def test_retorna_formato_bedrock_action_group(self, mock_scraper_cls, monkeypatch):
        """La respuesta debe seguir el formato que Bedrock AG espera."""
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)

        mock_scraper = MagicMock()
        mock_scraper.obtener_bandeja.return_value = [CASOS_RAW[1]]
        mock_scraper_cls.return_value = mock_scraper

        resultado = handler_module.lambda_handler(EVENT_BASE, {})

        assert resultado["actionGroup"] == "agente-ingesta-actions"
        assert resultado["function"] == "get_bandeja_crm"
        assert "functionResponse" in resultado
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])
        assert "casos" in body
        assert isinstance(body["total"], int)

    @patch("src.tools.get_bandeja_crm.infrastructure.salesforce_scraper.SalesforceScraper")
    def test_prioriza_casos_antes_de_retornar(self, mock_scraper_cls, monkeypatch):
        """El handler aplica BandejaService.priorizar() sobre los datos del scraper."""
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)

        mock_scraper = MagicMock()
        mock_scraper.obtener_bandeja.return_value = CASOS_RAW  # sin prioridad
        mock_scraper_cls.return_value = mock_scraper

        resultado = handler_module.lambda_handler(EVENT_BASE, {})
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])

        # C-001 (sla_alert=True) debe ir primero con prioridad 1
        assert body["casos"][0]["case_id"] == "C-001"
        assert body["casos"][0]["prioridad"] == 1
        assert body["total"] == 2

    def test_error_si_faltan_env_vars(self, monkeypatch):
        """Sin variables de entorno retorna respuesta de error (no exception)."""
        monkeypatch.delenv("SSM_SF_COOKIES_PATH", raising=False)
        monkeypatch.delenv("SF_BASE_URL", raising=False)

        resultado = handler_module.lambda_handler(EVENT_BASE, {})

        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])
        assert "error" in body
        assert body["total"] == 0
