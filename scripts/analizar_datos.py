"""Analiza los JSONs de Phase A en scripts/datos/."""
import json
from pathlib import Path

datos = sorted(Path(__file__).parent.glob("datos/*.json"))
total = len(datos)

sin_fecha = []
sin_poliza = []

for f in datos:
    d = json.load(open(f, encoding="utf-8")).get("reclamo_data", {})
    conductor = d.get("conductor", {})
    if not conductor.get("fecha_nacimiento"):
        sin_fecha.append(f.stem)
    if not d.get("numero_poliza"):
        sin_poliza.append(f.stem)

print(f"Total JSONs procesados : {total}")
print(f"Con fecha_nacimiento   : {total - len(sin_fecha)}")
print(f"Sin fecha_nacimiento   : {len(sin_fecha)}")
if sin_fecha:
    print("  Casos:", sin_fecha)

print(f"Con numero_poliza      : {total - len(sin_poliza)}")
print(f"Sin numero_poliza      : {len(sin_poliza)}")
if sin_poliza:
    print("  Casos:", sin_poliza)
