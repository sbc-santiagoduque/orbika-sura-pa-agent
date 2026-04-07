"""
Smoke test local: valida el cliente Orbika contra el sistema real.

Uso:
    # Primero capturar sesion:
    python scripts/capture_orbika_session.py --local

    # Luego correr el smoke test:
    python scripts/smoke_test_orbika.py --placa 422644
    python scripts/smoke_test_orbika.py --placa 422644 --session orbika_session.json

Lee la sesion desde orbika_session.json (capturado con capture_orbika_session.py).
"""
import argparse
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock


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


def _session_desde_archivo(path: Path) -> OrbikaSession:
    """Crea un OrbikaSession que lee desde archivo local (sin SSM)."""
    data = json.loads(path.read_text(encoding="utf-8"))

    mock_ssm = MagicMock()
    mock_ssm.get_parameter.return_value = {
        "Parameter": {"Value": json.dumps(data)}
    }
    return OrbikaSession(ssm_session_path="/local", ssm_client=mock_ssm)


def main(placa: str, session_path: Path):
    print(f"=== Smoke test Orbika | placa={placa} ===")
    print()

    if not session_path.exists():
        print(f"FAIL: no se encontro sesion en {session_path}")
        print("      Ejecutar primero: python scripts/capture_orbika_session.py --local")
        sys.exit(1)

    print(f"1. Cargando sesion desde {session_path}...")
    session = _session_desde_archivo(session_path)
    cookies, p_auth = session.load()
    print(f"   Cookies: {list(cookies.keys())}")
    print(f"   p_auth:  {p_auth[:8]}...")

    print(f"\n2. Consultando Orbika para placa {placa}...")
    client = OrbikaClient(session=session)
    try:
        avisos = client.listar_avisos(placa)
    except RuntimeError as e:
        print(f"FAIL: {e}")
        sys.exit(1)

    print(f"   OK - {len(avisos)} aviso(s) encontrado(s)")

    if not avisos:
        print("   Sin avisos para esta placa.")
    else:
        for i, aviso in enumerate(avisos):
            print(f"\n   [{i}] nro_aviso={aviso.get('nro_aviso')} "
                  f"estado={aviso.get('estado')!r} "
                  f"cobertura={aviso.get('cobertura')!r} "
                  f"fecha={aviso.get('fecha_creacion_aviso')}")
            print(f"       placa_asegurado={aviso.get('placa_asegurado')} "
                  f"placa_tercero={aviso.get('placa_tercero')}")

    print()
    print("Smoke test Orbika exitoso.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--placa", required=True, help="Placa a consultar en Orbika")
    parser.add_argument(
        "--session",
        default="orbika_session.json",
        help="Archivo JSON con sesion capturada (default: orbika_session.json)",
    )
    args = parser.parse_args()
    main(args.placa, Path(args.session))
