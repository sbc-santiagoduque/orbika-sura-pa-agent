"""
Service: ValidateDocumentosService
Orquesta la validacion de documentos delegando al validator inyectado.
El validator concreto (A o B) lo instancia el handler segun la estrategia.
"""


class ValidateDocumentosService:
    def __init__(self, validator):
        self._validator = validator

    def validar(self, expediente: dict) -> dict:
        return self._validator.validar(expediente)
