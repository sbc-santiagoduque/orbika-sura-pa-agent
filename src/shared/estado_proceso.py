"""
EstadoProceso — checkpoint por caso para el pipeline nocturno.

Persiste el estado de cada caso en un archivo JSON local (hoy)
con la misma interfaz que usaría DynamoDB en cloud.

Estados del ciclo de vida de un caso:
    PENDIENTE         → sin procesar
    FASE_A_OK         → datos SIC recolectados, JSON guardado
    FASE_B_INICIADO   → automatización Premium en curso
    COMPLETADO        → reclamo creado en Premium
    RECLAMO_EXISTENTE → Premium detectó que ya existe (skip esperado)
    ERROR_PERMANENTE  → falló todos los reintentos, no se intentará de nuevo
"""
import json
from datetime import datetime, timezone
from pathlib import Path


class EstadoCaso:
    PENDIENTE          = "PENDIENTE"
    FASE_A_OK          = "FASE_A_OK"
    FASE_B_INICIADO    = "FASE_B_INICIADO"
    COMPLETADO         = "COMPLETADO"
    RECLAMO_EXISTENTE  = "RECLAMO_EXISTENTE"
    ERROR_PERMANENTE   = "ERROR_PERMANENTE"
    POLIZA_CANCELADA   = "POLIZA_CANCELADA"

    _SALTAR = {COMPLETADO, RECLAMO_EXISTENTE, POLIZA_CANCELADA, ERROR_PERMANENTE}


_ESTADOS_FINALES_SKIP = {
    EstadoCaso.COMPLETADO,
    EstadoCaso.RECLAMO_EXISTENTE,
    EstadoCaso.POLIZA_CANCELADA,
    EstadoCaso.ERROR_PERMANENTE,
}


class EstadoProceso:
    """
    Checkpoint de sesión: registra el estado de cada caso en disco.

    Uso:
        ep = EstadoProceso("scripts/estado/estado.json")
        if ep.debe_saltar(case_number):
            continue
        ep.marcar_fase_a_ok(case_number, numero_poliza="...")
        ep.marcar_completado(case_number, numero_reclamo="...")
    """

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._datos: dict = {}
        self._cargar()

    # ------------------------------------------------------------------
    # Lectura
    # ------------------------------------------------------------------

    def obtener(self, case_number: str) -> dict | None:
        return self._datos.get(case_number)

    def debe_saltar(self, case_number: str) -> bool:
        """True si el caso ya está en un estado final positivo (no re-procesar)."""
        registro = self._datos.get(case_number)
        if not registro:
            return False
        return registro.get("estado") in _ESTADOS_FINALES_SKIP

    def listar_por_estado(self, estado: str) -> list[str]:
        return [k for k, v in self._datos.items() if v.get("estado") == estado]

    def resumen(self) -> dict[str, int]:
        conteo: dict[str, int] = {}
        for v in self._datos.values():
            e = v.get("estado", EstadoCaso.PENDIENTE)
            conteo[e] = conteo.get(e, 0) + 1
        return conteo

    # ------------------------------------------------------------------
    # Escritura
    # ------------------------------------------------------------------

    def marcar_fase_a_ok(self, case_number: str, numero_poliza: str = "") -> None:
        self._actualizar(case_number, {
            "estado":       EstadoCaso.FASE_A_OK,
            "numero_poliza": numero_poliza,
        })

    def marcar_fase_b_iniciado(self, case_number: str) -> None:
        self._actualizar(case_number, {"estado": EstadoCaso.FASE_B_INICIADO})

    def marcar_completado(self, case_number: str, numero_reclamo: str = "") -> None:
        self._actualizar(case_number, {
            "estado":          EstadoCaso.COMPLETADO,
            "numero_reclamo":  numero_reclamo,
            "ts_completado":   _now(),
        })

    def marcar_reclamo_existente(self, case_number: str) -> None:
        self._actualizar(case_number, {"estado": EstadoCaso.RECLAMO_EXISTENTE})

    def marcar_error_permanente(self, case_number: str, detalle: str = "") -> None:
        self._actualizar(case_number, {
            "estado":  EstadoCaso.ERROR_PERMANENTE,
            "detalle": detalle,
        })

    def marcar_poliza_cancelada(self, case_number: str, detalle: str = "") -> None:
        self._actualizar(case_number, {
            "estado":  EstadoCaso.POLIZA_CANCELADA,
            "detalle": detalle,
        })

    def incrementar_intentos(self, case_number: str, fase: str) -> int:
        registro = self._datos.setdefault(case_number, {"estado": EstadoCaso.PENDIENTE})
        campo = f"intentos_{fase}"
        registro[campo] = registro.get(campo, 0) + 1
        self._guardar()
        return registro[campo]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _actualizar(self, case_number: str, campos: dict) -> None:
        registro = self._datos.setdefault(case_number, {"ts_inicio": _now()})
        registro.update(campos)
        self._guardar()

    def _cargar(self) -> None:
        if self._path.exists():
            with open(self._path, encoding="utf-8") as f:
                self._datos = json.load(f)

    def _guardar(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._datos, f, ensure_ascii=False, indent=2)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
