"""
Smoke test local: valida el cliente Orbika contra el sistema real.

Uso:
    python scripts/smoke_test_orbika.py --placa 422644

Lee credenciales desde .env:
    ORBIKA_USERNAME=...
    ORBIKA_PASSWORD=...
"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock
import argparse


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

from src.shared.orbika.orbika_session import OrbikaSession
from src.tools.check_orbika.infrastructure.orbika_client import OrbikaClient


def _session_desde_env() -> OrbikaSession:
    """Crea OrbikaSession con credenciales desde .env (sin SSM)."""
    username = os.environ.get("ORBIKA_USERNAME")
    password = os.environ.get("ORBIKA_PASSWORD")
    if not username or not password:
        print("FAIL: ORBIKA_USERNAME / ORBIKA_PASSWORD no en .env")
        sys.exit(1)

    mock_ssm = MagicMock()
    mock_ssm.get_parameter.side_effect = [
        {"Parameter": {"Value": username}},
        {"Parameter": {"Value": password}},
    ]
    return OrbikaSession(
        ssm_username_path="/local/username",
        ssm_password_path="/local/password",
        ssm_client=mock_ssm,
    )


def main(placa: str):
    print(f"=== Smoke test Orbika | placa={placa} ===")
    print()

    print("1. Haciendo login HTTP...")
    session = _session_desde_env()
    client = OrbikaClient(session=session)

    print(f"\n2. Consultando avisos para placa {placa}...")
    try:
        avisos = client.listar_avisos(placa)
    except RuntimeError as e:
        print(f"FAIL: {e}")
        sys.exit(1)

    print(f"   OK - {len(avisos)} aviso(s) encontrado(s)")
    for i, aviso in enumerate(avisos):
        print(f"\n   [{i}] nro={aviso.get('nro_aviso')} "
              f"estado={aviso.get('estado')!r} "
              f"cobertura={aviso.get('cobertura')!r}")
        print(f"       placa_asegurado={aviso.get('placa_asegurado')} "
              f"placa_tercero={aviso.get('placa_tercero')} "
              f"fecha={aviso.get('fecha_creacion_aviso')}")

    print()
    print("Smoke test Orbika exitoso.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--placa", required=True)
    args = parser.parse_args()
    main(args.placa)
