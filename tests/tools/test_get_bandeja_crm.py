import json
import pytest
from unittest.mock import MagicMock, patch

import src.tools.get_bandeja_crm.lambda_function as handler_module

EVENT_BASE = {
    "actionGroup": "agente-ingesta-actions",
    "function": "get_bandeja_crm",
    "parameters": [],
}

ENV_VARS = {
    "SSM_SF_COOKIES_PATH": "/agente-analista/salesforce/cookies",
    "SF_REPORT_URL": "https://surapa.lightning.force.com/lightning/r/Report/00OS6000006Sz9xMAC/view",
}

CASOS_SCRAPER = [
    {"case_number": "02188582", "sf_record_id": "500VY00000ic55TYAQ"},
    {"case_number": "02188590", "sf_record_id": "500VY00000ic60XBAQ"},
    {"case_number": "02188601", "sf_record_id": "500VY00000ic71YCAQ"},
]


class TestGetBandejaCrmHandler:
    @patch("src.tools.get_bandeja_crm.infrastructure.salesforce_scraper.SalesforceScraper")
    def test_retorna_formato_bedrock_action_group(self, mock_scraper_cls, monkeypatch):
        """La respuesta debe seguir el formato que Bedrock AG espera."""
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)

        mock_scraper_cls.return_value.obtener_bandeja.return_value = CASOS_SCRAPER

        resultado = handler_module.lambda_handler(EVENT_BASE, {})

        assert resultado["actionGroup"] == "agente-ingesta-actions"
        assert resultado["function"] == "get_bandeja_crm"
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])
        assert "casos" in body
        assert isinstance(body["total"], int)

    @patch("src.tools.get_bandeja_crm.infrastructure.salesforce_scraper.SalesforceScraper")
    def test_respeta_orden_del_reporte(self, mock_scraper_cls, monkeypatch):
        """Los casos deben devolverse en el orden exacto que retorna el scraper."""
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)

        mock_scraper_cls.return_value.obtener_bandeja.return_value = CASOS_SCRAPER

        resultado = handler_module.lambda_handler(EVENT_BASE, {})
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])

        numeros = [c["case_number"] for c in body["casos"]]
        assert numeros == ["02188582", "02188590", "02188601"]

    @patch("src.tools.get_bandeja_crm.infrastructure.salesforce_scraper.SalesforceScraper")
    def test_cada_caso_tiene_case_number_y_sf_record_id(self, mock_scraper_cls, monkeypatch):
        """Cada elemento debe exponer los dos campos que necesitan las tools downstream."""
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)

        mock_scraper_cls.return_value.obtener_bandeja.return_value = CASOS_SCRAPER

        resultado = handler_module.lambda_handler(EVENT_BASE, {})
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])

        for caso in body["casos"]:
            assert "case_number" in caso
            assert "sf_record_id" in caso

    @patch("src.tools.get_bandeja_crm.infrastructure.salesforce_scraper.SalesforceScraper")
    def test_bandeja_vacia_retorna_total_cero(self, mock_scraper_cls, monkeypatch):
        """Si el reporte no tiene casos, total debe ser 0."""
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)

        mock_scraper_cls.return_value.obtener_bandeja.return_value = []

        resultado = handler_module.lambda_handler(EVENT_BASE, {})
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])

        assert body["total"] == 0
        assert body["casos"] == []

    def test_error_si_faltan_env_vars(self, monkeypatch):
        """Sin variables de entorno retorna respuesta de error estructurada."""
        monkeypatch.delenv("SSM_SF_COOKIES_PATH", raising=False)
        monkeypatch.delenv("SF_REPORT_URL", raising=False)

        resultado = handler_module.lambda_handler(EVENT_BASE, {})
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])

        assert "error" in body
        assert body["total"] == 0
