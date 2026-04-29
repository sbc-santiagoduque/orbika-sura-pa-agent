"""
Notificador — log interno + Telegram para el pipeline nocturno.

Configuración (.env):
    TELEGRAM_BOT_TOKEN   — token del bot (obtenido de @BotFather)
    TELEGRAM_CHAT_ID     — chat_id del destinatario (usuario o grupo)

Si TELEGRAM_BOT_TOKEN no está configurado, solo escribe al log.
El canal de Telegram se puede enchufar al bot existente del proyecto
cuando esté disponible — la interfaz no cambia.

Uso:
    n = Notificador.desde_env(log_path="scripts/resultados/run.log")
    n.info("Procesando caso 02191935")
    n.alerta("VPN caida — aprueba Microsoft Authenticator")
    n.esperar_aprobacion_vpn(timeout_s=180)
"""
import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests as _requests

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_TIMEOUT_HTTP  = 10


class Notificador:
    def __init__(
        self,
        telegram_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        log_path: Optional[str | Path] = None,
    ):
        self._token   = telegram_token
        self._chat_id = chat_id
        self._log_path = Path(log_path) if log_path else None
        if self._log_path:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def desde_env(cls, log_path: Optional[str | Path] = None) -> "Notificador":
        return cls(
            telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN"),
            chat_id=os.environ.get("TELEGRAM_CHAT_ID"),
            log_path=log_path,
        )

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def info(self, mensaje: str) -> None:
        self._log(f"[INFO]  {mensaje}")

    def ok(self, mensaje: str) -> None:
        self._log(f"[OK]    {mensaje}")
        self._telegram(f"OK: {mensaje}")

    def alerta(self, mensaje: str) -> None:
        self._log(f"[ALERT] {mensaje}")
        self._telegram(f"ALERTA: {mensaje}")

    def error(self, mensaje: str) -> None:
        self._log(f"[ERROR] {mensaje}")
        self._telegram(f"ERROR: {mensaje}")

    def resumen_final(self, completados: int, existentes: int,
                      errores: int, total: int) -> None:
        lineas = [
            "Resumen de procesamiento nocturno:",
            f"  Total pendientes:  {total}",
            f"  Completados:       {completados}",
            f"  Ya existian:       {existentes}",
            f"  Errores:           {errores}",
        ]
        texto = "\n".join(lineas)
        self._log(f"[RESUMEN]\n{texto}")
        self._telegram(texto)

    def solicitar_aprobacion_vpn(self) -> None:
        """Notifica al usuario que debe aprobar la solicitud en Microsoft Authenticator."""
        msg = (
            "VPN desconectada. Se intentó reconectar con FortiClient.\n"
            "Aprueba la solicitud en Microsoft Authenticator para continuar."
        )
        self.alerta(msg)

    def stop_sin_avance(self, n: int, ultimo_case: str) -> None:
        msg = (
            f"Pipeline detenido: {n} casos consecutivos sin avance.\n"
            f"Ultimo caso: {ultimo_case}\n"
            "Revisar log para diagnóstico."
        )
        self.error(msg)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _log(self, mensaje: str) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        linea = f"{ts} {mensaje}"
        print(linea)
        if self._log_path:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(linea + "\n")

    def _telegram(self, mensaje: str) -> None:
        if not self._token or not self._chat_id:
            return
        try:
            url = _TELEGRAM_API.format(token=self._token)
            _requests.post(
                url,
                json={"chat_id": self._chat_id, "text": mensaje},
                timeout=_TIMEOUT_HTTP,
            )
        except Exception as exc:
            logger.warning("Telegram: no se pudo enviar notificacion: %s", exc)
