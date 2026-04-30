"""
Verifica y reconecta la VPN de forma aislada.

Uso:
    python scripts/check_vpn.py              # solo verificar
    python scripts/check_vpn.py --reconectar # verificar y reconectar si está caida
"""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.shared.notificador import Notificador
from src.shared.vpn_monitor import VPNMonitor


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Verifica/reconecta VPN FortiClient")
    parser.add_argument("--reconectar", action="store_true",
                        help="Intentar reconectar si la VPN está caida")
    args = parser.parse_args()

    notif   = Notificador.desde_env()
    monitor = VPNMonitor.desde_env(notif)

    activa = monitor.verificar()
    print(f"[VPN] Estado: {'ACTIVA' if activa else 'CAIDA'}")

    if activa:
        print("[VPN] No se requiere acción.")
        return

    if not args.reconectar:
        print("[VPN] Usar --reconectar para intentar reconexión.")
        return

    print(f"[VPN] Intentando reconectar perfil '{monitor._vpn_profile}'...")
    ok = monitor.reconectar()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
