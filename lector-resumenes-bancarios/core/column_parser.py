"""
core/column_parser.py — Asignación de palabras a columnas y parseo de transacciones.
"""

import re

COLUMNS = ["fecha", "concepto", "f_valor", "comprobante", "origen", "canal", "debitos", "creditos", "saldos"]


def clean_amount(text):
    """Convierte '1.200.000,00-' → -1200000.00 | '1.200.000,00' → 1200000.00

    Tolera números divididos por OCR en dos tokens, ej: '1.309.000, 90-'
    (el OCR divide en '1.309.000,' y '90-' que luego se unen con espacio).
    """
    if not text:
        return None
    text = text.strip()
    negative = text.endswith("-")
    text = text.rstrip("-").strip()
    # El OCR a veces divide un número en varios tokens; eliminar espacios internos
    # para reconstruir el número completo antes de parsearlo.
    text = text.replace(" ", "")
    # Formato Argentina: separador de miles = '.', decimal = ','
    # Si hay múltiples comas (ej: '919,493,90' por ruido OCR), la última es decimal.
    text = text.replace(".", "")
    parts = text.split(",")
    if len(parts) > 2:
        text = "".join(parts[:-1]) + "." + parts[-1]
    elif len(parts) == 2:
        text = parts[0] + "." + parts[1]
    else:
        text = parts[0]
    try:
        value = float(text)
        return -value if negative else value
    except ValueError:
        return None


def build_col_ranges(col_starts):
    """Construye rangos estrictos {col: (start%, end%)} a partir de posiciones de inicio."""
    ordered = sorted(col_starts.items(), key=lambda kv: kv[1])
    ranges = {}
    for i, (col_name, start) in enumerate(ordered):
        end = ordered[i + 1][1] if i + 1 < len(ordered) else 100.0
        ranges[col_name] = (start, end)
    return ranges


def assign_column_strict(x_left_pct, col_ranges):
    """Asigna una palabra al rango de columna en que cae su borde izquierdo."""
    for col_name, (start, end) in col_ranges.items():
        if start <= x_left_pct < end:
            return col_name
    # fallback: columna con start más cercano
    best = min(col_ranges.items(), key=lambda kv: abs(kv[1][0] - x_left_pct))
    return best[0]


def is_transaction_row(row, col_ranges):
    """Retorna True si la fila empieza con DD-MM en la columna fecha."""
    fecha_words = [w for w in row if assign_column_strict(w["x_pct"], col_ranges) == "fecha"]
    if not fecha_words:
        return False
    return bool(re.match(r"^\d{2}-\d{2}$", fecha_words[0]["text"]))


def row_to_transaction(row, col_ranges):
    """Convierte una fila de words a un dict con las columnas de col_ranges."""
    cols = list(col_ranges.keys())
    tx = {c: [] for c in cols}
    for w in row:
        col = assign_column_strict(w["x_pct"], col_ranges)
        tx[col].append(w["text"])

    result = {c: " ".join(tx[c]).strip() for c in cols}

    # Post-proceso: tokens extra en fecha se desbordan al concepto
    # (el header "CONCEPTO" está más a la derecha que donde empieza la data)
    fecha_tokens = result["fecha"].split()
    if fecha_tokens and re.match(r"^\d{2}-\d{2}$", fecha_tokens[0]):
        result["fecha"] = fecha_tokens[0]
        if len(fecha_tokens) > 1:
            overflow = " ".join(fecha_tokens[1:])
            result["concepto"] = (overflow + " " + result["concepto"]).strip()

    return result


def is_saldo_inicial(row):
    """Detecta la fila de saldo inicial del extracto."""
    texts = " ".join(w["text"] for w in row).upper()
    return "SALDO" in texts and ("EXTRACTO" in texts or "ANTERIOR" in texts)


def extract_saldo_inicial(row):
    """Extrae el monto del saldo inicial/anterior."""
    amounts = [clean_amount(w["text"]) for w in row]
    amounts = [a for a in amounts if a is not None]
    return amounts[-1] if amounts else None
