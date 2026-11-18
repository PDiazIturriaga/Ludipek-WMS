from dominio.errores import WmsDataError, SupabaseWriteError

class BaseRepository:
    def __init__(self, client):
        self.client = client

    def listar(self, tabla: str, columnas: str = "*", **filtros):
        try:
            consulta = self.client.table(tabla).select(columnas)
            for campo, valor in filtros.items():
                consulta = consulta.eq(campo, valor)
            return consulta.execute().data or []
        except Exception as exc:
            raise WmsDataError("No se pudo consultar la información.", operacion="SELECT", entidad=tabla, detalle=str(exc)) from exc

    def upsert(self, tabla: str, payload, *, on_conflict: str | None = None):
        try:
            consulta = self.client.table(tabla).upsert(payload, on_conflict=on_conflict) if on_conflict else self.client.table(tabla).upsert(payload)
            return consulta.execute().data or []
        except Exception as exc:
            raise SupabaseWriteError("No se pudo guardar la operación.", operacion="UPSERT", entidad=tabla, detalle=str(exc)) from exc
