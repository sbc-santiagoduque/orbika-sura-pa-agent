"""
Tests para create_reclamo_premium — Phase A: recolección de datos.

Usa la estructura real de la API SIC (GET /api/v1/events/{EventId})
confirmada en inspección de red el 2026-04-16.

Cubre:
  - lambda_handler: orquestación completa y manejo de errores
  - DataCollector: agrega datos del evento SIC detail
  - SICReclamoClient: auth flow + events search + detail endpoint
  - Helpers: _calcular_edad, _mapear_genero, _mapear_responsabilidad
  - _determinar_tipo_siniestro / _determinar_reserva: reglas de negocio
"""
import json
import pytest
from datetime import date
from unittest.mock import MagicMock, patch

import src.tools.create_reclamo_premium.lambda_function as handler_module
from src.tools.create_reclamo_premium.service.data_collector import (
    DataCollector,
    _calcular_edad,
    _mapear_genero,
    _mapear_responsabilidad,
)
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
# Fixture — evento real del endpoint GET /api/v1/events/{EventId}
# Confirmado en inspección de red 2026-04-16 (EventId: 1788291)
# ---------------------------------------------------------------------------

ENV_VARS = {
    "SSM_SIC_API_USERNAME_PATH": "/agente/sic/username",
    "SSM_SIC_API_PASSWORD_PATH": "/agente/sic/password",
    "SIC_API_BASE_URL": "https://api-bkp.claims-sic.apps-connectassistance.com",
}

# Estructura real del campo data.event del endpoint de detalle
EVENTO_SIC_DETAIL = {
    "EventId": 1788291,
    "EventRecord": "5134134",
    "noPoliza": "02-93-1142585-1",
    "eventDateSinister": "2026-04-16",
    "timeSinister": "12:14:00",
    "placeDirectionSinister": "Al frente del colegio San Vicente de Paul, Santiago.",
    "storyDetail": "Venía hacia el colegio y al llegar, me encontré con un vehículo mal estacionado.",
    "driverId": "4-218-210",
    "driverName": "Cristobal",
    "driverLastName": " cedeño marrone",
    "driverGender": 2,
    "driverBirthDate": "1960-12-08",
    "IndResponsible": "",
    "plate": "EJ1949",
    "brand": "FORTHING",
    "model": "T5EVO",
    "year": "2024",
    "coverages": [{"coverageId": 2, "coverageName": "Colisión o Vuelco"}],
    "collisionType": "Menor",
}

# Evento en search (estructura de /api/v2/events/search)
EVENTO_SEARCH = {
    "eventRecord": "5134134",
    "EventId": 1788291,
    "eventDate": "2026-04-16T12:14:00Z",
}


# ---------------------------------------------------------------------------
# Handler tests
# ---------------------------------------------------------------------------

class TestCreateReclamoPremiumHandler:

    @patch("src.tools.create_reclamo_premium.lambda_function._recolectar_datos")
    def test_retorna_200_con_reclamo_data(self, mock_recolectar, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)
        mock_recolectar.return_value = _make_reclamo_data()

        resultado = handler_module.lambda_handler(
            {"case_number": "02195167", "placa": "EJ1949", "expediente": "5134134"}, {}
        )

        assert resultado["statusCode"] == 200
        body = json.loads(resultado["body"])
        assert body["case_number"] == "02195167"
        assert "reclamo_data" in body

    @patch("src.tools.create_reclamo_premium.lambda_function._recolectar_datos")
    def test_reclamo_data_serializa_campos_reales(self, mock_recolectar, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)
        mock_recolectar.return_value = _make_reclamo_data()

        resultado = handler_module.lambda_handler(
            {"case_number": "02195167", "placa": "EJ1949", "expediente": "5134134"}, {}
        )
        body = json.loads(resultado["body"])
        reclamo = body["reclamo_data"]

        assert reclamo["numero_poliza"] == "02-93-1142585-1"
        assert reclamo["siniestro"]["fecha"] == "2026-04-16"
        assert reclamo["siniestro"]["hora"] == "12:14"
        assert reclamo["conductor"]["cedula"] == "4-218-210"
        assert reclamo["poliza"]["reserva"] == 1300.0
        assert reclamo["ajustador_interno"] == 158

    def test_retorna_400_si_falta_case_number(self, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)

        resultado = handler_module.lambda_handler({"placa": "EJ1949"}, {})

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
            {"case_number": "02195167", "placa": "EJ1949", "expediente": "5134134"}, {}
        )

        assert resultado["statusCode"] == 500

    @patch("src.tools.create_reclamo_premium.lambda_function._recolectar_datos")
    def test_error_en_recoleccion_retorna_500(self, mock_recolectar, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)
        mock_recolectar.side_effect = RuntimeError("SIC no disponible")

        resultado = handler_module.lambda_handler(
            {"case_number": "02195167", "placa": "EJ1949", "expediente": "5134134"}, {}
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
        collector._ci  = ci_scraper
        return collector

    def test_retorna_datos_reclamo_con_poliza_de_sic(self):
        sic = MagicMock()
        sic.obtener_datos_evento.return_value = EVENTO_SIC_DETAIL
        collector = self._make_collector(sic)

        resultado = collector.recolectar("02195167", "EJ1949", "5134134")

        assert isinstance(resultado, DatosReclamo)
        assert resultado.numero_poliza == "02-93-1142585-1"

    def test_llama_sic_con_placa_y_expediente_correctos(self):
        sic = MagicMock()
        sic.obtener_datos_evento.return_value = EVENTO_SIC_DETAIL
        collector = self._make_collector(sic)

        collector.recolectar("02195167", "EJ1949", "5134134")

        sic.obtener_datos_evento.assert_called_once_with("EJ1949", "5134134")

    def test_fecha_siniestro_viene_de_eventDateSinister(self):
        sic = MagicMock()
        sic.obtener_datos_evento.return_value = EVENTO_SIC_DETAIL
        collector = self._make_collector(sic)

        resultado = collector.recolectar("02195167", "EJ1949", "5134134")

        assert resultado.siniestro.fecha == "2026-04-16"

    def test_hora_truncada_a_HH_MM(self):
        sic = MagicMock()
        sic.obtener_datos_evento.return_value = EVENTO_SIC_DETAIL
        collector = self._make_collector(sic)

        resultado = collector.recolectar("02195167", "EJ1949", "5134134")

        assert resultado.siniestro.hora == "12:14"

    def test_cobertura_colision_da_reserva_1300(self):
        sic = MagicMock()
        sic.obtener_datos_evento.return_value = EVENTO_SIC_DETAIL
        collector = self._make_collector(sic)

        resultado = collector.recolectar("02195167", "EJ1949", "5134134")

        assert resultado.poliza.cobertura == "Colisión o Vuelco"
        assert resultado.poliza.reserva == 1300.0

    def test_conductor_cedula_desde_driverId(self):
        sic = MagicMock()
        sic.obtener_datos_evento.return_value = EVENTO_SIC_DETAIL
        collector = self._make_collector(sic)

        resultado = collector.recolectar("02195167", "EJ1949", "5134134")

        assert resultado.conductor.cedula == "4-218-210"

    def test_conductor_apellido_sin_espacios_leading(self):
        sic = MagicMock()
        sic.obtener_datos_evento.return_value = EVENTO_SIC_DETAIL
        collector = self._make_collector(sic)

        resultado = collector.recolectar("02195167", "EJ1949", "5134134")

        assert resultado.conductor.apellido == "cedeño marrone"

    def test_conductor_responsabilidad_pendiente_si_ind_responsible_vacio(self):
        sic = MagicMock()
        evento = {**EVENTO_SIC_DETAIL, "IndResponsible": ""}
        sic.obtener_datos_evento.return_value = evento
        collector = self._make_collector(sic)

        resultado = collector.recolectar("02195167", "EJ1949", "5134134")

        assert resultado.conductor.responsabilidad == "Pendiente"

    def test_fecha_recibo_docs_es_hoy(self):
        sic = MagicMock()
        sic.obtener_datos_evento.return_value = EVENTO_SIC_DETAIL
        collector = self._make_collector(sic)

        resultado = collector.recolectar("02195167", "EJ1949", "5134134")

        assert resultado.siniestro.fecha_recibo_documentos == date.today().isoformat()

    def test_ajustador_interno_siempre_158(self):
        sic = MagicMock()
        sic.obtener_datos_evento.return_value = EVENTO_SIC_DETAIL
        collector = self._make_collector(sic)

        resultado = collector.recolectar("02195167", "EJ1949", "5134134")

        assert resultado.ajustador_interno == 158

    def test_ci_es_fuente_primaria_de_numero_poliza(self):
        sic = MagicMock()
        sic.obtener_datos_evento.return_value = EVENTO_SIC_DETAIL  # SIC tiene noPoliza

        ci = MagicMock()
        ci.obtener_datos_poliza.return_value = {
            "numero_poliza":  "02-98-1246363-0",  # CI puede diferir de SIC
            "cobertura":      "",
            "suma_asegurada": 12400.0,
            "estado":         "Vigente",
            "vigi":           "2026-07-01",
            "vigf":           "2027-07-01",
        }
        collector = self._make_collector(sic, ci)

        resultado = collector.recolectar("02195167", "EJ1949", "5134134")

        # Usa el número de CI, no el de SIC
        assert resultado.numero_poliza == "02-98-1246363-0"
        ci.obtener_datos_poliza.assert_called_once_with("EJ1949", "2026-04-16")

    def test_ci_siempre_se_llama_independientemente_de_sic(self):
        sic = MagicMock()
        sic.obtener_datos_evento.return_value = EVENTO_SIC_DETAIL
        ci = MagicMock()
        ci.obtener_datos_poliza.return_value = {
            "numero_poliza": "02-98-1246363-0", "cobertura": "",
            "suma_asegurada": 0, "estado": "Vigente", "vigi": "", "vigf": "",
        }
        collector = self._make_collector(sic, ci)

        collector.recolectar("02195167", "EJ1949", "5134134")

        ci.obtener_datos_poliza.assert_called_once()

    def test_ci_error_usa_noPoliza_de_sic_como_fallback(self):
        sic = MagicMock()
        sic.obtener_datos_evento.return_value = EVENTO_SIC_DETAIL  # noPoliza: 02-93-1142585-1

        ci = MagicMock()
        ci.obtener_datos_poliza.side_effect = RuntimeError("CI no disponible")
        collector = self._make_collector(sic, ci)

        resultado = collector.recolectar("02195167", "EJ1949", "5134134")

        assert resultado.numero_poliza == "02-93-1142585-1"

    def test_ci_error_y_sic_sin_poliza_retorna_vacio(self):
        sic = MagicMock()
        sic.obtener_datos_evento.return_value = {**EVENTO_SIC_DETAIL, "noPoliza": ""}

        ci = MagicMock()
        ci.obtener_datos_poliza.side_effect = RuntimeError("CI no disponible")
        collector = self._make_collector(sic, ci)

        resultado = collector.recolectar("02195167", "EJ1949", "5134134")

        assert resultado.numero_poliza == ""


# ---------------------------------------------------------------------------
# ConsultaIntegralClient tests
# ---------------------------------------------------------------------------

from src.tools.create_reclamo_premium.infrastructure.consulta_integral_scraper import (
    ConsultaIntegralClient,
    ConsultaIntegralClientStub,
    _parse_vigi,
)

_CI_BASE = "http://ptykappa"

_ASEGURADOS_RESPONSE = [
    {"id": 1, "Nombre": "MARIO ABDIEL PEREZ",  "identificación": "8-808-694"},
    {"id": 2, "Nombre": "RICARDO BRAGA",        "identificación": "E-8-133188"},
]

_POLIZAS_MARIO = [
    {
        "id": 4298387, "CORE": "Premium", "Póliza": "02-98-1246363-0",
        "Solución": "Automóvil", "Vigi": "07/01/2026", "Vigf": "07/01/2027",
        "Estado": "Vigente", "Suma": 12400.00, "Saldo": -155.35, "Siniestros": 1,
    }
]

_POLIZAS_RICARDO = [
    {
        "id": 1000001, "CORE": "Premium", "Póliza": "02-11-9999999-0",
        "Solución": "Automóvil", "Vigi": "01/01/2025", "Vigf": "01/01/2026",
        "Estado": "Vencida", "Suma": 8000.00, "Saldo": 0, "Siniestros": 0,
    }
]


class TestConsultaIntegralClient:

    def _make_client(self) -> ConsultaIntegralClient:
        return ConsultaIntegralClient(ci_base_url=_CI_BASE)

    @patch("src.tools.create_reclamo_premium.infrastructure.consulta_integral_scraper._requests")
    def test_retorna_poliza_vigente_para_fecha_en_rango(self, mock_req):
        mock_req.get.side_effect = [
            _mock_resp(_ASEGURADOS_RESPONSE),
            _mock_resp(_POLIZAS_MARIO),
            _mock_resp([]),  # Ricardo sin pólizas que apliquen
        ]
        client = self._make_client()

        resultado = client.obtener_datos_poliza("ED1370", fecha_siniestro="2026-10-15")

        assert resultado["numero_poliza"] == "02-98-1246363-0"
        assert resultado["estado"] == "Vigente"
        assert resultado["vigi"] == "2026-07-01"
        assert resultado["vigf"] == "2027-07-01"
        assert resultado["cobertura"] == ""  # CI no expone cobertura

    @patch("src.tools.create_reclamo_premium.infrastructure.consulta_integral_scraper._requests")
    def test_selecciona_poliza_que_cubre_fecha_sobre_la_vencida(self, mock_req):
        # Dos pólizas: una vencida que cubre la fecha, una vigente que no cubre
        poliza_vencida_cubre = {
            **_POLIZAS_MARIO[0],
            "Estado": "Vencida",
            "Póliza": "02-98-VENCIDA-0",
            "Vigi": "01/01/2026", "Vigf": "06/30/2026",
        }
        poliza_vigente_no_cubre = {
            **_POLIZAS_MARIO[0],
            "Estado": "Vigente",
            "Póliza": "02-98-VIGENTE-0",
            "Vigi": "07/01/2026", "Vigf": "07/01/2027",
        }
        mock_req.get.side_effect = [
            _mock_resp([_ASEGURADOS_RESPONSE[0]]),
            _mock_resp([poliza_vencida_cubre, poliza_vigente_no_cubre]),
        ]
        client = self._make_client()

        resultado = client.obtener_datos_poliza("ED1370", fecha_siniestro="2026-03-15")

        assert resultado["numero_poliza"] == "02-98-VENCIDA-0"

    @patch("src.tools.create_reclamo_premium.infrastructure.consulta_integral_scraper._requests")
    def test_sin_fecha_retorna_primera_poliza_vigente(self, mock_req):
        mock_req.get.side_effect = [
            _mock_resp([_ASEGURADOS_RESPONSE[0]]),
            _mock_resp(_POLIZAS_MARIO),
        ]
        client = self._make_client()

        resultado = client.obtener_datos_poliza("ED1370", fecha_siniestro=None)

        assert resultado["numero_poliza"] == "02-98-1246363-0"

    @patch("src.tools.create_reclamo_premium.infrastructure.consulta_integral_scraper._requests")
    def test_agrega_polizas_de_multiples_asegurados(self, mock_req):
        mock_req.get.side_effect = [
            _mock_resp(_ASEGURADOS_RESPONSE),          # dos asegurados
            _mock_resp(_POLIZAS_MARIO),                # pólizas Mario
            _mock_resp(_POLIZAS_RICARDO),              # pólizas Ricardo
        ]
        client = self._make_client()

        # fecha dentro de vigencia de Mario (julio 2026 – julio 2027)
        resultado = client.obtener_datos_poliza("ED1370", fecha_siniestro="2026-10-15")

        assert resultado["numero_poliza"] == "02-98-1246363-0"

    @patch("src.tools.create_reclamo_premium.infrastructure.consulta_integral_scraper._requests")
    def test_error_si_no_hay_asegurados(self, mock_req):
        mock_req.get.return_value = _mock_resp([])
        client = self._make_client()

        with pytest.raises(RuntimeError, match="no se encontraron asegurados"):
            client.obtener_datos_poliza("XX9999", fecha_siniestro="2026-10-15")

    @patch("src.tools.create_reclamo_premium.infrastructure.consulta_integral_scraper._requests")
    def test_error_si_no_hay_polizas(self, mock_req):
        mock_req.get.side_effect = [
            _mock_resp([_ASEGURADOS_RESPONSE[0]]),
            _mock_resp([]),
        ]
        client = self._make_client()

        with pytest.raises(RuntimeError, match="no se encontraron pólizas"):
            client.obtener_datos_poliza("XX9999", fecha_siniestro="2026-10-15")

    @patch("src.tools.create_reclamo_premium.infrastructure.consulta_integral_scraper._requests")
    def test_error_http_se_propaga_como_runtime_error(self, mock_req):
        mock_req.get.side_effect = ConnectionError("ptykappa inaccesible")
        client = self._make_client()

        with pytest.raises(RuntimeError, match="CI AseguradoPlaca"):
            client.obtener_datos_poliza("ED1370", fecha_siniestro="2026-10-15")

    def test_suma_asegurada_se_convierte_a_float(self):
        from src.tools.create_reclamo_premium.infrastructure.consulta_integral_scraper import (
            ConsultaIntegralClient,
        )
        with patch(
            "src.tools.create_reclamo_premium.infrastructure.consulta_integral_scraper._requests"
        ) as mock_req:
            mock_req.get.side_effect = [
                _mock_resp([_ASEGURADOS_RESPONSE[0]]),
                _mock_resp([{**_POLIZAS_MARIO[0], "Suma": "12400"}]),
            ]
            client = ConsultaIntegralClient(_CI_BASE)
            resultado = client.obtener_datos_poliza("ED1370", "2026-10-15")
            assert isinstance(resultado["suma_asegurada"], float)

    @patch("src.tools.create_reclamo_premium.infrastructure.consulta_integral_scraper._requests")
    def test_respuesta_como_string_json_se_parsea_correctamente(self, mock_req):
        """CI devuelve el body como string-dentro-de-JSON — debe manejarse transparentemente."""
        import json
        mock_req.get.side_effect = [
            _mock_resp(json.dumps(_ASEGURADOS_RESPONSE)),   # string, no lista
            _mock_resp(json.dumps(_POLIZAS_MARIO)),         # string, no lista
        ]
        client = self._make_client()

        resultado = client.obtener_datos_poliza("ED1370", fecha_siniestro="2026-10-15")

        assert resultado["numero_poliza"] == "02-98-1246363-0"

    def test_parse_vigi_formato_correcto(self):
        from datetime import date
        assert _parse_vigi("07/01/2026") == date(2026, 7, 1)

    def test_parse_vigi_string_vacio_retorna_none(self):
        assert _parse_vigi("") is None

    def test_parse_vigi_formato_invalido_retorna_none(self):
        assert _parse_vigi("2026-07-01") is None  # ISO no es el formato de CI

    def test_stub_retorna_datos_fijos_sin_http(self):
        stub = ConsultaIntegralClientStub()
        resultado = stub.obtener_datos_poliza("EJ1949", "2026-04-16")
        assert resultado["numero_poliza"] == "02-37-0000000-0"
        assert resultado["cobertura"] == ""

    def test_stub_acepta_datos_personalizados(self):
        stub = ConsultaIntegralClientStub({"numero_poliza": "99-99-9999999-9", "cobertura": ""})
        assert stub.obtener_datos_poliza("XX0000")["numero_poliza"] == "99-99-9999999-9"


def _mock_resp(data):
    """Helper: MagicMock de requests.Response con .json() y .raise_for_status()."""
    m = MagicMock()
    m.json.return_value = data
    m.raise_for_status.return_value = None
    return m


# ---------------------------------------------------------------------------
# SICReclamoClient tests
# ---------------------------------------------------------------------------

class TestSICReclamoClient:

    def _make_client(self) -> tuple[SICReclamoClient, MagicMock]:
        client = SICReclamoClient.__new__(SICReclamoClient)
        client._session = MagicMock()
        client._session.load_credentials.return_value = ("user", "pass")
        return client, client._session

    @patch("src.tools.create_reclamo_premium.infrastructure.sic_reclamo_client.requests")
    def test_autenticacion_exitosa_retorna_token_y_sub(self, mock_requests):
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
        mock_resp.json.return_value = {"data": {"userCompanyID": 99, "codPais": "PAN"}}
        mock_requests.get.return_value = mock_resp

        company_id, pais = client._obtener_datos_usuario("uuid-abc")

        assert company_id == 99
        assert pais == "PAN"

    @patch("src.tools.create_reclamo_premium.infrastructure.sic_reclamo_client.requests")
    def test_buscar_event_id_encuentra_por_eventRecord(self, mock_requests):
        client, _ = self._make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": {"response": {"events": [EVENTO_SEARCH]}}
        }
        mock_requests.get.return_value = mock_resp

        event_id = client._buscar_event_id_por_expediente("EJ1949", "5134134", 1, "PAN", {})

        assert event_id == 1788291

    @patch("src.tools.create_reclamo_premium.infrastructure.sic_reclamo_client.requests")
    def test_buscar_event_id_lanza_error_si_no_existe(self, mock_requests):
        client, _ = self._make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {"response": {"events": [EVENTO_SEARCH]}}}
        mock_requests.get.return_value = mock_resp

        with pytest.raises(ValueError, match="9999999"):
            client._buscar_event_id_por_expediente("EJ1949", "9999999", 1, "PAN", {})

    @patch("src.tools.create_reclamo_premium.infrastructure.sic_reclamo_client.requests")
    def test_obtener_detalle_evento_retorna_event_dict(self, mock_requests):
        client, _ = self._make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "success": True,
            "data": {"event": EVENTO_SIC_DETAIL},
        }
        mock_requests.get.return_value = mock_resp

        evento = client._obtener_detalle_evento(1788291, {})

        assert evento["EventId"] == 1788291
        assert evento["noPoliza"] == "02-93-1142585-1"

    @patch("src.tools.create_reclamo_premium.infrastructure.sic_reclamo_client.requests")
    def test_obtener_detalle_lanza_error_si_success_false(self, mock_requests):
        client, _ = self._make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"success": False, "error": "not found"}
        mock_requests.get.return_value = mock_resp

        with pytest.raises(RuntimeError, match="success=false"):
            client._obtener_detalle_evento(9999, {})


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

class TestCalcularEdad:

    def test_calcula_edad_correcta(self):
        # Cristobal nació 1960-12-08 → 65 años en 2026
        edad = _calcular_edad("1960-12-08")
        assert edad in (65, 66)  # depende de si ya pasó el cumpleaños en 2026

    def test_fecha_vacia_retorna_cero(self):
        assert _calcular_edad("") == 0

    def test_fecha_invalida_retorna_cero(self):
        assert _calcular_edad("no-es-fecha") == 0

    def test_fecha_con_timestamp_usa_solo_fecha(self):
        edad = _calcular_edad("1960-12-08T00:00:00")
        assert edad > 0


class TestMapearGenero:

    def test_codigo_2_retorna_M(self):
        # Confirmado: Cristobal (M) → driverGender = 2
        assert _mapear_genero(2) == "M"

    def test_codigo_1_retorna_F(self):
        assert _mapear_genero(1) == "F"

    def test_ninguno_retorna_M_como_default(self):
        assert _mapear_genero(None) == "M"

    def test_codigo_desconocido_retorna_M(self):
        assert _mapear_genero(99) == "M"


class TestMapearResponsabilidad:

    def test_vacio_retorna_pendiente(self):
        assert _mapear_responsabilidad("") == "Pendiente"

    def test_none_retorna_pendiente(self):
        assert _mapear_responsabilidad(None) == "Pendiente"

    def test_uno_retorna_culpable(self):
        assert _mapear_responsabilidad("1") == "Culpable"

    def test_dos_retorna_inocente(self):
        assert _mapear_responsabilidad("2") == "Inocente"


# ---------------------------------------------------------------------------
# _determinar_tipo_siniestro tests
# ---------------------------------------------------------------------------

class TestDeterminarTipoSiniestro:

    def test_colision_desde_nombre_cobertura(self):
        assert _determinar_tipo_siniestro("Colisión o Vuelco") == "Colision"

    def test_colision_desde_descripcion(self):
        assert _determinar_tipo_siniestro("venía hacia la colisión en la vía") == "Colision"

    def test_robo_desde_descripcion(self):
        assert _determinar_tipo_siniestro("robo del vehiculo en zona céntrica") == "Robo"

    def test_incendio_desde_descripcion(self):
        assert _determinar_tipo_siniestro("incendio total del auto") == "Incendio"

    def test_vuelco_mapea_a_colision(self):
        assert _determinar_tipo_siniestro("vuelco del vehículo") == "Colision"

    def test_roce_desde_relato_conductor(self):
        # Caso real EJ1949/5134134: coverages=[] → inferir desde storyDetail
        assert _determinar_tipo_siniestro(
            "lo rocé levemente, ya que no tuve el espacio suficiente para pasar"
        ) == "Colision"

    def test_desconocido_retorna_otro(self):
        assert _determinar_tipo_siniestro("falla eléctrica en el sistema de frenos") == "Otro"

    def test_vacio_retorna_otro(self):
        assert _determinar_tipo_siniestro("") == "Otro"


# ---------------------------------------------------------------------------
# _determinar_reserva tests
# ---------------------------------------------------------------------------

class TestDeterminarReserva:

    def test_colision_o_vuelco_retorna_1300(self):
        assert _determinar_reserva("Colisión o Vuelco") == 1300.0

    def test_colision_mayusculas(self):
        assert _determinar_reserva("POR COLISION O VUELCO") == 1300.0

    def test_robo_retorna_5000(self):
        assert _determinar_reserva("POR ROBO") == 5000.0

    def test_incendio_retorna_2500(self):
        assert _determinar_reserva("POR INCENDIO") == 2500.0

    def test_cobertura_desconocida_retorna_1000(self):
        assert _determinar_reserva("DAÑOS A TERCEROS") == 1000.0

    def test_vacia_retorna_1000(self):
        assert _determinar_reserva("") == 1000.0


# ---------------------------------------------------------------------------
# Helpers de fixture
# ---------------------------------------------------------------------------

def _make_reclamo_data() -> DatosReclamo:
    return DatosReclamo(
        case_number="02195167",
        numero_poliza="02-93-1142585-1",
        siniestro=DatosSiniestro(
            fecha="2026-04-16",
            hora="12:14",
            lugar="Al frente del colegio San Vicente de Paul, Santiago.",
            tipo="Colision",
            descripcion="Venía hacia el colegio...",
            fecha_recibo_documentos=date.today().isoformat(),
        ),
        conductor=DatosConductor(
            cedula="4-218-210",
            nombre="Cristobal",
            apellido="cedeño marrone",
            sexo="M",
            edad=65,
            responsabilidad="Pendiente",
        ),
        poliza=DatosPoliza(
            cobertura="Colisión o Vuelco",
            reserva=1300.0,
        ),
        ajustador_interno=158,
    )
