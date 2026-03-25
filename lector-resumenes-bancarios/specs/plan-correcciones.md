# Plan de Correcciones — Conta Tools / Lector de Extractos

**Fecha original:** 2026-03-23
**Actualizado:** 2026-03-24
**Estado:** COMPLETADO — todos los fixes implementados

---

## Contexto del proyecto

App web (FastAPI + HTML/JS) que convierte extractos bancarios PDF escaneados a Excel mediante OCR (Tesseract). Flujo principal:

1. Usuario calibra columnas sobre un PDF de muestra (wizard en `static/index.html` + `static/canvas.js`)
2. El perfil de calibración se guarda como JSON en `calibraciones/`
3. Usuario sube PDFs reales → el backend aplica el perfil → genera un Excel por archivo

**Stack:**
- Backend: `server.py` (FastAPI, uvicorn)
- Frontend: `static/index.html` (SPA sin framework), `static/canvas.js` (clase CalibrationCanvas)
- Core: `core/` (OCR, parseo, Excel writer, calibración)
- Librería de conversión: `pdf_to_excel.py` → función `convert()`

**Cómo correr:** `uvicorn server:app --reload`

---

## Prioridad 1 — Bugs críticos ✅ TODOS IMPLEMENTADOS

### 1.1 `/convert` devuelve HTTP 200 en caso de error ✅

**Archivo:** `server.py` líneas 123–131
**Problema:** Cuando `convert()` lanza `ConversionError`, el endpoint lo captura y devuelve `{"error": "...", "excel_url": ""}` con status 200. El frontend JS verifica `res.ok && json.excel_url` y como `res.ok` es `true` (status 200), no detecta el error correctamente.

**Fix:**
```python
# En el endpoint /convert, reemplazar:
except ConversionError as ce:
    return {"error": str(ce), "excel_url": ""}

# Por:
except ConversionError as ce:
    raise HTTPException(status_code=422, detail=str(ce))
```

El frontend ya maneja el caso `!res.ok` mostrando `json.detail` como error.

---

### 1.2 `/convert` no acepta el campo `empresa` ✅

**Archivos:** `server.py` línea 103, `pdf_to_excel.py` función `convert()`
**Problema:** El frontend envía `formData.append("empresa", empresa)` pero el endpoint no lo recibe. La función `convert()` ya acepta `empresa=` como kwarg opcional, pero el endpoint no lo pasa.

**Fix en `server.py`:**
```python
@app.post("/convert")
async def convert_pdf(
    file: UploadFile = File(...),
    profile_name: str = Form(...),
    empresa: str = Form(default=""),   # ← agregar
):
    ...
    result = convert(str(pdf_path), data, str(output_path), empresa=empresa)  # ← pasar
```

---

### 1.3 `result.total_transactions` no existe ✅

**Archivo:** `server.py` línea 128
**Problema:** El código accede a `result.total_transactions` pero `ConversionResult` tiene el campo `transactions` (lista), no `total_transactions`.

**Fix:**
```python
# Reemplazar:
"total_transacciones": result.total_transactions

# Por:
"total_transacciones": len(result.transactions)
```

---

### 1.4 `build_col_ranges` en `/preview-ocr` recibe datos incorrectos ✅

**Archivo:** `server.py` líneas 146–149
**Problema:** `build_col_ranges()` espera `{col: start_pct}` (solo el inicio), pero el payload tiene `{col: [start, end]}`. Se hace `rng[0]` para extraer solo el inicio, lo cual es correcto, pero después se llama `build_col_ranges` que recalcula los extremos basándose en los starts — perdiendo los extremos explícitamente calibrados.

El módulo `pdf_to_excel._profile_to_col_ranges()` ya hace esto correctamente usando `(rng[0], rng[1])` directamente. Usar esa lógica en el preview también.

**Fix en `server.py`:**
```python
# Reemplazar la construcción de col_ranges_odd/even:
col_ranges_odd = {col: (rng[0], rng[1]) for col, rng in payload.paginas_impares.items()}
col_ranges_even = col_ranges_odd
if payload.paginas_pares:
    col_ranges_even = {col: (rng[0], rng[1]) for col, rng in payload.paginas_pares.items()}
```

---

## Prioridad 2 — Funcionalidad incompleta ✅ TODOS IMPLEMENTADOS

### 2.1 Barra de progreso real durante conversión ✅

**Problema:** El endpoint `/convert` es síncrono y bloquea 30-120 segundos. El frontend solo muestra texto estático `"Procesando: archivo.pdf…"` y la barra no avanza hasta que termina el archivo.

**Solución:** Server-Sent Events (SSE). El endpoint `/convert` emite eventos mientras procesa; el frontend los consume con `EventSource`.

**Fix en `server.py`** — reemplazar el endpoint `/convert` por uno que use `StreamingResponse`:

```python
from fastapi.responses import StreamingResponse
import json as json_lib

@app.post("/convert")
async def convert_pdf(
    file: UploadFile = File(...),
    profile_name: str = Form(...),
    empresa: str = Form(default=""),
):
    # Guardar PDF
    pdf_path = TEMP_DIR / "temp_conversion.pdf"
    with open(pdf_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    calib_path = CALIBRATIONS_DIR / profile_name
    if not calib_path.exists():
        raise HTTPException(status_code=404, detail="Perfil no encontrado")

    data = CalibrationIO.load(str(calib_path))
    original_name_base = Path(file.filename).stem
    output_filename = f"{original_name_base}.xlsx"
    output_path = TEMP_DIR / output_filename

    def event_stream():
        events = []

        def on_progress(current, total, msg):
            pct = int(current / total * 100) if total else 0
            payload = json_lib.dumps({"type": "progress", "pct": pct, "msg": msg})
            events.append(f"data: {payload}\n\n")

        try:
            result = convert(
                str(pdf_path), data, str(output_path),
                empresa=empresa,
                on_progress=on_progress,
            )
            # Vaciar eventos acumulados
            while events:
                yield events.pop(0)

            done = json_lib.dumps({
                "type": "done",
                "excel_url": f"/temp/{output_filename}",
                "total": len(result.transactions),
            })
            yield f"data: {done}\n\n"

        except ConversionError as ce:
            while events:
                yield events.pop(0)
            err = json_lib.dumps({"type": "error", "msg": str(ce)})
            yield f"data: {err}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

**Fix en `static/index.html`** — reemplazar el `fetch("/convert")` por una función que use `fetch` con `ReadableStream` para consumir el SSE:

```javascript
async function convertirArchivo(file, profile, empresa) {
    return new Promise(async (resolve) => {
        const formData = new FormData();
        formData.append("file", file);
        formData.append("profile_name", profile);
        formData.append("empresa", empresa);

        const res = await fetch("/convert", { method: "POST", body: formData });
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n\n");
            buffer = lines.pop();
            for (const line of lines) {
                if (!line.startsWith("data: ")) continue;
                const event = JSON.parse(line.slice(6));
                if (event.type === "progress") {
                    // Actualizar progreso del archivo actual
                    actualizarProgreso(event.pct, event.msg);
                } else if (event.type === "done") {
                    resolve({ ok: true, excel_url: event.excel_url });
                } else if (event.type === "error") {
                    resolve({ ok: false, error: event.msg });
                }
            }
        }
    });
}
```

Nota: `on_progress` de `convert()` es síncrono y el endpoint usa un generador, por lo que los eventos se acumulan en una lista y se vacían al terminar. Es un approach pragmático que mantiene el progreso sin complejidad de async/threading. Si se quiere progreso en tiempo real habría que hacer la función async con un queue, pero esto ya mejora significativamente la UX respecto al estado actual.

---

### 2.2 Canvas: navegación entre páginas en el paso de marcado ✅

**Archivo:** `static/index.html` y `static/canvas.js`
**Problema:** El usuario solo ve la página correspondiente a la paridad que está calibrando (impar = pág 1, par = pág 2). No puede navegar a otras páginas para verificar el layout sin cambiar de fase.

**Fix en `static/index.html`** — agregar controles de navegación de página en la toolbar del paso `step-mark`:

```html
<!-- Dentro de .toolbar en step-mark, después de los controles de zoom -->
<div style="border-left: 1px solid #ccc; padding-left: 15px; display:flex; gap:8px; align-items:center;">
    <button class="btn-secondary" id="btn-prev-page" style="padding:4px 10px;">◀</button>
    <span id="page-indicator" style="font-weight:bold; min-width:80px; text-align:center;">Pág 1 / ?</span>
    <button class="btn-secondary" id="btn-next-page" style="padding:4px 10px;">▶</button>
</div>
```

**Fix en `static/index.html`** — agregar listeners en la inicialización del canvas (dentro del bloque `if(!calCanvas)`):

```javascript
document.getElementById('btn-prev-page').addEventListener('click', () => {
    if (calCanvas.pageNum > 1) {
        calCanvas.setPage(calCanvas.pageNum - 1);
        updatePageIndicator();
    }
});
document.getElementById('btn-next-page').addEventListener('click', () => {
    if (calCanvas.pdfDoc && calCanvas.pageNum < calCanvas.pdfDoc.numPages) {
        calCanvas.setPage(calCanvas.pageNum + 1);
        updatePageIndicator();
    }
});

function updatePageIndicator() {
    const total = calCanvas.pdfDoc ? calCanvas.pdfDoc.numPages : '?';
    document.getElementById('page-indicator').innerText = `Pág ${calCanvas.pageNum} / ${total}`;
}
```

Llamar `updatePageIndicator()` también después de `calCanvas.setPage(1)` y `calCanvas.setPage(2)` en `iniciarMarcado()`.

---

### 2.3 Contador de líneas marcadas en el canvas ✅

**Archivo:** `static/index.html`
**Problema:** El usuario no sabe cuántas líneas necesita marcar para completar la calibración. Solo se entera cuando hace click en "Confirmar" y aparece un `alert`.

**Fix** — agregar un indicador debajo de la toolbar en `step-mark`:

```html
<!-- Debajo de .toolbar -->
<div id="lines-counter" style="padding: 6px 12px; background:#E3F2FD; border-radius:4px; margin-bottom:8px; font-size:0.9em;">
    Líneas verticales: <span id="count-x" style="font-weight:bold;">0</span> / <span id="needed-x">?</span> necesarias
    &nbsp;|&nbsp;
    Límites horizontales: <span id="count-y" style="font-weight:bold;">0</span> / 2 (opcional)
</div>
```

**Fix en `static/canvas.js`** — emitir un evento custom después de cada `redrawOverlay()`:

```javascript
// Al final de redrawOverlay():
this.drawCanvas.dispatchEvent(new CustomEvent('linesChanged', {
    detail: { x: this.linesX.length, y: this.linesY.length },
    bubbles: true
}));
```

**Fix en `static/index.html`** — escuchar el evento:

```javascript
document.getElementById('draw-canvas').addEventListener('linesChanged', (e) => {
    document.getElementById('count-x').innerText = e.detail.x;
    document.getElementById('count-y').innerText = e.detail.y;
    document.getElementById('needed-x').innerText = stateJSON.columnas.length - 1;
    // Resaltar en rojo si faltan líneas, verde si está completo
    const ok = e.detail.x === stateJSON.columnas.length - 1;
    document.getElementById('lines-counter').style.background = ok ? '#E8F5E9' : '#E3F2FD';
});
```

---

### 2.4 Validación del campo período en Setup ✅

**Archivo:** `static/index.html`
**Problema:** El campo `período` acepta cualquier texto. Si no tiene formato `YYYY-MM`, el nombre del archivo JSON generado queda inconsistente y `CalibrationFinder` no puede ordenar perfiles correctamente.

**Fix** — agregar validación en el listener de `btn-comenzar-marcado`:

```javascript
const periodo = document.getElementById('inp-periodo').value.trim();
if (!/^\d{4}-\d{2}$/.test(periodo)) {
    alert("El período debe tener formato YYYY-MM (ej: 2025-06)");
    return;
}
```

---

### 2.5 Limpiar PDF temporal entre conversiones ✅

**Archivo:** `server.py`
**Problema:** El endpoint `/upload-pdf` siempre guarda en `temp/current_workspace.pdf`. Si dos usuarios usan la app simultáneamente (o si el mismo usuario sube un archivo nuevo mientras otro está en preview), el PDF en memoria es el equivocado.

**Fix** — usar el nombre original del archivo como nombre temporal (sanitizado):

```python
@app.post("/upload-pdf")
async def upload_pdf(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="El archivo debe ser un PDF")

    import uuid
    safe_name = f"{uuid.uuid4().hex}.pdf"
    file_path = TEMP_DIR / safe_name

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return {
        "nombre_original": file.filename,
        "bytes_guardados": file_path.stat().st_size,
        "pdf_url": f"/temp/{safe_name}",
        "pdf_filename": safe_name,   # ← el frontend debe guardar este valor en stateJSON
    }
```

**Fix en `static/index.html`** — guardar `pdf_filename` del response en `stateJSON`:

```javascript
stateJSON.pdf_filename = json.pdf_filename;   // en lugar de "current_workspace.pdf"
stateJSON.pdf_url = json.pdf_url;
```

---

## Prioridad 3 — Calidad y robustez ✅ TODOS IMPLEMENTADOS

### 3.1 Agregar warnings en el Excel cuando hay filas con montos vacíos ✅

**Archivo:** `core/excel_writer.py`
**Estado actual:** Las filas sin débito ni crédito ya se colorean en amarillo (`COLOR_EMPTY = "FFFF99"`). ✓
**Pendiente:** Agregar una hoja resumen que liste cuántas filas amarillas hay y en qué páginas, para que la operadora tenga una referencia rápida sin scrollear.

**Fix en `core/excel_writer.py`** — después de generar la hoja `Movimientos`, agregar hoja `Alertas`:

```python
# Detectar filas vacías
filas_vacias = [
    (tx["pagina"], tx.get("fecha", ""), tx.get("concepto", ""))
    for tx in transactions
    if not any(
        isinstance(tx.get(c + "_num"), (int, float))
        for c in columns
        if any(k in c.lower() for k in ("debito", "credito"))
    )
]

if filas_vacias:
    ws_alertas = wb.create_sheet("Alertas")
    ws_alertas["A1"] = "Filas sin monto (revisar manualmente)"
    ws_alertas["A1"].font = Font(bold=True, color="FFFFFF")
    ws_alertas["A1"].fill = PatternFill(start_color="E65100", end_color="E65100", fill_type="solid")
    ws_alertas.merge_cells("A1:C1")
    for i, (pag, fecha, concepto) in enumerate(filas_vacias, 2):
        ws_alertas.cell(row=i, column=1, value=pag)
        ws_alertas.cell(row=i, column=2, value=fecha)
        ws_alertas.cell(row=i, column=3, value=concepto)
    ws_alertas.column_dimensions["B"].width = 10
    ws_alertas.column_dimensions["C"].width = 50
```

---

### 3.2 Validar que el perfil de calibración tiene las columnas correctas antes de convertir ✅

**Archivo:** `server.py` endpoint `/convert`
**Problema:** Si el perfil tiene columnas que no matchean el PDF, el OCR corre igual y genera un Excel vacío o con datos en columnas incorrectas. No hay aviso al usuario.

**Fix** — agregar validación básica antes de llamar a `convert()`:

```python
# Después de cargar el perfil (data = CalibrationIO.load(...)):
if not data.paginas_impares:
    raise HTTPException(status_code=422, detail="El perfil no tiene columnas calibradas para páginas impares.")
if not data.columnas:
    raise HTTPException(status_code=422, detail="El perfil no tiene columnas definidas.")
```

---

### 3.3 Timeout explícito en el servidor para OCR ✅

**Archivo:** `server.py`
**Problema:** Si el PDF tiene muchas páginas (ej: 50+) el OCR puede tardar varios minutos. La conexión HTTP del cliente puede hacer timeout antes de que termine.

**Fix** — documentar en el servidor y agregar un límite de páginas configurable:

```python
MAX_PAGES_PREVIEW = int(os.environ.get("MAX_PAGES_PREVIEW", "3"))
MAX_PAGES_CONVERT = int(os.environ.get("MAX_PAGES_CONVERT", "100"))
```

En `/preview-ocr` usar `MAX_PAGES_PREVIEW` en `last_page=MAX_PAGES_PREVIEW`.

---

### 3.4 Nombre del Excel generado debe coincidir con el nombre del PDF ✅

**Archivo:** `server.py` endpoint `/convert`
**Estado actual:** Genera `extracto_excel_{nombre}.xlsx`. El frontend lo descarga con ese nombre.
**Fix:** Simplificar a `{nombre_original_sin_extension}.xlsx` para que sea fácil de identificar.

```python
original_name_base = Path(file.filename).stem   # ya está así ✓
output_filename = f"{original_name_base}.xlsx"  # cambiar de "extracto_excel_{...}" a esto
```

---

## Prioridad 4 — Pantalla de inicio "Conta Tools" ✅ IMPLEMENTADO

### 4.0 Landing page como punto de entrada de la aplicación ✅

**Archivo:** `static/index.html`
**Problema:** La app arranca directamente en el listado de perfiles de calibración. No hay pantalla de bienvenida, no queda claro qué es la herramienta ni cómo navegarla. El header actual tiene dos botones que cambian de modo, lo cual es confuso.

**Fix** — agregar un nuevo paso `step-landing` que sea el primero en mostrarse (reemplaza al `active-step` inicial que hoy tiene `step-home`).

**HTML a agregar** antes del bloque `step-home`:

```html
<div class="step-container active-step" id="step-landing">
    <div style="text-align:center; padding: 40px 20px;">

        <h1 style="font-size:2.4rem; color:#1565C0; margin-bottom:8px;">Conta Tools</h1>
        <p style="color:#546E7A; font-size:1.1rem; margin-bottom:48px;">
            Herramientas para contadores — Módulo: Lector de Extractos Bancarios
        </p>

        <div style="display:flex; justify-content:center; gap:32px; flex-wrap:wrap;">

            <div onclick="resetToHome()"
                 style="cursor:pointer; width:240px; padding:32px 24px; border-radius:12px;
                        border:2px solid #1565C0; background:#F0F4FF;
                        transition: box-shadow 0.2s;"
                 onmouseover="this.style.boxShadow='0 6px 20px rgba(21,101,192,0.25)'"
                 onmouseout="this.style.boxShadow='none'">
                <div style="font-size:2.5rem; margin-bottom:12px;">⚙️</div>
                <h2 style="margin:0 0 8px; color:#1565C0; font-size:1.2rem;">Calibrador</h2>
                <p style="margin:0; color:#546E7A; font-size:0.9rem;">
                    Configurá las columnas de un nuevo banco o formato de extracto.
                </p>
            </div>

            <div onclick="showStep('convert')"
                 style="cursor:pointer; width:240px; padding:32px 24px; border-radius:12px;
                        border:2px solid #2E7D32; background:#F0FFF4;
                        transition: box-shadow 0.2s;"
                 onmouseover="this.style.boxShadow='0 6px 20px rgba(46,125,50,0.25)'"
                 onmouseout="this.style.boxShadow='none'">
                <div style="font-size:2.5rem; margin-bottom:12px;">📄➡️📊</div>
                <h2 style="margin:0 0 8px; color:#2E7D32; font-size:1.2rem;">Convertir a Excel</h2>
                <p style="margin:0; color:#546E7A; font-size:0.9rem;">
                    Procesá uno o varios extractos PDF y descargá los Excel generados.
                </p>
            </div>

        </div>
    </div>
</div>
```

**Cambios adicionales:**

1. Quitar `active-step` del `div#step-home` (lo tiene actualmente, debe pasarlo a `step-landing`).

2. Simplificar el header — reemplazar los dos botones de modo por uno solo que vuelva al inicio:

```html
<!-- Reemplazar el div con los dos botones en el header por: -->
<button class="btn-secondary" onclick="showStep('landing')"
        style="padding: 5px 14px; font-size:0.9em;">
    🏠 Inicio
</button>
```

3. Agregar `'landing': 'Inicio'` al mapa de títulos en la función `showStep()`.

4. En `resetToHome()`, al final cambiar `showStep('home')` por `showStep('landing')` para que al cancelar una calibración vuelva al landing, no al listado de perfiles.

5. Agregar botón "← Volver al inicio" en la pantalla del conversor (`step-convert`) junto al botón existente "← Volver al Calibrador":

```html
<button class="btn-secondary" onclick="showStep('landing')">🏠 Volver al inicio</button>
```

**Verificación:** Al abrir `localhost:8000` debe aparecer la pantalla "Conta Tools" con las dos tarjetas. Hacer click en "Calibrador" lleva al listado de perfiles. Hacer click en "Convertir a Excel" lleva directo al conversor. El botón "🏠 Inicio" del header siempre vuelve al landing.

---

## Prioridad 5 — Deuda técnica ✅ TODOS IMPLEMENTADOS

### 5.1 Importaciones desordenadas en `server.py` ✅

Las importaciones están mezcladas: `from pydantic import BaseModel` aparece en el medio del archivo (línea 81) en lugar de al principio. Mover todas las importaciones al inicio del archivo.

---

### 5.2 Eliminar código legacy (tkinter) ✅

Los archivos `main.py` y `calibrator.py` son la versión tkinter que fue reemplazada por el frontend web. Pueden archivarse en una carpeta `legacy/` para no confundir a futuros colaboradores.

---

### 5.3 Comentarios desactualizados en `server.py` ✅

- Línea 78: `# W2 usará esto` → actualizar a descripción real
- Línea 104: `"""Punto de entrada final W5...` → actualizar

---

## Resumen de archivos a modificar

| Archivo | Cambios |
|---|---|
| `server.py` | Fix 1.1, 1.2, 1.3, 1.4, 2.1, 2.5, 3.2, 3.3, 3.4, 5.1, 5.3 |
| `static/index.html` | Fix 2.1 (frontend SSE), 2.2, 2.3, 2.4, 4.0 |
| `static/canvas.js` | Fix 2.3 (evento custom) |
| `core/excel_writer.py` | Fix 3.1 |

---

## Orden de ejecución recomendado

```
1.1 → 1.2 → 1.3 → 1.4   (bugs que rompen lo que ya funciona — hacerlos primero)
4.0                        (landing page — visible de inmediato, bajo riesgo)
2.5                        (aislamiento de PDFs — prerequisito de 2.1)
2.1                        (progreso real — mayor impacto en UX)
2.2 → 2.3 → 2.4           (mejoras al calibrador)
3.1 → 3.2 → 3.3 → 3.4    (calidad y robustez)
5.1 → 5.2 → 5.3           (deuda técnica — último)
```

---

## Cómo verificar cada fix

- **1.1–1.4:** Intentar convertir un PDF con un perfil válido y con uno inválido → verificar que los errores aparecen en el frontend con mensaje claro
- **2.1:** Convertir un PDF de 12 páginas → la barra debe avanzar página a página
- **2.2:** En el paso de calibración, navegar entre páginas con ◀ ▶ sin perder las líneas marcadas
- **2.3:** Marcar líneas → el contador debe actualizarse en tiempo real y ponerse verde cuando se alcanzan las necesarias
- **2.4:** Ingresar `2025/06` como período → debe rechazarse con mensaje claro
- **2.5:** Subir un PDF, luego subir otro → el segundo no debe pisar al primero en memoria
- **3.1:** Convertir el PDF de ICBC → verificar que hay hoja "Alertas" si existen filas amarillas
- **3.2:** Intentar convertir con un perfil sin columnas calibradas → debe dar error 422 con mensaje claro
- **4.0:** Abrir `localhost:8000` → debe aparecer "Conta Tools" con dos tarjetas. Cada tarjeta navega al módulo correcto. El botón 🏠 del header siempre vuelve al landing.
