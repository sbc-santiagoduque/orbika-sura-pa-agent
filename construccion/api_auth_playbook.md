# API Auth Playbook — Orbika & SIC

Guia para reproducir manualmente los flujos de autenticacion y consulta de ambas APIs.
Util para depuracion, validacion de credenciales y entender como funciona cada sistema.

---

## 1. Orbika (Liferay JSONWS)

**Base URL:** `https://orbika.subocol.com`

Orbika corre sobre Liferay Portal. El login NO es un endpoint REST clasico — es un
portlet de formulario. Hay que extraer IDs dinamicos del HTML antes de enviar
credenciales.

### Hallazgos clave

- El portlet instance ID y el `p_auth` **cambian en cada sesion** — no se pueden
  hardcodear, siempre hay que extraerlos del HTML de la pagina de login.
- Sin la llamada a `consultar-ultima-sesion` (Paso 3), todas las consultas dan 403.
  Orbika requiere que el rol y la organizacion esten activos en la sesion.
- El token de sesion util es el `p_auth` post-login (Liferay.authToken), no el pre-login.
  Ambos lucen iguales (8 caracteres alfanumericos) pero son distintos.
- Las cookies relevantes son `ID` (sesion de usuario) y `JSESSIONID`. Sin `ID` → 403.

### Paso 1 — Obtener portlet instance ID y p_auth pre-login

```http
GET https://orbika.subocol.com/web/guest/login
```

Del HTML de respuesta extraer dos valores con regex:

```
Portlet ID:  com_subocol_orbika_login_SubocolLoginPortlet_INSTANCE_(\w+)
p_auth:      p_auth=([A-Za-z0-9_-]{8})
```

Guardar:
- `PORTLET_INSTANCE` = la parte variable (ej. `AlinRqd5PNtv`)
- `PREFIX` = `_com_subocol_orbika_login_SubocolLoginPortlet_INSTANCE_{PORTLET_INSTANCE}_`
- `PRE_P_AUTH` = token de 8 chars

### Paso 2 — POST credenciales (multipart/form-data)

```http
POST https://orbika.subocol.com/web/guest/login
  ?p_p_id=com_subocol_orbika_login_SubocolLoginPortlet_INSTANCE_{PORTLET_INSTANCE}
  &p_p_lifecycle=1
  &p_p_state=normal
  &p_p_mode=view
  &_{PREFIX}javax.portlet.action=%2Flogin
  &_{PREFIX}mvcRenderCommandName=%2Flogin
  &p_auth={PRE_P_AUTH}

Headers:
  X-Requested-With: XMLHttpRequest
  X-PJAX: true
  Origin: https://orbika.subocol.com
  Referer: https://orbika.subocol.com/web/guest/login

Body (multipart/form-data):
  {PREFIX}username = tu_usuario
  {PREFIX}password = tu_contrasena
  {PREFIX}terminos = on
```

Del HTML de respuesta extraer el `authToken` autenticado:

```
Liferay.authToken\s*=\s*["']([^"']+)["']
```

Si no aparece, buscar con el mismo regex de p_auth (ambos tienen 8 chars):
```
p_auth=([A-Za-z0-9_-]{8})
```

Guardar: `P_AUTH` = token autenticado (distinto al PRE_P_AUTH)

### Paso 3 — Restaurar contexto de rol (obligatorio)

Sin este paso todas las consultas dan 403.

```http
POST https://orbika.subocol.com/api/jsonws/invoke

Headers:
  X-Requested-With: XMLHttpRequest
  Cookie: ID={cookie_ID}; JSESSIONID={cookie_JSESSIONID}

Body (application/x-www-form-urlencoded):
  cmd={"\/permisos.sesionaudit\/consultar-ultima-sesion":{}}
  p_auth={P_AUTH}
```

Respuesta esperada:
```json
{
  "rolName": "Analista Aseguradora",
  "organizationName": "Sura Panama",
  ...
}
```

### Paso 4 — Consultar avisos por placa

```http
POST https://orbika.subocol.com/api/jsonws/invoke

Headers:
  X-Requested-With: XMLHttpRequest
  Cookie: ID={cookie_ID}; JSESSIONID={cookie_JSESSIONID}

Body (application/x-www-form-urlencoded):
  p_auth={P_AUTH}
  cmd={
    "/adminAvisos.aviso/Listar-avisos-talleres": {
      "aseguradora": "Sura Panama",
      "cobertura": [],
      "regional": [],
      "estado": [],
      "taller": [],
      "tipofecha": null,
      "fechaini": null,
      "tipoVehiculo": [],
      "buscador": "placa",
      "valorBuscado": "422644",
      "imprevistos": false
    }
  }
```

Respuesta exitosa: array de avisos `[{nro_aviso, estado, cobertura, ...}, ...]`
Respuesta de error: `{"exception": "mensaje de error"}`

### Reproduccion rapida con curl

```bash
# Paso 1 — extraer IDs dinamicos
PORTLET=$(curl -c cookies.txt -s "https://orbika.subocol.com/web/guest/login" | \
  grep -oP 'INSTANCE_\K\w+' | head -1)
PRE_AUTH=$(curl -c cookies.txt -s "https://orbika.subocol.com/web/guest/login" | \
  grep -oP 'p_auth=\K[A-Za-z0-9_-]{8}' | head -1)
PREFIX="_com_subocol_orbika_login_SubocolLoginPortlet_INSTANCE_${PORTLET}_"
echo "PORTLET=$PORTLET  PRE_AUTH=$PRE_AUTH"

# Paso 2 — login (reemplazar TU_USER y TU_PASS)
HTML_LOGIN=$(curl -c cookies.txt -b cookies.txt \
  -H "X-Requested-With: XMLHttpRequest" -H "X-PJAX: true" \
  -F "${PREFIX}username=TU_USER" \
  -F "${PREFIX}password=TU_PASS" \
  -F "${PREFIX}terminos=on" \
  "https://orbika.subocol.com/web/guest/login?p_p_id=com_subocol_orbika_login_SubocolLoginPortlet_INSTANCE_${PORTLET}&p_p_lifecycle=1&p_p_state=normal&p_p_mode=view&${PREFIX}javax.portlet.action=%2Flogin&p_auth=${PRE_AUTH}")
P_AUTH=$(echo "$HTML_LOGIN" | grep -oP "p_auth=\K[A-Za-z0-9_-]{8}" | head -1)
echo "P_AUTH=$P_AUTH"

# Paso 3 — restaurar rol
curl -c cookies.txt -b cookies.txt \
  -H "X-Requested-With: XMLHttpRequest" \
  -d "cmd=%7B%22%2Fpermisos.sesionaudit%2Fconsultar-ultima-sesion%22%3A%7B%7D%7D&p_auth=${P_AUTH}" \
  "https://orbika.subocol.com/api/jsonws/invoke"

# Paso 4 — consultar avisos por placa
curl -b cookies.txt \
  -H "X-Requested-With: XMLHttpRequest" \
  --data-urlencode 'cmd={"/adminAvisos.aviso/Listar-avisos-talleres":{"aseguradora":"Sura Panama","cobertura":[],"regional":[],"estado":[],"taller":[],"tipofecha":null,"fechaini":null,"tipoVehiculo":[],"buscador":"placa","valorBuscado":"422644","imprevistos":false}}' \
  -d "p_auth=${P_AUTH}" \
  "https://orbika.subocol.com/api/jsonws/invoke"
```

---

## 2. SIC REST API (ConnectAssistance)

**Base URL:** `https://api-bkp.claims-sic.apps-connectassistance.com`
**Web app:** `https://sic.connectasistencia.com` (CloudFront + React SPA)

El flujo real tiene **4 requests** y requiere una API key fija que el app tiene
hardcodeada en su bundle JS. Fue descubierta inspeccionando el bundle.

### Hallazgos clave (descubiertos 2026-04-07)

- **La URL tiene `bkp` (backup), no `bkd`** — typo comun. El dominio
  `api-bkd.claims-sic.apps-connectassistance.com` no existe en DNS.
- **Todos los requests requieren la API key** como header `Authorization`.
  Sin ella → 401 inmediato, incluso en el endpoint de auth.
  ```
  Authorization: key_c5b4ad82c99e7abf75055d4095ba74c49632bf209b75f844fb2609d1e5900c17
  ```
  Esta key esta hardcodeada en el bundle JS del app (`index-*.js`). Si rota,
  re-extraer con: `grep -oE 'API_KEY="[^"]*"' <bundle.js>`

- **El auth requiere `mfaCode` y `challengeSession` en el body** (aunque sean null).
  Sin ellos el servidor puede retornar errores de validacion.

- **La respuesta de auth esta envuelta** en `{data: {...}, error: null, success: true}`.
  El token util es `data.accessToken` (Cognito), no `data.idToken`.
  El `idToken` es para decodificar el perfil; el `accessToken` es para Bearer.

- **El `userId` del search es un entero (`userCompanyID`)**, no el UUID de Cognito.
  El UUID (`sub`) viene del auth, pero hay que hacer una segunda llamada
  `GET /api/v1/users/{sub}` para obtener el `userCompanyID` numerico.

- **El search requiere `countryCode=PAN` y `page=1`** ademas de los parametros
  ya conocidos. Sin `countryCode` → 400.

- **Post-auth, el header cambia a `Bearer {accessToken}` + `X-User-Type: sic-user`**.
  La llamada de usuario (`/api/v1/users/{sub}`) sigue usando la API key, no Bearer.

- **La respuesta del search esta anidada**:
  `body.data.response.events` — no en el nivel raiz ni en `body.data` directamente.

### Paso 1 — Autenticar

```http
POST https://api-bkp.claims-sic.apps-connectassistance.com/api/v1/users/auth
Authorization: key_c5b4ad82c99e7abf75055d4095ba74c49632bf209b75f844fb2609d1e5900c17
Accept: application/json
Content-Type: application/json

{
  "username": "centroauto@sura.com.pa",
  "password": "TU_PASSWORD",
  "mfaCode": null,
  "challengeSession": null
}
```

Respuesta:
```json
{
  "data": {
    "idToken":      "eyJ...",
    "sub":          "22038386-8ff0-4798-8844-17265f326269",
    "accessToken":  "eyJ...",
    "refreshToken": "eyJ...",
    "isAuthenticated": true,
    "isMFARequired":   false,
    "challengeSession": null
  },
  "error": null,
  "success": true
}
```

Guardar: `ACCESS_TOKEN = data.accessToken`, `SUB = data.sub`

### Paso 2 — Obtener userCompanyID (userId numerico)

```http
GET https://api-bkp.claims-sic.apps-connectassistance.com/api/v1/users/{SUB}
Authorization: key_c5b4ad82c99e7abf75055d4095ba74c49632bf209b75f844fb2609d1e5900c17
Accept: application/json
```

Respuesta relevante:
```json
{
  "data": {
    "userCompanyID": 1713,
    "codPais":       "PAN",
    "rolId":         3,
    "companyId":     15,
    "userName":      "centroauto@sura.com.pa"
  }
}
```

Guardar: `USER_ID = data.userCompanyID` (entero), `COUNTRY = data.codPais`

### Paso 3 — Buscar eventos por placa

```http
GET https://api-bkp.claims-sic.apps-connectassistance.com/api/v2/events/search
  ?filterType=INSURED_PLATE
  &filterText=422644
  &countryCode=PAN
  &companyId=15
  &rolId=3
  &page=1
  &userId=1713

Authorization: Bearer {ACCESS_TOKEN}
X-User-Type: sic-user
Accept: application/json
```

Respuesta — la lista de eventos esta en `data.response.events`:
```json
{
  "data": {
    "response": {
      "indicators": [...],
      "events": [
        {
          "eventRecord":  "5105712",
          "eventDate":    "2026-04-06T15:07:45.347Z",
          "plate":        "422644",
          "companyName":  "SURA",
          "countryCode":  "PAN"
        },
        ...
      ],
      "pagination": {"page": 1, "totalPages": 1, "totalRecords": 4}
    }
  }
}
```

Tomar el evento con `eventDate` mas reciente. Guardar: `EVENT_RECORD`

### Paso 4 — Obtener imagenes del evento

```http
GET https://api-bkp.claims-sic.apps-connectassistance.com/api/v1/images/PAN/all/{EVENT_RECORD}
  ?forceUpdate=true

Authorization: Bearer {ACCESS_TOKEN}
X-User-Type: sic-user
Accept: application/json
```

Respuesta:
```json
{
  "data": [
    {
      "imageName":     "3_1775489295790.jpg",
      "imageUrl":      "https://inspeccionespty.s3.us-east-2.amazonaws.com/5105712/3_1775489295790.jpg?X-Amz-Expires=...",
      "imageSectionId": 3
    },
    ...
  ]
}
```

Las `imageUrl` son presigned S3 con expiracion. Usar directamente para descargar
o pasar a Bedrock Vision.

### Reproduccion rapida con curl

```bash
API_KEY="key_c5b4ad82c99e7abf75055d4095ba74c49632bf209b75f844fb2609d1e5900c17"

# Paso 1 — auth
AUTH=$(curl -s \
  -H "Authorization: $API_KEY" \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{"username":"centroauto@sura.com.pa","password":"TU_PASS","mfaCode":null,"challengeSession":null}' \
  "https://api-bkp.claims-sic.apps-connectassistance.com/api/v1/users/auth")
ACCESS_TOKEN=$(echo $AUTH | python -c "import sys,json; print(json.load(sys.stdin)['data']['accessToken'])")
SUB=$(echo $AUTH | python -c "import sys,json; print(json.load(sys.stdin)['data']['sub'])")
echo "SUB=$SUB"

# Paso 2 — userCompanyID
USER_DATA=$(curl -s \
  -H "Authorization: $API_KEY" \
  -H "Accept: application/json" \
  "https://api-bkp.claims-sic.apps-connectassistance.com/api/v1/users/$SUB")
USER_ID=$(echo $USER_DATA | python -c "import sys,json; print(json.load(sys.stdin)['data']['userCompanyID'])")
COUNTRY=$(echo $USER_DATA | python -c "import sys,json; print(json.load(sys.stdin)['data']['codPais'])")
echo "USER_ID=$USER_ID  COUNTRY=$COUNTRY"

# Paso 3 — buscar por placa (reemplazar 422644)
curl -s \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "X-User-Type: sic-user" \
  -H "Accept: application/json" \
  "https://api-bkp.claims-sic.apps-connectassistance.com/api/v2/events/search?filterType=INSURED_PLATE&filterText=422644&countryCode=$COUNTRY&companyId=15&rolId=3&page=1&userId=$USER_ID" \
  | python -c "import sys,json; evs=json.load(sys.stdin)['data']['response']['events']; [print(e['eventRecord'], e['eventDate']) for e in evs]"

# Paso 4 — imagenes (reemplazar EVENT_RECORD)
curl -s \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "X-User-Type: sic-user" \
  -H "Accept: application/json" \
  "https://api-bkp.claims-sic.apps-connectassistance.com/api/v1/images/PAN/all/5105712?forceUpdate=true" \
  | python -c "import sys,json; imgs=json.load(sys.stdin)['data']; print(len(imgs),'imagenes'); [print(i['imageName'], i['imageSectionId']) for i in imgs[:5]]"
```

---

## Diferencias clave entre ambas APIs

| Aspecto | Orbika | SIC |
|---------|--------|-----|
| Arquitectura | Liferay Portal (portlet form) | REST moderno + AWS Cognito |
| IDs dinamicos | Si — portlet + p_auth cambian por sesion | No — endpoints fijos |
| Auth header | Cookies (`ID` + `JSESSIONID`) | API key fija + Bearer post-auth |
| Contexto extra | `consultar-ultima-sesion` (obligatorio) | `GET /users/{sub}` para userId numerico |
| Token de sesion | p_auth (8 chars, stateful) | accessToken JWT (Cognito, stateless) |
| userId en queries | No aplica | `userCompanyID` entero (no el UUID de Cognito) |
| Formato de body | `application/x-www-form-urlencoded` con `cmd` JSON | `application/json` |
| Respuesta envuelta | No — array directo | Si — `{data: {...}, error, success}` |
| Parametros fijos Sura PA | `aseguradora=Sura Panama` | `companyId=15`, `rolId=3`, `countryCode=PAN` |
| Lista de resultados | Raiz de la respuesta | `data.response.events` (anidado 3 niveles) |
