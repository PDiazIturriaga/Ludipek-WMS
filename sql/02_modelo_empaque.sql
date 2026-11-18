begin;
create or replace view public.vw_maestra_empaque_sku as
with base as (
 select *, upper(replace(coalesce(unidad_medida,''),' ','_')) um
 from public.maestra_sku where activo is distinct from false
)
select sku,
 max(descripcion) descripcion,
 max(marca) marca,
 max(codigo_barras) filter(where um in ('UN','UNIDAD','UNIT')) ean_unidad,
 max(multiplo) filter(where um in ('UN','UNIDAD','UNIT')) multiplo_unidad,
 max(codigo_barras) filter(where um in ('DISPLAY','DSP')) ean_display,
 max(multiplo) filter(where um in ('DISPLAY','DSP')) multiplo_display,
 max(codigo_barras) filter(where um in ('CAJA','CAJA_MASTER','MASTER','CJ')) ean_caja,
 max(multiplo) filter(where um in ('CAJA','CAJA_MASTER','MASTER','CJ')) multiplo_caja,
 max((peso_gr/1000.0)) filter(where um in ('UN','UNIDAD','UNIT')) peso_unitario_kg,
 max((peso_gr/1000.0)) filter(where um in ('DISPLAY','DSP')) peso_display_kg,
 max((peso_gr/1000.0)) filter(where um in ('CAJA','CAJA_MASTER','MASTER','CJ')) peso_caja_kg,
 bool_or(requiere_vencimiento) requiere_vencimiento,
 (max(multiplo) filter(where um in ('CAJA','CAJA_MASTER','MASTER','CJ')) is not null) configuracion_caja_valida
from base group by sku;
commit;
