# Plan — Migración a interfaz web (Chrome)

**Versión:** 1.0
**Fecha:** 2026-03-23
**Contexto:** Reemplaza las Fases 2 y 3 del `plan.md` (tkinter) por una interfaz que corre en el browser. El `core/` no cambia.

---

## Arquitectura

```
[Chrome]  ←HTTP→  [FastAPI  — server.py]  ←import→  [core/]
```

- **FastAPI** levanta un servidor local (`localhost:8000`)
- El usuario abre Chrome apuntando a esa URL
- El `core/` existente es llamado directamente por FastAPI — sin cambios
- El PDF se renderiza en el browser usando **pdf.js** (Mozilla), eliminando la dependencia de `pdf2image` y `poppler` para la interfaz

---

## Lo que se construye

| Archivo | Responsabilidad |
|---|---|
| `server.py` | Servidor FastAPI: rutas, lógica de sesión, llamadas al core |
| `static/index.html` | Shell HTML de la app |
| `static/app.js` | Lógica del wizard, comunicación con el servidor |
| `static/canvas.js` | Canvas interactivo: renderizar PDF, marcar columnas |
| `static/style.css` | Estilos |

---

## Lo que NO cambia

- Todo el `core/` (calibración, OCR, PDF reader, column parser, excel writer)
- Los archivos JSON en `calibraciones/`
- `pdf_to_excel.py` como CLI de respaldo

---

## Fases

### Fase W1 — Servidor base

Levantar FastAPI con:

- `GET /` → sirve `index.html`
- `GET /calibraciones` → lista perfiles JSON existentes
- `DELETE /calibraciones/{nombre}` → elimina un perfil
- `POST /upload-pdf` → recibe el PDF, lo guarda en sesión temporal, devuelve metadata (nombre, número de páginas)

Al terminar: `python3 server.py` levanta el servidor y Chrome muestra la lista de perfiles.

---

### Fase W2 — Renderizado de PDF en el canvas

- En el frontend: `pdf.js` de Mozilla dibuja la imagen del PDF en un `<canvas>` HTML directamente en el navegador. (Decisión: renderizado del lado del cliente).
- El servidor solo devuelve el archivo binario del PDF.
- Navegación entre páginas (1 y 2) con botones y control de zoom fluido interactivo sin latencia.
- Esto elimina el cuello de botella de renderizar en el backend y enviar base64, mejorando el rendimiento y reduciendo el consumo de memoria del servidor.

Al terminar: el usuario puede ver el PDF en Chrome instantáneamente, navegar páginas y hacer zoom muy veloz.

---

### Fase W3 — Marcado interactivo de columnas y filas (límites Y)

- Soporte para dos modos de dibujado:
  - **Columnas (X):** Click izquierdo dibuja líneas verticales (almacenadas como % del ancho). Se dibujan zonas coloreadas como cabeceras.
  - **Filas útiles (Y):** Click izquierdo dibuja hasta 2 líneas horizontales (Top y Bottom, almacenadas como % del alto) para restringir el área válida de escaneo y descartar encabezados basura.
- Click derecho (o click sobre línea existente) → elimina la línea.
- Contador de líneas marcadas vs. requeridas (en modo Columnas).

Al terminar: el usuario puede marcar los límites de columnas y filas sobre el PDF, manteniendo la funcionalidad recientemente añadida a Tkinter.

---

### Fase W4 — Wizard completo (State Management en el Cliente)

Implementar los mismos pasos que `calibrator.py`, ahora como pantallas o componentes web manejados en JS. El frontend funcionará como "cerebro" acumulando el JSON de calibración en memoria hasta el final:

1. **Home** — lista de perfiles obtenida vía API, botones Nueva / Editar / Eliminar.
2. **Setup** — formulario: banco, tipo, período, PDF, lista de columnas.
3. **Detect** — `POST /detect-pdf-type` → llama `detect_pdf_type()` del core.
4. **Mark odd** — canvas con marcado (X e Y), página impar (W2 + W3).
5. **Parity choice** — ¿mismo layout en pares?
6. **Mark even** — canvas con marcado (X e Y), página par (si aplica).
7. **Preview** — `POST /preview-ocr` → envía un payload con los rangos seleccionados vía JSON; ejecuta el OCR en páginas 1, 2 y 3 devolviendo JSON filtrado → tabla HTML mostrando las transacciones limpias de varias páginas.
8. **Review & Save** — `POST /save-calibration` → envía el JSON completo acumulado durante las etapas; llama `CalibrationIO.save()`.

Al terminar: el wizard se siente como una Single Page Application (SPA) y genera el mismo JSON.

---

### Fase W5 — Pantalla principal de conversión

Reemplaza la GUI principal de tkinter (`main.py`) como página adicional:

- Selector de PDF (file input)
- Selector de perfil de calibración (dropdown con perfiles disponibles)
- Botón "Convertir" → `POST /convert` → corre el pipeline completo, devuelve el Excel
- Barra de progreso (via polling o SSE)
- Botón "Descargar Excel" al terminar

Al terminar: Sole puede convertir un extracto sin tocar la terminal.

---

### Fase W6 — Calidad y pulido

- Manejo de errores con mensajes claros en cada paso
- Estados de carga (spinners) durante operaciones lentas (OCR, conversión)
- Confirmaciones antes de eliminar o sobreescribir
- Layout responsive mínimo (que no se rompa al cambiar el tamaño de la ventana)

---

## Orden de ejecución

```
W1 → W2 → W3 → W4 → W5 → W6
```

Cada fase produce algo usable y testeable antes de pasar a la siguiente.

---

## Dependencias nuevas

```bash
pip install fastapi uvicorn python-multipart
```

- `fastapi` + `uvicorn`: servidor web
- `python-multipart`: necesario para recibir archivos (upload de PDF)

Las demás dependencias ya están instaladas.

---

## Relación con el plan.md existente

| plan.md | plan-web-ui.md |
|---|---|
| Fase 1 (core) | Sin cambios — prerequisito |
| Fase 2 (calibrator tkinter) | Reemplazado por W1–W4 |
| Fase 3 (GUI principal tkinter) | Reemplazado por W5 |
| Fase 4 (limpieza) | Se mantiene, se agrega la eliminación de `calibrator.py` y `main.py` tkinter |

---

## Criterio global de éxito

1. `python3 server.py` → Chrome abre la app en `localhost:8000`
2. Se puede crear una calibración completa sin la terminal
3. Se puede convertir un PDF a Excel sin la terminal
4. El JSON generado es compatible con `pdf_to_excel.py --profile` (retrocompatibilidad)
5. No hay dependencia de tkinter en el flujo principal
