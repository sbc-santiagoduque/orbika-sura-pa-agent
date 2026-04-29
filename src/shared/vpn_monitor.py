"""
VPNMonitor — detección de conectividad y reconexión automática con FortiClient.

Estrategia:
  1. Proxy principal: ventana RDP activa → VPN activa (si RDP vive, VPN vive).
  2. Fallback: ping a un host interno configurable (útil si RDP se abre después).
  3. Reconexión: lanzar FortiClient con el perfil guardado → esperar aprobación
     del push de Microsoft Authenticator (el usuario aprueba en el teléfono).
     Notifica via Telegram con `solicitar_aprobacion_vpn()`.

Configuración (.env):
    VPN_FORTICLIENT_PATH   — path al ejecutable FortiClient
                             (default: C:\\Program Files\\Fortinet\\FortiClient\\FortiClient.exe)
    VPN_PROFILE_NAME       — nombre del perfil VPN guardado en FortiClient
    VPN_HOST_INTERNO       — IP o host interno para verificar conectividad (fallback)
    VPN_2FA_TIMEOUT        — segundos para esperar aprobación del push (default: 120)

Uso:
    monitor = VPNMonitor.desde_env(notificador)
    if not monitor.verificar():
        ok = monitor.reconectar()
        if not ok:
            raise RuntimeError("No se pudo restablecer VPN")
"""
import os
import socket
import subprocess
import time
from pathlib import Path
from typing import Optional

_FORTICLIENT_DEFAULT = (
    r"C:\Program Files\Fortinet\FortiClient\FortiClient.exe"
)
_PING_TIMEOUT  = 2
_POLL_INTERVAL = 5


class VPNMonitor:
    def __init__(
        self,
        notificador,
        forticlient_path: Optional[str] = None,
        vpn_profile: Optional[str] = None,
        host_interno: Optional[str] = None,
        timeout_2fa: int = 120,
    ):
        self._notificador      = notificador
        self._forticlient_path = forticlient_path or _FORTICLIENT_DEFAULT
        self._vpn_profile      = vpn_profile
        self._host_interno     = host_interno
        self._timeout_2fa      = timeout_2fa

    @classmethod
    def desde_env(cls, notificador) -> "VPNMonitor":
        return cls(
            notificador      = notificador,
            forticlient_path = os.environ.get("VPN_FORTICLIENT_PATH"),
            vpn_profile      = os.environ.get("VPN_PROFILE_NAME"),
            host_interno     = os.environ.get("VPN_HOST_INTERNO"),
            timeout_2fa      = int(os.environ.get("VPN_2FA_TIMEOUT", "120")),
        )

    # ------------------------------------------------------------------
    # Verificación
    # ------------------------------------------------------------------

    def verificar(self) -> bool:
        """
        Retorna True si la conectividad VPN está activa.

        Proxy primario: ventana RDP activa.
        Fallback: ping a host_interno.
        """
        if self._rdp_activo():
            return True
        if self._host_interno and self._ping(self._host_interno):
            return True
        return False

    def _rdp_activo(self) -> bool:
        """Comprueba si hay una ventana de Escritorio Remoto activa."""
        try:
            import pygetwindow as gw
            titulos = gw.getAllTitles()
            return any(
                "Escritorio remoto" in t or "Remote Desktop" in t
                for t in titulos
            )
        except Exception:
            return False

    def _ping(self, host: str) -> bool:
        """Ping rápido con socket — no requiere permisos de admin."""
        try:
            socket.setdefaulttimeout(_PING_TIMEOUT)
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(
                (host, 80)
            )
            return True
        except OSError:
            return False

    # ------------------------------------------------------------------
    # Reconexión
    # ------------------------------------------------------------------

    def reconectar(self) -> bool:
        """
        Intenta reconectar la VPN:
          1. Lanza FortiClient con el perfil configurado.
          2. Notifica al usuario para que apruebe en Microsoft Authenticator.
          3. Espera hasta timeout_2fa segundos para que VPN suba.

        Retorna True si la VPN sube antes del timeout, False si se agota.
        """
        self._notificador.info("VPN caida — iniciando reconexion con FortiClient...")
        self._lanzar_forticlient()

        self._notificador.solicitar_aprobacion_vpn()

        return self._esperar_vpn(self._timeout_2fa)

    def _lanzar_forticlient(self) -> None:
        """
        Lanza FortiClient. Si el perfil está guardado, FortiClient lo conecta
        automáticamente al abrirse (comportamiento típico con perfil guardado).
        """
        exe = Path(self._forticlient_path)
        if not exe.exists():
            self._notificador.alerta(
                f"FortiClient no encontrado en {exe}. "
                "Ajustar VPN_FORTICLIENT_PATH en .env"
            )
            return
        try:
            cmd = [str(exe)]
            if self._vpn_profile:
                # Algunos builds de FortiClient aceptan --vpn-name
                cmd += ["--vpn-name", self._vpn_profile]
            subprocess.Popen(cmd)
            self._notificador.info(f"FortiClient lanzado: {' '.join(cmd)}")
        except Exception as exc:
            self._notificador.error(f"Error lanzando FortiClient: {exc}")

    def _esperar_vpn(self, timeout_s: int) -> bool:
        """Poll hasta que la VPN suba o se agote el timeout."""
        transcurrido = 0
        while transcurrido < timeout_s:
            time.sleep(_POLL_INTERVAL)
            transcurrido += _POLL_INTERVAL
            if self.verificar():
                self._notificador.ok(f"VPN reconectada ({transcurrido}s)")
                return True
            self._notificador.info(
                f"Esperando VPN... {transcurrido}/{timeout_s}s"
            )
        self._notificador.error(
            f"VPN no reconectada en {timeout_s}s. "
            "Verificar aprobacion en Microsoft Authenticator."
        )
        return False
