"""Navigation helpers: Oracle Forms menu traversal and Endosos form interaction."""
import os
import time

from premium.common import T, log, screenshot, find_on_screen, CAPTURES_DIR, TITLEBAR_REF

# Absolute coordinates of each menu item in the reference screenshot
# docs/screens/p17_menu_apertura.png (1920x1080).
_MENU_CLICKS_REF = {
    "Premium":                (312, 101),
    "1-Reclamos":             (312, 205),
    "1.2-Procesos":           (508, 238),
    "1.2.1-Manejo Reclamos":  (620, 239),
    "1.2.1.1-Apertura":       (900, 238),
    "1.2.1.2-Apertura":       (1100, 238),
}

# Highlighted-state templates for each menu item (primary matching strategy).
_MENU_TEMPLATES = {
    "Premium":                "menu_premium.png",
    "1-Reclamos":             "menu_1_reclamos.png",
    "1.2-Procesos":           "menu_12_procesos.png",
    "1.2.1-Manejo Reclamos":  "menu_121_manejo.png",
    "1.2.1.1-Apertura":       "menu_1211_apertura.png",
    "1.2.1.2-Apertura":       "menu_1211_apertura.png",
}

# Tabs from last policy field to Fecha del Siniestro in the Endosos form.
_TABS_TO_DATE = 1

# Down-arrow presses from row A to reach 'E - POR COLISIÓN O VUELCO'.
_DOWNS_TO_COLLISION = 4


def calculate_window_offset() -> tuple[int, int]:
    """
    Locate the Oracle Forms titlebar on screen and compute (dx, dy) relative to
    the reference screenshot position. Returns (0, 0) if the template is unavailable.
    """
    import pyautogui
    tpl = T("titlebar_oracle_forms.png")
    if not os.path.isfile(tpl):
        log("  → titlebar_oracle_forms.png not available — using reference coords")
        return (0, 0)
    try:
        loc = pyautogui.locateOnScreen(tpl, confidence=0.70)
        if loc:
            dx = int(loc.left) - TITLEBAR_REF[0]
            dy = int(loc.top)  - TITLEBAR_REF[1]
            log(f"  → Oracle Forms at ({int(loc.left)}, {int(loc.top)}) — offset ({dx:+d}, {dy:+d})")
            return (dx, dy)
        log("  → Titlebar not found — using reference coords")
    except pyautogui.ImageNotFoundException:
        log("  → Titlebar not found — using absolute reference coords")
    except Exception as exc:
        log(f"  → Error searching titlebar: {exc}")
    return (0, 0)


def click_menu_item(name: str, dx: int, dy: int, wait: float = 0.5) -> None:
    """Click a menu item using reference coordinates + window offset."""
    import pyautogui
    ref_x, ref_y = _MENU_CLICKS_REF[name]
    x, y = ref_x + dx, ref_y + dy
    pyautogui.click(x, y)
    log(f"  → Click '{name}' ({x}, {y})")
    time.sleep(wait)


def press_key(key: str, pause: float = 0.15) -> None:
    """Press a key and wait."""
    import pyautogui
    pyautogui.press(key)
    time.sleep(pause)


def navigate_to_claim_apertura() -> bool:
    """
    Steps 17-18 (keyboard via pywinauto): navigate
    Premium → 1-Reclamos → 1.2-Procesos → 1.2.1-Manejo Reclamos → 1.2.1.1-Apertura.
    Falls back to click-based navigation if RDP window is not found.
    """
    import pyautogui
    from pywinauto import Desktop

    _RIGHT_PREMIUM = 1
    _DOWN_RECLAMOS = 3
    _DOWN_PROCESOS  = 1
    _DOWN_MANEJO    = 0
    _DOWN_APERTURA  = 0

    log("\n[→] Step 17 (keyboard pywinauto) — Navigating Premium → Apertura...")
    screenshot("paso_17_inicio_navegacion.png", "before opening menu (keyboard)")

    try:
        from premium.rdp import get_rdp_window
        rdp = get_rdp_window()
        rdp.set_focus()
        time.sleep(0.50)
        log(f"  → RDP window: '{rdp.window_text()}'")
    except Exception as exc:
        log(f"  [WARN] RDP window not found: {exc} — trying click-based navigation")
        return _navigate_by_click()

    def _k(keys, n=1, pause=0.35):
        for _ in range(n):
            rdp.type_keys(keys, pause=0.05, with_spaces=True)
            time.sleep(pause)
            log(f"    {keys}")

    dx, dy = calculate_window_offset()
    tb_x = TITLEBAR_REF[0] + dx + 100
    tb_y = TITLEBAR_REF[1] + dy + 16
    log(f"  → Click Oracle Forms titlebar ({tb_x}, {tb_y})")
    pyautogui.click(tb_x, tb_y)
    time.sleep(0.60)

    log("  → {VK_MENU} — activate menubar")
    _k("{VK_MENU}", pause=0.60)

    log(f"  → {{RIGHT}} x{_RIGHT_PREMIUM} — reach 'Premium'")
    _k("{RIGHT}", _RIGHT_PREMIUM, pause=0.30)
    time.sleep(0.20)

    log("  → {DOWN} — open Premium dropdown")
    _k("{DOWN}", pause=0.60)

    log(f"  → {{DOWN}} x{_DOWN_RECLAMOS} — reach '1-Reclamos'")
    _k("{DOWN}", _DOWN_RECLAMOS, pause=0.25)
    time.sleep(0.20)

    log("  → {RIGHT} — open '1-Reclamos' submenu")
    _k("{RIGHT}", pause=0.60)

    log(f"  → {{DOWN}} x{_DOWN_PROCESOS} — reach '1.2-Procesos'")
    _k("{DOWN}", _DOWN_PROCESOS, pause=0.25)
    time.sleep(0.20)

    log("  → {RIGHT} — open '1.2-Procesos' submenu")
    _k("{RIGHT}", pause=0.60)

    if _DOWN_MANEJO:
        log(f"  → {{DOWN}} x{_DOWN_MANEJO} — reach '1.2.1-Manejo Reclamos'")
        _k("{DOWN}", _DOWN_MANEJO, pause=0.25)
        time.sleep(0.20)

    log("  → {RIGHT} — open '1.2.1-Manejo Reclamos' submenu")
    _k("{RIGHT}", pause=0.60)

    if _DOWN_APERTURA:
        log(f"  → {{DOWN}} x{_DOWN_APERTURA} — reach '1.2.1.1-Apertura'")
        _k("{DOWN}", _DOWN_APERTURA, pause=0.25)
        time.sleep(0.20)

    log("  → {ENTER} — select '1.2.1.1-Apertura'")
    _k("{ENTER}", pause=1.20)

    screenshot("paso_18_apertura_seleccionada.png", "post-navigation keyboard")
    log("[OK] Keyboard navigation complete")
    return True


def _navigate_by_click() -> bool:
    """
    Click-based menu navigation fallback using hover + template matching.
    Hover activates the highlight; locateOnScreen finds the exact position.
    """
    import pyautogui

    log("\n[→] Step 17 (click) — Navigating Premium → Apertura...")
    screenshot("paso_17_inicio_navegacion.png", "before opening menu")

    dx, dy = calculate_window_offset()

    tb_x = TITLEBAR_REF[0] + dx + 100
    tb_y = TITLEBAR_REF[1] + dy + 16
    pyautogui.click(tb_x, tb_y)
    time.sleep(0.3)
    log(f"  → Focus Oracle Forms ({tb_x}, {tb_y})")

    pm_x = _MENU_CLICKS_REF["Premium"][0] + dx
    pm_y = _MENU_CLICKS_REF["Premium"][1] + dy
    log(f"  → Click 'Premium' ({pm_x}, {pm_y})")
    pyautogui.click(pm_x, pm_y)
    time.sleep(1.20)

    def _menu_click(key, label, delay=0.80):
        approx_x = _MENU_CLICKS_REF[key][0] + dx
        approx_y = _MENU_CLICKS_REF[key][1] + dy
        pyautogui.moveTo(approx_x, approx_y)
        time.sleep(0.35)
        click_x, click_y = approx_x, approx_y
        tpl_file = T(_MENU_TEMPLATES.get(key, ""))
        if os.path.isfile(tpl_file):
            try:
                loc = pyautogui.locateOnScreen(tpl_file, confidence=0.90)
                if loc:
                    click_x = int(loc.left + loc.width  / 2)
                    click_y = int(loc.top  + loc.height / 2)
                    log(f"  → template '{label}' found at ({click_x}, {click_y})")
                else:
                    log(f"  → template '{label}' not found — using coord ({approx_x}, {approx_y})")
            except pyautogui.ImageNotFoundException:
                log(f"  → template '{label}' not found — using coord ({approx_x}, {approx_y})")
            except Exception as exc:
                log(f"  → template '{label}' error ({exc}) — using coord ({approx_x}, {approx_y})")
        pyautogui.click(click_x, click_y)
        time.sleep(delay)

    _menu_click("1-Reclamos",            "1-Reclamos")
    _menu_click("1.2-Procesos",          "1.2-Procesos")
    _menu_click("1.2.1-Manejo Reclamos", "1.2.1-Manejo Reclamos")
    _menu_click("1.2.1.1-Apertura",      "1.2.1.1-Apertura")
    _menu_click("1.2.1.2-Apertura",      "1.2.1.1-Apertura", delay=1.20)

    screenshot("paso_18_apertura_seleccionada.png", "post-navigation")
    log("[OK] Click navigation complete — 1.2.1.1-Apertura selected")
    return True


def wait_endosos_form(timeout_s: int = 15) -> bool:
    """
    Step 19: Wait for 'Consulta de Endosos REC0001' to open.
    Uses template if available; falls back to screen stability detection.
    """
    import pyautogui

    log(f"\n[→] Step 19 — Waiting for 'Consulta de Endosos' (up to {timeout_s}s)...")
    deadline = time.time() + timeout_s
    template = T("form_consulta_endosos.png")

    if os.path.isfile(template):
        while time.time() < deadline:
            if find_on_screen(template, confidence=0.75):
                screenshot("paso_19_consulta_endosos.png", "Consulta de Endosos open")
                log("[OK] 'Consulta de Endosos' form detected")
                return True
            time.sleep(1.0)
    else:
        log("  → No template — waiting for screen stability")
        import hashlib
        prev_hash, stable = None, 0
        while time.time() < deadline:
            time.sleep(1.5)
            h = hashlib.md5(pyautogui.screenshot().tobytes()).hexdigest()
            if h == prev_hash:
                stable += 1
                if stable >= 2:
                    screenshot("paso_19_consulta_endosos.png", "stable screen — form ready")
                    log("[OK] Stable screen — form ready")
                    return True
            else:
                stable = 0
            prev_hash = h

    log("[WARN] Timeout waiting for 'Consulta de Endosos'")
    screenshot("paso_19_timeout.png", "timeout")
    return False


def enter_policy_and_date(numero_poliza: str, fecha_siniestro: str) -> bool:
    """
    Step 20: Fill 'No. de Póliza' + 'Fecha del Siniestro' and press F8.
    Policy is entered as 4 Tab-separated sub-fields.
    Date is converted from ISO (YYYY-MM-DD) to DD/MM/YYYY.
    """
    try:
        from datetime import datetime
        fecha_of = datetime.strptime(fecha_siniestro[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        fecha_of = fecha_siniestro

    partes = numero_poliza.split("-")

    log(f"\n[→] Step 20 — Filling Consulta de Endosos...")
    log(f"  → Policy: {numero_poliza} ({len(partes)} parts)")
    log(f"  → Incident date: {fecha_siniestro} → {fecha_of}")

    try:
        from premium.rdp import get_rdp_window
        rdp = get_rdp_window()
        rdp.set_focus()
        time.sleep(0.40)
    except Exception as exc:
        log(f"  [WARN] RDP window not found: {exc}")
        return False

    def _k(keys, pause=0.20):
        rdp.type_keys(keys, pause=0.05, with_spaces=True)
        time.sleep(pause)
        log(f"    {keys}")

    for i, part in enumerate(partes):
        _k(part, pause=0.15)
        _k("{TAB}", pause=0.20)
        log(f"  → Part {i+1}: '{part}'")

    screenshot("paso_20_poliza_ingresada.png", f"policy {numero_poliza} entered")

    log(f"  → {_TABS_TO_DATE} Tab(s) to Fecha del Siniestro")
    for _ in range(_TABS_TO_DATE):
        _k("{TAB}", pause=0.15)

    _k(fecha_of, pause=0.20)
    screenshot("paso_20_fecha_ingresada.png", f"date {fecha_of} entered")
    log(f"  → Date: {fecha_of}")

    _k("{F8}", pause=1.50)
    screenshot("paso_21_f8_ejecutado.png", "F8 executed — waiting for results")
    log("[OK] F8 executed — query sent")
    return True


def click_consultar_unidades() -> bool:
    """
    Step 22: Click the 'Consultar Unidades' button.
    Template: docs/screens/boton_consultar_unidades.png
    """
    import pyautogui

    log("\n[→] Step 22 — Click Consultar Unidades button...")
    template = T("boton_consultar_unidades.png")

    if not os.path.isfile(template):
        log("  [WARN] boton_consultar_unidades.png not found — skipping step")
        return False

    try:
        loc = pyautogui.locateOnScreen(template, confidence=0.80)
        if loc:
            cx = int(loc.left + loc.width  / 2)
            cy = int(loc.top  + loc.height / 2)
            pyautogui.click(cx, cy)
            time.sleep(1.0)
            screenshot("paso_22_boton_consultar_click.png", "Consultar Unidades clicked")
            log(f"  → Button found and clicked at ({cx}, {cy})")
            return True
        log("  [WARN] Button not found on screen")
    except pyautogui.ImageNotFoundException:
        log("  [WARN] Button not found on screen")
    except Exception as exc:
        log(f"  [WARN] Error searching button: {exc}")
    return False


def extract_vehicle_data() -> dict:
    """
    Step 23: Capture the 'Consulta de Automóviles Asegurados' screen
    and extract vehicle data via OCR (pytesseract).
    Returns a dict with extracted data, or empty dict if OCR is unavailable.
    """
    import pyautogui

    screenshot("paso_23_consulta_automovil.png", "Consulta de Automóviles Asegurados")
    log("\n[→] Step 23 — Extracting vehicle data...")

    try:
        import pytesseract
        from PIL import Image as PILImage
        img = PILImage.open(os.path.join(CAPTURES_DIR, "paso_23_consulta_automovil.png"))
        text = pytesseract.image_to_string(img, lang="spa")
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        log(f"  → OCR: {len(lines)} lines extracted")
        for line in lines:
            log(f"    {line}")
        log("[OK] Vehicle data extracted")
        return {"raw_ocr": text}
    except (ImportError, Exception) as exc:
        log(f"  [WARN] OCR unavailable ({type(exc).__name__}) — capture saved, extraction pending")
        log("[OK] Capture saved to paso_23_consulta_automovil.png")
        return {}


def click_coberturas_button() -> bool:
    """
    Step 24: Click the auto coverage icon (top-right of Automóviles form).
    Template: docs/screens/boton_coberturas_auto.png
    """
    import pyautogui

    log("\n[→] Step 24 — Click Coberturas button...")
    template = T("boton_coberturas_auto.png")

    if not os.path.isfile(template):
        log("  [WARN] boton_coberturas_auto.png not found — skipping step")
        return False

    try:
        loc = pyautogui.locateOnScreen(template, confidence=0.80)
        if loc:
            cx = int(loc.left + loc.width  / 2)
            cy = int(loc.top  + loc.height / 2)
            pyautogui.click(cx, cy)
            time.sleep(1.0)
            screenshot("paso_24_coberturas_click.png", "Coberturas button clicked")
            log(f"  → Button found and clicked at ({cx}, {cy})")
            return True
        log("  [WARN] Coberturas button not found on screen")
    except pyautogui.ImageNotFoundException:
        log("  [WARN] Coberturas button not found on screen")
    except Exception as exc:
        log(f"  [WARN] Error searching Coberturas button: {exc}")
    return False


def select_collision_coverage() -> bool:
    """
    Step 25: In 'Consulta de Coberturas', navigate to row
    'E - POR COLISIÓN O VUELCO' and click the select button (hand icon).
    Uses Down arrows to reach row E, then template-matches the select button.
    """
    import pyautogui

    log("\n[→] Step 25 — Selecting Colisión o Vuelco coverage...")
    screenshot("paso_25_inicio_coberturas.png", "Consulta de Coberturas open")

    try:
        from premium.rdp import get_rdp_window
        rdp = get_rdp_window()
        rdp.set_focus()
        time.sleep(0.30)
    except Exception as exc:
        log(f"  [WARN] RDP window not found: {exc}")
        return False

    def _k(keys, n=1, pause=0.25):
        for _ in range(n):
            rdp.type_keys(keys, pause=0.05, with_spaces=True)
            time.sleep(pause)
            log(f"    {keys}")

    log(f"  → Down x{_DOWNS_TO_COLLISION} — reach 'E - POR COLISIÓN O VUELCO'")
    _k("{DOWN}", _DOWNS_TO_COLLISION)
    time.sleep(0.30)
    screenshot("paso_25_fila_colision_seleccionada.png", "Colisión o Vuelco row active")

    template = T("boton_seleccionar_cobertura.png")
    if not os.path.isfile(template):
        log("  [WARN] boton_seleccionar_cobertura.png not found — skipping click")
        return False

    try:
        loc = pyautogui.locateOnScreen(template, confidence=0.80)
        if loc:
            cx = int(loc.left + loc.width  / 2)
            cy = int(loc.top  + loc.height / 2)
            pyautogui.click(cx, cy)
            time.sleep(1.0)
            screenshot("paso_25_cobertura_seleccionada.png", "coverage selected")
            log(f"  → Select button clicked at ({cx}, {cy})")
            return True
        log("  [WARN] Select button not found on screen")
    except pyautogui.ImageNotFoundException:
        log("  [WARN] Select button not found on screen")
    except Exception as exc:
        log(f"  [WARN] Error searching select button: {exc}")
    return False
