# Plan de Ejecución — Refactor y Extensión

**Versión:** 2.0
**Fecha original:** 2026-03-23
**Actualizado:** 2026-03-24
**Estado:** COMPLETADO — todas las fases implementadas

---

## Resumen

Refactorizar el sistema monolítico original (solo ICBC, calibración por "Copia de" PDF, CLI únicamente) a una arquitectura modular con wizard de calibración en el browser, app web completa y soporte para múltiples bancos/formatos.

> Este plan fue superado por `plan-web-ui.md` que reemplazó Tkinter por una interfaz web. Ambos planes están completamente implementados.

---

## Fase 1 — Core modular ✅ COMPLETADO

Toda la lógica de `pdf_to_excel.py` fue extraída en módulos independientes bajo `core/`.

### 1.1 `core/calibration.py` ✅
- `CalibrationData`, `CalibrationIO`, `CalibrationFinder` — implementados.
- Soporte adicional: `limites_y_impares`, `limites_y_pares`, `set_ranges()`, `to_dict()`.

### 1.2 `core/pdf_reader.py` ✅
- `detect_pdf_type()`, `render_pages()` — implementados.
- Agregados: `extract_page_words_plumber()`, `get_pdf_page_count_plumber()`.

### 1.3 `core/ocr_engine.py` ✅
- `run_ocr()`, `group_into_rows()` — implementados.
- Agregado: `group_words_into_rows()` para el pipeline de extracción directa.

### 1.4 `core/column_parser.py` ✅
- `build_col_ranges()`, `assign_column_strict()`, `clean_amount()`, `is_transaction_row()`, `row_to_transaction()` — implementados.
- Agregados: `is_saldo_inicial()`, `extract_saldo_inicial()`.

### 1.5 `core/excel_writer.py` ✅
- `write_excel()` — implementado con tres hojas: **Movimientos**, **OCR Raw**, **Alertas**.

### 1.6 `pdf_to_excel.py` actualizado ✅
- Usa todos los módulos de `core/`.
- Pipeline dual: OCR (Tesseract) y extracción directa (pdfplumber), seleccionable con `--method` o detección automática.
- Callback `on_progress` para progreso en tiempo real.
- Tipos públicos: `ConversionResult`, `ConversionError`, `NoTransactionsError`.

---

## Fase 2 — Wizard de calibración ✅ COMPLETADO (vía web)

El wizard fue implementado como SPA en `static/index.html` + `static/canvas.js` en lugar de Tkinter. Ver `plan-web-ui.md`.

---

## Fase 3 — GUI principal ✅ COMPLETADO (vía web)

La pantalla de conversión fue implementada como pantalla web en lugar de Tkinter. Ver `plan-web-ui.md`.

---

## Fase 4 — Limpieza y documentación ✅ COMPLETADO

- `README.md` actualizado con arquitectura web y flujo de uso.
- Código legacy (tkinter) movido a `legacy/`.
- Mecanismo "Copia de" eliminado del código.
- Documentación de specs actualizada (2026-03-24).

---

## Criterio global de éxito — Verificación final

1. ✅ `uvicorn server:app --reload` → la app abre en `localhost:8000`.
2. ✅ Se puede crear una calibración completa sin la terminal.
3. ✅ Se puede convertir un PDF a Excel sin la terminal.
4. ✅ El Excel incluye columna **HOJA** para corrección manual.
5. ✅ No hay referencias a "Copia de" en el código ni en la documentación.
6. ✅ El Excel incluye hoja **Alertas** con filas sin monto detectado.
