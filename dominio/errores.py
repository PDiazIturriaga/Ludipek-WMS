class WmsError(Exception):
    def __init__(self, mensaje_operador: str, *, operacion: str = "", entidad: str = "", detalle: str = ""):
        super().__init__(mensaje_operador)
        self.mensaje_operador = mensaje_operador
        self.operacion = operacion
        self.entidad = entidad
        self.detalle = detalle

class WmsDataError(WmsError): pass
class SupabaseWriteError(WmsError): pass
class ConciliacionError(WmsError): pass
class DocumentoExportError(WmsError): pass
class TransicionEstadoError(WmsError): pass
