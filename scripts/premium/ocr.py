"""OCR helpers: locate Oracle Forms titlebar, crop claim-number field."""
import os

from premium.common import T, log, find_on_screen, CAPTURES_DIR, TITLEBAR_REF


def locate_titlebar():
    """
    Locate titlebar_oracle_forms.png with descending confidence (0.70→0.50).
    Returns pyautogui Box or None.
    """
    import pyautogui
    tpl = T("titlebar_oracle_forms.png")
    if not os.path.isfile(tpl):
        return None
    for conf in (0.70, 0.60, 0.55, 0.50):
        try:
            loc = pyautogui.locateOnScreen(tpl, confidence=conf)
            if loc:
                log(f"  → Titlebar found (confidence={conf}): ({int(loc.left)}, {int(loc.top)})")
                return loc
        except pyautogui.ImageNotFoundException:
            pass
        except Exception:
            pass
    log("  [WARN] titlebar_oracle_forms.png not found at any threshold (0.70–0.50)")
    return None


def crop_claim_number_field(filename: str) -> str | None:
    """
    Locate 'No. de Reclamo' field and save a crop of its value.
    Strategy 1: label_no_reclamo.png template anchor (below label).
    Strategy 2: fixed offset from Oracle Forms titlebar.
    Returns saved crop path or None.
    """
    import pyautogui

    os.makedirs(CAPTURES_DIR, exist_ok=True)
    crop_path = os.path.join(CAPTURES_DIR, filename)
    label_tpl = T("label_no_reclamo.png")

    if os.path.isfile(label_tpl):
        for conf in (0.85, 0.75, 0.65):
            try:
                loc = pyautogui.locateOnScreen(label_tpl, confidence=conf)
                if loc and loc.left > 0:
                    vx1 = int(loc.left)
                    vy1 = int(loc.top + loc.height) + 2
                    vx2 = vx1 + 200
                    vy2 = vy1 + 30
                    img = pyautogui.screenshot(region=(vx1, vy1, vx2 - vx1, vy2 - vy1))
                    img.save(crop_path)
                    log(f"  → Crop 'No. de Reclamo' via label (conf={conf}): ({vx1},{vy1})→({vx2},{vy2})")
                    log(f"     Saved: {crop_path}")
                    return crop_path
            except pyautogui.ImageNotFoundException:
                pass
            except Exception as exc:
                log(f"  [WARN] Error searching label_no_reclamo (conf={conf}): {exc}")
        log("  [WARN] label_no_reclamo.png not found on screen")

    loc_tb = locate_titlebar()
    if loc_tb:
        dx  = int(loc_tb.left) - TITLEBAR_REF[0]
        dy  = int(loc_tb.top)  - TITLEBAR_REF[1]
        rx1 = 168 + dx
        ry1 = 240 + dy
        rx2 = 420 + dx
        ry2 = 265 + dy
        img = pyautogui.screenshot(region=(rx1, ry1, rx2 - rx1, ry2 - ry1))
        img.save(crop_path)
        log(f"  → Crop 'No. de Reclamo' via titlebar offset: ({rx1},{ry1})→({rx2},{ry2})")
        log(f"     Saved: {crop_path}")
        if not os.path.isfile(label_tpl):
            log("     [NOTE] Create label_no_reclamo.png for greater precision")
        return crop_path

    log("  [WARN] Could not calculate 'No. de Reclamo' zone — neither label nor titlebar available")
    return None
