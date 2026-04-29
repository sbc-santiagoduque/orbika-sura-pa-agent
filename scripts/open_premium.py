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
  paso_11_dialogo_conexion.png    — diálogo "Conexión" de Oracle Forms detectado
  paso_12_usuario_escrito.png     — campo Usuario llenado
  paso_13_password_escrito.png    — campo Contraseña llenado
  paso_14_foco_conectar.png       — foco en botón Conectar
  paso_15_conectar_enviado.png    — click Conectar ejecutado
  paso_16_premium_logueado.png    — pantalla principal de Premium cargada

Uso:
    python scripts/open_premium.py                  # flujo completo
    python scripts/open_premium.py --no-rdp         # RDP ya activo, solo abrir Premium + login
    python scripts/open_premium.py --no-premium     # Premium ya abierto, solo hacer login
    python scripts/open_premium.py --dry-run        # detectar ícono pero sin doble click
    python scripts/open_premium.py --step login     # solo pasos 11-16 (debug de login aislado)

Requisitos:
    - Python corriendo como Administrador (necesario para pywinauto)
    - pip install pyautogui pywinauto pygetwindow pillow pyperclip

Variables de entorno (.env):
    RDP_HOST          IP o hostname del servidor RDP (ej: 172.16.1.77)
    RDP_USERNAME      Usuario Windows (ej: .\\PROYECTO_DMS)
    RDP_PASSWORD      Contraseña Windows
    PREMIUM_USERNAME  Usuario del sistema Premium (Oracle Forms)
    PREMIUM_PASSWORD  Contraseña del sistema Premium

Templates (generar con scripts/crop_premium_templates.py):
    docs/template_premium_conexion.png           — crop del título "Conexión" (login)
    docs/screens/titlebar_oracle_forms.png        — título "Oracle Forms Runtime" (ancla de menú)
    docs/screens/form_consulta_endosos.png        — crop del formulario "Consulta de Endosos"
    docs/screens/campo_no_poliza.png              — crop de la etiqueta "No. de Póliza"
    docs/screens/campo_fecha_siniestro.png        — crop de la etiqueta "Fecha del Siniestro"

Navegación de menú (P1):
    Usa coordenadas absolutas de referencia (p17, 1920x1080) + offset calculado
    localizando titlebar_oracle_forms.png en pantalla. No requiere Alt+flechas.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Deshabilitar failsafe de pyautogui (se dispara si el mouse llega a una esquina).
# En modo autónomo no necesitamos escape de emergencia por movimiento de mouse.
try:
    import pyautogui as _pag
    _pag.FAILSAFE = False
    _pag.PAUSE = 0.0
except ImportError:
    pass

_SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
_DOCS_DIR     = os.path.join(_SCRIPT_DIR, "..", "docs")
_SCREENS_DIR  = os.path.join(_DOCS_DIR, "screens")

_TEMPLATE          = os.path.join(_DOCS_DIR, "template_server_premium.png")
_TEMPLATE_CONEXION = os.path.join(_DOCS_DIR, "template_premium_conexion.png")

# Templates de pantallas Premium (UiPath-style: una imagen por pantalla/elemento)
_T = lambda name: os.path.join(_SCREENS_DIR, name)  # noqa: E731

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

def _rdp_win():
    """
    Retorna la ventana RDP activa via pywinauto.

    Si hay múltiples ventanas con 'Escritorio remoto' (ej: sesión nueva + diálogo
    anterior), prioriza la que contiene RDP_HOST en el título. Fallback: found_index=0.
    """
    from pywinauto import Desktop
    host = os.environ.get("RDP_HOST", "")
    if host:
        try:
            return Desktop(backend="uia").window(title_re=f".*{host}.*", top_level_only=True)
        except Exception:
            pass
    try:
        return Desktop(backend="uia").window(title_re=".*Escritorio remoto.*", top_level_only=True)
    except Exception:
        return Desktop(backend="uia").window(title_re=".*Escritorio remoto.*", found_index=0)


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


def _pegar(texto: str) -> None:
    """Pega texto via portapapeles — soporta @, !, # y cualquier carácter especial."""
    import pyperclip
    import pyautogui
    pyperclip.copy(texto)
    time.sleep(0.15)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.15)



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


def _cerrar_shutdown_tracker() -> bool:
    """
    Detecta y cierra el popup 'Shutdown Event Tracker' si está visible.
    Aparece al conectar RDP cuando el servidor tuvo un cierre inesperado.
    Retorna True si lo encontró y cerró, False si no estaba.
    """
    import pyautogui
    template = Path(_SCREENS_DIR) / "boton_cancel_shutdown.png"
    if not template.exists():
        return False
    try:
        pos = pyautogui.locateCenterOnScreen(str(template), confidence=0.8)
        if pos:
            pyautogui.click(pos)
            time.sleep(0.5)
            print("  → Shutdown Event Tracker cerrado")
            return True
    except Exception:
        pass
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
# Phase B — Pasos 11-16: Login Oracle Forms (diálogo "Conexión")
# ------------------------------------------------------------------

def _buscar_en_pantalla(template_path: str, confidence: float = 0.8):
    """Busca un template en la pantalla. Retorna (cx, cy) o None."""
    import pyautogui
    if not os.path.isfile(template_path):
        return None
    try:
        loc = pyautogui.locateOnScreen(template_path, confidence=confidence)
        if loc:
            c = pyautogui.center(loc)
            return int(c.x), int(c.y)
    except pyautogui.ImageNotFoundException:
        pass
    return None


def _esperar_dialogo_conexion(timeout_s: int = 30) -> bool:
    """
    Paso 11: Espera que aparezca el diálogo 'Conexión' de Oracle Forms.

    Con template (docs/template_premium_conexion.png): busca la imagen en pantalla.
    Sin template: espera estabilidad de pantalla post-apertura de Premium.
    """
    import pyautogui
    import hashlib

    print(f"\n[→] Paso 11 — Esperando diálogo 'Conexión' Oracle Forms (hasta {timeout_s}s)...")
    fin = time.time() + timeout_s

    if os.path.isfile(_TEMPLATE_CONEXION):
        while time.time() < fin:
            coords = _buscar_en_pantalla(_TEMPLATE_CONEXION, confidence=0.75)
            if coords:
                print(f"[OK] Diálogo 'Conexión' detectado en {coords}")
                _captura("paso_11_dialogo_conexion.png", "diálogo Conexión detectado")
                return True
            print("  → Buscando diálogo Conexión...")
            time.sleep(1.5)
    else:
        print("  → Sin template — esperando estabilidad de pantalla")
        print(f"     (Tip: crea docs/template_premium_conexion.png para detección precisa)")
        hash_ant = None
        estables = 0
        while time.time() < fin:
            time.sleep(2)
            img = pyautogui.screenshot()
            h = hashlib.md5(img.tobytes()).hexdigest()
            if h == hash_ant:
                estables += 1
                print(f"  → Pantalla estable ({estables}/2)...")
                if estables >= 2:
                    _captura("paso_11_dialogo_conexion.png", "pantalla estable — diálogo listo")
                    return True
            else:
                estables = 0
                print("  → Pantalla cambiando...")
            hash_ant = h

    print("[WARN] Timeout esperando diálogo 'Conexión'")
    _captura("paso_11_timeout.png", "timeout diálogo Conexión")
    return False


def _completar_login_premium(usuario: str, password: str) -> bool:
    """
    Pasos 12-15: Llena el formulario 'Conexión' de Oracle Forms y ejecuta Conectar.

    Flujo de campos (Tab navigation):
      Usuario → Tab → Contraseña → Tab → Base de datos (vacío) → Tab → Conectar → Enter

    Usa portapapeles para soportar caracteres especiales.
    Si existe docs/template_premium_conexion.png, hace click preciso en el campo Usuario.
    Sin template, hace click en el centro de la pantalla para que Oracle Forms reciba
    el foco de teclado dentro del RDP (el diálogo Conexión ocupa el centro).
    """
    import pyautogui

    print(f"\n[→] Paso 12-15 — Llenando diálogo 'Conexión'...")

    # Enfocar ventana RDP antes de cualquier interacción (igual que pasos 17-30)
    try:
        from pywinauto import Desktop
        rdp = _rdp_win()
        rdp.set_focus()
        time.sleep(0.50)
        print("  → Ventana RDP enfocada")
    except Exception as exc:
        print(f"  [WARN] set_focus RDP: {exc}")

    # Oracle Forms ya posiciona el cursor en el campo Usuario al abrir el
    # diálogo — no se necesita click. Solo asegurar que la ventana RDP tiene
    # el foco (hecho arriba) y escribir directamente.
    time.sleep(0.5)   # dar tiempo a Oracle Forms para renderizar el diálogo

    # Paso 12: Usuario — escribir carácter por carácter (sin clipboard)
    pyautogui.write(usuario, interval=0.05)
    _captura("paso_12_usuario_escrito.png", f"usuario: {usuario}")
    print(f"  → [12] Usuario escrito: {usuario}")

    # Paso 13: Contraseña
    pyautogui.hotkey("tab")
    time.sleep(0.2)
    pyautogui.write(password, interval=0.05)
    _captura("paso_13_password_escrito.png", "contraseña escrita")
    print("  → [13] Contraseña escrita")

    # Paso 14: Base de datos (siempre vacío) → Tab → Tab → foco en Conectar
    pyautogui.hotkey("tab")
    time.sleep(0.15)
    pyautogui.hotkey("tab")
    time.sleep(0.2)
    _captura("paso_14_foco_conectar.png", "foco en botón Conectar")
    print("  → [14] Foco en botón Conectar")

    # Paso 15: Enter = Conectar
    pyautogui.hotkey("enter")
    time.sleep(1.0)
    _captura("paso_15_conectar_enviado.png", "Conectar ejecutado")
    print("  → [15] Conectar ejecutado")

    return True


def _esperar_premium_logueado(timeout_s: int = 30) -> bool:
    """
    Paso 16: Espera que Premium cargue tras el login en Oracle Forms.

    Con template: detecta desaparición del diálogo 'Conexión' como señal de éxito.
    Sin template: espera estabilidad de pantalla.
    """
    import pyautogui
    import hashlib

    print(f"\n[→] Paso 16 — Esperando pantalla principal Premium (hasta {timeout_s}s)...")
    fin = time.time() + timeout_s

    if os.path.isfile(_TEMPLATE_CONEXION):
        while time.time() < fin:
            time.sleep(2)
            if _buscar_en_pantalla(_TEMPLATE_CONEXION, confidence=0.75) is None:
                time.sleep(2)
                _captura("paso_16_premium_logueado.png", "diálogo Conexión cerrado — Premium cargado")
                print("[OK] Login exitoso — pantalla principal de Premium")
                return True
            print("  → Diálogo Conexión aún visible...")
    else:
        hash_ant = None
        estables = 0
        while time.time() < fin:
            time.sleep(2)
            img = pyautogui.screenshot()
            h = hashlib.md5(img.tobytes()).hexdigest()
            if h == hash_ant:
                estables += 1
                if estables >= 3:
                    _captura("paso_16_premium_logueado.png", "pantalla estable post-login")
                    print("[OK] Pantalla estable — Premium cargado")
                    return True
            else:
                estables = 0
                print("  → Pantalla cambiando post-login...")
            hash_ant = h

    print("[WARN] Timeout esperando pantalla principal de Premium")
    _captura("paso_16_timeout.png", "timeout post-login")
    return False


# ------------------------------------------------------------------
# Phase B — P1/P2: Navegación al menú Apertura + Consulta de Endosos
# ------------------------------------------------------------------

# Coordenadas absolutas de cada item de menú en el screenshot de referencia
# docs/screens/p17_menu_apertura.png (1920x1080).
# Medidos con análisis de píxeles azul-resaltado (scan de regiones coloreadas).
# Se usan como fallback si el template matching no encuentra el ítem en pantalla.
_MENU_CLICKS_REF = {
    # (x_center, y_center) en el screenshot de referencia 1920x1080
    "Premium":                (312, 101),   # barra de menú: crop x=265-360, y=88-114
    "1-Reclamos":             (312, 205),   # dropdown de Premium — misma x que Premium, y=4to item
    "1.2-Procesos":           (508, 238),   # submenu: blue region x=468-549, y=225-252
    "1.2.1-Manejo Reclamos":  (620, 239),   # sub-submenu: ajustado (ref era 718, muy a la derecha)
    "1.2.1.1-Apertura":       (900, 238),   # deep submenu: ajustado
    "1.2.1.2-Apertura":       (1100, 238),
}

# Templates (estado resaltado) para cada ítem de menú.
# Se usan como estrategia primaria: hover → highlight → locate → click exacto.
_MENU_TEMPLATES = {
    "Premium":                "menu_premium.png",
    "1-Reclamos":             "menu_1_reclamos.png",
    "1.2-Procesos":           "menu_12_procesos.png",
    "1.2.1-Manejo Reclamos":  "menu_121_manejo.png",
    "1.2.1.1-Apertura":       "menu_1211_apertura.png",
    "1.2.1.2-Apertura":       "menu_1211_apertura.png",   # mismo ítem, distinto x de click
}

# Posición del titlebar en el screenshot de referencia (crop titlebar_oracle_forms.png)
_TITLEBAR_REF = (168, 60)   # (left, top) del crop en la imagen de referencia


def _calcular_offset_ventana() -> tuple[int, int]:
    """
    Localiza el título "Oracle Forms Runtime" en pantalla usando el template
    docs/screens/titlebar_oracle_forms.png y calcula el desplazamiento (dx, dy)
    respecto a la posición de referencia del screenshot p17.

    Retorna (0, 0) si el template no está disponible o no se encuentra,
    lo que hace que los clicks usen las coordenadas absolutas de la referencia.
    """
    import pyautogui

    template = _T("titlebar_oracle_forms.png")
    if not os.path.isfile(template):
        print("  → titlebar_oracle_forms.png no disponible — usando coords de referencia")
        return (0, 0)

    try:
        loc = pyautogui.locateOnScreen(template, confidence=0.70)
        if loc:
            match_left, match_top = int(loc.left), int(loc.top)
            dx = match_left - _TITLEBAR_REF[0]
            dy = match_top  - _TITLEBAR_REF[1]
            print(f"  → Oracle Forms en ({match_left}, {match_top}) — offset ({dx:+d}, {dy:+d})")
            return (dx, dy)
        print("  → Titlebar no encontrado en pantalla — usando coords de referencia")
    except pyautogui.ImageNotFoundException:
        print("  → Titlebar no encontrado — usando coords absolutas de referencia")
    except Exception as exc:
        print(f"  → Error buscando titlebar: {exc}")

    return (0, 0)


def _click_menu(nombre: str, dx: int, dy: int, espera: float = 0.5) -> None:
    """Hace click en un ítem de menú usando coordenadas de referencia + offset de ventana."""
    import pyautogui

    ref_x, ref_y = _MENU_CLICKS_REF[nombre]
    x, y = ref_x + dx, ref_y + dy
    pyautogui.click(x, y)
    print(f"  → Click '{nombre}' ({x}, {y})")
    time.sleep(espera)


def _key(tecla: str, pausa: float = 0.15) -> None:
    """Presiona una tecla y espera. Sin capturas intermedias."""
    import pyautogui
    pyautogui.press(tecla)
    time.sleep(pausa)


def _navegar_apertura_reclamo_clicks() -> bool:
    """
    Paso 17-18: Navega el menú Premium → 1-Reclamos → 1.2-Procesos →
    1.2.1-Manejo Reclamos → 1.2.1.1-Apertura.

    Estrategia de click:
      1. Calcular offset de ventana Oracle Forms (titlebar template).
      2. Click directo en "Premium" en la barra de menú para abrir el dropdown.
      3. Para cada ítem: hover en coordenada aproximada → esperar highlight →
         locateOnScreen con template resaltado → click en posición exacta.
         Si el template no se encuentra, fallback a coordenada + offset.
    """
    import pyautogui

    print("\n[→] Paso 17 — Navegando menu Premium → Apertura de Reclamo...")
    _captura("paso_17_inicio_navegacion.png", "antes de abrir menu")

    dx, dy = _calcular_offset_ventana()

    # ── 1. Foco: click en el titlebar de Oracle Forms ─────────────────────────
    tb_x = _TITLEBAR_REF[0] + dx + 100
    tb_y = _TITLEBAR_REF[1] + dy + 16
    pyautogui.click(tb_x, tb_y)
    time.sleep(0.3)
    print(f"  → Foco Oracle Forms ({tb_x}, {tb_y})")

    # ── 2. Click directo en "Premium" en la barra de menú ────────────────────
    # Evita el problema: Alt activa el menú pero el Right siguiente pierde foco.
    # Un click en el item del menubar abre el dropdown y retiene el foco.
    pm_x = _MENU_CLICKS_REF["Premium"][0] + dx
    pm_y = _MENU_CLICKS_REF["Premium"][1] + dy
    print(f"  → Click en 'Premium' ({pm_x}, {pm_y})")
    pyautogui.click(pm_x, pm_y)
    time.sleep(1.20)   # esperar que abra el dropdown

    # ── 3. Hover-to-navigate con template matching ────────────────────────────
    # Flujo por ítem:
    #   a) Mover mouse a posición aproximada (ref + offset) → activa highlight
    #   b) locateOnScreen con template resaltado → obtener posición exacta
    #   c) Si encontrado: click en centro real | Si no: click en coord aproximada
    def _menu_click(key, label, delay=0.80):
        approx_x = _MENU_CLICKS_REF[key][0] + dx
        approx_y = _MENU_CLICKS_REF[key][1] + dy

        # a) hover para activar highlight
        pyautogui.moveTo(approx_x, approx_y)
        time.sleep(0.35)

        # b) intentar template matching sobre el ítem ya resaltado
        click_x, click_y = approx_x, approx_y
        tpl_file = _T(_MENU_TEMPLATES.get(key, ""))
        if os.path.isfile(tpl_file):
            try:
                loc = pyautogui.locateOnScreen(tpl_file, confidence=0.90)
                if loc:
                    click_x = int(loc.left + loc.width  / 2)
                    click_y = int(loc.top  + loc.height / 2)
                    print(f"  → template '{label}' encontrado en ({click_x}, {click_y})")
                else:
                    print(f"  → template '{label}' no encontrado — usando coord ({approx_x}, {approx_y})")
            except pyautogui.ImageNotFoundException:
                print(f"  → template '{label}' no encontrado — usando coord ({approx_x}, {approx_y})")
            except Exception as exc:
                print(f"  → template '{label}' error ({exc}) — usando coord ({approx_x}, {approx_y})")

        # c) click en posición final
        pyautogui.click(click_x, click_y)
        time.sleep(delay)

    _menu_click("1-Reclamos",            "1-Reclamos")
    _menu_click("1.2-Procesos",          "1.2-Procesos")
    _menu_click("1.2.1-Manejo Reclamos", "1.2.1-Manejo Reclamos")
    _menu_click("1.2.1.1-Apertura",      "1.2.1.1-Apertura")
    _menu_click("1.2.1.2-Apertura",      "1.2.1.1-Apertura", delay=1.20)

    _captura("paso_18_apertura_seleccionada.png", "post-navegacion")
    print("[OK] Navegacion completada — 1.2.1.1-Apertura seleccionado")
    return True


def _navegar_apertura_reclamo() -> bool:
    """
    Alternativa full-teclado usando pywinauto para enviar teclas directo
    a la ventana RDP por handle — sin depender del foco del SO.

    Secuencia:
      {VK_MENU}                  → Alt activa menubar Oracle Forms
      {RIGHT} x_RIGHT_PREMIUM    → llega a "Premium"
      {DOWN}                     → abre dropdown Premium
      {DOWN} x_DOWN_RECLAMOS     → llega a 1-Reclamos
      {RIGHT}                    → abre submenu
      {DOWN} x_DOWN_PROCESOS     → llega a 1.2-Procesos
      {RIGHT}                    → abre submenu
      {DOWN} x_DOWN_MANEJO       → llega a 1.2.1-Manejo Reclamos
      {RIGHT}                    → abre submenu
      {DOWN} x_DOWN_APERTURA     → llega a 1.2.1.1-Apertura
      {ENTER}                    → selecciona
    """
    import pyautogui
    from pywinauto import Desktop

    _RIGHT_PREMIUM  = 1   # Rights desde el 1er item del menubar hasta "Premium"
    _DOWN_RECLAMOS  = 3   # 4to ítem del dropdown → 3 presses
    _DOWN_PROCESOS  = 1   # 2do ítem → 1 press
    _DOWN_MANEJO    = 0   # 1er ítem → ya apuntado
    _DOWN_APERTURA  = 0   # 1er ítem → ya apuntado

    print("\n[→] Paso 17 (teclado pywinauto) — Navegando menu Premium → Apertura...")
    _captura("paso_17_inicio_navegacion.png", "antes de abrir menu (teclado)")

    # Localizar ventana RDP por título
    try:
        rdp = _rdp_win()
        rdp.set_focus()
        time.sleep(0.50)
        print(f"  → Ventana RDP encontrada: '{rdp.window_text()}'")
    except Exception as exc:
        print(f"  [WARN] No se encontró ventana RDP: {exc} — abortando teclado")
        return False

    def _k(keys, n=1, pausa=0.35):
        """Envía teclas directo a la ventana RDP, sin depender del foco."""
        for _ in range(n):
            rdp.type_keys(keys, pause=0.05, with_spaces=True)
            time.sleep(pausa)
            print(f"    {keys}")

    # 1. Click en titlebar — foco inicial para que Oracle Forms esté activo dentro del RDP
    dx, dy = _calcular_offset_ventana()
    tb_x = _TITLEBAR_REF[0] + dx + 100
    tb_y = _TITLEBAR_REF[1] + dy + 16
    print(f"  → Click foco Oracle Forms ({tb_x}, {tb_y})")
    pyautogui.click(tb_x, tb_y)
    time.sleep(0.60)

    # 2. Alt → activa menubar
    print("  → {VK_MENU} — activa menubar")
    _k("{VK_MENU}", pausa=0.60)

    # 3. Right hasta "Premium"
    print(f"  → {{RIGHT}} x{_RIGHT_PREMIUM} — llega a 'Premium'")
    _k("{RIGHT}", _RIGHT_PREMIUM, pausa=0.30)
    time.sleep(0.20)

    # 4. Down → abre dropdown Premium
    print("  → {DOWN} — abre dropdown Premium")
    _k("{DOWN}", pausa=0.60)

    # 5. Down hasta 1-Reclamos
    print(f"  → {{DOWN}} x{_DOWN_RECLAMOS} — llega a '1-Reclamos'")
    _k("{DOWN}", _DOWN_RECLAMOS, pausa=0.25)
    time.sleep(0.20)

    # 6. Right → abre submenu 1-Reclamos
    print("  → {RIGHT} — abre submenu '1-Reclamos'")
    _k("{RIGHT}", pausa=0.60)

    # 7. Down hasta 1.2-Procesos
    print(f"  → {{DOWN}} x{_DOWN_PROCESOS} — llega a '1.2-Procesos'")
    _k("{DOWN}", _DOWN_PROCESOS, pausa=0.25)
    time.sleep(0.20)

    # 8. Right → abre submenu 1.2-Procesos
    print("  → {RIGHT} — abre submenu '1.2-Procesos'")
    _k("{RIGHT}", pausa=0.60)

    # 9. Down hasta 1.2.1-Manejo Reclamos
    if _DOWN_MANEJO:
        print(f"  → {{DOWN}} x{_DOWN_MANEJO} — llega a '1.2.1-Manejo Reclamos'")
        _k("{DOWN}", _DOWN_MANEJO, pausa=0.25)
        time.sleep(0.20)

    # 10. Right → abre submenu 1.2.1-Manejo Reclamos
    print("  → {RIGHT} — abre submenu '1.2.1-Manejo Reclamos'")
    _k("{RIGHT}", pausa=0.60)

    # 11. Down hasta 1.2.1.1-Apertura
    if _DOWN_APERTURA:
        print(f"  → {{DOWN}} x{_DOWN_APERTURA} — llega a '1.2.1.1-Apertura'")
        _k("{DOWN}", _DOWN_APERTURA, pausa=0.25)
        time.sleep(0.20)

    # 12. Enter → selecciona 1.2.1.1-Apertura
    print("  → {ENTER} — selecciona '1.2.1.1-Apertura'")
    _k("{ENTER}", pausa=1.20)

    _captura("paso_18_apertura_seleccionada.png", "post-navegacion teclado")
    print("[OK] Navegacion teclado completada")
    return True


def _esperar_consulta_endosos(timeout_s: int = 15) -> bool:
    """
    Paso 19: Espera que abra el formulario 'Consulta de Endosos REC0001'.

    Con template (docs/screens/form_consulta_endosos.png): detección por imagen.
    Sin template: espera estabilidad de pantalla.
    """
    import pyautogui
    import hashlib

    print(f"\n[→] Paso 19 — Esperando formulario 'Consulta de Endosos' (hasta {timeout_s}s)...")
    fin = time.time() + timeout_s
    template = _T("form_consulta_endosos.png")

    if os.path.isfile(template):
        while time.time() < fin:
            if _buscar_en_pantalla(template, confidence=0.75):
                _captura("paso_19_consulta_endosos.png", "formulario Consulta de Endosos abierto")
                print("[OK] Formulario 'Consulta de Endosos' detectado")
                return True
            time.sleep(1.0)
    else:
        print("  → Sin template — esperando estabilidad de pantalla")
        hash_ant, estables = None, 0
        while time.time() < fin:
            time.sleep(1.5)
            h = hashlib.md5(pyautogui.screenshot().tobytes()).hexdigest()
            if h == hash_ant:
                estables += 1
                if estables >= 2:
                    _captura("paso_19_consulta_endosos.png", "pantalla estable — formulario listo")
                    print("[OK] Pantalla estable — formulario listo")
                    return True
            else:
                estables = 0
            hash_ant = h

    print("[WARN] Timeout esperando 'Consulta de Endosos'")
    _captura("paso_19_timeout.png", "timeout")
    return False


def _ingresar_poliza_y_fecha(numero_poliza: str, fecha_siniestro: str) -> bool:
    """
    Paso 20: Llena 'No. de Póliza' + 'Fecha del Siniestro' y ejecuta F8.

    Usa pywinauto para enviar keystrokes directo a la ventana RDP (mismo
    mecanismo que la navegación de menú), evitando pérdida de foco.

    No. de Póliza: 4 sub-campos separados por Tab ("02" Tab "98" Tab "1246363" Tab "0")
    Fecha del Siniestro: DD/MM/YYYY — _TABS_HASTA_FECHA Tabs después de la póliza.
    F8 ejecuta la consulta.
    """
    from pywinauto import Desktop

    # Tabs desde el último campo de póliza hasta Fecha del Siniestro
    _TABS_HASTA_FECHA = 1   # ajustar si el formulario tiene más/menos campos intermedios

    # Convertir fecha ISO → DD/MM/YYYY
    try:
        from datetime import datetime
        fecha_of = datetime.strptime(fecha_siniestro[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        fecha_of = fecha_siniestro

    partes_poliza = numero_poliza.split("-")  # ["02", "98", "1246363", "0"]

    print(f"\n[→] Paso 20 — Llenando Consulta de Endosos...")
    print(f"  → Póliza: {numero_poliza} ({len(partes_poliza)} partes)")
    print(f"  → Fecha siniestro: {fecha_siniestro} → {fecha_of}")

    # Localizar ventana RDP
    try:
        rdp = _rdp_win()
        rdp.set_focus()
        time.sleep(0.40)
    except Exception as exc:
        print(f"  [WARN] Ventana RDP no encontrada: {exc}")
        return False

    def _k(keys, pausa=0.20):
        rdp.type_keys(keys, pause=0.05, with_spaces=True)
        time.sleep(pausa)
        print(f"    {keys}")

    # Llenar las 4 partes de la póliza — sin ctrl+a, el campo está vacío al abrirse
    for i, parte in enumerate(partes_poliza):
        _k(parte, pausa=0.15)
        _k("{TAB}", pausa=0.20)
        print(f"  → Parte {i+1}: '{parte}'")

    _captura("paso_20_poliza_ingresada.png", f"póliza {numero_poliza} ingresada")

    # Navegar hasta Fecha del Siniestro con Tabs
    print(f"  → {_TABS_HASTA_FECHA} Tabs hasta Fecha del Siniestro")
    for _ in range(_TABS_HASTA_FECHA):
        _k("{TAB}", pausa=0.15)

    # Escribir fecha
    _k(fecha_of, pausa=0.20)
    _captura("paso_20_fecha_ingresada.png", f"fecha {fecha_of} ingresada")
    print(f"  → Fecha: {fecha_of}")

    # F8 — ejecutar consulta
    _k("{F8}", pausa=1.50)
    _captura("paso_21_f8_ejecutado.png", "F8 ejecutado — esperando resultados")
    print("[OK] F8 ejecutado — consulta enviada")

    return True


def _cerrar_popup_forms_si_existe() -> bool:
    """
    Detecta cualquier popup 'Forms' de Oracle Forms (title bar genérico).
    Usa docs/screens/titlebar_forms_modal.png — solo el título 'Forms', sin
    depender del mensaje, por lo que funciona para duplicado, conductor, etc.
    Si está visible, presiona Enter (OK) y retorna True.
    """
    import pyautogui
    template = _T("titlebar_forms_modal.png")
    if not os.path.isfile(template):
        # fallback al template completo si el genérico no existe
        template = _T("modal_ok_forms.png")
        if not os.path.isfile(template):
            return False
    if _buscar_en_pantalla(template, confidence=0.75) is None:
        return False
    _captura("popup_forms_detectado.png", "popup Forms detectado")
    pyautogui.hotkey("enter")
    time.sleep(0.6)
    print("  → Popup Forms cerrado (Enter/OK)")
    return True


def _cerrar_pantalla_automovil_y_endosos() -> None:
    """
    Cierra los dos formularios apilados cuando ocurre 'Siniestro fuera de vigencia':
      1. Consulta de Automóviles Asegurados → X  (primer click)
      2. Posible confirmación Oracle Forms  → Enter
      3. Consulta de Endosos               → X  (segundo click)
    Usa el mismo template titlebar_consulta_endosos.png (botón X genérico MDI).
    """
    import pyautogui

    # -- Cierre 1: Automóviles Asegurados --
    print("  → Cerrando Consulta de Automóviles Asegurados...")
    _cerrar_formulario_consulta_endosos()   # reutiliza el click X

    # Puede aparecer un diálogo de confirmación tras cerrar Automóviles
    time.sleep(0.5)
    if _cerrar_popup_forms_si_existe():
        print("  → Confirmación post-cierre cerrada (Enter)")

    # -- Cierre 2: Consulta de Endosos --
    time.sleep(0.5)
    print("  → Cerrando Consulta de Endosos...")
    _cerrar_formulario_consulta_endosos()


def _cerrar_formulario_consulta_endosos() -> None:
    """
    Cierra el formulario 'Consulta de Endosos' (la pantalla grande) haciendo
    click en su botón X via template docs/screens/titlebar_consulta_endosos.png.
    Fallback: Ctrl+F4.
    """
    import pyautogui
    template = _T("titlebar_consulta_endosos.png")
    if os.path.isfile(template):
        try:
            loc = pyautogui.locateOnScreen(template, confidence=0.80)
            if loc:
                cx = int(loc.left + loc.width  / 2)
                cy = int(loc.top  + loc.height / 2)
                pyautogui.click(cx, cy)
                time.sleep(0.80)
                _captura("consulta_endosos_cerrada.png", "formulario cerrado via X")
                print("  → Formulario Consulta de Endosos cerrado (click X)")
                return
        except Exception as exc:
            print(f"  [WARN] Template X no encontrado: {exc}")

    # Fallback teclado
    try:
        from pywinauto import Desktop
        rdp = _rdp_win()
        rdp.set_focus()
        time.sleep(0.30)
    except Exception:
        pass
    pyautogui.hotkey("ctrl", "f4")
    time.sleep(0.80)
    _captura("consulta_endosos_cerrada.png", "formulario cerrado Ctrl+F4 fallback")
    print("  → Formulario cerrado (Ctrl+F4 fallback)")


def _extraer_datos_automovil() -> dict:
    """
    Paso 23: Captura la pantalla 'Consulta de Automóviles Asegurados' y extrae
    los datos del vehículo via OCR (pytesseract).

    Retorna dict con los campos encontrados, o vacío si OCR no está disponible.
    Los campos exactos a validar se definirán cuando llegue la guía operativa.
    """
    import pyautogui

    _captura("paso_23_consulta_automovil.png", "Consulta de Automóviles Asegurados")

    print("\n[→] Paso 23 — Extrayendo datos del automóvil asegurado...")

    try:
        import pytesseract
        from PIL import Image as PILImage

        img = PILImage.open(
            os.path.join(_CAPTURAS_DIR, "paso_23_consulta_automovil.png")
        )
        texto = pytesseract.image_to_string(img, lang="spa")
        lineas = [l.strip() for l in texto.splitlines() if l.strip()]
        print(f"  → OCR: {len(lineas)} líneas extraídas")
        for linea in lineas:
            print(f"    {linea}")
        print("[OK] Datos automóvil extraídos")
        return {"raw_ocr": texto}

    except (ImportError, Exception) as exc:
        print(f"  [WARN] OCR no disponible ({type(exc).__name__}) — captura guardada, extracción pendiente")
        print("[OK] Captura guardada en paso_23_consulta_automovil.png")
        return {}


def _click_boton_coberturas_auto() -> bool:
    """
    Paso 24: Click en el ícono de coberturas del auto asegurado
    (botón con ícono de auto rojo, esquina superior derecha del formulario).

    Template: docs/screens/boton_coberturas_auto.png
    """
    import pyautogui

    print("\n[→] Paso 24 — Click botón Coberturas del Auto...")
    template = _T("boton_coberturas_auto.png")

    if not os.path.isfile(template):
        print("  [WARN] Template boton_coberturas_auto.png no encontrado — saltando paso")
        return False

    try:
        loc = pyautogui.locateOnScreen(template, confidence=0.80)
        if loc:
            cx = int(loc.left + loc.width  / 2)
            cy = int(loc.top  + loc.height / 2)
            pyautogui.click(cx, cy)
            time.sleep(1.0)
            _captura("paso_24_coberturas_click.png", "botón Coberturas clickeado")
            print(f"  → Botón encontrado y clickeado en ({cx}, {cy})")
            return True
        else:
            print("  [WARN] Botón coberturas no encontrado en pantalla")
    except pyautogui.ImageNotFoundException:
        print("  [WARN] Botón coberturas no encontrado en pantalla")
    except Exception as exc:
        print(f"  [WARN] Error buscando botón coberturas: {exc}")

    return False


def _seleccionar_cobertura_colision_vuelco() -> bool:
    """
    Paso 25: En 'Consulta de Coberturas', navega hasta la fila
    'E - POR COLISIÓN O VUELCO' y click al botón seleccionar (manito).

    La tabla abre con fila A seleccionada — 4 Down llegan a E.
    _DOWNS_HASTA_COLISION: ajustar si el orden de filas cambia.

    Template: docs/screens/boton_seleccionar_cobertura.png
    """
    import pyautogui
    from pywinauto import Desktop

    _DOWNS_HASTA_COLISION = 4   # A→B→C→D→E

    print("\n[→] Paso 25 — Seleccionando cobertura Colisión o Vuelco...")
    _captura("paso_25_inicio_coberturas.png", "Consulta de Coberturas abierta")

    # Navegar con teclado directo a la ventana RDP
    try:
        rdp = _rdp_win()
        rdp.set_focus()
        time.sleep(0.30)
    except Exception as exc:
        print(f"  [WARN] Ventana RDP no encontrada: {exc}")
        return False

    def _k(keys, n=1, pausa=0.25):
        for _ in range(n):
            rdp.type_keys(keys, pause=0.05, with_spaces=True)
            time.sleep(pausa)
            print(f"    {keys}")

    print(f"  → Down x{_DOWNS_HASTA_COLISION} — llega a 'E - POR COLISIÓN O VUELCO'")
    _k("{DOWN}", _DOWNS_HASTA_COLISION)
    time.sleep(0.30)
    _captura("paso_25_fila_colision_seleccionada.png", "fila Colisión o Vuelco activa")

    # Click al botón seleccionar (manito)
    template = _T("boton_seleccionar_cobertura.png")
    if not os.path.isfile(template):
        print("  [WARN] Template boton_seleccionar_cobertura.png no encontrado — saltando click")
        return False

    try:
        loc = pyautogui.locateOnScreen(template, confidence=0.80)
        if loc:
            cx = int(loc.left + loc.width  / 2)
            cy = int(loc.top  + loc.height / 2)
            pyautogui.click(cx, cy)
            time.sleep(1.0)
            _captura("paso_25_cobertura_seleccionada.png", "cobertura seleccionada")
            print(f"  → Botón seleccionar clickeado en ({cx}, {cy})")
            return True
        else:
            print("  [WARN] Botón seleccionar no encontrado en pantalla")
    except pyautogui.ImageNotFoundException:
        print("  [WARN] Botón seleccionar no encontrado en pantalla")
    except Exception as exc:
        print(f"  [WARN] Error buscando botón: {exc}")

    return False


def _llenar_generales_1(tipo_siniestro_codigo: str = "30",
                        descripcion: str = "PRUEBA AUTOMATIZACION",
                        hora_siniestro: str = "10:00",
                        lugar_siniestro: str = "PANAMA") -> bool:
    """
    Paso 26: Llena la pestaña 'Generales (1)' del formulario Apertura del Reclamo.

    Orden obligatorio (Oracle Forms no permite editar fuera de orden):
      1. Fecha de Recibo de Documentos → hoy (DD-MM-YYYY)
      2. Tipo de siniestro → escribir código (ej. "30") + Tab → autocompleta
      3. Descripción del Siniestro → modal abre automáticamente
      4. Hora del siniestro
      5. Lugar del siniestro

    tipo_siniestro_index: posición en la lista (0 = primer ítem).
    Templates: campo_fecha_recibo_docs.png, boton_lov_tipo_siniestro.png,
               campo_descripcion_siniestro.png, campo_hora_siniestro.png,
               campo_lugar_siniestro.png
    """
    import pyautogui
    from pywinauto import Desktop
    from datetime import date

    # Offset en px desde el borde izquierdo de la etiqueta hasta el input
    _OFFSET_INPUT = 200

    hoy = date.today().strftime("%d-%m-%Y")

    print("\n[→] Paso 26 — Llenando Generales (1)...")
    _captura("paso_26_inicio_generales1.png", "Apertura del Reclamo — Generales (1)")

    try:
        rdp = _rdp_win()
        rdp.set_focus()
        time.sleep(0.30)
    except Exception as exc:
        print(f"  [WARN] Ventana RDP no encontrada: {exc}")
        return False

    def _k(keys, n=1, pausa=0.25):
        for _ in range(n):
            rdp.type_keys(keys, pause=0.05, with_spaces=True)
            time.sleep(pausa)

    def _click_label(template_name, offset_x=_OFFSET_INPUT, offset_y=0, label=""):
        """Localiza la etiqueta y clickea offset_x px a su derecha."""
        tpl = _T(template_name)
        if not os.path.isfile(tpl):
            print(f"  [WARN] Template {template_name} no encontrado")
            return False
        try:
            loc = pyautogui.locateOnScreen(tpl, confidence=0.80)
            if loc:
                cx = int(loc.left + offset_x)
                cy = int(loc.top  + loc.height / 2 + offset_y)
                pyautogui.click(cx, cy)
                time.sleep(0.40)
                print(f"  → Click '{label}' ({cx}, {cy})")
                return True
            print(f"  [WARN] Etiqueta '{label}' no encontrada en pantalla")
        except Exception as exc:
            print(f"  [WARN] Error buscando '{label}': {exc}")
        return False

    # ── 1. Fecha de Recibo de Documentos — click en campo + fecha de hoy ─────
    if _click_label("campo_fecha_recibo_docs.png", label="Fecha Recibo Docs"):
        _k(hoy, pausa=0.20)
        _captura("paso_26_fecha_recibo.png", f"Fecha Recibo Documentos: {hoy}")
        print(f"  → Fecha de Recibo: {hoy}")
    else:
        print("  [WARN] Saltando Fecha de Recibo — template no disponible")

    # ── 2. Tipo de siniestro ─────────────────────────────────────────────────
    # Flujo Oracle Forms LOV:
    #   click cuadro → escribir "s" (filtra lista) → Tab (selecciona ítem)
    #   → Tab×2 (foco en Aceptar) → Enter → abre modal Descripción automáticamente
    if _click_label("campo_tipo_siniestro.png", offset_x=130, label="Tipo Siniestro"):
        _k(tipo_siniestro_codigo, pausa=0.40)  # ej. "30" → autocompleta COLISION
        _k("{TAB}", pausa=0.80)       # autocompleta el tipo → abre modal Descripción automáticamente
        _captura("paso_26_tipo_siniestro.png", "tipo de siniestro seleccionado")
        print(f"  → Tipo de siniestro '{tipo_siniestro_codigo}' aceptado")

    # ── 3. Descripción del Siniestro — modal ya abierto automáticamente ──────
    # No hace falta click — el modal abre solo al aceptar el tipo de siniestro.
    # Escribir directo → Tab×2 → Enter (Aceptar tiene foco por defecto)
    _k(descripcion, pausa=0.20)
    _k("{TAB}", pausa=0.30)
    _k("{TAB}", pausa=0.30)
    _k("{ENTER}", pausa=0.60)
    print(f"  → Descripción ingresada: '{descripcion}'")

    _captura("paso_26_descripcion_siniestro.png", "descripción ingresada")

    # ── 4. Hora del siniestro ────────────────────────────────────────────────
    if _click_label("campo_hora_siniestro.png", label="Hora Siniestro"):
        _k(hora_siniestro, pausa=0.20)
        print(f"  → Hora: {hora_siniestro}")

    # ── 5. Lugar del siniestro ───────────────────────────────────────────────
    if _click_label("campo_lugar_siniestro.png", label="Lugar Siniestro"):
        _k(lugar_siniestro, pausa=0.20)
        print(f"  → Lugar: {lugar_siniestro}")

    _captura("paso_26_generales1_completo.png", "Generales (1) completo")
    print("[OK] Generales (1) completado")
    return True


def _llenar_generales_2(cedula: str = "8-123-456",
                        nombre: str = "JUAN",
                        apellido: str = "PEREZ",
                        sexo: str = "M",
                        edad: str = "35",
                        tel_residencial: str = "0",
                        tel_oficina: str = "0",
                        responsabilidad: str = "Culpable",
                        relacion: str = "CONDUCTOR") -> bool:
    """
    Paso 27: Click en pestaña 'Generales (2)' y llena los datos del Conductor.

    Flujo: primer campo es Lugar donde se encuentra, Tab lleva a Nombre.
      Lugar donde se encuentra (click) → Tab →
      Cédula (click) → Enter → [modal si cédula no declarada → Enter] →
      Nombre → Enter → Apellido → Enter →
      Sexo (Left abre en FEMENINO, Up sube a MASCULINO) → Enter →
      Edad → Enter → Tel. Residencial → Enter → Tel. Oficina → Enter →
      Relación → Enter → radio Se Declara (Left si Culpable)

    sexo: "F" → Left+Enter | "M" → Left+Up+Enter | "" → Enter (en blanco)
    responsabilidad: "Inocente" → default | "Culpable" → Left (radio)
    """
    import pyautogui
    import hashlib
    from pywinauto import Desktop

    _OFFSET_INPUT = 200

    print("\n[→] Paso 27 — Generales (2): datos del Conductor...")
    _captura("paso_27_inicio_generales2.png", "antes de click en pestaña Generales (2)")

    try:
        rdp = _rdp_win()
        rdp.set_focus()
        time.sleep(0.30)
    except Exception as exc:
        print(f"  [WARN] Ventana RDP no encontrada: {exc}")
        return False

    def _k(keys, n=1, pausa=0.25):
        for _ in range(n):
            rdp.type_keys(keys, pause=0.05, with_spaces=True)
            time.sleep(pausa)

    def _screenshot_hash():
        return hashlib.md5(pyautogui.screenshot().tobytes()).hexdigest()

    # ── 0. Click en pestaña Generales (2) ────────────────────────────────────
    tab_tpl = _T("tab_generales_2.png")
    if os.path.isfile(tab_tpl):
        try:
            loc = pyautogui.locateOnScreen(tab_tpl, confidence=0.80)
            if loc:
                pyautogui.click(int(loc.left + loc.width / 2), int(loc.top + loc.height / 2))
                time.sleep(0.80)
                print("  → Click pestaña Generales (2)")
            else:
                print("  [WARN] Pestaña Generales (2) no encontrada en pantalla")
        except Exception as exc:
            print(f"  [WARN] Error buscando pestaña: {exc}")
    else:
        print("  [WARN] tab_generales_2.png no disponible")

    _captura("paso_27_generales2_abierto.png", "Generales (2) activo")

    # ── 1. Lugar donde se encuentra → Tab → (queda en Nombre) ────────────────
    lugar_tpl = _T("campo_lugar_conductor.png")
    if os.path.isfile(lugar_tpl):
        try:
            loc = pyautogui.locateOnScreen(lugar_tpl, confidence=0.80)
            if loc:
                pyautogui.click(int(loc.left + _OFFSET_INPUT), int(loc.top + loc.height / 2))
                time.sleep(0.30)
                print("  → Click Lugar donde se encuentra")
            else:
                print("  [WARN] Lugar donde se encuentra no encontrado en pantalla")
        except Exception as exc:
            print(f"  [WARN] campo_lugar_conductor.png: {exc}")
    else:
        print("  [WARN] campo_lugar_conductor.png no disponible — saltando Lugar")
    pyautogui.write("Panama", interval=0.05)
    _k("{TAB}", pausa=0.30)
    print("  → Lugar donde se encuentra: Panama")

    # ── 2. Cédula → Enter → detectar modal por cambio de pantalla ────────────
    cedula_tpl = _T("campo_cedula_conductor.png")
    if os.path.isfile(cedula_tpl):
        try:
            loc = pyautogui.locateOnScreen(cedula_tpl, confidence=0.80)
            if loc:
                pyautogui.click(int(loc.left + _OFFSET_INPUT), int(loc.top + loc.height / 2))
                time.sleep(0.40)
                print(f"  → Click Cédula")
        except Exception as exc:
            print(f"  [WARN] campo_cedula_conductor.png: {exc}")

    _k(cedula, pausa=0.20)
    hash_antes = _screenshot_hash()
    _k("{ENTER}", pausa=0.80)
    hash_despues = _screenshot_hash()

    print(f"  → Cédula: {cedula}")
    if hash_antes != hash_despues:
        # Pantalla cambió → modal "El Conductor no ha sido declarado en la Póliza"
        _k("{ENTER}", pausa=0.50)
        print("  → Modal cédula detectado — Enter para cerrar")
    _captura("paso_27_cedula.png", "cédula ingresada")

    # ── 3. Nombre → Enter ─────────────────────────────────────────────────────
    _k(nombre, pausa=0.20)
    _k("{ENTER}", pausa=0.30)
    print(f"  → Nombre: {nombre}")

    # ── 4. Apellido → Enter ───────────────────────────────────────────────────
    _k(apellido, pausa=0.20)
    _k("{ENTER}", pausa=0.30)
    print(f"  → Apellido: {apellido}")

    # ── 5. Sexo — Left abre dropdown en FEMENINO, Up sube a MASCULINO ─────────
    # Right abre el dropdown. Luego Up navega: Up×1=FEMENINO, Up×2=MASCULINO.
    if sexo.upper() == "F":
        _k("{RIGHT}", pausa=0.30)   # abre dropdown
        _k("{UP}",    pausa=0.20)   # → FEMENINO
        _k("{ENTER}", pausa=0.20)   # selecciona
        _k("{ENTER}", pausa=0.30)   # avanza al siguiente campo
        print("  → Sexo: FEMENINO")
    elif sexo.upper() == "M":
        _k("{RIGHT}", pausa=0.30)   # abre dropdown
        _k("{UP}",    pausa=0.20)   # → FEMENINO
        _k("{UP}",    pausa=0.20)   # → MASCULINO
        _k("{ENTER}", pausa=0.20)   # selecciona
        _k("{ENTER}", pausa=0.30)   # avanza al siguiente campo
        print("  → Sexo: MASCULINO")
    else:
        _k("{ENTER}", pausa=0.30)   # en blanco, avanza
        print("  → Sexo: en blanco")

    # ── 6. Edad → Enter ───────────────────────────────────────────────────────
    _k(str(edad), pausa=0.20)
    _k("{ENTER}", pausa=0.30)
    print(f"  → Edad: {edad}")

    # ── 7. Teléfono Residencial → Enter ───────────────────────────────────────
    _k(tel_residencial, pausa=0.20)
    _k("{ENTER}", pausa=0.30)
    print(f"  → Tel. Residencial: {tel_residencial}")

    # ── 8. Teléfono Oficina → Enter ───────────────────────────────────────────
    _k(tel_oficina, pausa=0.20)
    _k("{ENTER}", pausa=0.30)
    print(f"  → Tel. Oficina: {tel_oficina}")

    # ── 9. Relación con el Asegurado → Enter → radio Se Declara ──────────────
    _k(relacion, pausa=0.20)
    _k("{ENTER}", pausa=0.40)
    print(f"  → Relación: {relacion}")

    # ── 10. Se Declara — Inocente es default, Left cambia a Culpable ───────────
    if responsabilidad == "Culpable":
        _k("{LEFT}", pausa=0.30)
        print("  → Se Declara: Culpable")
    else:
        print("  → Se Declara: Inocente (default)")

    _captura("paso_27_generales2_completo.png", "Generales (2) completo")
    print("[OK] Generales (2) completado")
    return True


def _click_boton_consultar_unidades() -> bool:
    """
    Paso 22: Click en el botón 'Consultar Unidades' (ícono a la derecha de
    No. de Póliza de Referencia). Usa template matching sobre el ícono.

    Template: docs/screens/boton_consultar_unidades.png
    """
    import pyautogui

    print("\n[→] Paso 22 — Click botón Consultar Unidades...")
    template = _T("boton_consultar_unidades.png")

    if not os.path.isfile(template):
        print("  [WARN] Template boton_consultar_unidades.png no encontrado — saltando paso")
        return False

    try:
        loc = pyautogui.locateOnScreen(template, confidence=0.80)
        if loc:
            cx = int(loc.left + loc.width  / 2)
            cy = int(loc.top  + loc.height / 2)
            pyautogui.click(cx, cy)
            time.sleep(1.0)
            _captura("paso_22_boton_consultar_click.png", "botón Consultar Unidades clickeado")
            print(f"  → Botón encontrado y clickeado en ({cx}, {cy})")
            return True
        else:
            print("  [WARN] Botón no encontrado en pantalla")
    except pyautogui.ImageNotFoundException:
        print("  [WARN] Botón no encontrado en pantalla")
    except Exception as exc:
        print(f"  [WARN] Error buscando botón: {exc}")

    return False


def _llenar_generales_3(descripcion_danos: str = "PRUEBA DESCRIPCION DANOS",
                        ajustador_interno: str = "158") -> bool:
    """
    Paso 28: Click en pestaña 'Generales (3)' y llena Descripción de daños + Ajustador Interno.

    Flujo:
      1. Click tab Generales (3)
      2. Click campo Descripción de daños → modal abre automáticamente
         → escribir → Tab×2 → Enter (Aceptar)
      3. Click campo Ajustador Interno → escribir código → Enter
    """
    import pyautogui
    from pywinauto import Desktop

    _OFFSET_INPUT = 200

    print("\n[→] Paso 28 — Generales (3): descripción de daños + ajustador...")
    _captura("paso_28_inicio_generales3.png", "antes de click en pestaña Generales (3)")

    try:
        rdp = _rdp_win()
        rdp.set_focus()
        time.sleep(0.30)
    except Exception as exc:
        print(f"  [WARN] Ventana RDP no encontrada: {exc}")
        return False

    def _k(keys, n=1, pausa=0.25):
        for _ in range(n):
            rdp.type_keys(keys, pause=0.05, with_spaces=True)
            time.sleep(pausa)

    def _click_label(template_name, offset_x=_OFFSET_INPUT, offset_y=0, label=""):
        tpl = _T(template_name)
        if not os.path.isfile(tpl):
            print(f"  [WARN] Template {template_name} no encontrado")
            return False
        try:
            loc = pyautogui.locateOnScreen(tpl, confidence=0.80)
            if loc:
                cx = int(loc.left + offset_x)
                cy = int(loc.top  + loc.height / 2 + offset_y)
                pyautogui.click(cx, cy)
                time.sleep(0.40)
                print(f"  → Click '{label}' ({cx}, {cy})")
                return True
            print(f"  [WARN] '{label}' no encontrado en pantalla")
        except Exception as exc:
            print(f"  [WARN] Error buscando '{label}': {exc}")
        return False

    # ── 0. Click pestaña Generales (3) ───────────────────────────────────────
    # Usa tab_generales_2.png como ancla y desplaza un ancho de pestaña a la derecha,
    # evitando confusión entre tabs visualmente similares.
    tab2_tpl = _T("tab_generales_2.png")
    if os.path.isfile(tab2_tpl):
        try:
            loc = pyautogui.locateOnScreen(tab2_tpl, confidence=0.85)
            if loc:
                # Generales (3) está una pestaña a la derecha de Generales (2)
                cx = int(loc.left + loc.width * 2.5)
                cy = int(loc.top  + loc.height / 2)
                pyautogui.click(cx, cy)
                time.sleep(0.80)
                print(f"  → Click pestaña Generales (3) via offset desde G2 ({cx}, {cy})")
            else:
                print("  [WARN] tab_generales_2.png no encontrado — no se pudo navegar a G3")
        except Exception as exc:
            print(f"  [WARN] Error buscando pestaña: {exc}")

    _captura("paso_28_generales3_abierto.png", "Generales (3) activo")

    # ── 1. Descripción de daños → modal → Tab×2 → Enter ──────────────────────
    if _click_label("campo_descripcion_danos.png", label="Descripción de daños"):
        time.sleep(0.30)
        _k(descripcion_danos, pausa=0.20)
        _k("{TAB}", pausa=0.20)
        _k("{TAB}", pausa=0.20)
        _k("{ENTER}", pausa=0.60)
        _captura("paso_28_descripcion_danos.png", "descripción de daños ingresada")
        print(f"  → Descripción de daños: '{descripcion_danos}'")

    # ── 2. Ajustador Interno → código → Enter ─────────────────────────────────
    if _click_label("campo_ajustador_interno.png", offset_x=100, offset_y=-8, label="Ajustador Interno"):
        _k(ajustador_interno, pausa=0.20)
        _k("{ENTER}", pausa=0.50)
        _captura("paso_28_ajustador.png", f"ajustador interno {ajustador_interno}")
        print(f"  → Ajustador Interno: {ajustador_interno}")

    _captura("paso_28_generales3_completo.png", "Generales (3) completo")
    print("[OK] Generales (3) completado")
    return True


def _llenar_reservas(cobertura_codigo: str = "E",
                     monto_reserva: str = "1300") -> bool:
    """
    Paso 29: Click en pestaña 'Reservas' y llena la primera fila de la tabla.

    Flujo:
      1. Click tab Reservas
      2. Click primera celda columna Cobertura → escribir código → Enter
      3. Escribir monto de reserva → parar (no guardar — eso crearía el reclamo real)

    Códigos de cobertura: E=COLISION/VUELCO, HUR=HURTO, INC=INCENDIO,
                          D=COMPRENSIVO, B=DAÑOS PROPIEDAD AJENA
    """
    import pyautogui
    from pywinauto import Desktop

    print("\n[→] Paso 29 — Reservas: cobertura + monto...")
    _captura("paso_29_inicio_reservas.png", "antes de click en pestaña Reservas")

    try:
        rdp = _rdp_win()
        rdp.set_focus()
        time.sleep(0.30)
    except Exception as exc:
        print(f"  [WARN] Ventana RDP no encontrada: {exc}")
        return False

    def _k(keys, n=1, pausa=0.25):
        for _ in range(n):
            rdp.type_keys(keys, pause=0.05, with_spaces=True)
            time.sleep(pausa)

    # ── 0. Click pestaña Reservas ─────────────────────────────────────────────
    tab_tpl = _T("tab_reservas.png")
    if os.path.isfile(tab_tpl):
        try:
            loc = pyautogui.locateOnScreen(tab_tpl, confidence=0.85)
            if loc:
                pyautogui.click(int(loc.left + loc.width / 2), int(loc.top + loc.height / 2))
                time.sleep(0.80)
                print("  → Click pestaña Reservas")
            else:
                print("  [WARN] Pestaña Reservas no encontrada (confidence 0.85)")
        except pyautogui.ImageNotFoundException:
            print("  [WARN] Pestaña Reservas no encontrada en pantalla")
        except Exception as exc:
            print(f"  [WARN] Error buscando pestaña Reservas: {exc}")
    else:
        print("  [WARN] tab_reservas.png no disponible")

    _captura("paso_29_reservas_abierto.png", "pestaña Reservas activa")

    # ── 1. Primera celda columna Cobertura ────────────────────────────────────
    col_tpl = _T("col_cobertura_reservas.png")
    if os.path.isfile(col_tpl):
        try:
            loc = pyautogui.locateOnScreen(col_tpl, confidence=0.80)
            if loc:
                cx = int(loc.left + loc.width / 2)
                cy = int(loc.top  + loc.height * 1.2)  # justo debajo del encabezado
                pyautogui.click(cx, cy)
                time.sleep(0.80)
                _captura("paso_29_celda_cobertura.png", "celda Cobertura clickeada")
                print(f"  → Click primera celda Cobertura ({cx}, {cy})")
                time.sleep(0.60)
                _k(cobertura_codigo, pausa=0.30)
                time.sleep(0.60)
                _captura("paso_29_codigo_escrito.png", f"código '{cobertura_codigo}' escrito")
                _k("{ENTER}", pausa=0.80)
                _captura("paso_29_cobertura.png", f"cobertura '{cobertura_codigo}' ingresada")
                print(f"  → Cobertura: {cobertura_codigo}")
            else:
                print("  [WARN] Encabezado Cobertura no encontrado (confidence 0.80)")
        except pyautogui.ImageNotFoundException:
            print("  [WARN] Encabezado Cobertura no encontrado en pantalla")
        except Exception as exc:
            print(f"  [WARN] Error buscando columna Cobertura: {exc}")
    else:
        print("  [WARN] col_cobertura_reservas.png no disponible")

    # ── 2. Monto de Reserva ───────────────────────────────────────────────────
    time.sleep(0.60)
    _k(monto_reserva, pausa=0.30)
    time.sleep(0.60)
    _captura("paso_29_monto_reserva.png", f"monto {monto_reserva} ingresado — listo para guardar")
    print(f"  → Monto de Reserva: {monto_reserva}")

    print("[OK] Reservas completado")
    return True


def _guardar_reclamo() -> str | None:
    """
    Paso 30: Guarda el reclamo y extrae el número generado.

    ⚠️  CREA UN RECLAMO REAL — solo ejecutar con --guardar.

    Flujo:
      1. Enter — confirma el monto y avanza
      2. {VK_MENU}{DOWN}{ENTER} via pywinauto — activa toolbar → baja al disquete → Enter
      3. Espera que el formulario regrese a Generales (1)
      4. Click en Generales (1) — offset a la izquierda de tab_generales_2.png
      5. OCR del área "No. de Reclamo" relativa al titlebar de Oracle Forms
      6. Retorna el número de reclamo como string, o None si no se pudo leer
    """
    import pyautogui
    from pywinauto import Desktop

    print("\n[→] Paso 30 — GUARDANDO RECLAMO...")

    try:
        rdp = _rdp_win()
        rdp.set_focus()
        time.sleep(0.40)
    except Exception as exc:
        print(f"  [WARN] Ventana RDP no encontrada: {exc}")
        return None

    def _k(keys, n=1, pausa=0.40):
        for _ in range(n):
            rdp.type_keys(keys, pause=0.05, with_spaces=True)
            time.sleep(pausa)

    # ── 1. Enter — confirma monto ─────────────────────────────────────────────
    _k("{ENTER}", pausa=0.80)
    _captura("paso_30_monto_confirmado.png", "monto confirmado")

    # ── 2. Guardar via toolbar — Alt activa menubar, Down baja al disquete, Enter ──
    print("  → Guardando via toolbar (Alt+Down+Enter)...")
    _k("{VK_MENU}", pausa=0.60)   # activa toolbar Oracle Forms
    _k("{DOWN}",    pausa=0.60)   # selecciona disquete (primer ítem activo)
    _k("{ENTER}",   pausa=2.00)   # guarda — esperar que Oracle Forms procese
    _captura("paso_30_guardado.png", "post-guardar")

    # ── 2.5. Detectar popup "reclamo ya creado" ───────────────────────────────
    # Si el formulario de Apertura (pestaña G2) sigue visible 1.5s después de
    # guardar, un diálogo bloqueante impidió el guardado.
    time.sleep(1.00)
    tab2_tpl = _T("tab_generales_2.png")
    if os.path.isfile(tab2_tpl):
        try:
            loc_g2 = pyautogui.locateOnScreen(tab2_tpl, confidence=0.85)
            if loc_g2:
                _captura("paso_30_dialog_reclamo_existente.png",
                         "pestaña G2 visible post-guardado — posible reclamo ya existente")
                _k("{ESC}", pausa=0.60)
                raise ReclamoExistenteError(
                    "El formulario de Apertura sigue activo tras guardar "
                    "— el reclamo probablemente ya existe en esta póliza"
                )
        except pyautogui.ImageNotFoundException:
            pass  # G2 no encontrado → guardado exitoso, formulario avanzó
        except ReclamoExistenteError:
            raise
        except Exception as exc:
            print(f"  [WARN] Error en detección de reclamo existente: {exc}")

    print("  → Reclamo guardado")

    # ── 3. Volver a Generales (1) — offset izquierdo desde tab_generales_2 ────
    tab2_tpl = _T("tab_generales_2.png")
    if os.path.isfile(tab2_tpl):
        try:
            loc = pyautogui.locateOnScreen(tab2_tpl, confidence=0.85)
            if loc:
                cx = int(loc.left - loc.width * 0.5)   # una pestaña a la izquierda
                cy = int(loc.top  + loc.height / 2)
                pyautogui.click(cx, cy)
                time.sleep(0.80)
                print(f"  → Click Generales (1) ({cx}, {cy})")
        except pyautogui.ImageNotFoundException:
            print("  [WARN] tab_generales_2.png no encontrado — no se pudo ir a G1")
        except Exception as exc:
            print(f"  [WARN] Error navegando a G1: {exc}")

    _captura("paso_30_generales1.png", "Generales (1) post-guardado")

    # ── 4. OCR del área "No. de Reclamo" ──────────────────────────────────────
    numero_reclamo = None
    crop_path = _crop_zona_no_reclamo("paso_30_no_reclamo_crop.png")
    if crop_path:
        try:
            from PIL import Image as _PILImage
            img = _PILImage.open(crop_path)
            import pytesseract
            texto = pytesseract.image_to_string(img, config="--psm 7 digits").strip()
            numero_reclamo = texto.replace(" ", "-") if texto else None
            print(f"  → No. de Reclamo (OCR): {numero_reclamo}")
        except Exception:
            print("  [WARN] OCR no disponible — crop guardado en paso_30_no_reclamo_crop.png")

    _captura("paso_30_completo.png", f"reclamo {numero_reclamo} generado")
    print(f"[OK] Reclamo guardado — No. de Reclamo: {numero_reclamo}")
    return numero_reclamo


# ------------------------------------------------------------------
# Simulación de guardar (calibración OCR sin reclamo real)
# ------------------------------------------------------------------

def _cerrar_modal_no() -> bool:
    """
    Si hay un modal Oracle Forms visible (titlebar_forms_modal.png), presiona
    Tab+Enter para seleccionar el botón 'No' (el foco por defecto está en 'Si').
    Retorna True si se detectó y cerró el modal.
    """
    template = _T("titlebar_forms_modal.png")
    fallback = _T("modal_ok_forms.png")
    tpl = template if os.path.isfile(template) else (fallback if os.path.isfile(fallback) else None)
    if tpl is None:
        return False
    if _buscar_en_pantalla(tpl, confidence=0.75) is None:
        return False

    _captura("modal_guardar_detectado.png", "modal guardar detectado")
    try:
        from pywinauto import Desktop
        rdp = _rdp_win()
        rdp.set_focus()
        time.sleep(0.20)
        rdp.type_keys("{TAB}", pause=0.05, with_spaces=True)   # Si → No
        time.sleep(0.20)
        rdp.type_keys("{ENTER}", pause=0.05, with_spaces=True)
        time.sleep(0.50)
    except Exception as exc:
        import pyautogui as _pag_modal
        print(f"  [WARN] pywinauto no disponible para modal No: {exc} — usando Tab+Enter pyautogui")
        _pag_modal.hotkey("tab")
        time.sleep(0.15)
        _pag_modal.hotkey("enter")
        time.sleep(0.50)

    print("  → Modal cerrado con 'No' (Tab+Enter)")
    return True


def _en_menu_principal() -> bool:
    """
    Retorna True si menu_1_reclamos.png es visible — señal de que Oracle Forms
    está en la pantalla principal (menú de reclamos accesible).
    """
    import pyautogui
    tpl = _T("menu_1_reclamos.png")
    if not os.path.isfile(tpl):
        return False
    try:
        return pyautogui.locateOnScreen(tpl, confidence=0.80) is not None
    except pyautogui.ImageNotFoundException:
        return False
    except Exception:
        return False


def _cerrar_reclamo_y_volver_inicio() -> None:
    """
    Cierra los formularios MDI apilados (reclamo, Coberturas, Automóviles,
    Endosos) vía botón X hasta detectar la pantalla principal con
    menu_1_reclamos.png. Máx 10 intentos como seguro.

    Por cada cierre:
      1. Click X (via _cerrar_formulario_consulta_endosos)
      2. Si aparece modal "¿Guardar?" → Tab+Enter (No)
      3. Verificar si menu_1_reclamos.png ya es visible → si sí, parar
    """
    _MAX = 10

    print("\n[→] Cerrando formularios — volviendo a pantalla principal...")

    for intento in range(1, _MAX + 1):
        if _en_menu_principal():
            print(f"  → Menú principal detectado — ya en pantalla inicial (intento {intento})")
            break

        print(f"  → Cerrando MDI {intento}...")
        _cerrar_formulario_consulta_endosos()
        time.sleep(0.60)
        _captura(f"paso_cierre_{intento:02d}.png", f"cierre MDI {intento}")

        if _cerrar_modal_no():
            time.sleep(0.25)
            _captura(f"paso_cierre_{intento:02d}b_post_no.png", f"post-modal No ({intento})")
    else:
        print(f"  [WARN] Se alcanzó el máximo de {_MAX} cierres sin detectar menú principal")

    _captura("paso_cierre_pantalla_principal.png", "pantalla principal Oracle Forms")
    print("[OK] Vuelto a pantalla principal — listo para siguiente caso")


def _crop_zona_no_reclamo(nombre_archivo: str) -> str | None:
    """
    Localiza el campo 'No. de Reclamo' en pantalla y guarda un crop del valor.

    Estrategia 1 (preferida): template matching del label 'label_no_reclamo.png'.
      El número está en el campo inmediatamente a la derecha del label.
      Crop: desde el borde derecho del label hasta +250px, misma altura.

    Estrategia 2 (fallback): coordenadas fijas relativas al titlebar.
      Válido solo si la referencia p17 (1920×1080) coincide con la pantalla actual.

    Retorna la ruta del crop guardado, o None si no se pudo capturar.
    """
    import pyautogui

    crop_path = os.path.join(_CAPTURAS_DIR, nombre_archivo)
    label_tpl = _T("label_no_reclamo.png")

    # Estrategia 1: label como ancla
    if os.path.isfile(label_tpl):
        for conf in (0.85, 0.75, 0.65):
            try:
                loc = pyautogui.locateOnScreen(label_tpl, confidence=conf)
                if loc and loc.left > 0:
                    # El valor está debajo del label — mismo x, 200px de ancho, ~30px de alto
                    vx1 = int(loc.left)
                    vy1 = int(loc.top + loc.height) + 2
                    vx2 = vx1 + 200
                    vy2 = vy1 + 30
                    img = pyautogui.screenshot(region=(vx1, vy1, vx2 - vx1, vy2 - vy1))
                    img.save(crop_path)
                    print(f"  → Crop 'No. de Reclamo' via label (conf={conf}): ({vx1},{vy1})→({vx2},{vy2})")
                    print(f"     Guardado: {crop_path}")
                    return crop_path
            except pyautogui.ImageNotFoundException:
                pass
            except Exception as exc:
                print(f"  [WARN] Error buscando label_no_reclamo (conf={conf}): {exc}")
        print("  [WARN] label_no_reclamo.png no encontrado en pantalla")

    # Estrategia 2: offset fijo desde titlebar
    loc_tb = _localizar_titlebar()
    if loc_tb:
        dx  = int(loc_tb.left) - _TITLEBAR_REF[0]
        dy  = int(loc_tb.top)  - _TITLEBAR_REF[1]
        rx1 = 168 + dx
        ry1 = 240 + dy
        rx2 = 420 + dx
        ry2 = 265 + dy
        img = pyautogui.screenshot(region=(rx1, ry1, rx2 - rx1, ry2 - ry1))
        img.save(crop_path)
        print(f"  → Crop 'No. de Reclamo' via titlebar offset: ({rx1},{ry1})→({rx2},{ry2})")
        print(f"     Guardado: {crop_path}")
        if not os.path.isfile(label_tpl):
            print("     [NOTA] Crea label_no_reclamo.png para mayor precisión")
        return crop_path

    print("  [WARN] No se pudo calcular zona 'No. de Reclamo' — ni label ni titlebar disponibles")
    return None


def _localizar_titlebar() -> tuple | None:
    """
    Localiza titlebar_oracle_forms.png con umbral descendente (0.70 → 0.50).
    Retorna el Box de pyautogui o None si no se encuentra.
    """
    import pyautogui
    tpl = _T("titlebar_oracle_forms.png")
    if not os.path.isfile(tpl):
        return None
    for conf in (0.70, 0.60, 0.55, 0.50):
        try:
            loc = pyautogui.locateOnScreen(tpl, confidence=conf)
            if loc:
                print(f"  → Titlebar encontrado (confidence={conf}): ({int(loc.left)}, {int(loc.top)})")
                return loc
        except pyautogui.ImageNotFoundException:
            pass
        except Exception:
            pass
    print("  [WARN] titlebar_oracle_forms.png no encontrado en ningún umbral (0.70–0.50)")
    return None


def _simular_guardar() -> None:
    """
    Simula el paso de guardar para calibrar el OCR del No. de Reclamo.

    - NO presiona Enter (el monto queda sin confirmar — no se crea nada)
    - Escape para salir del campo monto sin activar nada
    - Click en Generales (2) → luego offset izquierdo a Generales (1)
      (desde Reservas, G2 puede no ser visible — primero volvemos al formulario)
    - Toma el crop exacto de la zona OCR del "No. de Reclamo" para inspección visual
    """
    import pyautogui

    print("\n[→] Simulación guardar — calibrando OCR (sin reclamo real)...")

    try:
        from pywinauto import Desktop
        rdp = _rdp_win()
        rdp.set_focus()
        time.sleep(0.40)
    except Exception as exc:
        print(f"  [WARN] Ventana RDP no encontrada: {exc}")
        return

    def _k(keys, pausa=0.40):
        rdp.type_keys(keys, pause=0.05, with_spaces=True)
        time.sleep(pausa)

    # ── 1. Enter confirma monto → Alt activa toolbar → Down selecciona disquete
    #       → ESC cancela sin guardar
    print("  → Enter (confirma monto)...")
    _k("{ENTER}", pausa=0.80)
    _captura("paso_sim_01a_monto_confirmado.png", "monto confirmado")

    print("  → Alt (activa toolbar Oracle Forms)...")
    _k("{VK_MENU}", pausa=0.60)
    _captura("paso_sim_01b_toolbar_activa.png", "toolbar activada")

    print("  → Down (selecciona disquete)...")
    _k("{DOWN}", pausa=0.60)
    _captura("paso_sim_01c_disquete_seleccionado.png", "disquete seleccionado")

    print("  → ESC (cancela sin guardar)...")
    _k("{ESC}", pausa=0.60)
    _captura("paso_sim_01d_cancelado.png", "ESC — guardado cancelado sin reclamo")
    print("  → Secuencia Alt+Down+ESC completada — toolbar cerrada sin guardar")

    # ── 2. Re-focusear Oracle Forms y navegar a Generales (1) ────────────────
    # Tras ESC del toolbar, la ventana puede perder foco.
    # Usamos el titlebar como ancla para hacer click en el área de contenido
    # y así re-focusear antes de buscar las pestañas.
    tab2_tpl = _T("tab_generales_2.png")
    res_tpl  = _T("tab_reservas.png")

    # Re-focusear: click en el área de contenido de Oracle Forms
    loc_tb_focus = _localizar_titlebar()
    if loc_tb_focus:
        fx = int(loc_tb_focus.left + loc_tb_focus.width / 2)
        fy = int(loc_tb_focus.top  + loc_tb_focus.height + 80)  # 80px bajo el titlebar
        pyautogui.click(fx, fy)
        time.sleep(0.60)
        print(f"  → Re-foco Oracle Forms ({fx}, {fy})")
        _captura("paso_sim_02a_refoco.png", "Oracle Forms re-focuseado")

    # Buscar tab G2 con umbrales descendentes; exigir x > 100 para descartar falsos
    g1_ok = False
    for conf in (0.85, 0.75, 0.65):
        try:
            loc = pyautogui.locateOnScreen(tab2_tpl, confidence=conf)
            if loc and loc.left > 100:
                cx = int(loc.left - loc.width * 0.5)
                cy = int(loc.top  + loc.height / 2)
                pyautogui.click(cx, cy)
                time.sleep(0.80)
                print(f"  → Click Generales (1) via offset G2 (conf={conf}) ({cx}, {cy})")
                g1_ok = True
                break
            elif loc:
                print(f"  [SKIP] G2 encontrado en x={int(loc.left)} (< 100) con conf={conf} — posible falso positivo")
        except pyautogui.ImageNotFoundException:
            pass
        except Exception as exc:
            print(f"  [WARN] Error buscando G2 (conf={conf}): {exc}")

    if not g1_ok:
        # Fallback: tab_reservas como ancla — G1 está ~4 anchos de pestaña a la izq.
        for conf in (0.85, 0.75, 0.65):
            try:
                loc_r = pyautogui.locateOnScreen(res_tpl, confidence=conf)
                if loc_r and loc_r.left > 100:
                    cx = int(loc_r.left - loc_r.width * 4)
                    cy = int(loc_r.top  + loc_r.height / 2)
                    if cx > 50:
                        pyautogui.click(cx, cy)
                        time.sleep(0.80)
                        print(f"  → Click Generales (1) via offset Reservas (conf={conf}) ({cx}, {cy})")
                        g1_ok = True
                        break
            except pyautogui.ImageNotFoundException:
                pass
            except Exception as exc:
                print(f"  [WARN] Error buscando Reservas (conf={conf}): {exc}")

    if not g1_ok:
        print("  [WARN] No se pudo navegar a G1 — captura del estado actual")

    _captura("paso_sim_02_generales1.png", "estado tras navegar a G1")

    # ── 3. Captura completa de pantalla para referencia / para cropear template ─
    _captura("paso_sim_03_contexto_g1_completo.png", "pantalla completa G1 referencia OCR")

    # ── 4. Crop zona "No. de Reclamo" usando label como ancla ────────────────
    _crop_zona_no_reclamo("paso_sim_04_zona_ocr_reclamo.png")

    print("[OK] Simulación completada — sin reclamo creado")
    print(f"     Revisar capturas en: {_CAPTURAS_DIR}")
    print("      · paso_sim_03_contexto_g1_completo.png — pantalla completa G1")
    print("      · paso_sim_04_zona_ocr_reclamo.png     — crop campo No. de Reclamo")
    if not os.path.isfile(_T("label_no_reclamo.png")):
        print()
        print("  [PRÓXIMO PASO] Crear template del label:")
        print("    1. Abre paso_sim_03_contexto_g1_completo.png")
        print("    2. Recorta solo el texto 'No. de Reclamo' (sin el campo)")
        print(f"    3. Guarda como: {_T('label_no_reclamo.png')}")


# ------------------------------------------------------------------
# Excepciones de negocio
# ------------------------------------------------------------------

class ReclamoExistenteError(Exception):
    """El formulario detectó que ya existe un reclamo para esta póliza/expediente."""


class ReclamoDuplicadoError(Exception):
    """
    Oracle Forms advirtió 'Existe un reclamo para esta póliza con la misma fecha
    de siniestro' en la Consulta de Endosos, antes de abrir el formulario.
    El caso debe saltarse — no crear un reclamo duplicado.
    """


class SiniestroFueraVigenciaError(Exception):
    """
    Oracle Forms advirtió 'El siniestro ha ocurrido fuera de la vigencia del
    automóvil' en la Consulta de Automóviles Asegurados.
    Requiere revisión manual — la fecha del siniestro no cae dentro de ningún
    endoso vigente para este vehículo.
    """


class NoAutorizadoError(Exception):
    """
    Oracle Forms mostró un modal de 'no autorizado' al intentar guardar.
    El usuario activo no tiene permisos para crear reclamos.
    Requiere revisión manual o cambio de usuario.
    """


# ------------------------------------------------------------------
# Helpers de mapeo DatosReclamo → códigos Oracle Forms
# ------------------------------------------------------------------

def _tipo_siniestro_a_codigo(tipo: str) -> str:
    """Convierte DatosSiniestro.tipo al código numérico del LOV de Oracle Forms."""
    t = (tipo or "").lower()
    if "colisi" in t or "vuelco" in t:
        return "30"
    if "robo" in t or "hurto" in t:
        return "20"
    if "incendio" in t:
        return "910"
    if "comprensivo" in t:
        return "40"
    return "30"


def _cobertura_a_codigo(cobertura: str) -> str:
    """Convierte DatosPoliza.cobertura al código de la tabla Reservas en Oracle Forms."""
    c = (cobertura or "").upper()
    if "COLISI" in c or "VUELCO" in c:
        return "E"
    if "ROBO" in c or "HURTO" in c:
        return "HUR"
    if "INCENDIO" in c:
        return "INC"
    if "COMPRENSIVO" in c:
        return "D"
    if "PROPIEDAD" in c or "AJENA" in c:
        return "B"
    return "E"


# ------------------------------------------------------------------
# Flujo principal
# ------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Conectar RDP, abrir sistema Premium y hacer login en Oracle Forms"
    )
    # Credenciales RDP
    parser.add_argument("--host",             default=os.environ.get("RDP_HOST", ""))
    parser.add_argument("--username",         default=os.environ.get("RDP_USERNAME", ""))
    parser.add_argument("--password",         default=os.environ.get("RDP_PASSWORD", ""))
    # Credenciales Oracle Forms (diálogo "Conexión" de Premium)
    parser.add_argument("--premium-username", default=os.environ.get("PREMIUM_USERNAME", ""))
    parser.add_argument("--premium-password", default=os.environ.get("PREMIUM_PASSWORD", ""))
    # Control de flujo
    parser.add_argument("--timeout",    type=int, default=90,
                        help="Segundos a esperar escritorio RDP (default: 90)")
    parser.add_argument("--dry-run",    action="store_true",
                        help="Detectar ícono Premium pero sin doble click")
    parser.add_argument("--no-rdp",     action="store_true",
                        help="Omitir pasos RDP (asumir sesión ya activa)")
    parser.add_argument("--no-premium", action="store_true",
                        help="Omitir apertura de Premium (asumir diálogo Conexión ya visible)")
    parser.add_argument("--step",       choices=["all", "rdp", "premium", "login", "apertura", "generales1", "generales2", "generales3", "reservas", "formulario"],
                        default="all",
                        help=(
                            "Ejecutar solo un segmento del flujo para debug:\n"
                            "  all        — flujo completo (default)\n"
                            "  rdp        — solo conectar RDP y parar\n"
                            "  premium    — solo abrir Premium (asume RDP activo)\n"
                            "  login      — solo llenar diálogo Conexión (asume Premium abierto)\n"
                            "  apertura   — solo P1+P2: menú Apertura + Consulta de Endosos\n"
                            "  generales1 — solo Generales (1): fecha recibo, tipo, descripción, hora, lugar"
                        ))
    parser.add_argument("--poliza",   default="", help="Número de póliza para Consulta de Endosos")
    parser.add_argument("--fecha-siniestro", default="", help="Fecha siniestro ISO YYYY-MM-DD")
    parser.add_argument("--tipo-siniestro", default="30",
                        help="Código del tipo de siniestro (ej: 10=PERDIDA TOTAL COLISION, 20=ROBO, 30=COLISION, 910=INCENDIO)")
    parser.add_argument("--guardar", action="store_true",
                        help="⚠️  CREA UN RECLAMO REAL — guarda el formulario y extrae el número de reclamo")
    parser.add_argument("--simular-guardar", action="store_true",
                        help="Calibración: click neutral + ir a G1 + crop zona OCR (sin Enter, sin reclamo)")
    parser.add_argument("--datos-json", metavar="ARCHIVO",
                        help="Ruta al JSON de DatosReclamo (salida de Phase A / procesar_casos.py). "
                             "Precarga póliza, fecha y todos los campos del formulario.")
    args = parser.parse_args()

    # ── Cargar DatosReclamo desde JSON (Phase A → Phase B bridge) ────────────
    datos: dict = {}
    if args.datos_json:
        _json_path = Path(args.datos_json)
        if not _json_path.is_absolute() and not _json_path.exists():
            _json_path = Path(__file__).parent / _json_path
        with open(_json_path, encoding="utf-8") as _f:
            _raw = json.load(_f)
        # Soporta tanto el dict plano como el envelope {"reclamo_data": {...}}
        datos = _raw.get("reclamo_data", _raw)
        print(f"[→] Datos cargados desde {args.datos_json}")
        print(f"    Póliza:    {datos.get('numero_poliza', '—')}")
        print(f"    Tipo:      {(datos.get('siniestro') or {}).get('tipo', '—')}")
        print(f"    Conductor: {(datos.get('conductor') or {}).get('nombre', '—')} "
              f"{(datos.get('conductor') or {}).get('apellido', '—')}")

    # Auto-poblar poliza y fecha desde datos si no fueron pasados como arg
    if datos:
        if not args.poliza:
            args.poliza = datos.get("numero_poliza", "")
        if not args.fecha_siniestro:
            args.fecha_siniestro = (datos.get("siniestro") or {}).get("fecha", "")

    # --step login / apertura implican saltar pasos anteriores
    if args.step in ("login", "apertura", "generales1", "generales2", "generales3", "reservas", "formulario"):
        args.no_rdp = True
        args.no_premium = True
        # Traer la ventana RDP al frente para poder ver la automatización
        import pygetwindow as gw
        try:
            rdp_wins = [t for t in gw.getAllTitles()
                        if ("Conexión a Escritorio remoto" in t or "Remote Desktop Connection" in t)
                        and " - " in t]
            if rdp_wins:
                win = gw.getWindowsWithTitle(rdp_wins[0])[0]
                win.maximize()
                win.activate()
                time.sleep(0.8)
                print(f"[→] Ventana RDP al frente: '{rdp_wins[0]}'")
            else:
                print("[WARN] Ventana RDP no encontrada — asegurate de que la sesion este activa")
        except Exception as e:
            print(f"[WARN] No se pudo traer ventana RDP al frente: {e}")

    # pasos que saltan segmentos anteriores
    skip_login      = args.step in ("rdp", "premium", "apertura", "generales1", "generales2", "generales3", "reservas", "formulario")
    skip_apertura   = args.step in ("rdp", "premium", "login", "generales1", "generales2", "generales3", "reservas", "formulario")
    skip_generales1 = args.step in ("rdp", "premium", "login", "apertura", "generales2", "generales3", "reservas")
    skip_generales2 = args.step in ("rdp", "premium", "login", "apertura", "generales1", "generales3", "reservas")
    skip_generales3 = args.step in ("rdp", "premium", "login", "apertura", "generales1", "generales2", "reservas")
    skip_reservas   = args.step in ("rdp", "premium", "login", "apertura", "generales1", "generales2", "generales3")

    if not args.no_rdp:
        if not args.host:
            print("[ERROR] Host requerido: --host o RDP_HOST en .env")
            sys.exit(1)
        if not args.username or not args.password:
            print("[ERROR] Credenciales RDP requeridas en .env o como args")
            sys.exit(1)

    if not skip_login and not args.dry_run:
        if not args.premium_username or not args.premium_password:
            print("[ERROR] Credenciales Premium requeridas: PREMIUM_USERNAME y PREMIUM_PASSWORD en .env")
            sys.exit(1)

    # Limpiar capturas anteriores
    import shutil
    if os.path.isdir(_CAPTURAS_DIR):
        shutil.rmtree(_CAPTURAS_DIR)
    os.makedirs(_CAPTURAS_DIR)
    print(f"[→] Capturas en: {_CAPTURAS_DIR}")

    print(f"\n{'='*55}")
    print(f"  PHASE B — Abrir Sistema Premium + Login Oracle Forms")
    if not args.no_rdp:
        print(f"  RDP:     {args.host}  |  {args.username}")
    if not skip_login and not args.dry_run:
        print(f"  Premium: {args.premium_username}")
    if args.step != "all":
        print(f"  Modo:    --step {args.step}")
    print(f"{'='*55}\n")

    try:
        _captura("paso_01_inicio.png", "pantalla inicial")

        # ── Segmento RDP ─────────────────────────────────────────────
        if not args.no_rdp:
            _limpiar_credenciales(args.host)
            _abrir_rdp(fullscreen=True)
            time.sleep(2)
            _captura("paso_02_mstsc_lanzado.png", "mstsc recién lanzado")

            if not _esperar_escritorio(
                args.host, args.username, args.password, timeout_s=args.timeout
            ):
                print("[ERROR] No se pudo establecer la sesión RDP")
                _captura("error_rdp_fallido.png")
                sys.exit(1)

            _esperar_escritorio_rdp_listo(timeout_s=90)
            _cerrar_shutdown_tracker()
            _captura("paso_07_escritorio_rdp.png", "escritorio remoto listo")
            _enfocar_ventana_rdp(args.host)

        if args.step == "rdp":
            print(f"\n[✓] --step rdp completado. Capturas en: {_CAPTURAS_DIR}")
            return

        # ── Segmento Premium (abrir app) ──────────────────────────────
        if not args.no_premium:
            if not _abrir_servidor_premium(dry_run=args.dry_run):
                _captura("error_premium_no_encontrado.png")
                print(f"\n[HINT] Revisá las capturas en: {_CAPTURAS_DIR}")
                sys.exit(1)

            if args.dry_run:
                print(f"\n[✓] Dry-run completado. Capturas en: {_CAPTURAS_DIR}")
                return

            time.sleep(3)
            _esperar_premium_abierto(timeout_s=30)
            time.sleep(2)
            _captura("paso_10_premium_abierto.png", "app Premium abierta")

        if args.step == "premium":
            print(f"\n[✓] --step premium completado. Capturas en: {_CAPTURAS_DIR}")
            return

        # ── Segmento Login Oracle Forms ───────────────────────────────
        if not skip_login:
            if not _esperar_dialogo_conexion(timeout_s=30):
                print("[WARN] Continuando de todas formas — el diálogo puede estar visible")

            _completar_login_premium(args.premium_username, args.premium_password)

            _esperar_premium_logueado(timeout_s=45)

            if args.step == "login":
                print(f"\n[✓] --step login completado. Capturas en: {_CAPTURAS_DIR}")
                return

        # ── Segmento Apertura de Reclamo (P1 + P2) ───────────────────
        if not skip_apertura:
            poliza = args.poliza
            fecha  = args.fecha_siniestro
            if not poliza or not fecha:
                print("[WARN] --poliza y --fecha-siniestro requeridos para el paso apertura")
                print(f"       Capturas hasta login en: {_CAPTURAS_DIR}")
                return

            if not _navegar_apertura_reclamo():
                _captura("error_navegacion_menu.png")
                print(f"\n[HINT] Creá los templates en docs/screens/ para navegación precisa")
                sys.exit(1)

            if not _esperar_consulta_endosos(timeout_s=15):
                print("[WARN] Continuando de todas formas...")

            _ingresar_poliza_y_fecha(poliza, fecha)
            _click_boton_consultar_unidades()

            # El popup de duplicado aparece después de que Consultar Unidades
            # carga los datos — esperar un poco más y luego verificar
            time.sleep(1.5)
            if _cerrar_popup_forms_si_existe():
                print("\n[!] Reclamo duplicado — Oracle Forms advirtió posible duplicidad")
                _cerrar_formulario_consulta_endosos()
                raise ReclamoDuplicadoError(
                    f"Póliza {poliza} ya tiene un reclamo para la fecha {fecha}"
                )

            _extraer_datos_automovil()

            # El popup de vigencia puede aparecer al cargar la pantalla de automóvil
            if _cerrar_popup_forms_si_existe():
                print("\n[!] Siniestro fuera de vigencia — detectado al cargar automóvil")
                _cerrar_pantalla_automovil_y_endosos()
                raise SiniestroFueraVigenciaError(
                    f"Póliza {poliza}: siniestro {fecha} fuera de vigencia del automóvil"
                )

            _click_boton_coberturas_auto()

            # También puede aparecer al intentar abrir coberturas
            if _cerrar_popup_forms_si_existe():
                print("\n[!] Siniestro fuera de vigencia — detectado al abrir coberturas")
                _cerrar_pantalla_automovil_y_endosos()
                raise SiniestroFueraVigenciaError(
                    f"Póliza {poliza}: siniestro {fecha} fuera de vigencia del automóvil"
                )

            _seleccionar_cobertura_colision_vuelco()

        if not skip_generales1:
            _sin = datos.get("siniestro") or {}
            _tipo_codigo = _tipo_siniestro_a_codigo(_sin.get("tipo", "")) or args.tipo_siniestro
            _llenar_generales_1(
                tipo_siniestro_codigo=_tipo_codigo,
                descripcion=_sin.get("descripcion", "") or "SIN DESCRIPCION",
                hora_siniestro=_sin.get("hora", "") or "00:00",
                lugar_siniestro=_sin.get("lugar", "") or "PANAMA",
            )

        if not skip_generales2:
            _con = datos.get("conductor") or {}
            _llenar_generales_2(
                cedula=_con.get("cedula", "") or "",
                nombre=(_con.get("nombre", "") or "").upper(),
                apellido=(_con.get("apellido", "") or "").upper(),
                sexo=_con.get("sexo", "M") or "M",
                edad=str(_con.get("edad", "") or ""),
                responsabilidad=_con.get("responsabilidad", "Culpable") or "Culpable",
            )

        if not skip_generales3:
            _sin3 = datos.get("siniestro") or {}
            _llenar_generales_3(
                descripcion_danos=_sin3.get("descripcion_danos", "") or "SIN DESCRIPCION",
                ajustador_interno=str(datos.get("ajustador_interno", 158) or 158),
            )

        if not skip_reservas:
            _pol = datos.get("poliza") or {}
            _llenar_reservas(
                cobertura_codigo=_cobertura_a_codigo(_pol.get("cobertura", "")),
                monto_reserva=str(int(_pol.get("reserva", 1300) or 1300)),
            )

        if args.guardar:
            try:
                numero = _guardar_reclamo()
                print(f"\n[✓] RECLAMO CREADO — No.: {numero}")
                _cerrar_reclamo_y_volver_inicio()
            except ReclamoExistenteError as exc:
                print(f"\n[!] RECLAMO YA EXISTE — {exc}")
                sys.exit(2)
        elif args.simular_guardar:
            _simular_guardar()
            _cerrar_reclamo_y_volver_inicio()
        else:
            print("\n[i] Formulario listo. Usar --guardar para crear el reclamo.")

        print(f"\n[✓] Listo. Capturas en: {_CAPTURAS_DIR}")
        print(f"    Abrí la carpeta: explorer {_CAPTURAS_DIR}")

    except ReclamoDuplicadoError as exc:
        print(f"\n[!] RECLAMO DUPLICADO — {exc}")
        print("    Oracle Forms advirtió posible duplicidad — caso saltado.")
        sys.exit(3)

    except SiniestroFueraVigenciaError as exc:
        print(f"\n[!] SINIESTRO FUERA DE VIGENCIA — {exc}")
        print("    La fecha del siniestro no está cubierta por ningún endoso — requiere revisión manual.")
        sys.exit(4)

    finally:
        pass


if __name__ == "__main__":
    main()
