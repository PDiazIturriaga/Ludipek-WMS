from repositorios.base_repository import BaseRepository

class RecepcionRepository(BaseRepository):
    def obtener_asn(self, asn_id: int):
        cabecera = self.listar("asn_cabecera", "*", id=asn_id)
        detalle = self.listar("asn_detalle", "*", asn_id=asn_id)
        packing = self.listar("asn_packing_list_detalle", "*", asn_id=asn_id)
        fisico = self.listar("registro_recepcion", "*", asn_id=asn_id)
        return {"cabecera": cabecera[0] if cabecera else None, "detalle": detalle, "packing_list": packing, "fisico": fisico}
