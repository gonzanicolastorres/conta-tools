# Conta Tools — Lector de Extractos Bancarios

Herramienta web para convertir extractos bancarios en PDF a archivos Excel estructurados. Soporta PDFs escaneados (OCR con Tesseract) y PDFs con texto seleccionable (extracción directa). Diseñada para contadores que trabajan con múltiples bancos y formatos.

---

## Características

- Conversión de PDF bancario a Excel formateado con un click
- Soporte para PDFs escaneados (OCR) y PDFs digitales (extracción directa)
- Sistema de calibración visual: marcá las columnas sobre el PDF directamente en el navegador
- Perfiles de calibración reutilizables por banco y tipo de documento
- Progreso en tiempo real durante la conversión (Server-Sent Events)
- Excel con colores por tipo de movimiento, hoja de alertas para filas a revisar

---

## Requisitos del sistema

**macOS:**
```bash
brew install tesseract tesseract-lang poppler
```

**Python 3.12+** (recomendado via conda):
```bash
conda create -n conta-tools python=3.12
conda activate conta-tools
pip install -r requirements.txt
```

---

## Instalación

```bash
git clone <repo>
cd lector-resumenes-bancarios
conda activate conta-tools
pip install -r requirements.txt
```

---

## Uso

```bash
conda activate conta-tools
uvicorn server:app --reload
```

Abrir en el navegador: [http://localhost:8000](http://localhost:8000)

---

## Flujo de trabajo

### 1. Calibrar un banco nuevo

La calibración le enseña al sistema dónde están las columnas en un extracto específico. Se hace una sola vez por banco y tipo de documento.

1. Ir a **Calibrador** en la pantalla de inicio
2. Subir un PDF de muestra del banco
3. Completar los datos: banco, tipo de documento, período
4. Marcar las líneas verticales que separan columnas (página impar y par)
5. Opcionalmente, marcar los límites horizontales del área de datos
6. Hacer preview del OCR para verificar
7. Guardar el perfil

Los perfiles se guardan en `calibraciones/` como archivos JSON y quedan disponibles para futuras conversiones.

### 2. Convertir extractos

1. Ir a **Convertir a Excel** en la pantalla de inicio
2. Ingresar el nombre de la empresa del cliente
3. Seleccionar el perfil de calibración correspondiente al banco
4. Subir uno o varios PDFs
5. Hacer click en **Convertir**
6. Descargar los Excel generados

---

## Estructura del proyecto

```
conta-tools/
├── server.py              # Backend FastAPI — endpoints y servidor web
├── pdf_to_excel.py        # Librería de conversión (función convert())
├── diagnostico.py         # CLI para depurar calibraciones
├── compare_excel.py       # CLI para comparar dos Excel (control de calidad)
├── requirements.txt
│
├── core/
│   ├── calibration.py     # CalibrationData, CalibrationIO, CalibrationFinder
│   ├── pdf_reader.py      # Detección de tipo PDF, rendering, extracción pdfplumber
│   ├── ocr_engine.py      # Tesseract OCR, agrupación en filas
│   ├── column_parser.py   # Asignación de palabras a columnas, parseo de importes
│   └── excel_writer.py    # Generación del Excel con openpyxl
│
├── static/
│   ├── index.html         # Frontend SPA (calibrador + conversor)
│   └── canvas.js          # CalibrationCanvas — canvas interactivo para marcar columnas
│
├── calibraciones/         # Perfiles JSON (generados por el calibrador)
├── temp/                  # Archivos temporales (PDFs subidos, Excel generados)
├── legacy/                # Versión tkinter (descontinuada)
└── specs/                 # Documentos de diseño y planificación
```

---

## Arquitectura

### Backend (`server.py`)

FastAPI con los siguientes endpoints:

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/` | Sirve el frontend |
| GET | `/calibraciones` | Lista perfiles disponibles |
| DELETE | `/calibraciones/{nombre}` | Elimina un perfil |
| GET | `/api/calibraciones/{nombre}` | Lee un perfil JSON |
| POST | `/upload-pdf` | Guarda PDF temporal, detecta tipo (text/scanned) |
| POST | `/preview-ocr` | Corre OCR sobre primeras páginas para verificar calibración |
| POST | `/save-calibration` | Guarda perfil de calibración |
| POST | `/convert` | Convierte PDF a Excel (responde con SSE para progreso) |

### Pipeline de conversión (`pdf_to_excel.py`)

```
PDF
 │
 ├─ PDF digital ──→ pdfplumber → palabras con coordenadas
 │
 └─ PDF escaneado → pdf2image → imagen → Tesseract OCR → palabras con coordenadas
                                                    │
                                    group_into_rows() → filas
                                                    │
                                    is_transaction_row() → filtrado
                                                    │
                                    row_to_transaction() → asignación a columnas
                                                    │
                                    write_excel() → Excel formateado
```

### Calibración

Los perfiles se guardan como JSON con esta estructura:

```json
{
  "banco": "ICBC",
  "tipo_documento": "cuenta-corriente",
  "periodo": "2025-06",
  "columnas": ["fecha", "concepto", "f_valor", "comprobante", "origen", "canal", "debitos", "creditos", "saldos"],
  "paginas_impares": {
    "fecha":       [0.0,  17.3],
    "concepto":    [17.3, 35.8],
    "debitos":     [56.6, 70.7],
    ...
  },
  "paginas_pares": { ... },
  "limites_y_impares": [10.5, 92.0],
  "limites_y_pares":   [10.5, 92.0]
}
```

Los rangos son **porcentajes del ancho de página**, lo que hace los perfiles independientes del DPI de renderizado.

### Por qué páginas impares y pares

Los extractos bancarios suelen tener márgenes espejo: las páginas pares están desplazadas horizontalmente respecto de las impares (como un libro). El sistema calibra dos conjuntos de rangos independientes para manejar esto correctamente.

### Excel generado

El archivo Excel tiene hasta tres hojas:

- **Movimientos**: tabla formateada con encabezado de metadata (empresa, titular, CUIT, período, saldo inicial), colores por tipo de movimiento (rojo=débito, verde=crédito, amarillo=sin monto detectado) y columna de número de página
- **OCR Raw**: datos crudos de OCR por fila, para diagnóstico
- **Alertas** *(si aplica)*: lista de filas sin monto detectado para revisión manual

---

## Herramientas de diagnóstico

### `diagnostico.py`

Muestra las transacciones detectadas por página para verificar la calibración:

```bash
python diagnostico.py extracto.pdf --profile calibraciones/ICBC_cuenta-corriente_2025-06.json
python diagnostico.py extracto.pdf --profile calibraciones/ICBC_cuenta-corriente_2025-06.json --paginas 1,2 --filas 20
```

### `compare_excel.py`

Compara dos archivos Excel para control de calidad:

```bash
python compare_excel.py original.xlsx nuevo.xlsx
python compare_excel.py original.xlsx nuevo.xlsx --detalle
```

---

## Variables de entorno

| Variable | Default | Descripción |
|---|---|---|
| `MAX_PAGES_PREVIEW` | `3` | Páginas procesadas en el preview del calibrador |
| `MAX_PAGES_CONVERT` | `100` | Límite de páginas por conversión |

---

## Dependencias principales

| Paquete | Uso |
|---|---|
| `fastapi` + `uvicorn` | Servidor web |
| `pdfplumber` | Extracción de texto de PDFs digitales |
| `pdf2image` | Renderizado de PDFs escaneados a imagen |
| `pytesseract` | OCR sobre imágenes |
| `pillow` | Procesamiento de imágenes |
| `openpyxl` | Generación de archivos Excel |
| `pydantic` | Validación de datos en la API |

Binarios del sistema requeridos: `tesseract`, `tesseract-lang` (español), `poppler`.
