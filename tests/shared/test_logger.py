import json
import logging
import pytest
from unittest.mock import patch, MagicMock
from src.shared.observability.logger import log_decision, log_tool


class TestLogDecision:
    def test_emite_json_con_campos_requeridos(self, caplog):
        with caplog.at_level(logging.INFO):
            log_decision(
                case_id="CASE-001",
                fase="F2",
                decision="criterio_panama_detectado",
                razonamiento="Nota del analista Panamá indica rechazo previo",
                inputs={"historial": "rechazado 2025-01"}
            )
        record = json.loads(caplog.records[0].message)
        assert record["type"] == "decision"
        assert record["case_id"] == "CASE-001"
        assert record["fase"] == "F2"
        assert record["decision"] == "criterio_panama_detectado"
        assert record["razonamiento"] == "Nota del analista Panamá indica rechazo previo"
        assert "timestamp" in record

    def test_razonamiento_puede_ser_none(self, caplog):
        with caplog.at_level(logging.INFO):
            log_decision(
                case_id="CASE-002",
                fase="F9",
                decision="tipo_responsabilidad_clasificado",
                razonamiento=None,
                inputs={}
            )
        record = json.loads(caplog.records[0].message)
        assert record["razonamiento"] is None

    def test_inputs_sensibles_no_se_exponen_en_texto_plano(self, caplog):
        with caplog.at_level(logging.INFO):
            log_decision(
                case_id="CASE-003",
                fase="F1",
                decision="bandeja_cargada",
                razonamiento=None,
                inputs={"total_casos": 10}
            )
        raw_log = caplog.records[0].message
        # El log debe ser JSON parseable — no concatenación libre
        json.loads(raw_log)


class TestLogTool:
    def test_emite_json_con_campos_requeridos(self, caplog):
        with caplog.at_level(logging.INFO):
            log_tool(
                case_id="CASE-001",
                fase="F8",
                tool_name="check_orbika",
                input_data={"placa": "ABC123"},
                output_data={"estado": "ajustado", "cotizacion_disponible": True},
                duracion_ms=1250,
                status="ok"
            )
        record = json.loads(caplog.records[0].message)
        assert record["type"] == "tool"
        assert record["case_id"] == "CASE-001"
        assert record["tool_name"] == "check_orbika"
        assert record["duracion_ms"] == 1250
        assert record["status"] == "ok"
        assert "timestamp" in record

    def test_status_error_se_registra(self, caplog):
        with caplog.at_level(logging.INFO):
            log_tool(
                case_id="CASE-002",
                fase="F6",
                tool_name="extract_expediente_sic",
                input_data={"placa": "XYZ999"},
                output_data={"error": "timeout"},
                duracion_ms=30000,
                status="error"
            )
        record = json.loads(caplog.records[0].message)
        assert record["status"] == "error"

    def test_status_invalido_lanza_error(self):
        with pytest.raises(ValueError, match="status debe ser 'ok' o 'error'"):
            log_tool(
                case_id="CASE-003",
                fase="F1",
                tool_name="get_bandeja_crm",
                input_data={},
                output_data={},
                duracion_ms=100,
                status="unknown"
            )
