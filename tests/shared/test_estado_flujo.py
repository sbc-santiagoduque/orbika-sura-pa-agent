import pytest
import boto3
from moto import mock_aws
from src.shared.state_store.estado_flujo import EstadoFlujoRepository

TABLE_NAME = "EstadoFlujo"

CASO_BASE = {
    "case_id": "CASE-001",
    "placa": "ABC123",
    "canal": "SIC",
    "fecha_siniestro": "2026-03-15T08:00:00Z",
    "sla_alert": False,
    "prioridad": 1,
    "dry_run": True,
}


@mock_aws
class TestEstadoFlujoRepository:
    def _make_repo(self):
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        dynamodb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[{"AttributeName": "case_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "case_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        return EstadoFlujoRepository(table_name=TABLE_NAME, region="us-east-1")

    # --- create ---

    def test_create_persiste_estado_inicial(self):
        repo = self._make_repo()
        repo.create(CASO_BASE)

        estado = repo.get("CASE-001")
        assert estado["case_id"] == "CASE-001"
        assert estado["fase_actual"] == "ingesta"
        assert estado["fases_completadas"] == []
        assert estado["escalamientos"] == []
        assert estado["flags"] == {}
        assert "ttl_expiry" in estado

    def test_create_falla_si_caso_ya_existe(self):
        repo = self._make_repo()
        repo.create(CASO_BASE)

        with pytest.raises(ValueError, match="ya existe un run activo"):
            repo.create(CASO_BASE)

    # --- get ---

    def test_get_retorna_none_si_no_existe(self):
        repo = self._make_repo()
        assert repo.get("CASE-INEXISTENTE") is None

    def test_get_retorna_estado_existente(self):
        repo = self._make_repo()
        repo.create(CASO_BASE)

        estado = repo.get("CASE-001")
        assert estado is not None
        assert estado["placa"] == "ABC123"

    # --- update_fase ---

    def test_update_fase_actualiza_fase_actual_y_agrega_completada(self):
        repo = self._make_repo()
        repo.create(CASO_BASE)

        repo.update_fase(
            case_id="CASE-001",
            fase_actual="expediente",
            fase_completada={"fase": "F1", "status": "ok", "duracion_ms": 800},
            flags_update={"criterio_panama": False},
        )

        estado = repo.get("CASE-001")
        assert estado["fase_actual"] == "expediente"
        assert len(estado["fases_completadas"]) == 1
        assert estado["fases_completadas"][0]["fase"] == "F1"
        # Los flags se mergean — no reemplazan
        assert estado["flags"]["criterio_panama"] is False

    def test_update_fase_mergea_flags_sin_borrar_anteriores(self):
        repo = self._make_repo()
        repo.create(CASO_BASE)

        repo.update_fase("CASE-001", "documentos",
                         {"fase": "F2", "status": "ok", "duracion_ms": 1200},
                         {"criterio_panama": False})
        repo.update_fase("CASE-001", "orbika",
                         {"fase": "F6", "status": "ok", "duracion_ms": 3000},
                         {"documentos_ok": True})

        estado = repo.get("CASE-001")
        # Ambos flags deben estar presentes
        assert estado["flags"]["criterio_panama"] is False
        assert estado["flags"]["documentos_ok"] is True

    # --- close ---

    def test_close_marca_completado_con_ttl_24h(self):
        repo = self._make_repo()
        repo.create(CASO_BASE)
        repo.close("CASE-001", "pasa_a_analista")

        estado = repo.get("CASE-001")
        assert estado["fase_actual"] == "completado"

    def test_close_error_usa_ttl_3_dias(self):
        repo = self._make_repo()
        repo.create({**CASO_BASE, "case_id": "CASE-ERR"})
        repo.create({**CASO_BASE, "case_id": "CASE-OK"})

        repo.close("CASE-ERR", "error")
        repo.close("CASE-OK", "pasa_a_analista")

        ttl_err = repo.get("CASE-ERR")["ttl_expiry"]
        ttl_ok = repo.get("CASE-OK")["ttl_expiry"]
        assert ttl_err > ttl_ok

    def test_close_decision_invalida_lanza_error(self):
        repo = self._make_repo()
        repo.create(CASO_BASE)

        with pytest.raises(ValueError, match="decision_final inválido"):
            repo.close("CASE-001", "algo_inventado")
