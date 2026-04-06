"""
Opcion A: validacion de documentos por existencia de imagenes.
Estrategia simple: imagen_count > 0 → documentos presentes.
"""


class OpcionAValidator:
    """Valida existencia de documentos contando imagenes en el expediente."""

    def validar(self, expediente: dict) -> dict:
        imagen_count = expediente.get("imagen_count", 0)
        tiene_documentos = imagen_count > 0

        return {
            "resultado": "documentos_presentes" if tiene_documentos else "sin_documentos",
            "estrategia": "A",
            "imagen_count": imagen_count,
            "detalle": f"{imagen_count} imagen(es) encontrada(s) en el expediente",
        }
