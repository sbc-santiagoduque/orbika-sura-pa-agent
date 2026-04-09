"""
Build script: sbc-admin-tool-get-case-lambda
Genera: dist/sbc-admin-tool-get-case-lambda.zip

Uso:
    python scripts/build_sbc_admin_tool_get_case.py
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT       = Path(__file__).parent.parent
BUILD_DIR  = ROOT / "dist" / "sbc_admin_tool_get_case_build"
OUTPUT_ZIP = ROOT / "dist" / "sbc-admin-tool-get-case-lambda"

FILES = [
    "src/__init__.py",
    "src/tools/__init__.py",
    "src/tools/sbc_admin_tool_get_case/__init__.py",
    "src/tools/sbc_admin_tool_get_case/lambda_function.py",
    "src/tools/sbc_admin_tool_get_case/infrastructure/__init__.py",
    "src/tools/sbc_admin_tool_get_case/infrastructure/dynamo_repository.py",
]


def main():
    print("=== Build: sbc-admin-tool-get-case-lambda ===\n")

    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    BUILD_DIR.mkdir(parents=True)
    print(f"[1/3] Directorio de build limpio: {BUILD_DIR}")

    print("[2/3] Instalando dependencias (boto3)...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "boto3", "-t", str(BUILD_DIR), "-q"],
        check=True,
    )

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

    zip_path = shutil.make_archive(str(OUTPUT_ZIP), "zip", BUILD_DIR)
    print(f"\nZIP generado: {zip_path}")
    print(f"Handler AWS:  src.tools.sbc_admin_tool_get_case.lambda_function.lambda_handler")
    print("\nVariables de entorno requeridas en AWS:")
    print("  DYNAMO_TABLE_NAME  (default: sbc-admin-cases)")


if __name__ == "__main__":
    main()
