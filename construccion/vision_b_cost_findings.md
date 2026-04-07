# Vision B — Hallazgos de Costo y Clasificacion

Prueba experimental con Bedrock Vision (Opcion B) — 2026-04-06.
Placa de prueba: CU7559 / 422644

---

## Configuracion de la prueba

| Parametro | Valor |
|-----------|-------|
| Modelo | `amazon.nova-lite-v1:0` |
| Imagenes analizadas | ~16 de 31 |
| Placa | CU7559 |
| Expediente | 5105397-1 |

---

## Tokens consumidos (experimental)

| Metrica | Valor |
|---------|-------|
| Input tokens | 37,951 |
| Output tokens | 490 |
| Total | 38,441 |
| Promedio por imagen | ~2,402 tokens |

---

## Costo estimado

### Por imagen
```
Input:  ~2,350 tokens * $0.00006/1K = $0.000141
Output: ~52    tokens * $0.00024/1K = $0.000012
Total por imagen:                   ≈ $0.000153
```

### Por expediente (31 imagenes)
```
31 * $0.000153 ≈ $0.0047 por caso
```

### Mensual (1,648 casos/mes — volumen piloto)
```
1,648 * $0.0047 ≈ $7.75/mes
```

---

## Comparativa de modelos

| Modelo | $/1K input | $/1K output | Costo/mes est. |
|--------|-----------|-------------|----------------|
| amazon.nova-lite-v1:0 | $0.00006 | $0.00024 | ~$8/mes |
| anthropic.claude-3-haiku-20240307-v1:0 | $0.00025 | $0.00125 | ~$33/mes |
| anthropic.claude-sonnet-4-20250514-v1:0 | $0.003 | $0.015 | ~$390/mes |

**Decision:** Nova Lite es suficiente para clasificacion de documentos a ~$8/mes.
El costo dominante del sistema sera el agente Bedrock (invocaciones), no la vision.

---

## Calidad de clasificacion (muestra)

Documentos obligatorios detectados sobre la muestra analizada:

| Documento | Resultado |
|-----------|-----------|
| fud (Formato Unico de Denuncia) | OK — modelo identifica leyendo encabezado del formulario |
| foto_danio | OK |
| ruv (Registro Unico Vehicular) | OK |
| resolucion | NO detectado en muestra (puede no estar en las primeras imagenes) |

**Nota:** La clasificacion funciona via OCR integrado del modelo — lee el texto del
documento (encabezado "FORMATO UNICO DE DENUNCIA", "REGISTRO UNICO VEHICULAR", etc.)
sin necesidad de RAG ni templates de referencia.

---

## Hallazgo de navegacion

El expediente SIC abre en el **paso actual del flujo** (no siempre en Inspeccion).
Para acceder a las imagenes hay que hacer click en el tab "Inspeccion" explicitamente.

Selector del tab:
```
button[role='tab']:has-text('Inspeccion')
```

---

## Pendiente

- Validar clasificacion de resolucion (correr con --n 31 para analizar todas las imagenes)
- Implementar `OpcionBValidator.validar()` en `validate_documentos` cuando se requiera
- Activar con: `VALIDATE_DOCS_STRATEGY=B` + `BEDROCK_MODEL_ID=amazon.nova-lite-v1:0`
