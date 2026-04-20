"""
Script de prueba: conexión RDP desde Python.

Verifica que Python puede:
  1. Guardar credenciales en Windows Credential Manager (cmdkey)
  2. Abrir una sesión RDP via mstsc
  3. Detectar cuándo el escritorio remoto cargó
  4. Tomar un screenshot de confirmación

Uso:
    python scripts/test_rdp_connection.py --host IP_O_HOST --username USUARIO --password PASS

    # Con variables de entorno (o en .env):
    RDP_HOST=192.168.1.10 RDP_USERNAME=admin RDP_PASSWORD=pass \
    python scripts/test_rdp_connection.py

Salida:
    [OK] Credenciales guardadas para TERMSRV/192.168.1.10
    [OK] mstsc lanzado — esperando escritorio remoto...
    [OK] Escritorio detectado (intento 3/15)
    [OK] Screenshot guardado: scripts/rdp_screenshot.png
    [✓] Conexión RDP verificada.
"""
import argparse
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Directorio base del script — todas las rutas de salida son relativas a él
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Cargar .env automáticamente
_dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.isfile(_dotenv_path):
    try:
        from dotenv import load_dotenv
        load_dotenv(_dotenv_path, override=False)
    except ImportError:
        with open(_dotenv_path) as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _, _v = _line.partition("=")
                    os.environ.setdefault(_k.strip(), _v.strip())


# ------------------------------------------------------------------
# Detectores de escritorio remoto cargado
# ------------------------------------------------------------------

def _escribir_texto(texto: str) -> None:
    """
    Escribe texto carácter a carácter via keyboard.send() — funciona en diálogos
    de 'Seguridad de Windows' que bloquean el portapapeles por seguridad.
    Soporta caracteres especiales como \\ . @ * números etc.
    """
    import keyboard
    for char in texto:
        keyboard.write(char, delay=0.03)
    time.sleep(0.1)


def _manejar_dialogo_credenciales(username: str, password: str) -> bool:
    """
    Completa el diálogo 'Seguridad de Windows' de mstsc via portapapeles.

    Usa portapapeles en vez de typewrite() porque typewrite() no soporta
    caracteres especiales como \\ en '.\\PROYECTO_DMS'.

    Retorna True si encontró y manejó el diálogo, False si no apareció.
    """
    import pyautogui
    import pygetwindow as gw

    ventanas = gw.getAllTitles()
    dialogos = [t for t in ventanas if t in ("Seguridad de Windows", "Windows Security")]
    if not dialogos:
        return False

    print(f"  → Diálogo '{dialogos[0]}' — ingresando credenciales via portapapeles...")

    try:
        ventana = gw.getWindowsWithTitle(dialogos[0])[0]
        ventana.activate()
        time.sleep(0.8)
    except Exception:
        pass

    # (screenshot del diálogo eliminado — disparaba el overlay de captura de Win11)

    # El diálogo CredUI bloquea clipboard y keyboard.write().
    # Usamos pywinauto que habla directamente con los controles Win32.
    try:
        from pywinauto import Application
        app = Application(backend="win32").connect(
            title=dialogos[0], timeout=3
        )
        dlg = app.window(title=dialogos[0])

        # Buscar todos los campos Edit del diálogo
        # Estructura típica: Edit[0]=usuario, Edit[1]=contraseña
        campos = dlg.children(class_name="Edit")
        print(f"  → Campos Edit encontrados: {len(campos)}")

        if len(campos) >= 2:
            # Click + set_edit_text en el campo contraseña (índice 1)
            campos[1].click_input()
            campos[1].set_edit_text(password)
            print("  → Contraseña escrita via pywinauto (set_edit_text)")
        elif len(campos) == 1:
            # Solo hay un campo visible — es la contraseña
            campos[0].click_input()
            campos[0].set_edit_text(password)
            print("  → Contraseña escrita via pywinauto (campo único)")
        else:
            print("  → [WARN] No se encontraron campos Edit — usando type_keys fallback")
            dlg.type_keys(password, with_spaces=True)

        time.sleep(0.3)
        # Buscar botón Aceptar y clickearlo
        try:
            dlg.child_window(title="Aceptar").click()
        except Exception:
            pyautogui.hotkey("enter")

        time.sleep(1.5)
        print("  → Credenciales enviadas via pywinauto")
        return True

    except Exception as e:
        print(f"  → pywinauto falló: {e} — intentando enter directo")
        pyautogui.hotkey("enter")
        time.sleep(1.5)
        return True


_MAX_CRED_REINTENTOS = 3


def _escritorio_listo(host: str, username: str, password: str,
                      timeout_s: int = 60, poll_s: float = 3.0) -> bool:
    """
    Espera hasta que mstsc esté conectado al escritorio remoto.

    Cuando conecta, el título cambia de "Conexión a Escritorio remoto"
    (diálogo) a "HOST - Conexión a Escritorio remoto" (sesión activa).
    Si aparece un diálogo de credenciales, lo completa automáticamente.

    Retorna True si conectó, False si agotó el timeout.
    """
    import pygetwindow as gw

    intentos = int(timeout_s / poll_s)
    cred_reintentos = 0

    for i in range(intentos):
        time.sleep(poll_s)
        ventanas = gw.getAllTitles()

        # Sesión activa: título incluye el hostname antes del guión
        # Ej: "172.16.1.77 - Conexión a Escritorio remoto"
        sesion_activa = [
            t for t in ventanas
            if ("Conexión a Escritorio remoto" in t or "Remote Desktop Connection" in t)
            and " - " in t
        ]
        if sesion_activa:
            print(f"  → Escritorio conectado (intento {i+1}/{intentos}): '{sesion_activa[0]}'")
            return True

        # Detectar diálogo de credenciales — máx 3 intentos para no loopear
        dialogo_creds = [
            t for t in ventanas
            if t in ("Seguridad de Windows", "Windows Security")
        ]
        if dialogo_creds:
            if cred_reintentos >= _MAX_CRED_REINTENTOS:
                print(f"[ERROR] Diálogo de credenciales apareció {_MAX_CRED_REINTENTOS} veces "
                      f"— credenciales incorrectas o formato inválido.")
                print("        Revisa RDP_USERNAME y RDP_PASSWORD en .env")
                print(f"        Screenshot: {os.path.join(_SCRIPT_DIR, 'rdp_dialogo_credenciales.png')}")
                return False
            cred_reintentos += 1
            print(f"  → Reintento de credenciales {cred_reintentos}/{_MAX_CRED_REINTENTOS}")
            _manejar_dialogo_credenciales(username, password)
            continue

        # Descartar overlay de captura de Windows 11 ("Click o arrastre para
        # tomar una captura...") — no tiene título de ventana, se cierra con Escape
        _descartar_overlay_captura()

        # Detectar diálogo de certificado — "¿Desea conectarse de todas formas?"
        if _manejar_dialogo_certificado():
            continue

        # Diálogo inicial de mstsc (aún conectando)
        conectando = [
            t for t in ventanas
            if "Conexión a Escritorio remoto" in t or "Remote Desktop Connection" in t
        ]
        estado = f"conectando... '{conectando[0]}'" if conectando else "esperando mstsc..."
        print(f"  → Intento {i+1}/{intentos} — {estado}")

    return False


def _descartar_overlay_captura() -> None:
    """
    Descarta el overlay de captura de pantalla de Windows 11.

    Windows 11 muestra "Haga clic o arrastre para tomar una captura de
    pantalla o video" cuando detecta que una app captura la pantalla.
    Solo envía Escape si detecta la ventana del overlay por título.
    """
    import pyautogui
    import pygetwindow as gw

    ventanas = gw.getAllTitles()
    overlay = [t for t in ventanas if t in (
        "Recorte y anotación", "Snipping Tool", "Screenshot",
    )]
    if overlay:
        print(f"  → Overlay de captura detectado ('{overlay[0]}') — Escape")
        pyautogui.hotkey("escape")
        time.sleep(0.5)


def _manejar_dialogo_certificado() -> bool:
    """
    Detecta el diálogo de advertencia de certificado de mstsc y hace click en Sí.

    Aparece cuando el certificado del servidor RDP no está en el almacén de
    confianza local. Título: 'Conexión a Escritorio remoto'.
    Retorna True si encontró y manejó el diálogo.
    """
    import pyautogui
    import pygetwindow as gw

    ventanas = gw.getAllTitles()
    dialogo = [
        t for t in ventanas
        if t in ("Conexión a Escritorio remoto", "Remote Desktop Connection")
    ]
    if not dialogo:
        return False

    try:
        from pywinauto import Application
        app = Application(backend="win32").connect(
            title=dialogo[0], timeout=2, top_level_only=True
        )
        dlg = app.top_window()

        # Intentar click en "Sí" / "Yes"
        # Imprimir botones disponibles para debug y buscar "Sí"
        botones = dlg.children(class_name="Button")
        nombres = [b.window_text() for b in botones]
        print(f"  → Botones del diálogo certificado: {nombres}")

        for boton in botones:
            nombre = boton.window_text()
            if nombre.lower() in ("sí", "si", "yes"):
                boton.click()
                print(f"  → Certificado: click en '{nombre}'")
                time.sleep(1.0)
                return True
    except Exception as e:
        print(f"  → pywinauto falló: {e}")

    # Fallback: enfocar + Left arrow (mueve foco de "No" → "Sí" en el grupo
    # de botones) + Enter. El orden del diálogo es [Sí][No][Ver certificado]
    # con foco en "No" — Left va a "Sí", Tab va a "Ver certificado".
    try:
        win = gw.getWindowsWithTitle(dialogo[0])[0]
        win.activate()
        time.sleep(0.5)
        pyautogui.hotkey("left")   # No → Sí
        time.sleep(0.2)
        pyautogui.hotkey("enter")
        print("  → Certificado: Left+Enter enviado (Sí)")
        time.sleep(1.0)
        return True
    except Exception:
        pass

    return False


def _esperar_y_descartar_overlay(segundos: int = 4) -> None:
    """
    Espera N segundos y envía Escape para descartar el overlay de captura
    de pantalla de Windows 11 que aparece tras confirmar el certificado RDP.
    """
    import pyautogui
    print(f"  → Esperando {segundos}s y descartando overlay con Escape...")
    time.sleep(segundos)
    pyautogui.hotkey("escape")
    time.sleep(0.5)


def _tomar_screenshot(output_path: str) -> None:
    """Toma screenshot de la pantalla completa y lo guarda."""
    import pyautogui
    screenshot = pyautogui.screenshot()
    screenshot.save(output_path)
    print(f"[OK] Screenshot guardado: {output_path}")


# ------------------------------------------------------------------
# Flujo principal
# ------------------------------------------------------------------

def guardar_credenciales(host: str, username: str, password: str) -> None:
    """Guarda credenciales en Windows Credential Manager via cmdkey."""
    result = subprocess.run(
        ["cmdkey", f"/generic:TERMSRV/{host}",
         f"/user:{username}", f"/pass:{password}"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"cmdkey falló: {result.stderr}")
    print(f"[OK] Credenciales guardadas para TERMSRV/{host}")


def limpiar_credenciales(host: str) -> None:
    """Elimina las credenciales del Credential Manager al terminar."""
    subprocess.run(
        ["cmdkey", f"/delete:TERMSRV/{host}"],
        capture_output=True
    )
    print(f"[OK] Credenciales limpiadas para TERMSRV/{host}")


def abrir_rdp(host: str, fullscreen: bool = False) -> subprocess.Popen:
    """Lanza mstsc y retorna el proceso."""
    cmd = ["mstsc", f"/v:{host}"]
    if fullscreen:
        cmd.append("/f")
    proceso = subprocess.Popen(cmd)
    print(f"[OK] mstsc lanzado (PID {proceso.pid}) — esperando escritorio remoto...")
    return proceso


def main():
    parser = argparse.ArgumentParser(description="Test conexión RDP desde Python")
    parser.add_argument("--host",       default=os.environ.get("RDP_HOST", ""))
    parser.add_argument("--username",   default=os.environ.get("RDP_USERNAME", ""))
    parser.add_argument("--password",   default=os.environ.get("RDP_PASSWORD", ""))
    parser.add_argument("--fullscreen", action="store_true",
                        help="Abrir RDP en pantalla completa")
    parser.add_argument("--timeout",    type=int, default=60,
                        help="Segundos a esperar que cargue el escritorio (default: 60)")
    parser.add_argument("--screenshot", default=os.path.join(_SCRIPT_DIR, "rdp_screenshot.png"),
                        help="Ruta de salida del screenshot")
    args = parser.parse_args()

    if not args.host:
        print("[ERROR] Host requerido: --host o RDP_HOST en .env")
        sys.exit(1)
    if not args.username or not args.password:
        print("[ERROR] Credenciales requeridas: --username / --password o RDP_USERNAME / RDP_PASSWORD en .env")
        sys.exit(1)

    print(f"\n--- Conectando a RDP: {args.host} ---")

    try:
        # Paso 1: guardar credenciales en Credential Manager
        guardar_credenciales(args.host, args.username, args.password)

        # Paso 2: lanzar mstsc
        proceso = abrir_rdp(args.host, fullscreen=args.fullscreen)

        # Paso 3: esperar escritorio (maneja diálogo de credenciales automáticamente)
        if _escritorio_listo(args.host, args.username, args.password, timeout_s=args.timeout):
            print("[OK] Escritorio remoto conectado")
        else:
            print("[WARN] No se confirmó la conexión en el tiempo esperado — tomando screenshot de todos modos")

        # Paso 4: screenshot de verificación
        time.sleep(2)  # pequeña pausa para que la UI termine de renderizar
        _tomar_screenshot(args.screenshot)

        print(f"\n[✓] Test RDP completado. Revisa: {args.screenshot}")

    finally:
        # Limpiar credenciales del Credential Manager siempre
        limpiar_credenciales(args.host)


if __name__ == "__main__":
    main()
