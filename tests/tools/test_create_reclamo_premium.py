"""
Tests para create_reclamo_premium — Phase A: recolección de datos.

Cubre:
  - lambda_handler: orquestación completa y manejo de errores
  - DataCollector: agrega datos de SIC + Consulta Integral
  - SICReclamoClient: llamadas HTTP al SIC REST API
  - ConsultaIntegralScraper: (mock) extracción de póliza y coberturas
  - _determinar_reserva: reglas de negocio por tipo de cobertura
"""
import json
import pytest
from datetime import date
from unittest.mock import MagicMock, patch, PropertyMock

import src.tools.create_reclamo_premium.lambda_function as handler_module
from src.tools.create_reclamo_premium.service.data_collector import DataCollector
from src.tools.create_reclamo_premium.service.reclamo_models import (
    DatosReclamo,
    DatosConductor,
    DatosSiniestro,
    DatosPoliza,
)
from src.tools.create_reclamo_premium.infrastructure.sic_reclamo_client import (
    SICReclamoClient,
    _determinar_tipo_siniestro,
    _determinar_reserva,
)

# ---------------------------------------------------------------------------
# Fixtures / datos de prueba
# ---------------------------------------------------------------------------

ENV_VARS = {
    "SSM_SIC_API_USERNAME_PATH": "/agente/sic/username",
    "SSM_SIC_API_PASSWORD_PATH": "/agente/sic/password",
    "SIC_API_BASE_URL": "https://api-bkp.claims-sic.apps-connectassistance.com",
}

EVENTO_SIC = {
    "eventRecord": "EXP001",
    "eventDate": "2026-03-03T13:50:00Z",
    "eventTime": "13:50",
    "eventLocation": "Panama",
    "eventDescription": "Colision vehicular en avenida principal",
    "driverIdNumber": "4-702-1179",
    "driverFirstName": "Alberto",
    "driverLastName": "Antonio",
    "driverGender": "M",
    "driverAge": 45,
    "driverFault": True,
}

DATOS_POLIZA = {
    "numero_poliza": "02-37-1252419-0",
    "cobertura": "POR COLISION O VUELCO",
    "suma_asegurada": 25000.0,
}

RECLAMO_DATA_ESPERADO = DatosReclamo(
    case_number="02195167",
    numero_poliza="02-37-1252419-0",
    siniestro=DatosSiniestro(
        fecha="2026-03-03",
        hora="13:50",
        lugar="Panama",
        tipo="Colision",
        descripcion="Colision vehicular en avenida principal",
        fecha_recibo_documentos=date.today().isoformat(),
    ),
    conductor=DatosConductor(
        cedula="4-702-1179",
        nombre="Alberto",
        apellido="Antonio",
        sexo="M",
        edad=45,
        responsabilidad="Culpable",
    ),
    poliza=DatosPoliza(
        cobertura="POR COLISION O VUELCO",
        reserva=1300.0,
    ),
    ajustador_interno=158,
)


# ---------------------------------------------------------------------------
# Handler tests
# ---------------------------------------------------------------------------

class TestCreateReclamoPremiumHandler:

    @patch("src.tools.create_reclamo_premium.lambda_function._recolectar_datos")
    def test_retorna_200_con_reclamo_data(self, mock_recolectar, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)
        mock_recolectar.return_value = RECLAMO_DATA_ESPERADO

        resultado = handler_module.lambda_handler(
            {"case_number": "02195167", "placa": "XYZ123", "expediente": "EXP001"}, {}
        )

        assert resultado["statusCode"] == 200
        body = json.loads(resultado["body"])
        assert body["case_number"] == "02195167"
        assert "reclamo_data" in body

    @patch("src.tools.create_reclamo_premium.lambda_function._recolectar_datos")
    def test_reclamo_data_serializa_correctamente(self, mock_recolectar, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)
        mock_recolectar.return_value = RECLAMO_DATA_ESPERADO

        resultado = handler_module.lambda_handler(
            {"case_number": "02195167", "placa": "XYZ123", "expediente": "EXP001"}, {}
        )
        body = json.loads(resultado["body"])
        reclamo = body["reclamo_data"]

        assert reclamo["numero_poliza"] == "02-37-1252419-0"
        assert reclamo["siniestro"]["fecha"] == "2026-03-03"
        assert reclamo["conductor"]["cedula"] == "4-702-1179"
        assert reclamo["conductor"]["responsabilidad"] == "Culpable"
        assert reclamo["poliza"]["reserva"] == 1300.0
        assert reclamo["ajustador_interno"] == 158

    def test_retorna_400_si_falta_case_number(self, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)

        resultado = handler_module.lambda_handler({"placa": "XYZ123"}, {})

        assert resultado["statusCode"] == 400
        body = json.loads(resultado["body"])
        assert "case_number" in body["error"].lower()

    def test_retorna_400_si_falta_placa(self, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)

        resultado = handler_module.lambda_handler({"case_number": "02195167"}, {})

        assert resultado["statusCode"] == 400

    def test_retorna_500_si_faltan_env_vars(self, monkeypatch):
        monkeypatch.delenv("SSM_SIC_API_USERNAME_PATH", raising=False)

        resultado = handler_module.lambda_handler(
            {"case_number": "02195167", "placa": "XYZ123", "expediente": "EXP001"}, {}
        )

        assert resultado["statusCode"] == 500

    @patch("src.tools.create_reclamo_premium.lambda_function._recolectar_datos")
    def test_error_en_recoleccion_retorna_500(self, mock_recolectar, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)
        mock_recolectar.side_effect = RuntimeError("SIC no disponible")

        resultado = handler_module.lambda_handler(
            {"case_number": "02195167", "placa": "XYZ123", "expediente": "EXP001"}, {}
        )

        assert resultado["statusCode"] == 500
        body = json.loads(resultado["body"])
        assert "SIC no disponible" in body["error"]


# ---------------------------------------------------------------------------
# DataCollector tests
# ---------------------------------------------------------------------------

class TestDataCollector:

    def _make_collector(self, sic_client=None, ci_scraper=None):
        collector = DataCollector.__new__(DataCollector)
        collector._sic = sic_client or MagicMock()
        collector._ci  = ci_scraper or MagicMock()
        return collector

    def test_retorna_datos_reclamo_completo(self):
        sic = MagicMock()
        sic.obtener_datos_evento.return_value = EVENTO_SIC
        ci = MagicMock()
        ci.obtener_datos_poliza.return_value = DATOS_POLIZA
        collector = self._make_collector(sic, ci)

        resultado = collector.recolectar("02195167", "XYZ123", "EXP001")

        assert isinstance(resultado, DatosReclamo)
        assert resultado.case_number == "02195167"

    def test_llama_sic_con_placa_y_expediente(self):
        sic = MagicMock()
        sic.obtener_datos_evento.return_value = EVENTO_SIC
        ci = MagicMock()
        ci.obtener_datos_poliza.return_value = DATOS_POLIZA
        collector = self._make_collector(sic, ci)

        collector.recolectar("02195167", "XYZ123", "EXP001")

        sic.obtener_datos_evento.assert_called_once_with("XYZ123", "EXP001")

    def test_conductor_responsabilidad_culpable_si_driverFault_true(self):
        sic = MagicMock()
        evento = {**EVENTO_SIC, "driverFault": True}
        sic.obtener_datos_evento.return_value = evento
        ci = MagicMock()
        ci.obtener_datos_poliza.return_value = DATOS_POLIZA
        collector = self._make_collector(sic, ci)

        resultado = collector.recolectar("02195167", "XYZ123", "EXP001")

        assert resultado.conductor.responsabilidad == "Culpable"

    def test_conductor_responsabilidad_inocente_si_driverFault_false(self):
        sic = MagicMock()
        evento = {**EVENTO_SIC, "driverFault": False}
        sic.obtener_datos_evento.return_value = evento
        ci = MagicMock()
        ci.obtener_datos_poliza.return_value = DATOS_POLIZA
        collector = self._make_collector(sic, ci)

        resultado = collector.recolectar("02195167", "XYZ123", "EXP001")

        assert resultado.conductor.responsabilidad == "Inocente"

    def test_fecha_recibo_docs_es_hoy(self):
        sic = MagicMock()
        sic.obtener_datos_evento.return_value = EVENTO_SIC
        ci = MagicMock()
        ci.obtener_datos_poliza.return_value = DATOS_POLIZA
        collector = self._make_collector(sic, ci)

        resultado = collector.recolectar("02195167", "XYZ123", "EXP001")

        assert resultado.siniestro.fecha_recibo_documentos == date.today().isoformat()

    def test_ajustador_interno_siempre_158(self):
        sic = MagicMock()
        sic.obtener_datos_evento.return_value = EVENTO_SIC
        ci = MagicMock()
        ci.obtener_datos_poliza.return_value = DATOS_POLIZA
        collector = self._make_collector(sic, ci)

        resultado = collector.recolectar("02195167", "XYZ123", "EXP001")

        assert resultado.ajustador_interno == 158


# ---------------------------------------------------------------------------
# SICReclamoClient tests
# ---------------------------------------------------------------------------

class TestSICReclamoClient:

    def _make_client(self) -> tuple["SICReclamoClient", MagicMock]:
        client = SICReclamoClient.__new__(SICReclamoClient)
        client._session = MagicMock()
        client._session.load_credentials.return_value = ("user", "pass")
        return client, client._session

    @patch("src.tools.create_reclamo_premium.infrastructure.sic_reclamo_client.requests")
    def test_autenticacion_exitosa_retorna_token(self, mock_requests):
        client, _ = self._make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {"accessToken": "tok123", "sub": "uuid-abc"}}
        mock_requests.post.return_value = mock_resp

        token, sub = client._autenticar()

        assert token == "tok123"
        assert sub == "uuid-abc"

    @patch("src.tools.create_reclamo_premium.infrastructure.sic_reclamo_client.requests")
    def test_obtener_datos_usuario_retorna_company_y_pais(self, mock_requests):
        client, _ = self._make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": {"userCompanyID": 99, "codPais": "PAN"}
        }
        mock_requests.get.return_value = mock_resp

        company_id, pais = client._obtener_datos_usuario("uuid-abc")

        assert company_id == 99
        assert pais == "PAN"

    @patch("src.tools.create_reclamo_premium.infrastructure.sic_reclamo_client.requests")
    def test_lista_eventos_retorna_lista(self, mock_requests):
        client, _ = self._make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": {"response": {"events": [EVENTO_SIC]}}
        }
        mock_requests.get.return_value = mock_resp

        eventos = client._listar_eventos("XYZ123", 1, "PAN", {})

        assert len(eventos) == 1
        assert eventos[0]["eventRecord"] == "EXP001"

    @patch("src.tools.create_reclamo_premium.infrastructure.sic_reclamo_client.requests")
    def test_obtener_datos_evento_filtra_por_expediente(self, mock_requests):
        client, _ = self._make_client()

        otro_evento = {**EVENTO_SIC, "eventRecord": "EXP999"}

        mock_auth = MagicMock()
        mock_auth.json.return_value = {"data": {"accessToken": "tok", "sub": "sub"}}

        mock_user = MagicMock()
        mock_user.json.return_value = {"data": {"userCompanyID": 1, "codPais": "PAN"}}

        mock_eventos = MagicMock()
        mock_eventos.json.return_value = {
            "data": {"response": {"events": [EVENTO_SIC, otro_evento]}}
        }

        mock_requests.post.return_value = mock_auth
        mock_requests.get.side_effect = [mock_user, mock_eventos]

        evento = client.obtener_datos_evento("XYZ123", "EXP001")

        assert evento["eventRecord"] == "EXP001"

    @patch("src.tools.create_reclamo_premium.infrastructure.sic_reclamo_client.requests")
    def test_lanza_error_si_expediente_no_existe(self, mock_requests):
        client, _ = self._make_client()

        mock_auth = MagicMock()
        mock_auth.json.return_value = {"data": {"accessToken": "tok", "sub": "sub"}}

        mock_user = MagicMock()
        mock_user.json.return_value = {"data": {"userCompanyID": 1, "codPais": "PAN"}}

        mock_eventos = MagicMock()
        mock_eventos.json.return_value = {"data": {"response": {"events": []}}}

        mock_requests.post.return_value = mock_auth
        mock_requests.get.side_effect = [mock_user, mock_eventos]

        with pytest.raises(ValueError, match="EXP999"):
            client.obtener_datos_evento("XYZ123", "EXP999")


# ---------------------------------------------------------------------------
# _determinar_tipo_siniestro tests
# ---------------------------------------------------------------------------

class TestDeterminarTipoSiniestro:

    def test_colision_desde_descripcion(self):
        assert _determinar_tipo_siniestro("colision vehicular grave") == "Colision"

    def test_colision_mayusculas(self):
        assert _determinar_tipo_siniestro("COLISION en autopista") == "Colision"

    def test_robo_desde_descripcion(self):
        assert _determinar_tipo_siniestro("robo del vehiculo") == "Robo"

    def test_incendio_desde_descripcion(self):
        assert _determinar_tipo_siniestro("incendio total del auto") == "Incendio"

    def test_tipo_desconocido_retorna_otro(self):
        assert _determinar_tipo_siniestro("accidente sin descripcion clara") == "Otro"

    def test_descripcion_vacia_retorna_otro(self):
        assert _determinar_tipo_siniestro("") == "Otro"


# ---------------------------------------------------------------------------
# _determinar_reserva tests
# ---------------------------------------------------------------------------

class TestDeterminarReserva:

    def test_colision_retorna_1300(self):
        assert _determinar_reserva("POR COLISION O VUELCO") == 1300.0

    def test_colision_parcial_match(self):
        assert _determinar_reserva("COLISION") == 1300.0

    def test_robo_retorna_reserva_robo(self):
        assert _determinar_reserva("POR ROBO") == 5000.0

    def test_incendio_retorna_reserva_incendio(self):
        assert _determinar_reserva("POR INCENDIO") == 2500.0

    def test_cobertura_desconocida_retorna_default(self):
        assert _determinar_reserva("DAÑOS A TERCEROS") == 1000.0

    def test_cobertura_vacia_retorna_default(self):
        assert _determinar_reserva("") == 1000.0
