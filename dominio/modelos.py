from dataclasses import dataclass, field
from datetime import date

@dataclass(frozen=True)
class ClaveTrazabilidad:
    sku: str
    lote: str
    fecha_vencimiento: date | None

@dataclass
class CantidadEmpaque:
    cajas: int = 0
    displays: int = 0
    unidades_sueltas: int = 0
    multiplo_caja: int = 1
    multiplo_display: int = 1

    @property
    def unidades_totales(self) -> int:
        return self.cajas * self.multiplo_caja + self.displays * self.multiplo_display + self.unidades_sueltas

@dataclass
class LineaConciliacion:
    sku: str
    descripcion: str = ""
    lote: str = "S/L"
    fecha_vencimiento: date | None = None
    unidades_oc: int = 0
    unidades_packing_list: int = 0
    unidades_recibidas: int = 0
    observaciones: list[str] = field(default_factory=list)

    @property
    def diferencia_oc_pl(self) -> int:
        return self.unidades_packing_list - self.unidades_oc

    @property
    def diferencia_pl_fisico(self) -> int:
        return self.unidades_recibidas - self.unidades_packing_list
