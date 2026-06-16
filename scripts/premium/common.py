"""
Shared utilities for the Premium RPA package.

All other modules import from here:
    from premium.common import log, screenshot, find_on_screen, T, CAPTURES_DIR, TITLEBAR_REF
"""
import os
import time
from pathlib import Path

# ------------------------------------------------------------------
# Paths
# ------------------------------------------------------------------

_SCRIPTS_DIR  = Path(__file__).parent.parent          # scripts/
_DOCS_DIR     = _SCRIPTS_DIR.parent / "docs"
_SCREENS_DIR  = _DOCS_DIR / "screens"
CAPTURES_DIR  = str(_SCRIPTS_DIR / "capturas")

TEMPLATE_SERVER   = str(_DOCS_DIR / "template_server_premium.png")
TEMPLATE_CONEXION = str(_DOCS_DIR / "template_premium_conexion.png")

# Position of the Oracle Forms titlebar crop in the reference screenshot
# (docs/screens/titlebar_oracle_forms.png, captured at 1920x1080).
TITLEBAR_REF = (168, 60)


def T(name: str) -> str:
    """Return absolute path to a template in docs/screens/."""
    return str(_SCREENS_DIR / name)


# ------------------------------------------------------------------
# Template catalogue
# ------------------------------------------------------------------

TEMPLATES = (
    "boton_cancel_shutdown.png",
    "boton_coberturas_auto.png",
    "boton_consultar_unidades.png",
    "boton_lov_tipo_siniestro.png",
    "boton_seleccionar_cobertura.png",
    "campo_ajustador_interno.png",
    "campo_apellido_conductor.png",
    "campo_cedula_conductor.png",
    "campo_descripcion_danos.png",
    "campo_descripcion_siniestro.png",
    "campo_edad_conductor.png",
    "campo_fecha_recibo_docs.png",
    "campo_hora_siniestro.png",
    "campo_lugar_conductor.png",
    "campo_lugar_siniestro.png",
    "campo_nombre_conductor.png",
    "campo_relacion_asegurado.png",
    "campo_sexo_conductor.png",
    "campo_tipo_siniestro.png",
    "col_cobertura_reservas.png",
    "label_no_reclamo.png",
    "menu_1211_apertura.png",
    "menu_121_manejo.png",
    "menu_12_procesos.png",
    "menu_1_reclamos.png",
    "menu_premium.png",
    "modal_ok_forms.png",
    "p17_menu_apertura.png",
    "p19_consulta_endosos.png",
    "radio_culpable.png",
    "tab_generales_2.png",
    "tab_generales_3.png",
    "tab_reservas.png",
    "titlebar_consulta_endosos.png",
    "titlebar_forms_modal.png",
    "titlebar_oracle_forms.png",
    "titulo_shutdown_tracker.png",
)


def validate_templates() -> None:
    """
    Check that every template in the catalogue exists in docs/screens/.
    Logs a warning per missing file so failures are visible before runtime.
    """
    missing = [t for t in TEMPLATES if not os.path.isfile(T(t))]
    if missing:
        for t in missing:
            log(f"[WARN] Missing template: docs/screens/{t}")
        log(f"[WARN] {len(missing)} template(s) missing — some steps may fail")


# ------------------------------------------------------------------
# RDP input mode
# ------------------------------------------------------------------

_rdp_slow_mode: bool = False


def is_slow_rdp() -> bool:
    """True when high-latency RDP was detected at session start."""
    return _rdp_slow_mode


def set_slow_rdp(value: bool) -> None:
    global _rdp_slow_mode
    _rdp_slow_mode = value
    if value:
        log("[WARN] Slow RDP detected — text input via pyautogui.write, special keys via rdp.type_keys")


def rdp_focus(rdp) -> None:
    """
    Focus the RDP/Oracle Forms window before sending keystrokes.
    Normal mode: pywinauto set_focus() (~10s UIA overhead in slow RDP).
    Slow mode: no-op — Oracle Forms is already focused from click-based navigation.
    """
    if not _rdp_slow_mode:
        rdp.set_focus()
        time.sleep(0.40)
    # In slow mode the form is already focused; avoid another UIA round-trip.


def rdp_type(rdp, keys: str, pause: float = 0.05) -> None:
    """
    Send keystrokes to the RDP window.

    Normal mode: rdp.type_keys() for everything (pywinauto UIA).
    Slow mode: pyautogui.write() for plain-text segments (avoids ~11s UIA
    stabilisation wait per call), rdp.type_keys() only for special keys
    like {TAB}, {ENTER}, {F8}, {VK_MENU}, {DOWN}, etc.
    """
    import re
    if not _rdp_slow_mode:
        rdp.type_keys(keys, pause=pause, with_spaces=True)
        return

    import pyautogui
    pending_specials = ""
    for part in re.split(r'(\{[^}]+\})', keys):
        if not part:
            continue
        if part.startswith('{') and part.endswith('}'):
            pending_specials += part
        else:
            if pending_specials:
                rdp.type_keys(pending_specials, pause=pause, with_spaces=True)
                pending_specials = ""
            pyautogui.write(part, interval=0.05)
    if pending_specials:
        rdp.type_keys(pending_specials, pause=pause, with_spaces=True)


# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------

_notif = None


def set_notifier(notif) -> None:
    """Called from main() after initialising Notificador."""
    global _notif
    _notif = notif


def log(*args, **kwargs) -> None:
    """
    Drop-in for print() that routes to Notificador when available.
    Without a notifier it behaves exactly like print().
    Level inferred from message prefix:
      [WARN] / [!]  → alerta
      [ERROR]       → error
      [OK] / [✓]    → ok
      anything else → info
    """
    import builtins
    if _notif is None:
        builtins.print(*args, **kwargs)
        return
    msg = " ".join(str(a) for a in args)
    s = msg.lstrip()
    if s.startswith(("[WARN]", "[!")):
        _notif.alerta(msg)
    elif s.startswith("[ERROR]"):
        _notif.error(msg)
    elif s.startswith(("[OK]", "[✓]")):
        _notif.ok(msg)
    else:
        _notif.info(msg)


# ------------------------------------------------------------------
# Screenshots
# ------------------------------------------------------------------

def screenshot(filename: str, label: str = "") -> str:
    """Take a screenshot and save it to CAPTURES_DIR."""
    import pyautogui
    os.makedirs(CAPTURES_DIR, exist_ok=True)
    path = os.path.join(CAPTURES_DIR, filename)
    time.sleep(0.5)
    pyautogui.screenshot().save(path)
    tag = f" [{label}]" if label else ""
    log(f"  📸 {filename}{tag}")
    return path


def screenshot_with_marker(filename: str, x: int, y: int, radius: int = 40) -> str:
    """Take a screenshot and draw a red crosshair at (x, y)."""
    import pyautogui
    from PIL import Image, ImageDraw
    os.makedirs(CAPTURES_DIR, exist_ok=True)
    path = os.path.join(CAPTURES_DIR, filename)
    time.sleep(0.5)
    img = pyautogui.screenshot()
    draw = ImageDraw.Draw(img)
    draw.ellipse([x - radius, y - radius, x + radius, y + radius], outline="red", width=4)
    draw.line([x - radius - 10, y, x + radius + 10, y], fill="red", width=3)
    draw.line([x, y - radius - 10, x, y + radius + 10], fill="red", width=3)
    img.save(path)
    log(f"  📸 {filename} [marked at ({x}, {y})]")
    return path


# ------------------------------------------------------------------
# Screen search
# ------------------------------------------------------------------

def find_on_screen(template_path: str, confidence: float = 0.8):
    """Locate a template on screen. Returns (cx, cy) or None."""
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


# ------------------------------------------------------------------
# Tesseract OCR
# ------------------------------------------------------------------

_TESSERACT_DEFAULT = os.path.join(
    os.path.expanduser("~"), "AppData", "Local", "Programs",
    "Tesseract-OCR", "tesseract.exe",
)

try:
    import pytesseract as _pyt
    _tess_cmd = os.environ.get("TESSERACT_CMD", _TESSERACT_DEFAULT)
    if os.path.isfile(_tess_cmd):
        _pyt.pytesseract.tesseract_cmd = _tess_cmd
except ImportError:
    pass
