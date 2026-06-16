"""RDP and Oracle Forms login helpers."""
import glob
import hashlib
import os
import subprocess
import time

from premium.common import (
    T, log, screenshot, screenshot_with_marker,
    TEMPLATE_SERVER, TEMPLATE_CONEXION, CAPTURES_DIR, find_on_screen,
)

# Resolved at import time — looks for 'SERVER PREMIUM.rdp' on any user desktop.
_RDP_FILE = ""


def find_rdp_executable() -> str:
    """
    Locate 'SERVER PREMIUM.rdp' on any user's Desktop.
    Search order:
      1. RDP_FILE env var (explicit override)
      2. C:\\Users\\*\\Desktop\\SERVER PREMIUM.rdp
      3. Public desktop
      4. Fallback path (for error messages)
    """
    env_path = os.environ.get("RDP_FILE", "")
    if env_path and os.path.isfile(env_path):
        return env_path

    matches = glob.glob("C:\\Users\\*\\Desktop\\SERVER PREMIUM.rdp")
    if matches:
        return matches[0]

    pub = os.path.join(
        os.environ.get("PUBLIC", "C:\\Users\\Public"), "Desktop", "SERVER PREMIUM.rdp"
    )
    if os.path.isfile(pub):
        return pub

    return "C:\\Users\\Subocol\\Desktop\\SERVER PREMIUM.rdp"


_RDP_FILE = find_rdp_executable()


def get_rdp_window():
    """
    Return the active RDP window via pywinauto.
    Prefers the window whose title contains RDP_HOST; falls back to found_index=0.
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


def clear_saved_credentials(host: str) -> None:
    """Remove RDP credentials for host from the Windows Credential Manager."""
    subprocess.run(["cmdkey", f"/delete:TERMSRV/{host}"], capture_output=True)


def open_rdp_session(host: str = "", username: str = "", fullscreen: bool = True) -> subprocess.Popen:
    """
    Launch mstsc with 'SERVER PREMIUM.rdp'.
    The .rdp file has authentication level:i:0 and the username pre-configured.
    """
    if not os.path.isfile(_RDP_FILE):
        raise FileNotFoundError(
            f"RDP file not found: {_RDP_FILE}\n"
            "Make sure 'SERVER PREMIUM.rdp' is on the desktop."
        )
    cmd = ["mstsc", _RDP_FILE]
    if fullscreen:
        cmd.append("/f")
    process = subprocess.Popen(cmd)
    log(f"[OK] mstsc launched with 'SERVER PREMIUM.rdp' (PID {process.pid})")
    return process


def paste_text(text: str) -> None:
    """Paste text via clipboard — supports @, !, # and other special characters."""
    import pyperclip
    import pyautogui
    pyperclip.copy(text)
    time.sleep(0.15)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.15)


def _strip_amp(text: str) -> str:
    """Remove Windows accelerator-key prefix & from button text. 'Co&nectar' → 'Conectar'"""
    return text.replace("&", "").strip()


def _inspect_dialog_buttons(title: str) -> list[str]:
    """Return button texts (without &) from the dialog with the given title."""
    try:
        from pywinauto import Desktop
        wins = [w for w in Desktop(backend="win32").windows()
                if w.window_text() == title and w.is_visible()]
        if wins:
            buttons = wins[0].children(class_name="Button")
            return [_strip_amp(b.window_text()) for b in buttons]
    except Exception:
        pass
    return []


def handle_credentials_dialog(username: str, password: str) -> bool:
    """
    Fill 'Seguridad de Windows' credential dialog.
    Tries three strategies in order:
      1. pywinauto uia — find Edit controls by handle
      2. Click by position + clipboard (supports special characters)
      3. Tab + clipboard fallback
    Returns True (always — dialog presence is the signal, not fill success).
    """
    import pygetwindow as gw
    import pyautogui

    titles = gw.getAllTitles()
    dialogs = [t for t in titles if t in ("Seguridad de Windows", "Windows Security")]
    if not dialogs:
        return False

    title = dialogs[0]
    log(f"  → Credential dialog: '{title}'")
    screenshot("paso_05_dialogo_credenciales.png", "before sending credentials")

    try:
        from pywinauto import Desktop
        all_wins = Desktop(backend="uia").windows()
        wins = [w for w in all_wins if title in w.window_text() and w.is_visible()]
        log(f"  → uia windows with '{title}': {len(wins)}")
        if wins:
            dlg = wins[0]
            fields = dlg.descendants(control_type="Edit")
            log(f"  → Edit fields (uia): {len(fields)}")
            if len(fields) >= 2:
                fields[0].click_input()
                fields[0].type_keys("^a")
                fields[0].type_keys(username, with_spaces=True)
                log(f"  → Username: {username}")
                time.sleep(0.2)
                fields[1].click_input()
                fields[1].type_keys("^a")
                fields[1].type_keys(password, with_spaces=True)
                log("  → Password written (uia)")
            elif len(fields) == 1:
                fields[0].click_input()
                fields[0].type_keys("^a")
                fields[0].type_keys(password, with_spaces=True)
                log("  → Password written uia (single field)")
            else:
                raise RuntimeError("0 Edit fields")
            time.sleep(0.3)
            try:
                dlg.child_window(title="Aceptar", control_type="Button").click_input()
            except Exception:
                pyautogui.hotkey("enter")
            time.sleep(1.5)
            screenshot("paso_06_credenciales_enviadas.png", "uia")
            return True
    except Exception as e:
        log(f"  → uia failed: {e}")

    try:
        wins_gw = gw.getWindowsWithTitle(title)
        if not wins_gw:
            raise RuntimeError("window not found")
        win = wins_gw[0]
        win.activate()
        time.sleep(0.6)
        cx = win.left + win.width // 2
        cy_user = win.top + int(win.height * 0.45)
        log(f"  → Click username ({cx}, {cy_user})")
        pyautogui.click(cx, cy_user, clicks=3, interval=0.1)
        time.sleep(0.2)
        pyautogui.hotkey("ctrl", "a")
        paste_text(username)
        cy_pwd = win.top + int(win.height * 0.60)
        log(f"  → Click password ({cx}, {cy_pwd})")
        pyautogui.click(cx, cy_pwd, clicks=3, interval=0.1)
        time.sleep(0.2)
        pyautogui.hotkey("ctrl", "a")
        paste_text(password)
        time.sleep(0.3)
        cy_ok = win.top + int(win.height * 0.85)
        pyautogui.click(cx, cy_ok)
        time.sleep(1.5)
        screenshot("paso_06_credenciales_enviadas.png", "clipboard")
        return True
    except Exception as e:
        log(f"  → click+clipboard: {e}")

    try:
        wins_gw = gw.getWindowsWithTitle(title)
        if wins_gw:
            wins_gw[0].activate()
            time.sleep(0.5)
        pyautogui.hotkey("ctrl", "a")
        paste_text(username)
        time.sleep(0.2)
        pyautogui.hotkey("tab")
        time.sleep(0.2)
        pyautogui.hotkey("ctrl", "a")
        paste_text(password)
        time.sleep(0.3)
        pyautogui.hotkey("enter")
        time.sleep(1.5)
        screenshot("paso_06_credenciales_enviadas.png", "tab+clipboard")
        return True
    except Exception as e:
        log(f"  → tab fallback: {e}")

    return True


def handle_certificate_dialog() -> bool:
    """
    Handle mstsc certificate/security dialogs:
      Warning type [Sí][No]          → Left+Enter (focus on No → move to Sí)
      Warning type [Conectar][Cancel] → Enter (focus already on Conectar)
      Error type [Aceptar only]       → Enter (close, return False — do not retry)
    Returns True if a dialog was handled, False if none found or it was an error dialog.
    """
    import pygetwindow as gw
    import pyautogui

    _CERT_TITLES = (
        "Advertencia de seguridad de conexión a Escritorio remoto",
        "Remote Desktop Connection Security Warning",
        "Conexión a Escritorio remoto",
        "Remote Desktop Connection",
    )

    titles = gw.getAllTitles()
    title = next((t for t in titles if t in _CERT_TITLES), None)
    if not title:
        return False

    buttons = _inspect_dialog_buttons(title)
    names_lower = [b.lower() for b in buttons]
    log(f"  → Dialog '{title}' — buttons: {buttons}")

    if buttons and all(b.lower() in ("aceptar", "ok", "cerrar", "close")
                       for b in buttons if b.strip()):
        log("  → [ERROR RDP] Error dialog detected — closing with Enter")
        screenshot("error_rdp_dialogo.png", "RDP connection error")
        try:
            win = gw.getWindowsWithTitle(title)[0]
            win.activate()
            time.sleep(0.3)
        except Exception:
            pass
        pyautogui.hotkey("enter")
        time.sleep(0.5)
        return False

    screenshot("paso_03_dialogo_certificado.png", "before accepting")

    _ACCEPT_LABELS = ("conectar", "connect", "sí", "si", "yes")
    try:
        from pywinauto import Desktop
        for backend in ("uia", "win32"):
            wins = [w for w in Desktop(backend=backend).windows()
                    if title in w.window_text() and w.is_visible()]
            if not wins:
                continue
            dlg = wins[0]
            btns = (dlg.descendants(control_type="Button") if backend == "uia"
                    else dlg.children(class_name="Button"))
            for btn in btns:
                clean = _strip_amp(btn.window_text()).lower()
                if clean in _ACCEPT_LABELS:
                    log(f"  → Click '{btn.window_text()}' (backend={backend})")
                    btn.click_input()
                    time.sleep(1.0)
                    screenshot("paso_04_certificado_aceptado.png", f"click {backend}")
                    return True
    except Exception as e:
        log(f"  → pywinauto: {e}")

    try:
        win = gw.getWindowsWithTitle(title)[0]
        win.activate()
        time.sleep(0.5)
        if any(b in names_lower for b in ("conectar", "connect")):
            pyautogui.hotkey("enter")
            log("  → Enter (Conectar)")
        else:
            pyautogui.hotkey("left")
            time.sleep(0.2)
            pyautogui.hotkey("enter")
            log("  → Left+Enter (Sí)")
        time.sleep(1.0)
        screenshot("paso_04_certificado_aceptado.png", "keyboard fallback")
        return True
    except Exception as ex:
        log(f"  → Keyboard fallback: {ex}")

    return False


_MAX_CRED_RETRIES = 3


def wait_for_desktop(host: str, username: str, password: str,
                     timeout_s: int = 90, poll_s: float = 3.0) -> bool:
    """
    Poll until the RDP session is active (title contains ' - Conexión a Escritorio remoto').
    Handles credential dialogs and certificate warnings as they appear.
    """
    import pygetwindow as gw

    iterations = int(timeout_s / poll_s)
    cred_retries = 0

    for i in range(iterations):
        time.sleep(poll_s)
        titles = gw.getAllTitles()

        active = [t for t in titles
                  if ("Conexión a Escritorio remoto" in t or "Remote Desktop Connection" in t)
                  and " - " in t]
        if active:
            log(f"[OK] Desktop connected: '{active[0]}'")
            return True

        cred_dialog = [t for t in titles if t in ("Seguridad de Windows", "Windows Security")]
        if cred_dialog:
            if cred_retries >= _MAX_CRED_RETRIES:
                log(f"[ERROR] Credentials rejected {_MAX_CRED_RETRIES} times")
                screenshot("error_credenciales_rechazadas.png")
                return False
            cred_retries += 1
            log(f"  → Credential attempt {cred_retries}/{_MAX_CRED_RETRIES}")
            handle_credentials_dialog(username, password)
            continue

        warning = [t for t in titles if "Advertencia de seguridad" in t or "Security Warning" in t]
        if warning:
            log(f"  → Certificate warning: '{warning[0]}'")
            handle_certificate_dialog()
            continue

        handle_certificate_dialog()

        connecting = [t for t in titles if "Escritorio remoto" in t or "Remote Desktop" in t]
        state = f"'{connecting[0]}'" if connecting else "waiting for mstsc..."
        log(f"  → Attempt {i+1}/{iterations} — {state}")

    return False


def focus_rdp_window(host: str) -> bool:
    """Bring the active RDP window to the foreground. Returns False if not found."""
    import pygetwindow as gw

    titles = [t for t in gw.getAllTitles()
              if ("Conexión a Escritorio remoto" in t or "Remote Desktop Connection" in t)
              and " - " in t]
    if not titles:
        return False
    try:
        win = gw.getWindowsWithTitle(titles[0])[0]
        win.activate()
        time.sleep(1.0)
        return True
    except Exception as e:
        log(f"  → Could not focus RDP window: {e}")
        return False


def find_premium_icon(confidence: float = 0.8):
    """
    Search for the SERVER PREMIUM icon on screen.
    Returns (cx, cy) or None.
    """
    import pyautogui
    if not os.path.isfile(TEMPLATE_SERVER):
        raise FileNotFoundError(
            f"Template not found: {TEMPLATE_SERVER}\n"
            "Run the icon crop first (see docs/escritorio_remoto_config.png)"
        )
    try:
        location = pyautogui.locateOnScreen(TEMPLATE_SERVER, confidence=confidence)
    except pyautogui.ImageNotFoundException:
        return None
    if location is None:
        return None
    center = pyautogui.center(location)
    return int(center.x), int(center.y)


def wait_rdp_desktop_ready(timeout_s: int = 90) -> bool:
    """
    Wait until the remote desktop has finished loading by detecting when
    the screen stops changing (3 consecutive identical hashes → stable).
    """
    import pyautogui

    log(f"  → Waiting for remote desktop to load (up to {timeout_s}s)...")
    deadline = time.time() + timeout_s
    prev_hash = None
    stable = 0

    while time.time() < deadline:
        time.sleep(3)
        img = pyautogui.screenshot()
        current_hash = hashlib.md5(img.tobytes()).hexdigest()
        if current_hash == prev_hash:
            stable += 1
            log(f"  → Screen stable ({stable}/3)...")
            if stable >= 3:
                log(f"  → Desktop ready — stable for {stable * 3}s")
                return True
        else:
            stable = 0
            log("  → Screen still changing...")
        prev_hash = current_hash

    log("  → [WARN] Timeout waiting for desktop — proceeding anyway")
    return False


def close_shutdown_tracker() -> bool:
    """
    Detect and close the 'Shutdown Event Tracker' popup if visible.
    Returns True if found and closed.
    """
    import pyautogui
    tpl_path = T("boton_cancel_shutdown.png")
    if not os.path.isfile(tpl_path):
        return False
    try:
        pos = pyautogui.locateCenterOnScreen(tpl_path, confidence=0.8)
        if pos:
            pyautogui.click(pos)
            time.sleep(0.5)
            log("  → Shutdown Event Tracker closed")
            return True
    except Exception:
        pass
    return False


def open_premium_app(dry_run: bool = False, retries: int = 5) -> bool:
    """
    Find and double-click the SERVER PREMIUM icon on the remote desktop.
    Retries up to `retries` times with 3s waits; relaxes confidence on last two tries.
    """
    import pyautogui

    log("\n[→] Looking for SERVER PREMIUM icon...")
    screenshot("paso_08_buscando_premium.png", "screen where icon is searched")

    for attempt in range(1, retries + 1):
        coords = find_premium_icon(confidence=0.8)
        if coords is None and attempt >= retries - 1:
            coords = find_premium_icon(confidence=0.6)

        if coords:
            x, y = coords
            log(f"[OK] SERVER PREMIUM found at ({x}, {y}) — attempt {attempt}/{retries}")
            screenshot_with_marker("paso_09_premium_encontrado.png", x, y)
            if dry_run:
                log(f"[DRY-RUN] Double-click at ({x}, {y}) — not executed")
                return True
            pyautogui.doubleClick(x, y)
            log("[OK] Double-click on SERVER PREMIUM")
            return True

        log(f"  → Icon not found (attempt {attempt}/{retries}) — waiting 3s...")
        screenshot(f"paso_08_intento_{attempt:02d}.png", f"attempt {attempt} — icon not found")
        time.sleep(3)

    log("[WARN] SERVER PREMIUM not detected")
    return False


def wait_premium_open(timeout_s: int = 30) -> bool:
    """Wait until a Premium/SISTEMA window appears (up to timeout_s seconds)."""
    import pygetwindow as gw

    log(f"[→] Waiting for Premium to load (up to {timeout_s}s)...")
    deadline = time.time() + timeout_s

    while time.time() < deadline:
        time.sleep(2)
        titles = gw.getAllTitles()
        premium = [t for t in titles
                   if any(kw in t.upper() for kw in ("PREMIUM", "SERVER PREMIUM", "SISTEMA"))
                   and t not in ("Conexión a Escritorio remoto", "Remote Desktop Connection")]
        if premium:
            log(f"[OK] Premium open: '{premium[0]}'")
            return True

    log("[WARN] No Premium window detected by title")
    log("       (may have opened inside the remote desktop — see paso_10)")
    return False


def wait_login_dialog(timeout_s: int = 30) -> bool:
    """
    Wait for the Oracle Forms 'Conexión' dialog to appear.
    Uses template matching if TEMPLATE_CONEXION exists; otherwise polls for screen stability.
    """
    import pyautogui

    log(f"\n[→] Step 11 — Waiting for 'Conexión' dialog (up to {timeout_s}s)...")
    deadline = time.time() + timeout_s

    if os.path.isfile(TEMPLATE_CONEXION):
        while time.time() < deadline:
            if find_on_screen(TEMPLATE_CONEXION, confidence=0.75):
                log("[OK] 'Conexión' dialog detected")
                screenshot("paso_11_dialogo_conexion.png", "Conexión dialog detected")
                return True
            log("  → Searching for Conexión dialog...")
            time.sleep(1.5)
    else:
        log("  → No template — waiting for screen stability")
        log("     (Tip: create docs/template_premium_conexion.png for precise detection)")
        prev_hash, stable = None, 0
        while time.time() < deadline:
            time.sleep(2)
            h = hashlib.md5(pyautogui.screenshot().tobytes()).hexdigest()
            if h == prev_hash:
                stable += 1
                log(f"  → Screen stable ({stable}/2)...")
                if stable >= 2:
                    screenshot("paso_11_dialogo_conexion.png", "stable screen — dialog ready")
                    return True
            else:
                stable = 0
                log("  → Screen changing...")
            prev_hash = h

    log("[WARN] Timeout waiting for 'Conexión' dialog")
    screenshot("paso_11_timeout.png", "timeout Conexión dialog")
    return False


def complete_login(usuario: str, password: str) -> bool:
    """
    Fill the Oracle Forms 'Conexión' dialog and click Conectar.
    Tab navigation: Usuario → Password → Database (empty) → Tab → Conectar → Enter.
    Uses pyautogui.write() so special chars in credentials work without clipboard.
    """
    import pyautogui

    log("\n[→] Steps 12-15 — Filling 'Conexión' dialog...")

    try:
        rdp = get_rdp_window()
        rdp.set_focus()
        time.sleep(0.50)
        log("  → RDP window focused")
    except Exception as exc:
        log(f"  [WARN] set_focus RDP: {exc}")

    time.sleep(0.5)

    pyautogui.write(usuario, interval=0.05)
    screenshot("paso_12_usuario_escrito.png", f"username: {usuario}")
    log(f"  → [12] Username written: {usuario}")

    pyautogui.hotkey("tab")
    time.sleep(0.2)
    pyautogui.write(password, interval=0.05)
    screenshot("paso_13_password_escrito.png", "password written")
    log("  → [13] Password written")

    pyautogui.hotkey("tab")
    time.sleep(0.15)
    pyautogui.hotkey("tab")
    time.sleep(0.2)
    screenshot("paso_14_foco_conectar.png", "focus on Conectar button")
    log("  → [14] Focus on Conectar")

    pyautogui.hotkey("enter")
    time.sleep(1.0)
    screenshot("paso_15_conectar_enviado.png", "Conectar executed")
    log("  → [15] Conectar executed")

    return True


def wait_logged_in(timeout_s: int = 30) -> bool:
    """
    Wait until Oracle Forms main screen loads after login.
    Detects disappearance of 'Conexión' template, or screen stability as fallback.
    """
    import pyautogui

    log(f"\n[→] Step 16 — Waiting for Premium main screen (up to {timeout_s}s)...")
    deadline = time.time() + timeout_s

    if os.path.isfile(TEMPLATE_CONEXION):
        while time.time() < deadline:
            time.sleep(2)
            if find_on_screen(TEMPLATE_CONEXION, confidence=0.75) is None:
                time.sleep(2)
                screenshot("paso_16_premium_logueado.png", "Conexión dialog gone — Premium loaded")
                log("[OK] Login successful — Premium main screen")
                return True
            log("  → Conexión dialog still visible...")
    else:
        prev_hash, stable = None, 0
        while time.time() < deadline:
            time.sleep(2)
            h = hashlib.md5(pyautogui.screenshot().tobytes()).hexdigest()
            if h == prev_hash:
                stable += 1
                if stable >= 3:
                    screenshot("paso_16_premium_logueado.png", "stable screen post-login")
                    log("[OK] Stable screen — Premium loaded")
                    return True
            else:
                stable = 0
                log("  → Screen changing post-login...")
            prev_hash = h

    log("[WARN] Timeout waiting for Premium main screen")
    screenshot("paso_16_timeout.png", "post-login timeout")
    return False
