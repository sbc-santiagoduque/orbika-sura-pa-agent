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
│   ├── sic_api/
│   │   └── sic_api_session.py          # Credenciales SIC desde AWS SSM
│   ├── estado_proceso.py               # Checkpoint JSON por caso (pipeline)
│   ├── retry.py                        # Decorador con_reintento + backoff
│   ├── notificador.py                  # Log interno + Telegram
│   └── vpn_monitor.py                  # Watchdog VPN + reconexión FortiClient
└── tools/
    └── create_reclamo_premium/
        ├── lambda_function.py          # Entry point (Lambda / RPA standalone)
        ├── infrastructure/
        │   ├── sic_reclamo_client.py   # Cliente SIC REST API (4 requests)
        │   └── consulta_integral_scraper.py  # Cliente CI REST (requiere VPN)
        └── service/
            ├── data_collector.py       # Orquesta recolección → DatosReclamo
            └── reclamo_models.py       # Dataclasses: DatosReclamo, DatosSiniestro, etc.

tests/
├── shared/
│   ├── test_estado_proceso.py          # 14 tests
│   └── test_retry.py                   # 7 tests
└── tools/
    └── test_create_reclamo_premium.py  # 66 tests unitarios — 87 total, todos passing

scripts/
├── procesar_casos.py                   # Pipeline nocturno Salesforce → Phase A → Phase B
├── open_premium.py                     # RPA Phase B (Oracle Forms via RDP)
├── test_sic_reclamo_real.py            # Test de integración real vs SIC API
└── test_rdp_connection.py              # Test de conexión RDP automatizada
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

---

## Phase B — Automatización Premium (escritorio remoto)

**Estado:** Flujo end-to-end funcional hasta Reservas inclusive. Guardado detrás de `--guardar` (2026-04-28).

Premium es una aplicación de escritorio que corre en un servidor remoto accedido
via RDP. La automatización usa `PyAutoGUI` + `pywinauto` corriendo en la máquina
local (o futura EC2 Windows).

### Stack de automatización de escritorio

| Librería | Rol |
|---|---|
| `pyautogui` | Screenshot, click por coordenadas, detección por imagen (template matching) |
| `pygetwindow` | Encontrar y enfocar ventanas por título |
| `pywinauto` | Envío de teclas directo al handle de la ventana (sin depender del foco del SO) |

### Flujo end-to-end (`scripts/open_premium.py`)

```
1.  Abrir SERVER PREMIUM.rdp  (mstsc)
2.  "Advertencia de seguridad" → click "Conectar" via pywinauto uia
3.  "Seguridad de Windows" → contraseña via uia type_keys
4.  Esperar escritorio estable (hash screenshot)
5.  Template matching ícono Premium → doble click
6.  Login Oracle Forms (Usuario / Contraseña / Base de datos)
7.  Menú: Alt → Right → Down → Down×3 → Right → Down → Right → Right → Right → Enter
        → 1.2.1.1-Apertura
8.  Consulta de Endosos: llenar póliza (4 partes) + fecha → F8
9.  Consulta de Automóviles Asegurados: captura
10. Click botón Coberturas del auto (template: boton_coberturas_auto.png)
11. Consulta de Coberturas: Down×4 → fila Colisión/Vuelco → click manito
12. Apertura del Reclamo — Generales (1):
      a. Fecha de Recibo de Documentos → hoy (DD-MM-YYYY)
      b. Tipo de siniestro → click label + código (ej. "30") + Tab → autocompleta
      c. Descripción del Siniestro → modal abre automáticamente → texto + Tab×2 + Enter
      d. Hora del siniestro → Enter para avanzar
      e. Lugar del siniestro → Enter para avanzar
13. Apertura del Reclamo — Generales (2):
      a. Click tab G2 (template: tab_generales_2.png)
      b. Lugar donde se encuentra → click (campo_lugar_conductor.png) → "Panama" → Tab
      c. Cédula → click (campo_cedula_conductor.png) → Enter → hash screenshot
             (modal "conductor no declarado" → Enter si cambió)
      d. Nombre → Enter, Apellido → Enter
      e. Sexo → Right (abre dropdown) → Up×1=FEMENINO / Up×2=MASCULINO → Enter×2
      f. Edad → Enter, Tel Residencial ("0") → Enter, Tel Oficina ("0") → Enter, Relación → Enter
      g. Se Declara (radio) → Left si Culpable (default Inocente)
14. Apertura del Reclamo — Generales (3):
      a. Click tab G3 (offset desde G2: left + width × 2.5)
      b. Descripción de Daños → click label → modal → texto + Tab×2 + Enter
      c. Ajustador Interno → "158" + Enter (valor fijo siempre)
15. Reservas:
      a. Click tab Reservas (template: tab_reservas.png)
      b. Cobertura → col_cobertura_reservas.png anchor + offset height×1.2 → código + Enter
      c. Monto de Reserva → escribir monto → PARAR AQUÍ (no guardar)
16. [--guardar] Guardar reclamo:
      a. Enter (confirma monto) → Alt+Down+Enter (disquete amarillo) → esperar 2s
      b. Click G1 (offset desde G2: left - width × 0.5)
      c. OCR región "No. de Reclamo" desde ancla titlebar → retorna número
```

### Uso

```bash
# Requiere terminal como Administrador

# Flujo completo (RDP + Premium + todas las pestañas + reservas)
python scripts/open_premium.py --poliza "02-98-1246363-0" --fecha-siniestro "2026-10-15"

# Flujo completo con guardado real del reclamo
python scripts/open_premium.py --poliza "02-98-1246363-0" --fecha-siniestro "2026-10-15" --guardar

# Saltar RDP (ya conectado), ejecutar desde login
python scripts/open_premium.py --step login

# Saltar hasta apertura (RDP + Premium ya listos)
python scripts/open_premium.py --step apertura --poliza "02-98-1246363-0" --fecha-siniestro "2026-10-15"

# Ejecutar solo un paso individual
python scripts/open_premium.py --step generales1
python scripts/open_premium.py --step generales2
python scripts/open_premium.py --step generales3
python scripts/open_premium.py --step reservas

# Ejecutar todas las pestañas del formulario (G1+G2+G3+Reservas) sin RDP/login/apertura
python scripts/open_premium.py --step formulario

# Pasar tipo de siniestro como código Oracle Forms
python scripts/open_premium.py --step generales1 --tipo-siniestro "30"
```

### Flags `--step`

| Flag | Qué ejecuta |
|---|---|
| `all` | Flujo completo (default) |
| `rdp` | Solo RDP |
| `premium` | Solo abrir app Premium |
| `login` | Solo login Oracle Forms |
| `apertura` | Solo Consulta de Endosos → selección cobertura |
| `generales1` | Solo llenar pestaña Generales (1) |
| `generales2` | Solo llenar pestaña Generales (2) |
| `generales3` | Solo llenar pestaña Generales (3) |
| `reservas` | Solo llenar pestaña Reservas |
| `formulario` | G1 + G2 + G3 + Reservas en secuencia |

### Variables de entorno (`.env`)

```env
RDP_PASSWORD=tu_password_rdp
PREMIUM_USERNAME=usuario_oracle
PREMIUM_PASSWORD=tu_password_premium
```

### Templates (`docs/screens/`)

| Archivo | Propósito |
|---|---|
| `titlebar_oracle_forms.png` | Ancla para calcular offset de ventana y OCR No. de Reclamo |
| `boton_consultar_unidades.png` | Botón tras F8 en Consulta de Endosos |
| `boton_coberturas_auto.png` | Ícono auto en Automóviles Asegurados |
| `boton_seleccionar_cobertura.png` | Manito en Consulta de Coberturas |
| `campo_fecha_recibo_docs.png` | Etiqueta "Fecha de Recibo de Documentos" |
| `campo_tipo_siniestro.png` | Etiqueta "Tipo de siniestro" (click label → offset derecho) |
| `campo_descripcion_siniestro.png` | Etiqueta "Descripción del Siniestro" |
| `campo_hora_siniestro.png` | Etiqueta "Hora del siniestro" |
| `campo_lugar_siniestro.png` | Etiqueta "Lugar del siniestro" |
| `tab_generales_2.png` | Pestaña Generales (2) — ancla para G1 (izq) y G3 (der×2.5) |
| `campo_cedula_conductor.png` | Etiqueta "Cédula:" en Generales (2) |
| `campo_lugar_conductor.png` | Etiqueta "Lugar donde se encuentra:" en Generales (2) — primer campo |
| `campo_descripcion_danos.png` | Etiqueta "Descripción de los daños:" en Generales (3) |
| `campo_ajustador_interno.png` | Etiqueta "Ajustador Interno:" en Generales (3) |
| `tab_reservas.png` | Pestaña "Reservas" |
| `col_cobertura_reservas.png` | Encabezado columna "Cobertura" en tabla Reservas |
| `titlebar_forms_modal.png` | Barra de título "Forms ×" — detecta cualquier popup Oracle Forms sin importar el mensaje |
| `titlebar_consulta_endosos.png` | Botón X de la ventana "Consulta de Endosos" — para cerrarla vía click |

### Tipos de siniestro (campo código en Generales 1)

| Código | Tipo |
|---|---|
| `10` | PERDIDA TOTAL COLISION |
| `20` | ROBO DE AUTO |
| `30` | COLISION |
| `40` | COMPRENSIVO |
| `50` | COLISION CONTRA PERSONA |
| `60` | PERDIDA TOTAL ROBO |
| `910` | INCENDIO |

### Códigos de cobertura (campo Cobertura en Reservas)

| Código | Cobertura |
|---|---|
| `E` | COLISION/VUELCO |
| `HUR` | HURTO |
| `INC` | INCENDIO |
| `D` | COMPRENSIVO |
| `B` | DAÑOS PROP AJENA |

### Hallazgos clave Phase B

- `pyautogui.press()` no funciona dentro del RDP — las teclas van al terminal Python. Solución: `pywinauto Desktop(backend="uia").window(...).type_keys()` envía directo al handle RDP.
- `pyautogui.FAILSAFE = False` requerido — el mouse llega a esquinas en campos del formulario.
- `Ctrl+A` en Oracle Forms selecciona todos los registros del bloque, no el texto del campo — nunca usarlo antes de escribir.
- `Tab` en Apertura del Reclamo abre una pestaña bloqueante — siempre navegar con Enter o click por template label.
- **Enter navega campos en Oracle Forms** igual que Tab, pero más confiable en este formulario. Estrategia: un solo click inicial en el primer campo, luego Enter para avanzar.
- **`with_spaces=True` obligatorio en `rdp.type_keys()`** — sin este flag los espacios se pierden silenciosamente. Aplica a **todos** los helpers `_k()` del script. Alternativa: `pyautogui.write("texto", interval=0.05)` para campos donde hay riesgo de perder foco tras `pyautogui.click()`.
- **LOV de Tipo de Siniestro:** escribir el código numérico directo (ej. "30") + Tab autocompleta sin abrir el diálogo LOV. La descripción del siniestro abre automáticamente en modal tras el Tab.
- **Modal "conductor no declarado en la Póliza":** pywinauto no puede detectar ventanas remotas del RDP. Solución: comparar hash del screenshot antes/después de Enter en cédula — si cambia, el modal apareció → otro Enter para cerrarlo.
- **Tabs similares G2/G3:** template matching confunde ambas pestañas. Solución: usar G2 como ancla y calcular G3 como `left + width × 2.5`. G1 se calcula como `left - width × 0.5`.
- **`ImageNotFoundException`** tiene `str(exc)` vacío — debe capturarse explícitamente antes del `except Exception` genérico, de lo contrario el error se silencia.
- **Sexo dropdown:** `{RIGHT}` abre, `{UP}×1`=FEMENINO / `{UP}×2`=MASCULINO, `{ENTER}×2` (primer Enter selecciona, segundo avanza al siguiente campo).
- **Generales (2) — Lugar donde se encuentra:** es el primer campo del formulario. Click → `pyautogui.write("Panama")` → Tab → cursor queda en Nombre. Luego click en Cédula y el flujo continúa normalmente.
- **Teléfonos en Generales (2):** siempre "0" para Residencial y Oficina — no hay número real disponible desde SIC.
- **Popups Oracle Forms:** detectar con `titlebar_forms_modal.png` (crop solo de la barra "Forms ×", agnóstico al mensaje). Siempre cerrar con Enter.
- **Reclamo duplicado (exit 3):** el popup aparece tras `Consultar Unidades` (F8). Cerrar popup con Enter → cerrar Consulta de Endosos con click X (`titlebar_consulta_endosos.png`) → `ReclamoDuplicadoError` → `procesar_casos.py` marca como `RECLAMO_EXISTENTE` y continúa.
- **Siniestro fuera de vigencia (exit 4):** popup aparece tras abrir Coberturas del auto. Cerrar popup → cerrar Automóviles (X + confirmar) → cerrar Endosos (X) → `SiniestroFueraVigenciaError` → `ERROR_PERMANENTE` (requiere revisión manual).
- **Delays en Reservas necesarios:** Oracle Forms necesita tiempo entre acciones; 0.6–0.8s tras clicks y antes/después de escribir para que el UI procese.
- `cmdkey` + NLA causaba "La conexión se interrumpió" → solución: abrir el `.rdp` existente del escritorio. `authentication level:i:0` en el `.rdp` es clave (sin validación de cert).

### Arquitectura futura (EC2)

```
Lambda Phase A          SQS             EC2 Windows (admin)
─────────────────  →  ──────────  →   ──────────────────────────
DatosReclamo JSON       cola            PyAutoGUI + pywinauto
                                        RDP → Premium
                                        Llena formulario
                                        Confirma apertura reclamo
                                        Retorna No. de Reclamo
```

---

## Pipeline completo (`scripts/procesar_casos.py`)

Orquesta el flujo nocturno end-to-end: reporte Salesforce → Phase A (SIC) → Phase B (Premium RPA).

```bash
# Dry-run: listar casos pendientes sin procesar
python scripts/procesar_casos.py --reporte reporte.xls --dry-run

# Phase A para todos los pendientes → guarda JSON en scripts/datos/
python scripts/procesar_casos.py --reporte reporte.xls

# Phase A + Phase B (requiere RDP activo y Premium abierto)
python scripts/procesar_casos.py --reporte reporte.xls --fase-b

# Phase A + Phase B + guardar reclamos reales
python scripts/procesar_casos.py --reporte reporte.xls --fase-b --guardar

# Sin watchdog VPN (sesión ya estable)
python scripts/procesar_casos.py --reporte reporte.xls --sin-vpn-check

# Ajustar tolerancia de errores (default: 5 casos sin avance antes de parar)
python scripts/procesar_casos.py --reporte reporte.xls --max-sin-avance 3
```

### Robustez nocturna

| Componente | Mecanismo |
|---|---|
| Checkpoint por caso | `scripts/estado/estado.json` — reanuda donde quedó si el proceso se interrumpe |
| Retry con backoff | Phase A: 3 intentos, 10s/60s/180s entre reintentos |
| VPN watchdog | Antes de cada caso: RDP activo = VPN activa; fallback ping a host interno |
| Reconexión VPN | Lanza FortiClient → notifica Telegram → espera aprobación Microsoft Authenticator |
| Sin avance | Contador de casos consecutivos sin avance; stop cuando alcanza `--max-sin-avance` |
| Log + Telegram | Mensajes clave (OK, alertas, errores, resumen final) enviados al bot Telegram |

### Ciclo de vida de un caso

```
PENDIENTE → FASE_A_OK → FASE_B_INICIADO → COMPLETADO
                                        ↘ RECLAMO_EXISTENTE
              ↘ ERROR_PERMANENTE (retry agotado o Phase B exit != 0/2)
```

### Lógica de "reclamo ya creado"

- Primera línea: columna `Número de reclamo en el core` no vacía en el reporte → skip automático
- Segunda línea: Premium muestra popup al guardar → `ReclamoExistenteError` → exit code 2 → estado `RECLAMO_EXISTENTE`

### Variables de entorno (`script/.env` o `.env` en raíz)

```env
# Credenciales SIC
SIC_USERNAME=usuario@sura.com.pa
SIC_PASSWORD=tu_password
SIC_API_BASE_URL=https://api-bkp.claims-sic.apps-connectassistance.com

# Telegram (opcional — solo log si ausente)
TELEGRAM_BOT_TOKEN=123456:ABC-token
TELEGRAM_CHAT_ID=tu_chat_id

# VPN
VPN_FORTICLIENT_PATH=C:\Program Files\Fortinet\FortiClient\FortiClient.exe
VPN_PROFILE_NAME=nombre_perfil_vpn
VPN_HOST_INTERNO=10.0.0.1
VPN_2FA_TIMEOUT=120
```

### Módulos compartidos (`src/shared/`)

| Módulo | Responsabilidad |
|---|---|
| `estado_proceso.py` | Checkpoint JSON por caso; estados del ciclo de vida |
| `retry.py` | Decorador `@con_reintento` con backoff configurable |
| `notificador.py` | Log interno + Telegram; `solicitar_aprobacion_vpn()` |
| `vpn_monitor.py` | Verificación RDP/ping + reconexión FortiClient |

**Phase B con `--datos-json`:**
```bash
python scripts/open_premium.py --datos-json scripts/datos/02191935.json --guardar
```
Los campos se mapean automáticamente: tipo_siniestro → código Oracle Forms, cobertura → código Reservas.

---

## Pendientes

### Phase B — en progreso
- [x] **Conectar DatosReclamo → formulario** — `--datos-json` implementado (2026-04-28)
- [x] **Detección popup "reclamo ya creado"** — `ReclamoExistenteError` via template G2 (2026-04-28)
- [x] **Reclamo duplicado Oracle Forms** — `ReclamoDuplicadoError` exit 3 (2026-04-28)
- [x] **Siniestro fuera de vigencia** — `SiniestroFueraVigenciaError` exit 4 (2026-04-28)
- [x] **Generales (2) — Lugar donde se encuentra** — campo "Panama" + `with_spaces=True` global (2026-04-28)
- [ ] **Calibrar `_guardar_reclamo()`** — validar secuencia Alt+Down+Enter; calibrar OCR No. de Reclamo
- [ ] **Tesseract en PATH** — instalado pero ejecutable no encontrado; necesario para OCR número de reclamo
- [ ] **Navegación multi-reclamo** — después de guardar, volver al menú apertura para el siguiente caso
- [ ] **Propiedad Ajena / Personas Lesionadas** — pestañas pendientes cuando aplique

### Phase A — pendiente
- [ ] **Reserva cuando `coverages: []`** — inferir desde `tipo` cuando cobertura vacía
- [ ] **Confirmar `IndResponsible`** — valores "1"/"2" con equipo de operaciones Sura

### Infraestructura
- [ ] **Integrar a Bedrock agent** — registrar `create_reclamo_premium` como action group

---

## Ramas

| Branch | Descripción |
|---|---|
| `main` | Base estable |
| `AAP-RPA1-create-reclamo-premium` | Phase A (datos SIC) + base RDP Phase B — activo |
