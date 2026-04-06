"""
Captura la sesión de Salesforce y la guarda en AWS SSM.

Uso:
    python scripts/capture_sf_session.py --ssm-path /agente-analista/salesforce/state

Qué hace:
    1. Abre un browser visible (headless=False)
    2. Navega al login de Salesforce
    3. El operador hace login + 2FA manualmente
    4. Captura el storageState completo (cookies + localStorage)
       — esto incluye el token de dispositivo confiable
    5. Guarda el storageState en SSM SecureString

Por qué storageState y no solo cookies:
    Salesforce Lightning guarda el token de "dispositivo confiable" en localStorage,
    no en cookies. Sin él, cada login desde un browser nuevo pide 2FA.
    Ver: construccion/salesforce_rpa_findings.md

Cuándo correr este script:
    - Primera vez (setup inicial)
    - Cuando Lambda falla con redirect al login (token de dispositivo expirado)
    El token típicamente dura 30-90 días (configurable por el admin de Sura Panamá).

Requisito:
    AWS CLI configurado con perfil orbika-admin-panama-agent y acceso a SSM.
"""
import argparse
import json
import sys

import boto3
from playwright.sync_api import sync_playwright

SF_LOGIN_URL = "https://surapa.lightning.force.com"
SF_HOME_URL = "https://surapa.lightning.force.com/lightning/page/home"

DEFAULT_SSM_PATH = "/agente-analista/salesforce/state"
DEFAULT_REGION = "us-east-1"
DEFAULT_PROFILE = "orbika-admin-panama-agent"


def main(ssm_path: str, region: str, profile: str, local_path: str | None):
    print("=== Captura de sesión Salesforce ===")
    if local_path:
        print(f"Modo: LOCAL → {local_path}")
    else:
        print(f"Modo: SSM → {ssm_path} ({region} / {profile})")
    print()

    storage_state = _capturar_sesion_interactiva()

    if local_path:
        _guardar_local(storage_state, local_path)
        print()
        print("Listo. Para usar en el smoke test:")
        print(f"  python scripts/smoke_test_bandeja.py --storage-state {local_path}")
        print()
        print("Cuando SSM esté aprovisionado, sube con:")
        print(f"  python scripts/capture_sf_session.py --from-file {local_path} --ssm-path {ssm_path}")
    else:
        _guardar_en_ssm(storage_state, ssm_path, region, profile)
        print()
        print("Listo. Lambda ya puede usar esta sesión.")
        print(f"Para verificar: python scripts/smoke_test_bandeja.py --use-ssm --ssm-path {ssm_path}")


def _capturar_sesion_interactiva() -> dict:
    """
    Abre el browser visible, espera que el operador haga login con 2FA
    y captura el storageState completo.
    """
    print("Abriendo browser...")
    print("Instrucciones:")
    print("  1. Se abrira el browser en la pagina de login de Salesforce")
    print("  2. Haz login con tu usuario y contraseña")
    print("  3. Completa el 2FA cuando Salesforce lo pida")
    print("  4. Espera a que cargue la pagina principal")
    print("  5. El script detecta el login y captura la sesion automaticamente")
    print()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        page.goto(SF_LOGIN_URL, wait_until="domcontentloaded")

        print("Esperando que completes el login (maximo 3 minutos)...")

        # Esperar a que la URL cambie a la home page — señal de login exitoso
        try:
            page.wait_for_url(
                lambda url: "/lightning/" in url and "login" not in url,
                timeout=180_000,
            )
        except Exception:
            print()
            print("FAIL: timeout esperando el login. Asegurate de completar el")
            print("  proceso de autenticacion dentro de los 3 minutos.")
            browser.close()
            sys.exit(1)

        print(f"Login detectado. URL: {page.url}")
        print("Capturando storageState...")

        # Dar unos segundos para que Salesforce termine de escribir en localStorage
        page.wait_for_timeout(3_000)

        storage_state = context.storage_state()
        browser.close()

    cookies_count = len(storage_state.get("cookies", []))
    origins_count = len(storage_state.get("origins", []))
    print(f"  Capturado: {cookies_count} cookies, {origins_count} origins con localStorage")

    return storage_state


def _guardar_local(storage_state: dict, local_path: str):
    """Guarda el storageState en un archivo JSON local (para cuando SSM no está listo)."""
    import os
    os.makedirs(os.path.dirname(os.path.abspath(local_path)), exist_ok=True)
    with open(local_path, "w", encoding="utf-8") as f:
        json.dump(storage_state, f, indent=2, ensure_ascii=False)

    cookies_count = len(storage_state.get("cookies", []))
    origins = storage_state.get("origins", [])
    ls_count = sum(len(o.get("localStorage", [])) for o in origins)
    print(f"  Guardado en {local_path}")
    print(f"  Contenido: {cookies_count} cookies, {ls_count} entradas de localStorage")


def _guardar_en_ssm(storage_state: dict, ssm_path: str, region: str, profile: str):
    """Guarda el storageState en SSM Parameter Store como SecureString."""
    print(f"Guardando en SSM {ssm_path}...")

    session = boto3.Session(profile_name=profile, region_name=region)
    ssm = session.client("ssm")

    ssm.put_parameter(
        Name=ssm_path,
        Value=json.dumps(storage_state),
        Type="SecureString",
        Overwrite=True,
    )

    print(f"  Guardado correctamente en SSM.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Captura sesion de Salesforce y guarda en SSM o archivo local"
    )
    parser.add_argument(
        "--ssm-path",
        default=DEFAULT_SSM_PATH,
        help=f"Path en SSM Parameter Store (default: {DEFAULT_SSM_PATH})",
    )
    parser.add_argument(
        "--region",
        default=DEFAULT_REGION,
        help=f"Region AWS (default: {DEFAULT_REGION})",
    )
    parser.add_argument(
        "--profile",
        default=DEFAULT_PROFILE,
        help=f"Perfil AWS CLI (default: {DEFAULT_PROFILE})",
    )
    parser.add_argument(
        "--local",
        metavar="RUTA",
        default=None,
        help="Guardar storageState en archivo local en vez de SSM. "
             "Util cuando SSM aun no esta aprovisionado.",
    )
    args = parser.parse_args()
    main(args.ssm_path, args.region, args.profile, args.local)
