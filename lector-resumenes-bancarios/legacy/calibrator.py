#!/usr/bin/env python3
"""
calibrator.py — Wizard interactivo para calibrar columnas de extractos bancarios.

Genera un archivo JSON reutilizable por pdf_to_excel.py.

Uso:
    python3 calibrator.py

Dependencias:
    pip install pdf2image pillow pdfplumber
    (tkinter viene incluido en Python estándar)
"""

import re
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from typing import Optional, Callable, List

try:
    from pdf2image import convert_from_path
    from PIL import Image, ImageTk
except ImportError as e:
    print(f"Error: {e}\nInstalar con: pip install pdf2image pillow")
    raise SystemExit(1)

from core.calibration  import CalibrationData, CalibrationIO, CalibrationFinder
from core.pdf_reader   import detect_pdf_type
from core.ocr_engine   import run_ocr, group_into_rows
from core.column_parser import build_col_ranges, is_transaction_row, row_to_transaction

CALIBRATIONS_DIR = Path(__file__).parent / "calibraciones"

# ══════════════════════════════════════════════════════════════════════════════
# WIDGET: CANVAS CON ZOOM Y MARCADO DE LÍNEAS
# ══════════════════════════════════════════════════════════════════════════════

ZONE_COLORS = [
    "#BBDEFB", "#C8E6C9", "#FFF9C4", "#FFE0B2",
    "#E1BEE7", "#B2EBF2", "#FFCDD2", "#DCEDC8", "#F8BBD0",
]


class ZoomableImageCanvas(tk.Frame):
    """
    Canvas scrolleable con soporte de zoom y marcado interactivo de
    líneas verticales. Las líneas se almacenan como porcentajes del
    ancho original (independiente del zoom).
    """

    ZOOM_LEVELS = [0.25, 0.33, 0.5, 0.67, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0]
    DEFAULT_ZOOM = 5   # índice → 1.0x
    LINE_COLOR = "#D32F2F"
    LINE_WIDTH = 2

    def __init__(self, parent, on_lines_changed: Optional[Callable] = None, **kwargs):
        super().__init__(parent, **kwargs)
        self._orig_image: Optional[Image.Image] = None
        self._tk_image: Optional[ImageTk.PhotoImage] = None
        self._zoom_idx: int = self.DEFAULT_ZOOM
        self._line_pcts: List[float] = []
        self._y_lines: List[float] = []
        self._column_names: List[str] = []
        self._on_lines_changed = on_lines_changed

        self._build_toolbar()
        self._build_canvas()

    def _build_toolbar(self):
        bar = tk.Frame(self, bg="#ECEFF1", pady=4)
        bar.pack(fill="x")

        tk.Label(bar, text="Modo:", bg="#ECEFF1").pack(side="left", padx=(8, 2))
        self._mode_var = tk.StringVar(value="x")
        tk.Radiobutton(bar, text="┋ Columnas (X)", variable=self._mode_var,
                       value="x", bg="#ECEFF1").pack(side="left")
        tk.Radiobutton(bar, text="═ Filas (Y)", variable=self._mode_var,
                       value="y", bg="#ECEFF1").pack(side="left", padx=(0, 6))

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6, pady=2)

        tk.Label(bar, text="Zoom:", bg="#ECEFF1").pack(side="left", padx=(8, 2))
        tk.Button(bar, text="−", width=2, command=self.zoom_out,
                  relief="groove").pack(side="left")
        self._lbl_zoom = tk.Label(bar, text="100%", width=6, bg="#ECEFF1",
                                  font=("Helvetica", 10, "bold"))
        self._lbl_zoom.pack(side="left")
        tk.Button(bar, text="+", width=2, command=self.zoom_in,
                  relief="groove").pack(side="left")

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=12, pady=2)

        tk.Button(bar, text="↩ Deshacer", command=self.undo_last,
                  relief="groove").pack(side="left")
        tk.Button(bar, text="✕ Limpiar todo", command=self.clear_all,
                  relief="groove").pack(side="left", padx=4)

        self._lbl_status = tk.Label(bar, text="", bg="#ECEFF1",
                                    fg="#555", font=("Helvetica", 10))
        self._lbl_status.pack(side="left", padx=16)

    def _build_canvas(self):
        container = tk.Frame(self)
        container.pack(fill="both", expand=True)
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        self._canvas = tk.Canvas(container, bg="#424242", cursor="crosshair",
                                 highlightthickness=0)
        vbar = ttk.Scrollbar(container, orient="vertical",   command=self._canvas.yview)
        hbar = ttk.Scrollbar(container, orient="horizontal", command=self._canvas.xview)
        self._canvas.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)

        self._canvas.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")

        self._canvas.bind("<Button-1>", self._on_left_click)
        self._canvas.bind("<Button-2>", self._on_right_click)   # macOS
        self._canvas.bind("<Button-3>", self._on_right_click)   # Windows / Linux
        self._canvas.bind("<MouseWheel>", self._on_mousewheel)
        self._canvas.bind("<Button-4>", self._on_mousewheel)
        self._canvas.bind("<Button-5>", self._on_mousewheel)

    # ── Zoom ──────────────────────────────────────────────────────────────────

    def _zoom(self) -> float:
        return self.ZOOM_LEVELS[self._zoom_idx]

    def zoom_in(self):
        if self._zoom_idx < len(self.ZOOM_LEVELS) - 1:
            self._zoom_idx += 1
            self._redraw()

    def zoom_out(self):
        if self._zoom_idx > 0:
            self._zoom_idx -= 1
            self._redraw()

    def _on_mousewheel(self, event):
        if event.num == 4 or getattr(event, "delta", 0) > 0:
            self.zoom_in()
        else:
            self.zoom_out()

    # ── Renderizado ───────────────────────────────────────────────────────────

    def _redraw(self):
        if self._orig_image is None:
            return
        zoom = self._zoom()
        self._lbl_zoom.config(text=f"{int(zoom * 100)}%")
        w = int(self._orig_image.width  * zoom)
        h = int(self._orig_image.height * zoom)
        resized = self._orig_image.resize((w, h), Image.LANCZOS)
        self._tk_image = ImageTk.PhotoImage(resized)
        self._canvas.delete("all")
        self._canvas.create_image(0, 0, anchor="nw", image=self._tk_image, tags="image")
        self._canvas.configure(scrollregion=(0, 0, w, h))
        self._draw_zones(w, h)
        self._draw_lines(h)
        self._update_status()

    def _draw_zones(self, canvas_w, canvas_h):
        boundaries = [0.0] + self._line_pcts + [100.0]
        for i in range(len(boundaries) - 1):
            x0 = int(boundaries[i]     / 100 * canvas_w)
            x1 = int(boundaries[i + 1] / 100 * canvas_w)
            col_name = self._column_names[i] if i < len(self._column_names) else f"col {i + 1}"
            color = ZONE_COLORS[i % len(ZONE_COLORS)]
            self._canvas.create_rectangle(x0, 0, x1, 40,
                                          fill=color, outline="", tags="zone")
            cx = (x0 + x1) // 2
            self._canvas.create_text(cx, 18, text=col_name,
                                     font=("Helvetica", 9, "bold"),
                                     fill="#1A237E", tags="zone_label")

    def _draw_lines(self, canvas_h):
        zoom = self._zoom()
        for pct in self._line_pcts:
            x = int(pct / 100 * self._orig_image.width * zoom)
            self._canvas.create_line(x, 0, x, canvas_h,
                                     fill=self.LINE_COLOR, width=self.LINE_WIDTH,
                                     dash=(6, 3), tags="line")
            self._canvas.create_text(x + 4, 36, text=f"{pct:.1f}%",
                                     anchor="w", font=("Helvetica", 8),
                                     fill=self.LINE_COLOR, tags="line_label")

        canvas_w = int(self._orig_image.width * zoom)
        for pct in self._y_lines:
            y = int(pct / 100 * self._orig_image.height * zoom)
            self._canvas.create_line(0, y, canvas_w, y,
                                     fill="#2E7D32", width=int(self.LINE_WIDTH * 1.5),
                                     dash=(8, 4), tags="line_y")
            self._canvas.create_text(16, y - 10, text=f"Top/Bottom: {pct:.1f}%",
                                     anchor="w", font=("Helvetica", 9, "bold"),
                                     fill="#2E7D32", tags="line_label_y")

    # ── Interacción ───────────────────────────────────────────────────────────

    def _canvas_x_to_pct(self, event_x):
        canvas_x = self._canvas.canvasx(event_x)
        pct = canvas_x / (self._orig_image.width * self._zoom()) * 100
        return max(0.1, min(99.9, pct))

    def _canvas_y_to_pct(self, event_y):
        canvas_y = self._canvas.canvasy(event_y)
        pct = canvas_y / (self._orig_image.height * self._zoom()) * 100
        return max(0.1, min(99.9, pct))

    def _on_left_click(self, event):
        if self._orig_image is None:
            return
        if self._mode_var.get() == "x":
            pct = self._canvas_x_to_pct(event.x)
            if any(abs(pct - p) < 0.8 for p in self._line_pcts):
                return
            self._line_pcts.append(pct)
            self._line_pcts.sort()
        else:
            if len(self._y_lines) >= 2:
                messagebox.showwarning("Límite", "Solo podés marcar 2 límites horizontales (Top y Bottom).")
                return
            pct = self._canvas_y_to_pct(event.y)
            if any(abs(pct - p) < 0.8 for p in self._y_lines):
                return
            self._y_lines.append(pct)
            self._y_lines.sort()

        self._redraw()
        self._notify()

    def _on_right_click(self, event):
        if self._mode_var.get() == "x":
            if not self._line_pcts:
                return
            pct = self._canvas_x_to_pct(event.x)
            closest = min(self._line_pcts, key=lambda p: abs(p - pct))
            if abs(closest - pct) < 3.0:
                self._line_pcts.remove(closest)
        else:
            if not self._y_lines:
                return
            pct = self._canvas_y_to_pct(event.y)
            closest = min(self._y_lines, key=lambda p: abs(p - pct))
            if abs(closest - pct) < 3.0:
                self._y_lines.remove(closest)

        self._redraw()
        self._notify()

    def _update_status(self):
        n = len(self._line_pcts)
        needed = len(self._column_names) - 1 if self._column_names else "?"
        color = "#2E7D32" if (self._column_names and n == needed) else "#BF360C"
        self._lbl_status.config(text=f"{n} / {needed} límites marcados", fg=color)

    def _notify(self):
        if self._on_lines_changed:
            self._on_lines_changed(self._line_pcts)

    # ── API pública ───────────────────────────────────────────────────────────

    def load_image(self, image: Image.Image):
        self._orig_image = image
        self._line_pcts  = []
        self._y_lines    = []
        self._zoom_idx   = self.DEFAULT_ZOOM
        self._redraw()

    def set_column_names(self, names: List[str]):
        self._column_names = list(names)
        self._redraw()

    def set_line_pcts(self, pcts: List[float]):
        self._line_pcts = sorted(pcts)
        self._redraw()

    def get_line_pcts(self) -> List[float]:
        return list(self._line_pcts)

    def set_y_lines(self, pcts: List[float]):
        self._y_lines = sorted(pcts)
        self._redraw()

    def get_y_lines(self) -> List[float]:
        return list(self._y_lines)

    def undo_last(self):
        if self._mode_var.get() == "x" and self._line_pcts:
            self._line_pcts.pop()
        elif self._mode_var.get() == "y" and self._y_lines:
            self._y_lines.pop()
        else:
            return
        self._redraw()
        self._notify()

    def clear_all(self):
        if self._mode_var.get() == "x":
            self._line_pcts = []
        else:
            self._y_lines = []
        self._redraw()
        self._notify()

    def is_complete(self) -> bool:
        if not self._column_names:
            return False
        return len(self._line_pcts) == len(self._column_names) - 1


# ══════════════════════════════════════════════════════════════════════════════
# BASE DE PASOS DEL WIZARD
# ══════════════════════════════════════════════════════════════════════════════

class WizardStep(tk.Frame):
    """Clase base para cada paso del wizard."""

    def __init__(self, parent, data: CalibrationData, **kwargs):
        super().__init__(parent, bg="#ECEFF1", **kwargs)
        self.data = data
        self._on_next: Optional[Callable] = None
        self._on_back: Optional[Callable] = None

    def set_navigation(self, on_next: Optional[Callable], on_back: Optional[Callable]):
        self._on_next = on_next
        self._on_back = on_back

    def on_enter(self):
        """Llamado cada vez que el paso se hace visible."""

    def can_proceed(self) -> bool:
        return True

    def _nav_bar(self, back_label="← Atrás", next_label="Siguiente →",
                 show_next=True) -> tk.Frame:
        bar = tk.Frame(self, bg="#CFD8DC", pady=6)
        bar.pack(fill="x", side="bottom")
        tk.Button(bar, text=back_label, width=14,
                  command=lambda: self._on_back() if self._on_back else None).pack(side="left", padx=12)
        if show_next:
            tk.Button(bar, text=next_label, width=14,
                      bg="#1565C0", fg="black",
                      command=self._safe_next).pack(side="right", padx=12)
        return bar

    def _safe_next(self):
        if self.can_proceed() and self._on_next:
            self._on_next()


# ══════════════════════════════════════════════════════════════════════════════
# PANTALLA INICIAL: LISTA DE PERFILES
# ══════════════════════════════════════════════════════════════════════════════

class StepHome(WizardStep):
    """
    Pantalla de inicio: muestra los perfiles guardados en calibraciones/
    y permite crear uno nuevo o editar uno existente.
    """

    def __init__(self, parent, data: CalibrationData,
                 on_new: Callable, on_edit: Callable, **kwargs):
        super().__init__(parent, data, **kwargs)
        self._on_new  = on_new
        self._on_edit = on_edit
        self._profiles: List[dict] = []
        self._build()

    def _build(self):
        tk.Label(self, text="Calibrador de Extractos Bancarios",
                 font=("Helvetica", 17, "bold"), bg="#ECEFF1").pack(pady=(28, 4))
        tk.Label(self, text="Perfiles de calibración guardados:",
                 bg="#ECEFF1", fg="#546E7A",
                 font=("Helvetica", 11)).pack(pady=(12, 4))

        # ── Tabla de perfiles ─────────────────────────────────────────────────
        tbl_frame = tk.Frame(self, bg="#ECEFF1")
        tbl_frame.pack(fill="both", expand=True, padx=48, pady=4)

        cols = ("banco", "tipo", "periodo", "archivo")
        self._tree = ttk.Treeview(tbl_frame, columns=cols, show="headings", height=12)
        for col, label, width in [
            ("banco",   "Banco",    160),
            ("tipo",    "Tipo",     160),
            ("periodo", "Período",   90),
            ("archivo", "Archivo",  280),
        ]:
            self._tree.heading(col, text=label)
            self._tree.column(col, width=width, anchor="w")

        vsb = ttk.Scrollbar(tbl_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")

        # ── Botones de acción ─────────────────────────────────────────────────
        btn_frame = tk.Frame(self, bg="#ECEFF1")
        btn_frame.pack(pady=16)

        tk.Button(btn_frame, text="+ Nueva calibración",
                  bg="#1565C0", fg="black", width=22, pady=6,
                  font=("Helvetica", 11), command=self._on_new).pack(side="left", padx=8)

        tk.Button(btn_frame, text="✏ Editar seleccionada",
                  width=22, pady=6,
                  font=("Helvetica", 11), command=self._edit_selected).pack(side="left", padx=8)

        tk.Button(btn_frame, text="✕ Eliminar seleccionada",
                  fg="#C62828", width=22, pady=6,
                  font=("Helvetica", 11), command=self._delete_selected).pack(side="left", padx=8)

    def on_enter(self):
        self._reload_profiles()

    def _reload_profiles(self):
        self._tree.delete(*self._tree.get_children())
        self._profiles = []
        if CALIBRATIONS_DIR.exists():
            self._profiles = CalibrationFinder.find_all(str(CALIBRATIONS_DIR))
        for entry in self._profiles:
            d = entry["data"]
            self._tree.insert("", "end", values=(
                d.banco, d.tipo_documento, d.periodo, entry["path"].name
            ))

    def _selected_entry(self):
        sel = self._tree.selection()
        if not sel:
            messagebox.showinfo("Sin selección", "Seleccioná un perfil de la lista.")
            return None
        idx = self._tree.index(sel[0])
        return self._profiles[idx]

    def _edit_selected(self):
        entry = self._selected_entry()
        if entry:
            self._on_edit(entry["data"], str(entry["path"]))

    def _delete_selected(self):
        entry = self._selected_entry()
        if not entry:
            return
        d = entry["data"]
        name = f"{d.banco} / {d.tipo_documento} / {d.periodo}"
        if messagebox.askyesno("Confirmar eliminación",
                               f"¿Eliminar el perfil '{name}'?"):
            try:
                entry["path"].unlink()
                self._reload_profiles()
            except Exception as exc:
                messagebox.showerror("Error", str(exc))


# ══════════════════════════════════════════════════════════════════════════════
# PASO 1: DATOS GENERALES Y COLUMNAS
# ══════════════════════════════════════════════════════════════════════════════

class StepSetup(WizardStep):
    """El usuario define: banco, tipo, período, PDF y lista de columnas."""

    def __init__(self, parent, data: CalibrationData, **kwargs):
        super().__init__(parent, data, **kwargs)
        self._banco_var   = tk.StringVar(value=data.banco)
        self._tipo_var    = tk.StringVar(value=data.tipo_documento)
        self._periodo_var = tk.StringVar(value=data.periodo)
        self._pdf_var     = tk.StringVar(value=data.pdf_path)
        self._build()

    def _build(self):
        tk.Label(self, text="Configuración del perfil",
                 font=("Helvetica", 16, "bold"), bg="#ECEFF1").pack(pady=(24, 4))
        tk.Label(self,
                 text="Ingresá los datos del banco y definí las columnas del extracto.",
                 bg="#ECEFF1", fg="#546E7A").pack()

        form = tk.LabelFrame(self, text="  Información general  ",
                             bg="#ECEFF1", pady=8, padx=12)
        form.pack(fill="x", padx=32, pady=12)

        fields = [
            ("Banco:",        self._banco_var,   "ej: icbc"),
            ("Tipo doc.:",    self._tipo_var,    "ej: cuenta_corriente"),
            ("Período:",      self._periodo_var, "formato yyyy-mm, ej: 2025-06"),
        ]
        for label, var, placeholder in fields:
            row = tk.Frame(form, bg="#ECEFF1")
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label, width=12, anchor="e",
                     bg="#ECEFF1").pack(side="left")
            tk.Entry(row, textvariable=var, width=30).pack(side="left", padx=6)
            tk.Label(row, text=placeholder, fg="#90A4AE",
                     bg="#ECEFF1", font=("Helvetica", 9)).pack(side="left")

        pdf_row = tk.Frame(form, bg="#ECEFF1")
        pdf_row.pack(fill="x", pady=3)
        tk.Label(pdf_row, text="PDF:", width=12, anchor="e",
                 bg="#ECEFF1").pack(side="left")
        tk.Entry(pdf_row, textvariable=self._pdf_var,
                 width=30, state="readonly").pack(side="left", padx=6)
        tk.Button(pdf_row, text="Elegir…", command=self._pick_pdf).pack(side="left")

        # ── Lista de columnas ─────────────────────────────────────────────────
        col_frame = tk.LabelFrame(self, text="  Columnas  ",
                                  bg="#ECEFF1", pady=8, padx=12)
        col_frame.pack(fill="both", expand=True, padx=32)

        list_frame = tk.Frame(col_frame, bg="#ECEFF1")
        list_frame.pack(fill="both", expand=True)

        self._listbox = tk.Listbox(list_frame, height=8, selectmode="single",
                                   font=("Courier", 11), activestyle="dotbox")
        scroll = ttk.Scrollbar(list_frame, command=self._listbox.yview)
        self._listbox.configure(yscrollcommand=scroll.set)
        self._listbox.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")

        for col in self.data.columnas:
            self._listbox.insert("end", col)

        btn_col = tk.Frame(col_frame, bg="#ECEFF1")
        btn_col.pack(side="right", padx=(8, 0), pady=4)
        for text, cmd in [
            ("↑ Subir",   self._move_up),
            ("↓ Bajar",   self._move_down),
            ("+ Agregar", self._add_column),
            ("✕ Quitar",  self._del_column),
        ]:
            tk.Button(btn_col, text=text, width=12, command=cmd).pack(pady=2)

        self._nav_bar(next_label="Siguiente →")

    def on_enter(self):
        # Sincronizar campos si los datos fueron cargados externamente (edición)
        self._banco_var.set(self.data.banco)
        self._tipo_var.set(self.data.tipo_documento)
        self._periodo_var.set(self.data.periodo)
        self._pdf_var.set(self.data.pdf_path)
        self._listbox.delete(0, "end")
        for col in self.data.columnas:
            self._listbox.insert("end", col)

    def _pick_pdf(self):
        path = filedialog.askopenfilename(
            title="Seleccionar extracto PDF",
            filetypes=[("PDF", "*.pdf"), ("Todos", "*.*")]
        )
        if path:
            self._pdf_var.set(path)

    def _move_up(self):
        sel = self._listbox.curselection()
        if not sel or sel[0] == 0:
            return
        i = sel[0]
        val = self._listbox.get(i)
        self._listbox.delete(i)
        self._listbox.insert(i - 1, val)
        self._listbox.selection_set(i - 1)

    def _move_down(self):
        sel = self._listbox.curselection()
        if not sel or sel[0] >= self._listbox.size() - 1:
            return
        i = sel[0]
        val = self._listbox.get(i)
        self._listbox.delete(i)
        self._listbox.insert(i + 1, val)
        self._listbox.selection_set(i + 1)

    def _add_column(self):
        win = tk.Toplevel(self)
        win.title("Nueva columna")
        win.resizable(False, False)
        win.grab_set()
        tk.Label(win, text="Nombre de la columna:").pack(padx=16, pady=(12, 4))
        var = tk.StringVar()
        entry = tk.Entry(win, textvariable=var, width=24)
        entry.pack(padx=16)
        entry.focus_set()

        def confirm(_event=None):
            name = var.get().strip()
            if name:
                self._listbox.insert("end", name)
            win.destroy()

        entry.bind("<Return>", confirm)
        tk.Button(win, text="Agregar", command=confirm).pack(pady=10)

    def _del_column(self):
        sel = self._listbox.curselection()
        if sel:
            self._listbox.delete(sel[0])

    def can_proceed(self) -> bool:
        if not self._banco_var.get().strip():
            messagebox.showwarning("Falta dato", "Ingresá el nombre del banco.")
            return False
        if not self._tipo_var.get().strip():
            messagebox.showwarning("Falta dato", "Ingresá el tipo de documento.")
            return False
        periodo = self._periodo_var.get().strip()
        if not re.match(r"^\d{4}-\d{2}$", periodo):
            messagebox.showwarning("Período inválido",
                                   "El período debe tener formato yyyy-mm (ej: 2025-06).")
            return False
        if not self._pdf_var.get():
            messagebox.showwarning("Falta PDF", "Seleccioná el PDF a calibrar.")
            return False
        if self._listbox.size() < 2:
            messagebox.showwarning("Pocas columnas", "Definí al menos 2 columnas.")
            return False
        self.data.banco          = self._banco_var.get().strip()
        self.data.tipo_documento = self._tipo_var.get().strip()
        self.data.periodo        = periodo
        self.data.pdf_path       = self._pdf_var.get()
        self.data.columnas       = list(self._listbox.get(0, "end"))
        return True


# ══════════════════════════════════════════════════════════════════════════════
# PASO 2: DETECCIÓN DE TIPO DE PDF
# ══════════════════════════════════════════════════════════════════════════════

class StepDetect(WizardStep):
    """
    Detecta si el PDF tiene texto seleccionable o es escaneado.
    - Escaneado: avanza automáticamente.
    - Con texto: muestra advertencia y espera confirmación.
    """

    def __init__(self, parent, data: CalibrationData, **kwargs):
        super().__init__(parent, data, **kwargs)
        self._build()

    def _build(self):
        tk.Label(self, text="Detección de tipo de PDF",
                 font=("Helvetica", 16, "bold"), bg="#ECEFF1").pack(pady=(40, 8))

        self._icon_lbl = tk.Label(self, text="", font=("Helvetica", 40), bg="#ECEFF1")
        self._icon_lbl.pack(pady=8)

        self._result_lbl = tk.Label(self, text="Analizando…",
                                    font=("Helvetica", 13), bg="#ECEFF1")
        self._result_lbl.pack(pady=4)

        self._detail_lbl = tk.Label(self, text="", bg="#ECEFF1", fg="#546E7A",
                                    wraplength=520, justify="center")
        self._detail_lbl.pack(pady=8)

        self._nav_bar()

    def on_enter(self):
        self._icon_lbl.config(text="⏳", fg="#546E7A")
        self._result_lbl.config(text="Analizando el PDF…")
        self._detail_lbl.config(text="")
        # Correr la detección en un hilo para no bloquear la UI
        threading.Thread(target=self._detect, daemon=True).start()

    def _detect(self):
        try:
            pdf_type = detect_pdf_type(self.data.pdf_path)
        except Exception as exc:
            self.after(0, lambda: self._show_error(str(exc)))
            return
        self.after(0, lambda: self._show_result(pdf_type))

    def _show_result(self, pdf_type: str):
        if pdf_type == "scanned":
            self._icon_lbl.config(text="✓", fg="#2E7D32")
            self._result_lbl.config(text="PDF escaneado — ideal para calibración OCR.",
                                    fg="#2E7D32")
            self._detail_lbl.config(text="No se detectó texto seleccionable. "
                                         "Podés continuar con la calibración normalmente.")
            # Avanzar automáticamente después de 1.5 segundos
            self.after(1500, self._safe_next)
        else:
            self._icon_lbl.config(text="⚠", fg="#E65100")
            self._result_lbl.config(text="PDF con texto seleccionable.",
                                    fg="#E65100")
            self._detail_lbl.config(
                text="Este PDF tiene texto que puede extraerse directamente, "
                     "sin necesidad de OCR.\n\n"
                     "Podés continuar con la calibración para usarlo como respaldo "
                     "en modo OCR, o cancelar y usar extracción directa."
            )

    def _show_error(self, msg: str):
        self._icon_lbl.config(text="⚠", fg="#B71C1C")
        self._result_lbl.config(text="No se pudo analizar el PDF.", fg="#B71C1C")
        self._detail_lbl.config(text=msg)


# ══════════════════════════════════════════════════════════════════════════════
# PASO 3 / 5: MARCAR LÍMITES EN UNA PÁGINA
# ══════════════════════════════════════════════════════════════════════════════

class StepMarkPage(WizardStep):
    """Muestra una página del PDF y permite marcar los límites de columnas."""

    def __init__(self, parent, data: CalibrationData, parity: str, **kwargs):
        super().__init__(parent, data, **kwargs)
        self.parity = parity
        self._current_page: int = 1 if parity == "odd" else 2
        self._build()

    def _build(self):
        parity_label = ("Páginas impares  (1, 3, 5…)"
                        if self.parity == "odd"
                        else "Páginas pares  (2, 4, 6…)")
        tk.Label(self, text=f"Marcar columnas — {parity_label}",
                 font=("Helvetica", 14, "bold"), bg="#ECEFF1").pack(pady=(12, 2))
        tk.Label(self,
                 text="  Clic izquierdo → agregar límite     "
                      "Clic derecho → eliminar límite     Rueda → zoom  ",
                 bg="#ECEFF1", fg="#546E7A").pack()

        # Selector de página eliminado para simplificar - solo trabajamos con default
        self._page_var = tk.IntVar(value=self._current_page)

        self._image_canvas = ZoomableImageCanvas(self)
        self._image_canvas.pack(fill="both", expand=True, padx=8, pady=6)
        self._nav_bar()

    def on_enter(self):
        self._image_canvas.set_column_names(self.data.columnas)
        self._load_page(self._current_page)

        # Restaurar líneas previas si ya estaban calibradas
        prev_x = (self.data.paginas_impares if self.parity == "odd"
                  else self.data.paginas_pares)
        if prev_x:
            pcts = [v[0] for v in list(prev_x.values())[1:]]
            self._image_canvas.set_line_pcts(pcts)
            
        prev_y = (self.data.limites_y_impares if self.parity == "odd" 
                  else self.data.limites_y_pares)
        if prev_y:
            self._image_canvas.set_y_lines(prev_y)

    def _load_page(self, page_num: int):
        if not self.data.pdf_path:
            return
        try:
            images = convert_from_path(
                self.data.pdf_path, dpi=150,
                first_page=page_num, last_page=page_num
            )
            self._image_canvas.load_image(images[0])
        except Exception as exc:
            messagebox.showerror("Error al cargar PDF",
                                 f"No se pudo renderizar la página {page_num}:\n{exc}")

    def _change_page(self):
        self._current_page = self._page_var.get()
        self._load_page(self._current_page)

    def can_proceed(self) -> bool:
        if not self._image_canvas.is_complete():
            n = len(self.data.columnas) - 1
            messagebox.showwarning(
                "Incompleto",
                f"Necesitás marcar exactamente {n} líneas "
                f"para definir {len(self.data.columnas)} columnas verticales.\n\n"
                f"Líneas actuales: {len(self._image_canvas.get_line_pcts())}"
            )
            return False
            
        y_lines = self._image_canvas.get_y_lines()
        if len(y_lines) == 1:
            messagebox.showwarning(
                "Límites Y",
                "Marcaste solo 1 límite horizontal. Debés marcar 2 (Top y Bottom) o ninguno."
            )
            return False
            
        self.data.set_ranges(self._image_canvas.get_line_pcts(), self.parity)
        
        if self.parity == "odd":
            self.data.limites_y_impares = y_lines
        else:
            self.data.limites_y_pares = y_lines
            
        return True


# ══════════════════════════════════════════════════════════════════════════════
# PASO 4: CONFIRMAR PARIDAD DE PÁGINAS
# ══════════════════════════════════════════════════════════════════════════════

class StepParityChoice(WizardStep):
    """Pregunta si las páginas pares tienen el mismo layout que las impares."""

    def __init__(self, parent, data: CalibrationData,
                 on_same: Callable, on_different: Callable, **kwargs):
        super().__init__(parent, data, **kwargs)
        self._on_same      = on_same
        self._on_different = on_different
        self._build()

    def _build(self):
        tk.Label(self, text="¿Las páginas pares tienen el mismo layout?",
                 font=("Helvetica", 15, "bold"), bg="#ECEFF1").pack(pady=(60, 8))
        tk.Label(self,
                 text="En muchos extractos bancarios las páginas pares tienen\n"
                      "márgenes espejo: las columnas aparecen desplazadas\n"
                      "horizontalmente respecto de las páginas impares.",
                 bg="#ECEFF1", fg="#546E7A", justify="center").pack(pady=8)

        btn_frame = tk.Frame(self, bg="#ECEFF1")
        btn_frame.pack(pady=28)

        tk.Button(btn_frame,
                  text="✓   Mismo layout — no necesito calibrar pares",
                  bg="#2E7D32", fg="black", width=46, pady=8,
                  font=("Helvetica", 11), command=self._on_same).pack(pady=6)

        tk.Button(btn_frame,
                  text="≠   Layout diferente — quiero calibrar pares también",
                  bg="#1565C0", fg="black", width=46, pady=8,
                  font=("Helvetica", 11), command=self._on_different).pack(pady=6)

        tk.Button(self, text="← Atrás", command=lambda: self._on_back() if self._on_back else None).pack(pady=4)


# ══════════════════════════════════════════════════════════════════════════════
# PASO 6: PREVIEW — VERIFICAR ASIGNACIÓN DE COLUMNAS
# ══════════════════════════════════════════════════════════════════════════════

class StepPreview(WizardStep):
    """
    Corre OCR en la página 1 y muestra las primeras filas con las columnas
    asignadas según la calibración, para que el usuario verifique.
    """

    def __init__(self, parent, data: CalibrationData, **kwargs):
        super().__init__(parent, data, **kwargs)
        self._build()

    def _build(self):
        tk.Label(self, text="Preview de calibración",
                 font=("Helvetica", 16, "bold"), bg="#ECEFF1").pack(pady=(16, 2))
        tk.Label(self,
                 text="Verificá que las palabras aparezcan en la columna correcta. "
                      "Si hay errores, volvé atrás a ajustar las líneas.",
                 bg="#ECEFF1", fg="#546E7A", wraplength=700).pack(pady=4)

        self._status_lbl = tk.Label(self, text="Ejecutando OCR…",
                                    bg="#ECEFF1", fg="#546E7A",
                                    font=("Helvetica", 10, "italic"))
        self._status_lbl.pack()

        # Tabla
        tbl_frame = tk.Frame(self, bg="#ECEFF1")
        tbl_frame.pack(fill="both", expand=True, padx=16, pady=8)

        self._tree = ttk.Treeview(tbl_frame, show="headings", height=16)
        vsb = ttk.Scrollbar(tbl_frame, orient="vertical",   command=self._tree.yview)
        hsb = ttk.Scrollbar(tbl_frame, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tbl_frame.rowconfigure(0, weight=1)
        tbl_frame.columnconfigure(0, weight=1)

        self._nav_bar()

    def on_enter(self):
        self._status_lbl.config(text="Ejecutando OCR en página 1…")
        self._tree.delete(*self._tree.get_children())
        threading.Thread(target=self._run_preview, daemon=True).start()

    def _run_preview(self):
        try:
            images = convert_from_path(self.data.pdf_path, dpi=200,
                                       first_page=1, last_page=3)

            col_ranges_odd = build_col_ranges({
                col: rng[0] for col, rng in self.data.paginas_impares.items()
            })
            
            col_ranges_even = col_ranges_odd
            if self.data.paginas_pares:
                col_ranges_even = build_col_ranges({
                    col: rng[0] for col, rng in self.data.paginas_pares.items()
                })

            transactions = []
            for page_num, img in enumerate(images, 1):
                self.after(0, lambda p=page_num: self._status_lbl.config(
                    text=f"Ejecutando OCR en página {p}…"))
                
                is_even = (page_num % 2 == 0)
                active_ranges = col_ranges_even if is_even else col_ranges_odd
                
                active_y_bounds = tuple(self.data.limites_y_pares) if (is_even and self.data.limites_y_pares) else tuple(self.data.limites_y_impares)
                if not active_y_bounds and self.data.limites_y_impares:
                    active_y_bounds = tuple(self.data.limites_y_impares)
                
                data = run_ocr(img)
                rows = group_into_rows(data, img.width, page_height=img.height, y_bounds=active_y_bounds if len(active_y_bounds)==2 else None)

                for row in rows:
                    if is_transaction_row(row, active_ranges):
                        tx = row_to_transaction(row, active_ranges)
                        tx["_pagina"] = page_num
                        transactions.append(tx)
                
                # Ya no cortamos en la primer página con transacciones
                # para poder ver la página 2 (el layout par) en el preview.

            self.after(0, lambda: self._populate(transactions))
        except Exception as exc:
            self.after(0, lambda: self._status_lbl.config(
                text=f"Error al ejecutar OCR: {exc}", fg="#B71C1C"
            ))

    def _populate(self, transactions):
        cols = ["Pág."] + self.data.columnas
        self._tree.configure(columns=cols)
        for col in cols:
            self._tree.heading(col, text=col)
            width = 40 if col == "Pág." else max(80, 560 // len(self.data.columnas))
            self._tree.column(col, width=width, anchor="w" if col != "Pág." else "center")

        for tx in transactions[:100]:
            values = [tx.get("_pagina", "1")] + [tx.get(c, "") for c in self.data.columnas]
            self._tree.insert("", "end", values=values)

        count = len(transactions)
        pages = len(set(tx.get("_pagina", 1) for tx in transactions))
        self._status_lbl.config(
            text=f"{count} movimientos detectados en {pages} páginas iniciales (mostrando hasta 100).",
            fg="#2E7D32" if count > 0 else "#B71C1C"
        )


# ══════════════════════════════════════════════════════════════════════════════
# PASO 7: RESUMEN Y GUARDADO
# ══════════════════════════════════════════════════════════════════════════════

class StepReview(WizardStep):
    """Muestra resumen de la calibración y guarda el JSON en calibraciones/."""

    def __init__(self, parent, data: CalibrationData,
                 on_home: Callable, on_close: Callable,
                 edit_path: Optional[str] = None, **kwargs):
        super().__init__(parent, data, **kwargs)
        self._on_home = on_home
        self._on_close = on_close
        self._edit_path = edit_path   # path original si estamos editando
        self._build()

    def _build(self):
        tk.Label(self, text="Resumen de calibración",
                 font=("Helvetica", 15, "bold"), bg="#ECEFF1").pack(pady=(16, 4))

        self._text = tk.Text(self, font=("Courier", 10), state="disabled",
                             bg="#FAFAFA", relief="flat", padx=8, pady=8)
        self._text.pack(fill="both", expand=True, padx=24, pady=8)

        dest_frame = tk.Frame(self, bg="#ECEFF1")
        dest_frame.pack(fill="x", padx=24, pady=4)
        tk.Label(dest_frame, text="Guardar como:", bg="#ECEFF1").pack(side="left")
        self._dest_var = tk.StringVar()
        tk.Entry(dest_frame, textvariable=self._dest_var,
                 width=46).pack(side="left", padx=6)
        tk.Button(dest_frame, text="…", command=self._pick_dest).pack(side="left")

        btn_frame = tk.Frame(self, bg="#ECEFF1")
        btn_frame.pack(pady=12)

        self._btn_another = tk.Button(btn_frame, text="💾 Guardar y cargar otro",
                  bg="#1565C0", fg="black", width=24, pady=8,
                  font=("Helvetica", 11, "bold"),
                  command=self._save_and_home)
        self._btn_another.pack(side="left", padx=12)

        self._btn_close = tk.Button(btn_frame, text="✕ Guardar y cerrar",
                  bg="#CFD8DC", fg="black", width=20, pady=8,
                  font=("Helvetica", 11, "bold"),
                  command=self._save_and_close)
        self._btn_close.pack(side="left", padx=12)
        
        self._status_lbl = tk.Label(self, text="", bg="#ECEFF1", font=("Helvetica", 10, "bold"))
        self._status_lbl.pack(pady=4)

        self._nav_bar(show_next=False)

    def on_enter(self):
        # Generar nombre automático: {banco}_{tipo}_{yyyy-mm}.json
        safe = lambda s: s.lower().replace(" ", "_")
        filename = (f"{safe(self.data.banco)}_"
                    f"{safe(self.data.tipo_documento)}_"
                    f"{self.data.periodo}.json")
        default_path = CALIBRATIONS_DIR / filename
        # Si estamos editando, mantener el path original
        self._dest_var.set(str(self._edit_path or default_path))
        self._refresh_summary()

    def _refresh_summary(self):
        lines = [
            f"Banco:          {self.data.banco or '—'}",
            f"Tipo documento: {self.data.tipo_documento or '—'}",
            f"Período:        {self.data.periodo or '—'}",
            f"Columnas:       {', '.join(self.data.columnas)}",
            "",
        ]
        for title, ranges in [
            ("Páginas impares", self.data.paginas_impares),
            ("Páginas pares",   self.data.paginas_pares),
        ]:
            lines.append("─" * 56)
            lines.append(f"{title}:")
            for col, rng in ranges.items():
                s, e = rng[0], rng[1]
                bar = "█" * max(1, int((e - s) / 2.5))
                lines.append(f"  {col:<18} {s:5.1f}% – {e:5.1f}%  {bar}")
            lines.append("")

        self._text.config(state="normal")
        self._text.delete("1.0", "end")
        self._text.insert("1.0", "\n".join(lines))
        self._text.config(state="disabled")

    def _pick_dest(self):
        path = filedialog.asksaveasfilename(
            title="Guardar calibración",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialdir=str(CALIBRATIONS_DIR),
            initialfile=Path(self._dest_var.get()).name,
        )
        if path:
            self._dest_var.set(path)

    def _do_save_process(self, on_success: Callable):
        path = self._dest_var.get().strip()
        if not path:
            messagebox.showwarning("Falta ruta", "Indicá dónde guardar el archivo.")
            return

        dest = Path(path)
        if dest.exists() and str(dest) != str(self._edit_path):
            if not messagebox.askyesno("Sobreescribir", f"Ya existe '{dest.name}'.\n¿Sobreescribir?"):
                return

        # Deshabilita botones e informa ejecución
        self._btn_another.config(state="disabled", text="⏳ Guardando...")
        self._btn_close.config(state="disabled", text="⏳ Guardando...")
        self._status_lbl.config(text="Guardando perfil de calibración, por favor esperá...", fg="#1565C0")
        self.update_idletasks()

        def background_task():
            try:
                import time
                time.sleep(0.7)  # Delay intencional para validación visual de UI
                CalibrationIO.save(self.data, path)
                self.after(0, _finish_success)
            except Exception as exc:
                self.after(0, lambda e=exc: _finish_error(e))

        def _finish_success():
            self._status_lbl.config(text="¡Guardado exitosamente!", fg="#2E7D32")
            messagebox.showinfo("¡Guardado!", f"Calibración finalizada y guardada en:\n{path}")
            on_success()

        def _finish_error(exc):
            self._status_lbl.config(text="Error al guardar.", fg="#B71C1C")
            messagebox.showerror("Error al guardar", str(exc))
            self._btn_another.config(state="normal", text="💾 Guardar y cargar otro")
            self._btn_close.config(state="normal", text="✕ Guardar y cerrar")

        threading.Thread(target=background_task, daemon=True).start()

    def _save_and_home(self):
        self._do_save_process(self._on_home)

    def _save_and_close(self):
        self._do_save_process(self._on_close)


# ══════════════════════════════════════════════════════════════════════════════
# CONTROLADOR PRINCIPAL DEL WIZARD
# ══════════════════════════════════════════════════════════════════════════════

class WizardApp(tk.Tk):
    """Controlador central. Administra la pila de pasos y la navegación."""

    TITLE = "Calibrador de Extractos Bancarios"

    def __init__(self):
        super().__init__()
        self.title(self.TITLE)
        self.geometry("1020x780")
        self.minsize(800, 600)
        self.configure(bg="#ECEFF1")

        self._data  = CalibrationData()
        self._stack: List[WizardStep] = []

        self._build_header()
        self._container = tk.Frame(self, bg="#ECEFF1")
        self._container.pack(fill="both", expand=True)

        CALIBRATIONS_DIR.mkdir(parents=True, exist_ok=True)
        self._push(self._create_step_home())

    def _build_header(self):
        header = tk.Frame(self, bg="#1565C0")
        header.pack(fill="x")
        tk.Label(header, text=f"  {self.TITLE}",
                 font=("Helvetica", 13, "bold"),
                 bg="#1565C0", fg="white", pady=10).pack(side="left")

    # ── Gestión de la pila ────────────────────────────────────────────────────

    def _push(self, step: WizardStep):
        if self._stack:
            self._stack[-1].pack_forget()
        self._stack.append(step)
        step.pack(fill="both", expand=True, in_=self._container)
        step.on_enter()

    def _pop(self):
        if len(self._stack) < 2:
            return
        self._stack.pop().pack_forget()
        prev = self._stack[-1]
        prev.pack(fill="both", expand=True, in_=self._container)
        prev.on_enter()

    def _reset_to_home(self):
        """Vacía la pila y vuelve a la pantalla inicial."""
        for step in self._stack:
            step.pack_forget()
        self._stack.clear()
        self._data = CalibrationData()
        self._push(self._create_step_home())

    # ── Fábrica de pasos ──────────────────────────────────────────────────────

    def _create_step_home(self) -> StepHome:
        return StepHome(
            self._container, self._data,
            on_new=lambda: self._push(self._create_step_setup()),
            on_edit=self._start_edit,
        )

    def _start_edit(self, loaded_data: CalibrationData, edit_path: str):
        """Carga un perfil existente en el wizard para editarlo."""
        self._data = loaded_data
        # Actualizar referencia en los nuevos pasos
        setup = self._create_step_setup()
        self._push(setup)

    def _create_step_setup(self) -> StepSetup:
        step = StepSetup(self._container, self._data)
        step.set_navigation(
            on_next=lambda: self._push(self._create_step_detect()),
            on_back=self._pop,
        )
        return step

    def _create_step_detect(self) -> StepDetect:
        step = StepDetect(self._container, self._data)
        step.set_navigation(
            on_next=lambda: self._push(self._create_step_mark_odd()),
            on_back=self._pop,
        )
        return step

    def _create_step_mark_odd(self) -> StepMarkPage:
        step = StepMarkPage(self._container, self._data, parity="odd")
        step.set_navigation(
            on_next=lambda: self._push(self._create_step_parity_choice()),
            on_back=self._pop,
        )
        return step

    def _create_step_parity_choice(self) -> StepParityChoice:
        step = StepParityChoice(
            self._container, self._data,
            on_same=self._handle_same_parity,
            on_different=lambda: self._push(self._create_step_mark_even()),
        )
        step.set_navigation(on_next=None, on_back=self._pop)
        return step

    def _handle_same_parity(self):
        self._data.paginas_pares = dict(self._data.paginas_impares)
        self._push(self._create_step_preview())

    def _create_step_mark_even(self) -> StepMarkPage:
        step = StepMarkPage(self._container, self._data, parity="even")
        step.set_navigation(
            on_next=lambda: self._push(self._create_step_preview()),
            on_back=self._pop,
        )
        return step

    def _create_step_preview(self) -> StepPreview:
        step = StepPreview(self._container, self._data)
        step.set_navigation(
            on_next=lambda: self._push(self._create_step_review()),
            on_back=self._pop,
        )
        return step

    def _create_step_review(self) -> StepReview:
        step = StepReview(self._container, self._data,
                          on_home=self._reset_to_home,
                          on_close=self.destroy)
        step.set_navigation(on_next=None, on_back=self._pop)
        return step


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = WizardApp()
    app.mainloop()
