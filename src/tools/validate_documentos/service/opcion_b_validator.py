"""
Opcion B: clasificacion de documentos via Bedrock Vision.

PENDIENTE — implementar cuando se requiera identificar tipos de documentos.

Flujo previsto:
  1. Recibe imagen_urls_signed (pre-firmadas, validas 7 dias) del expediente SIC
  2. Invoca Bedrock con claude-3-5-sonnet o amazon.nova-lite pasando las URLs
  3. Prompt: "Clasifica que tipo de documento es cada imagen:
              foto del danio, cedula, poliza, placa, otro"
  4. Retorna lista de documentos clasificados + resultado agregado

Activar con: VALIDATE_DOCS_STRATEGY=B + BEDROCK_MODEL_ID=<model_id>
"""


class OpcionBValidator:
    """Clasifica tipos de documentos via Bedrock Vision. [STUB — pendiente]"""

    def __init__(self, model_id: str):
        self._model_id = model_id

    def validar(self, expediente: dict) -> dict:
        # TODO: implementar cuando se requiera clasificacion por vision
        # imagen_urls_signed = expediente.get("imagen_urls_signed", [])
        # Invocar bedrock con cada URL y clasificar tipo de documento
        raise NotImplementedError(
            "Opcion B pendiente de implementar. "
            "Usar VALIDATE_DOCS_STRATEGY=A en produccion."
        )
