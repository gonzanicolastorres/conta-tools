"""
core/pdf_reader.py — Detección de tipo de PDF y rendering de páginas.
"""

try:
    from pdf2image import convert_from_path
except ImportError as e:
    raise ImportError(f"Dependencia faltante: {e}. Instalá con: pip install pdf2image")

try:
    import pdfplumber
except ImportError:
    pdfplumber = None


def detect_pdf_type(pdf_path):
    """
    Detecta si el PDF tiene texto seleccionable o es una imagen escaneada.
    Retorna 'text' | 'scanned'.
    Requiere pdfplumber.
    """
    if pdfplumber is None:
        return "scanned"  # sin pdfplumber asumimos escaneado
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages[:3]:  # inspeccionar primeras 3 páginas
            words = page.extract_words()
            if words:
                return "text"
    return "scanned"


def render_pages(pdf_path, dpi=200):
    """
    Convierte todas las páginas del PDF a imágenes PIL.
    Retorna lista de imágenes en el orden del PDF.
    """
    return convert_from_path(pdf_path, dpi=dpi)


def _extract_words_pdfplumber_legacy(pdf_path):
    """
    Extrae palabras con coordenadas de un PDF con texto seleccionable.
    Retorna lista de páginas; cada página = lista de dicts:
        {text, x_pct, y, page_num}
    La estructura es compatible con group_into_rows() de ocr_engine.py.
    """
    if pdfplumber is None:
        raise ImportError("pdfplumber no está instalado. Ejecutá: pip install pdfplumber")

    pages_words = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            page_width = float(page.width)
            words = page.extract_words()
            page_data = []
            for w in words:
                x_left = float(w["x0"])
                y_top  = float(w["top"])
                page_data.append({
                    "text":     w["text"],
                    "x":        x_left,
                    "x_pct":    x_left / page_width * 100,
                    "y":        y_top,
                    "page_num": page_num,
                })
            pages_words.append(page_data)
    return pages_words

def extract_page_words_plumber(pdf_path, page_num, y_bounds=None):
    """
    Extrae palabras de UNA página de un PDF con texto seleccionable.
    page_num es 1-based.
    y_bounds: (y_min_pct, y_max_pct) para filtrar filas fuera del área útil.
    Retorna lista de {text, x, x_pct, y, y_pct} — mismo formato que
    group_into_rows() produce internamente.

    Nota: pdfplumber mide 'top' desde el borde superior del bounding box del
    texto, lo que produce y_pct levemente menores que el equivalente OCR
    (que mide desde el tope del box de píxeles). Se aplica una tolerancia de
    1.5 pp al filtro y_bounds para evitar que transacciones en los bordes del
    área útil queden excluidas por esta pequeña diferencia de coordenadas.
    """
    Y_BOUNDS_TOLERANCE = 1.5  # pp de tolerancia para diferencia OCR vs pdfplumber

    if pdfplumber is None:
        raise ImportError("pdfplumber no está instalado.")
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_num - 1]
        page_width  = float(page.width)
        page_height = float(page.height)
        words = []
        for w in page.extract_words():
            x     = float(w["x0"])
            y     = float(w["top"])
            x_pct = x / page_width  * 100
            y_pct = y / page_height * 100
            if y_bounds:
                y_min = min(y_bounds) - Y_BOUNDS_TOLERANCE
                y_max = max(y_bounds) + Y_BOUNDS_TOLERANCE
                if not (y_min <= y_pct <= y_max):
                    continue
            words.append({
                "text":  w["text"],
                "x":     x,
                "x_pct": x_pct,
                "y":     y,
                "y_pct": y_pct,
            })
        return words

def get_pdf_page_count_plumber(pdf_path):
    """Retorna el número de páginas del PDF usando pdfplumber."""
    if pdfplumber is None:
        raise ImportError("pdfplumber no está instalado.")
    with pdfplumber.open(pdf_path) as pdf:
        return len(pdf.pages)
