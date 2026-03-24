# Plan de Ejecución — Refactor y Extensión

**Versión:** 1.0
**Fecha:** 2026-03-23

---

## Resumen

Refactorizar el sistema actual (monolítico, solo ICBC, calibración por "Copia de" PDF) a una arquitectura modular con wizard de calibración, GUI principal y soporte para múltiples bancos/formatos.

---

## Fase 1 — Core modular

Extraer la lógica de `pdf_to_excel.py` en módulos independientes bajo `core/`.

### 1.1 `core/calibration.py`

Mover desde `calibrator.py` y `pdf_to_excel.py`:

- `CalibrationData` (dataclass): banco, tipo_documento, periodo, columnas, paginas_impares, paginas_pares
- `CalibrationIO.save(data, path)` / `load(path)`
- `CalibrationFinder.find_all(folder)` → lista de perfiles ordenados por periodo desc
- `CalibrationFinder.find_latest(folder, banco, tipo)` → perfil más reciente

**Criterio de completitud:** importable sin errores; `CalibrationFinder` retorna el JSON correcto dado una carpeta de prueba.

---

### 1.2 `core/pdf_reader.py`

- `detect_pdf_type(pdf_path)` → `"scanned"` | `"text"` usando `pdfplumber`
- `render_pages(pdf_path, dpi)` → lista de PIL Images (para pipeline OCR)
- `extract_words_pdfplumber(pdf_path)` → lista de páginas; cada página = lista de dicts `{text, x_pct, y, page_num}`, usando `page.extract_words()` de pdfplumber con coordenadas normalizadas por ancho de página

La salida de `extract_words_pdfplumber` debe ser compatible con la entrada que espera `group_into_rows` en `core/ocr_engine.py`, para que el resto del pipeline (asignación de columnas, parseo, Excel) funcione sin cambios.

**Criterio de completitud:** `detect_pdf_type` retorna `"scanned"` para el ICBC actual; `extract_words_pdfplumber` retorna palabras con coordenadas para un PDF de prueba con texto seleccionable.

---

### 1.3 `core/ocr_engine.py`

Extraer de `pdf_to_excel.py`:

- `run_ocr(image, lang)` → DataFrame pytesseract
- `group_into_rows(ocr_data, page_width, y_tolerance=12, min_conf=10)` → lista de filas (cada fila = lista de dicts con `text`, `x_pct`, `y`)

**Criterio de completitud:** misma salida que `words_to_rows` actual.

---

### 1.4 `core/column_parser.py`

Extraer de `pdf_to_excel.py`:

- `build_col_ranges(col_starts)` → dict `{col: (start%, end%)}`
- `assign_column_strict(x_left_pct, col_ranges)` → str
- `clean_amount(text)` → float | None
- `is_transaction_row(row, col_ranges)` → bool
- `row_to_transaction(row, col_ranges)` → dict

**Criterio de completitud:** las mismas filas del extracto ICBC 06-2025 quedan correctamente asignadas.

---

### 1.5 `core/excel_writer.py`

Extraer de `pdf_to_excel.py`:

- `write_excel(metadata, transactions, output_path)`

**Criterio de completitud:** genera el mismo Excel que hoy.

---

### 1.6 Actualizar `pdf_to_excel.py`

- Reescribir `process_pdf` y `main` para usar los módulos de `core/`.
- Eliminar la lógica de calibración por "Copia de" PDF (`detect_col_ranges_from_markers`, `_extract_line_centers`, `_lines_to_col_ranges`).
- Agregar detección de tipo de PDF al inicio: si es texto, preguntar en CLI (`input()`) si continuar con extracción directa o con OCR.
- Mantener el CLI como interfaz de uso temporal hasta que exista la GUI.

**Criterio de completitud:** `python3 pdf_to_excel.py "06-2025 ICBC.pdf" --profile calibraciones/icbc_cuenta_corriente_2025-06.json` produce el mismo Excel; un PDF con texto seleccionable pregunta y procesa correctamente por ambas rutas.

---

## Fase 2 — Wizard de calibración mejorado (`calibrator.py`)

Extender el wizard existente con:

### 2.1 Campo "período" en StepSetup

- Input de texto con formato `yyyy-mm` y validación.
- Usar como parte del nombre del JSON al guardar.

### 2.2 Paso de auto-detección de PDF

- Nuevo `StepDetect`: llama `detect_pdf_type`, muestra resultado.
- Si es `"text"`: advertencia + opción de continuar.
- Si es `"scanned"`: avanza directamente.

### 2.3 Paso de preview

- Nuevo `StepPreview`: corre OCR en la primera página + aplica los rangos marcados.
- Muestra tabla de texto (primeras 10-15 filas) con columnas asignadas.
- El usuario puede volver atrás a ajustar líneas.

### 2.4 Guardar en `calibraciones/`

- `StepReview` usa `CalibrationIO.save()` del nuevo `core/calibration.py`.
- Nombre automático: `{banco}_{tipo_documento}_{yyyy-mm}.json`.
- Si ya existe ese nombre: pide confirmación antes de sobreescribir.

### 2.5 Listar/editar perfiles existentes

- En la pantalla inicial: lista de perfiles en `calibraciones/` con opción de editar (cargar en el wizard) o eliminar.

**Criterio de completitud:** el wizard genera un JSON válido en `calibraciones/` que `pdf_to_excel.py` puede consumir directamente.

---

## Fase 3 — GUI principal (`main.py`)

Tkinter con las siguientes pantallas:

### 3.1 Pantalla principal

- Botón "Seleccionar PDF".
- Área de estado: tipo detectado, perfil seleccionado, ruta de salida.
- Botón "Convertir" (activo solo cuando hay PDF y perfil).
- Link/botón "Abrir calibrador".

### 3.2 Selección de perfil

- Lista de perfiles en `calibraciones/` ordenados por periodo desc.
- Selección automática del más reciente; el usuario puede elegir otro.
- Botón "Calibrar nuevo…" que abre `calibrator.py`.

### 3.3 Progreso y resultado

- Barra de progreso durante OCR (por página).
- Al terminar: botón "Abrir Excel" (`subprocess.open` o `os.startfile`).
- Mostrar errores si ocurren.

**Criterio de completitud:** Sole puede convertir un extracto sin usar la terminal.

---

## Fase 4 — Limpieza y documentación

- Actualizar `README.md` con la nueva arquitectura y flujo de uso.
- Eliminar el mecanismo de "Copia de" del README.
- Agregar instrucciones de instalación para las nuevas dependencias (`pdfplumber`).
- Eliminar código muerto de `pdf_to_excel.py` (funciones de comparación de píxeles).

---

## Orden de ejecución recomendado

```
Fase 1.1 → 1.2 → 1.3 → 1.4 → 1.5 → 1.6   (core)
Fase 2.1 → 2.2 → 2.4 → 2.3 → 2.5           (calibrator)
Fase 3.1 → 3.2 → 3.3                         (main GUI)
Fase 4                                         (cleanup)
```

Las fases 1 y 2 son independientes entre sí y pueden trabajarse en paralelo si hay capacidad. La fase 3 depende de que 1 y 2 estén completas. La fase 4 es la última.

---

## Dependencias adicionales a instalar

```bash
pip install pdfplumber
```

`pdfplumber` cubre tanto la detección de tipo como la extracción directa de palabras con coordenadas.

Las demás dependencias (`pdf2image`, `pytesseract`, `openpyxl`, `pillow`) ya están en uso.

---

## Criterio global de éxito

1. `python3 main.py` abre la GUI y Sole puede convertir `06-2025 ICBC.pdf` sin tocar la terminal.
2. `python3 calibrator.py` abre el wizard y genera un JSON válido en `calibraciones/`.
3. El Excel generado tiene las 9 columnas correctamente asignadas en todas las páginas (pares e impares).
4. No hay referencias a "Copia de" en el código ni en la documentación.
5. El Excel incluye columna **Hoja** para facilitar corrección manual de valores no reconocidos por OCR (ej. números tapados por marca de agua).

---

## Comportamientos ya implementados (no requieren desarrollo adicional)

- Columna **Hoja** en la hoja Movimientos del Excel: número de página del PDF de origen.
- Preprocesamiento OCR con binarización configurable (`--threshold`, default 160): reduce ruido de marcas de agua pero no elimina completamente la interferencia donde el sello se superpone directamente con números. La columna Hoja compensa esta limitación.
