import os
import shutil
import uuid
import json as json_lib
from pathlib import Path
from typing import List, Dict, Optional, Any

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pdf2image import convert_from_path

from core.calibration import CalibrationData, CalibrationIO
from core.ocr_engine import run_ocr, group_into_rows
from core.column_parser import build_col_ranges, is_transaction_row, row_to_transaction
from core.excel_writer import write_excel
from pdf_to_excel import convert, ConversionError


app = FastAPI(title="Lector de Resúmenes Bancarios - UI Web")

# Variables de entorno / Config
MAX_PAGES_PREVIEW = int(os.environ.get("MAX_PAGES_PREVIEW", "3"))
MAX_PAGES_CONVERT = int(os.environ.get("MAX_PAGES_CONVERT", "100"))

# Rutas locales
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
CALIBRATIONS_DIR = BASE_DIR / "calibraciones"
TEMP_DIR = BASE_DIR / "temp"

# Crear carpetas si no existen
STATIC_DIR.mkdir(exist_ok=True)
CALIBRATIONS_DIR.mkdir(exist_ok=True)
TEMP_DIR.mkdir(exist_ok=True)

# Montar carpeta 'static' para servir CSS, JS y PDF.js
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/", response_class=HTMLResponse)
async def read_root():
    """Sirve el frontend principal (index.html)."""
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse(content="<h1>Falta index.html en static/</h1>", status_code=404)
    return FileResponse(index_path)

@app.get("/calibraciones")
async def list_calibraciones():
    """Devuelve la lista de archivos JSON mapeados en el directorio."""
    archivos = []
    for file_path in CALIBRATIONS_DIR.glob("*.json"):
        archivos.append({
            "nombre": file_path.name,
            "tamaño": file_path.stat().st_size
        })
    return {"calibraciones": archivos}

@app.delete("/calibraciones/{nombre}")
async def delete_calibracion(nombre: str):
    """Elimina un perfil de calibración específico."""
    file_path = CALIBRATIONS_DIR / nombre
    if not file_path.exists() or file_path.suffix != '.json':
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    os.remove(file_path)
    return {"resultado": "Eliminado exitosamente"}

@app.get("/api/calibraciones/{nombre}")
async def get_calibracion(nombre: str):
    """Lee y devuelve el archivo JSON de un perfil."""
    file_path = CALIBRATIONS_DIR / nombre
    if not file_path.exists() or file_path.suffix != '.json':
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    try:
        data = CalibrationIO.load(str(file_path))
        return data.to_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/upload-pdf")
async def upload_pdf(file: UploadFile = File(...)):
    """Guarda localmente en temporal el PDF seleccionado, aislando sesiones."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="El archivo debe ser un PDF")

    safe_name = f"{uuid.uuid4().hex}.pdf"
    file_path = TEMP_DIR / safe_name

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    from core.pdf_reader import detect_pdf_type
    pdf_type = detect_pdf_type(str(file_path))

    return {
        "nombre_original": file.filename,
        "bytes_guardados": file_path.stat().st_size,
        "pdf_url": f"/temp/{safe_name}",
        "pdf_filename": safe_name,
        "pdf_type": pdf_type,
    }

class CalibrationPayload(BaseModel):
    pdf_filename: str
    banco: str
    tipo_documento: str
    periodo: str
    columnas: List[str]
    paginas_impares: Dict[str, List[float]]  # Col -> [start, end]
    paginas_pares: Optional[Dict[str, List[float]]] = None
    limites_y_impares: List[float]
    limites_y_pares: Optional[List[float]] = None

@app.post("/convert")
async def convert_pdf(
    file: UploadFile = File(...), 
    profile_name: str = Form(...),
    empresa: str = Form(default=""),
    method: str = Form(default="auto"),
):
    """Endpoint principal de conversión con SSE para progreso."""
    pdf_path = TEMP_DIR / "temp_conversion.pdf"
    with open(pdf_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    calib_path = CALIBRATIONS_DIR / profile_name
    if not calib_path.exists():
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
        
    data = CalibrationIO.load(str(calib_path))

    if not data.paginas_impares:
        raise HTTPException(status_code=422, detail="El perfil no tiene columnas calibradas para páginas impares.")
    if not data.columnas:
        raise HTTPException(status_code=422, detail="El perfil no tiene columnas definidas.")
    
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
                method=method,
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

@app.post("/preview-ocr")
async def preview_ocr(payload: CalibrationPayload):
    pdf_path = TEMP_DIR / payload.pdf_filename
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF temporal no encontrado. Sube el archivo nuevamente.")
        
    try:
        images = convert_from_path(str(pdf_path), dpi=200, first_page=1, last_page=MAX_PAGES_PREVIEW)
        
        # Uso dict generator sin validación dependiente por fallos
        col_ranges_odd = {col: (rng[0], rng[1]) for col, rng in payload.paginas_impares.items()}
        col_ranges_even = col_ranges_odd
        if payload.paginas_pares:
            col_ranges_even = {col: (rng[0], rng[1]) for col, rng in payload.paginas_pares.items()}

        transactions = []
        for page_num, img in enumerate(images, 1):
            is_even = (page_num % 2 == 0)
            active_ranges = col_ranges_even if is_even else col_ranges_odd
            
            active_y_bounds = payload.limites_y_pares if (is_even and payload.limites_y_pares) else payload.limites_y_impares
            if not active_y_bounds and payload.limites_y_impares:
                active_y_bounds = payload.limites_y_impares
            
            data = run_ocr(img)
            rows = group_into_rows(data, img.width, page_height=img.height, y_bounds=active_y_bounds if len(active_y_bounds)==2 else None)

            for row in rows:
                if is_transaction_row(row, active_ranges):
                    tx = row_to_transaction(row, active_ranges)
                    tx["_pagina"] = page_num
                    transactions.append(tx)
                    
        return {"rows": transactions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/save-calibration")
async def save_calibration(payload: CalibrationPayload):
    # Generar el JSON final
    data = CalibrationData(
        banco=payload.banco,
        tipo_documento=payload.tipo_documento,
        periodo=payload.periodo,
        columnas=payload.columnas,
        paginas_impares=payload.paginas_impares,
        paginas_pares=payload.paginas_pares or {},
        limites_y_impares=payload.limites_y_impares,
        limites_y_pares=payload.limites_y_pares or []
    )
    
    filename = f"{payload.banco}_{payload.tipo_documento}_{payload.periodo}.json"
    save_path = CALIBRATIONS_DIR / filename
    
    CalibrationIO.save(data, str(save_path))
    return {"message": "Guardado exitoso", "filename": filename}

# Servir carpeta de archivos temporales directamente para PDF.js
app.mount("/temp", StaticFiles(directory=TEMP_DIR), name="temp")
