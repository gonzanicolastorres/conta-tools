# Especificación Funcional — Lector de Resúmenes Bancarios

**Versión:** 1.0
**Fecha:** 2026-03-23
**Estado:** Acordado, pendiente de implementación

---

## 1. Objetivo

Convertir extractos bancarios en PDF escaneado (imágenes) a archivos Excel estructurados, con soporte para múltiples bancos/formatos y perfiles de calibración reutilizables. El sistema está diseñado para uso doméstico y debe ser accesible sin conocimientos técnicos.

---

## 2. Arquitectura objetivo

```
lector-resumenes-bancarios/
├── calibraciones/                    ← perfiles JSON reutilizables
│   └── {banco}_{tipo}_{yyyy-mm}.json
├── core/
│   ├── calibration.py               ← CalibrationData, CalibrationIO, CalibrationFinder
│   ├── pdf_reader.py                ← detect_pdf_type, extract_text, render_pages
│   ├── ocr_engine.py                ← run_ocr, group_into_rows
│   ├── column_parser.py             ← assign_columns, parse_amount
│   └── excel_writer.py              ← write_excel
├── calibrator.py                    ← wizard interactivo de calibración
├── main.py                          ← GUI principal (conversión)
├── specs/
│   ├── functional_spec.md           ← este archivo
│   └── plan.md                      ← plan de ejecución
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

## 6. Wizard de calibración (`calibrator.py`)

### 6.1 Pasos del wizard

1. **Configuración**: banco, tipo de documento, período (yyyy-mm), lista de columnas (editable: agregar/quitar/reordenar).
2. **Auto-detección de PDF**: verificar si el PDF tiene texto o no; informar al usuario.
3. **Marcar columnas — páginas impares**: canvas con zoom, el usuario hace click para agregar líneas verticales (N-1 líneas para N columnas). Muestra zonas de color como feedback.
4. **¿Calibrar páginas pares también?**: branching.
   - SÍ → paso 5.
   - NO → copiar rangos de impares a pares.
5. **Marcar columnas — páginas pares** (igual que paso 3, pero sobre página 2 del PDF).
6. **Preview**: tabla de texto parseado (primeras filas del PDF) usando los rangos actuales, para verificar que la asignación es correcta.
7. **Guardar**: confirmar nombre y guardar JSON en `calibraciones/`.

### 6.2 Funcionalidad del canvas

- Zoom: niveles 0.25x a 3.0x.
- Click izquierdo: agregar línea vertical.
- Click derecho: eliminar línea más cercana.
- Undo (Ctrl+Z).
- Clear: borrar todas las líneas.
- Zonas de color con stipple entre líneas (feedback visual de columnas).
- Status label: "N de N-1 líneas marcadas".

### 6.3 Navegación del wizard

- Botones Atrás / Siguiente en cada paso.
- Pila de pasos (stack) para soporte de branching.
- Cada paso valida condiciones antes de permitir avanzar.

---

## 7. GUI principal (`main.py`)

### 7.1 Flujo

1. El usuario selecciona un PDF.
2. El sistema detecta el tipo (escaneado o con texto) e informa.
3. El sistema sugiere el perfil de calibración más reciente compatible.
4. El usuario puede aceptar o elegir otro perfil.
5. El usuario puede lanzar la calibración si no hay perfiles.
6. El usuario inicia la conversión.
7. Se muestra progreso.
8. Al terminar: botón para abrir el Excel generado.

### 7.2 Tecnología

- Tkinter (estándar de Python, sin dependencias extra de GUI).
- Sin diseño elaborado; funcional y claro.

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

## 12. Decisiones de diseño acordadas

| Decisión | Resolución |
|---|---|
| Mecanismo de calibración | Wizard interactivo (reemplaza "Copia de" PDF) |
| Persistencia de calibración | JSON en `calibraciones/` local |
| Nombre del JSON | `{banco}_{tipo}_{yyyy-mm}.json`; mismo yyyy-mm sobreescribe |
| Selección de calibración | Automática (más reciente); el usuario puede elegir |
| Preview de calibración | Tabla de texto parseado (más rápido de implementar) |
| GUI principal | Tkinter |
| Soporte multi-banco | Por módulos; detección por encabezado de PDF (futuro) |
| PDF con texto seleccionable | Preguntar: extracción directa (pdfplumber, recomendado) o forzar OCR |
| Asignación de columnas | Borde izquierdo + rangos estrictos (no "closest column") |
| Headers del Excel | Dinámicos: derivados de los nombres de columna del perfil de calibración |
| Páginas pares vs impares | Dos conjuntos de rangos independientes en el JSON |
| Marcas de agua | No resueltas automáticamente; columna HOJA guía la corrección manual |
| Preprocesamiento OCR | Binarización con threshold configurable (`--threshold`, default 160) para reducir ruido |

---

## 13. Fuera de alcance (por ahora)

- Sincronización remota de calibraciones.
- Soporte automático para otros bancos (se requiere calibración manual).
- Detección automática del banco por texto del header.
- Procesamiento por lotes desde la GUI.
- Detección de duplicados al consolidar meses.
