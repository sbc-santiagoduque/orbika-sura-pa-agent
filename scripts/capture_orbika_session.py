"""
Captura la sesion de Orbika (cookies + p_auth) para uso en Lambda.

Uso:
    python scripts/capture_orbika_session.py --local
    python scripts/capture_orbika_session.py --ssm /agente-analista/orbika/session

El flag --local guarda en orbika_session.json (para pruebas locales).
El flag --ssm guarda directamente en SSM (requiere AWS credentials).

Lee credenciales desde .env:
    ORBIKA_USERNAME=...
    ORBIKA_PASSWORD=...
"""
import argparse
import json
import os
import sys
from pathlib import Path


def _load_env():
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        print(f"FAIL: no se encontro .env en {env_path}")
        sys.exit(1)
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


_load_env()

from playwright.sync_api import sync_playwright

ORBIKA_BASE_URL  = "https://orbika.subocol.com"
ORBIKA_LOGIN_URL = f"{ORBIKA_BASE_URL}/c/portal/login"

_SEL_USERNAME = "input#_58_login"
_SEL_PASSWORD = "input#_58_password"
_SEL_SUBMIT   = "input[type='submit'][value='Ingresar']"

# Cookies de sesion relevantes de Liferay
_SESSION_COOKIE_KEYS = [
    "JSESSIONID",
    "ID",
    "COMPANY_ID",
    "GUEST_LANGUAGE_ID",
    "COOKIE_SUPPORT",
    "LFR_SESSION_STATE_20105",
]


def _extraer_p_auth(page) -> str:
    """Extrae el token CSRF de Liferay desde el contexto JavaScript."""
    try:
        token = page.evaluate("() => Liferay.authToken")
        if token:
            return token
    except Exception:
        pass
    # Fallback: navegar a gestion-aviso y extraer desde ahi
    page.goto(f"{ORBIKA_BASE_URL}/gestion-aviso", wait_until="domcontentloaded")
    page.wait_for_timeout(2_000)
    try:
        return page.evaluate("() => Liferay.authToken")
    except Exception:
        raise RuntimeError("No se pudo extraer Liferay.authToken. Verificar que el login fue exitoso.")


def _filtrar_cookies(all_cookies: list) -> dict:
    """Extrae solo las cookies de sesion relevantes."""
    resultado = {}
    for c in all_cookies:
        if c["name"] in _SESSION_COOKIE_KEYS or c["name"].startswith("LFR_SESSION_STATE_"):
            resultado[c["name"]] = c["value"]
    return resultado


def main(save_local: bool, ssm_path: str | None, aws_profile: str | None):
    username = os.environ.get("ORBIKA_USERNAME")
    password = os.environ.get("ORBIKA_PASSWORD")

    if not username or not password:
        print("FAIL: ORBIKA_USERNAME o ORBIKA_PASSWORD no encontrados en .env")
        sys.exit(1)

    print(f"=== Captura sesion Orbika | usuario={username} ===")
    print()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        print("1. Navegando al login...")
        page.goto(ORBIKA_LOGIN_URL, wait_until="domcontentloaded")

        try:
            page.wait_for_selector(_SEL_USERNAME, timeout=10_000)
        except Exception:
            # Puede que ya este logueado o la URL cambio
            print(f"   URL actual: {page.url}")
            page.screenshot(path="capture_orbika_login_fail.png")
            print("FAIL: no se encontro el formulario de login.")
            browser.close()
            sys.exit(1)

        page.fill(_SEL_USERNAME, username)
        page.fill(_SEL_PASSWORD, password)
        page.click(_SEL_SUBMIT)

        try:
            page.wait_for_url(
                lambda url: "login" not in url and url != ORBIKA_BASE_URL,
                timeout=15_000,
            )
            print(f"   OK - login exitoso. URL: {page.url}")
        except Exception:
            page.screenshot(path="capture_orbika_login_fail.png")
            print("FAIL: login no completado. Screenshot: capture_orbika_login_fail.png")
            browser.close()
            sys.exit(1)

        print("2. Extrayendo cookies y p_auth...")
        all_cookies = context.cookies()
        cookies = _filtrar_cookies(all_cookies)
        p_auth = _extraer_p_auth(page)

        print(f"   Cookies capturadas: {list(cookies.keys())}")
        print(f"   p_auth: {p_auth[:8]}...")

        browser.close()

    session_data = {"cookies": cookies, "p_auth": p_auth}

    if save_local:
        out_path = Path(__file__).parent.parent / "orbika_session.json"
        out_path.write_text(json.dumps(session_data, indent=2), encoding="utf-8")
        print(f"\n3. Sesion guardada localmente en: {out_path}")
        print("   Usar con smoke_test_orbika.py --local")

    if ssm_path:
        import boto3
        session_kwargs = {"profile_name": aws_profile} if aws_profile else {}
        ssm = boto3.Session(**session_kwargs).client("ssm", region_name="us-east-1")
        ssm.put_parameter(
            Name=ssm_path,
            Value=json.dumps(session_data),
            Type="SecureString",
            Overwrite=True,
        )
        print(f"\n3. Sesion guardada en SSM: {ssm_path}")

    print()
    print("Captura exitosa.")
    print()
    print("NOTA: La sesion Liferay expira tipicamente en 30 minutos de inactividad.")
    print("      Re-ejecutar este script cuando el smoke test reporte sesion expirada.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", action="store_true", help="Guardar en orbika_session.json")
    parser.add_argument("--ssm", metavar="PATH", help="Path SSM donde guardar la sesion")
    parser.add_argument(
        "--profile",
        default=os.environ.get("AWS_PROFILE", "orbika-admin-panama-agent"),
        help="AWS profile",
    )
    args = parser.parse_args()

    if not args.local and not args.ssm:
        print("Indica --local o --ssm <path>")
        sys.exit(1)

    main(save_local=args.local, ssm_path=args.ssm, aws_profile=args.profile)
