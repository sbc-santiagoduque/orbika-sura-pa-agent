"""
Genera un informe Excel desde estado.json + JSONs de datos por caso.

Uso:
    python scripts/generar_informe.py
    python scripts/generar_informe.py --estado scripts/estado/estado.json --salida informe.xlsx
    python scripts/generar_informe.py --fecha 2026-05-07   # filtrar solo casos de esa fecha
    python scripts/generar_informe.py --reporte report.xls  # solo casos del reporte Salesforce
"""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_DIR = Path(__file__).parent
_ESTADO_DEFAULT = _DIR / "estado" / "estado.json"
_DATOS_DIR      = _DIR / "datos"
_SALIDA_DEFAULT = _DIR / f"informe_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"

# ---------------------------------------------------------------------------
# Colores por estado
# ---------------------------------------------------------------------------
_COLORES = {
    "COMPLETADO":       "C6EFCE",  # verde
    "RECLAMO_EXISTENTE":"FFEB9C",  # amarillo
    "ERROR_PERMANENTE": "FFC7CE",  # rojo
    "FASE_B_INICIADO":  "DDEBF7",  # azul claro
    "FASE_A_OK":        "E2EFDA",  # verde pálido
    "PENDIENTE":        "F2F2F2",  # gris
}

_ETIQUETAS = {
    "COMPLETADO":        "Completado",
    "RECLAMO_EXISTENTE": "Reclamo ya existía",
    "ERROR_PERMANENTE":  "Error permanente",
    "FASE_B_INICIADO":   "Phase B iniciada",
    "FASE_A_OK":         "Phase A OK (sin Phase B)",
    "PENDIENTE":         "Pendiente",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cargar_datos_caso(case_number: str) -> dict:
    path = _DATOS_DIR / f"{case_number}.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("reclamo_data", {})
    return {}


def _fmt_ts(ts: str) -> str:
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        local = dt.astimezone()
        return local.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ts


def _border():
    s = Side(style="thin", color="BFBFBF")
    return Border(left=s, right=s, top=s, bottom=s)


def _header_fill(hex_color: str) -> PatternFill:
    return PatternFill("solid", fgColor=hex_color)


def _cell_fill(hex_color: str) -> PatternFill:
    return PatternFill("solid", fgColor=hex_color)


# ---------------------------------------------------------------------------
# Construir filas de detalle
# ---------------------------------------------------------------------------

def _construir_filas(
    estado: dict,
    filtro_fecha: str | None,
    filtro_casos: set[str] | None = None,
) -> list[dict]:
    filas = []
    for case_number, info in estado.items():

        # Filtro por reporte: solo casos presentes en el XLS/CSV indicado
        if filtro_casos is not None and case_number not in filtro_casos:
            continue

        ts = info.get("ts_completado", "")

        if filtro_fecha:
            if not ts or not ts.startswith(filtro_fecha):
                if info.get("estado") not in ("COMPLETADO",):
                    pass
                else:
                    continue

        datos = _cargar_datos_caso(case_number)
        siniestro  = datos.get("siniestro",  {})
        conductor  = datos.get("conductor",  {})
        poliza     = datos.get("poliza",     {})

        filas.append({
            "N° Caso":           case_number,
            "N° Póliza":         info.get("numero_poliza", datos.get("numero_poliza", "")),
            "Estado":            info.get("estado", ""),
            "Etiqueta":          _ETIQUETAS.get(info.get("estado", ""), info.get("estado", "")),
            "N° Reclamo":        info.get("numero_reclamo", ""),
            "Completado":        _fmt_ts(ts),
            "Intentos A":        info.get("intentos_a", ""),
            "Intentos B":        info.get("intentos_b", ""),
            "Tipo Siniestro":    siniestro.get("tipo", ""),
            "Fecha Siniestro":   siniestro.get("fecha", ""),
            "Conductor Nombre":  f"{conductor.get('nombre', '')} {conductor.get('apellido', '')}".strip(),
            "Conductor Cédula":  conductor.get("cedula", ""),
            "Cobertura":         poliza.get("cobertura", ""),
            "Detalle":           info.get("detalle", ""),
        })
    return filas


# ---------------------------------------------------------------------------
# Hoja Detalle
# ---------------------------------------------------------------------------

def _escribir_detalle(ws, filas: list[dict]):
    columnas = [
        "N° Caso", "N° Póliza", "Estado", "Etiqueta", "N° Reclamo",
        "Completado", "Intentos A", "Intentos B", "Tipo Siniestro",
        "Fecha Siniestro", "Conductor Nombre", "Conductor Cédula",
        "Cobertura", "Detalle",
    ]

    header_font  = Font(bold=True, color="FFFFFF", size=10)
    header_fill  = _header_fill("2E4057")
    center       = Alignment(horizontal="center", vertical="center", wrap_text=False)
    wrap         = Alignment(horizontal="left",   vertical="center", wrap_text=True)
    brd          = _border()

    # Encabezados
    for col_idx, col_name in enumerate(columnas, start=1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.font   = header_font
        cell.fill   = header_fill
        cell.border = brd
        cell.alignment = center

    ws.row_dimensions[1].height = 20

    # Filas de datos
    for row_idx, fila in enumerate(filas, start=2):
        estado_key = fila.get("Estado", "")
        fill_color = _COLORES.get(estado_key, "FFFFFF")
        row_fill   = _cell_fill(fill_color)

        for col_idx, col_name in enumerate(columnas, start=1):
            val  = fila.get(col_name, "")
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.fill      = row_fill
            cell.border    = brd
            cell.alignment = wrap if col_name in ("Detalle", "Conductor Nombre") else center
            cell.font      = Font(size=9)

    # Anchos de columna
    anchos = {
        "N° Caso": 12, "N° Póliza": 22, "Estado": 18, "Etiqueta": 26,
        "N° Reclamo": 14, "Completado": 18, "Intentos A": 11,
        "Intentos B": 11, "Tipo Siniestro": 16, "Fecha Siniestro": 15,
        "Conductor Nombre": 28, "Conductor Cédula": 16,
        "Cobertura": 16, "Detalle": 40,
    }
    for col_idx, col_name in enumerate(columnas, start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = anchos.get(col_name, 14)

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(columnas))}1"


# ---------------------------------------------------------------------------
# Hoja Resumen
# ---------------------------------------------------------------------------

def _escribir_resumen(ws, filas: list[dict], fecha_informe: str):
    # Título
    ws.merge_cells("A1:D1")
    title_cell = ws["A1"]
    title_cell.value     = f"Informe de Procesamiento — {fecha_informe}"
    title_cell.font      = Font(bold=True, size=13, color="FFFFFF")
    title_cell.fill      = _header_fill("2E4057")
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    # Conteos por estado
    conteos: dict[str, int] = {}
    for f in filas:
        conteos[f["Estado"]] = conteos.get(f["Estado"], 0) + 1

    total = len(filas)

    # Encabezados tabla
    headers = ["Estado", "Etiqueta", "Cantidad", "% del Total"]
    header_font = Font(bold=True, color="FFFFFF", size=10)
    header_fill = _header_fill("048A81")
    brd = _border()
    center = Alignment(horizontal="center", vertical="center")

    for col_idx, h in enumerate(headers, start=1):
        c = ws.cell(row=3, column=col_idx, value=h)
        c.font      = header_font
        c.fill      = header_fill
        c.border    = brd
        c.alignment = center

    # Filas de resumen (orden fijo)
    orden = [
        "COMPLETADO", "RECLAMO_EXISTENTE", "FASE_A_OK",
        "FASE_B_INICIADO", "ERROR_PERMANENTE", "PENDIENTE",
    ]
    row = 4
    for estado in orden:
        cantidad = conteos.get(estado, 0)
        if cantidad == 0:
            continue
        pct = f"{cantidad / total * 100:.1f}%" if total else "0%"
        fill_color = _COLORES.get(estado, "FFFFFF")

        datos_fila = [estado, _ETIQUETAS.get(estado, estado), cantidad, pct]
        for col_idx, val in enumerate(datos_fila, start=1):
            c = ws.cell(row=row, column=col_idx, value=val)
            c.fill      = _cell_fill(fill_color)
            c.border    = brd
            c.alignment = center
            c.font      = Font(size=10, bold=(col_idx == 3))
        row += 1

    # Fila total
    for col_idx, val in enumerate(["TOTAL", "", total, "100%"], start=1):
        c = ws.cell(row=row, column=col_idx, value=val)
        c.font      = Font(bold=True, size=10)
        c.fill      = _header_fill("2E4057")
        c.fill.fgColor.rgb = "2E4057"
        c.font      = Font(bold=True, color="FFFFFF", size=10)
        c.border    = brd
        c.alignment = center

    # Anchos
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 30
    ws.column_dimensions["C"].width = 12
    ws.column_dimensions["D"].width = 14

    # Métricas adicionales
    completados    = conteos.get("COMPLETADO", 0)
    existentes     = conteos.get("RECLAMO_EXISTENTE", 0)
    errores        = conteos.get("ERROR_PERMANENTE", 0)
    procesados_b   = completados + existentes + errores

    row += 2
    metricas = [
        ("Casos procesados por Phase B", procesados_b),
        ("Tasa de éxito (COMPLETADO / procesados B)",
         f"{completados / procesados_b * 100:.1f}%" if procesados_b else "N/A"),
        ("Casos ya tenían reclamo (RECLAMO_EXISTENTE)", existentes),
        ("Errores permanentes (requieren revisión manual)", errores),
    ]
    ws.cell(row=row, column=1, value="Métricas").font = Font(bold=True, size=10)
    row += 1
    for label, val in metricas:
        lc = ws.cell(row=row, column=1, value=label)
        vc = ws.cell(row=row, column=2, value=val)
        lc.font = Font(size=9)
        vc.font = Font(bold=True, size=9)
        lc.border = brd
        vc.border = brd
        row += 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _leer_casos_reporte(path: str) -> set[str]:
    """Extrae los case_numbers del XLS/CSV de Salesforce usando la misma lógica de procesar_casos."""
    import sys
    sys.path.insert(0, str(_DIR))
    from procesar_casos import _leer_reporte, _normalizar_casos  # noqa: PLC0415
    casos_raw = _leer_reporte(path)
    casos     = _normalizar_casos(casos_raw)
    return {c["case_number"] for c in casos if c["case_number"]}


def main():
    parser = argparse.ArgumentParser(description="Genera informe Excel desde estado.json")
    parser.add_argument("--estado",   default=str(_ESTADO_DEFAULT), help="Path al estado.json")
    parser.add_argument("--salida",   default=str(_SALIDA_DEFAULT), help="Path del Excel de salida")
    parser.add_argument("--fecha",    default=None, help="Filtrar COMPLETADO por fecha (YYYY-MM-DD)")
    parser.add_argument("--reporte",  default=None,
                        help="XLS/CSV del reporte Salesforce — solo muestra casos de ese reporte")
    args = parser.parse_args()

    with open(args.estado, encoding="utf-8") as f:
        estado = json.load(f)

    print(f"Casos en estado.json: {len(estado)}")

    filtro_casos = None
    if args.reporte:
        filtro_casos = _leer_casos_reporte(args.reporte)
        print(f"Reporte '{Path(args.reporte).name}': {len(filtro_casos)} casos encontrados")

    filas = _construir_filas(estado, filtro_fecha=args.fecha, filtro_casos=filtro_casos)

    fecha_informe = args.fecha or datetime.now().strftime("%Y-%m-%d")
    if args.reporte:
        fecha_informe = f"{fecha_informe} · {Path(args.reporte).stem}"

    wb = openpyxl.Workbook()

    # Hoja Resumen (primera)
    ws_resumen = wb.active
    ws_resumen.title = "Resumen"
    _escribir_resumen(ws_resumen, filas, fecha_informe)

    # Hoja Detalle
    ws_detalle = wb.create_sheet("Detalle")
    _escribir_detalle(ws_detalle, filas)

    wb.save(args.salida)
    print(f"Informe generado: {args.salida}")
    print(f"  Total filas:  {len(filas)}")

    conteos: dict[str, int] = {}
    for f in filas:
        conteos[f["Estado"]] = conteos.get(f["Estado"], 0) + 1
    for estado_key, cnt in sorted(conteos.items(), key=lambda x: -x[1]):
        print(f"  {_ETIQUETAS.get(estado_key, estado_key):35s} {cnt:4d}")


if __name__ == "__main__":
    main()
