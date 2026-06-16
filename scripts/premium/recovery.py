"""Recovery helpers: close Oracle Forms popups and MDI windows."""
import os
import time

from premium.common import T, log, screenshot, find_on_screen


def detect_modal_type() -> str:
    """
    Classify the Oracle Forms modal currently on screen.
    Returns 'frm_validation' | 'unauthorized' | 'close_confirm' | 'unknown' | 'none'.

    Requires templates in docs/screens/:
      modal_frm_validation.png  — FRM-40202 'Se debe ingresar al campo' (blue !, OK)
      modal_unauthorized.png    — error de autorización / permisos
      modal_cerrar_pantalla.png — '¿Cerrar esta pantalla?' (yellow ⚠, Sí/No)
                                   Aparece al cerrar sin completar campos.
                                   En go_back_one_tab: Sí (Enter) — cierre intencional.
                                   En save_claim: No (Tab+Enter) — cierre inesperado.

    Sin esos templates, cualquier modal visible devuelve 'unknown' y se
    guarda una captura para facilitar la creación del template.
    """
    generic_tpl  = T("titlebar_forms_modal.png")
    fallback_tpl = T("modal_ok_forms.png")
    tpl = generic_tpl if os.path.isfile(generic_tpl) else (
          fallback_tpl if os.path.isfile(fallback_tpl) else None)
    if tpl is None or find_on_screen(tpl, confidence=0.75) is None:
        return "none"

    frm_tpl    = T("modal_frm_validation.png")
    unauth_tpl = T("modal_unauthorized.png")
    close_tpl  = T("modal_cerrar_pantalla.png")

    if os.path.isfile(frm_tpl) and find_on_screen(frm_tpl, confidence=0.80) is not None:
        return "frm_validation"

    if os.path.isfile(unauth_tpl) and find_on_screen(unauth_tpl, confidence=0.80) is not None:
        return "unauthorized"

    if os.path.isfile(close_tpl) and find_on_screen(close_tpl, confidence=0.80) is not None:
        return "close_confirm"

    screenshot("modal_tipo_desconocido.png",
               "modal visible — tipo no identificado, recortar para crear template")
    log("  [WARN] Modal detectado sin tipo identificado — ver modal_tipo_desconocido.png")
    return "unknown"


def close_forms_popup() -> bool:
    """
    Detect any Oracle Forms popup (titlebar_forms_modal.png).
    If visible, press Enter (OK) and return True.
    Falls back to modal_ok_forms.png if the generic titlebar template is absent.
    """
    import pyautogui
    template = T("titlebar_forms_modal.png")
    if not os.path.isfile(template):
        template = T("modal_ok_forms.png")
        if not os.path.isfile(template):
            return False
    if find_on_screen(template, confidence=0.75) is None:
        return False
    screenshot("popup_forms_detected.png", "Forms popup detected")
    pyautogui.hotkey("enter")
    time.sleep(0.6)
    log("  → Forms popup closed (Enter/OK)")
    return True


def close_endosos_form() -> None:
    """
    Close 'Consulta de Endosos' by clicking its MDI X button.
    Fallback: Ctrl+F4 via pyautogui.
    """
    import pyautogui
    template = T("titlebar_consulta_endosos.png")
    if os.path.isfile(template):
        try:
            loc = pyautogui.locateOnScreen(template, confidence=0.80)
            if loc:
                cx = int(loc.left + loc.width  / 2)
                cy = int(loc.top  + loc.height / 2)
                pyautogui.click(cx, cy)
                time.sleep(0.80)
                screenshot("consulta_endosos_closed.png", "form closed via X")
                log("  → Consulta de Endosos closed (click X)")
                return
        except Exception as exc:
            log(f"  [WARN] X template not found: {exc}")

    try:
        from premium.rdp import get_rdp_window
        rdp = get_rdp_window()
        rdp.set_focus()
        time.sleep(0.30)
    except Exception:
        pass
    pyautogui.hotkey("ctrl", "f4")
    time.sleep(0.80)
    screenshot("consulta_endosos_closed.png", "form closed Ctrl+F4 fallback")
    log("  → Form closed (Ctrl+F4 fallback)")


def close_vehicle_screens() -> None:
    """
    Close stacked MDI forms after 'Siniestro fuera de vigencia':
      1. Consulta de Automóviles Asegurados → X
      2. Possible Oracle Forms confirmation  → Enter
      3. Consulta de Endosos                → X
    """
    log("  → Closing Consulta de Automóviles Asegurados...")
    close_endosos_form()

    time.sleep(0.5)
    if close_forms_popup():
        log("  → Post-close confirmation dismissed (Enter)")

    time.sleep(0.5)
    log("  → Closing Consulta de Endosos...")
    close_endosos_form()


def close_modal_no() -> bool:
    """
    If an Oracle Forms modal is visible, press Tab+Enter to click 'No'
    (focus defaults to 'Sí'). Returns True if a modal was detected.
    """
    template = T("titlebar_forms_modal.png")
    fallback  = T("modal_ok_forms.png")
    tpl = template if os.path.isfile(template) else (fallback if os.path.isfile(fallback) else None)
    if tpl is None:
        return False
    if find_on_screen(tpl, confidence=0.75) is None:
        return False

    screenshot("modal_save_detected.png", "save modal detected")
    try:
        from premium.rdp import get_rdp_window
        rdp = get_rdp_window()
        rdp.set_focus()
        time.sleep(0.20)
        rdp.type_keys("{TAB}",   pause=0.05, with_spaces=True)
        time.sleep(0.20)
        rdp.type_keys("{ENTER}", pause=0.05, with_spaces=True)
        time.sleep(0.50)
    except Exception as exc:
        import pyautogui as _pag
        log(f"  [WARN] pywinauto unavailable for 'No' modal: {exc} — using Tab+Enter pyautogui")
        _pag.hotkey("tab")
        time.sleep(0.15)
        _pag.hotkey("enter")
        time.sleep(0.50)

    log("  → Modal closed with 'No' (Tab+Enter)")
    return True


def is_at_main_menu() -> bool:
    """Return True if menu_1_reclamos.png is visible — Oracle Forms is at the main menu."""
    import pyautogui
    tpl = T("menu_1_reclamos.png")
    if not os.path.isfile(tpl):
        return False
    try:
        return pyautogui.locateOnScreen(tpl, confidence=0.80) is not None
    except pyautogui.ImageNotFoundException:
        return False
    except Exception:
        return False


def close_claim_and_return_home() -> None:
    """
    Close stacked MDI windows (claim, Coberturas, Automóviles, Endosos)
    by clicking X until the main menu is detected. Max 15 iterations.

    After each X click, loops on close_forms_popup() up to 3 times —
    Oracle Forms can show consecutive confirmation modals for a single
    close (e.g. unsaved changes + inner child confirmation), so one
    Enter is not always enough before the next X click is safe.
    """
    _MAX = 15
    _MAX_POPUPS = 3

    log("\n[→] Closing forms — returning to main screen...")

    for attempt in range(1, _MAX + 1):
        if is_at_main_menu():
            log(f"  → Main menu detected (attempt {attempt})")
            break

        log(f"  → Closing MDI {attempt}...")
        close_endosos_form()
        time.sleep(0.50)
        screenshot(f"paso_cierre_{attempt:02d}.png", f"MDI close {attempt}")

        dismissed = 0
        for _ in range(_MAX_POPUPS):
            if not close_forms_popup():
                break
            dismissed += 1
            time.sleep(0.25)
        if dismissed:
            screenshot(f"paso_cierre_{attempt:02d}b_post_si.png",
                       f"post-modal(s) Sí ({attempt}×{dismissed})")
    else:
        log(f"  [WARN] Reached {_MAX} close attempts without detecting main menu")

    screenshot("paso_cierre_pantalla_principal.png", "Oracle Forms main screen")
    log("[OK] Returned to main screen — ready for next case")
