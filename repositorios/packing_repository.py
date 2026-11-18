from repositorios.base_repository import BaseRepository

class PackingRepository(BaseRepository):
    def sesion_activa(self, orden_id: int):
        try:
            return (self.client.table("wms_packing_cabecera").select("*")
                    .eq("orden_id", orden_id).eq("estado", "PACKING_EN_PROCESO")
                    .order("id", desc=True).limit(1).execute().data or [])
        except Exception:
            return []

    def guardar_linea(self, payload: dict):
        return self.upsert(
            "wms_packing_linea", payload,
            on_conflict="pallet_id,detalle_orden_id,lote,fecha_vencimiento"
        )
