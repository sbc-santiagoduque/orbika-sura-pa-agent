import pytest
import boto3
from moto import mock_aws
from src.shared.observability.resultado_caso import ResultadoCasoRepository

TABLE_NAME = "ResultadoCaso"

VALID_PAYLOAD = {
    "case_id": "CASE-001",
    "decision_final": "pasa_a_analista",
    "fases_ejecutadas": [
        {"fase": "F1", "status": "ok", "duracion_ms": 800},
        {"fase": "F2", "status": "ok", "duracion_ms": 1200},
    ],
    "duracion_total_ms": 12000,
    "timestamp_inicio": "2026-04-01T10:00:00Z",
    "timestamp_fin": "2026-04-01T10:00:12Z",
    "escalamientos": [],
    "dry_run": False,
}


@mock_aws
class TestResultadoCasoRepository:
    def _create_table(self, dynamodb):
        dynamodb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[{"AttributeName": "case_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "case_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )

    def test_save_persiste_item_en_dynamodb(self):
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        self._create_table(dynamodb)

        repo = ResultadoCasoRepository(table_name=TABLE_NAME, region="us-east-1")
        repo.save(VALID_PAYLOAD)

        table = dynamodb.Table(TABLE_NAME)
        item = table.get_item(Key={"case_id": "CASE-001"})["Item"]
        assert item["decision_final"] == "pasa_a_analista"
        assert item["dry_run"] is False
        assert "ttl_expiry" in item

    def test_save_decision_invalida_lanza_error(self):
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        self._create_table(dynamodb)

        repo = ResultadoCasoRepository(table_name=TABLE_NAME, region="us-east-1")
        payload = {**VALID_PAYLOAD, "decision_final": "decision_inventada"}

        with pytest.raises(ValueError, match="decision_final inválido"):
            repo.save(payload)

    def test_save_dry_run_persiste_con_flag(self):
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        self._create_table(dynamodb)

        repo = ResultadoCasoRepository(table_name=TABLE_NAME, region="us-east-1")
        payload = {**VALID_PAYLOAD, "case_id": "CASE-DRY", "dry_run": True}
        repo.save(payload)

        table = dynamodb.Table(TABLE_NAME)
        item = table.get_item(Key={"case_id": "CASE-DRY"})["Item"]
        assert item["dry_run"] is True

    def test_ttl_se_calcula_segun_decision_final(self):
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        self._create_table(dynamodb)

        repo = ResultadoCasoRepository(table_name=TABLE_NAME, region="us-east-1")

        # pasa_a_analista → TTL 24h
        repo.save({**VALID_PAYLOAD, "case_id": "CASE-OK"})
        item_ok = dynamodb.Table(TABLE_NAME).get_item(Key={"case_id": "CASE-OK"})["Item"]

        # error → TTL 3 días
        repo.save({**VALID_PAYLOAD, "case_id": "CASE-ERR", "decision_final": "error"})
        item_err = dynamodb.Table(TABLE_NAME).get_item(Key={"case_id": "CASE-ERR"})["Item"]

        assert item_err["ttl_expiry"] > item_ok["ttl_expiry"]
