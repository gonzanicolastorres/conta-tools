"""
core/ocr_engine.py — OCR sobre imágenes de páginas PDF.
"""

try:
    import pytesseract
    from PIL import ImageOps
except ImportError as e:
    raise ImportError(f"Dependencia faltante: {e}. Instalá con: pip install pytesseract pillow")


def preprocess_for_ocr(img, threshold=160):
    """
    Convierte a escala de grises y binariza para reducir ruido de marcas de agua.
    threshold: píxeles más oscuros que este valor → negro; resto → blanco.
    """
    gray = img.convert("L")
    bw = gray.point(lambda x: 0 if x < threshold else 255)
    return bw


def run_ocr(image, lang="spa", threshold=160):
    """
    Corre Tesseract sobre una imagen PIL y devuelve el dict de datos posicionales.
    """
    img_proc = preprocess_for_ocr(image, threshold=threshold)
    return pytesseract.image_to_data(img_proc, lang=lang, output_type=pytesseract.Output.DICT)


def group_into_rows(data, page_width, page_height=None, y_bounds=None, y_tolerance=12, min_conf=10):
    """
    Agrupa palabras del OCR en filas según proximidad vertical.
    Si se provee y_bounds (y_min_%, y_max%) y page_height, ignora lo que quede fuera.
    """
    words = []
    for i, text in enumerate(data["text"]):
        text = text.strip()
        if not text or data["conf"][i] < min_conf:
            continue
        x = data["left"][i]
        y = data["top"][i]
        
        y_pct = None
        if page_height:
            y_pct = y / page_height * 100
            if y_bounds and not (min(y_bounds) <= y_pct <= max(y_bounds)):
                continue

        words.append({"text": text, "x": x, "x_pct": x / page_width * 100, "y": y, "y_pct": y_pct})

    if not words:
        return []

    words.sort(key=lambda w: w["y"])
    rows = []
    current_row = [words[0]]
    for w in words[1:]:
        if abs(w["y"] - current_row[0]["y"]) <= y_tolerance:
            current_row.append(w)
        else:
            rows.append(sorted(current_row, key=lambda w: w["x"]))
            current_row = [w]
    rows.append(sorted(current_row, key=lambda w: w["x"]))
    return rows


def group_words_into_rows(words, y_tolerance=12):
    """
    Agrupa una lista de word-dicts {text, x, x_pct, y, y_pct} en filas.
    Mismo formato de salida que group_into_rows().
    """
    if not words:
        return []
    words = sorted(words, key=lambda w: w["y"])
    rows = []
    current_row = [words[0]]
    for w in words[1:]:
        if abs(w["y"] - current_row[0]["y"]) <= y_tolerance:
            current_row.append(w)
        else:
            rows.append(sorted(current_row, key=lambda w: w["x"]))
            current_row = [w]
    rows.append(sorted(current_row, key=lambda w: w["x"]))
    return rows
