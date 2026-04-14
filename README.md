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
│   └── state_store/         # U1 — helpers DynamoDB EstadoFlujo ✅
└── tools/                   # Lambda tools (Action Groups de Bedrock)
    ├── get_bandeja_crm/     # U2 — F1: bandeja Salesforce
    ├── review_historial_crm/ # U2 — F2: historial + criterio Panamá
    ├── extract_expediente_sic/ # U3 — F6-SIC: extracción SIC
    ├── extract_expediente_crm/ # U3 — F6-CRM: adjuntos desde Salesforce CRM
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
| U2 Agente Ingesta | F1 bandeja CRM + F2 historial | ✅ Completo — F1 100% · F2 87% scraper (Playwright excluido) |
| U3 Agente Expediente | F6-SIC + F6-CRM + F7 existencia docs | ✅ F6-SIC completo · F6-CRM completo (100% handler, 72% scraper) · F7 pendiente |
| U4 Agente Orbika | F8 Orbika + F9 responsabilidad | ⏳ Pendiente |
| U5 Agente Cierre | F13 nota CRM + estado | ⏳ Pendiente |

---

## Variables de entorno

Cada Lambda tool lee su config desde variables de entorno inyectadas por AWS.
Ver `src/tools/<nombre>/config/` para los valores por ambiente.

| Variable | Descripción | Usado en |
|----------|-------------|----------|
| `ESTADO_FLUJO_TABLE` | Nombre de la tabla DynamoDB EstadoFlujo | State Store |
| `RESULTADO_CASO_TABLE` | Nombre de la tabla DynamoDB ResultadoCaso | Observabilidad |
| `DRY_RUN` | `true` en piloto — el agente no escribe en CRM | U5 Cierre |
| `BATCH_SIZE_SSM_PATH` | Path SSM del parámetro BATCH_SIZE | trigger_daily |
| `SSM_SF_COOKIES_PATH` | Path SSM con storageState de sesión Salesforce | U2 get_bandeja_crm |
| `SF_REPORT_URL` | URL del reporte de bandeja en Salesforce | U2 get_bandeja_crm |
| `SSM_SIC_STATE_PATH` | Path SSM con storageState de sesión SIC | U3 extract_expediente_sic |
| `SSM_SIC_USERNAME_PATH` | Path SSM con usuario SIC | U3 extract_expediente_sic |
| `SSM_SIC_PASSWORD_PATH` | Path SSM con contraseña SIC | U3 extract_expediente_sic |
| `SSM_SF_COOKIES_PATH` | Path SSM con storageState de sesión Salesforce | U3 extract_expediente_crm (también U2) |

---

## Rama activa

`HAB-6289` — construcción U6, U1 y U2 (F1)

---

## Pendiente próxima sesión

### U2 Agente Ingesta — F1 scraper (requiere acceso Salesforce)
El scraper `src/tools/get_bandeja_crm/infrastructure/salesforce_scraper.py` tiene
selectores CSS y columnas **placeholder**. Antes de usar en producción:

1. Abrir el Salesforce de Sura Panamá en Chrome DevTools
2. Localizar la vista de bandeja de casos (URL real)
3. Inspeccionar los selectores de la tabla y el orden de columnas
4. Actualizar `_SELECTOR_TABLA`, `_SELECTOR_FILAS` y `_extraer_casos()` con los valores reales
5. Ejecutar el scraper en modo headful (`headless=False`) para validar

### U2 Agente Ingesta — F2 (siguiente a implementar)
Lambda tool `review_historial_crm`:
- Lee el historial de notas del caso en Salesforce (RPA, mismas cookies)
- Detecta si aplica el criterio Panamá (ítem §4.1 del protocolo)
- Retorna `HistorialCRM` con `aplica_criterio_panama: bool` + extracto relevante

### Decisión de infraestructura pendiente
CDK vs Terraform — esperando respuesta del equipo de arquitectura.
Una vez definido, correr `/mommo-devops` para aprovisionar:
- DynamoDB: EstadoFlujo + ResultadoCaso
- Lambdas de cada tool + Lambda trigger_daily
- Bedrock: Agente supervisor + 4 sub-agentes + Knowledge Base
- SSM: BATCH_SIZE + SSM_SF_COOKIES_PATH (requiere auth manual inicial)
