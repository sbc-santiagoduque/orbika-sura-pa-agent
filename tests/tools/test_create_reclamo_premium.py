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

    def test_poliza_fallback_a_ci_si_sic_no_tiene_noPoliza(self):
        sic = MagicMock()
        evento_sin_poliza = {**EVENTO_SIC_DETAIL, "noPoliza": ""}
        sic.obtener_datos_evento.return_value = evento_sin_poliza

        ci = MagicMock()
        ci.obtener_datos_poliza.return_value = {
            "numero_poliza": "02-37-0000000-0",
            "cobertura": "Colisión o Vuelco",
        }
        collector = self._make_collector(sic, ci)

        resultado = collector.recolectar("02195167", "EJ1949", "5134134")

        assert resultado.numero_poliza == "02-37-0000000-0"


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

    def test_desconocido_retorna_otro(self):
        assert _determinar_tipo_siniestro("daños mecánicos en la transmisión") == "Otro"

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
