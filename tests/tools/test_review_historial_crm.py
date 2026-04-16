import json
import pytest
from unittest.mock import MagicMock, patch

import src.tools.review_historial_crm.lambda_function as handler_module
from src.tools.review_historial_crm.infrastructure.salesforce_case_scraper import (
    SalesforceCaseScraper,
    _limpiar,
    _limpiar_texto,
)

EVENT_BASE = {
    "actionGroup": "agente-crm-actions",
    "function": "review_historial_crm",
    "parameters": [
        {"name": "case_number", "type": "string", "value": "CF0975"}
    ],
}

ENV_VARS = {
    "SSM_SF_COOKIES_PATH": "/agente-analista/salesforce/cookies",
}

HISTORIAL_MOCK = {
    "sf_record_id": "500SF000001ABCDE",
    "case_number": "CF0975",
    "comments": [
        {
            "autor": "Carlos Gaona",
            "fecha": "04/15/2026 09:28 AM",
            "texto": "Se procede con la validación con Joel.",
            "es_publico": False,
        },
        {
            "autor": "Marjorie Morales",
            "fecha": "04/14/2026 12:06 PM",
            "texto": "El caso sale como Pt con acreedor.",
            "es_publico": False,
        },
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
        assert h["case_number"] == "CF0975"
        assert len(h["comments"]) == 2

    def test_error_si_falta_parametro_case_number(self, monkeypatch):
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


class TestSalesforceCaseScraperParseo:
    """
    Tests unitarios de los métodos de parsing del scraper.
    No requieren Playwright — usan mocks de elementos del DOM.
    """

    def _make_scraper(self) -> SalesforceCaseScraper:
        scraper = SalesforceCaseScraper.__new__(SalesforceCaseScraper)
        scraper._session = MagicMock()
        return scraper

    # ------------------------------------------------------------------
    # _parsear_fila — happy path
    # ------------------------------------------------------------------

    def test_parsear_fila_extrae_todos_los_campos(self):
        scraper = self._make_scraper()
        row = _make_row(
            autor="Carlos Gaona",
            fecha="04/15/2026 09:28 AM",
            texto="Se procede con la validación con Joel.",
            es_publico=False,
        )

        result = scraper._parsear_fila(row)

        assert result is not None
        assert result["autor"] == "Carlos Gaona"
        assert result["fecha"] == "04/15/2026 09:28 AM"
        assert result["texto"] == "Se procede con la validación con Joel."
        assert result["es_publico"] is False

    def test_parsear_fila_es_publico_true(self):
        scraper = self._make_scraper()
        row = _make_row("Kelly Barría", "04/11/2026 09:25 AM", "ADJUNTO ACH.", es_publico=True)

        result = scraper._parsear_fila(row)

        assert result is not None
        assert result["es_publico"] is True

    def test_parsear_fila_es_publico_false(self):
        scraper = self._make_scraper()
        row = _make_row("Jorge Urriola", "04/01/2026 11:37 PM", "Perdida total.", es_publico=False)

        result = scraper._parsear_fila(row)

        assert result is not None
        assert result["es_publico"] is False

    def test_parsear_fila_retorna_none_sin_user_link(self):
        scraper = self._make_scraper()
        row = MagicMock()
        row.query_selector.return_value = None

        result = scraper._parsear_fila(row)

        assert result is None

    def test_parsear_fila_retorna_none_si_texto_vacio(self):
        scraper = self._make_scraper()
        row = _make_row("Ana Lopez", "04/01/2026", "", es_publico=False)

        result = scraper._parsear_fila(row)

        assert result is None

    def test_parsear_fila_usa_inner_text_si_title_attr_es_none(self):
        scraper = self._make_scraper()
        # title attr None → fallback a inner_text del link
        row = _make_row(
            autor="Kelly Barría",
            fecha="04/11/2026 09:25 AM",
            texto="Texto del comentario.",
            es_publico=False,
            autor_title_attr=None,
        )

        result = scraper._parsear_fila(row)

        assert result is not None
        assert result["autor"] == "Kelly Barría"

    def test_parsear_fila_texto_largo_truncado_a_2000(self):
        scraper = self._make_scraper()
        texto_largo = "x" * 3000
        row = _make_row("Ana", "04/01/2026", texto_largo, es_publico=False)

        result = scraper._parsear_fila(row)

        assert result is not None
        assert len(result["texto"]) <= 2000

    def test_parsear_fila_retorna_none_si_excepcion_interna(self):
        scraper = self._make_scraper()
        row = MagicMock()
        row.query_selector.side_effect = RuntimeError("Error inesperado de Playwright")

        result = scraper._parsear_fila(row)

        assert result is None

    def test_parsear_fila_fecha_vacia_si_no_hay_elemento(self):
        scraper = self._make_scraper()
        row = _make_row("Ana", "", "Comentario válido.", es_publico=False, sin_fecha=True)

        result = scraper._parsear_fila(row)

        assert result is not None
        assert result["fecha"] == ""

    # ------------------------------------------------------------------
    # _extraer_comentarios
    # ------------------------------------------------------------------

    def test_extraer_comentarios_retorna_vacio_sin_filas(self):
        scraper = self._make_scraper()
        page = MagicMock()
        page.query_selector_all.return_value = []

        comentarios = scraper._extraer_comentarios(page)

        assert comentarios == []

    def test_extraer_comentarios_omite_filas_invalidas(self):
        scraper = self._make_scraper()
        page = MagicMock()

        row_valida = _make_row("Carlos Gaona", "04/15/2026 09:28 AM", "Comentario válido.", False)
        row_invalida = MagicMock()
        row_invalida.query_selector.return_value = None  # sin user_link → None

        page.query_selector_all.return_value = [row_valida, row_invalida]

        comentarios = scraper._extraer_comentarios(page)

        assert len(comentarios) == 1
        assert comentarios[0]["autor"] == "Carlos Gaona"

    def test_extraer_comentarios_limita_a_max_comments(self):
        scraper = self._make_scraper()
        page = MagicMock()

        filas = [
            _make_row("Ana", f"04/0{i}/2026", f"Comentario {i}.", False)
            for i in range(1, 20)
        ]
        page.query_selector_all.return_value = filas

        comentarios = scraper._extraer_comentarios(page)

        assert len(comentarios) <= 10

    def test_extraer_comentarios_retorna_todos_si_menos_de_max(self):
        scraper = self._make_scraper()
        page = MagicMock()

        filas = [
            _make_row("Ana", f"04/0{i}/2026", f"Comentario {i}.", False)
            for i in range(1, 4)
        ]
        page.query_selector_all.return_value = filas

        comentarios = scraper._extraer_comentarios(page)

        assert len(comentarios) == 3

    # ------------------------------------------------------------------
    # _esperar_tabla_cargada
    # ------------------------------------------------------------------

    def test_esperar_tabla_retorna_inmediatamente_si_encuentra_thead(self):
        scraper = self._make_scraper()
        page = MagicMock()
        page.query_selector.return_value = MagicMock()  # thead encontrado

        scraper._esperar_tabla_cargada(page)

        assert page.wait_for_timeout.call_count == 1

    def test_esperar_tabla_emite_warning_si_no_encuentra_thead(self, caplog):
        import logging
        scraper = self._make_scraper()
        page = MagicMock()
        page.query_selector.return_value = None

        with caplog.at_level(logging.WARNING):
            scraper._esperar_tabla_cargada(page)

        assert any(
            "tabla" in m.lower() or "comment" in m.lower()
            for m in [r.message for r in caplog.records]
        )

    # ------------------------------------------------------------------
    # _esperar_filas
    # ------------------------------------------------------------------

    def test_esperar_filas_retorna_filas_cuando_aparecen(self):
        scraper = self._make_scraper()
        page = MagicMock()
        fila = MagicMock()
        page.query_selector_all.side_effect = [[], [fila, fila]]  # vacío primero, luego 2 filas

        rows = scraper._esperar_filas(page)

        assert len(rows) == 2

    def test_esperar_filas_retorna_vacio_si_nunca_aparecen(self):
        scraper = self._make_scraper()
        page = MagicMock()
        page.query_selector_all.return_value = []

        rows = scraper._esperar_filas(page)

        assert rows == []


# ------------------------------------------------------------------
# Factory de mocks de Playwright para tests de parseo
# ------------------------------------------------------------------

def _make_row(
    autor: str,
    fecha: str,
    texto: str,
    es_publico: bool,
    autor_title_attr: str | None = "USE_NAME",  # sentinel → usa el nombre
    sin_fecha: bool = False,
) -> MagicMock:
    """
    Crea un mock de una fila <tr> de la tabla CaseComments de Salesforce.

    Estructura simulada (validada contra HTML real 2026-04-15):
      th[scope='row'] a.forceOutputLookup  → autor (title attr)
      span.uiOutputCheckbox img            → es_publico (aria-checked)
      span.uiOutputDateTime                → fecha (inner_text)
      span.forceListViewManagerGridWrapText → texto (inner_text)
    """
    row = MagicMock()

    # User link (th > a.forceOutputLookup)
    user_link = MagicMock()
    resolved_title = autor if autor_title_attr == "USE_NAME" else autor_title_attr
    user_link.get_attribute.side_effect = lambda attr: (
        resolved_title if attr == "title" else None
    )
    user_link.inner_text.return_value = autor

    # Public checkbox img (span.uiOutputCheckbox img)
    public_img = MagicMock()
    public_img.get_attribute.side_effect = lambda attr: (
        "true" if (attr == "aria-checked" and es_publico)
        else ("false" if attr == "aria-checked" else None)
    )

    # Created Date (span.uiOutputDateTime)
    fecha_el = MagicMock() if not sin_fecha else None
    if fecha_el:
        fecha_el.inner_text.return_value = fecha

    # Comment text (span.forceListViewManagerGridWrapText)
    texto_el = MagicMock()
    texto_el.inner_text.return_value = texto

    def row_query(sel):
        if "forceOutputLookup" in sel:
            return user_link
        if "uiOutputCheckbox" in sel:
            return public_img
        if "uiOutputDateTime" in sel:
            return fecha_el
        if "forceListViewManagerGridWrapText" in sel:
            return texto_el
        return None

    row.query_selector.side_effect = row_query
    return row


# ------------------------------------------------------------------
# TestLimpiar / TestLimpiarTexto
# ------------------------------------------------------------------

class TestLimpiar:
    def test_normaliza_espacios_multiples(self):
        assert _limpiar("  hola   mundo  ") == "hola mundo"

    def test_string_vacio(self):
        assert _limpiar("") == ""

    def test_none(self):
        assert _limpiar(None) == ""

    def test_tabs_y_newlines(self):
        assert _limpiar("hola\n\tmundo") == "hola mundo"


class TestLimpiarTexto:
    def test_preserva_newlines_simples(self):
        texto = "linea uno\nlinea dos"
        assert _limpiar_texto(texto) == "linea uno\nlinea dos"

    def test_colapsa_tres_o_mas_newlines(self):
        texto = "linea uno\n\n\n\nlinea dos"
        assert _limpiar_texto(texto) == "linea uno\n\nlinea dos"

    def test_normaliza_espacios_dentro_de_linea(self):
        texto = "hola   mundo\nnueva   linea"
        assert _limpiar_texto(texto) == "hola mundo\nnueva linea"

    def test_strip_leading_trailing(self):
        assert _limpiar_texto("  texto  ") == "texto"

    def test_string_vacio(self):
        assert _limpiar_texto("") == ""

    def test_none(self):
        assert _limpiar_texto(None) == ""

    def test_preserva_doble_newline(self):
        texto = "parte uno\n\nparte dos"
        assert _limpiar_texto(texto) == "parte uno\n\nparte dos"
