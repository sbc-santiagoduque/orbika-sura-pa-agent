"""
Smoke test local: valida el cliente SIC REST API contra el sistema real.

Uso:
    python scripts/smoke_test_sic_api.py --placa 422644

Lee credenciales desde .env:
    SIC_USERNAME=...
    SIC_PASSWORD=...
"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock
import argparse

import requests


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
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.shared.sic_api.sic_api_session import SICApiSession
from src.tools.extract_expediente_sic_api.infrastructure.sic_api_client import (
    SICApiClient,
    _SIC_API_BASE,
    _AUTH_URL,
    _SEARCH_URL,
    _IMAGES_URL,
    _API_KEY,
    _parsear_fecha,
)

_COMPANY_ID = 15
_ROL_ID     = 3


def _session_desde_env() -> SICApiSession:
    """Crea SICApiSession con credenciales desde .env (sin SSM)."""
    username = os.environ.get("SIC_USERNAME")
    password = os.environ.get("SIC_PASSWORD")
    if not username or not password:
        print("FAIL: SIC_USERNAME / SIC_PASSWORD no en .env")
        sys.exit(1)

    mock_ssm = MagicMock()
    mock_ssm.get_parameter.side_effect = [
        {"Parameter": {"Value": username}},
        {"Parameter": {"Value": password}},
    ]
    return SICApiSession(
        ssm_username_path="/local/username",
        ssm_password_path="/local/password",
        ssm_client=mock_ssm,
    )


def _probe_auth(username: str, password: str) -> tuple[str, str]:
    """Paso 1: autenticar y mostrar payload JWT."""
    print(f"   POST {_AUTH_URL}")
    resp = requests.post(
        _AUTH_URL,
        json={"username": username, "password": password, "mfaCode": None, "challengeSession": None},
        headers={"Authorization": _API_KEY, "Accept": "application/json"},
        timeout=15,
    )
    print(f"   HTTP {resp.status_code}")
    resp.raise_for_status()
    body = resp.json()
    print(f"   Claves respuesta: {list(body.keys())}")

    # La respuesta viene en body["data"]
    data = body.get("data") or body
    print(f"   Claves data: {list(data.keys())}")

    access_token = data.get("accessToken")
    if not access_token:
        print(f"FAIL: no se encontro accessToken. Claves data: {list(data.keys())}")
        sys.exit(1)

    sub = data.get("sub") or ""
    print(f"   sub={sub}")
    print(f"   accessToken (60 chars): {access_token[:60]}...")
    return access_token, sub


def _probe_get_user(sub: str) -> tuple[int, str]:
    """Paso 2: obtener userCompanyID y codPais desde /v1/users/{sub}."""
    url = f"{_SIC_API_BASE}/api/v1/users/{sub}"
    print(f"   GET {url}")
    resp = requests.get(url, headers={"Authorization": _API_KEY, "Accept": "application/json"}, timeout=10)
    print(f"   HTTP {resp.status_code}")
    resp.raise_for_status()
    data = resp.json().get("data") or {}
    user_company_id = data.get("userCompanyID")
    country_code    = data.get("codPais", "PAN")
    print(f"   userCompanyID={user_company_id}  codPais={country_code}  rolId={data.get('rolId')}")
    return int(user_company_id), country_code


def _probe_search(placa: str, user_id: int, country_code: str, headers: dict) -> list:
    """Paso 3: buscar eventos por placa."""
    params = {
        "filterType":  "INSURED_PLATE",
        "filterText":  placa,
        "countryCode": country_code,
        "companyId":   _COMPANY_ID,
        "rolId":       _ROL_ID,
        "page":        1,
        "userId":      user_id,
    }
    print(f"   GET {_SEARCH_URL}")
    print(f"   Params: {params}")
    resp = requests.get(_SEARCH_URL, params=params, headers=headers, timeout=15)
    print(f"   HTTP {resp.status_code}")
    resp.raise_for_status()
    body = resp.json()

    # Estructura real: body.data.response.events
    data = body.get("data") or {}
    if isinstance(data, dict):
        response = data.get("response") or {}
        eventos = response.get("events") or data.get("events") or []
    elif isinstance(data, list):
        eventos = data
    else:
        eventos = []

    print(f"   {len(eventos)} evento(s) encontrado(s)")
    for i, ev in enumerate(eventos[:5]):
        print(f"   [{i}] eventRecord={ev.get('eventRecord')} fecha={ev.get('eventDate')} "
              f"placa={ev.get('plate') or ev.get('vehicleMetallicPlate') or '?'}")
    return eventos


def _probe_imagenes(event_record: str, headers: dict) -> list:
    """Paso 3: obtener imagenes del evento."""
    url = f"{_IMAGES_URL}/{event_record}"
    print(f"   GET {url}?forceUpdate=true")
    resp = requests.get(url, params={"forceUpdate": "true"}, headers=headers, timeout=20)
    print(f"   HTTP {resp.status_code}")
    resp.raise_for_status()
    body = resp.json()

    items = body.get("data") if isinstance(body, dict) else body
    if not isinstance(items, list):
        print(f"   Respuesta inesperada: {type(body)}")
        return []

    print(f"   {len(items)} imagen(es)")
    for i, img in enumerate(items[:5]):
        print(f"   [{i}] nombre={img.get('imageName')!r} seccionId={img.get('imageSectionId')} "
              f"url={str(img.get('imageUrl', ''))[:60]}...")
    return items


def main(placa: str):
    print(f"=== Smoke test SIC API | placa={placa} ===")
    print()

    username = os.environ.get("SIC_USERNAME")
    password = os.environ.get("SIC_PASSWORD")

    # --- Paso 1: Auth ---
    print("1. Autenticando...")
    jwt, sub = _probe_auth(username, password)
    print("   OK")

    headers = {
        "Authorization": f"Bearer {jwt}",
        "X-User-Type":   "sic-user",
        "Accept":        "application/json",
        "Content-Type":  "application/json",
    }

    # --- Paso 2: Datos de usuario ---
    print(f"\n2. Obteniendo datos de usuario ({sub})...")
    user_company_id, country_code = _probe_get_user(sub)
    print("   OK")

    # --- Paso 3: Search ---
    print(f"\n3. Buscando eventos para placa {placa}...")
    eventos = _probe_search(placa, user_company_id, country_code, headers)
    if not eventos:
        print("   Sin eventos — terminando smoke test")
        return

    # Tomar el mas reciente
    evento_reciente = max(eventos, key=lambda e: _parsear_fecha(e.get("eventDate", "")))
    event_record = str(evento_reciente.get("eventRecord", ""))
    print(f"   Evento mas reciente: eventRecord={event_record} fecha={evento_reciente.get('eventDate')}")

    # --- Paso 4: Imagenes ---
    print(f"\n4. Obteniendo imagenes del evento {event_record}...")
    imagenes = _probe_imagenes(event_record, headers)

    # --- Paso 4: Flujo completo via cliente ---
    print("\n4. Verificando flujo completo con SICApiClient...")
    session = _session_desde_env()
    client  = SICApiClient(session=session)
    try:
        expediente = client.obtener_expediente(placa)
    except Exception as e:
        print(f"FAIL: {e}")
        sys.exit(1)

    print(f"   OK — evento_id={expediente['evento_id']} "
          f"imagen_count={expediente['imagen_count']} "
          f"fecha={expediente['fecha_evento']}")

    print()
    print("Smoke test SIC API exitoso.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--placa", required=True)
    args = parser.parse_args()
    main(args.placa)
