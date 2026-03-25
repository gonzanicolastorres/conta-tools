# Plan — Migración a interfaz web

**Versión:** 2.0
**Fecha original:** 2026-03-23
**Actualizado:** 2026-03-24
**Estado:** COMPLETADO — todas las fases implementadas

---

## Arquitectura implementada

```
[Browser]  ←HTTP/SSE→  [FastAPI — server.py]  ←import→  [core/]
```

- **FastAPI** corre en `localhost:8000`
- El PDF se renderiza en el browser con **pdf.js** (sin backend)
- El `core/` es llamado directamente por FastAPI — sin cambios al pipeline
- Progreso en tiempo real via **Server-Sent Events (SSE)**

---

## Archivos construidos

| Archivo | Responsabilidad |
|---|---|
| `server.py` | Backend FastAPI: endpoints, SSE, llamadas al core |
| `static/index.html` | SPA: landing, wizard de calibración, pantalla de conversión |
| `static/canvas.js` | `CalibrationCanvas` — renderiza PDF, marcado interactivo de columnas |

---

## Lo que NO cambió

- Todo el `core/` (calibración, OCR, PDF reader, column parser, excel writer)
- Los archivos JSON en `calibraciones/`
- `pdf_to_excel.py` como CLI de respaldo

---

## Fases

### Fase W1 — Servidor base ✅ COMPLETADO

FastAPI con:
- `GET /` → sirve `index.html`
- `GET /calibraciones` → lista perfiles JSON
- `DELETE /calibraciones/{nombre}` → elimina un perfil
- `GET /api/calibraciones/{nombre}` → lee un perfil JSON
- `POST /upload-pdf` → guarda PDF en temp con nombre UUID, detecta tipo (text/scanned)

---

### Fase W2 — Renderizado de PDF en el canvas ✅ COMPLETADO

- **pdf.js** renderiza el PDF directamente en el browser.
- Navegación entre páginas con botones ◀ ▶.
- Zoom fluido sin latencia (todo del lado del cliente).
- El servidor solo sirve el PDF como archivo estático desde `/temp/`.

---

### Fase W3 — Marcado interactivo de columnas y límites ✅ COMPLETADO

- **Modo columnas (X):** click izquierdo agrega líneas verticales (como % del ancho); click derecho elimina.
- **Modo límites horizontales (Y):** marca área útil (top/bottom) para excluir encabezados y pies.
- Contador en tiempo real: verde cuando se alcanza el número requerido de líneas.
- Evento custom `linesChanged` para sincronizar el contador con el HTML.

---

### Fase W4 — Wizard completo ✅ COMPLETADO

Pasos implementados en `static/index.html`:

1. **Landing** — pantalla de inicio con tarjetas "Calibrador" y "Convertir a Excel".
2. **Home** — lista de perfiles con botones Editar / Eliminar / Nueva calibración.
3. **Setup** — banco, tipo, período (validado como YYYY-MM), columnas editables.
4. **Mark odd** — canvas con marcado de columnas e Y-bounds, página impar.
5. **Parity choice** — ¿mismo layout en páginas pares?
6. **Mark even** — canvas para página par (si aplica).
7. **Preview** — `POST /preview-ocr` → tabla de transacciones detectadas.
8. **Review & Save** — `POST /save-calibration` → JSON guardado en `calibraciones/`.

---

### Fase W5 — Pantalla de conversión ✅ COMPLETADO

- Input de empresa (aparece en encabezado del Excel).
- Dropdown de perfiles de calibración.
- Upload de uno o varios PDFs.
- Si el PDF tiene texto: pregunta si usar extracción directa o OCR.
- Botón "Convertir" → SSE con progreso página a página.
- Botón de descarga por cada Excel generado.

---

### Fase W6 — Calidad y pulido ✅ COMPLETADO

- Mensajes de error claros en cada paso del wizard y en la conversión.
- Spinners durante OCR y conversión.
- Confirmación antes de eliminar perfiles o sobreescribir calibraciones existentes.
- Layout funcional y consistente.

---

## Criterio global de éxito — Verificación final

1. ✅ `uvicorn server:app --reload` → Chrome muestra la app en `localhost:8000`.
2. ✅ Se puede crear una calibración completa sin la terminal.
3. ✅ Se puede convertir un PDF a Excel sin la terminal.
4. ✅ El JSON generado es compatible con `pdf_to_excel.py --profile`.
5. ✅ No hay dependencia de tkinter en el flujo principal (movido a `legacy/`).
