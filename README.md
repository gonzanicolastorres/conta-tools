# Conta Tools

Conjunto de herramientas para contadores, orientadas a automatizar tareas repetitivas con archivos bancarios y contables.

---

## Módulos

### [lector-resumenes-bancarios](./lector-resumenes-bancarios/)

Herramienta web para convertir extractos bancarios en PDF a archivos Excel estructurados. Soporta PDFs escaneados (OCR con Tesseract) y PDFs con texto seleccionable (extracción directa con pdfplumber). Incluye un calibrador visual interactivo para configurar nuevos bancos/formatos sin tocar código.

**Estado:** Operativo. Ver [README del módulo](./lector-resumenes-bancarios/README.md) para instrucciones de uso.

---

## Inicio rápido

```bash
cd lector-resumenes-bancarios
conda activate conta-tools
uvicorn server:app --reload
```

Abrir en el navegador: [http://localhost:8000](http://localhost:8000)
