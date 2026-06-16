"""
Tests para EstadoProceso — checkpoint de casos por sesión de procesamiento.
"""
import json
import pytest
from pathlib import Path

from src.shared.estado_proceso import EstadoProceso, EstadoCaso


class TestEstadoCasoEnum:
    def test_valores_definidos(self):
        assert EstadoCaso.PENDIENTE          == "PENDIENTE"
        assert EstadoCaso.FASE_A_OK          == "FASE_A_OK"
        assert EstadoCaso.FASE_B_INICIADO    == "FASE_B_INICIADO"
        assert EstadoCaso.COMPLETADO         == "COMPLETADO"
        assert EstadoCaso.RECLAMO_EXISTENTE  == "RECLAMO_EXISTENTE"
        assert EstadoCaso.ERROR_PERMANENTE   == "ERROR_PERMANENTE"


class TestEstadoProceso:
    @pytest.fixture
    def ep(self, tmp_path):
        return EstadoProceso(tmp_path / "estado.json")

    def test_caso_nuevo_es_pendiente(self, ep):
        assert ep.obtener("02000001") is None

    def test_marcar_fase_a_ok(self, ep):
        ep.marcar_fase_a_ok("02000001", numero_poliza="02-93-1000000-0")
        r = ep.obtener("02000001")
        assert r["estado"] == EstadoCaso.FASE_A_OK
        assert r["numero_poliza"] == "02-93-1000000-0"

    def test_marcar_completado(self, ep):
        ep.marcar_fase_a_ok("02000001")
        ep.marcar_completado("02000001", numero_reclamo="2026-4-300000")
        r = ep.obtener("02000001")
        assert r["estado"] == EstadoCaso.COMPLETADO
        assert r["numero_reclamo"] == "2026-4-300000"

    def test_marcar_reclamo_existente(self, ep):
        ep.marcar_reclamo_existente("02000001")
        assert ep.obtener("02000001")["estado"] == EstadoCaso.RECLAMO_EXISTENTE

    def test_marcar_error_permanente(self, ep):
        ep.marcar_error_permanente("02000001", detalle="SIC timeout")
        r = ep.obtener("02000001")
        assert r["estado"] == EstadoCaso.ERROR_PERMANENTE
        assert "SIC timeout" in r["detalle"]

    def test_incrementar_intentos(self, ep):
        ep.incrementar_intentos("02000001", fase="a")
        ep.incrementar_intentos("02000001", fase="a")
        ep.incrementar_intentos("02000001", fase="b")
        r = ep.obtener("02000001")
        assert r["intentos_a"] == 2
        assert r["intentos_b"] == 1

    def test_persistencia_en_disco(self, tmp_path):
        path = tmp_path / "estado.json"
        ep1 = EstadoProceso(path)
        ep1.marcar_fase_a_ok("02000001", numero_poliza="02-93-X")
        ep2 = EstadoProceso(path)
        assert ep2.obtener("02000001")["numero_poliza"] == "02-93-X"

    def test_listar_por_estado(self, ep):
        ep.marcar_fase_a_ok("02000001")
        ep.marcar_completado("02000002", numero_reclamo="X")
        ep.marcar_completado("02000003", numero_reclamo="Y")
        completados = ep.listar_por_estado(EstadoCaso.COMPLETADO)
        assert set(completados) == {"02000002", "02000003"}

    def test_debe_saltar_completado(self, ep):
        ep.marcar_completado("02000001", numero_reclamo="X")
        assert ep.debe_saltar("02000001") is True

    def test_debe_saltar_reclamo_existente(self, ep):
        ep.marcar_reclamo_existente("02000001")
        assert ep.debe_saltar("02000001") is True

    def test_no_debe_saltar_pendiente(self, ep):
        assert ep.debe_saltar("02000099") is False

    def test_debe_saltar_error_permanente(self, ep):
        ep.marcar_error_permanente("02000001", "timeout")
        assert ep.debe_saltar("02000001") is True

    def test_resumen(self, ep):
        ep.marcar_completado("C1", numero_reclamo="X")
        ep.marcar_completado("C2", numero_reclamo="Y")
        ep.marcar_reclamo_existente("C3")
        ep.marcar_error_permanente("C4", "err")
        r = ep.resumen()
        assert r[EstadoCaso.COMPLETADO]         == 2
        assert r[EstadoCaso.RECLAMO_EXISTENTE]  == 1
        assert r[EstadoCaso.ERROR_PERMANENTE]   == 1
