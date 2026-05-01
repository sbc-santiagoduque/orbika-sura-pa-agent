"""
Pipeline principal: Bandeja CRM -> Phase A (SIC) -> Phase B (Premium RPA).

Diseñado para correr de noche sin supervisión. Características:
  - Checkpoint por caso (scripts/estado/estado.json) — reanuda donde quedó
  - Retry con backoff para Phase A y Phase B
  - VPN watchdog antes de cada caso (RDP como proxy de VPN)
  - Reconexión FortiClient + notificación Telegram para aprobación 2FA
  - Contador de "N casos sin avance" en lugar de circuit breaker duro
  - Notificaciones Telegram + log interno

Uso:
    # Dry-run: listar casos pendientes
    python scripts/procesar_casos.py --reporte reporte.xls --dry-run

    # Phase A (recolectar datos SIC) para todos los pendientes
    python scripts/procesar_casos.py --reporte reporte.xls

    # Phase A + Phase B (requiere RDP activo, Premium abierto)
    python scripts/procesar_casos.py --reporte reporte.xls --fase-b

    # Phase A + Phase B + guardar reclamos reales
    python scripts/procesar_casos.py --reporte reporte.xls --fase-b --guardar

    # Sin VPN watchdog (sesión ya estable)
    python scripts/procesar_casos.py --reporte reporte.xls --sin-vpn-check

Variables de entorno (.env):
    SIC_USERNAME, SIC_PASSWORD, SIC_API_BASE_URL
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    VPN_FORTICLIENT_PATH, VPN_PROFILE_NAME, VPN_HOST_INTERNO, VPN_2FA_TIMEOUT
    RDP_HOST, RDP_USERNAME, RDP_PASSWORD, PREMIUM_USERNAME, PREMIUM_PASSWORD
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Cargar .env
_dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
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

_SCRIPT_DIR = Path(__file__).parent
_DATOS_DIR  = _SCRIPT_DIR / "datos"
_ESTADO_DIR = _SCRIPT_DIR / "estado"
_LOGS_DIR   = _SCRIPT_DIR / "resultados"

_SIC_BASE_URL_DEFAULT = "https://api-bkp.claims-sic.apps-connectassistance.com"

# Casos consecutivos sin avance antes de detener el pipeline
_MAX_SIN_AVANCE_DEFAULT = 5


# ---------------------------------------------------------------------------
# Parsing del reporte HTML/XLS de Salesforce
# ---------------------------------------------------------------------------

class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] = []
        self._cell = ""
        self._in_cell = False

    def handle_starttag(self, tag, attrs):
        if tag in ("td", "th"):
            self._in_cell = True
            self._cell = ""
        elif tag == "tr":
            self._row = []

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self._row.append(self._cell.strip())
            self._in_cell = False
        elif tag == "tr":
            if any(c for c in self._row):
                self.rows.append(self._row)

    def handle_data(self, data):
        if self._in_cell:
            self._cell += data


def _leer_reporte(path: str) -> list[dict]:
    """
    Lee el reporte de Salesforce en cualquier formato:
      - .xlsx  → openpyxl (detecta fila de headers automáticamente)
      - .csv   → csv.DictReader (UTF-8-BOM, UTF-8 o latin-1)
      - .xls   → HTML disfrazado de Excel (export legacy Salesforce)
    """
    ext = Path(path).suffix.lower()
    if ext == ".xlsx":
        return _leer_xlsx(path)
    if ext == ".csv":
        return _leer_csv(path)
    return _leer_html_xls(path)


_HEADER_CASE_NUMBER = {
    "case number",          # Salesforce EN
    "número de caso",       # Salesforce ES "de" (con tilde)
    "numero de caso",       # Salesforce ES "de" (sin tilde)
    "número del caso",      # Salesforce ES "del" (con tilde)
    "numero del caso",      # Salesforce ES "del" (sin tilde)
    "case no",
    "caso",
}


def _leer_xlsx(path: str) -> list[dict]:
    import openpyxl
    import warnings as _w
    _w.filterwarnings("ignore", category=UserWarning, module="openpyxl")
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    # Buscar la fila de headers: contiene una celda que coincida con cualquier
    # variante de "Case Number" (EN/ES, con o sin tilde).
    header_idx = None
    for i, row in enumerate(rows):
        for c in row:
            norm = str(c or "").strip().lower()
            if norm in _HEADER_CASE_NUMBER:
                header_idx = i
                break
        if header_idx is not None:
            break

    if header_idx is None or header_idx >= len(rows) - 1:
        print("[WARN] No se encontró fila de headers en el XLSX.")
        print("       Buscando columna con alguno de estos nombres:", sorted(_HEADER_CASE_NUMBER))
        # Mostrar la primera fila con más de 1 celda no vacía (candidata a headers)
        for i, r in enumerate(rows):
            cells = [str(c or "").strip() for c in r if c is not None and str(c or "").strip()]
            if len(cells) > 1:
                print(f"       Primera fila multi-columna (fila {i + 1}): {cells}")
                break
        else:
            print("       No se encontró ninguna fila con múltiples columnas en el archivo.")
        return []

    headers = [str(h).strip() if h is not None else "" for h in rows[header_idx]]
    casos = []
    for row in rows[header_idx + 1:]:
        cells = [str(c).strip() if c is not None else "" for c in row]
        if not any(cells):
            continue
        padded = cells + [""] * (len(headers) - len(cells))
        casos.append(dict(zip(headers, padded)))
    return casos


def _leer_csv(path: str) -> list[dict]:
    import csv
    # Intentar encodings en orden: UTF-8 con BOM (export Windows), UTF-8, latin-1
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            with open(path, newline="", encoding=enc) as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            if rows:
                return rows
        except (UnicodeDecodeError, csv.Error):
            continue
    return []


def _leer_html_xls(path: str) -> list[dict]:
    with open(path, encoding="utf-8", errors="replace") as f:
        html = f.read()
    parser = _TableParser()
    parser.feed(html)
    if len(parser.rows) < 2:
        return []
    headers = [h.strip() for h in parser.rows[0]]
    casos = []
    for row in parser.rows[1:]:
        padded = row + [""] * (len(headers) - len(row))
        casos.append(dict(zip(headers, padded)))
    return casos


def _get(row: dict, *keys: str) -> str:
    """Busca el primer key no vacío en el dict, insensible a mayúsculas."""
    row_lower = {k.lower(): v for k, v in row.items()}
    for k in keys:
        v = row_lower.get(k.lower(), "")
        if v:
            return str(v).strip()
    return ""


def _normalizar_casos(casos_raw: list[dict]) -> list[dict]:
    resultado = []
    for c in casos_raw:
        case_number = _get(c,
            "Case Number",
            "Número de caso", "Numero de caso",
            "Número del caso", "Numero del caso",
            "Case No",
        )
        placa = _get(c,
            "Placa", "Placa Afectado", "Placa del afectado",
            "Vehicle Plate", "Plate",
        ).upper()
        expediente_sic = _get(c,
            "Expediente SIC", "Expediente",
        )
        reclamo_core = _get(c,
            "Numero de reclamo en el core",
            "Número de reclamo en el core",
            "N�mero de reclamo en el core",
            "N?mero de reclamo en el core",
            "Número de reclamo en el core",
            "Reclamo Core", "Core Claim Number",
        )
        fecha_apertura = _get(c, "Opened Date", "Fecha de apertura", "Fecha Apertura")
        case_origin    = _get(c, "Case Origin", "Origen del caso", "Origen")

        if not case_number or not placa:
            continue
        resultado.append({
            "case_number":    case_number,
            "placa":          placa,
            "expediente_sic": expediente_sic,
            "reclamo_core":   reclamo_core,
            "fecha_apertura": fecha_apertura,
            "case_origin":    case_origin,
        })
    return resultado


def casos_pendientes(casos: list[dict]) -> list[dict]:
    """Casos de origen SIC que NO tienen reclamo creado en el core."""
    return [
        c for c in casos
        if not c["reclamo_core"] and c.get("case_origin", "").upper() == "SIC"
    ]


# ---------------------------------------------------------------------------
# Phase A: recolección de datos SIC
# ---------------------------------------------------------------------------

class _CredStub:
    def __init__(self, username: str, password: str):
        self._u = username
        self._p = password

    def load_credentials(self) -> tuple[str, str]:
        return self._u, self._p


def _construir_ci_client(ci_url: str | None):
    if ci_url:
        from src.tools.create_reclamo_premium.infrastructure.consulta_integral_scraper import (
            ConsultaIntegralClient,
        )
        return ConsultaIntegralClient(ci_base_url=ci_url)
    from src.tools.create_reclamo_premium.infrastructure.consulta_integral_scraper import (
        ConsultaIntegralClientStub,
    )
    return ConsultaIntegralClientStub()


class _CIWatchdog:
    """
    Envuelve el cliente CI con un circuit breaker simple.
    Después de `max_fallos` timeouts consecutivos lo desactiva
    y lanza RuntimeError inmediatamente, sin esperar al timeout de red.
    """
    def __init__(self, cliente, max_fallos: int, notif):
        self._c       = cliente
        self._max     = max_fallos
        self._notif   = notif
        self._fallos  = 0
        self._abierto = False

    def obtener_datos_poliza(self, placa: str, fecha_siniestro=None):
        if self._abierto:
            raise RuntimeError("CI circuit breaker abierto — usando SIC directo")
        try:
            resultado = self._c.obtener_datos_poliza(placa, fecha_siniestro)
            self._fallos = 0
            return resultado
        except RuntimeError as exc:
            if "timed out" in str(exc).lower() or "timeout" in str(exc).lower():
                self._fallos += 1
                if self._fallos >= self._max:
                    self._abierto = True
                    self._notif.alerta(
                        f"CI desactivado por {self._max} timeouts consecutivos"
                        " — resto del run usa noPoliza de SIC"
                    )
            raise


def _ejecutar_fase_a(caso: dict, sic_username: str, sic_password: str,
                     ci_client=None) -> dict:
    from src.tools.create_reclamo_premium.infrastructure.sic_reclamo_client import SICReclamoClient
    from src.tools.create_reclamo_premium.service.data_collector import DataCollector

    session    = _CredStub(sic_username, sic_password)
    sic_client = SICReclamoClient(session=session)

    collector = DataCollector(sic_client=sic_client, ci_scraper=ci_client)
    reclamo   = collector.recolectar(
        case_number=caso["case_number"],
        placa=caso["placa"],
        expediente=caso["expediente_sic"],
    )
    return reclamo.to_dict()


# ---------------------------------------------------------------------------
# Phase B: automatización Premium (subprocess)
# ---------------------------------------------------------------------------

_EXIT_RECLAMO_EXISTENTE  = 2
_EXIT_RECLAMO_DUPLICADO  = 3
_EXIT_FUERA_VIGENCIA     = 4
_EXIT_NO_AUTORIZADO      = 5
_EXIT_VALIDACION_CAMPO   = 6


def _rdp_activo() -> bool:
    """Retorna True si hay una ventana RDP activa y accesible."""
    try:
        import pygetwindow as gw
        return any(
            ("Escritorio remoto" in t or "Remote Desktop" in t) and " - " in t
            for t in gw.getAllTitles()
        )
    except Exception:
        return False


def _ejecutar_fase_b(datos_json_path: str, guardar: bool = False,
                     case_number: str = "") -> int:
    """
    Invoca open_premium.py para un caso.

    Si la sesión RDP ya está activa → --step apertura (rápido, sin reconectar).
    Si no hay ventana RDP → flujo completo con credenciales de .env
    (abre RDP, loga en Premium y corre apertura).
    """
    if _rdp_activo():
        # RDP activo → Premium ya abierto y logueado → saltar conexión y login
        cmd = [
            sys.executable,
            str(_SCRIPT_DIR / "open_premium.py"),
            "--no-rdp",
            "--no-premium",
            "--datos-json", datos_json_path,
        ]
    else:
        cmd = [
            sys.executable,
            str(_SCRIPT_DIR / "open_premium.py"),
            "--host",             os.environ.get("RDP_HOST", ""),
            "--username",         os.environ.get("RDP_USERNAME", ""),
            "--password",         os.environ.get("RDP_PASSWORD", ""),
            "--premium-username", os.environ.get("PREMIUM_USERNAME", ""),
            "--premium-password", os.environ.get("PREMIUM_PASSWORD", ""),
            "--datos-json",       datos_json_path,
        ]

    if guardar:
        cmd.append("--guardar")
    if case_number:
        cmd += ["--case-number", case_number]

    result = subprocess.run(cmd)
    return result.returncode


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Pipeline nocturno: Bandeja CRM -> Phase A -> Phase B"
    )
    parser.add_argument("--reporte",        required=True,
                        help="Ruta al reporte XLS/HTML de Salesforce")
    parser.add_argument("--ci-url",         default=os.environ.get("CI_BASE_URL"),
                        help="URL base de Consulta Integral (requiere VPN). "
                             "Si se omite, usa stub.")
    parser.add_argument("--fase-b",         action="store_true",
                        help="Ejecutar Phase B despues de Phase A")
    parser.add_argument("--guardar",        action="store_true",
                        help="Pasar --guardar a Phase B (crea reclamos reales)")
    parser.add_argument("--dry-run",        action="store_true",
                        help="Solo listar casos pendientes, sin procesar")
    parser.add_argument("--sin-vpn-check",  action="store_true",
                        help="Omitir watchdog de VPN (sesion ya estable)")
    parser.add_argument("--caso",           default=None,
                        help="Procesar solo este Case Number (util para pruebas paso a paso)")
    parser.add_argument("--casos",          default=None, nargs="+",
                        help="Procesar solo estos Case Numbers separados por coma o espacio (ej: 02213748,02213735 o 02213748 02213735)")
    parser.add_argument("--max-casos",      type=int, default=None,
                        help="Limitar a los primeros N casos pendientes")
    parser.add_argument("--max-sin-avance", type=int, default=_MAX_SIN_AVANCE_DEFAULT,
                        help=f"Casos consecutivos sin avance antes de detener (default: {_MAX_SIN_AVANCE_DEFAULT})")
    parser.add_argument("--username",       default=os.environ.get("SIC_USERNAME", ""))
    parser.add_argument("--password",       default=os.environ.get("SIC_PASSWORD", ""))
    parser.add_argument("--base-url",       default=os.environ.get("SIC_API_BASE_URL",
                                                                    _SIC_BASE_URL_DEFAULT))
    args = parser.parse_args()

    os.environ["SIC_API_BASE_URL"] = args.base_url

    # -- Infraestructura --------------------------------------------------
    ts_run = datetime.now().strftime("%Y%m%d_%H%M%S")
    _DATOS_DIR.mkdir(exist_ok=True)
    _ESTADO_DIR.mkdir(exist_ok=True)
    _LOGS_DIR.mkdir(exist_ok=True)

    log_path    = _LOGS_DIR / f"run_{ts_run}.log"
    estado_path = _ESTADO_DIR / "estado.json"

    from src.shared.notificador import Notificador
    from src.shared.estado_proceso import EstadoProceso, EstadoCaso
    from src.shared.retry import con_reintento, RetryAgotadoError

    notif  = Notificador.desde_env(log_path=log_path)
    estado = EstadoProceso(estado_path)

    # -- Leer y filtrar reporte -------------------------------------------
    notif.info(f"Leyendo reporte: {args.reporte}")
    casos_raw  = _leer_reporte(args.reporte)
    casos      = _normalizar_casos(casos_raw)
    pendientes = casos_pendientes(casos)

    sic_total    = sum(1 for c in casos if c.get("case_origin", "").upper() == "SIC")
    otros_total  = len(casos) - sic_total
    notif.info(
        f"Total en reporte: {len(casos)} "
        f"| SIC: {sic_total} | Otros (omitidos): {otros_total} "
        f"| Ya con reclamo: {len(casos) - len(pendientes) - otros_total} "
        f"| Pendientes SIC: {len(pendientes)}"
    )

    if args.casos:
        _raw = " ".join(args.casos)  # une tokens por si el usuario puso espacio tras la coma
        _filtro = {cn.strip() for cn in _raw.replace(",", " ").split() if cn.strip()}
        pendientes = [c for c in pendientes if c["case_number"] in _filtro]
        if not pendientes:
            notif.info(f"Ninguno de los casos {_filtro} está pendiente en este reporte.")
            return
        notif.info(f"Modo --casos: procesando {[c['case_number'] for c in pendientes]}")
    elif args.caso:
        pendientes = [c for c in pendientes if c["case_number"] == args.caso]
        if not pendientes:
            notif.info(f"Caso '{args.caso}' no esta en este reporte (puede ya tener reclamo o ser de otro origen).")
            return
        notif.info(f"Modo --caso: procesando solo {args.caso}")

    if args.max_casos and len(pendientes) > args.max_casos:
        notif.info(f"--max-casos {args.max_casos}: limitando de {len(pendientes)} a {args.max_casos} casos")
        pendientes = pendientes[:args.max_casos]

    if not pendientes:
        notif.ok("Todos los casos ya tienen reclamo. Nada por procesar.")
        return

    if args.dry_run:
        print(f"\nCasos pendientes SIC (dry-run) — {len(pendientes)} casos:")
        for c in pendientes:
            exp   = c["expediente_sic"] or "(sin expediente)"
            salto = " [SKIP-checkpoint]" if estado.debe_saltar(c["case_number"]) else ""
            print(f"  {c['case_number']} | {c['placa']:<8} | Exp: {exp}{salto}")
        return

    if not args.username or not args.password:
        print("[ERROR] Credenciales SIC requeridas: --username y --password (o SIC_USERNAME en .env)")
        sys.exit(1)

    # -- VPN Monitor ------------------------------------------------------
    vpn_monitor = None
    if not args.sin_vpn_check:
        from src.shared.vpn_monitor import VPNMonitor
        vpn_monitor = VPNMonitor.desde_env(notif)

    # -- CI client con circuit breaker ------------------------------------
    ci_base    = _construir_ci_client(args.ci_url)
    ci_cliente = _CIWatchdog(ci_base, max_fallos=3, notif=notif)

    from src.tools.create_reclamo_premium.infrastructure.consulta_integral_scraper import (
        PolizaCanceladaError,
    )

    # -- Retry wrappers ---------------------------------------------------
    @con_reintento(
        max_intentos=3,
        backoff=(10, 60, 180),
        no_reintentar=(PolizaCanceladaError,),
        on_reintento=lambda n, exc: notif.info(f"  Phase A reintento {n}: {exc}"),
    )
    def fase_a_con_retry(caso):
        return _ejecutar_fase_a(caso, args.username, args.password, ci_cliente)

    # -- Loop principal ---------------------------------------------------
    notif.info(f"Iniciando pipeline — {len(pendientes)} casos pendientes")

    sin_avance  = 0
    procesados  = 0

    for i, caso in enumerate(pendientes, 1):
        cn  = caso["case_number"]
        exp = caso["expediente_sic"] or "(sin expediente)"
        notif.info(f"[{i}/{len(pendientes)}] {cn} | {caso['placa']} | Exp: {exp}")

        # -- Skip por checkpoint ------------------------------------------
        if estado.debe_saltar(cn):
            notif.info(f"  Saltando {cn} — ya en estado {estado.obtener(cn)['estado']}")
            continue

        # -- VPN check ----------------------------------------------------
        if vpn_monitor and not vpn_monitor.verificar():
            notif.alerta("VPN caida. Intentando reconexion...")
            ok = vpn_monitor.reconectar()
            if not ok:
                notif.error("No se pudo restablecer VPN. Deteniendo pipeline.")
                break

        # -- Phase A -------------------------------------------------------
        datos_json = _DATOS_DIR / f"{cn}.json"

        if not datos_json.exists():
            notif.info(f"  [A] Recolectando datos SIC...")
            estado.incrementar_intentos(cn, "a")
            try:
                datos = fase_a_con_retry(caso)
                with open(datos_json, "w", encoding="utf-8") as jf:
                    json.dump({"reclamo_data": datos}, jf, ensure_ascii=False, indent=2)
                estado.marcar_fase_a_ok(cn, numero_poliza=datos.get("numero_poliza", ""))
                notif.info(
                    f"  [A] OK — Poliza: {datos.get('numero_poliza', '?')} | "
                    f"Tipo: {(datos.get('siniestro') or {}).get('tipo', '?')} | "
                    f"Reserva: {(datos.get('poliza') or {}).get('reserva', '?')}"
                )
            except PolizaCanceladaError as exc:
                estado.marcar_poliza_cancelada(cn, str(exc))
                notif.alerta(f"  [A] Póliza cancelada — {cn}: {exc}")
                sin_avance = 0
                continue
            except RetryAgotadoError as exc:
                estado.marcar_error_permanente(cn, str(exc))
                notif.error(f"  [A] Agotados reintentos: {exc}")
                sin_avance += 1
                if sin_avance >= args.max_sin_avance:
                    notif.stop_sin_avance(sin_avance, cn)
                    break
                continue
        else:
            notif.info(f"  [A] JSON en cache: {datos_json.name}")

        # -- Phase B -------------------------------------------------------
        if not args.fase_b:
            sin_avance = 0
            procesados += 1
            continue

        notif.info(f"  [B] Automatizacion Premium...")
        estado.marcar_fase_b_iniciado(cn)
        estado.incrementar_intentos(cn, "b")

        rc = _ejecutar_fase_b(str(datos_json), guardar=args.guardar, case_number=cn)

        if rc == 0:
            estado.marcar_completado(cn)
            notif.ok(f"  [B] Reclamo creado — {cn}")
            sin_avance = 0
            procesados += 1
        elif rc == _EXIT_RECLAMO_EXISTENTE:
            estado.marcar_reclamo_existente(cn)
            notif.info(f"  [B] Reclamo ya existia — {cn}")
            sin_avance = 0
            procesados += 1
        elif rc == _EXIT_RECLAMO_DUPLICADO:
            estado.marcar_reclamo_existente(cn)
            notif.info(f"  [B] Duplicado detectado por Oracle Forms — {cn}")
            sin_avance = 0
            procesados += 1
        elif rc == _EXIT_FUERA_VIGENCIA:
            estado.marcar_error_permanente(cn, "Siniestro fuera de vigencia del automóvil — revisión manual")
            notif.error(f"  [B] Fuera de vigencia — {cn}")
            sin_avance = 0
            procesados += 1
        elif rc == _EXIT_NO_AUTORIZADO:
            estado.marcar_error_permanente(cn, "Usuario sin autorización para crear reclamo — revisión manual")
            notif.error(f"  [B] Sin autorización — {cn}")
            sin_avance = 0
            procesados += 1
        elif rc == _EXIT_VALIDACION_CAMPO:
            estado.marcar_error_permanente(cn, "Campo requerido vacío persistente tras reintentos — revisión manual")
            notif.error(f"  [B] Validación de campo fallida — {cn}")
            sin_avance = 0
            procesados += 1
        else:
            estado.marcar_error_permanente(cn, f"Phase B exit={rc}")
            notif.error(f"  [B] Error Phase B (exit {rc}) — {cn}")
            sin_avance += 1
            if sin_avance >= args.max_sin_avance:
                notif.stop_sin_avance(sin_avance, cn)
                break

    # -- Resumen final ---------------------------------------------------
    res = estado.resumen()
    notif.resumen_final(
        completados = res.get(EstadoCaso.COMPLETADO, 0),
        existentes  = res.get(EstadoCaso.RECLAMO_EXISTENTE, 0),
        canceladas  = res.get(EstadoCaso.POLIZA_CANCELADA, 0),
        errores     = res.get(EstadoCaso.ERROR_PERMANENTE, 0),
        total       = len(pendientes),
    )
    notif.info(f"Log en: {log_path}")
    notif.info(f"Estado en: {estado_path}")


if __name__ == "__main__":
    main()
