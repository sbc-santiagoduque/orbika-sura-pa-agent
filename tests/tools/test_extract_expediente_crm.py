import json
import pytest
from unittest.mock import MagicMock, patch

import src.tools.extract_expediente_crm.lambda_function as handler_module
from src.tools.extract_expediente_crm.infrastructure.salesforce_attachments_scraper import (
    SalesforceAttachmentsScraper,
    _normalizar_tipo,
    _limpiar,
)

EVENT_BASE = {
    "actionGroup": "agente-expediente-actions",
    "function": "extract_expediente_crm",
    "parameters": [
        {"name": "sf_record_id", "type": "string", "value": "500VY00000YWjzMYAT"}
    ],
}

ENV_VARS = {
    "SSM_SF_COOKIES_PATH": "/agente-analista/salesforce/cookies",
}

DOCUMENTOS_MOCK = {
    "sf_record_id": "500VY00000YWjzMYAT",
    "imagen_count": 3,
    "documentos": [
        {
            "title": "Finiquito",
            "content_document_id": "069VY00000eY8CHYA0",
            "file_type": "pdf",
            "last_modified": "04/14/2026 12:50 PM",
            "created_by": "Valentina Castrillón",
            "size": "67 KB",
        },
        {
            "title": "CUADRO PT CF0975",
            "content_document_id": "069VY00000dUYllYAG",
            "file_type": "pdf",
            "last_modified": "04/01/2026 11:57 PM",
            "created_by": "Jorge Urriola",
            "size": "406 KB",
        },
        {
            "title": "CL",
            "content_document_id": "069VY00000dUUS3YAO",
            "file_type": "image",
            "last_modified": "04/01/2026 11:47 PM",
            "created_by": "Jorge Urriola",
            "size": "58 KB",
        },
    ],
}


class TestExtractExpedienteCrmHandler:
    @patch(
        "src.tools.extract_expediente_crm.infrastructure.salesforce_attachments_scraper.SalesforceAttachmentsScraper"
    )
    def test_retorna_formato_bedrock_action_group(self, mock_scraper_cls, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)
        mock_scraper_cls.return_value.obtener_documentos.return_value = DOCUMENTOS_MOCK

        resultado = handler_module.lambda_handler(EVENT_BASE, {})

        assert resultado["actionGroup"] == "agente-expediente-actions"
        assert resultado["function"] == "extract_expediente_crm"
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])
        assert "expediente" in body

    @patch(
        "src.tools.extract_expediente_crm.infrastructure.salesforce_attachments_scraper.SalesforceAttachmentsScraper"
    )
    def test_retorna_imagen_count_y_documentos(self, mock_scraper_cls, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)
        mock_scraper_cls.return_value.obtener_documentos.return_value = DOCUMENTOS_MOCK

        resultado = handler_module.lambda_handler(EVENT_BASE, {})
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])

        exp = body["expediente"]
        assert exp["imagen_count"] == 3
        assert len(exp["documentos"]) == 3

    @patch(
        "src.tools.extract_expediente_crm.infrastructure.salesforce_attachments_scraper.SalesforceAttachmentsScraper"
    )
    def test_sin_documentos_imagen_count_cero(self, mock_scraper_cls, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)
        mock_scraper_cls.return_value.obtener_documentos.return_value = {
            "sf_record_id": "500VY00000YWjzMYAT",
            "imagen_count": 0,
            "documentos": [],
        }

        resultado = handler_module.lambda_handler(EVENT_BASE, {})
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])

        assert body["expediente"]["imagen_count"] == 0
        assert body["expediente"]["documentos"] == []

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

    @patch(
        "src.tools.extract_expediente_crm.infrastructure.salesforce_attachments_scraper.SalesforceAttachmentsScraper"
    )
    def test_error_propagado_desde_scraper(self, mock_scraper_cls, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)
        mock_scraper_cls.return_value.obtener_documentos.side_effect = RuntimeError(
            "SSM no disponible"
        )

        resultado = handler_module.lambda_handler(EVENT_BASE, {})
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])

        assert "error" in body
        assert "SSM no disponible" in body["error"]


class TestSalesforceAttachmentsScraperParseo:
    """
    Tests unitarios de los métodos de parsing del scraper.
    No requieren Playwright — usan mocks de elementos del DOM.
    """

    def _make_scraper(self) -> SalesforceAttachmentsScraper:
        scraper = SalesforceAttachmentsScraper.__new__(SalesforceAttachmentsScraper)
        scraper._session = MagicMock()
        return scraper

    # ------------------------------------------------------------------
    # _parsear_fila — happy path
    # ------------------------------------------------------------------

    def test_parsear_fila_extrae_todos_los_campos(self):
        scraper = self._make_scraper()
        row = _make_row(
            content_document_id="069VY00000eY8CHYA0",
            title="Finiquito",
            file_type_raw="Adobe PDF",
            last_modified="04/14/2026 12:50 PM",
            created_by="Valentina Castrillón",
            size_num="67",
            size_unit="KB",
        )

        result = scraper._parsear_fila(row)

        assert result is not None
        assert result["content_document_id"] == "069VY00000eY8CHYA0"
        assert result["title"] == "Finiquito"
        assert result["file_type"] == "pdf"
        assert result["last_modified"] == "04/14/2026 12:50 PM"
        assert result["created_by"] == "Valentina Castrillón"
        assert result["size"] == "67 KB"

    def test_parsear_fila_imagen_retorna_file_type_image(self):
        scraper = self._make_scraper()
        row = _make_row(
            content_document_id="069VY00000dUUS3YAO",
            title="CL",
            file_type_raw="Image file",
            last_modified="04/01/2026 11:47 PM",
            created_by="Jorge Urriola",
            size_num="58",
            size_unit="KB",
        )

        result = scraper._parsear_fila(row)

        assert result is not None
        assert result["file_type"] == "image"

    def test_parsear_fila_retorna_none_sin_link_de_titulo(self):
        scraper = self._make_scraper()
        row = MagicMock()
        row.query_selector.return_value = None

        result = scraper._parsear_fila(row)

        assert result is None

    def test_parsear_fila_retorna_none_si_href_no_tiene_content_document(self):
        scraper = self._make_scraper()
        row = MagicMock()
        link = MagicMock()
        link.get_attribute.return_value = "/lightning/r/Case/500abc/view"  # no ContentDocument
        link.query_selector.return_value = None
        row.query_selector.return_value = link

        result = scraper._parsear_fila(row)

        assert result is None

    def test_parsear_fila_size_vacio_si_faltan_elementos(self):
        scraper = self._make_scraper()
        row = _make_row(
            content_document_id="069VY00000eY8CHYA0",
            title="Finiquito",
            file_type_raw="Adobe PDF",
            last_modified="04/14/2026 12:50 PM",
            created_by="Valentina Castrillón",
            size_num=None,
            size_unit=None,
        )

        result = scraper._parsear_fila(row)

        assert result is not None
        assert result["size"] == ""

    def test_parsear_fila_created_by_fallback_a_inner_text(self):
        scraper = self._make_scraper()
        row = _make_row(
            content_document_id="069VY00000eY8CHYA0",
            title="Finiquito",
            file_type_raw="Adobe PDF",
            last_modified="04/14/2026 12:50 PM",
            created_by="Valentina Castrillón",
            size_num="67",
            size_unit="KB",
            created_by_title_attr=None,  # sin atributo title → fallback a inner_text
        )

        result = scraper._parsear_fila(row)

        assert result is not None
        assert result["created_by"] == "Valentina Castrillón"

    # ------------------------------------------------------------------
    # _extraer_documentos
    # ------------------------------------------------------------------

    def test_extraer_documentos_retorna_lista_vacia_sin_filas(self):
        scraper = self._make_scraper()
        page = MagicMock()
        page.query_selector_all.return_value = []

        docs = scraper._extraer_documentos(page)

        assert docs == []

    def test_extraer_documentos_omite_filas_invalidas(self):
        scraper = self._make_scraper()
        page = MagicMock()

        row_valida = _make_row("069abc", "Doc válido", "Adobe PDF", "04/01/2026", "Ana", "100", "KB")
        row_invalida = MagicMock()
        row_invalida.query_selector.return_value = None  # sin link → parsear_fila retorna None

        page.query_selector_all.return_value = [row_valida, row_invalida]

        docs = scraper._extraer_documentos(page)

        assert len(docs) == 1
        assert docs[0]["title"] == "Doc válido"

    def test_extraer_documentos_retorna_todos_los_validos(self):
        scraper = self._make_scraper()
        page = MagicMock()

        filas = [
            _make_row(f"069abc{i}", f"Doc {i}", "Adobe PDF", "04/01/2026", "Ana", "100", "KB")
            for i in range(5)
        ]
        page.query_selector_all.return_value = filas

        docs = scraper._extraer_documentos(page)

        assert len(docs) == 5

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
        page.query_selector.return_value = None  # nunca encuentra

        with caplog.at_level(logging.WARNING):
            scraper._esperar_tabla_cargada(page)

        assert any("tabla" in m.lower() or "attachment" in m.lower() for m in [r.message for r in caplog.records])


class TestNormalizarTipo:
    def test_pdf_reconocido(self):
        assert _normalizar_tipo("Adobe PDF") == "pdf"

    def test_image_file_reconocido(self):
        assert _normalizar_tipo("Image file") == "image"

    def test_word_reconocido(self):
        assert _normalizar_tipo("Microsoft Word Document") == "word"

    def test_excel_reconocido(self):
        assert _normalizar_tipo("Microsoft Excel Spreadsheet") == "excel"

    def test_csv_como_excel(self):
        assert _normalizar_tipo("CSV file") == "excel"

    def test_desconocido_retorna_unknown(self):
        assert _normalizar_tipo("Zip Archive") == "unknown"

    def test_string_vacio_retorna_unknown(self):
        assert _normalizar_tipo("") == "unknown"

    def test_case_insensitive(self):
        assert _normalizar_tipo("adobe pdf") == "pdf"
        assert _normalizar_tipo("IMAGE FILE") == "image"


class TestLimpiar:
    def test_normaliza_espacios_multiples(self):
        assert _limpiar("  hola   mundo  ") == "hola mundo"

    def test_string_vacio(self):
        assert _limpiar("") == ""

    def test_none(self):
        assert _limpiar(None) == ""

    def test_tabs_y_newlines(self):
        assert _limpiar("hola\n\tmundo") == "hola mundo"


# ------------------------------------------------------------------
# Factories de mocks de Playwright para tests de parseo
# ------------------------------------------------------------------

def _make_row(
    content_document_id: str,
    title: str,
    file_type_raw: str,
    last_modified: str,
    created_by: str,
    size_num: str | None,
    size_unit: str | None,
    created_by_title_attr: str | None = "USE_NAME",  # sentinel
) -> MagicMock:
    """
    Crea un mock de una fila <tr> de la tabla de attachments de Salesforce.

    Estructura que simula:
      th[scope='row'] a.forceContentCompoundFieldsTitleRenderer
        span.slds-assistive-text  → file_type_raw
        span.itemTitle[title]     → title
      td span.uiOutputDateTime    → last_modified
      td a.forceOutputLookup      → created_by
      .fileSizeAmount             → size_num
      .fileSizeUnits              → size_unit
    """
    row = MagicMock()

    # title_link (th > a)
    title_link = MagicMock()
    title_link.get_attribute.side_effect = lambda attr: (
        f"/lightning/r/ContentDocument/{content_document_id}/view" if attr == "href" else None
    )

    # span.itemTitle dentro del link
    title_span = MagicMock()
    title_span.get_attribute.side_effect = lambda attr: title if attr == "title" else None
    title_span.inner_text.return_value = title

    # span.slds-assistive-text dentro del link
    type_span = MagicMock()
    type_span.inner_text.return_value = file_type_raw

    def title_link_query(sel):
        if "itemTitle" in sel:
            return title_span
        if "assistive-text" in sel:
            return type_span
        return None

    title_link.query_selector.side_effect = title_link_query

    # span.uiOutputDateTime (td)
    last_mod_span = MagicMock()
    last_mod_span.inner_text.return_value = last_modified

    # a.forceOutputLookup (td)
    created_by_link = MagicMock()
    # Simula title attribute o inner_text
    resolved_title = created_by if created_by_title_attr == "USE_NAME" else created_by_title_attr
    created_by_link.get_attribute.side_effect = lambda attr: (
        resolved_title if attr == "title" else None
    )
    created_by_link.inner_text.return_value = created_by

    # .fileSizeAmount y .fileSizeUnits
    size_num_el = MagicMock() if size_num is not None else None
    if size_num_el:
        size_num_el.inner_text.return_value = size_num

    size_unit_el = MagicMock() if size_unit is not None else None
    if size_unit_el:
        size_unit_el.inner_text.return_value = size_unit

    def row_query(sel):
        if "th[scope='row'] a" in sel:
            return title_link
        if "uiOutputDateTime" in sel:
            return last_mod_span
        if "forceOutputLookup" in sel:
            return created_by_link
        if "fileSizeAmount" in sel:
            return size_num_el
        if "fileSizeUnits" in sel:
            return size_unit_el
        return None

    row.query_selector.side_effect = row_query
    return row
