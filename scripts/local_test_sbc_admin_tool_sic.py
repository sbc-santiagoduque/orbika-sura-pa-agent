"""
Test local de sbc-admin-tool-sic-lambda.

Uso:
    python scripts/local_test_sbc_admin_tool_sic.py <caso> <placa> <expediente> <siniestro>

Ejemplo:
    python scripts/local_test_sbc_admin_tool_sic.py CASO-001 422644 5105712 SIN-001
"""
import json
import os
import sys

# ------------------------------------------------------------------
# Credenciales — edita estos valores antes de correr
# ------------------------------------------------------------------
os.environ["SIC_API_BASE_URL"] = "https://api-bkp.claims-sic.apps-connectassistance.com"
os.environ["SIC_API_USERNAME"] = "centroauto@sura.com.pa"
os.environ["SIC_API_PASSWORD"] = "Cauto01!"
os.environ["DYNAMO_TABLE_NAME"] = "sbc-admin-cases"
# ------------------------------------------------------------------

# Agrega la raiz del proyecto al path para que funcionen los imports src.*
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.tools.sbc_admin_tool_sic.lambda_function import lambda_handler

if len(sys.argv) < 5:
    print("Uso: python scripts/local_test_sbc_admin_tool_sic.py <caso> <placa> <expediente> <siniestro>")
    sys.exit(1)

caso, placa, expediente, siniestro = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]

event = {
    "function": "sbc-admin-tool-sic-lambda",
    "parameters": [
        {"name": "caso",       "value": caso},
        {"name": "placa",      "value": placa},
        {"name": "expediente", "value": expediente},
        {"name": "siniestro",  "value": siniestro},
    ],
}

print(f"\nTestando: caso={caso} placa={placa} expediente={expediente} siniestro={siniestro}\n")
response = lambda_handler(event, context=None)
print(json.dumps(response, indent=2, ensure_ascii=False))
