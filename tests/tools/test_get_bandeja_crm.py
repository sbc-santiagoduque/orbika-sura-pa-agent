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

# Fixture con todos los campos que el scraper ahora debe retornar
CASOS_SCRAPER = [
    {
        "case_number": "02019304",
        "sf_record_id": "500VY00000ic55TYAQ",
        "opened_date": "10/16/2025",
        "last_modified": "4/06/2026 15:12",
        "subestado_autos": "En verificación",
        "placa": "BF9997",
        "contact_name": "DIANA MELISSA VASQUEZ ZUÑIGA",
        "account_name": "DIANA MELISSA VASQUEZ ZUÑIGA",
        "case_origin": "Comunidad",
        "expediente_sic": "",
        "numero_reclamo_core": "2025-10-259958",
    },
    {
        "case_number": "02019400",
        "sf_record_id": "500VY00000ic60XBAQ",
        "opened_date": "11/01/2025",
        "last_modified": "4/06/2026 16:30",
        "subestado_autos": "Pendiente documentos",
        "placa": "ZZ1234",
        "contact_name": "JUAN PEREZ",
        "account_name": "JUAN PEREZ",
        "case_origin": "Email",
        "expediente_sic": "2025-10-123456",
        "numero_reclamo_core": "2025-11-000001",
    },
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
        assert numeros == ["02019304", "02019400"]

    @patch("src.tools.get_bandeja_crm.infrastructure.salesforce_scraper.SalesforceScraper")
    def test_cada_caso_tiene_todos_los_campos(self, mock_scraper_cls, monkeypatch):
        """Cada caso debe incluir todos los campos del reporte."""
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)

        mock_scraper_cls.return_value.obtener_bandeja.return_value = CASOS_SCRAPER

        resultado = handler_module.lambda_handler(EVENT_BASE, {})
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])

        campos_requeridos = [
            "case_number", "sf_record_id",
            "opened_date", "last_modified", "subestado_autos",
            "placa", "contact_name", "account_name",
            "case_origin", "expediente_sic", "numero_reclamo_core",
        ]
        for caso in body["casos"]:
            for campo in campos_requeridos:
                assert campo in caso, f"Campo '{campo}' faltante en el caso"

    @patch("src.tools.get_bandeja_crm.infrastructure.salesforce_scraper.SalesforceScraper")
    def test_valores_del_primer_caso(self, mock_scraper_cls, monkeypatch):
        """Los valores del primer caso deben coincidir con los del reporte de ejemplo."""
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)

        mock_scraper_cls.return_value.obtener_bandeja.return_value = CASOS_SCRAPER

        resultado = handler_module.lambda_handler(EVENT_BASE, {})
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])

        caso = body["casos"][0]
        assert caso["case_number"] == "02019304"
        assert caso["sf_record_id"] == "500VY00000ic55TYAQ"
        assert caso["placa"] == "BF9997"
        assert caso["subestado_autos"] == "En verificación"
        assert caso["contact_name"] == "DIANA MELISSA VASQUEZ ZUÑIGA"
        assert caso["numero_reclamo_core"] == "2025-10-259958"
        assert caso["expediente_sic"] == ""  # vacío en el ejemplo real

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


class TestSalesforceScraperColumnMapping:
    """Tests unitarios del scraper — lógica de mapeo de columnas."""

    def test_normalizar_headers(self):
        """Verifica que los headers del reporte real se mapeen correctamente."""
        from src.tools.get_bandeja_crm.infrastructure.salesforce_scraper import (
            _normalizar,
            _HEADER_TO_FIELD,
        )
        headers_reales = [
            ("Opened Date",                      "opened_date"),
            ("Case Date/Time Last Modified",      "last_modified"),
            ("Subestados Autos",                  "subestado_autos"),
            ("Placa",                             "placa"),
            ("Case Number",                       "case_number"),
            ("Contact Name",                      "contact_name"),
            ("Account Name",                      "account_name"),
            ("Case Origin",                       "case_origin"),
            ("Expediente SIC",                    "expediente_sic"),
            ("Número de reclamo en el core",      "numero_reclamo_core"),
        ]
        for header, expected_field in headers_reales:
            normalized = _normalizar(header)
            field = _HEADER_TO_FIELD.get(normalized)
            assert field == expected_field, (
                f"Header '{header}' (normalizado: '{normalized}') "
                f"debería mapearse a '{expected_field}', obtuvo '{field}'"
            )

    def test_fallback_sin_headers_retorna_campos_vacios(self):
        """
        Si el frame no tiene headers de tabla, _extraer_casos debe retornar
        casos con solo case_number y sf_record_id (el resto vacío).
        """
        from src.tools.get_bandeja_crm.infrastructure.salesforce_scraper import (
            SalesforceScraper,
            _REQUIRED_FIELDS,
        )

        scraper = SalesforceScraper.__new__(SalesforceScraper)

        # Frame mock sin headers, con un link de caso
        link_mock = MagicMock()
        link_mock.get_attribute.return_value = "/lightning/r/500ABC123/view"
        link_mock.inner_text.return_value = "02019304"

        frame_mock = MagicMock()
        frame_mock.query_selector_all.side_effect = lambda sel: (
            [link_mock] if "a[href]" in sel else []
        )

        # _leer_columnas retorna {} → fallback
        with patch.object(scraper, "_leer_columnas", return_value={}):
            casos = scraper._extraer_casos(frame_mock)

        assert len(casos) == 1
        assert casos[0]["case_number"] == "02019304"
        assert casos[0]["sf_record_id"] == "500ABC123"
        for field in _REQUIRED_FIELDS:
            assert field in casos[0]
