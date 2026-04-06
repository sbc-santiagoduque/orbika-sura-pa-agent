import json
import pytest
from unittest.mock import MagicMock, patch

import src.tools.validate_documentos.lambda_function as handler_module

EVENT_BASE = {
    "actionGroup": "agente-expediente-actions",
    "function": "validate_documentos",
    "parameters": [
        {
            "name": "expediente",
            "type": "string",
            "value": json.dumps({
                "expediente_url": "https://sic.connectasistencia.com/claims/abc/view",
                "imagen_count": 31,
                "imagen_urls": ["https://inspeccionespty.s3.us-east-2.amazonaws.com/5105397/1.jpg"],
                "imagen_urls_signed": ["https://inspeccionespty.s3.us-east-2.amazonaws.com/5105397/1.jpg?X-Amz-Expires=604800"],
                "tiene_documentos": True,
            }),
        }
    ],
}

EVENT_SIN_DOCS = {
    **EVENT_BASE,
    "parameters": [
        {
            "name": "expediente",
            "type": "string",
            "value": json.dumps({
                "expediente_url": "https://sic.connectasistencia.com/claims/abc/view",
                "imagen_count": 0,
                "imagen_urls": [],
                "imagen_urls_signed": [],
                "tiene_documentos": False,
            }),
        }
    ],
}

ENV_A = {"VALIDATE_DOCS_STRATEGY": "A"}
ENV_B = {"VALIDATE_DOCS_STRATEGY": "B", "BEDROCK_MODEL_ID": "amazon.nova-lite-v1:0"}


class TestValidateDocumentosStrategyA:
    def test_retorna_documentos_presentes_cuando_hay_imagenes(self, monkeypatch):
        for k, v in ENV_A.items():
            monkeypatch.setenv(k, v)

        resultado = handler_module.lambda_handler(EVENT_BASE, {})

        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])
        assert body["validacion"]["resultado"] == "documentos_presentes"
        assert body["validacion"]["estrategia"] == "A"
        assert body["validacion"]["imagen_count"] == 31

    def test_retorna_sin_documentos_cuando_imagen_count_es_0(self, monkeypatch):
        for k, v in ENV_A.items():
            monkeypatch.setenv(k, v)

        resultado = handler_module.lambda_handler(EVENT_SIN_DOCS, {})

        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])
        assert body["validacion"]["resultado"] == "sin_documentos"
        assert body["validacion"]["imagen_count"] == 0

    def test_usa_estrategia_A_por_defecto(self, monkeypatch):
        monkeypatch.delenv("VALIDATE_DOCS_STRATEGY", raising=False)

        resultado = handler_module.lambda_handler(EVENT_BASE, {})

        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])
        assert body["validacion"]["estrategia"] == "A"

    def test_retorna_formato_bedrock_action_group(self, monkeypatch):
        for k, v in ENV_A.items():
            monkeypatch.setenv(k, v)

        resultado = handler_module.lambda_handler(EVENT_BASE, {})

        assert resultado["actionGroup"] == "agente-expediente-actions"
        assert resultado["function"] == "validate_documentos"
        assert "functionResponse" in resultado


class TestValidateDocumentosStrategyB:
    def test_error_si_estrategia_B_sin_bedrock_model_id(self, monkeypatch):
        monkeypatch.setenv("VALIDATE_DOCS_STRATEGY", "B")
        monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)

        resultado = handler_module.lambda_handler(EVENT_BASE, {})

        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])
        assert "error" in body

    def test_estrategia_B_invoca_validator_con_model_id(self, monkeypatch):
        for k, v in ENV_B.items():
            monkeypatch.setenv(k, v)

        mock_validator = MagicMock()
        mock_validator.validar.return_value = {
            "resultado": "documentos_presentes",
            "estrategia": "B",
            "imagen_count": 31,
            "detalle": "Documentos clasificados por vision",
        }

        with patch(
            "src.tools.validate_documentos.service.opcion_b_validator.OpcionBValidator",
            return_value=mock_validator,
        ):
            resultado = handler_module.lambda_handler(EVENT_BASE, {})

        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])
        assert body["validacion"]["estrategia"] == "B"
        mock_validator.validar.assert_called_once()


class TestValidateDocumentosErrores:
    def test_error_si_falta_parametro_expediente(self, monkeypatch):
        for k, v in ENV_A.items():
            monkeypatch.setenv(k, v)

        evento_sin_expediente = {**EVENT_BASE, "parameters": []}
        resultado = handler_module.lambda_handler(evento_sin_expediente, {})

        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])
        assert "error" in body

    def test_error_si_expediente_no_es_json_valido(self, monkeypatch):
        for k, v in ENV_A.items():
            monkeypatch.setenv(k, v)

        evento_invalido = {
            **EVENT_BASE,
            "parameters": [{"name": "expediente", "type": "string", "value": "no-es-json"}],
        }
        resultado = handler_module.lambda_handler(evento_invalido, {})

        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])
        assert "error" in body
