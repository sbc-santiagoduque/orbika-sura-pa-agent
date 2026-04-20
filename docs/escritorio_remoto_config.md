# Configuración del Escritorio Remoto — 172.16.1.77

Captura de referencia: `escritorio_remoto_config.png` (2026-04-20)

## Apps instaladas

| Ícono | App | Relevancia para RPA |
|---|---|---|
| SERVER PREMIUM | **Sistema Premium** ← target principal | ⭐ App a automatizar |
| FortiClient VPN | VPN client | Puede requerirse para conectar |
| UiPath Studio | UiPath Studio | Instalado (no en uso por restricción de licencia) |
| UiPath Assistant | UiPath Assistant | Instalado |
| UiPath Communi... | UiPath Community | Instalado |
| AnyDesk | Escritorio remoto alternativo | Acceso remoto backup |
| DBeaver | Cliente de BD | Herramienta de desarrollo |
| Google Chrome | Chrome | Browser disponible |
| Microsoft Edge | Edge | Browser disponible |
| Firefox | Firefox | Browser disponible |
| Greenshot | Capturas de pantalla | Herramienta de captura |
| ScreenRec | Grabación de pantalla | Herramienta de grabación |
| Postman | Postman | Herramienta API |
| WinRAR | Compresor | Utilidad |
| Revo Uninstaller | Desinstalador | Utilidad |
| Zoom Workplace | Zoom | Comunicación |
| n8n | n8n (carpeta) | Workflow automation |
| agente (carpeta) | Carpeta agente | Proyecto |
| agente-analist... | Carpeta agente analista | Proyecto |
| RPA-BILLING | Carpeta RPA Billing | Otro proyecto RPA |

## Acceso directo de Premium

El ícono **SERVER PREMIUM** en el escritorio abre directamente el sistema.
Doble click → abre la aplicación de escritorio de Premium.

## Acceso RDP

- **Host:** 172.16.1.77
- **Usuario:** `.\PROYECTO_DMS`
- **Credenciales:** ver `.env` (no commitear)

## Notas

- El escritorio tiene fondo de pantalla oceánico azul — útil como referencia
  visual para confirmar que la sesión RDP conectó correctamente
- UiPath está instalado pero **no se usa** en este proyecto (restricción de licencia)
- El acceso fue configurado el 2026-04-20
