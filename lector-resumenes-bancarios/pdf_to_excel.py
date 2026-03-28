#!/usr/bin/env python3
"""
pdf_to_excel.py  —  Convierte extractos bancarios PDF a Excel.

Uso:
    python3 pdf_to_excel.py <archivo.pdf> --profile <calibracion.json>
                            [--lang spa] [--dpi 200] [--out salida.xlsx]
                            [--threshold 160]

Dependencias:
    pip install pdf2image pytesseract openpyxl pillow pdfplumber
    brew install tesseract tesseract-lang poppler
"""

import re
import sys
import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from core.calibration  import CalibrationData, CalibrationIO
from core.pdf_reader   import detect_pdf_type, render_pages
from core.ocr_engine   import run_ocr, group_into_rows
from core.column_parser import (
    clean_amount, build_col_ranges,
    is_transaction_row, row_to_transaction,
    is_saldo_inicial, extract_saldo_inicial,
)
from core.excel_writer import write_excel


# ── Tipos públicos ─────────────────────────────────────────────────────────────

class ConversionError(Exception):
    """Error durante la conversión. Mensaje legible para mostrar en la UI."""


class NoTransactionsError(ConversionError):
    """El pipeline terminó sin detectar ninguna transacción."""


@dataclass
class ConversionResult:
    output_path: str
    transactions: list
    metadata: dict
    warnings: List[str] = field(default_factory=list)


# ── Pipeline principal ─────────────────────────────────────────────────────────

def convert(
    pdf_path: str,
    profile: CalibrationData,
    output_path: str,
    *,
    empresa: str = "",
    lang: str = "spa",
    dpi: int = 200,
    threshold: int = 160,
    method: str = "auto",
    page_from: Optional[int] = None,
    page_to: Optional[int] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> ConversionResult:
    """
    Convierte un PDF bancario a Excel usando el perfil de calibración dado.

    Parámetros:
        pdf_path     — ruta al PDF de entrada
        profile      — CalibrationData cargado desde un JSON de calibración
        output_path  — ruta del Excel a generar
        lang         — idioma OCR (default: "spa")
        dpi          — resolución de renderizado (default: 200)
        threshold    — umbral de binarización OCR (default: 160)
        on_progress  — callback(pagina_actual, total_paginas, mensaje)
                       llamado antes de cada página y al finalizar.
                       Si es None, el progreso se ignora silenciosamente.

    Retorna:
        ConversionResult con el resultado y eventuales advertencias.

    Lanza:
        ConversionError       — error recuperable con mensaje para la UI
        NoTransactionsError   — subclase de ConversionError: OCR corrió pero
                                no encontró ninguna transacción
    """
    def _progress(current: int, total: int, msg: str):
        if on_progress:
            on_progress(current, total, msg)

    pdf_path = str(pdf_path)

    # Construir rangos de columnas desde el perfil
    col_ranges_odd  = _profile_to_col_ranges(profile, parity="odd")
    col_ranges_even = _profile_to_col_ranges(profile, parity="even")

    y_bounds_odd  = profile.limites_y_impares or None
    y_bounds_even = profile.limites_y_pares   or None

    # Determinar método
    from core.pdf_reader import detect_pdf_type, get_pdf_page_count_plumber
    from core.pdf_reader import extract_page_words_plumber
    from core.ocr_engine import group_words_into_rows

    if method == "auto":
        detected = detect_pdf_type(pdf_path)
        use_plumber = (detected == "text")
    elif method == "text":
        use_plumber = True
    else:  # "ocr"
        use_plumber = False

    # Renderizar páginas
    if use_plumber:
        try:
            total = get_pdf_page_count_plumber(pdf_path)
            images = []
        except Exception as exc:
            raise ConversionError(f"No se pudo leer el PDF con pdfplumber: {exc}") from exc
    else:
        try:
            images = render_pages(pdf_path, dpi=dpi)
            total = len(images)
        except Exception as exc:
            raise ConversionError(f"No se pudo renderizar el PDF: {exc}") from exc

    # Aplicar rango de páginas si se especificó
    first_page = max(1, page_from) if page_from else 1
    last_page  = min(total, page_to) if page_to else total
    if first_page > last_page:
        raise ConversionError(
            f"Rango de páginas inválido: {first_page}-{last_page} (el PDF tiene {total} páginas)."
        )

    metodo_label = "extracción de texto" if use_plumber else "OCR"
    rango_label  = f"págs {first_page}–{last_page}" if (first_page != 1 or last_page != total) else f"{total} págs"
    _progress(0, total, f"PDF cargado — {rango_label} · método: {metodo_label}")

    metadata: dict = {}
    transactions: list = []
    warnings: List[str] = []

    for page_num in range(first_page, last_page + 1):
        _progress(page_num, total, f"Procesando página {page_num}/{total}")

        if use_plumber:
            # Para PDFs de texto, detectar el layout real de la página en lugar
            # de asumir alternancia par/impar. Cuando una hoja tiene una sola
            # cara (sin dorso), la alternancia se rompe a partir de esa página.
            # Se detecta el layout mirando la x_pct de la primera fecha DD-MM.
            page_is_even = _detect_page_layout(
                pdf_path, page_num, col_ranges_odd, col_ranges_even
            )
        else:
            # Para OCR no hay coordenadas exactas disponibles de antemano;
            # se mantiene la heurística par/impar por número de página.
            page_is_even = (page_num % 2 == 0)

        active_ranges = col_ranges_even if (page_is_even and col_ranges_even) else col_ranges_odd
        y_bounds = y_bounds_even if (page_is_even and y_bounds_even) else y_bounds_odd
        active_y = y_bounds if (y_bounds and len(y_bounds) == 2) else None

        if use_plumber:
            try:
                word_list = extract_page_words_plumber(
                    pdf_path, page_num, y_bounds=active_y
                )
                # pdfplumber usa puntos PDF (A4 ≈ 842pt), no píxeles.
                # y_tolerance=12 fue diseñado para OCR en píxeles a 200 DPI
                # donde 12px << altura de línea (~40px). En puntos PDF,
                # 12pt ≈ 1 línea completa → fusiona filas adyacentes.
                # Con 3pt tenemos margen suficiente sin cruzar al renglón siguiente.
                rows = group_words_into_rows(word_list, y_tolerance=3)
            except Exception as exc:
                warnings.append(f"Página {page_num}: extracción de texto falló — {exc}")
                continue
        else:
            img = images[page_num - 1]
            page_width = img.width
            try:
                ocr_data = run_ocr(img, lang=lang, threshold=threshold)
            except Exception as exc:
                warnings.append(f"Página {page_num}: OCR falló — {exc}")
                continue

            rows = group_into_rows(
                ocr_data, page_width,
                page_height=img.height,
                y_bounds=active_y,
            )

        # Extraer metadata desde la primera página.
        # Para PDFs seleccionables, los `rows` ya vienen filtrados por y_bounds
        # (que excluye el encabezado del documento). Se hace una pasada separada
        # sin filtro de y_bounds para capturar titular, CUIT y período.
        if page_num == 1:
            if use_plumber:
                try:
                    header_words = extract_page_words_plumber(pdf_path, 1, y_bounds=None)
                    header_rows  = group_words_into_rows(header_words, y_tolerance=3)
                    _extract_metadata(header_rows, metadata)
                    # La fila "SALDO ULTIMO EXTRACTO" queda fuera del y_bounds;
                    # la buscamos en la pasada sin filtro de la página 1.
                    for row in header_rows:
                        if is_saldo_inicial(row):
                            val = extract_saldo_inicial(row)
                            if val and not metadata.get("saldo_inicial"):
                                metadata["saldo_inicial"] = val
                            break
                except Exception:
                    _extract_metadata(rows, metadata)  # fallback
            else:
                _extract_metadata(rows, metadata)

        if active_ranges is None:
            warnings.append(f"Página {page_num}: sin rangos de columna — se omite.")
            continue

        # Extraer saldo inicial y transacciones
        for row in rows:
            if is_saldo_inicial(row):
                val = extract_saldo_inicial(row)
                if val and not metadata.get("saldo_inicial"):
                    metadata["saldo_inicial"] = val
                continue

            if is_transaction_row(row, active_ranges):
                tx = row_to_transaction(row, active_ranges)
                tx["debitos_num"]  = clean_amount(tx.get("debitos",  ""))
                tx["creditos_num"] = clean_amount(tx.get("creditos", ""))
                tx["saldos_num"]   = clean_amount(tx.get("saldos",   ""))
                tx["pagina"]       = page_num
                transactions.append(tx)

    _progress(total, total, f"{metodo_label.capitalize()} completada — {len(transactions)} movimientos")

    if not transactions:
        raise NoTransactionsError(
            "No se detectaron transacciones en el PDF. "
            "Revisá el perfil de calibración o ajustá el umbral OCR."
        )

    columns = list(col_ranges_odd.keys()) if col_ranges_odd else None

    try:
        write_excel(metadata, transactions, output_path, columns=columns, empresa=empresa)
    except Exception as exc:
        raise ConversionError(f"No se pudo escribir el Excel: {exc}") from exc

    return ConversionResult(
        output_path=output_path,
        transactions=transactions,
        metadata=metadata,
        warnings=warnings,
    )


# ── Helpers internos ───────────────────────────────────────────────────────────

def _detect_page_layout(pdf_path: str, page_num: int,
                        col_ranges_odd: dict, col_ranges_even: dict) -> bool:
    """
    Detecta si una página tiene layout 'par' (dorso) o 'impar' (frente)
    mirando la x_pct de la primera fecha DD-MM que aparece en la página.

    La alternancia par/impar por número de página falla cuando alguna hoja
    del extracto tiene una sola cara (sin dorso), lo que desplaza la paridad
    de todas las páginas siguientes.

    Retorna True si la página tiene layout 'par' (even), False si 'impar' (odd).
    Si no hay col_ranges_even definidos, retorna siempre False.
    """
    if not col_ranges_even:
        return False

    from core.pdf_reader import extract_page_words_plumber
    from core.ocr_engine import group_words_into_rows

    try:
        words = extract_page_words_plumber(pdf_path, page_num, y_bounds=None)
    except Exception:
        return (page_num % 2 == 0)  # fallback a heurística

    rows = group_words_into_rows(words, y_tolerance=3)

    # Buscar la x_pct de la primera palabra que sea una fecha DD-MM
    fecha_range_odd  = col_ranges_odd.get("fecha",  (0, 100))
    fecha_range_even = col_ranges_even.get("fecha", (0, 100))
    midpoint_odd  = (fecha_range_odd[0]  + fecha_range_odd[1])  / 2
    midpoint_even = (fecha_range_even[0] + fecha_range_even[1]) / 2
    threshold = (midpoint_odd + midpoint_even) / 2  # punto medio entre ambos centros

    for row in rows:
        for w in row:
            if re.match(r"^\d{2}-\d{2}$", w["text"]):
                return w["x_pct"] < threshold
    return (page_num % 2 == 0)  # fallback si no se encontró ninguna fecha


def _profile_to_col_ranges(profile: CalibrationData, parity: str) -> Optional[dict]:
    """Convierte las ranges del perfil al formato {col: (start%, end%)} que usa el pipeline."""
    source = profile.paginas_impares if parity == "odd" else profile.paginas_pares
    if not source:
        return None
    return {col: (rng[0], rng[1]) for col, rng in source.items()}


def _extract_metadata(rows: list, metadata: dict):
    """Extrae período, CUIT y titular de las primeras filas de la página 1."""
    full_text = " ".join(w["text"] for row in rows for w in row)

    m = re.search(r"(\d{2}-\d{2}-\d{4}\s+AL\s+\d{2}-\d{2}-\d{4})", full_text, re.I)
    if m:
        metadata["periodo"] = m.group(1)

    m = re.search(r"(\d{2}-\d{8}-\d)", full_text)
    if m:
        metadata["cuit"] = m.group(1)

    for row in rows[:20]:
        txt = " ".join(w["text"] for w in row)
        if re.search(r"\b(SRL|S\.R\.L\.|SA|S\.A\.)\b", txt, re.I):
            metadata["titular"] = txt.strip()
            break


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Extracto bancario PDF → Excel")
    parser.add_argument("pdf",        help="Ruta al archivo PDF")
    parser.add_argument("--profile",  required=True, metavar="JSON",
                        help="Perfil de calibración (.json generado por calibrator.py)")
    parser.add_argument("--lang",     default="spa",
                        help="Idioma OCR (default: spa)")
    parser.add_argument("--dpi",      type=int, default=200,
                        help="DPI de renderizado (default: 200)")
    parser.add_argument("--out",      default=None,
                        help="Archivo .xlsx de salida (default: mismo nombre que el PDF)")
    parser.add_argument("--threshold", type=int, default=160,
                        help="Umbral de binarización OCR 0-255 (default: 160)")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"Error: no existe '{pdf_path}'")
        sys.exit(1)

    profile_path = Path(args.profile)
    if not profile_path.exists():
        print(f"Error: no existe el perfil '{profile_path}'")
        sys.exit(1)

    output_path = args.out or str(pdf_path.with_suffix(".xlsx"))

    pdf_type = detect_pdf_type(str(pdf_path))
    if pdf_type == "text":
        print(f"Aviso: '{pdf_path.name}' tiene texto seleccionable — se usará extracción directa.")

    profile = CalibrationIO.load(str(profile_path))
    print(f"Perfil: {profile.banco} / {profile.tipo_documento} / {profile.periodo}")
    print(f"Procesando: {pdf_path.name}")

    def _print_progress(current: int, total: int, msg: str):
        print(f"  [{current}/{total}] {msg}")

    try:
        result = convert(
            str(pdf_path),
            profile,
            output_path,
            lang=args.lang,
            dpi=args.dpi,
            threshold=args.threshold,
            on_progress=_print_progress,
        )
    except NoTransactionsError as exc:
        print(f"\nError: {exc}")
        sys.exit(1)
    except ConversionError as exc:
        print(f"\nError: {exc}")
        sys.exit(1)

    if result.warnings:
        print("\nAdvertencias:")
        for w in result.warnings:
            print(f"  - {w}")

    print(f"\nMetadata: {result.metadata}")
    print(f"Excel guardado en: {result.output_path}")
    print(f"{len(result.transactions)} movimientos exportados.")


if __name__ == "__main__":
    main()
