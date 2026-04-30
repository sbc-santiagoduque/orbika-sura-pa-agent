"""Oracle Forms filling, saving, and tab-retry helpers."""
import os
import time

from premium.common import T, log, screenshot, CAPTURES_DIR, TITLEBAR_REF
from premium.exceptions import FieldValidationError, UnauthorizedError

_OFFSET_INPUT = 200

_TAB_PREVIOUS = {
    "generals1": None,
    "generals2": "generals1",
    "generals3": "generals2",
    "reserves":  "generals3",
}


def _get_rdp():
    from premium.rdp import get_rdp_window
    return get_rdp_window()


def _close_forms_popup():
    from premium.recovery import close_forms_popup
    return close_forms_popup()


def _type_keys(rdp, keys, n=1, pause=0.25) -> None:
    for _ in range(n):
        rdp.type_keys(keys, pause=0.05, with_spaces=True)
        time.sleep(pause)


def _click_label(template_name: str, offset_x: int = _OFFSET_INPUT,
                 offset_y: int = 0, label: str = "") -> bool:
    """Locate a field label template and click offset_x px to its right."""
    import pyautogui
    tpl = T(template_name)
    if not os.path.isfile(tpl):
        log(f"  [WARN] Template {template_name} not found")
        return False
    try:
        loc = pyautogui.locateOnScreen(tpl, confidence=0.80)
        if loc:
            cx = int(loc.left + offset_x)
            cy = int(loc.top  + loc.height / 2 + offset_y)
            pyautogui.click(cx, cy)
            time.sleep(0.40)
            log(f"  → Click '{label}' ({cx}, {cy})")
            return True
        log(f"  [WARN] Label '{label}' not found on screen")
    except Exception as exc:
        log(f"  [WARN] Error searching '{label}': {exc}")
    return False


def assert_no_frm_modal(tab: str = "") -> None:
    """
    Check for an active FRM modal (FRM-40202 or similar).
    If detected: dismiss with Enter and raise FieldValidationError so the
    caller can go back one tab and retry.
    """
    if _close_forms_popup():
        raise FieldValidationError(
            f"FRM modal detected on tab '{tab}' — required field empty",
            tab=tab,
        )


def go_back_one_tab(failed_tab: str) -> None:
    """
    Navigate back to the previous tab and re-enter failed_tab.
    Used to reset Oracle Forms state when FRM-40202 blocked a fill step.
    Anchors on tab_generales_2.png; uses offsets for G1/G3 and tab_reservas.png for Reserves.
    """
    import pyautogui

    log(f"  [RETRY] Stepping back from '{failed_tab}' to retry...")

    try:
        rdp = _get_rdp()
        rdp.type_keys("{ESC}", pause=0.05, with_spaces=True)
        time.sleep(0.25)
        rdp.type_keys("{ESC}", pause=0.05, with_spaces=True)
        time.sleep(0.30)
    except Exception:
        pass

    tab2_tpl = T("tab_generales_2.png")
    res_tpl  = T("tab_reservas.png")

    def _click_tab(x, y):
        pyautogui.click(x, y)
        time.sleep(0.70)

    def _loc_g2():
        try:
            loc = pyautogui.locateOnScreen(tab2_tpl, confidence=0.80)
            return loc if (loc and loc.left > 100) else None
        except Exception:
            return None

    loc = _loc_g2()
    if loc is None:
        log("  [WARN] tab_generales_2.png not found — cannot navigate back")
        return

    g2_cx = int(loc.left + loc.width / 2)
    g2_cy = int(loc.top  + loc.height / 2)
    g1_cx = int(loc.left - loc.width * 0.5)
    g3_cx = int(loc.left + loc.width * 1.5)

    if failed_tab == "generals1":
        _click_tab(g1_cx, g2_cy)

    elif failed_tab == "generals2":
        _click_tab(g1_cx, g2_cy)
        loc = _loc_g2()
        if loc:
            _click_tab(int(loc.left + loc.width / 2), g2_cy)

    elif failed_tab == "generals3":
        _click_tab(g2_cx, g2_cy)
        _click_tab(g3_cx, g2_cy)

    elif failed_tab == "reserves":
        _click_tab(g3_cx, g2_cy)
        try:
            loc_r = pyautogui.locateOnScreen(res_tpl, confidence=0.80)
            if loc_r:
                _click_tab(int(loc_r.left + loc_r.width / 2),
                           int(loc_r.top  + loc_r.height / 2))
        except Exception:
            pass

    screenshot(f"retry_tab_{failed_tab}.png", f"after stepping back to '{failed_tab}'")
    log(f"  [RETRY] Ready to retry '{failed_tab}'")


def fill_generals_1(incident_type_code: str = "30",
                    description: str = "PRUEBA AUTOMATIZACION",
                    incident_time: str = "10:00",
                    incident_place: str = "PANAMA") -> bool:
    """
    Step 26: Fill 'Generales (1)' tab.
    Order:
      1. Fecha de Recibo de Documentos → today (DD-MM-YYYY)
      2. Tipo de siniestro → code + Tab → autocomplete + description modal
      3. Hora del siniestro
      4. Lugar del siniestro
    Raises FieldValidationError if an FRM modal appears (field left empty).
    """
    from datetime import date

    hoy = date.today().strftime("%d-%m-%Y")

    log("\n[→] Step 26 — Filling Generales (1)...")
    screenshot("paso_26_inicio_generales1.png", "Apertura del Reclamo — Generales (1)")

    try:
        rdp = _get_rdp()
        rdp.set_focus()
        time.sleep(0.30)
    except Exception as exc:
        log(f"  [WARN] RDP window not found: {exc}")
        return False

    def _k(keys, n=1, pause=0.25):
        _type_keys(rdp, keys, n, pause)

    if _click_label("campo_fecha_recibo_docs.png", label="Fecha Recibo Docs"):
        _k(hoy, pause=0.20)
        screenshot("paso_26_fecha_recibo.png", f"Fecha Recibo Documentos: {hoy}")
        log(f"  → Receipt date: {hoy}")
    else:
        log("  [WARN] Skipping receipt date — template unavailable")

    if _click_label("campo_tipo_siniestro.png", offset_x=130, label="Tipo Siniestro"):
        _k(incident_type_code, pause=0.40)
        _k("{TAB}", pause=0.80)
        screenshot("paso_26_tipo_siniestro.png", "incident type selected")
        log(f"  → Incident type '{incident_type_code}' accepted")

    _k(description, pause=0.20)
    _k("{TAB}", pause=0.30)
    _k("{TAB}", pause=0.30)
    _k("{ENTER}", pause=0.60)
    log(f"  → Description entered: '{description}'")
    screenshot("paso_26_descripcion_siniestro.png", "description entered")

    if _click_label("campo_hora_siniestro.png", label="Hora Siniestro"):
        _k(incident_time, pause=0.20)
        log(f"  → Time: {incident_time}")

    if _click_label("campo_lugar_siniestro.png", label="Lugar Siniestro"):
        _k(incident_place, pause=0.20)
        log(f"  → Place: {incident_place}")

    screenshot("paso_26_generales1_completo.png", "Generales (1) complete")
    assert_no_frm_modal("generals1")
    log("[OK] Generales (1) complete")
    return True


def fill_generals_2(cedula: str = "8-123-456",
                    nombre: str = "JUAN",
                    apellido: str = "PEREZ",
                    sexo: str = "M",
                    edad: str = "35",
                    tel_residencial: str = "0",
                    tel_oficina: str = "0",
                    responsabilidad: str = "Culpable",
                    relacion: str = "CONDUCTOR") -> bool:
    """
    Step 27: Click 'Generales (2)' tab and fill conductor data.
    Raises FieldValidationError if an FRM modal appears.
    """
    import pyautogui
    import hashlib

    log("\n[→] Step 27 — Generales (2): conductor data...")
    screenshot("paso_27_inicio_generales2.png", "before clicking Generales (2) tab")

    try:
        rdp = _get_rdp()
        rdp.set_focus()
        time.sleep(0.30)
    except Exception as exc:
        log(f"  [WARN] RDP window not found: {exc}")
        return False

    def _k(keys, n=1, pause=0.25):
        _type_keys(rdp, keys, n, pause)

    def _screen_hash():
        return hashlib.md5(pyautogui.screenshot().tobytes()).hexdigest()

    tab_tpl = T("tab_generales_2.png")
    if os.path.isfile(tab_tpl):
        try:
            loc = pyautogui.locateOnScreen(tab_tpl, confidence=0.80)
            if loc:
                pyautogui.click(int(loc.left + loc.width / 2), int(loc.top + loc.height / 2))
                time.sleep(0.80)
                log("  → Click Generales (2) tab")
            else:
                log("  [WARN] Generales (2) tab not found")
        except Exception as exc:
            log(f"  [WARN] Error searching tab: {exc}")
    else:
        log("  [WARN] tab_generales_2.png unavailable")

    screenshot("paso_27_generales2_abierto.png", "Generales (2) active")

    lugar_tpl = T("campo_lugar_conductor.png")
    if os.path.isfile(lugar_tpl):
        try:
            loc = pyautogui.locateOnScreen(lugar_tpl, confidence=0.80)
            if loc:
                pyautogui.click(int(loc.left + _OFFSET_INPUT), int(loc.top + loc.height / 2))
                time.sleep(0.30)
                log("  → Click Lugar donde se encuentra")
            else:
                log("  [WARN] Lugar field not found")
        except Exception as exc:
            log(f"  [WARN] campo_lugar_conductor.png: {exc}")
    else:
        log("  [WARN] campo_lugar_conductor.png unavailable — skipping Lugar")
    pyautogui.write("Panama", interval=0.05)
    _k("{TAB}", pause=0.30)
    log("  → Lugar donde se encuentra: Panama")

    cedula_tpl = T("campo_cedula_conductor.png")
    if os.path.isfile(cedula_tpl):
        try:
            loc = pyautogui.locateOnScreen(cedula_tpl, confidence=0.80)
            if loc:
                pyautogui.click(int(loc.left + _OFFSET_INPUT), int(loc.top + loc.height / 2))
                time.sleep(0.40)
                log("  → Click Cédula")
        except Exception as exc:
            log(f"  [WARN] campo_cedula_conductor.png: {exc}")

    _k(cedula, pause=0.20)
    hash_before = _screen_hash()
    _k("{ENTER}", pause=0.80)
    hash_after = _screen_hash()

    log(f"  → Cédula: {cedula}")
    if hash_before != hash_after:
        _k("{ENTER}", pause=0.50)
        log("  → Cédula modal detected — Enter to close")
    screenshot("paso_27_cedula.png", "cédula entered")

    _k(nombre, pause=0.20)
    _k("{ENTER}", pause=0.30)
    log(f"  → Nombre: {nombre}")

    _k(apellido, pause=0.20)
    _k("{ENTER}", pause=0.30)
    log(f"  → Apellido: {apellido}")

    if sexo.upper() == "F":
        _k("{RIGHT}", pause=0.30)
        _k("{UP}",    pause=0.20)
        _k("{ENTER}", pause=0.20)
        _k("{ENTER}", pause=0.30)
        log("  → Sexo: FEMENINO")
    elif sexo.upper() == "M":
        _k("{RIGHT}", pause=0.30)
        _k("{UP}",    pause=0.20)
        _k("{UP}",    pause=0.20)
        _k("{ENTER}", pause=0.20)
        _k("{ENTER}", pause=0.30)
        log("  → Sexo: MASCULINO")
    else:
        _k("{ENTER}", pause=0.30)
        log("  → Sexo: blank")

    _k(str(edad), pause=0.20)
    _k("{ENTER}", pause=0.30)
    log(f"  → Edad: {edad}")

    _k(tel_residencial, pause=0.20)
    _k("{ENTER}", pause=0.30)
    log(f"  → Tel. Residencial: {tel_residencial}")

    _k(tel_oficina, pause=0.20)
    _k("{ENTER}", pause=0.30)
    log(f"  → Tel. Oficina: {tel_oficina}")

    _k(relacion, pause=0.20)
    _k("{ENTER}", pause=0.40)
    log(f"  → Relación: {relacion}")

    if responsabilidad == "Culpable":
        _k("{LEFT}", pause=0.30)
        log("  → Se Declara: Culpable")
    else:
        log("  → Se Declara: Inocente (default)")

    screenshot("paso_27_generales2_completo.png", "Generales (2) complete")
    assert_no_frm_modal("generals2")
    log("[OK] Generales (2) complete")
    return True


def fill_generals_3(descripcion_danos: str = "PRUEBA DESCRIPCION DANOS",
                    ajustador_interno: str = "158") -> bool:
    """
    Step 28: Click 'Generales (3)' tab and fill damage description + internal adjuster.
    G3 tab is located via offset from tab_generales_2.png anchor.
    Raises FieldValidationError if an FRM modal appears.
    """
    import pyautogui

    log("\n[→] Step 28 — Generales (3): damage description + adjuster...")
    screenshot("paso_28_inicio_generales3.png", "before clicking Generales (3) tab")

    try:
        rdp = _get_rdp()
        rdp.set_focus()
        time.sleep(0.30)
    except Exception as exc:
        log(f"  [WARN] RDP window not found: {exc}")
        return False

    def _k(keys, n=1, pause=0.25):
        _type_keys(rdp, keys, n, pause)

    tab2_tpl = T("tab_generales_2.png")
    if os.path.isfile(tab2_tpl):
        try:
            loc = pyautogui.locateOnScreen(tab2_tpl, confidence=0.85)
            if loc:
                cx = int(loc.left + loc.width * 2.5)
                cy = int(loc.top  + loc.height / 2)
                pyautogui.click(cx, cy)
                time.sleep(0.80)
                log(f"  → Click Generales (3) via G2 offset ({cx}, {cy})")
            else:
                log("  [WARN] tab_generales_2.png not found — cannot navigate to G3")
        except Exception as exc:
            log(f"  [WARN] Error searching tab: {exc}")

    screenshot("paso_28_generales3_abierto.png", "Generales (3) active")

    if _click_label("campo_descripcion_danos.png", label="Descripción de daños"):
        time.sleep(0.30)
        _k(descripcion_danos, pause=0.20)
        _k("{TAB}", pause=0.20)
        _k("{TAB}", pause=0.20)
        _k("{ENTER}", pause=0.60)
        screenshot("paso_28_descripcion_danos.png", "damage description entered")
        log(f"  → Damage description: '{descripcion_danos}'")

    if _click_label("campo_ajustador_interno.png", offset_x=100, offset_y=-8,
                    label="Ajustador Interno"):
        _k(ajustador_interno, pause=0.20)
        _k("{ENTER}", pause=0.50)
        screenshot("paso_28_ajustador.png", f"adjuster {ajustador_interno}")
        log(f"  → Ajustador Interno: {ajustador_interno}")

    screenshot("paso_28_generales3_completo.png", "Generales (3) complete")
    assert_no_frm_modal("generals3")
    log("[OK] Generales (3) complete")
    return True


def fill_reserves(coverage_code: str = "E",
                  reserve_amount: str = "1300") -> bool:
    """
    Step 29: Click 'Reservas' tab, enter coverage code in the first row,
    and enter the reserve amount.
    Coverage codes: E=COLISION/VUELCO, HUR=HURTO, INC=INCENDIO, D=COMPRENSIVO, B=PROPIEDAD AJENA.
    Raises FieldValidationError if an FRM modal appears.
    """
    import pyautogui

    log("\n[→] Step 29 — Reserves: coverage + amount...")
    screenshot("paso_29_inicio_reservas.png", "before clicking Reservas tab")

    try:
        rdp = _get_rdp()
        rdp.set_focus()
        time.sleep(0.30)
    except Exception as exc:
        log(f"  [WARN] RDP window not found: {exc}")
        return False

    def _k(keys, n=1, pause=0.25):
        _type_keys(rdp, keys, n, pause)

    tab_tpl = T("tab_reservas.png")
    if os.path.isfile(tab_tpl):
        try:
            loc = pyautogui.locateOnScreen(tab_tpl, confidence=0.85)
            if loc:
                pyautogui.click(int(loc.left + loc.width / 2), int(loc.top + loc.height / 2))
                time.sleep(0.80)
                log("  → Click Reservas tab")
            else:
                log("  [WARN] Reservas tab not found (confidence 0.85)")
        except pyautogui.ImageNotFoundException:
            log("  [WARN] Reservas tab not found")
        except Exception as exc:
            log(f"  [WARN] Error searching Reservas tab: {exc}")
    else:
        log("  [WARN] tab_reservas.png unavailable")

    screenshot("paso_29_reservas_abierto.png", "Reservas tab active")

    col_tpl = T("col_cobertura_reservas.png")
    if os.path.isfile(col_tpl):
        try:
            loc = pyautogui.locateOnScreen(col_tpl, confidence=0.80)
            if loc:
                cx = int(loc.left + loc.width / 2)
                cy = int(loc.top  + loc.height * 1.2)
                pyautogui.click(cx, cy)
                time.sleep(0.80)
                screenshot("paso_29_celda_cobertura.png", "Coverage cell clicked")
                log(f"  → Click first Coverage cell ({cx}, {cy})")
                time.sleep(0.60)
                _k(coverage_code, pause=0.30)
                time.sleep(0.60)
                screenshot("paso_29_codigo_escrito.png", f"code '{coverage_code}' written")
                _k("{ENTER}", pause=0.80)
                screenshot("paso_29_cobertura.png", f"coverage '{coverage_code}' entered")
                log(f"  → Coverage: {coverage_code}")
            else:
                log("  [WARN] Coverage column header not found (confidence 0.80)")
        except pyautogui.ImageNotFoundException:
            log("  [WARN] Coverage column not found")
        except Exception as exc:
            log(f"  [WARN] Error searching coverage column: {exc}")
    else:
        log("  [WARN] col_cobertura_reservas.png unavailable")

    time.sleep(0.60)
    _k(reserve_amount, pause=0.30)
    time.sleep(0.60)
    screenshot("paso_29_monto_reserva.png", f"amount {reserve_amount} entered — ready to save")
    log(f"  → Reserve amount: {reserve_amount}")

    assert_no_frm_modal("reserves")
    log("[OK] Reserves complete")
    return True


def save_claim() -> str | None:
    """
    Step 30: Save the claim and return the generated claim number.
    ⚠️  CREATES A REAL CLAIM — only call when --guardar is active.
    Raises UnauthorizedError if a Forms modal blocks the save.
    """
    from premium.ocr import crop_claim_number_field

    log("\n[→] Step 30 — SAVING CLAIM...")

    try:
        rdp = _get_rdp()
        rdp.set_focus()
        time.sleep(0.40)
    except Exception as exc:
        log(f"  [WARN] RDP window not found: {exc}")
        return None

    def _k(keys, n=1, pause=0.40):
        _type_keys(rdp, keys, n, pause)

    _k("{ENTER}", pause=0.80)
    screenshot("paso_30_monto_confirmado.png", "amount confirmed")

    log("  → Saving via toolbar (Alt+Down+Enter)...")
    _k("{VK_MENU}", pause=0.60)
    _k("{DOWN}",    pause=0.60)
    _k("{ENTER}",   pause=2.00)
    screenshot("paso_30_guardado.png", "post-save")

    time.sleep(1.50)
    if _close_forms_popup():
        screenshot("paso_30_error_guardado.png", "modal blocked save")
        raise UnauthorizedError(
            "A modal blocked the save — user lacks permissions or validation error"
        )

    log("  → Claim saved")

    import pyautogui
    tab2_tpl = T("tab_generales_2.png")
    if os.path.isfile(tab2_tpl):
        try:
            loc = pyautogui.locateOnScreen(tab2_tpl, confidence=0.85)
            if loc:
                cx = int(loc.left - loc.width * 0.5)
                cy = int(loc.top  + loc.height / 2)
                pyautogui.click(cx, cy)
                time.sleep(0.80)
                log(f"  → Click Generales (1) ({cx}, {cy})")
        except pyautogui.ImageNotFoundException:
            log("  [WARN] tab_generales_2.png not found — cannot go to G1")
        except Exception as exc:
            log(f"  [WARN] Error navigating to G1: {exc}")

    screenshot("paso_30_generales1.png", "Generales (1) post-save")

    claim_number = None
    crop_path = crop_claim_number_field("paso_30_no_reclamo_crop.png")
    if crop_path:
        try:
            from PIL import Image as _PILImage
            import pytesseract
            img   = _PILImage.open(crop_path)
            text  = pytesseract.image_to_string(img, config="--psm 7 digits").strip()
            claim_number = text.replace(" ", "-") if text else None
            log(f"  → Claim number (OCR): {claim_number}")
        except Exception:
            log(f"  [WARN] OCR unavailable — crop at: {crop_path}")
    else:
        log("  [WARN] Could not crop claim number zone")

    screenshot("paso_30_completo.png", f"claim {claim_number or 'OCR-FAILED'} generated")

    if not claim_number:
        log("  [!] Claim number not read by OCR — check crop manually")

    log(f"[OK] Claim saved — No. de Reclamo: {claim_number or '(check crop)'}")
    return claim_number


def simulate_save() -> None:
    """
    Simulate the save step to calibrate OCR without creating a real claim.
    Sequence: Enter → Alt (activate toolbar) → Down (select floppy) → ESC (cancel).
    Then navigates to Generales (1) and crops the claim number zone for inspection.
    """
    import pyautogui
    from premium.ocr import crop_claim_number_field, locate_titlebar

    log("\n[→] Save simulation — calibrating OCR (no real claim)...")

    try:
        rdp = _get_rdp()
        rdp.set_focus()
        time.sleep(0.40)
    except Exception as exc:
        log(f"  [WARN] RDP window not found: {exc}")
        return

    def _k(keys, pause=0.40):
        rdp.type_keys(keys, pause=0.05, with_spaces=True)
        time.sleep(pause)

    log("  → Enter (confirm amount)...")
    _k("{ENTER}", pause=0.80)
    screenshot("paso_sim_01a_monto_confirmado.png", "amount confirmed")

    log("  → Alt (activate Oracle Forms toolbar)...")
    _k("{VK_MENU}", pause=0.60)
    screenshot("paso_sim_01b_toolbar_activa.png", "toolbar activated")

    log("  → Down (select floppy)...")
    _k("{DOWN}", pause=0.60)
    screenshot("paso_sim_01c_disquete_seleccionado.png", "floppy selected")

    log("  → ESC (cancel without saving)...")
    _k("{ESC}", pause=0.60)
    screenshot("paso_sim_01d_cancelado.png", "ESC — save cancelled")
    log("  → Alt+Down+ESC complete — toolbar closed without saving")

    tab2_tpl = T("tab_generales_2.png")
    res_tpl  = T("tab_reservas.png")

    loc_tb_focus = locate_titlebar()
    if loc_tb_focus:
        fx = int(loc_tb_focus.left + loc_tb_focus.width / 2)
        fy = int(loc_tb_focus.top  + loc_tb_focus.height + 80)
        pyautogui.click(fx, fy)
        time.sleep(0.60)
        log(f"  → Re-focus Oracle Forms ({fx}, {fy})")
        screenshot("paso_sim_02a_refoco.png", "Oracle Forms re-focused")

    g1_ok = False
    for conf in (0.85, 0.75, 0.65):
        try:
            loc = pyautogui.locateOnScreen(tab2_tpl, confidence=conf)
            if loc and loc.left > 100:
                cx = int(loc.left - loc.width * 0.5)
                cy = int(loc.top  + loc.height / 2)
                pyautogui.click(cx, cy)
                time.sleep(0.80)
                log(f"  → Click Generales (1) via G2 offset (conf={conf}) ({cx}, {cy})")
                g1_ok = True
                break
            elif loc:
                log(f"  [SKIP] G2 at x={int(loc.left)} (< 100) conf={conf} — possible false positive")
        except pyautogui.ImageNotFoundException:
            pass
        except Exception as exc:
            log(f"  [WARN] Error searching G2 (conf={conf}): {exc}")

    if not g1_ok:
        for conf in (0.85, 0.75, 0.65):
            try:
                loc_r = pyautogui.locateOnScreen(res_tpl, confidence=conf)
                if loc_r and loc_r.left > 100:
                    cx = int(loc_r.left - loc_r.width * 4)
                    cy = int(loc_r.top  + loc_r.height / 2)
                    if cx > 50:
                        pyautogui.click(cx, cy)
                        time.sleep(0.80)
                        log(f"  → Click Generales (1) via Reservas offset (conf={conf}) ({cx}, {cy})")
                        g1_ok = True
                        break
            except pyautogui.ImageNotFoundException:
                pass
            except Exception as exc:
                log(f"  [WARN] Error searching Reservas (conf={conf}): {exc}")

    if not g1_ok:
        log("  [WARN] Could not navigate to G1 — capturing current state")

    screenshot("paso_sim_02_generales1.png", "state after navigating to G1")
    screenshot("paso_sim_03_contexto_g1_completo.png", "full G1 context — OCR reference")
    crop_claim_number_field("paso_sim_04_zona_ocr_reclamo.png")

    log("[OK] Simulation complete — no claim created")
    log(f"     Check captures in: {CAPTURES_DIR}")
    log("      · paso_sim_03_contexto_g1_completo.png — full G1 screen")
    log("      · paso_sim_04_zona_ocr_reclamo.png     — claim number crop")
    if not os.path.isfile(T("label_no_reclamo.png")):
        log()
        log("  [NEXT STEP] Create the label template:")
        log("    1. Open paso_sim_03_contexto_g1_completo.png")
        log("    2. Crop only the text 'No. de Reclamo' (not the field)")
        log(f"    3. Save as: {T('label_no_reclamo.png')}")
