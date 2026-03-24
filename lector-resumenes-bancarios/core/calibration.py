"""
core/calibration.py — Modelo de datos y persistencia de perfiles de calibración.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class CalibrationData:
    """Almacena toda la información de una calibración."""
    banco: str = ""
    tipo_documento: str = ""
    periodo: str = ""          # yyyy-mm
    columnas: List[str] = field(default_factory=lambda: [
        "fecha", "concepto", "f_valor", "comprobante",
        "origen", "canal", "debitos", "creditos", "saldos"
    ])
    paginas_impares: dict = field(default_factory=dict)
    paginas_pares: dict = field(default_factory=dict)
    limites_y_impares: List[float] = field(default_factory=list)
    limites_y_pares: List[float] = field(default_factory=list)
    pdf_path: str = ""

    def set_ranges(self, boundary_pcts: List[float], parity: str):
        """
        Convierte N-1 porcentajes de límite en rangos para N columnas.
        parity: 'odd' | 'even'
        """
        edges = [0.0] + sorted(boundary_pcts) + [100.0]
        ranges = {
            col: [edges[i], edges[i + 1]]
            for i, col in enumerate(self.columnas)
        }
        if parity == "odd":
            self.paginas_impares = ranges
        else:
            self.paginas_pares = ranges

    def to_dict(self) -> dict:
        return {
            "banco": self.banco,
            "tipo_documento": self.tipo_documento,
            "periodo": self.periodo,
            "columnas": self.columnas,
            "paginas_impares": self.paginas_impares,
            "paginas_pares": self.paginas_pares or self.paginas_impares,
            "limites_y_impares": self.limites_y_impares,
            "limites_y_pares": self.limites_y_pares or self.limites_y_impares,
        }


class CalibrationIO:
    """Lee y escribe archivos JSON de calibración."""

    @staticmethod
    def save(data: CalibrationData, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data.to_dict(), f, indent=2, ensure_ascii=False)

    @staticmethod
    def load(path: str) -> CalibrationData:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return CalibrationData(
            banco=d.get("banco", ""),
            tipo_documento=d.get("tipo_documento", d.get("formato", "")),
            periodo=d.get("periodo", ""),
            columnas=d.get("columnas", []),
            paginas_impares=d.get("paginas_impares", {}),
            paginas_pares=d.get("paginas_pares", {}),
            limites_y_impares=d.get("limites_y_impares", []),
            limites_y_pares=d.get("limites_y_pares", []),
        )


class CalibrationFinder:
    """Busca y selecciona perfiles de calibración en una carpeta local."""

    @staticmethod
    def find_all(folder: str) -> List[dict]:
        """
        Retorna todos los perfiles JSON en la carpeta, ordenados por periodo desc.
        Cada entrada: {"path": Path, "data": CalibrationData}
        """
        results = []
        for p in Path(folder).glob("*.json"):
            try:
                data = CalibrationIO.load(str(p))
                results.append({"path": p, "data": data})
            except Exception:
                pass
        results.sort(key=lambda e: e["data"].periodo, reverse=True)
        return results

    @staticmethod
    def find_latest(folder: str, banco: str = "", tipo_documento: str = "") -> Optional[CalibrationData]:
        """
        Retorna el perfil más reciente, opcionalmente filtrado por banco y tipo.
        """
        all_profiles = CalibrationFinder.find_all(folder)
        for entry in all_profiles:
            d = entry["data"]
            if banco and d.banco.lower() != banco.lower():
                continue
            if tipo_documento and d.tipo_documento.lower() != tipo_documento.lower():
                continue
            return d
        return None
