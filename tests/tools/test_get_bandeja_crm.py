import pytest
from unittest.mock import MagicMock, patch
from src.tools.get_bandeja_crm.service.bandeja_service import BandejaService

# Casos sin ordenar que devolvería el scraper de Salesforce
CASOS_RAW = [
    {"case_id": "C-003", "placa": "ZZZ999", "canal": "SIC",
     "fecha_siniestro": "2026-03-10T08:00:00Z",
     "fecha_recepcion": "2026-03-20T09:00:00Z", "sla_alert": False},
    {"case_id": "C-001", "placa": "ABC123", "canal": "Comunidad",
     "fecha_siniestro": "2026-03-12T08:00:00Z",
     "fecha_recepcion": "2026-03-18T08:00:00Z", "sla_alert": True},
    {"case_id": "C-002", "placa": "XYZ456", "canal": "SIC",
     "fecha_siniestro": "2026-03-11T08:00:00Z",
     "fecha_recepcion": "2026-03-19T10:00:00Z", "sla_alert": False},
]


class TestBandejaService:
    def test_prioriza_sla_alert_primero(self):
        """Casos con SLA en riesgo deben ir antes que los demás."""
        service = BandejaService()
        resultado = service.priorizar(CASOS_RAW)

        assert resultado[0]["case_id"] == "C-001"  # sla_alert=True
        assert resultado[0]["prioridad"] == 1

    def test_sin_sla_ordena_por_fecha_recepcion_ascendente(self):
        """Sin SLA, el más antiguo en la bandeja va primero."""
        service = BandejaService()
        resultado = service.priorizar(CASOS_RAW)

        # C-003 recibido 2026-03-20, C-002 recibido 2026-03-19
        # C-002 va antes porque llegó antes
        ids_sin_sla = [c["case_id"] for c in resultado if not c["sla_alert"]]
        assert ids_sin_sla == ["C-002", "C-003"]

    def test_prioridad_es_consecutiva_desde_1(self):
        service = BandejaService()
        resultado = service.priorizar(CASOS_RAW)

        prioridades = [c["prioridad"] for c in resultado]
        assert prioridades == [1, 2, 3]

    def test_bandeja_vacia_retorna_lista_vacia(self):
        service = BandejaService()
        assert service.priorizar([]) == []

    def test_todos_con_sla_mantiene_orden_por_fecha_recepcion(self):
        """Si todos tienen SLA, el orden interno es por fecha_recepcion."""
        casos = [
            {**CASOS_RAW[0], "sla_alert": True, "fecha_recepcion": "2026-03-21T00:00:00Z"},
            {**CASOS_RAW[1], "sla_alert": True, "fecha_recepcion": "2026-03-18T00:00:00Z"},
        ]
        service = BandejaService()
        resultado = service.priorizar(casos)

        # C-001 recibido antes → prioridad 1
        assert resultado[0]["case_id"] == "C-001"
