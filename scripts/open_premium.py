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
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, os.path.join(_SCRIPT_DIR, ".."))

# Deshabilitar failsafe de pyautogui en modo autónomo.
try:
    import pyautogui as _pag
    _pag.FAILSAFE = False
    _pag.PAUSE = 0.0
except ImportError:
    pass

# Cargar .env
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

# ── Premium package ────────────────────────────────────────────────────────────
from premium.common import log, set_notifier, screenshot, validate_templates, CAPTURES_DIR
from premium.exceptions import (
    ClaimAlreadyExistsError, DuplicateClaimError,
    IncidentOutOfCoverageError, UnauthorizedError, FieldValidationError,
)
from premium.mappers import incident_type_to_code, coverage_to_code
from premium.rdp import (
    clear_saved_credentials, open_rdp_session, wait_for_desktop,
    focus_rdp_window, wait_rdp_desktop_ready, close_shutdown_tracker,
    open_premium_app, wait_premium_open,
    wait_login_dialog, complete_login, wait_logged_in,
)
from premium.navigation import (
    navigate_to_claim_apertura, wait_endosos_form, enter_policy_and_date,
    click_consultar_unidades, extract_vehicle_data,
    click_coberturas_button, select_collision_coverage,
)
from premium.recovery import (
    close_forms_popup, close_endosos_form,
    close_vehicle_screens, close_claim_and_return_home,
)
from premium.forms import (
    fill_generals_1, fill_generals_2, fill_generals_3, fill_reserves,
    fill_formulario, save_claim, simulate_save,
)


def main():
    parser = argparse.ArgumentParser(
        description="Conectar RDP, abrir sistema Premium y hacer login en Oracle Forms"
    )
    parser.add_argument("--host",             default=os.environ.get("RDP_HOST", ""))
    parser.add_argument("--username",         default=os.environ.get("RDP_USERNAME", ""))
    parser.add_argument("--password",         default=os.environ.get("RDP_PASSWORD", ""))
    parser.add_argument("--premium-username", default=os.environ.get("PREMIUM_USERNAME", ""))
    parser.add_argument("--premium-password", default=os.environ.get("PREMIUM_PASSWORD", ""))
    parser.add_argument("--timeout",    type=int, default=90)
    parser.add_argument("--dry-run",    action="store_true")
    parser.add_argument("--no-rdp",     action="store_true")
    parser.add_argument("--no-premium", action="store_true")
    parser.add_argument("--step",
                        choices=["all", "rdp", "premium", "login", "apertura",
                                 "generales1", "generales2", "generales3",
                                 "reservas", "formulario"],
                        default="all")
    parser.add_argument("--poliza",           default="")
    parser.add_argument("--fecha-siniestro",  default="")
    parser.add_argument("--tipo-siniestro",   default="30")
    parser.add_argument("--guardar",          action="store_true")
    parser.add_argument("--simular-guardar",  action="store_true")
    parser.add_argument("--datos-json",       metavar="ARCHIVO")
    parser.add_argument("--case-number",      default="")
    args = parser.parse_args()

    # ── Notificador ───────────────────────────────────────────────────────────
    from src.shared.notificador import Notificador
    import datetime
    _ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    _log_name = f"run_b_{args.case_number}_{_ts}.log" if args.case_number else f"run_b_{_ts}.log"
    _log_path = Path(_SCRIPT_DIR) / "resultados" / _log_name
    set_notifier(Notificador.desde_env(log_path=_log_path))
    validate_templates()

    # ── Cargar DatosReclamo desde JSON ────────────────────────────────────────
    datos: dict = {}
    if args.datos_json:
        _json_path = Path(args.datos_json)
        if not _json_path.is_absolute() and not _json_path.exists():
            _json_path = Path(__file__).parent / _json_path
        with open(_json_path, encoding="utf-8") as _f:
            _raw = json.load(_f)
        datos = _raw.get("reclamo_data", _raw)
        log(f"[→] Datos cargados desde {args.datos_json}")
        log(f"    Póliza:    {datos.get('numero_poliza', '—')}")
        log(f"    Tipo:      {(datos.get('siniestro') or {}).get('tipo', '—')}")
        log(f"    Conductor: {(datos.get('conductor') or {}).get('nombre', '—')} "
            f"{(datos.get('conductor') or {}).get('apellido', '—')}")

    if datos:
        if not args.poliza:
            args.poliza = datos.get("numero_poliza", "")
        if not args.fecha_siniestro:
            args.fecha_siniestro = (datos.get("siniestro") or {}).get("fecha", "")

    # ── Saltar pasos cuando --step lo indica ─────────────────────────────────
    _FORM_STEPS = ("login", "apertura", "generales1", "generales2",
                   "generales3", "reservas", "formulario")
    if args.step in _FORM_STEPS:
        args.no_rdp = True
        args.no_premium = True

    # ── Traer ventana RDP al frente si ya está activa ─────────────────────────
    # Se activa tanto cuando --step es un form step como cuando se pasan
    # --no-rdp explícitamente (ej: desde procesar_casos.py con RDP ya activo).
    if args.no_rdp:
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
                log(f"[→] Ventana RDP al frente: '{rdp_wins[0]}'")
            else:
                log("[WARN] Ventana RDP no encontrada — asegurate de que la sesion este activa")
        except Exception as e:
            log(f"[WARN] No se pudo traer ventana RDP al frente: {e}")

    # Si se saltan tanto RDP como Premium, asumimos que ya estamos conectados
    # y logueados — no intentar login de nuevo (evita escribir credenciales en el menú principal).
    skip_login      = (args.step in ("rdp", "premium", "apertura",
                                     "generales1", "generales2", "generales3",
                                     "reservas", "formulario")
                       or (args.no_rdp and args.no_premium))
    skip_apertura   = args.step in ("rdp", "premium", "login",
                                    "generales1", "generales2", "generales3",
                                    "reservas", "formulario")
    skip_generales1 = args.step in ("rdp", "premium", "login", "apertura",
                                    "generales2", "generales3", "reservas")
    skip_generales2 = args.step in ("rdp", "premium", "login", "apertura",
                                    "generales1", "generales3", "reservas")
    skip_generales3 = args.step in ("rdp", "premium", "login", "apertura",
                                    "generales1", "generales2", "reservas")
    skip_reservas   = args.step in ("rdp", "premium", "login", "apertura",
                                    "generales1", "generales2", "generales3")

    if not args.no_rdp:
        if not args.host:
            log("[ERROR] Host requerido: --host o RDP_HOST en .env")
            sys.exit(1)
        if not args.username or not args.password:
            log("[ERROR] Credenciales RDP requeridas en .env o como args")
            sys.exit(1)

    if not skip_login and not args.dry_run:
        if not args.premium_username or not args.premium_password:
            log("[ERROR] Credenciales Premium requeridas: PREMIUM_USERNAME y PREMIUM_PASSWORD en .env")
            sys.exit(1)

    import shutil
    if os.path.isdir(CAPTURES_DIR):
        shutil.rmtree(CAPTURES_DIR)
    os.makedirs(CAPTURES_DIR)
    log(f"[→] Capturas en: {CAPTURES_DIR}")

    log(f"\n{'='*55}")
    log(f"  PHASE B — Abrir Sistema Premium + Login Oracle Forms")
    if not args.no_rdp:
        log(f"  RDP:     {args.host}  |  {args.username}")
    if not skip_login and not args.dry_run:
        log(f"  Premium: {args.premium_username}")
    if args.step != "all":
        log(f"  Modo:    --step {args.step}")
    log(f"{'='*55}\n")

    try:
        screenshot("paso_01_inicio.png", "pantalla inicial")

        # ── RDP ───────────────────────────────────────────────────────────────
        if not args.no_rdp:
            clear_saved_credentials(args.host)
            open_rdp_session(fullscreen=True)
            time.sleep(2)
            screenshot("paso_02_mstsc_lanzado.png", "mstsc recién lanzado")

            if not wait_for_desktop(args.host, args.username, args.password,
                                    timeout_s=args.timeout):
                log("[ERROR] No se pudo establecer la sesión RDP")
                screenshot("error_rdp_fallido.png")
                sys.exit(1)

            wait_rdp_desktop_ready(timeout_s=90)
            close_shutdown_tracker()
            screenshot("paso_07_escritorio_rdp.png", "escritorio remoto listo")
            focus_rdp_window(args.host)

        if args.step == "rdp":
            log(f"\n[✓] --step rdp completado. Capturas en: {CAPTURES_DIR}")
            return

        # ── Abrir Premium ─────────────────────────────────────────────────────
        if not args.no_premium:
            if not open_premium_app(dry_run=args.dry_run):
                screenshot("error_premium_no_encontrado.png")
                log(f"\n[HINT] Revisá las capturas en: {CAPTURES_DIR}")
                sys.exit(1)

            if args.dry_run:
                log(f"\n[✓] Dry-run completado. Capturas en: {CAPTURES_DIR}")
                return

            time.sleep(3)
            wait_premium_open(timeout_s=30)
            time.sleep(2)
            screenshot("paso_10_premium_abierto.png", "app Premium abierta")

        if args.step == "premium":
            log(f"\n[✓] --step premium completado. Capturas en: {CAPTURES_DIR}")
            return

        # ── Login Oracle Forms ────────────────────────────────────────────────
        if not skip_login:
            if not wait_login_dialog(timeout_s=30):
                log("[WARN] Continuando de todas formas — el diálogo puede estar visible")

            complete_login(args.premium_username, args.premium_password)
            wait_logged_in(timeout_s=45)

            if args.step == "login":
                log(f"\n[✓] --step login completado. Capturas en: {CAPTURES_DIR}")
                return

        # ── Apertura de Reclamo (P1 + P2) ────────────────────────────────────
        if not skip_apertura:
            poliza = args.poliza
            fecha  = args.fecha_siniestro
            if not poliza or not fecha:
                log("[WARN] --poliza y --fecha-siniestro requeridos para el paso apertura")
                log(f"       Capturas hasta login en: {CAPTURES_DIR}")
                return

            if not navigate_to_claim_apertura():
                screenshot("error_navegacion_menu.png")
                log(f"\n[HINT] Creá los templates en docs/screens/ para navegación precisa")
                sys.exit(1)

            if not wait_endosos_form(timeout_s=15):
                log("[WARN] Continuando de todas formas...")

            enter_policy_and_date(poliza, fecha)
            click_consultar_unidades()

            time.sleep(1.5)
            if close_forms_popup():
                log("\n[!] Reclamo duplicado — Oracle Forms advirtió posible duplicidad")
                close_endosos_form()
                raise DuplicateClaimError(
                    f"Póliza {poliza} ya tiene un reclamo para la fecha {fecha}"
                )

            extract_vehicle_data()

            if close_forms_popup():
                log("\n[!] Siniestro fuera de vigencia — detectado al cargar automóvil")
                close_vehicle_screens()
                raise IncidentOutOfCoverageError(
                    f"Póliza {poliza}: siniestro {fecha} fuera de vigencia del automóvil"
                )

            click_coberturas_button()

            if close_forms_popup():
                log("\n[!] Siniestro fuera de vigencia — detectado al abrir coberturas")
                close_vehicle_screens()
                raise IncidentOutOfCoverageError(
                    f"Póliza {poliza}: siniestro {fecha} fuera de vigencia del automóvil"
                )

            select_collision_coverage()

        # ── Formulario ────────────────────────────────────────────────────────
        _sin  = datos.get("siniestro") or {}
        _con  = datos.get("conductor") or {}
        _pol  = datos.get("poliza") or {}
        _tipo_codigo = incident_type_to_code(_sin.get("tipo", "")) or args.tipo_siniestro

        _formulario_filled = False
        if not (skip_generales1 or skip_generales2 or skip_generales3 or skip_reservas):
            # Flujo completo — retry unificado entre tabs
            fill_formulario(
                g1_kwargs=dict(
                    incident_type_code=_tipo_codigo,
                    description=_sin.get("descripcion", "") or "SIN DESCRIPCION",
                    incident_time=_sin.get("hora", "") or "00:00",
                    incident_place=_sin.get("lugar", "") or "PANAMA",
                ),
                g2_kwargs=dict(
                    cedula=_con.get("cedula", "") or "",
                    nombre=(_con.get("nombre", "") or "").upper(),
                    apellido=(_con.get("apellido", "") or "").upper(),
                    sexo=_con.get("sexo", "M") or "M",
                    edad=str(_con.get("edad", "") or ""),
                    responsabilidad=_con.get("responsabilidad", "Culpable") or "Culpable",
                ),
                g3_kwargs=dict(
                    descripcion_danos=_sin.get("descripcion_danos", "") or "SIN DESCRIPCION",
                    ajustador_interno=str(datos.get("ajustador_interno", 158) or 158),
                ),
                res_kwargs=dict(
                    coverage_code=coverage_to_code(_pol.get("cobertura", "")),
                    reserve_amount=str(int(_pol.get("reserva", 1300) or 1300)),
                ),
            )
            _formulario_filled = True
        else:
            # Ejecución individual por tab (modo --step generalesN para debug)
            if not skip_generales1:
                fill_generals_1(
                    incident_type_code=_tipo_codigo,
                    description=_sin.get("descripcion", "") or "SIN DESCRIPCION",
                    incident_time=_sin.get("hora", "") or "00:00",
                    incident_place=_sin.get("lugar", "") or "PANAMA",
                )
                _formulario_filled = True
            if not skip_generales2:
                fill_generals_2(
                    cedula=_con.get("cedula", "") or "",
                    nombre=(_con.get("nombre", "") or "").upper(),
                    apellido=(_con.get("apellido", "") or "").upper(),
                    sexo=_con.get("sexo", "M") or "M",
                    edad=str(_con.get("edad", "") or ""),
                    responsabilidad=_con.get("responsabilidad", "Culpable") or "Culpable",
                )
                _formulario_filled = True
            if not skip_generales3:
                fill_generals_3(
                    descripcion_danos=_sin.get("descripcion_danos", "") or "SIN DESCRIPCION",
                    ajustador_interno=str(datos.get("ajustador_interno", 158) or 158),
                )
                _formulario_filled = True
            if not skip_reservas:
                fill_reserves(
                    coverage_code=coverage_to_code(_pol.get("cobertura", "")),
                    reserve_amount=str(int(_pol.get("reserva", 1300) or 1300)),
                )
                _formulario_filled = True

        if args.guardar:
            if not _formulario_filled:
                log("\n[WARN] --guardar ignorado — ningún tab de formulario fue llenado en este paso.")
                log("       Usa --step all o --step formulario para llenar y guardar.")
            else:
                try:
                    numero = save_claim()
                    log(f"\n[✓] RECLAMO CREADO — No.: {numero}")
                    close_claim_and_return_home()
                except UnauthorizedError as exc:
                    log(f"\n[!] NO AUTORIZADO — {exc}")
                    close_claim_and_return_home()
                    sys.exit(5)
                except ClaimAlreadyExistsError as exc:
                    log(f"\n[!] RECLAMO YA EXISTE — {exc}")
                    close_claim_and_return_home()
                    sys.exit(2)
        elif args.simular_guardar:
            if not _formulario_filled:
                log("\n[WARN] --simular-guardar ignorado — ningún tab de formulario fue llenado en este paso.")
            else:
                simulate_save()
                close_claim_and_return_home()
        else:
            if _formulario_filled:
                log("\n[i] Formulario listo. Usar --guardar para crear el reclamo.")

        log(f"\n[✓] Listo. Capturas en: {CAPTURES_DIR}")
        log(f"    Abrí la carpeta: explorer {CAPTURES_DIR}")

    except DuplicateClaimError as exc:
        log(f"\n[!] RECLAMO DUPLICADO — {exc}")
        log("    Oracle Forms advirtió posible duplicidad — caso saltado.")
        close_claim_and_return_home()
        sys.exit(3)

    except IncidentOutOfCoverageError as exc:
        log(f"\n[!] SINIESTRO FUERA DE VIGENCIA — {exc}")
        log("    La fecha del siniestro no está cubierta por ningún endoso — requiere revisión manual.")
        close_claim_and_return_home()
        sys.exit(4)

    except FieldValidationError as exc:
        log(f"\n[!] VALIDACION FALLIDA tras reintentos — {exc}")
        log(f"    Tab: {exc.tab} — campo requerido vacío persistente.")
        close_claim_and_return_home()
        sys.exit(6)

    finally:
        pass


if __name__ == "__main__":
    main()
