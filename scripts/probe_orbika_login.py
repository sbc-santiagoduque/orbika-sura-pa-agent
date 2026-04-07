"""
Prueba de login Orbika via HTTP puro (sin Playwright).
Si funciona, elimina la dependencia de browser en capture_orbika_session.py.

Uso:
    python scripts/probe_orbika_login.py
"""
import os
import re
import sys
from pathlib import Path

def _load_env():
    env_path = Path(__file__).parent.parent / ".env"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

_load_env()

import requests

ORBIKA_BASE    = "https://orbika.subocol.com"
LOGIN_PAGE_URL = f"{ORBIKA_BASE}/web/guest/login"

_RE_P_AUTH        = re.compile(r'Liferay\.authToken\s*=\s*["\']([^"\']+)["\']')
_RE_PORTLET_ID    = re.compile(r'com_subocol_orbika_login_SubocolLoginPortlet_INSTANCE_(\w+)')
_RE_GUEST_P_AUTH  = re.compile(r'p_auth=([A-Za-z0-9_-]{8})')

username = os.environ.get("ORBIKA_USERNAME")
password = os.environ.get("ORBIKA_PASSWORD")

if not username or not password:
    print("FAIL: ORBIKA_USERNAME / ORBIKA_PASSWORD no en .env")
    sys.exit(1)

print(f"=== Probe login Orbika via HTTP | user={username} ===\n")

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "es-ES,es;q=0.9",
})

# 1. GET login page para extraer portlet instance ID y p_auth pre-login
print("1. GET login page para extraer portlet ID y p_auth...")
resp0 = s.get(LOGIN_PAGE_URL, timeout=15)
print(f"   status={resp0.status_code}")

m_pid = _RE_PORTLET_ID.search(resp0.text)
m_pa  = _RE_GUEST_P_AUTH.search(resp0.text)

if not m_pid or not m_pa:
    Path("probe_orbika_login_page.html").write_text(resp0.text, encoding="utf-8")
    print("FAIL: no se encontro portlet ID o p_auth en la pagina de login.")
    print("      HTML guardado en probe_orbika_login_page.html")
    sys.exit(1)

portlet_instance = f"com_subocol_orbika_login_SubocolLoginPortlet_INSTANCE_{m_pid.group(1)}"
pre_p_auth = m_pa.group(1)
prefix = f"_{portlet_instance}_"

print(f"   portlet_instance: {portlet_instance}")
print(f"   pre_p_auth: {pre_p_auth}")

# 2. POST login con multipart/form-data
print("\n2. POST login (multipart/form-data)...")
login_url = (
    f"{LOGIN_PAGE_URL}"
    f"?p_p_id={portlet_instance}"
    f"&p_p_lifecycle=1&p_p_state=normal&p_p_mode=view"
    f"&{prefix}javax.portlet.action=%2Flogin"
    f"&{prefix}mvcRenderCommandName=%2Flogin"
    f"&p_auth={pre_p_auth}"
)

resp1 = s.post(
    login_url,
    files={
        f"{prefix}username": (None, username),
        f"{prefix}password": (None, password),
        f"{prefix}terminos": (None, "on"),
    },
    headers={
        "X-Requested-With": "XMLHttpRequest",
        "X-PJAX": "true",
        "Origin": ORBIKA_BASE,
        "Referer": LOGIN_PAGE_URL,
    },
    allow_redirects=True,
    timeout=15,
)
print(f"   status={resp1.status_code} url={resp1.url}")
print(f"   cookies: {list(s.cookies.keys())}")

if "ID" not in s.cookies:
    print("\nFAIL: cookie 'ID' no obtenida — login fallido")
    Path("probe_orbika_login_fail.html").write_text(resp1.text, encoding="utf-8")
    print("      HTML guardado en probe_orbika_login_fail.html")
    sys.exit(1)

print("   OK - login exitoso (cookie ID obtenida)")

# 3. Extraer p_auth autenticado de /navigation
print(f"\n3. Extrayendo p_auth autenticado de /navigation...")
Path("probe_orbika_navigation.html").write_text(resp1.text, encoding="utf-8")

m_auth = _RE_P_AUTH.search(resp1.text)
if not m_auth:
    # Buscar patron alternativo en el HTML
    m_auth = re.search(r'"p_auth"\s*:\s*"([A-Za-z0-9_-]{8})"', resp1.text)
if not m_auth:
    m_auth = re.search(r'p_auth=([A-Za-z0-9_-]{8})', resp1.text)

if not m_auth:
    print("   FAIL: no se encontro p_auth autenticado en /navigation")
    print("   HTML guardado en probe_orbika_navigation.html — inspeccionar manualmente")
    sys.exit(1)

p_auth = m_auth.group(1)
print(f"   OK - p_auth autenticado={p_auth}")

# 4. Restaurar sesion via consultar-ultima-sesion (evita seleccion manual de rol)
print("\n4. Restaurando sesion (consultar-ultima-sesion)...")
import json

cmd_sesion = {"/permisos.sesionaudit/consultar-ultima-sesion": {}}
resp_sesion = s.post(
    f"{ORBIKA_BASE}/api/jsonws/invoke",
    data={"cmd": json.dumps(cmd_sesion), "p_auth": p_auth},
    headers={"X-Requested-With": "XMLHttpRequest"},
    timeout=15,
)
print(f"   status={resp_sesion.status_code}")
sesion_data = resp_sesion.json()
print(f"   sesion: {json.dumps(sesion_data, indent=4, ensure_ascii=False)}")

if isinstance(sesion_data, dict) and "exception" in sesion_data:
    print(f"   WARN: {sesion_data['exception']} — continuando de todas formas")
elif isinstance(sesion_data, dict) and "roleid" in sesion_data:
    print(f"   OK - rol={sesion_data.get('rolName')} org={sesion_data.get('organizationName')}")

# 5. Probar llamada API
print("\n5. Probando llamada API...")
import json
cmd = {
    "/adminAvisos.aviso/Listar-avisos-talleres": {
        "aseguradora": "Sura Panama",
        "cobertura": [], "regional": [], "estado": [], "taller": [],
        "tipofecha": None, "fechaini": None, "tipoVehiculo": [],
        "buscador": "placa", "valorBuscado": "422644", "imprevistos": False,
    }
}
resp3 = s.post(
    f"{ORBIKA_BASE}/api/jsonws/invoke",
    data={"cmd": json.dumps(cmd), "p_auth": p_auth},
    headers={"X-Requested-With": "XMLHttpRequest"},
    timeout=15,
)
print(f"   status={resp3.status_code}")
data = resp3.json()
if isinstance(data, dict) and "exception" in data:
    print(f"   FAIL sesion: {data['exception']}")
    sys.exit(1)

print(f"   OK - {len(data)} aviso(s)")
if data:
    print(f"   Primer aviso: nro={data[0].get('nro_aviso')} estado={data[0].get('estado')}")

session_cookies = {k: v for k, v in s.cookies.items()}
print(f"\nLogin HTTP puro exitoso.")
print(f"Cookies: {json.dumps(session_cookies, indent=2)}")
print(f"p_auth: {p_auth}")
