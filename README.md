# Agente Analista — Sura Panamá (AAP-I1)

Automatización del flujo administrativo de ajuste de siniestros para Sura Panamá.
Arquitectura Multi-Agent Collaboration sobre AWS Bedrock — Tier A (sin VPN), Fase 1.

**Flujo cubierto:** F1 → F2 → F6 → F7(existencia docs) → F8 → F9 → F13
**Volumen:** ~1,648 casos/mes

---

## Setup

```bash
# Crear y activar el ambiente virtual
python -m venv agente-env
agente-env\Scripts\activate      # Windows
# source agente-env/bin/activate  # Mac/Linux

# Instalar dependencias de desarrollo
pip install -r requirements-dev.txt
```

---

## Correr tests

```bash
# Todos los tests con reporte de coverage
pytest tests/ -v --cov=src --cov-report=term-missing

# Solo un módulo específico
pytest tests/shared/ -v
```

---

## Estructura del proyecto

```
src/
├── shared/
│   ├── observability/       # U6 — logging y métricas del piloto ✅
│   │   ├── logger.py        # log_decision() + log_tool() → CloudWatch JSON
│   │   └── resultado_caso.py # ResultadoCasoRepository → DynamoDB
│   └── state_store/         # U1 — helpers DynamoDB EstadoFlujo 🔄 en progreso
└── tools/                   # Lambda tools (Action Groups de Bedrock)
    ├── get_bandeja_crm/     # U2 — F1: bandeja Salesforce
    ├── review_historial_crm/ # U2 — F2: historial + criterio Panamá
    ├── extract_expediente_sic/ # U3 — F6: extracción SIC
    ├── validate_documentos/ # U3 — F7: existencia de documentos
    ├── check_orbika/        # U4 — F8: estado aviso Orbika
    ├── validate_responsabilidad/ # U4 — F9: clasificación responsabilidad
    ├── close_case/          # U5 — F13: nota CRM + cambio estado
    └── trigger_daily/       # Trigger EventBridge → InvokeAgent por lote

tests/
├── shared/                  # Tests de utilidades compartidas
└── tools/                   # Tests de Lambda tools
```

---

## Estado de construcción

| Unit | Descripción | Estado |
|------|-------------|--------|
| U6 Observabilidad | `logger.py` + `ResultadoCasoRepository` | ✅ Completo — 100% coverage |
| U1 State Store | `EstadoFlujoRepository` — get, create, update_fase, close | ✅ Completo — 100% coverage |
| U2 Agente Ingesta | F1 bandeja CRM + F2 historial | ⏳ Pendiente |
| U3 Agente Expediente | F6 SIC + F7 existencia docs | ⏳ Pendiente |
| U4 Agente Orbika | F8 Orbika + F9 responsabilidad | ⏳ Pendiente |
| U5 Agente Cierre | F13 nota CRM + estado | ⏳ Pendiente |

---

## Variables de entorno

Cada Lambda tool lee su config desde variables de entorno inyectadas por AWS.
Ver `src/tools/<nombre>/config/` para los valores por ambiente.

| Variable | Descripción |
|----------|-------------|
| `ESTADO_FLUJO_TABLE` | Nombre de la tabla DynamoDB EstadoFlujo |
| `RESULTADO_CASO_TABLE` | Nombre de la tabla DynamoDB ResultadoCaso |
| `DRY_RUN` | `true` en piloto — el agente no escribe en CRM |
| `BATCH_SIZE_SSM_PATH` | Path SSM del parámetro BATCH_SIZE |

---

## Rama activa

`HAB-6289` — construcción U6 y U1
