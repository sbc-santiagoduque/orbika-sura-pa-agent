"""
VPNMonitor — detección de conectividad y reconexión automática con FortiClient.

Estrategia:
  1. Proxy principal: ventana RDP activa → VPN activa (si RDP vive, VPN vive).
  2. Fallback: ping a un host interno configurable (útil si RDP se abre después).
  3. Reconexión:
       a. Si FortiClient ya está abierto → no relanzar.
       b. Si no → lanzar y esperar ventana.
       c. Seleccionar el perfil VPN_PROFILE_NAME en la lista (ej. "SURA VPN").
       d. Hacer click en "Conectar" — FortiClient dispara el push MFA.
       e. Notifica via Telegram para que el usuario apruebe en Authenticator.
       f. Poll hasta que VPN suba o se agote VPN_2FA_TIMEOUT.

Configuración (.env):
    VPN_FORTICLIENT_PATH   — path al ejecutable FortiClient
                             (default: C:\\Program Files\\Fortinet\\FortiClient\\FortiClient.exe)
    VPN_PROFILE_NAME       — nombre exacto del perfil en FortiClient (ej. "SURA VPN")
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

_FORTICLIENT_DEFAULT = r"C:\Program Files\Fortinet\FortiClient\FortiClient.exe"
_PING_TIMEOUT        = 2
_POLL_INTERVAL       = 5
_FORTICLIENT_TITULO  = ".*FortiClient.*"
_WAIT_ARRANQUE       = 4   # segundos tras lanzar antes de buscar la ventana


class VPNMonitor:
    def __init__(
        self,
        notificador,
        forticlient_path: Optional[str] = None,
        vpn_profile: Optional[str] = None,
        host_interno: Optional[str] = None,
        timeout_2fa: int = 120,
        vpn_username: Optional[str] = None,
        vpn_password: Optional[str] = None,
    ):
        self._notificador      = notificador
        self._forticlient_path = forticlient_path or _FORTICLIENT_DEFAULT
        self._vpn_profile      = vpn_profile or "SURA VPN"
        self._host_interno     = host_interno
        self._timeout_2fa      = timeout_2fa
        self._vpn_username     = vpn_username
        self._vpn_password     = vpn_password

    @classmethod
    def desde_env(cls, notificador) -> "VPNMonitor":
        return cls(
            notificador      = notificador,
            forticlient_path = os.environ.get("VPN_FORTICLIENT_PATH"),
            vpn_profile      = os.environ.get("VPN_PROFILE_NAME"),
            host_interno     = os.environ.get("VPN_HOST_INTERNO"),
            timeout_2fa      = int(os.environ.get("VPN_2FA_TIMEOUT", "120")),
            vpn_username     = os.environ.get("VPN_USERNAME"),
            vpn_password     = os.environ.get("VPN_PASSWORD"),
        )

    # ------------------------------------------------------------------
    # Verificación
    # ------------------------------------------------------------------

    def verificar(self) -> bool:
        """
        Retorna True si la conectividad VPN está activa.

        Proxy primario: ventana RDP activa y conectada.
        Fallback: ping a host_interno.
        """
        if self._rdp_activo():
            return True
        if self._host_interno and self._ping(self._host_interno):
            return True
        return False

    def _rdp_activo(self) -> bool:
        """Comprueba si hay una ventana RDP activa (título con ' - ' indica sesión conectada)."""
        try:
            import pygetwindow as gw
            return any(
                ("Escritorio remoto" in t or "Remote Desktop" in t) and " - " in t
                for t in gw.getAllTitles()
            )
        except Exception:
            return False

    def _ping(self, host: str) -> bool:
        """Ping rápido con socket — no requiere permisos de admin."""
        try:
            socket.setdefaulttimeout(_PING_TIMEOUT)
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, 80))
            return True
        except OSError:
            return False

    # ------------------------------------------------------------------
    # Reconexión
    # ------------------------------------------------------------------

    def reconectar(self) -> bool:
        """
        Intenta reconectar la VPN:
          1. Abre FortiClient si no está corriendo.
          2. Selecciona el perfil VPN_PROFILE_NAME y hace click en Conectar.
          3. Notifica al usuario para que apruebe en Microsoft Authenticator.
          4. Espera hasta timeout_2fa segundos para que VPN suba.

        Retorna True si la VPN sube antes del timeout, False si se agota.
        """
        self._notificador.info(
            f"VPN caida — reconectando perfil '{self._vpn_profile}' en FortiClient..."
        )

        ventana = self._obtener_ventana_forticlient()
        if ventana is None:
            self._notificador.error("No se pudo obtener ventana de FortiClient")
            return False

        if not self._click_conectar(ventana):
            self._notificador.alerta(
                f"No se encontró botón Conectar para '{self._vpn_profile}' — "
                "conexión manual requerida"
            )
            # Aún así esperamos: el usuario puede conectar manualmente tras ver el Telegram

        self._notificador.solicitar_aprobacion_vpn()
        return self._esperar_vpn(self._timeout_2fa)

    def _obtener_ventana_forticlient(self):
        """
        Retorna la ventana pywinauto de FortiClient.
        Si ya está abierto la reutiliza; si no, la lanza y espera.
        """
        from pywinauto import Desktop

        def _buscar():
            try:
                return Desktop(backend="uia").window(
                    title_re=_FORTICLIENT_TITULO, top_level_only=True
                )
            except Exception:
                return None

        ventana = _buscar()
        if ventana and ventana.exists():
            self._notificador.info("FortiClient ya estaba abierto — reutilizando ventana")
            return ventana

        # FortiClient no estaba abierto → lanzar
        exe = Path(self._forticlient_path)
        if not exe.exists():
            self._notificador.alerta(
                f"FortiClient no encontrado en {exe}. "
                "Ajustar VPN_FORTICLIENT_PATH en .env"
            )
            return None

        try:
            subprocess.Popen([str(exe)])
            self._notificador.info("FortiClient lanzado — esperando ventana...")
            time.sleep(_WAIT_ARRANQUE)
        except Exception as exc:
            self._notificador.error(f"Error lanzando FortiClient: {exc}")
            return None

        ventana = _buscar()
        if ventana and ventana.exists():
            return ventana

        self._notificador.error("FortiClient lanzado pero ventana no encontrada")
        return None

    def _click_conectar(self, ventana) -> bool:
        """
        Selecciona el perfil, rellena credenciales si están vacías y hace
        click en Conectar.

        Estrategia:
          1. Seleccionar perfil VPN_PROFILE_NAME en el dropdown.
          2. Esperar 1.5 s para que el formulario actualice y muestren los campos.
          3. Rellenar "Nombre de Usuario" y "Contraseña" si están vacíos
             (solo si VPN_USERNAME / VPN_PASSWORD están en .env).
          4. Click en "Conectar".
        """
        try:
            ventana.set_focus()
            time.sleep(0.5)

            # Paso 1: seleccionar el perfil en el dropdown
            try:
                perfil_el = ventana.child_window(title=self._vpn_profile)
                if perfil_el.exists(timeout=3):
                    perfil_el.click_input()
                    time.sleep(1.5)  # esperar que el form muestre los campos
                    self._notificador.info(f"Perfil '{self._vpn_profile}' seleccionado")
                else:
                    self._notificador.alerta(
                        f"Perfil '{self._vpn_profile}' no encontrado en FortiClient — "
                        "verificar VPN_PROFILE_NAME en .env"
                    )
            except Exception as exc:
                self._notificador.alerta(f"No se pudo seleccionar perfil: {exc}")

            # Paso 2: rellenar credenciales si están configuradas
            if self._vpn_username or self._vpn_password:
                self._rellenar_credenciales()

            # Paso 3: click en Conectar / Connect
            for texto in ("Conectar", "Connect", "CONECTAR", "CONNECT"):
                try:
                    btn = ventana.child_window(title=texto, control_type="Button")
                    if btn.exists(timeout=2):
                        btn.click_input()
                        self._notificador.info(
                            f"Click en '{texto}' — esperando aprobación MFA"
                        )
                        return True
                except Exception:
                    continue

            return False

        except Exception as exc:
            self._notificador.error(f"Error automatizando FortiClient UI: {exc}")
            return False

    def _rellenar_credenciales(self) -> None:
        """
        Rellena los campos 'Nombre de Usuario' y 'Contraseña' de FortiClient
        usando pyautogui (clicks directos + write) — sin pywinauto UIA para
        evitar el escaneo lento del árbol de accesibilidad de Electron (~30s).

        Coordenadas relativas a la ventana FortiClient (basadas en proporciones
        del layout estándar: username ~61% desde arriba, password ~65.5%).
        Si la ventana no se encuentra, loguea advertencia y continúa.
        """
        import pyautogui
        try:
            import pygetwindow as gw
            wins = [w for w in gw.getAllWindows()
                    if "FortiClient" in w.title and w.width > 100]
            if not wins:
                self._notificador.alerta("FortiClient no encontrado para rellenar credenciales")
                return
            win = wins[0]
            wx, wy, ww, wh = win.left, win.top, win.width, win.height

            # Campo Nombre de Usuario: ~47% desde izquierda, ~61% desde arriba
            ux = wx + int(ww * 0.47)
            uy = wy + int(wh * 0.61)
            # Campo Contraseña: misma x, ~65.5% desde arriba
            py_ = wy + int(wh * 0.655)

            if self._vpn_username:
                pyautogui.click(ux, uy)
                time.sleep(0.20)
                pyautogui.hotkey("ctrl", "a")
                pyautogui.write(self._vpn_username, interval=0.04)
                time.sleep(0.20)
                self._notificador.info("Nombre de Usuario rellenado")

            if self._vpn_password:
                pyautogui.click(ux, py_)
                time.sleep(0.20)
                pyautogui.hotkey("ctrl", "a")
                pyautogui.write(self._vpn_password, interval=0.04)
                time.sleep(0.20)
                self._notificador.info("Contraseña rellenada")

        except Exception as exc:
            self._notificador.alerta(f"No se pudieron rellenar credenciales VPN: {exc}")

    # ------------------------------------------------------------------
    # Espera
    # ------------------------------------------------------------------

    def _esperar_vpn(self, timeout_s: int) -> bool:
        """Poll hasta que la VPN suba o se agote el timeout."""
        transcurrido = 0
        while transcurrido < timeout_s:
            time.sleep(_POLL_INTERVAL)
            transcurrido += _POLL_INTERVAL
            if self.verificar():
                self._notificador.ok(f"VPN reconectada en {transcurrido}s")
                return True
            self._notificador.info(f"Esperando VPN... {transcurrido}/{timeout_s}s")
        self._notificador.error(
            f"VPN no reconectada en {timeout_s}s — "
            "verificar aprobacion en Microsoft Authenticator"
        )
        return False
