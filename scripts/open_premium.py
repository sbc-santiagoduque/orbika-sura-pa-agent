"""
Automatización Phase B: conectar RDP y abrir el sistema Premium.

Flujo con capturas en cada paso:
  paso_01_inicio.png              — pantalla al arrancar el script
  paso_02_mstsc_lanzado.png       — mstsc recién abierto
  paso_03_dialogo_certificado.png — diálogo de advertencia detectado
  paso_04_certificado_aceptado.png— después de aceptar el certificado
  paso_05_dialogo_credenciales.png— diálogo "Seguridad de Windows"
  paso_06_credenciales_enviadas.png — después de enviar la contraseña
  paso_07_escritorio_rdp.png      — escritorio remoto conectado
  paso_08_buscando_premium.png    — pantalla donde busca el ícono
  paso_09_premium_encontrado.png  — ícono detectado (marcado en rojo)
  paso_10_premium_abierto.png     — app Premium cargada

Uso:
    python scripts/open_premium.py            # flujo completo
    python scripts/open_premium.py --no-rdp   # RDP ya activo, solo abrir Premium
    python scripts/open_premium.py --dry-run  # solo detectar ícono, sin doble click

Requisitos:
    - Python corriendo como Administrador (necesario para pywinauto)
    - pip install pyautogui pywinauto pygetwindow pillow

Variables de entorno (.env):
    RDP_HOST       IP o hostname del servidor RDP (ej: 172.16.1.77)
    RDP_USERNAME   Usuario Windows (ej: .\\PROYECTO_DMS)
    RDP_PASSWORD   Contraseña
"""
import argparse
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DOCS_DIR   = os.path.join(_SCRIPT_DIR, "..", "docs")
_TEMPLATE   = os.path.join(_DOCS_DIR, "template_server_premium.png")

# Directorio de capturas — scripts/capturas/
_CAPTURAS_DIR = os.path.join(_SCRIPT_DIR, "capturas")

# Cargar .env automáticamente
_dotenv_path = os.path.join(_SCRIPT_DIR, "..", ".env")
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
# Capturas de pantalla numeradas
# ------------------------------------------------------------------

def _captura(nombre: str, label: str = "") -> str:
    """
    Toma un screenshot y lo guarda en scripts/capturas/.
    nombre: ej. "paso_03_dialogo_certificado.png"
    """
    import pyautogui
    os.makedirs(_CAPTURAS_DIR, exist_ok=True)
    path = os.path.join(_CAPTURAS_DIR, nombre)
    time.sleep(0.5)          # pequeña pausa para que la UI termine de renderizar
    pyautogui.screenshot().save(path)
    tag = f" [{label}]" if label else ""
    print(f"  📸 {nombre}{tag}")
    return path


def _captura_con_marca(nombre: str, x: int, y: int, radio: int = 40) -> str:
    """
    Toma screenshot y dibuja un círculo rojo en (x, y) para marcar el ícono detectado.
    """
    import pyautogui
    from PIL import Image, ImageDraw

    os.makedirs(_CAPTURAS_DIR, exist_ok=True)
    path = os.path.join(_CAPTURAS_DIR, nombre)
    time.sleep(0.5)

    img = pyautogui.screenshot()
    draw = ImageDraw.Draw(img)
    draw.ellipse(
        [x - radio, y - radio, x + radio, y + radio],
        outline="red", width=4
    )
    draw.line([x - radio - 10, y, x + radio + 10, y], fill="red", width=3)
    draw.line([x, y - radio - 10, x, y + radio + 10], fill="red", width=3)
    img.save(path)
    print(f"  📸 {nombre} [marcado en ({x}, {y})]")
    return path


# ------------------------------------------------------------------
# RDP
# ------------------------------------------------------------------

def _limpiar_credenciales(host: str) -> None:
    """Limpia credenciales del Credential Manager si existen."""
    subprocess.run(["cmdkey", f"/delete:TERMSRV/{host}"], capture_output=True)


def _encontrar_rdp() -> str:
    """
    Busca 'SERVER PREMIUM.rdp' en el escritorio de cualquier usuario del sistema.
    Necesario porque el script corre como Administrador (perfil distinto al usuario real).
    Orden de búsqueda:
      1. Variable de entorno RDP_FILE (permite override explícito en .env)
      2. Glob en C:\\Users\\*\\Desktop\\
      3. Escritorio público
    """
    import glob

    # Override explícito vía .env
    env_path = os.environ.get("RDP_FILE", "")
    if env_path and os.path.isfile(env_path):
        return env_path

    # Buscar en todos los perfiles de usuario
    patron = "C:\\Users\\*\\Desktop\\SERVER PREMIUM.rdp"
    matches = glob.glob(patron)
    if matches:
        return matches[0]

    # Escritorio público
    pub = os.path.join(os.environ.get("PUBLIC", "C:\\Users\\Public"), "Desktop", "SERVER PREMIUM.rdp")
    if os.path.isfile(pub):
        return pub

    # Fallback: ruta esperada (para el mensaje de error)
    return "C:\\Users\\Subocol\\Desktop\\SERVER PREMIUM.rdp"


_RDP_DESKTOP = _encontrar_rdp()


def _abrir_rdp(host: str = "", username: str = "", fullscreen: bool = True) -> subprocess.Popen:
    """
    Abre la conexión RDP usando el archivo 'SERVER PREMIUM.rdp' del escritorio local.

    Ese archivo tiene authentication level:i:0 (sin validación de cert) y el
    username ya configurado — es exactamente lo que el usuario abre manualmente.
    """
    if not os.path.isfile(_RDP_DESKTOP):
        raise FileNotFoundError(
            f"No se encontró el archivo RDP: {_RDP_DESKTOP}\n"
            "Asegurate de que 'SERVER PREMIUM.rdp' esté en el escritorio."
        )
    cmd = ["mstsc", _RDP_DESKTOP]
    if fullscreen:
        cmd.append("/f")
    proceso = subprocess.Popen(cmd)
    print(f"[OK] mstsc lanzado con 'SERVER PREMIUM.rdp' (PID {proceso.pid})")
    return proceso


def _manejar_dialogo_credenciales(username: str, password: str) -> bool:
    import pygetwindow as gw
    import pyautogui

    ventanas = gw.getAllTitles()
    dialogos = [t for t in ventanas if t in ("Seguridad de Windows", "Windows Security")]
    if not dialogos:
        return False

    titulo = dialogos[0]
    print(f"  → Diálogo credenciales: '{titulo}'")
    _captura("paso_05_dialogo_credenciales.png", "antes de enviar credenciales")

    def _pegar(texto: str) -> None:
        """Pega texto via portapapeles — soporta @, !, # y cualquier carácter especial."""
        import pyperclip
        pyperclip.copy(texto)
        time.sleep(0.15)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.15)

    # Intento 1: pywinauto uia — busca por título exacto o parcial
    try:
        from pywinauto import Desktop
        todas = Desktop(backend="uia").windows()
        wins = [w for w in todas if titulo in w.window_text() and w.is_visible()]
        print(f"  → uia windows con '{titulo}': {len(wins)}")
        if wins:
            dlg = wins[0]
            campos = dlg.descendants(control_type="Edit")
            print(f"  → Campos Edit (uia): {len(campos)}")
            if len(campos) >= 2:
                campos[0].click_input()
                campos[0].type_keys("^a")
                campos[0].type_keys(username, with_spaces=True)
                print(f"  → Usuario: {username}")
                time.sleep(0.2)
                campos[1].click_input()
                campos[1].type_keys("^a")
                campos[1].type_keys(password, with_spaces=True)
                print(f"  → Contraseña escrita (uia)")
            elif len(campos) == 1:
                campos[0].click_input()
                campos[0].type_keys("^a")
                campos[0].type_keys(password, with_spaces=True)
                print(f"  → Contraseña escrita uia (campo único)")
            else:
                raise RuntimeError("0 campos Edit")
            time.sleep(0.3)
            try:
                dlg.child_window(title="Aceptar", control_type="Button").click_input()
            except Exception:
                pyautogui.hotkey("enter")
            time.sleep(1.5)
            _captura("paso_06_credenciales_enviadas.png", "uia")
            return True
    except Exception as e:
        print(f"  → uia falló: {e}")

    # Intento 2: click por posición + portapapeles (soporta caracteres especiales)
    try:
        wins_gw = gw.getWindowsWithTitle(titulo)
        if not wins_gw:
            raise RuntimeError("ventana no encontrada")
        win = wins_gw[0]
        win.activate()
        time.sleep(0.6)
        cx = win.left + win.width // 2

        # Campo usuario (~45% alto)
        cy_user = win.top + int(win.height * 0.45)
        print(f"  → Click usuario ({cx}, {cy_user})")
        pyautogui.click(cx, cy_user, clicks=3, interval=0.1)
        time.sleep(0.2)
        pyautogui.hotkey("ctrl", "a")
        _pegar(username)

        # Campo contraseña (~60% alto)
        cy_pwd = win.top + int(win.height * 0.60)
        print(f"  → Click contraseña ({cx}, {cy_pwd})")
        pyautogui.click(cx, cy_pwd, clicks=3, interval=0.1)
        time.sleep(0.2)
        pyautogui.hotkey("ctrl", "a")
        _pegar(password)

        time.sleep(0.3)
        # Click en botón Aceptar por posición (~85% alto, centrado)
        cy_ok = win.top + int(win.height * 0.85)
        pyautogui.click(cx, cy_ok)
        time.sleep(1.5)
        _captura("paso_06_credenciales_enviadas.png", "portapapeles")
        return True
    except Exception as e:
        print(f"  → click+portapapeles: {e}")

    # Intento 3: Tab + portapapeles
    try:
        wins_gw = gw.getWindowsWithTitle(titulo)
        if wins_gw:
            wins_gw[0].activate()
            time.sleep(0.5)
        pyautogui.hotkey("ctrl", "a")
        _pegar(username)
        time.sleep(0.2)
        pyautogui.hotkey("tab")
        time.sleep(0.2)
        pyautogui.hotkey("ctrl", "a")
        _pegar(password)
        time.sleep(0.3)
        pyautogui.hotkey("enter")
        time.sleep(1.5)
        _captura("paso_06_credenciales_enviadas.png", "tab+portapapeles")
        return True
    except Exception as e:
        print(f"  → tab fallback: {e}")

    return True


def _strip_amp(texto: str) -> str:
    """Elimina el prefijo de tecla aceleradora & de Windows. 'Co&nectar' → 'Conectar'"""
    return texto.replace("&", "").strip()


def _inspeccionar_botones_dialogo(titulo: str) -> list[str]:
    """Retorna los textos de botones (sin &) del diálogo con ese título."""
    try:
        from pywinauto import Desktop
        wins = [w for w in Desktop(backend="win32").windows()
                if w.window_text() == titulo and w.is_visible()]
        if wins:
            botones = wins[0].children(class_name="Button")
            return [_strip_amp(b.window_text()) for b in botones]
    except Exception:
        pass
    return []


def _manejar_dialogo_certificado() -> bool:
    """
    Maneja diálogos de mstsc con título "Conexión a Escritorio remoto":

    Tipo advertencia — botones [Sí][No]        → Left+Enter (foco en No → mueve a Sí)
    Tipo Advertencia — botones [Conectar][Cancelar] → Enter (foco en Conectar)
    Tipo error       — botón solo [Aceptar]    → Enter (cierra el error, no reintenta)

    Retorna True si manejó el diálogo, False si no había diálogo.
    """
    import pygetwindow as gw
    import pyautogui

    _TITULOS_CERT = (
        "Advertencia de seguridad de conexión a Escritorio remoto",
        "Remote Desktop Connection Security Warning",
        "Conexión a Escritorio remoto",
        "Remote Desktop Connection",
    )

    ventanas = gw.getAllTitles()
    titulo = next((t for t in ventanas if t in _TITULOS_CERT), None)
    if not titulo:
        return False

    # Inspeccionar botones para distinguir tipo de diálogo
    botones = _inspeccionar_botones_dialogo(titulo)
    nombres_lower = [b.lower() for b in botones]
    print(f"  → Diálogo '{titulo}' — botones: {botones}")

    # Diálogo de error (solo "Aceptar") — cerrar y NO reintentar conexión
    if botones and all(b.lower() in ("aceptar", "ok", "cerrar", "close")
                       for b in botones if b.strip()):
        print(f"  → [ERROR RDP] Diálogo de error detectado — cerrando con Enter")
        _captura("error_rdp_dialogo.png", "error de conexión RDP")
        try:
            win = gw.getWindowsWithTitle(titulo)[0]
            win.activate()
            time.sleep(0.3)
        except Exception:
            pass
        pyautogui.hotkey("enter")
        time.sleep(0.5)
        return False   # retorna False para que el loop no siga como si nada

    _captura("paso_03_dialogo_certificado.png", "antes de aceptar")

    # Intentar click directo con pywinauto uia (devuelve texto sin &)
    _BOTONES_ACEPTAR = ("conectar", "connect", "sí", "si", "yes")
    try:
        from pywinauto import Desktop
        # Intentar primero con uia (texto limpio sin &)
        for backend in ("uia", "win32"):
            wins = [w for w in Desktop(backend=backend).windows()
                    if titulo in w.window_text() and w.is_visible()]
            if not wins:
                continue
            dlg = wins[0]
            botones = dlg.descendants(control_type="Button") if backend == "uia" \
                      else dlg.children(class_name="Button")
            for boton in botones:
                texto_limpio = _strip_amp(boton.window_text()).lower()
                if texto_limpio in _BOTONES_ACEPTAR:
                    print(f"  → Click '{boton.window_text()}' (backend={backend})")
                    boton.click_input()
                    time.sleep(1.0)
                    _captura("paso_04_certificado_aceptado.png", f"click {backend}")
                    return True
    except Exception as e:
        print(f"  → pywinauto: {e}")

    # Fallback teclado — usar nombre limpio del botón para decidir tecla
    try:
        win = gw.getWindowsWithTitle(titulo)[0]
        win.activate()
        time.sleep(0.5)

        if any(b in nombres_lower for b in ("conectar", "connect")):
            # "Advertencia de seguridad": botón Conectar → suele ser el default → Enter
            pyautogui.hotkey("enter")
            print(f"  → Enter (Conectar)")
        else:
            # "Conexión a Escritorio remoto": foco en "No" → Left → "Sí" → Enter
            pyautogui.hotkey("left")
            time.sleep(0.2)
            pyautogui.hotkey("enter")
            print(f"  → Left+Enter (Sí)")

        time.sleep(1.0)
        _captura("paso_04_certificado_aceptado.png", "teclado fallback")
        return True
    except Exception as ex:
        print(f"  → Fallback teclado: {ex}")

    return False


_MAX_CRED_REINTENTOS = 3


def _esperar_escritorio(host: str, username: str, password: str,
                         timeout_s: int = 90, poll_s: float = 3.0) -> bool:
    import pygetwindow as gw

    intentos = int(timeout_s / poll_s)
    cred_reintentos = 0

    for i in range(intentos):
        time.sleep(poll_s)
        ventanas = gw.getAllTitles()

        # Sesión activa: título "HOST - Conexión a Escritorio remoto"
        sesion_activa = [
            t for t in ventanas
            if ("Conexión a Escritorio remoto" in t or "Remote Desktop Connection" in t)
            and " - " in t
        ]
        if sesion_activa:
            print(f"[OK] Escritorio conectado: '{sesion_activa[0]}'")
            return True

        # Diálogo de credenciales
        dialogo_creds = [
            t for t in ventanas
            if t in ("Seguridad de Windows", "Windows Security")
        ]
        if dialogo_creds:
            if cred_reintentos >= _MAX_CRED_REINTENTOS:
                print(f"[ERROR] Credenciales rechazadas {_MAX_CRED_REINTENTOS} veces")
                _captura("error_credenciales_rechazadas.png")
                return False
            cred_reintentos += 1
            print(f"  → Credenciales intento {cred_reintentos}/{_MAX_CRED_REINTENTOS}")
            _manejar_dialogo_credenciales(username, password)
            continue

        # Advertencia de certificado (nuevo formato)
        advertencia = [
            t for t in ventanas
            if "Advertencia de seguridad" in t or "Security Warning" in t
        ]
        if advertencia:
            print(f"  → Advertencia certificado: '{advertencia[0]}'")
            _manejar_dialogo_certificado()
            continue

        # Certificado clásico
        _manejar_dialogo_certificado()

        conectando = [
            t for t in ventanas
            if "Escritorio remoto" in t or "Remote Desktop" in t
        ]
        estado = f"'{conectando[0]}'" if conectando else "esperando mstsc..."
        print(f"  → Intento {i+1}/{intentos} — {estado}")

    return False


# ------------------------------------------------------------------
# Abrir SERVER PREMIUM
# ------------------------------------------------------------------

def _enfocar_ventana_rdp(host: str) -> bool:
    import pygetwindow as gw

    ventanas = [
        t for t in gw.getAllTitles()
        if ("Conexión a Escritorio remoto" in t or "Remote Desktop Connection" in t)
        and " - " in t
    ]
    if not ventanas:
        return False
    try:
        win = gw.getWindowsWithTitle(ventanas[0])[0]
        win.activate()
        time.sleep(1.0)
        return True
    except Exception as e:
        print(f"  → No pudo enfocar ventana RDP: {e}")
        return False


def _buscar_icono_premium(confidence: float = 0.8):
    import pyautogui

    if not os.path.isfile(_TEMPLATE):
        raise FileNotFoundError(
            f"Template no encontrado: {_TEMPLATE}\n"
            "Ejecuta el crop del ícono primero (ver docs/escritorio_remoto_config.png)"
        )

    try:
        location = pyautogui.locateOnScreen(_TEMPLATE, confidence=confidence)
    except pyautogui.ImageNotFoundException:
        return None

    if location is None:
        return None

    center = pyautogui.center(location)
    return int(center.x), int(center.y)


def _esperar_escritorio_rdp_listo(timeout_s: int = 90) -> bool:
    """
    Espera hasta que el escritorio remoto haya cargado completamente.
    Detecta cuando ya no se ve "Applying user settings" / "Aplicando configuración"
    tomando screenshots periódicos y comparando el cambio de pantalla.
    """
    import pyautogui
    from PIL import Image
    import hashlib

    print(f"  → Esperando que el escritorio remoto cargue (hasta {timeout_s}s)...")
    fin = time.time() + timeout_s
    hash_anterior = None
    iguales_consecutivos = 0

    while time.time() < fin:
        time.sleep(3)
        img = pyautogui.screenshot()
        # Hash de la imagen para detectar cuando la pantalla deja de cambiar
        hash_actual = hashlib.md5(img.tobytes()).hexdigest()

        if hash_actual == hash_anterior:
            iguales_consecutivos += 1
            print(f"  → Pantalla estable ({iguales_consecutivos}/3)...")
            if iguales_consecutivos >= 3:
                print(f"  → Escritorio listo — pantalla estable por {iguales_consecutivos * 3}s")
                return True
        else:
            iguales_consecutivos = 0
            print(f"  → Pantalla cambiando (aún cargando)...")

        hash_anterior = hash_actual

    print(f"  → [WARN] Timeout esperando escritorio — intentando de todas formas")
    return False


def _abrir_servidor_premium(dry_run: bool = False, retries: int = 5) -> bool:
    import pyautogui

    print("\n[→] Buscando ícono SERVER PREMIUM...")
    _captura("paso_08_buscando_premium.png", "pantalla donde busca el ícono")

    for intento in range(1, retries + 1):
        coords = _buscar_icono_premium(confidence=0.8)

        if coords is None and intento >= retries - 1:
            coords = _buscar_icono_premium(confidence=0.6)

        if coords:
            x, y = coords
            print(f"[OK] SERVER PREMIUM encontrado en ({x}, {y}) — intento {intento}/{retries}")
            _captura_con_marca("paso_09_premium_encontrado.png", x, y)

            if dry_run:
                print(f"[DRY-RUN] Doble click en ({x}, {y}) — no ejecutado")
                return True

            pyautogui.doubleClick(x, y)
            print(f"[OK] Doble click en SERVER PREMIUM")
            return True

        print(f"  → Ícono no encontrado (intento {intento}/{retries}) — esperando 3s...")
        _captura(f"paso_08_intento_{intento:02d}.png", f"intento {intento} — ícono no encontrado")
        time.sleep(3)

    print("[WARN] SERVER PREMIUM no detectado")
    return False


def _esperar_premium_abierto(timeout_s: int = 30) -> bool:
    import pygetwindow as gw

    print(f"[→] Esperando que Premium cargue (hasta {timeout_s}s)...")
    fin = time.time() + timeout_s

    while time.time() < fin:
        time.sleep(2)
        ventanas = gw.getAllTitles()
        premium = [
            t for t in ventanas
            if any(kw in t.upper() for kw in ("PREMIUM", "SERVER PREMIUM", "SISTEMA"))
            and t not in ("Conexión a Escritorio remoto", "Remote Desktop Connection")
        ]
        if premium:
            print(f"[OK] Premium abierto: '{premium[0]}'")
            return True

    print("[WARN] No se detectó ventana de Premium por título")
    print("       (puede haber abierto dentro del escritorio remoto — ver paso_10)")
    return False


# ------------------------------------------------------------------
# Flujo principal
# ------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Conectar RDP y abrir el sistema SERVER PREMIUM"
    )
    parser.add_argument("--host",       default=os.environ.get("RDP_HOST", ""))
    parser.add_argument("--username",   default=os.environ.get("RDP_USERNAME", ""))
    parser.add_argument("--password",   default=os.environ.get("RDP_PASSWORD", ""))
    parser.add_argument("--timeout",    type=int, default=90,
                        help="Segundos a esperar que cargue el escritorio (default: 90)")
    parser.add_argument("--dry-run",    action="store_true",
                        help="Detectar ícono pero no hacer doble click")
    parser.add_argument("--no-rdp",     action="store_true",
                        help="Omitir paso RDP (asumir sesión ya activa)")
    args = parser.parse_args()

    if not args.no_rdp:
        if not args.host:
            print("[ERROR] Host requerido: --host o RDP_HOST en .env")
            sys.exit(1)
        if not args.username or not args.password:
            print("[ERROR] Credenciales requeridas en .env o como args")
            sys.exit(1)

    # Limpiar capturas anteriores
    import shutil
    if os.path.isdir(_CAPTURAS_DIR):
        shutil.rmtree(_CAPTURAS_DIR)
    os.makedirs(_CAPTURAS_DIR)
    print(f"[→] Capturas en: {_CAPTURAS_DIR}")

    print(f"\n{'='*50}")
    print(f"  PHASE B — Abrir Sistema Premium")
    if not args.no_rdp:
        print(f"  Host: {args.host}  |  Usuario: {args.username}")
    print(f"{'='*50}\n")

    try:
        # Captura 1 — estado inicial
        _captura("paso_01_inicio.png", "pantalla inicial antes de conectar")

        if not args.no_rdp:
            # Limpiar credenciales previas para forzar el diálogo natural de mstsc
            # (cmdkey interfiere con NLA y causa error de autenticación)
            _limpiar_credenciales(args.host)

            # Paso 1: abrir SERVER PREMIUM.rdp del escritorio (mismo archivo que el usuario usa)
            _abrir_rdp(fullscreen=True)
            time.sleep(2)
            _captura("paso_02_mstsc_lanzado.png", "mstsc recién lanzado")

            # Paso 3: esperar conexión (maneja diálogos internamente)
            if not _esperar_escritorio(
                args.host, args.username, args.password, timeout_s=args.timeout
            ):
                print("[ERROR] No se pudo establecer la sesión RDP")
                _captura("error_rdp_fallido.png")
                sys.exit(1)

            # Esperar que el escritorio termine de cargar (Applying user settings...)
            _esperar_escritorio_rdp_listo(timeout_s=90)
            _captura("paso_07_escritorio_rdp.png", "escritorio remoto listo")

        # Paso 4: enfocar ventana RDP
        if not args.no_rdp:
            _enfocar_ventana_rdp(args.host)

        # Paso 5: buscar y abrir SERVER PREMIUM
        if not _abrir_servidor_premium(dry_run=args.dry_run):
            _captura("error_premium_no_encontrado.png")
            print(f"\n[HINT] Revisá las capturas en: {_CAPTURAS_DIR}")
            sys.exit(1)

        if args.dry_run:
            print(f"\n[✓] Dry-run completado. Capturas en: {_CAPTURAS_DIR}")
            return

        # Paso 6: esperar que Premium cargue
        time.sleep(3)
        _esperar_premium_abierto(timeout_s=30)

        # Captura final
        time.sleep(2)
        _captura("paso_10_premium_abierto.png", "estado final")

        print(f"\n[✓] Listo. Revisá las capturas en: {_CAPTURAS_DIR}")
        print(f"    Abrí la carpeta: explorer {_CAPTURAS_DIR}")

    finally:
        pass


if __name__ == "__main__":
    main()
