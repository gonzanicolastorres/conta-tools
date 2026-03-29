"""
core/ocr_engine.py — OCR sobre imágenes de páginas PDF.
"""

try:
    import pytesseract
    from PIL import ImageOps, Image
    import cv2
    import numpy as np
except ImportError as e:
    raise ImportError(f"Dependencia faltante: {e}. Instalá con: pip install pytesseract pillow opencv-python numpy")


def preprocess_for_ocr(img, threshold=160, remove_watermark=False, adaptive=False):
    """
    Convierte a escala de grises y binariza para reducir ruido de marcas de agua.

    Args:
        img: imagen PIL
        threshold: umbral de binarización 0-255 (ignorado si adaptive=True)
        remove_watermark: si True, remueve el sello "Copia Fiel" antes de binarizar
        adaptive: si True, usa binarización adaptativa de Otsu en lugar de threshold fijo

    Returns:
        imagen binarizada (PIL)
    """
    if remove_watermark:
        # Remover sello gris (80-200) antes de binarizar
        # Esto mejora OCR eliminando la contaminación del sello diagonal

        # Convertir PIL a numpy para procesamiento con cv2
        img_array = np.array(img.convert("RGB"))
        gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)

        # Detectar píxeles grises del sello
        mask = cv2.inRange(gray, 140, 200)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask_dilated = cv2.dilate(mask, kernel, iterations=2)

        # Rellenar sello con blanco
        img_bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
        img_bgr[mask_dilated == 255] = [255, 255, 255]
        img_cleaned = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

        # Convertir de vuelta a PIL
        img = Image.fromarray(img_cleaned)

    # Binarizar
    if adaptive:
        # Binarización adaptativa usando Otsu's method
        img_array = np.array(img.convert("L"))
        _, bw_array = cv2.threshold(img_array, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        bw = Image.fromarray(bw_array)
    else:
        # Threshold fijo
        gray = img.convert("L")
        bw = gray.point(lambda x: 0 if x < threshold else 255)

    return bw


def run_ocr(image, lang="spa", threshold=160, psm=6, remove_watermark=False, adaptive=False):
    """
    Corre Tesseract sobre una imagen PIL y devuelve el dict de datos posicionales.

    Args:
        image: imagen PIL
        lang: idioma OCR (default "spa")
        threshold: umbral de binarización 0-255 (default 160, ignorado si adaptive=True)
        psm: Page Segmentation Mode de Tesseract (default 6 = bloque uniforme, mejor para tablas)
             3 = auto
             6 = bloque uniforme, mejor para tablas
        remove_watermark: si True, remueve sello "Copia Fiel" antes de OCR
        adaptive: si True, usa binarización adaptativa de Otsu
    """
    img_proc = preprocess_for_ocr(
        image, threshold=threshold, remove_watermark=remove_watermark, adaptive=adaptive
    )
    config = f"--psm {psm}"
    return pytesseract.image_to_data(
        img_proc, lang=lang, config=config, output_type=pytesseract.Output.DICT
    )


def group_into_rows(data, page_width, page_height=None, y_bounds=None, y_tolerance=12, min_conf=10):
    """
    Agrupa palabras del OCR en filas según proximidad vertical.
    Si se provee y_bounds (y_min_%, y_max%) y page_height, ignora lo que quede fuera.

    Nota: Internamente captura tokens con baja confianza (0-10) para merge_number_fragments,
    pero solo los incluye si están adyacentes a números de alta confianza.
    """
    # Primero, capturar TODOS los tokens sin filtrar por confianza
    # Usaremos esta lista para find low-conf fragments
    all_tokens = []
    for i, text in enumerate(data["text"]):
        text = text.strip()
        if not text:
            continue
        x = data["left"][i]
        y = data["top"][i]

        y_pct = None
        if page_height:
            y_pct = y / page_height * 100
            if y_bounds and not (min(y_bounds) <= y_pct <= max(y_bounds)):
                continue

        all_tokens.append({
            "text": text,
            "x": x,
            "x_pct": x / page_width * 100,
            "y": y,
            "y_pct": y_pct,
            "conf": data["conf"][i],
            "width": data["width"][i],
            "height": data["height"][i],
            "idx": i
        })

    # Filtrar palabras de alta confianza (min_conf)
    words = [t for t in all_tokens if t["conf"] >= min_conf]

    if not words:
        return []

    # Agrupar en filas
    words.sort(key=lambda w: w["y"])
    rows = []
    current_row = [words[0]]
    for w in words[1:]:
        if abs(w["y"] - current_row[0]["y"]) <= y_tolerance:
            current_row.append(w)
        else:
            sorted_row = sorted(current_row, key=lambda w: w["x"])
            rows.append(_merge_low_conf_fragments(sorted_row, all_tokens))
            current_row = [w]

    sorted_row = sorted(current_row, key=lambda w: w["x"])
    rows.append(_merge_low_conf_fragments(sorted_row, all_tokens))
    return rows


def _merge_low_conf_fragments(high_conf_words, all_tokens):
    """
    Helper privado que recombina fragmentos de números separados.

    Detecta patrones como:
    - "865," + "50-" → "865,50-"
    - "2.553," + "70-" → "2.553,70-"

    Funciona tanto con min_conf=10 como con min_conf=0.
    """
    if len(high_conf_words) < 2:
        return high_conf_words

    merged = []
    i = 0
    skip_indices = set()  # Rastrear qué índices ya fueron merged

    while i < len(high_conf_words):
        if i in skip_indices:
            i += 1
            continue

        current = high_conf_words[i]
        current_text = current["text"]

        # Buscar si el siguiente token puede ser merged
        if i + 1 < len(high_conf_words):
            next_word = high_conf_words[i + 1]
            next_text = next_word["text"]

            # Patrón: "NUM," + "NUM-" (separación entre entero y decimal con signo)
            # Ej: "865," + "50-" → "865,50-"
            if (current_text.endswith(",") and
                next_text.replace("-", "").replace(".", "").isdigit() and
                next_text.endswith("-")):
                # Verificar que están en la misma fila
                if abs(next_word["y"] - current["y"]) <= 5:
                    merged_text = current_text + next_text
                    merged.append({
                        **current,
                        "text": merged_text,
                        "conf": max(current.get("conf", 0), next_word.get("conf", 0))
                    })
                    skip_indices.add(i + 1)  # Saltear el siguiente en la próxima iteración
                    i += 1
                    continue

        # Si no se recombina, agregar el token tal cual
        merged.append(current)
        i += 1

    return merged


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
