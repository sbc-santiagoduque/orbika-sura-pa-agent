"""
Test local de sbc-admin-tool-classifier-lambda.

Uso:
    python scripts/local_test_sbc_admin_tool_classifier.py <caso> <date>

Ejemplo:
    python scripts/local_test_sbc_admin_tool_classifier.py 02191935 2026-04-08
"""
import json
import os
import sys

os.environ["DYNAMO_TABLE_NAME"] = "sbc-admin-cases"
os.environ["AWS_PROFILE"]       = "675605375671_AWSAdministratorAccess"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.tools.sbc_admin_tool_classifier.lambda_function import lambda_handler

if len(sys.argv) < 3:
    print("Uso: python scripts/local_test_sbc_admin_tool_classifier.py <caso> <date>")
    sys.exit(1)

caso = sys.argv[1]
date = sys.argv[2]

# Ejemplo de imagenes enriquecidas por el agente
imagenes_ejemplo = [
    {
        "nombre":        "1_1775489283174.jpg",
        "url":           "https://inspeccionespty.s3.us-east-2.amazonaws.com/5105712/1_1775489283174.jpg",
        "seccion_id":    1,
        "document_type": "foto_frontal_vehiculo",
        "confidence":    0.95,
        "justification": "Se observa la parte delantera del vehiculo con placa visible.",
    },
    {
        "nombre":        "30_1775489261188.jpg",
        "url":           "https://inspeccionespty.s3.us-east-2.amazonaws.com/5105712/30_1775489261188.jpg",
        "seccion_id":    30,
        "document_type": "foto_danio_lateral",
        "confidence":    0.88,
        "justification": "Se aprecia danio en la parte lateral derecha del vehiculo.",
    },
]

event = {
    "function": "sbc-admin-tool-classifier-lambda",
    "parameters": [
        {"name": "caso",     "value": caso},
        {"name": "date",     "value": date},
        {"name": "imagenes", "value": json.dumps(imagenes_ejemplo)},
    ],
}

print(f"\nTestando clasificacion: caso={caso} date={date} imagenes={len(imagenes_ejemplo)}\n")
response = lambda_handler(event, context=None)
print(json.dumps(response, indent=2, ensure_ascii=False))
