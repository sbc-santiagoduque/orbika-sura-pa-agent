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
import os
import subprocess
import sys
import time

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
    Sin template, Oracle Forms ya pone el foco en Usuario al abrir el diálogo.
    """
    import pyautogui

    print(f"\n[→] Paso 12-15 — Llenando diálogo 'Conexión'...")

    # Intentar click en campo Usuario via template
    coords = _buscar_en_pantalla(_TEMPLATE_CONEXION, confidence=0.75)
    if coords:
        cx, cy = coords
        # Campo Usuario está ~30px debajo del centro del header del diálogo
        pyautogui.click(cx, cy + 30)
        print(f"  → Click en campo Usuario via template ({cx}, {cy + 30})")
    else:
        # Oracle Forms pone foco en Usuario al abrir — no se necesita click
        print("  → Sin template — asumiendo foco en campo Usuario")

    time.sleep(0.4)

    # Paso 12: Usuario
    pyautogui.hotkey("ctrl", "a")
    _pegar(usuario)
    _captura("paso_12_usuario_escrito.png", f"usuario: {usuario}")
    print(f"  → [12] Usuario escrito: {usuario}")

    # Paso 13: Contraseña
    pyautogui.hotkey("tab")
    time.sleep(0.2)
    pyautogui.hotkey("ctrl", "a")
    _pegar(password)
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
# Se usan como fallback si el titlebar no se encuentra en pantalla.
_MENU_CLICKS_REF = {
    # (x_center, y_center) en el screenshot de referencia 1920x1080
    "Premium":                (312, 101),   # barra de menú: crop x=265-360, y=88-114
    "1-Reclamos":             (312, 205),   # dropdown de Premium — misma x que Premium, y=4to item
    "1.2-Procesos":           (508, 238),   # submenu: blue region x=468-549, y=225-252
    "1.2.1-Manejo Reclamos":  (620, 239),   # sub-submenu: ajustado (ref era 718, muy a la derecha)
    "1.2.1.1-Apertura":       (900, 238),   # deep submenu: ajustado
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


def _navegar_apertura_reclamo() -> bool:
    """
    Paso 17-18: Navega el menú Premium → 1-Reclamos → 1.2-Procesos →
    1.2.1-Manejo Reclamos → 1.2.1.1-Apertura.

    Estrategia:
      1. Calcular offset de ventana Oracle Forms.
      2. Click directo en "Premium" en la barra de menú (coordenadas ajustadas)
         para abrir el dropdown. Esto evita el problema de foco con Alt.
      3. Con el dropdown abierto, usar Down/Enter para navegar submenús.
         El dropdown retiene el foco en Oracle Forms.
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

    # ── 3. Hover-to-navigate: mover el mouse abre submenús en cascada ────────
    # No se usan teclas — el mouse se mantiene dentro de Oracle Forms en todo momento.
    # Hover sobre item intermedio → su submenu se abre → continuar hacia la derecha.
    # Solo el item final (1.2.1.1-Apertura) recibe click.
    def _menu_click(ref_x, ref_y, label, delay=0.80):
        x, y = ref_x + dx, ref_y + dy
        print(f"  → click '{label}' ({x}, {y})")
        pyautogui.click(x, y)
        time.sleep(delay)

    _menu_click(*_MENU_CLICKS_REF["1-Reclamos"],            "1-Reclamos")
    _menu_click(*_MENU_CLICKS_REF["1.2-Procesos"],          "1.2-Procesos")
    _menu_click(*_MENU_CLICKS_REF["1.2.1-Manejo Reclamos"], "1.2.1-Manejo Reclamos")
    _menu_click(*_MENU_CLICKS_REF["1.2.1.1-Apertura"],      "1.2.1.1-Apertura", delay=1.20)

    _captura("paso_18_apertura_seleccionada.png", "post-navegacion")
    print("[OK] Navegacion completada — 1.2.1.1-Apertura seleccionado")
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

    No. de Póliza tiene 4 sub-campos separados por Tab (ej. "02-98-1246363-0"):
      "02" → Tab → "98" → Tab → "1246363" → Tab → "0" → Tab

    Fecha del Siniestro en formato DD/MM/YYYY (Oracle Forms estándar Panamá).
    F8 ejecuta la consulta.

    Con template campo_no_poliza.png: click preciso en el primer sub-campo.
    Sin template: foco asumido en primer campo tras abrir el formulario.
    """
    import pyautogui

    # Convertir fecha ISO → DD/MM/YYYY
    try:
        from datetime import datetime
        fecha_of = datetime.strptime(fecha_siniestro[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        fecha_of = fecha_siniestro  # usar tal cual si no parsea

    partes_poliza = numero_poliza.split("-")  # ["02", "98", "1246363", "0"]

    print(f"\n[→] Paso 20 — Llenando Consulta de Endosos...")
    print(f"  → Póliza: {numero_poliza} ({len(partes_poliza)} partes)")
    print(f"  → Fecha siniestro: {fecha_siniestro} → {fecha_of}")

    # Enfocar primer sub-campo de No. de Póliza
    template_poliza = _T("campo_no_poliza.png")
    if os.path.isfile(template_poliza):
        coords = _buscar_en_pantalla(template_poliza, confidence=0.75)
        if coords:
            cx, cy = coords
            # El primer sub-campo está ~120px a la derecha de la etiqueta "No. de Póliza"
            pyautogui.click(cx + 120, cy)
            print(f"  → Click campo Póliza via template ({cx + 120}, {cy})")
            time.sleep(0.3)
    else:
        print("  → Sin template campo_no_poliza — asumiendo foco en primer campo")

    # Llenar las partes de la póliza con Tab entre cada una
    for i, parte in enumerate(partes_poliza):
        pyautogui.hotkey("ctrl", "a")
        _pegar(parte)
        time.sleep(0.15)
        pyautogui.hotkey("tab")
        time.sleep(0.15)
        print(f"  → Parte {i+1}: '{parte}'")

    _captura("paso_20_poliza_ingresada.png", f"póliza {numero_poliza} ingresada")

    # Navegar a Fecha del Siniestro
    template_fecha = _T("campo_fecha_siniestro.png")
    if os.path.isfile(template_fecha):
        coords = _buscar_en_pantalla(template_fecha, confidence=0.75)
        if coords:
            cx, cy = coords
            # El campo fecha está ~120px a la derecha de la etiqueta
            pyautogui.click(cx + 120, cy)
            print(f"  → Click campo Fecha via template ({cx + 120}, {cy})")
            time.sleep(0.3)
    else:
        # Sin template: Tab navega desde la última parte de póliza
        # a través de Estado y Siniestralidad hasta Fecha del Siniestro
        print("  → Sin template fecha — navegando con Tab hasta Fecha del Siniestro")
        for _ in range(4):   # Estado (1) + $ (2) + % (3) + Fecha (4)
            pyautogui.hotkey("tab")
            time.sleep(0.15)

    pyautogui.hotkey("ctrl", "a")
    _pegar(fecha_of)
    time.sleep(0.2)
    _captura("paso_20_fecha_ingresada.png", f"fecha {fecha_of} ingresada")
    print(f"  → Fecha: {fecha_of}")

    # F8 — ejecutar consulta
    pyautogui.hotkey("f8")
    time.sleep(1.5)
    _captura("paso_21_f8_ejecutado.png", "F8 ejecutado — esperando resultados")
    print("[OK] F8 ejecutado — consulta enviada")

    return True


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
    parser.add_argument("--step",       choices=["all", "rdp", "premium", "login", "apertura"],
                        default="all",
                        help=(
                            "Ejecutar solo un segmento del flujo para debug:\n"
                            "  all      — flujo completo (default)\n"
                            "  rdp      — solo conectar RDP y parar\n"
                            "  premium  — solo abrir Premium (asume RDP activo)\n"
                            "  login    — solo llenar diálogo Conexión (asume Premium abierto)\n"
                            "  apertura — solo P1+P2: menú Apertura + Consulta de Endosos"
                        ))
    parser.add_argument("--poliza",   default="", help="Número de póliza para Consulta de Endosos")
    parser.add_argument("--fecha-siniestro", default="", help="Fecha siniestro ISO YYYY-MM-DD")
    args = parser.parse_args()

    # --step login / apertura implican saltar pasos anteriores
    if args.step in ("login", "apertura"):
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
    skip_login    = args.step in ("rdp", "premium", "apertura")
    skip_apertura = args.step in ("rdp", "premium", "login")

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

        print(f"\n[✓] Listo. Capturas en: {_CAPTURAS_DIR}")
        print(f"    Abrí la carpeta: explorer {_CAPTURAS_DIR}")

    finally:
        pass


if __name__ == "__main__":
    main()
