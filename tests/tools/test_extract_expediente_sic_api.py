import json
import pytest
from unittest.mock import MagicMock, patch

import src.tools.extract_expediente_sic_api.lambda_function as handler_module
from src.tools.extract_expediente_sic_api.infrastructure.sic_api_client import (
    SICApiClient,
    _parsear_fecha,
)
from src.shared.sic_api.sic_api_session import SICApiSession

EVENT_BASE = {
    "actionGroup": "agente-expediente-actions",
    "function": "extract_expediente_sic_api",
    "parameters": [
        {"name": "placa",      "type": "string", "value": "422644"},
        {"name": "expediente", "type": "string", "value": "5109574"},
    ],
}

ENV_VARS = {
    "SSM_SIC_API_USERNAME_PATH": "/agente-analista/sic/api/username",
    "SSM_SIC_API_PASSWORD_PATH": "/agente-analista/sic/api/password",
    "SIC_API_BASE_URL":          "https://api-bkp.claims-sic.apps-connectassistance.com",
}

IMAGES_MOCK = [
    {"nombre": "doc1.jpg", "url": "https://s3.amazonaws.com/bucket/doc1.jpg", "seccion_id": 1},
    {"nombre": "doc2.jpg", "url": "https://s3.amazonaws.com/bucket/doc2.jpg", "seccion_id": 2},
    {"nombre": "doc3.jpg", "url": "https://s3.amazonaws.com/bucket/doc3.jpg", "seccion_id": 3},
]

REGISTRO_DYNAMO = {"id": "uuid-abc-123", "date": "2023-06-23", "plate": "422644", "expediente": "5109574"}


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

class TestExtractExpedienteSicApiHandler:

    def _setup_mocks(self, mock_client_cls, mock_repo_cls):
        mock_client_cls.return_value.obtener_imagenes_por_expediente.return_value = IMAGES_MOCK
        mock_repo_cls.return_value.find_by_plate_expediente.return_value = REGISTRO_DYNAMO
        mock_repo_cls.return_value.update_images.return_value = None

    @patch("src.tools.extract_expediente_sic_api.infrastructure.dynamo_repository.AdminCasesRepository")
    @patch("src.tools.extract_expediente_sic_api.infrastructure.sic_api_client.SICApiClient")
    def test_retorna_formato_bedrock_con_message_version(self, mock_client_cls, mock_repo_cls, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)
        self._setup_mocks(mock_client_cls, mock_repo_cls)

        resultado = handler_module.lambda_handler(EVENT_BASE, {})

        assert resultado["messageVersion"] == "1.0"
        assert resultado["response"]["actionGroup"] == "agente-expediente-actions"
        assert resultado["response"]["function"] == "extract_expediente_sic_api"

    @patch("src.tools.extract_expediente_sic_api.infrastructure.dynamo_repository.AdminCasesRepository")
    @patch("src.tools.extract_expediente_sic_api.infrastructure.sic_api_client.SICApiClient")
    def test_retorna_placa_expediente_e_imagenes(self, mock_client_cls, mock_repo_cls, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)
        self._setup_mocks(mock_client_cls, mock_repo_cls)

        resultado = handler_module.lambda_handler(EVENT_BASE, {})
        body = json.loads(resultado["response"]["functionResponse"]["responseBody"]["TEXT"]["body"])

        assert body["placa"] == "422644"
        assert body["expediente"] == "5109574"
        assert body["image_count"] == 3
        assert len(body["images"]) == 3

    @patch("src.tools.extract_expediente_sic_api.infrastructure.dynamo_repository.AdminCasesRepository")
    @patch("src.tools.extract_expediente_sic_api.infrastructure.sic_api_client.SICApiClient")
    def test_action_group_leido_del_evento(self, mock_client_cls, mock_repo_cls, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)
        self._setup_mocks(mock_client_cls, mock_repo_cls)

        evento = {**EVENT_BASE, "actionGroup": "mi-action-group-custom"}
        resultado = handler_module.lambda_handler(evento, {})

        assert resultado["response"]["actionGroup"] == "mi-action-group-custom"

    @patch("src.tools.extract_expediente_sic_api.infrastructure.dynamo_repository.AdminCasesRepository")
    @patch("src.tools.extract_expediente_sic_api.infrastructure.sic_api_client.SICApiClient")
    def test_llama_update_images_en_dynamo(self, mock_client_cls, mock_repo_cls, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)
        self._setup_mocks(mock_client_cls, mock_repo_cls)

        handler_module.lambda_handler(EVENT_BASE, {})

        mock_repo_cls.return_value.update_images.assert_called_once_with(
            record_id="uuid-abc-123",
            date="2023-06-23",
            images=IMAGES_MOCK,
        )

    def test_error_si_falta_parametro_placa(self, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)

        evento = {**EVENT_BASE, "parameters": [{"name": "expediente", "type": "string", "value": "5109574"}]}
        resultado = handler_module.lambda_handler(evento, {})
        body = json.loads(resultado["response"]["functionResponse"]["responseBody"]["TEXT"]["body"])

        assert "error" in body

    def test_error_si_falta_parametro_expediente(self, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)

        evento = {**EVENT_BASE, "parameters": [{"name": "placa", "type": "string", "value": "422644"}]}
        resultado = handler_module.lambda_handler(evento, {})
        body = json.loads(resultado["response"]["functionResponse"]["responseBody"]["TEXT"]["body"])

        assert "error" in body

    def test_error_si_faltan_env_vars(self, monkeypatch):
        for k in ENV_VARS:
            monkeypatch.delenv(k, raising=False)

        resultado = handler_module.lambda_handler(EVENT_BASE, {})
        body = json.loads(resultado["response"]["functionResponse"]["responseBody"]["TEXT"]["body"])

        assert "error" in body


# ---------------------------------------------------------------------------
# SICApiClient — obtener_imagenes_por_expediente
# ---------------------------------------------------------------------------

class TestSICApiClientObtenerImagenesPorExpediente:

    _AUTH_RESP = {
        "data": {
            "accessToken": "access-tok-for-bearer",
            "sub": "uuid-123",
            "isAuthenticated": True,
        }
    }
    _USER_RESP = {
        "data": {"userCompanyID": 42, "codPais": "PAN"}
    }

    def _make_client(self) -> SICApiClient:
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
        return SICApiClient(session=session)

    @patch("src.tools.extract_expediente_sic_api.infrastructure.sic_api_client.requests.get")
    @patch("src.tools.extract_expediente_sic_api.infrastructure.sic_api_client.requests.post")
    def test_retorna_imagenes_del_expediente_especifico(self, mock_post, mock_get, monkeypatch):
        monkeypatch.setenv("SIC_API_BASE_URL", "https://api-bkp.claims-sic.apps-connectassistance.com")
        client = self._make_client()

        mock_post.return_value.raise_for_status = MagicMock()
        mock_post.return_value.json.return_value = self._AUTH_RESP

        user_resp = MagicMock()
        user_resp.raise_for_status = MagicMock()
        user_resp.json.return_value = self._USER_RESP

        search_resp = MagicMock()
        search_resp.raise_for_status = MagicMock()
        search_resp.json.return_value = {
            "data": {"response": {"events": [
                {"eventRecord": "5109574", "eventDate": "2023-06-23T10:00:00Z"},
                {"eventRecord": "9999999", "eventDate": "2024-01-01T00:00:00Z"},
            ]}}
        }

        images_resp = MagicMock()
        images_resp.raise_for_status = MagicMock()
        images_resp.json.return_value = {"data": [
            {"imageName": "doc1.jpg", "imageUrl": "https://s3.amazonaws.com/doc1.jpg", "imageSectionId": 1},
        ]}

        mock_get.side_effect = [user_resp, search_resp, images_resp]

        imagenes = client.obtener_imagenes_por_expediente("422644", "5109574")

        assert len(imagenes) == 1
        assert imagenes[0]["nombre"] == "doc1.jpg"

    @patch("src.tools.extract_expediente_sic_api.infrastructure.sic_api_client.requests.get")
    @patch("src.tools.extract_expediente_sic_api.infrastructure.sic_api_client.requests.post")
    def test_lanza_error_si_expediente_no_existe(self, mock_post, mock_get, monkeypatch):
        monkeypatch.setenv("SIC_API_BASE_URL", "https://api-bkp.claims-sic.apps-connectassistance.com")
        client = self._make_client()

        mock_post.return_value.raise_for_status = MagicMock()
        mock_post.return_value.json.return_value = self._AUTH_RESP

        user_resp = MagicMock()
        user_resp.raise_for_status = MagicMock()
        user_resp.json.return_value = self._USER_RESP

        search_resp = MagicMock()
        search_resp.raise_for_status = MagicMock()
        search_resp.json.return_value = {
            "data": {"response": {"events": [
                {"eventRecord": "1111111", "eventDate": "2023-01-01T00:00:00Z"},
            ]}}
        }

        mock_get.side_effect = [user_resp, search_resp]

        with pytest.raises(ValueError, match="5109574"):
            client.obtener_imagenes_por_expediente("422644", "5109574")


# ---------------------------------------------------------------------------
# SICApiClient — obtener_expediente (flujo existente, sin regresion)
# ---------------------------------------------------------------------------

class TestSICApiClientObtenerExpediente:

    _AUTH_RESP = {
        "data": {
            "accessToken": "access-tok-for-bearer",
            "sub": "uuid-123",
            "isAuthenticated": True,
        }
    }
    _USER_RESP = {
        "data": {"userCompanyID": 42, "codPais": "PAN"}
    }

    def _make_client(self) -> SICApiClient:
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
        return SICApiClient(session=session)

    def _mock_get(self, events, images_data):
        user_resp = MagicMock()
        user_resp.raise_for_status = MagicMock()
        user_resp.json.return_value = self._USER_RESP

        search_resp = MagicMock()
        search_resp.raise_for_status = MagicMock()
        search_resp.json.return_value = {"data": {"response": {"events": events}}}

        side = [user_resp, search_resp]
        if images_data is not None:
            images_resp = MagicMock()
            images_resp.raise_for_status = MagicMock()
            images_resp.json.return_value = {"data": images_data}
            side.append(images_resp)
        return side

    @patch("src.tools.extract_expediente_sic_api.infrastructure.sic_api_client.requests.get")
    @patch("src.tools.extract_expediente_sic_api.infrastructure.sic_api_client.requests.post")
    def test_flujo_completo(self, mock_post, mock_get, monkeypatch):
        monkeypatch.setenv("SIC_API_BASE_URL", "https://api-bkp.claims-sic.apps-connectassistance.com")
        client = self._make_client()

        mock_post.return_value.raise_for_status = MagicMock()
        mock_post.return_value.json.return_value = self._AUTH_RESP
        mock_get.side_effect = self._mock_get(
            events=[{"eventRecord": "5109574", "eventDate": "2023-06-23T10:00:00Z", "plate": "422644"}],
            images_data=[
                {"imageName": "doc1.jpg", "imageUrl": "https://s3.amazonaws.com/doc1.jpg", "imageSectionId": 1},
            ],
        )

        expediente = client.obtener_expediente("422644")

        assert expediente["placa"] == "422644"
        assert expediente["evento_id"] == "5109574"
        assert expediente["imagen_count"] == 1

    @patch("src.tools.extract_expediente_sic_api.infrastructure.sic_api_client.requests.get")
    @patch("src.tools.extract_expediente_sic_api.infrastructure.sic_api_client.requests.post")
    def test_sin_eventos_retorna_vacio(self, mock_post, mock_get, monkeypatch):
        monkeypatch.setenv("SIC_API_BASE_URL", "https://api-bkp.claims-sic.apps-connectassistance.com")
        client = self._make_client()

        mock_post.return_value.raise_for_status = MagicMock()
        mock_post.return_value.json.return_value = self._AUTH_RESP
        mock_get.side_effect = self._mock_get(events=[], images_data=None)

        expediente = client.obtener_expediente("ZZZZZZ")

        assert expediente["evento_id"] is None
        assert expediente["imagen_count"] == 0

    @patch("src.tools.extract_expediente_sic_api.infrastructure.sic_api_client.requests.get")
    @patch("src.tools.extract_expediente_sic_api.infrastructure.sic_api_client.requests.post")
    def test_selecciona_evento_mas_reciente(self, mock_post, mock_get, monkeypatch):
        monkeypatch.setenv("SIC_API_BASE_URL", "https://api-bkp.claims-sic.apps-connectassistance.com")
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
    def test_imagenes_sin_url_son_filtradas(self, mock_post, mock_get, monkeypatch):
        monkeypatch.setenv("SIC_API_BASE_URL", "https://api-bkp.claims-sic.apps-connectassistance.com")
        client = self._make_client()

        mock_post.return_value.raise_for_status = MagicMock()
        mock_post.return_value.json.return_value = self._AUTH_RESP
        mock_get.side_effect = self._mock_get(
            events=[{"eventRecord": "5109574", "eventDate": "2023-06-23T10:00:00Z"}],
            images_data=[
                {"imageName": "ok.jpg",    "imageUrl": "https://s3.amazonaws.com/ok.jpg", "imageSectionId": 1},
                {"imageName": "bad.jpg",   "imageUrl": None,  "imageSectionId": 2},
                {"imageName": "empty.jpg", "imageUrl": "",    "imageSectionId": 3},
            ],
        )

        expediente = client.obtener_expediente("422644")

        assert expediente["imagen_count"] == 1
        assert expediente["imagenes"][0]["nombre"] == "ok.jpg"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# SICApiSession
# ---------------------------------------------------------------------------

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
