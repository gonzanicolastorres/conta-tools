# Especificación Funcional — Lector de Resúmenes Bancarios

**Versión:** 2.0
**Fecha:** 2026-03-24
**Estado:** Implementado — refleja el sistema en producción

---

## 1. Objetivo

Convertir extractos bancarios en PDF (escaneados o digitales) a archivos Excel estructurados, con soporte para múltiples bancos/formatos y perfiles de calibración reutilizables. El sistema corre como app web local y es accesible sin conocimientos técnicos.

---

## 2. Arquitectura

```
lector-resumenes-bancarios/
├── calibraciones/                    ← perfiles JSON reutilizables
│   └── {banco}_{tipo}_{yyyy-mm}.json
├── core/
│   ├── calibration.py               ← CalibrationData, CalibrationIO, CalibrationFinder
│   ├── pdf_reader.py                ← detect_pdf_type, render_pages, extract_page_words_plumber
│   ├── ocr_engine.py                ← run_ocr, group_into_rows, group_words_into_rows
│   ├── column_parser.py             ← assign_columns, parse_amount, is_saldo_inicial
│   └── excel_writer.py              ← write_excel (hojas: Movimientos, OCR Raw, Alertas)
├── server.py                        ← backend FastAPI con SSE para progreso
├── pdf_to_excel.py                  ← librería de conversión (función convert()) + CLI
├── diagnostico.py                   ← CLI para depurar calibraciones
├── compare_excel.py                 ← CLI para comparar dos Excel
├── static/
│   ├── index.html                   ← SPA: landing, calibrador, conversor
│   └── canvas.js                    ← CalibrationCanvas interactivo (pdf.js)
├── legacy/                          ← versión tkinter descontinuada
├── specs/                           ← documentación de diseño
└── README.md
```

---

## 3. Pipeline de conversión

```
PDF de entrada
    │
    ▼
Detección de tipo de PDF
    │ ¿Tiene texto seleccionable?
    ├── NO  → pipeline OCR (Tesseract)
    └── SÍ  → preguntar al usuario
               ├── "Extracción directa" → pipeline pdfplumber
               └── "Usar OCR igual"    → pipeline OCR (Tesseract)
    │
    ▼
Selección de perfil de calibración
    │ ¿Hay perfiles en calibraciones/?
    ├── NO → invitar a calibrar primero
    └── SÍ → usar el más reciente compatible
    │         (el usuario puede elegir otro)
    ▼
OCR por página (Tesseract, DPI configurable)
    │
    ▼
Agrupación de palabras en filas por proximidad vertical (tolerancia ±12px)
    │
    ▼
Asignación de columna por borde izquierdo + rangos estrictos [start%, end%)
    │ Páginas impares: usar col_ranges_odd
    │ Páginas pares:   usar col_ranges_even
    ▼
Post-proceseo: overflow fecha→concepto, parseo de importes
    │
    ▼
Generación de Excel (2 hojas: Movimientos + OCR Raw)
```

---

## 4. Detección de tipo de PDF

- Usar `pdfplumber` para inspeccionar si el PDF contiene texto extraíble.
- **Si no tiene texto (escaneado):** proceder directamente con OCR.
- **Si tiene texto seleccionable:** preguntar al usuario:
  - _"Continuar con extracción directa"_ → usar `pdfplumber` (más rápido y preciso, recomendado).
  - _"Continuar con OCR"_ → usar Tesseract igual que con un PDF escaneado (el usuario elige esto si sospecha que el texto extraíble tiene errores).
- No se investiga la causa del problema si el usuario elige OCR sobre un PDF con texto.

---

## 5. Perfiles de calibración

### 5.1 Formato del nombre de archivo

```
{banco}_{tipo_documento}_{yyyy-mm}.json
```

- `banco`: nombre libre (ej. `icbc`, `galicia`)
- `tipo_documento`: nombre libre (ej. `cuenta_corriente`, `tarjeta`)
- `yyyy-mm`: período del resumen (no la fecha de hoy)
- Si ya existe un JSON con el mismo `yyyy-mm` para el mismo banco+tipo, se sobreescribe.

### 5.2 Estructura del JSON

```json
{
  "banco": "icbc",
  "tipo_documento": "cuenta_corriente",
  "periodo": "2025-06",
  "columnas": ["FECHA", "CONCEPTO", "F.VALOR", "COMPROBANTE", "ORIGEN", "CANAL", "DÉBITOS", "CRÉDITOS", "SALDOS"],
  "paginas_impares": {
    "FECHA":        [0.0,   17.3],
    "CONCEPTO":     [17.3,  35.8],
    "F.VALOR":      [35.8,  39.9],
    "COMPROBANTE":  [39.9,  49.2],
    "ORIGEN":       [49.2,  52.9],
    "CANAL":        [52.9,  56.6],
    "DÉBITOS":      [56.6,  70.7],
    "CRÉDITOS":     [70.7,  85.9],
    "SALDOS":       [85.9, 100.0]
  },
  "paginas_pares": {
    "FECHA":        [0.0,   7.1],
    "CONCEPTO":     [7.1,  25.5],
    ...
  }
}
```

### 5.3 Selección automática

- El sistema busca en `calibraciones/` todos los JSON que coincidan con el banco+tipo detectado o elegido.
- Selecciona el de `yyyy-mm` más reciente.
- El usuario puede elegir uno diferente desde la GUI.

### 5.4 Almacenamiento

- Carpeta `calibraciones/` local, junto a los scripts.
- No hay sincronización remota ni base de datos.

---

## 6. Wizard de calibración (interfaz web — `static/index.html` + `canvas.js`)

### 6.1 Pasos del wizard

1. **Setup**: banco, tipo de documento, período (yyyy-mm), lista de columnas (editable). Validación de formato YYYY-MM en el campo período.
2. **Subir PDF**: el PDF se renderiza en el canvas usando pdf.js (lado del cliente).
3. **Marcar columnas — páginas impares**: canvas interactivo con navegación de páginas (◀ ▶), zoom, y contador en tiempo real de líneas marcadas vs. requeridas.
4. **¿Calibrar páginas pares también?**: branching — SÍ → paso 5 / NO → copia rangos de impares.
5. **Marcar columnas — páginas pares** (mismo canvas, mostrando página 2 del PDF).
6. **Preview OCR**: tabla de transacciones detectadas (primeras páginas), para verificar la calibración antes de guardar.
7. **Guardar**: `POST /save-calibration` → JSON en `calibraciones/`.

### 6.2 Funcionalidad del canvas (`canvas.js` — `CalibrationCanvas`)

- Renderizado con **pdf.js** (sin backend, sin latencia).
- Navegación entre páginas con botones ◀ ▶.
- Zoom interactivo.
- Modo columnas (X): click izquierdo agrega línea vertical; click derecho elimina.
- Modo límites horizontales (Y): marca área útil (top/bottom) para ignorar encabezados y pies de página.
- Contador en tiempo real: se vuelve verde cuando se alcanzan las líneas requeridas.
- Evento custom `linesChanged` para sincronizar el contador en el HTML.

---

## 7. Interfaz web de conversión (`static/index.html` — pantalla "Convertir a Excel")

### 7.1 Flujo

1. El usuario ingresa el nombre de empresa.
2. Selecciona el perfil de calibración del banco.
3. Sube uno o varios PDFs. Si el PDF tiene texto seleccionable, se le pregunta si usar extracción directa o OCR.
4. Hace click en "Convertir". La barra de progreso avanza página a página (Server-Sent Events).
5. Al terminar: botón de descarga por cada Excel generado.

### 7.2 Tecnología

- Frontend: SPA HTML/JS sin framework, usando pdf.js para renderizado.
- Backend: FastAPI con `StreamingResponse` (SSE) para progreso en tiempo real.
- PDFs temporales con nombre UUID para aislar sesiones concurrentes.

---

## 8. Módulos del core

### `core/pdf_reader.py`
- `detect_pdf_type(pdf_path)` → `"scanned"` | `"text"`
- `render_pages(pdf_path, dpi)` → lista de PIL Images (para pipeline OCR)
- `extract_words_pdfplumber(pdf_path)` → lista de páginas; cada página = lista de dicts `{text, x_pct, y, page_num}` (para pipeline de extracción directa)

### `core/ocr_engine.py`
- `run_ocr(image, lang)` → DataFrame con palabras y coordenadas
- `group_into_rows(ocr_data, page_width, y_tolerance)` → lista de filas

### `core/column_parser.py`
- `build_col_ranges(col_starts)` → dict `{col: (start%, end%)}`
- `assign_column_strict(x_left_pct, col_ranges)` → nombre de columna
- `clean_amount(text)` → float | None (formato argentino)
- `is_transaction_row(row, col_ranges)` → bool
- `row_to_transaction(row, col_ranges)` → dict

### `core/calibration.py`
- `CalibrationData` (dataclass): banco, tipo_documento, periodo, columnas, paginas_impares, paginas_pares
- `CalibrationIO`: `save(data, path)`, `load(path)`
- `CalibrationFinder`: `find_all(folder)`, `find_latest(folder, banco, tipo)`

### `core/excel_writer.py`
- `write_excel(metadata, transactions, output_path)`
- Hoja "Movimientos": encabezado, colores (rojo=débito, verde=crédito), formato argentino, filas alternas.
- Hoja "OCR Raw": línea cruda por movimiento para diagnóstico.

---

## 9. Comportamiento con páginas pares/impares

- Los extractos ICBC tienen márgenes espejo: páginas pares están desplazadas ~10% hacia la izquierda.
- El perfil JSON almacena dos conjuntos de rangos: `paginas_impares` y `paginas_pares`.
- Durante la conversión, se selecciona el conjunto correcto según `page_num % 2`.

---

## 10. Formato de números (Argentina)

- Separador de miles: `.` (punto)
- Separador decimal: `,` (coma)
- Débitos marcados con `-` al final (ej. `178.812,40-`)
- El parseo toma ambas convenciones y normaliza a float.

---

## 11. Salida Excel

| Campo | Descripción |
|---|---|
| FECHA | DD-MM |
| CONCEPTO | descripción del movimiento |
| F.VALOR | fecha valor (DD-MM) |
| COMPROBANTE | número de comprobante |
| ORIGEN | código de origen |
| CANAL | canal de operación |
| DÉBITOS | importe débito (float, rojo) |
| CRÉDITOS | importe crédito (float, verde) |
| SALDOS | saldo al cierre del día (null en filas intermedias) |
| HOJA | número de página del PDF de origen |

Los headers del Excel se derivan directamente de los nombres de columna definidos en el perfil de calibración (ej. `"f_valor"` → `"F.Valor"`), por lo que son dinámicos y adaptables a cualquier banco.

La columna **HOJA** facilita la corrección manual: cuando un importe queda vacío (por ej. por una marca de agua sobre el número), el usuario sabe exactamente en qué página del PDF buscar el valor correcto.

---

## 12. Decisiones de diseño

| Decisión | Resolución |
|---|---|
| Interfaz principal | App web local (FastAPI + HTML/JS + pdf.js) — sin tkinter |
| Mecanismo de calibración | Wizard interactivo en el browser (canvas.js) |
| Persistencia de calibración | JSON en `calibraciones/` local |
| Nombre del JSON | `{banco}_{tipo}_{yyyy-mm}.json`; mismo yyyy-mm sobreescribe |
| Selección de calibración | El usuario elige desde el dropdown; se listan todos los perfiles disponibles |
| Preview de calibración | Tabla de transacciones detectadas via `POST /preview-ocr` |
| Soporte multi-banco | Por perfiles JSON; cualquier banco se puede calibrar desde la UI |
| PDF con texto seleccionable | El servidor detecta el tipo; la UI pregunta: extracción directa (pdfplumber) o forzar OCR |
| Asignación de columnas | Borde izquierdo + rangos estrictos (no "closest column") |
| Headers del Excel | Dinámicos: derivados de los nombres de columna del perfil de calibración |
| Páginas pares vs impares | Dos conjuntos de rangos independientes en el JSON |
| Marcas de agua | No resueltas automáticamente; columna HOJA guía la corrección manual |
| Preprocesamiento OCR | Binarización con threshold configurable (`--threshold`, default 160) para reducir ruido |
| Progreso de conversión | Server-Sent Events (SSE): la barra avanza página a página en tiempo real |
| Aislamiento de sesiones | PDFs temporales nombrados con UUID para evitar colisiones entre usuarios |

---

## 13. Fuera de alcance (por ahora)

- Sincronización remota de calibraciones.
- Detección automática del banco por texto del header (requiere calibración manual siempre).
- Detección de duplicados al consolidar meses.
- Multi-tenant / autenticación (es una herramienta de uso individual/doméstico).
