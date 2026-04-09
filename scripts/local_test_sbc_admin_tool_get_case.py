"""
Test local de sbc-admin-tool-get-case-lambda.

Uso:
    python scripts/local_test_sbc_admin_tool_get_case.py <caso>

Ejemplo:
    python scripts/local_test_sbc_admin_tool_get_case.py 02191935
"""
import json
import os
import sys

os.environ["DYNAMO_TABLE_NAME"] = "sbc-admin-cases"
os.environ["AWS_PROFILE"]       = "675605375671_AWSAdministratorAccess"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.tools.sbc_admin_tool_get_case.lambda_function import lambda_handler

if len(sys.argv) < 2:
    print("Uso: python scripts/local_test_sbc_admin_tool_get_case.py <caso>")
    sys.exit(1)

caso = sys.argv[1]

event = {
    "function": "sbc-admin-tool-get-case-lambda",
    "parameters": [
        {"name": "caso", "value": caso},
    ],
}

print(f"\nTestando caso: {caso}\n")
response = lambda_handler(event, context=None)
print(json.dumps(response, indent=2, ensure_ascii=False, default=str))
