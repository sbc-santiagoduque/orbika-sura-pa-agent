import json
import pytest
from unittest.mock import MagicMock, patch

import src.tools.extract_expediente_sic_api.lambda_function as handler_module
from src.tools.extract_expediente_sic_api.infrastructure.sic_api_client import (
    SICApiClient,
    _decode_user_id,
    _parsear_fecha,
)
from src.shared.sic_api.sic_api_session import SICApiSession

EVENT_BASE = {
    "actionGroup": "agente-expediente-actions",
    "function": "extract_expediente_sic_api",
    "parameters": [
        {"name": "placa", "type": "string", "value": "422644"}
    ],
}

ENV_VARS = {
    "SSM_SIC_API_USERNAME_PATH": "/agente-analista/sic/api/username",
    "SSM_SIC_API_PASSWORD_PATH": "/agente-analista/sic/api/password",
}

EXPEDIENTE_MOCK = {
    "placa": "422644",
    "evento_id": "5109574",
    "fecha_evento": "2023-06-23T10:00:00Z",
    "imagen_count": 3,
    "imagenes": [
        {"nombre": "doc1.jpg", "url": "https://s3.amazonaws.com/bucket/doc1.jpg", "seccion_id": 1},
        {"nombre": "doc2.jpg", "url": "https://s3.amazonaws.com/bucket/doc2.jpg", "seccion_id": 2},
        {"nombre": "doc3.jpg", "url": "https://s3.amazonaws.com/bucket/doc3.jpg", "seccion_id": 3},
    ],
}

EXPEDIENTE_VACIO = {
    "placa": "422644",
    "evento_id": None,
    "fecha_evento": None,
    "imagen_count": 0,
    "imagenes": [],
}


class TestExtractExpedienteSicApiHandler:
    @patch("src.tools.extract_expediente_sic_api.infrastructure.sic_api_client.SICApiClient")
    def test_retorna_formato_bedrock_action_group(self, mock_client_cls, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)
        mock_client_cls.return_value.obtener_expediente.return_value = EXPEDIENTE_MOCK

        resultado = handler_module.lambda_handler(EVENT_BASE, {})

        assert resultado["actionGroup"] == "agente-expediente-actions"
        assert resultado["function"] == "extract_expediente_sic_api"
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])
        assert "expediente" in body

    @patch("src.tools.extract_expediente_sic_api.infrastructure.sic_api_client.SICApiClient")
    def test_retorna_campos_correctos(self, mock_client_cls, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)
        mock_client_cls.return_value.obtener_expediente.return_value = EXPEDIENTE_MOCK

        resultado = handler_module.lambda_handler(EVENT_BASE, {})
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])

        exp = body["expediente"]
        assert exp["placa"] == "422644"
        assert exp["evento_id"] == "5109574"
        assert exp["imagen_count"] == 3
        assert len(exp["imagenes"]) == 3

    @patch("src.tools.extract_expediente_sic_api.infrastructure.sic_api_client.SICApiClient")
    def test_expediente_sin_eventos(self, mock_client_cls, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)
        mock_client_cls.return_value.obtener_expediente.return_value = EXPEDIENTE_VACIO

        resultado = handler_module.lambda_handler(EVENT_BASE, {})
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])

        exp = body["expediente"]
        assert exp["evento_id"] is None
        assert exp["imagen_count"] == 0
        assert exp["imagenes"] == []

    def test_error_si_falta_parametro_placa(self, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)

        evento = {**EVENT_BASE, "parameters": []}
        resultado = handler_module.lambda_handler(evento, {})
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])

        assert "error" in body

    def test_error_si_faltan_env_vars(self, monkeypatch):
        monkeypatch.delenv("SSM_SIC_API_USERNAME_PATH", raising=False)
        monkeypatch.delenv("SSM_SIC_API_PASSWORD_PATH", raising=False)

        resultado = handler_module.lambda_handler(EVENT_BASE, {})
        body = json.loads(resultado["functionResponse"]["responseBody"]["TEXT"]["body"])

        assert "error" in body


class TestSICApiClientObtenerExpediente:
    """
    Flujo real (descubierto 2026-04-07):
      POST /api/v1/users/auth      -> {data: {idToken, sub, ...}}
      GET  /api/v1/users/{sub}     -> {data: {userCompanyID, codPais, ...}}
      GET  /api/v2/events/search   -> {data: {response: {events: [...]}}}
      GET  /api/v1/images/PAN/all/{eventRecord} -> {data: [...]}
    """

    _AUTH_RESP = {
        "data": {
            "idToken": "header.eyJzdWIiOiAidXVpZC0xMjMifQ.sig",
            "sub": "uuid-123",
            "accessToken": "access-tok-for-bearer",
            "isAuthenticated": True,
        },
        "error": None,
        "success": True,
    }
    _USER_RESP = {
        "data": {
            "userCompanyID": 42,
            "codPais": "PAN",
            "rolId": 3,
            "companyId": 15,
        }
    }

    def _make_client(self, username="testuser", password="testpass") -> SICApiClient:
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.side_effect = [
            {"Parameter": {"Value": username}},
            {"Parameter": {"Value": password}},
        ]
        session = SICApiSession(
            ssm_username_path="/test/username",
            ssm_password_path="/test/password",
            ssm_client=mock_ssm,
        )
        return SICApiClient(session=session)

    def _mock_get(self, events, images_data):
        """Construye side_effect para requests.get: [user_resp, search_resp, images_resp?]"""
        user_resp = MagicMock()
        user_resp.raise_for_status = MagicMock()
        user_resp.json.return_value = self._USER_RESP

        search_resp = MagicMock()
        search_resp.raise_for_status = MagicMock()
        search_resp.json.return_value = {
            "data": {"response": {"events": events}}
        }

        side = [user_resp, search_resp]
        if images_data is not None:
            images_resp = MagicMock()
            images_resp.raise_for_status = MagicMock()
            images_resp.json.return_value = {"data": images_data}
            side.append(images_resp)
        return side

    @patch("src.tools.extract_expediente_sic_api.infrastructure.sic_api_client.requests.get")
    @patch("src.tools.extract_expediente_sic_api.infrastructure.sic_api_client.requests.post")
    def test_flujo_completo(self, mock_post, mock_get):
        client = self._make_client()

        mock_post.return_value.raise_for_status = MagicMock()
        mock_post.return_value.json.return_value = self._AUTH_RESP

        mock_get.side_effect = self._mock_get(
            events=[{"eventRecord": "5109574", "eventDate": "2023-06-23T10:00:00Z", "plate": "422644"}],
            images_data=[
                {"imageName": "doc1.jpg", "imageUrl": "https://s3.amazonaws.com/doc1.jpg", "imageSectionId": 1},
                {"imageName": "doc2.jpg", "imageUrl": "https://s3.amazonaws.com/doc2.jpg", "imageSectionId": 2},
            ],
        )

        expediente = client.obtener_expediente("422644")

        assert expediente["placa"] == "422644"
        assert expediente["evento_id"] == "5109574"
        assert expediente["imagen_count"] == 2
        assert len(expediente["imagenes"]) == 2
        assert expediente["imagenes"][0]["nombre"] == "doc1.jpg"

    @patch("src.tools.extract_expediente_sic_api.infrastructure.sic_api_client.requests.get")
    @patch("src.tools.extract_expediente_sic_api.infrastructure.sic_api_client.requests.post")
    def test_sin_eventos_retorna_vacio(self, mock_post, mock_get):
        client = self._make_client()

        mock_post.return_value.raise_for_status = MagicMock()
        mock_post.return_value.json.return_value = self._AUTH_RESP

        mock_get.side_effect = self._mock_get(events=[], images_data=None)

        expediente = client.obtener_expediente("ZZZZZZ")

        assert expediente["evento_id"] is None
        assert expediente["imagen_count"] == 0
        assert expediente["imagenes"] == []

    @patch("src.tools.extract_expediente_sic_api.infrastructure.sic_api_client.requests.get")
    @patch("src.tools.extract_expediente_sic_api.infrastructure.sic_api_client.requests.post")
    def test_selecciona_evento_mas_reciente(self, mock_post, mock_get):
        client = self._make_client()

        mock_post.return_value.raise_for_status = MagicMock()
        mock_post.return_value.json.return_value = self._AUTH_RESP

        mock_get.side_effect = self._mock_get(
            events=[
                {"eventRecord": "1000", "eventDate": "2022-01-01T00:00:00Z"},
                {"eventRecord": "9999", "eventDate": "2023-12-01T00:00:00Z"},
                {"eventRecord": "5000", "eventDate": "2021-06-15T00:00:00Z"},
            ],
            images_data=[],
        )

        expediente = client.obtener_expediente("422644")

        assert expediente["evento_id"] == "9999"

    @patch("src.tools.extract_expediente_sic_api.infrastructure.sic_api_client.requests.get")
    @patch("src.tools.extract_expediente_sic_api.infrastructure.sic_api_client.requests.post")
    def test_imagenes_sin_url_son_filtradas(self, mock_post, mock_get):
        client = self._make_client()

        mock_post.return_value.raise_for_status = MagicMock()
        mock_post.return_value.json.return_value = self._AUTH_RESP

        mock_get.side_effect = self._mock_get(
            events=[{"eventRecord": "5109574", "eventDate": "2023-06-23T10:00:00Z"}],
            images_data=[
                {"imageName": "ok.jpg", "imageUrl": "https://s3.amazonaws.com/ok.jpg", "imageSectionId": 1},
                {"imageName": "bad.jpg", "imageUrl": None, "imageSectionId": 2},
                {"imageName": "empty.jpg", "imageUrl": "", "imageSectionId": 3},
            ],
        )

        expediente = client.obtener_expediente("422644")

        assert expediente["imagen_count"] == 1
        assert expediente["imagenes"][0]["nombre"] == "ok.jpg"


class TestHelpers:
    def test_parsear_fecha_iso_z(self):
        dt = _parsear_fecha("2023-06-23T10:00:00Z")
        assert dt.year == 2023 and dt.month == 6 and dt.day == 23

    def test_parsear_fecha_iso_millis(self):
        dt = _parsear_fecha("2023-06-23T10:00:00.000Z")
        assert dt.year == 2023

    def test_parsear_fecha_vacia_retorna_min(self):
        from datetime import datetime
        assert _parsear_fecha("") == datetime.min

    def test_parsear_fecha_invalida_retorna_min(self):
        from datetime import datetime
        assert _parsear_fecha("not-a-date") == datetime.min


class TestSICApiSession:
    def test_carga_credenciales_desde_ssm(self):
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.side_effect = [
            {"Parameter": {"Value": "testuser"}},
            {"Parameter": {"Value": "testpass"}},
        ]
        session = SICApiSession(
            ssm_username_path="/test/username",
            ssm_password_path="/test/password",
            ssm_client=mock_ssm,
        )
        username, password = session.load_credentials()

        assert username == "testuser"
        assert password == "testpass"
