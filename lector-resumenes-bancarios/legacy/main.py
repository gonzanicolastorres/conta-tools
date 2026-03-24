#!/usr/bin/env python3
"""
main.py — Interfaz principal para convertir extractos bancarios PDF a Excel.

Uso:
    python3 main.py
"""

import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from core.calibration import CalibrationFinder, CalibrationIO
from pdf_to_excel import ConversionError, NoTransactionsError, convert

CALIBRATIONS_DIR = Path(__file__).parent / "calibraciones"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Conta Tools — Lector de Extractos")
        self.geometry("660x580")
        self.resizable(False, False)

        self._empresa_var = tk.StringVar()
        self._profile_var = tk.StringVar()
        self._status_var  = tk.StringVar(value="Agregá archivos PDF para comenzar.")
        self._profiles    = []
        self._pdf_files   = []   # lista de Path
        self._last_output_dir = None

        self._build()
        self._load_profiles()

    # ── Construcción de la UI ──────────────────────────────────────────────────

    def _build(self):
        pad = {"padx": 16, "pady": 6}

        # Empresa
        frm_empresa = tk.LabelFrame(self, text="  Empresa  ", pady=6, padx=12)
        frm_empresa.pack(fill="x", **pad)
        tk.Entry(frm_empresa, textvariable=self._empresa_var,
                 width=50).pack(side="left", expand=True, fill="x")
        tk.Label(frm_empresa, text="(nombre de la empresa del cliente)",
                 fg="#888", font=("Helvetica", 9)).pack(side="left", padx=(8, 0))

        # Perfil
        frm_profile = tk.LabelFrame(self, text="  Perfil de calibración  ", pady=6, padx=12)
        frm_profile.pack(fill="x", **pad)
        tk.Button(frm_profile, text="Calibrador…", width=14,
                  command=self._open_calibrator).pack(side="right", padx=(8, 0))
        self._profile_combo = ttk.Combobox(
            frm_profile, textvariable=self._profile_var, state="readonly",
        )
        self._profile_combo.pack(side="left", expand=True, fill="x")

        # Lista de PDFs
        frm_files = tk.LabelFrame(self, text="  Archivos PDF  (prefijo recomendado: AAAA-MM)  ",
                                  pady=6, padx=12)
        frm_files.pack(fill="both", expand=True, **pad)

        list_frame = tk.Frame(frm_files)
        list_frame.pack(fill="both", expand=True)
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")
        self._listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set,
                                   selectmode="extended", height=8,
                                   font=("Courier", 10))
        self._listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self._listbox.yview)

        btn_frame = tk.Frame(frm_files)
        btn_frame.pack(fill="x", pady=(6, 0))
        tk.Button(btn_frame, text="Agregar PDFs…", width=16,
                  command=self._add_pdfs).pack(side="left", padx=(0, 6))
        tk.Button(btn_frame, text="Quitar seleccionados", width=20,
                  command=self._remove_selected).pack(side="left")
        tk.Button(btn_frame, text="Limpiar todo", width=14,
                  command=self._clear_files).pack(side="left", padx=6)

        # Progreso
        frm_progress = tk.LabelFrame(self, text="  Progreso  ", pady=6, padx=12)
        frm_progress.pack(fill="x", **pad)
        self._progress = ttk.Progressbar(frm_progress, mode="determinate")
        self._progress.pack(fill="x")
        tk.Label(frm_progress, textvariable=self._status_var,
                 anchor="w", fg="#555").pack(fill="x", pady=(4, 0))

        # Botones de acción
        frm_actions = tk.Frame(self)
        frm_actions.pack(pady=10)

        self._btn_convert = tk.Button(
            frm_actions, text="Convertir a Excel",
            width=22, pady=6, font=("Helvetica", 11),
            command=self._start_conversion, state="disabled",
        )
        self._btn_convert.pack(side="left", padx=8)

        self._btn_open_dir = tk.Button(
            frm_actions, text="Abrir carpeta",
            width=16, pady=6, font=("Helvetica", 11),
            command=self._open_output_dir, state="disabled",
        )
        self._btn_open_dir.pack(side="left", padx=8)

        self._profile_var.trace_add("write", lambda *_: self._update_convert_btn())

    # ── Perfiles ───────────────────────────────────────────────────────────────

    def _load_profiles(self):
        CALIBRATIONS_DIR.mkdir(parents=True, exist_ok=True)
        self._profiles = CalibrationFinder.find_all(str(CALIBRATIONS_DIR))
        labels = [
            f"{e['data'].banco}  /  {e['data'].tipo_documento}  /  {e['data'].periodo}"
            for e in self._profiles
        ]
        self._profile_combo["values"] = labels
        if labels:
            self._profile_combo.current(0)
        else:
            self._status_var.set("No hay perfiles de calibración. Usá el Calibrador para crear uno.")

    def _selected_profile(self):
        idx = self._profile_combo.current()
        if idx < 0 or idx >= len(self._profiles):
            return None
        return self._profiles[idx]

    # ── Gestión de archivos ────────────────────────────────────────────────────

    def _add_pdfs(self):
        paths = filedialog.askopenfilenames(
            title="Seleccionar extractos PDF",
            filetypes=[("PDF", "*.pdf"), ("Todos", "*.*")],
        )
        added = 0
        for p in paths:
            path = Path(p)
            if path not in self._pdf_files:
                self._pdf_files.append(path)
                self._listbox.insert("end", path.name)
                added += 1
        if added:
            self._update_convert_btn()
            self._status_var.set(f"{len(self._pdf_files)} archivo(s) en cola.")

    def _remove_selected(self):
        for i in reversed(self._listbox.curselection()):
            self._listbox.delete(i)
            self._pdf_files.pop(i)
        self._update_convert_btn()

    def _clear_files(self):
        self._pdf_files.clear()
        self._listbox.delete(0, "end")
        self._update_convert_btn()
        self._btn_open_dir.config(state="disabled")
        self._last_output_dir = None
        self._status_var.set("Agregá archivos PDF para comenzar.")

    def _update_convert_btn(self):
        ready = bool(self._pdf_files) and bool(self._profile_var.get())
        self._btn_convert.config(state="normal" if ready else "disabled")

    # ── Acciones ───────────────────────────────────────────────────────────────

    def _open_calibrator(self):
        subprocess.Popen([sys.executable, str(Path(__file__).parent / "calibrator.py")])

    def _open_output_dir(self):
        if self._last_output_dir:
            subprocess.Popen(["open", str(self._last_output_dir)])

    # ── Conversión ─────────────────────────────────────────────────────────────

    def _start_conversion(self):
        profile_entry = self._selected_profile()
        if not profile_entry:
            messagebox.showwarning("Sin perfil", "Seleccioná un perfil de calibración.")
            return
        if not self._pdf_files:
            messagebox.showwarning("Sin archivos", "Agregá al menos un PDF.")
            return

        empresa = self._empresa_var.get().strip()
        profile = CalibrationIO.load(str(profile_entry["path"]))
        files   = list(self._pdf_files)

        self._btn_convert.config(state="disabled")
        self._btn_open_dir.config(state="disabled")
        self._progress["value"] = 0

        thread = threading.Thread(
            target=self._run_batch,
            args=(files, profile, empresa),
            daemon=True,
        )
        thread.start()

    def _run_batch(self, files, profile, empresa):
        total_files = len(files)
        errors      = []

        for file_idx, pdf_path in enumerate(files):
            output_path = str(pdf_path.with_suffix(".xlsx"))

            def on_progress(current, total_pages, msg, fi=file_idx, fp=pdf_path):
                overall = (fi + current / total_pages) / total_files * 100 if total_pages else 0
                label   = f"[{fi + 1}/{total_files}] {fp.name}  —  {msg}"
                self.after(0, lambda p=overall, l=label: self._update_progress(p, l))

            try:
                convert(
                    str(pdf_path), profile, output_path,
                    empresa=empresa,
                    on_progress=on_progress,
                )
                self._last_output_dir = pdf_path.parent
            except (ConversionError, NoTransactionsError) as exc:
                errors.append(f"{pdf_path.name}: {exc}")
            except Exception as exc:
                errors.append(f"{pdf_path.name}: Error inesperado — {exc}")

        self.after(0, lambda: self._on_batch_done(total_files, errors))

    def _update_progress(self, pct: float, msg: str):
        self._progress["value"] = pct
        self._status_var.set(msg)

    def _on_batch_done(self, total, errors):
        ok = total - len(errors)
        self._progress["value"] = 100
        self._status_var.set(f"✓  {ok}/{total} archivos convertidos.")
        self._btn_convert.config(state="normal")

        if self._last_output_dir:
            self._btn_open_dir.config(state="normal")

        if errors:
            messagebox.showwarning(
                "Conversión con errores",
                f"{len(errors)} archivo(s) fallaron:\n\n" + "\n".join(errors),
            )


if __name__ == "__main__":
    App().mainloop()
