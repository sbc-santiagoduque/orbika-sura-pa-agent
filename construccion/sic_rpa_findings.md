# SIC RPA Findings — sic.connectasistencia.com

Hallazgos validados contra el sistema real durante smoke test (2026-04-06).
Placa de prueba: CU7559

---

## URLs

| Recurso | URL |
|---------|-----|
| Login / raiz | `https://sic.connectasistencia.com` |
| Busqueda | `https://sic.connectasistencia.com/events-claims` |
| Expediente | `https://sic.connectasistencia.com/claims/{uuid}?force=1` |

**IMPORTANTE:** La URL `/login` redirige directo al dashboard si hay sesion activa.
El login vive en la raiz `/`. Usar `SIC_BASE_URL` como `SIC_LOGIN_URL`.

---

## Selectores validados

### Login
```
input#username           → campo usuario (label: "Usuario *")
input#password           → campo contrasena (label: "Contrasena *")
button[type='submit']    → boton "Ingresar"
```

Deteccion de login exitoso: esperar que la URL cambie de la raiz.
```python
page.wait_for_url(lambda url: url.rstrip("/") != SIC_BASE_URL.rstrip("/"))
```
**NO usar** `"login" not in url` — el login page IS la raiz, no tiene "login" en la URL.

### Busqueda de placa
```
div[role='combobox']                              → MUI Select (filtro)
li[role='option']:has-text('Placa Asegurado')     → opcion del dropdown
input[placeholder='Buscar Placa Asegurado']       → input de placa
```
Flujo: click combobox → wait option → click option → fill input → press Enter.

### Tabla de resultados
```
table[aria-label='simple table'] tbody tr        → filas de resultado
```

**Skeleton rows:** React renderiza filas vacias (`['/', '', '']`) antes de cargar datos.
Esperar 2.5s despues de `wait_for_selector` antes de re-consultar filas.

**Usar `page.locator().nth(i).click()`** para el click — los `ElementHandle` de
`query_selector_all` quedan stale cuando React re-renderiza.

### Estructura de columnas (por indice)
```
[0]  icono/estado (vacio)
[1]  numero de caso (ej: "5105397-1")
[2]  estado (ej: "Pendiente de Informacion")
[3]  fecha apertura (ej: "06 Abril, 2026 09:31 AM")  ← formato espanol
[4]  nombre asegurado
[5]  placa asegurado
[6]  placa tercero
[7]  poliza
[8]  compania
[9]  inspector
[10-13] columnas adicionales (vacias en prueba)
```

**Formato de fecha:** `"DD MesEspanol, YYYY HH:MM AM/PM"` — requiere parse con meses en espanol.

### Apertura del expediente
El click en una fila abre el expediente en **nueva pestana** (no navegacion SPA).
Usar `context.expect_page()` para capturarla.

```python
with context.expect_page() as new_page_info:
    page.locator(_SEL_RESULT_ROWS).nth(idx).click()
expediente_page = new_page_info.value
expediente_page.wait_for_load_state("domcontentloaded")
```

### Imagenes del expediente
```
img[src*='amazonaws']    → imagenes S3 (Opcion A y B)
```

**Importante:**
- El alt real es `"Imagen de galeria"` (con acento: `í`) pero no es fiable entre versiones.
- Usar `src*='amazonaws'` — mas robusto y cubre todas las imagenes.
- Las imagenes estan fuera del viewport (lazy loading) → usar `state="attached"`, no `"visible"`.

---

## Sesion y credenciales

- **Sin 2FA** — login totalmente automatizable con usuario/contrasena.
- **storageState:** 1 cookie capturada. Suficiente para mantener sesion entre invocaciones.
- **Deteccion de sesion expirada:** si post-goto la URL es la raiz → re-login automatico.
- **Credenciales en SSM:** `SSM_SIC_USERNAME_PATH` + `SSM_SIC_PASSWORD_PATH`.
- **storageState en SSM:** `SSM_SIC_STATE_PATH` (SecureString, JSON).

---

## Imagenes S3

Bucket: `inspeccionespty` (us-east-2)
Patron URL base: `https://inspeccionespty.s3.us-east-2.amazonaws.com/{caso_id}/{filename}`
Firma: `?X-Amz-Expires=604800` (7 dias de validez)

**Opcion A (fase actual):** contar imagenes (`imagen_count > 0` → `tiene_documentos=True`)
**Opcion B (fase futura):** pasar `imagen_urls_signed` a Bedrock Vision para clasificacion.
Las URLs pre-firmadas son validas 7 dias — Bedrock puede accederlas directamente sin re-auth.

---

## Caso de prueba real

| Campo | Valor |
|-------|-------|
| Placa | CU7559 |
| Caso mas reciente | 5105397-1 |
| Estado | Pendiente de Informacion |
| Fecha apertura | 06 Abril, 2026 09:31 AM |
| UUID expediente | e127710d-62c7-4d7a-a311-b1258098a595 |
| Imagenes encontradas | 31 |
| Bucket S3 | inspeccionespty / carpeta 5105397 |

---

## Pendiente

- Validar comportamiento cuando la placa no tiene expedientes activos.
- Validar `save_storage_state` → SSM una vez aprovisionado.
