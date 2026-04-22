"""
Script de prueba real contra la API de Consulta Integral.

NO es un test unitario — requiere VPN activa y acceso a http://ptykappa.
Ejecutar desde la raíz del proyecto:

    python scripts/test_ci_real.py --placa ED1370 --fecha 2026-10-15

Args opcionales:
    --base-url    URL base de CI (default: http://ptykappa)
    --placa       Placa del vehículo (requerida)
    --fecha       Fecha del siniestro ISO YYYY-MM-DD (opcional — muestra todas las pólizas si se omite)

Salida esperada:
  --- Paso 1: AseguradoPlaca ---
  [OK] 2 asegurado(s) encontrado(s):
       1. MARIO ABDIEL PEREZ  (8-808-694)
       2. RICARDO BRAGA       (E-8-133188)

  --- Paso 2: Polizas por asegurado ---
  [OK] 8-808-694 → 1 póliza(s)
       02-98-1246363-0 | Vigente | 07/01/2026 – 07/01/2027 | Suma: 12400.0

  --- Paso 3: Selección por fecha 2026-10-15 ---
  [OK] Póliza seleccionada:
       Número:  02-98-1246363-0
       Estado:  Vigente
       Vigencia: 2026-07-01 → 2027-07-01
       Suma:    12400.0
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

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


def main():
    parser = argparse.ArgumentParser(description="Test real contra Consulta Integral API")
    parser.add_argument("--placa",    required=True, help="Placa del vehículo (ej. ED1370)")
    parser.add_argument("--fecha",    default=None,  help="Fecha siniestro ISO YYYY-MM-DD (opcional)")
    parser.add_argument("--base-url", default=os.environ.get("CI_BASE_URL", "http://ptykappa"))
    args = parser.parse_args()

    from src.tools.create_reclamo_premium.infrastructure.consulta_integral_scraper import (
        ConsultaIntegralClient,
        _parse_vigi,
    )
    import requests

    client = ConsultaIntegralClient(ci_base_url=args.base_url)

    print(f"\n{'='*55}")
    print(f"  Consulta Integral — Test Real")
    print(f"  Base URL: {args.base_url}")
    print(f"  Placa:    {args.placa}")
    if args.fecha:
        print(f"  Fecha:    {args.fecha}")
    print(f"{'='*55}\n")

    # ------------------------------------------------------------------
    # Paso 1: AseguradoPlaca
    # ------------------------------------------------------------------
    print(f"--- Paso 1: GET /api/api/AseguradoPlaca?id={args.placa} ---")
    try:
        asegurados = client._obtener_asegurados(args.placa)
        if not asegurados:
            print(f"[WARN] Sin asegurados para placa '{args.placa}'")
            sys.exit(0)
        print(f"[OK] {len(asegurados)} asegurado(s):")
        for i, a in enumerate(asegurados, 1):
            cedula = a.get("identificación") or a.get("identificacion", "")
            print(f"     {i}. {a.get('Nombre', '')}  ({cedula})")
    except RuntimeError as e:
        print(f"[FAIL] {e}")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Paso 2: Polizas por asegurado
    # ------------------------------------------------------------------
    print(f"\n--- Paso 2: GET /api/api/Polizas por asegurado ---")
    todas_polizas = []
    for asegurado in asegurados:
        cedula = asegurado.get("identificación") or asegurado.get("identificacion", "")
        if not cedula:
            continue
        polizas = client._obtener_polizas_cedula(cedula, args.placa)
        print(f"[OK] {cedula} → {len(polizas)} póliza(s)")
        for p in polizas:
            print(f"     {p.get('Póliza', '?')} | {p.get('Estado', '?')} "
                  f"| {p.get('Vigi', '?')} – {p.get('Vigf', '?')} "
                  f"| Suma: {p.get('Suma', '?')}")
        todas_polizas.extend(polizas)

    if not todas_polizas:
        print("[WARN] No se encontraron pólizas")
        sys.exit(0)

    # ------------------------------------------------------------------
    # Paso 3: Selección (si se dio fecha)
    # ------------------------------------------------------------------
    if args.fecha:
        print(f"\n--- Paso 3: Selección por fecha {args.fecha} ---")
        try:
            resultado = client.obtener_datos_poliza(args.placa, fecha_siniestro=args.fecha)
            print(f"[OK] Póliza seleccionada:")
            print(f"     Número:   {resultado['numero_poliza']}")
            print(f"     Estado:   {resultado['estado']}")
            print(f"     Vigencia: {resultado['vigi']} → {resultado['vigf']}")
            print(f"     Suma:     {resultado['suma_asegurada']}")
            print(f"     Cobertura: {resultado['cobertura'] or '(no disponible en CI)'}")
        except RuntimeError as e:
            print(f"[FAIL] {e}")
            sys.exit(1)
    else:
        print(f"\n[INFO] Pasá --fecha YYYY-MM-DD para ver la póliza seleccionada para esa fecha.")

    print(f"\n[✓] Test CI completado.")


if __name__ == "__main__":
    main()
