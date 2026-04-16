# Agente Analista — Sura Panamá

Herramientas RPA e IA para automatización del flujo de reclamos de Sura Panamá.

## Estado actual — Branch `AAP-RPA1-create-reclamo-premium`

### Tool: `create_reclamo_premium` — Phase A (Recolección de datos)

**Estado:** Implementado y validado contra API real (2026-04-16).

Recolecta todos los datos necesarios para abrir un reclamo en el sistema Premium,
usando el SIC REST API como fuente primaria. Consulta Integral es fallback cuando
SIC no provee número de póliza o cobertura.

---

## Arquitectura

```
src/
├── shared/
│   └── sic_api/
│       └── sic_api_session.py          # Credenciales SIC desde AWS SSM
└── tools/
    └── create_reclamo_premium/
        ├── lambda_function.py          # Entry point (Lambda / RPA standalone)
        ├── infrastructure/
        │   ├── sic_reclamo_client.py   # Cliente SIC REST API (4 requests)
        │   └── consulta_integral_scraper.py  # Fallback CI (pendiente VPN)
        └── service/
            ├── data_collector.py       # Orquesta recolección → DatosReclamo
            └── reclamo_models.py       # Dataclasses: DatosReclamo, DatosSiniestro, etc.

tests/
└── tools/
    └── test_create_reclamo_premium.py  # 49 tests unitarios (todos passing)

scripts/
└── test_sic_reclamo_real.py            # Test de integración real vs SIC API
```

---

## Flujo SIC REST API (confirmado contra entorno real)

```
POST /api/v1/users/auth
    → accessToken + sub

GET  /api/v1/users/{sub}
    → userCompanyID + codPais

GET  /api/v2/events/search?filterType=INSURED_PLATE&filterText={placa}&...
    → lista de eventos → filtrar por eventRecord == expediente → extraer EventId

GET  /api/v1/events/{EventId}
    → detalle completo del evento (noPoliza, conductor, siniestro, coverages)
```

### Campos del detalle de evento (`GET /api/v1/events/{EventId}`)

| Campo SIC | Mapeado a | Notas |
|---|---|---|
| `noPoliza` | `numero_poliza` | Disponible directo — CI no necesario si está presente |
| `eventDateSinister` | `siniestro.fecha` | Formato ISO date |
| `timeSinister` | `siniestro.hora` | Truncado a `HH:MM` |
| `placeDirectionSinister` | `siniestro.lugar` | |
| `storyDetail` | `siniestro.descripcion` | Relato del conductor |
| `coverages[0].coverageName` | `poliza.cobertura` | Puede ser `[]` — ver nota |
| `driverId` | `conductor.cedula` | Cédula panameña |
| `driverName` | `conductor.nombre` | |
| `driverLastName` | `conductor.apellido` | Tiene leading space — se aplica `.strip()` |
| `driverGender` | `conductor.sexo` | Entero: `2=M`, `1=F` (confirmado 2026-04-16) |
| `driverBirthDate` | `conductor.edad` | ISO date → edad calculada en años |
| `IndResponsible` | `conductor.responsabilidad` | `"" → "Pendiente"`, `"1" → "Culpable"`, `"2" → "Inocente"` |

### Hallazgos confirmados en API real (evento EJ1949 / expediente 5134134)

- `coverages: []` — el endpoint puede devolver cobertura vacía. En ese caso el tipo
  de siniestro se infiere desde `storyDetail` (relato del conductor) con normalización
  de tildes (NFKD) para cubrir variantes como "rocé" → "roce".
- `driverLastName` lleva espacio inicial — se normaliza con `.strip()`.
- `IndResponsible: ""` cuando la responsabilidad no está determinada → `"Pendiente"`.
- `userCompanyID` en entorno real: `1713` (no hardcodear este valor).

### Inferencia de tipo de siniestro

Cuando `coverages` está vacío, `_determinar_tipo_siniestro()` aplica sobre `storyDetail`:

| Tipo | Keywords (sin tildes) |
|---|---|
| `Colision` | colisi, vuelco, choque, impacto, roce, golpe, raspó, rasguño, estrello, accidente, estacion, vía |
| `Robo` | robo, hurto, sustraccion, robaron, hurtaron |
| `Incendio` | incendio, fuego, quemado |

### Reglas de reserva (protocolo sección 8.5)

| Cobertura contiene | Reserva |
|---|---|
| `COLISI` / `VUELCO` | $1,300 |
| `ROBO` | $5,000 |
| `INCENDIO` | $2,500 |
| (default) | $1,000 |

> **Nota:** cuando `coverages: []`, la reserva queda en $1,000 (default) porque no
> hay nombre de cobertura para clasificar. El tipo de siniestro sí se infiere desde
> el relato, pero la reserva requiere el nombre formal de cobertura.

---

## Configuración

### Variables de entorno (Lambda)

| Variable | Requerida | Descripción |
|---|---|---|
| `SSM_SIC_API_USERNAME_PATH` | Sí | Ruta SSM del usuario SIC |
| `SSM_SIC_API_PASSWORD_PATH` | Sí | Ruta SSM de la contraseña SIC |
| `SIC_API_BASE_URL` | Sí | URL base SIC (ej. `https://api-bkp.claims-sic.apps-connectassistance.com`) |
| `CI_BASE_URL` | No | URL de Consulta Integral (requiere VPN). Si ausente, usa Stub |
| `CI_STUB_POLIZA` | No | Póliza fija para el Stub (desarrollo sin VPN) |
| `CI_STUB_COBERTURA` | No | Cobertura fija para el Stub (desarrollo sin VPN) |

### Credenciales locales (`.env`)

```env
SIC_USERNAME=usuario@sura.com.pa
SIC_PASSWORD=tu_password
```

---

## Tests

### Unitarios

```bash
python -m pytest tests/tools/test_create_reclamo_premium.py -v
# 49 passed
```

### Integración real (requiere red + credenciales en `.env`)

```bash
python scripts/test_sic_reclamo_real.py --placa EJ1949 --expediente 5134134
```

Output esperado con evento EJ1949 / 5134134:

```
[OK] Auth exitosa — sub: 22038386-8ff0-4798-8844-17265f326269
[OK] Usuario — userCompanyID: 1713, codPais: PAN
[OK] EventId encontrado: 1788291
[OK] Detalle obtenido — noPoliza: 02-93-1142585-1
[OK] Reclamo armado:
     Póliza:       02-93-1142585-1
     Cobertura:    (vacía — coverages=[])
     Reserva:      1000.0
     Tipo:         Colision  ← inferido desde storyDetail
     Fecha:        2026-04-16 12:14
     Lugar:        Al frente del colegio San Vicente de Paul, Santiago.
     Conductor:    Cristobal cedeño marrone (4-218-210) | M | 65 años | Pendiente
     Ajustador:    158
```

---

## Pendientes

- [ ] **Reserva cuando `coverages: []`** — inferir reserva desde `tipo` además del nombre de cobertura
- [ ] **Confirmar `IndResponsible`** — valores "1"/"2" con equipo de operaciones Sura
- [ ] **`ConsultaIntegralScraper`** — implementar selector mapping (requiere VPN CLI + FortiClient)
- [ ] **Phase B** — Premium Oracle Forms RPA (apertura del reclamo en Premium)
- [ ] **Integrar a Bedrock agent** — registrar como action group / tool en el agente analista

---

## Ramas

| Branch | Descripción |
|---|---|
| `main` | Base estable |
| `AAP-RPA1-create-reclamo-premium` | Tool de recolección de datos (Phase A) — activo |
