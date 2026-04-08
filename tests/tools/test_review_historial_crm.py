import json
import pytest
from unittest.mock import MagicMock, patch

import src.tools.review_historial_crm.lambda_function as handler_module
from src.tools.review_historial_crm.infrastructure.salesforce_case_scraper import (
    SalesforceCaseScraper,
    _limpiar,
)

EVENT_BASE = {
    "actionGroup": "agente-crm-actions",
    "function": "review_historial_crm",
    "parameters": [
        {"name": "sf_record_id", "type": "string", "value": "500SF000001ABCDE"}
    ],
}

ENV_VARS = {
    "SSM_SF_COOKIES_PATH": "/agente-analista/salesforce/cookies",
}

HISTORIAL_MOCK = {
    "sf_record_id": "500SF000001ABCDE",
    "case_number": "00001234",
    "status": "En Proceso",
    "subject": "Accidente vehicular - Placa 422644",
    "account_name": "Juan Perez",
    "created_date": "4/1/2026",
    "comments": [
        {"fecha": "4/5/2026", "autor": "Ana Lopez", "texto": "Se solicito documentacion adicional al asegurado."},
        {"fecha": "4/3/2026", "autor": "Ana Lopez", "texto": "Caso recibido y registrado en sistema."},
    ],
}


class TestReviewHistorialCrmHandler:
    @patch("src.tools.review_historial_crm.infrastructure.salesforce_case_scraper.SalesforceCaseScraper")
    def test_retorna_formato_bedrock_action_group(self, mock_scraper_cls, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)
        mock_scraper_cls.return_value.obtener_historial.return_value = HISTORIAL_MOCK

        resultado = handler_module.lambda_handler(EVENT_BASE, {})

        assert resultado["actionGroup"] == "agente-crm-actions"
        assert resultado["function"] == "review_historial_crm"
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])
        assert "historial" in body

    @patch("src.tools.review_historial_crm.infrastructure.salesforce_case_scraper.SalesforceCaseScraper")
    def test_retorna_campos_correctos(self, mock_scraper_cls, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)
        mock_scraper_cls.return_value.obtener_historial.return_value = HISTORIAL_MOCK

        resultado = handler_module.lambda_handler(EVENT_BASE, {})
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])

        h = body["historial"]
        assert h["sf_record_id"] == "500SF000001ABCDE"
        assert h["case_number"] == "00001234"
        assert h["status"] == "En Proceso"
        assert len(h["comments"]) == 2

    def test_error_si_falta_parametro_sf_record_id(self, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)

        evento = {**EVENT_BASE, "parameters": []}
        resultado = handler_module.lambda_handler(evento, {})
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])

        assert "error" in body

    def test_error_si_faltan_env_vars(self, monkeypatch):
        monkeypatch.delenv("SSM_SF_COOKIES_PATH", raising=False)

        resultado = handler_module.lambda_handler(EVENT_BASE, {})
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])

        assert "error" in body

    @patch("src.tools.review_historial_crm.infrastructure.salesforce_case_scraper.SalesforceCaseScraper")
    def test_error_propagado_desde_scraper(self, mock_scraper_cls, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)
        mock_scraper_cls.return_value.obtener_historial.side_effect = RuntimeError("SSM no disponible")

        resultado = handler_module.lambda_handler(EVENT_BASE, {})
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])

        assert "error" in body
        assert "SSM no disponible" in body["error"]


class TestSalesforceCaseScraperExtraccion:
    """
    Tests unitarios de los métodos de extracción del scraper.
    No requieren Playwright — testean la lógica de parsing con mocks de Page.
    """

    def _make_scraper(self) -> SalesforceCaseScraper:
        """Crea scraper sin inicializar SSM (para tests de extracción)."""
        scraper = SalesforceCaseScraper.__new__(SalesforceCaseScraper)
        scraper._session = MagicMock()
        return scraper

    # ------------------------------------------------------------------
    # _extraer_campos
    # ------------------------------------------------------------------

    def test_extraer_campos_identifica_case_number_numerico(self):
        scraper = self._make_scraper()
        page = MagicMock()

        h1 = MagicMock()
        h1.inner_text.return_value = "00001234"
        page.query_selector_all.side_effect = lambda sel: [h1] if sel == "h1" else []

        campos = scraper._extraer_campos(page)
        assert campos["case_number"] == "00001234"

    def test_extraer_campos_identifica_status_en_layout(self):
        scraper = self._make_scraper()
        page = MagicMock()
        page.query_selector_all.side_effect = lambda sel: (
            [] if sel == "h1" else [_make_layout_item("Status", "En Proceso")]
        )

        campos = scraper._extraer_campos(page)
        assert campos["status"] == "En Proceso"

    def test_extraer_campos_identifica_subject(self):
        scraper = self._make_scraper()
        page = MagicMock()
        page.query_selector_all.side_effect = lambda sel: (
            [] if sel == "h1" else [_make_layout_item("Subject", "Accidente placa 422644")]
        )

        campos = scraper._extraer_campos(page)
        assert campos["subject"] == "Accidente placa 422644"

    def test_extraer_campos_retorna_vacios_si_sin_contenido(self):
        scraper = self._make_scraper()
        page = MagicMock()
        page.query_selector_all.return_value = []

        campos = scraper._extraer_campos(page)
        assert campos == {
            "case_number": "",
            "status": "",
            "subject": "",
            "account_name": "",
            "created_date": "",
        }

    # ------------------------------------------------------------------
    # _extraer_comentarios
    # ------------------------------------------------------------------

    def test_extraer_comentarios_retorna_vacio_sin_timeline(self):
        scraper = self._make_scraper()
        page = MagicMock()
        page.query_selector_all.return_value = []

        comentarios = scraper._extraer_comentarios(page)
        assert comentarios == []

    def test_extraer_comentarios_parsea_items_con_texto(self):
        scraper = self._make_scraper()

        item = _make_timeline_item(fecha="2026-04-05", autor="Ana Lopez", texto="Documentacion recibida.")
        page = MagicMock()
        page.query_selector_all.return_value = [item]

        comentarios = scraper._extraer_comentarios(page)
        assert len(comentarios) == 1
        assert comentarios[0]["texto"] == "Documentacion recibida."

    def test_extraer_comentarios_limita_a_max_comments(self):
        scraper = self._make_scraper()

        items = [
            _make_timeline_item("2026-04-05", "Ana", f"Comentario {i}.")
            for i in range(25)
        ]
        page = MagicMock()
        page.query_selector_all.return_value = items

        comentarios = scraper._extraer_comentarios(page)
        assert len(comentarios) <= 10

    # ------------------------------------------------------------------
    # _parsear_item_timeline
    # ------------------------------------------------------------------

    def test_parsear_item_retorna_none_si_texto_muy_corto(self):
        scraper = self._make_scraper()
        item = _make_timeline_item("2026-04-05", "Ana", "ok")  # < 5 chars

        result = scraper._parsear_item_timeline(item)
        assert result is None

    def test_parsear_item_retorna_dict_con_campos(self):
        scraper = self._make_scraper()
        item = _make_timeline_item("2026-04-05", "Ana Lopez", "Solicitud enviada al perito.")

        result = scraper._parsear_item_timeline(item)
        assert result is not None
        assert result["fecha"] == "2026-04-05"
        assert result["autor"] == "Ana Lopez"
        assert "Solicitud" in result["texto"]

    def test_parsear_item_trunca_texto_largo(self):
        scraper = self._make_scraper()
        texto_largo = "x" * 600
        item = _make_timeline_item("2026-04-05", "Ana", texto_largo)

        result = scraper._parsear_item_timeline(item)
        assert result is not None
        assert len(result["texto"]) <= 500


# ------------------------------------------------------------------
# Factories de mocks de Playwright para tests de extracción
# ------------------------------------------------------------------

def _make_layout_item(label_text: str, value_text: str):
    """Crea un mock de records-record-layout-item con label y value."""
    item = MagicMock()
    label = MagicMock()
    label.inner_text.return_value = label_text
    value = MagicMock()
    value.inner_text.return_value = value_text

    def query_selector_for_item(sel):
        if "label" in sel:
            return label
        return value

    item.query_selector.side_effect = query_selector_for_item
    return item


def _make_timeline_item(fecha: str, autor: str, texto: str):
    """Crea un mock de timeline item con fecha, autor y texto.

    _parsear_item_timeline llama query_selector 3 veces en este orden:
      1) fecha  (abbr[title], time, ...)
      2) autor  (.slds-timeline__trigger ...)
      3) texto  (.slds-timeline__item-detail p, ...)
    Se usa call_count para evitar falsos positivos por substrings (ej.
    ".slds-timeline__trigger" contiene "time").
    """
    item = MagicMock()

    fecha_el = MagicMock()
    fecha_el.get_attribute.return_value = fecha
    fecha_el.inner_text.return_value = fecha

    autor_el = MagicMock()
    autor_el.inner_text.return_value = autor

    texto_el = MagicMock()
    texto_el.inner_text.return_value = texto

    # item.inner_text fallback
    item.inner_text.return_value = texto

    _calls = [fecha_el, autor_el, texto_el]
    _idx = [0]

    def _dispatch(_sel):
        el = _calls[min(_idx[0], len(_calls) - 1)]
        _idx[0] += 1
        return el

    item.query_selector.side_effect = _dispatch
    return item


class TestHelpers:
    def test_limpiar_normaliza_espacios(self):
        assert _limpiar("  hola   mundo  ") == "hola mundo"

    def test_limpiar_string_vacio(self):
        assert _limpiar("") == ""

    def test_limpiar_none(self):
        assert _limpiar(None) == ""

    def test_limpiar_tabs_y_newlines(self):
        assert _limpiar("hola\n\tmundo") == "hola mundo"
