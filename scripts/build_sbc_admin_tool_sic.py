"""
Build script: sbc-admin-tool-sic-lambda
========================================
Empaqueta unicamente los archivos necesarios para el deployment manual
de la lambda sbc-admin-tool-sic-lambda en AWS.

Uso:
    python scripts/build_sbc_admin_tool_sic.py

Genera: dist/sbc-admin-tool-sic-lambda.zip
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT       = Path(__file__).parent.parent
BUILD_DIR  = ROOT / "dist" / "sbc_admin_tool_sic_build"
OUTPUT_ZIP = ROOT / "dist" / "sbc-admin-tool-sic-lambda"

FILES = [
    "src/__init__.py",
    "src/tools/__init__.py",
    "src/tools/sbc_admin_tool_sic/__init__.py",
    "src/tools/sbc_admin_tool_sic/lambda_function.py",
    "src/tools/sbc_admin_tool_sic/infrastructure/__init__.py",
    "src/tools/sbc_admin_tool_sic/infrastructure/sic_images_client.py",
    "src/tools/sbc_admin_tool_sic/infrastructure/dynamo_repository.py",
]


def main():
    print("=== Build: sbc-admin-tool-sic-lambda ===\n")

    # 1. Limpiar y recrear directorio de build
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    BUILD_DIR.mkdir(parents=True)
    print(f"[1/3] Directorio de build limpio: {BUILD_DIR}")

    # 2. Instalar dependencias externas
    print("[2/3] Instalando dependencias (requests)...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "requests", "-t", str(BUILD_DIR), "-q"],
        check=True,
    )

    # 3. Copiar archivos del proyecto
    print("[3/3] Copiando archivos del proyecto:")
    for rel_path in FILES:
        src  = ROOT / rel_path
        dest = BUILD_DIR / rel_path
        if not src.exists():
            print(f"  [ERROR] No encontrado: {src}")
            sys.exit(1)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        print(f"  + {rel_path}")

    # 4. Generar ZIP
    zip_path = shutil.make_archive(str(OUTPUT_ZIP), "zip", BUILD_DIR)
    print(f"\nZIP generado: {zip_path}")
    print(f"Handler AWS:  src.tools.sbc_admin_tool_sic.lambda_function.lambda_handler")
    print("\nVariables de entorno requeridas en AWS:")
    print("  SSM_SIC_API_USERNAME_PATH")
    print("  SSM_SIC_API_PASSWORD_PATH")


if __name__ == "__main__":
    main()
