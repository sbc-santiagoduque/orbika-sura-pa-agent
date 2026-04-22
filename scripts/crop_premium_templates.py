"""
Genera templates de menu para open_premium.py a partir de la captura de referencia
docs/screens/p17_menu_apertura.png (1920x1080).

Ejecutar una vez desde la raíz del proyecto:

    python scripts/crop_premium_templates.py

Salida (en docs/screens/):
    titlebar_oracle_forms.png    — título de ventana "Oracle Forms Runtime" (ancla)
    menu_premium.png             — "Premium" en la barra de menú
    menu_1_reclamos.png          — "1-Reclamos" (item 4 del dropdown Premium)
    menu_12_procesos.png         — "1.2-Procesos" (item 2 del dropdown 1-Reclamos)
    menu_121_manejo.png          — "1.2.1-Manejo Reclamos" (item 1 del sub-sub-dropdown)
    menu_1211_apertura.png       — "1.2.1.1-Apertura" (item 1 del último submenu)
    debug_crops_overlay.png      — imagen de referencia con rectángulos de los crops

Todos los crops usan el estado RESALTADO (fondo azul) porque la referencia p17
muestra el camino completo de navegación abierto. Para la navegación real usamos
coordenadas relativas al titlebar, no image matching de items.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PIL import Image, ImageDraw, ImageFont

_SCREENS_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "screens")
_REF = os.path.join(_SCREENS_DIR, "p17_menu_apertura.png")


def crop(img: Image.Image, x1: int, y1: int, x2: int, y2: int, name: str) -> None:
    """Recorta una región y la guarda en docs/screens/."""
    region = img.crop((x1, y1, x2, y2))
    out = os.path.join(_SCREENS_DIR, name)
    region.save(out)
    print(f"  {name:40s}  ({x2-x1}x{y2-y1} px)  [{x1},{y1} to {x2},{y2}]")


def main():
    if not os.path.isfile(_REF):
        print(f"[ERROR] No se encontró: {_REF}")
        sys.exit(1)

    img = Image.open(_REF).convert("RGB")
    W, H = img.size
    print(f"Referencia: {W}x{H}  ({_REF})\n")

    if W != 1920 or H != 1080:
        print(f"[WARN] Imagen no es 1920x1080 — crops pueden no ser precisos")

    os.makedirs(_SCREENS_DIR, exist_ok=True)

    print("Generando templates...")

    # ── Ancla: título de la ventana Oracle Forms Runtime ─────────────────────
    # Fondo azul oscuro del título con "Oracle Forms Runtime" en blanco.
    # Se usa en _navegar_apertura_reclamo() para encontrar la posición de la ventana.
    crop(img, 168, 60,  580, 92,  "titlebar_oracle_forms.png")

    # ── Barra de menú: "Premium" (resaltado en azul en p17) ──────────────────
    crop(img, 265, 88,  360, 114, "menu_premium.png")

    # ── Dropdown Premium: "1-Reclamos" (4to ítem, resaltado) ─────────────────
    # Blue region medida: x=171-279, y=192-218 (center 225, 205)
    crop(img, 171, 192, 279, 218, "menu_1_reclamos.png")

    # ── Submenu 1-Reclamos: "1.2-Procesos" (2do ítem, resaltado) ─────────────
    # Blue region medida: x=468-549, y=225-252 (center 508, 238)
    crop(img, 400, 225, 560, 252, "menu_12_procesos.png")

    # ── Submenu 1.2-Procesos: "1.2.1-Manejo Reclamos" (1er ítem, resaltado) ──
    # Blue region medida: x=590-846, y=225-252 (center 718, 239)
    crop(img, 590, 225, 850, 252, "menu_121_manejo.png")

    # ── Submenu 1.2.1: "1.2.1.1-Apertura" (1er ítem, resaltado) ─────────────
    # Blue region medida: x=990-1249, y=225-252 (center 1119, 238)
    crop(img, 990, 225, 1250, 252, "menu_1211_apertura.png")

    # ── Debug: superposición visual de todos los crops ────────────────────────
    debug = img.copy()
    draw = ImageDraw.Draw(debug)
    rects = [
        ("titlebar",  168, 60,   580,  92,  "red"),
        ("Premium",   265, 88,   360,  114, "yellow"),
        ("1-Reclamos",171, 192,  279,  218, "lime"),
        ("1.2-Procs", 400, 225,  560,  252, "cyan"),
        ("1.2.1-Man", 590, 225,  850,  252, "magenta"),
        ("1.2.1.1-Ap",990, 225, 1250,  252, "orange"),
    ]
    for label, x1, y1, x2, y2, color in rects:
        draw.rectangle([x1, y1, x2, y2], outline=color, width=3)
        draw.text((x1 + 2, y1 + 2), label, fill=color)

    debug_path = os.path.join(_SCREENS_DIR, "debug_crops_overlay.png")
    debug.save(debug_path)
    print(f"\n  {'debug_crops_overlay.png':40s}  (verificación visual)")

    print(f"\n[OK] Templates guardados en: {os.path.abspath(_SCREENS_DIR)}")
    print(f"    Abri debug_crops_overlay.png para verificar que los recortes son correctos.")
    print(f"    Si algun recorte esta mal, ajusta las coordenadas en este script y re-ejecuta.")


if __name__ == "__main__":
    main()
