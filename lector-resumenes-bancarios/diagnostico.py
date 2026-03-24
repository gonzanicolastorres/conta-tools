#!/usr/bin/env python3
"""
diagnostico.py — Muestra las primeras N filas detectadas como transacciones
para verificar que la calibración está funcionando correctamente.

Uso:
    python3 diagnostico.py <archivo.pdf> --profile <calibracion.json> [--paginas 1-3] [--filas 20]
"""

import argparse
from pathlib import Path
from core.calibration  import CalibrationIO
from core.pdf_reader   import render_pages
from core.ocr_engine   import run_ocr, group_into_rows
from core.column_parser import clean_amount, is_transaction_row, row_to_transaction, is_saldo_inicial


def diagnosticar(pdf_path, profile, paginas=None, max_filas=20):
    images = render_pages(pdf_path, dpi=200)
    total  = len(images)
    print(f"PDF: {Path(pdf_path).name}  —  {total} páginas\n")

    if paginas:
        indices = [p - 1 for p in paginas if 0 < p <= total]
    else:
        indices = list(range(total))

    count = 0
    for idx in indices:
        page_num = idx + 1
        img      = images[idx]
        is_even  = (page_num % 2 == 0)

        col_ranges = (
            {col: (rng[0], rng[1]) for col, rng in profile.paginas_pares.items()}
            if is_even else
            {col: (rng[0], rng[1]) for col, rng in profile.paginas_impares.items()}
        )
        y_bounds = (
            profile.limites_y_pares if (is_even and profile.limites_y_pares)
            else profile.limites_y_impares
        ) or None
        active_y = y_bounds if (y_bounds and len(y_bounds) == 2) else None

        print(f"{'─'*80}")
        print(f"Página {page_num}  ({'par' if is_even else 'impar'})  "
              f"y_bounds={[f'{v:.1f}%' for v in active_y] if active_y else 'ninguno'}")
        print(f"{'─'*80}")

        ocr_data = run_ocr(img, threshold=160)
        rows     = group_into_rows(ocr_data, img.width, page_height=img.height, y_bounds=active_y)

        tx_en_pagina = 0
        for row in rows:
            if is_saldo_inicial(row):
                txt = " ".join(w["text"] for w in row)
                print(f"  [SALDO INICIAL] {txt}")
                continue

            if is_transaction_row(row, col_ranges):
                if count >= max_filas:
                    continue
                tx = row_to_transaction(row, col_ranges)
                print(
                    f"  {tx.get('fecha',''):<8} "
                    f"{tx.get('concepto','')[:30]:<30} "
                    f"deb={tx.get('debitos',''):<14} "
                    f"cred={tx.get('creditos',''):<14} "
                    f"saldo={tx.get('saldos','')}"
                )
                count      += 1
                tx_en_pagina += 1

        print(f"  → {tx_en_pagina} transacciones detectadas en esta página")
        print()

    print(f"Total mostradas: {count} (limitado a {max_filas})")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--paginas", default=None,
                        help="Páginas a inspeccionar, ej: 1,2,3 (default: todas)")
    parser.add_argument("--filas", type=int, default=20,
                        help="Máximo de filas a mostrar (default: 20)")
    args = parser.parse_args()

    paginas = [int(p) for p in args.paginas.split(",")] if args.paginas else None
    profile = CalibrationIO.load(args.profile)
    diagnosticar(args.pdf, profile, paginas=paginas, max_filas=args.filas)


if __name__ == "__main__":
    main()
