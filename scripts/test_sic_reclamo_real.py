"""
Script de prueba real contra la API SIC.

NO es un test unitario — requiere credenciales reales y acceso a red.
Ejecutar desde la raíz del proyecto:

    python scripts/test_sic_reclamo_real.py --placa EJ1949 --expediente 5134134

Las credenciales se cargan automáticamente desde el archivo .env del proyecto
(SIC_USERNAME y SIC_PASSWORD). También se pueden pasar como args o env vars:

    python scripts/test_sic_reclamo_real.py \
        --username TU_USUARIO_SIC \
        --password TU_PASSWORD_SIC \
        --placa EJ1949 \
        --expediente 5134134

Salida esperada:
  [OK] Auth exitosa — sub: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
  [OK] Usuario — userCompanyID: 99, codPais: PAN
  [OK] EventId encontrado: 1788291
  [OK] Detalle evento obtenido — noPoliza: 02-93-1142585-1
  [OK] DataCollector — reclamo armado:
       Póliza:       02-93-1142585-1
       Cobertura:    Colisión o Vuelco
       Reserva:      1300.0
       Siniestro:    2026-04-16 12:14 — Al frente del colegio...
       Conductor:    Cristobal cedeño marrone (4-218-210) | M | 65 años | Pendiente
       Ajustador:    158
"""
import argparse
import json
import os
import sys

# Asegurar que src/ esté en el path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Cargar .env del proyecto automáticamente (SIC_USERNAME, SIC_PASSWORD, etc.)
_project_root = os.path.join(os.path.dirname(__file__), "..")
_dotenv_path  = os.path.join(_project_root, ".env")
if os.path.isfile(_dotenv_path):
    try:
        from dotenv import load_dotenv
        load_dotenv(_dotenv_path, override=False)
    except ImportError:
        # python-dotenv no instalado — parseo manual mínimo
        with open(_dotenv_path) as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _, _v = _line.partition("=")
                    os.environ.setdefault(_k.strip(), _v.strip())


def main():
    parser = argparse.ArgumentParser(description="Test real contra SIC API")
    parser.add_argument("--username",    default=os.environ.get("SIC_USERNAME", ""))
    parser.add_argument("--password",    default=os.environ.get("SIC_PASSWORD", ""))
    parser.add_argument("--placa",       required=True)
    parser.add_argument("--expediente",  required=True)
    parser.add_argument("--case-number", default="TEST-001")
    parser.add_argument("--base-url",    default="https://api-bkp.claims-sic.apps-connectassistance.com")
    parser.add_argument("--dump-raw",    action="store_true",
                        help="Imprimir JSON completo del evento SIC (para descubrir campos)")
    args = parser.parse_args()

    if not args.username or not args.password:
        print("[ERROR] Credenciales requeridas: --username y --password (o SIC_USERNAME / SIC_PASSWORD)")
        sys.exit(1)

    os.environ["SIC_API_BASE_URL"] = args.base_url

    # Importar aquí para que el PYTHONPATH ya esté configurado
    from src.tools.create_reclamo_premium.infrastructure.sic_reclamo_client import SICReclamoClient
    from src.tools.create_reclamo_premium.service.data_collector import DataCollector

    # ------------------------------------------------------------------
    # Stub de sesión con credenciales planas (sin SSM para el test local)
    # ------------------------------------------------------------------
    class CredStub:
        def __init__(self, username, password):
            self._u = username
            self._p = password
        def load_credentials(self):
            return self._u, self._p

    session = CredStub(args.username, args.password)
    client  = SICReclamoClient(session)

    # ------------------------------------------------------------------
    # Paso 1: Auth
    # ------------------------------------------------------------------
    print("\n--- Paso 1: Auth ---")
    try:
        token, sub = client._autenticar()
        print(f"[OK] Auth exitosa — sub: {sub}")
    except Exception as e:
        print(f"[FAIL] Auth: {e}")
        sys.exit(1)

    headers = client._bearer_headers(token)

    # ------------------------------------------------------------------
    # Paso 2: Datos de usuario
    # ------------------------------------------------------------------
    print("\n--- Paso 2: Datos de usuario ---")
    try:
        company_id, pais = client._obtener_datos_usuario(sub)
        print(f"[OK] Usuario — userCompanyID: {company_id}, codPais: {pais}")
    except Exception as e:
        print(f"[FAIL] Datos usuario: {e}")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Paso 3: Buscar EventId por expediente
    # ------------------------------------------------------------------
    print(f"\n--- Paso 3: Buscar EventId para placa={args.placa} expediente={args.expediente} ---")
    try:
        event_id = client._buscar_event_id_por_expediente(
            args.placa, args.expediente, company_id, pais, headers
        )
        print(f"[OK] EventId encontrado: {event_id}")
    except Exception as e:
        print(f"[FAIL] Buscar EventId: {e}")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Paso 4: Detalle del evento
    # ------------------------------------------------------------------
    print(f"\n--- Paso 4: GET /api/v1/events/{event_id} ---")
    try:
        evento = client._obtener_detalle_evento(event_id, headers)
        print(f"[OK] Detalle obtenido — noPoliza: {evento.get('noPoliza')}")
        print(f"     EventRecord:     {evento.get('EventRecord')}")
        print(f"     driverId:        {evento.get('driverId')}")
        print(f"     driverGender:    {evento.get('driverGender')}")
        print(f"     driverBirthDate: {evento.get('driverBirthDate')}")
        print(f"     IndResponsible:  '{evento.get('IndResponsible')}'")
        coverages = evento.get("coverages") or []
        print(f"     coverages:       {[c.get('coverageName') for c in coverages]}")
        # Campos tarjeta de propiedad — intentar nombres conocidos
        for campo in ("propertyCard", "cardProperty", "vehicleCard", "nroTarjeta", "tarjetaPropiedad"):
            val = evento.get(campo)
            if val is not None:
                print(f"     {campo}: {val}")
        if args.dump_raw:
            print(f"\n--- RAW evento SIC (todos los campos) ---")
            print(json.dumps(evento, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"[FAIL] Detalle evento: {e}")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Paso 5: DataCollector completo
    # ------------------------------------------------------------------
    print(f"\n--- Paso 5: DataCollector.recolectar() ---")
    try:
        collector = DataCollector(sic_client=client, ci_scraper=None)
        reclamo   = collector.recolectar(args.case_number, args.placa, args.expediente)

        print(f"[OK] Reclamo armado:")
        print(f"     Póliza:       {reclamo.numero_poliza}")
        print(f"     Cobertura:    {reclamo.poliza.cobertura}")
        print(f"     Reserva:      {reclamo.poliza.reserva}")
        print(f"     Tipo:         {reclamo.siniestro.tipo}")
        print(f"     Fecha:        {reclamo.siniestro.fecha} {reclamo.siniestro.hora}")
        print(f"     Lugar:        {reclamo.siniestro.lugar[:60]}...")
        print(f"     Conductor:    {reclamo.conductor.nombre} {reclamo.conductor.apellido}")
        print(f"                   Cédula: {reclamo.conductor.cedula}")
        print(f"                   Sexo: {reclamo.conductor.sexo} | Edad: {reclamo.conductor.edad} años")
        print(f"                   Nacimiento: {reclamo.conductor.fecha_nacimiento or '(no disponible)'}")
        print(f"                   Responsabilidad: {reclamo.conductor.responsabilidad}")
        print(f"     Vehículo:     Tarjeta propiedad: {reclamo.vehiculo.tarjeta_propiedad or '(no disponible)'}")
        print(f"     Ajustador:    {reclamo.ajustador_interno}")
        print(f"     Recibo docs:  {reclamo.siniestro.fecha_recibo_documentos}")

        print(f"\n--- JSON completo ---")
        print(json.dumps(reclamo.to_dict(), ensure_ascii=False, indent=2))

    except Exception as e:
        print(f"[FAIL] DataCollector: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print("\n[✓] Test real completado exitosamente.")


if __name__ == "__main__":
    main()
