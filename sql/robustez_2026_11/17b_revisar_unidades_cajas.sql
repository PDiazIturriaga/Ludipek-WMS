-- =====================================================================
-- LUDIPEK WMS · 17b REVISAR ANTES DE CORREGIR (solo lectura)   [versión 2]
-- Una fila por stock con unidades = cajas, con el múltiplo que aplicaría el 17.
-- (La maestra tiene una fila por presentación: se usa la CAJA = mayor múltiplo.)
-- Si "unidades_por_caja" es 1, el 17 no la toca.
-- =====================================================================
with mae as (
  select sku, max(multiplo) filter (where multiplo > 1) caja,
         string_agg(distinct coalesce(unidad_medida, '?') || '=' || multiplo, ' · ') presentaciones
  from maestra_sku group by sku
), rec as (
  select r.sku, r.multiplo_aplicado m,
         row_number() over (partition by r.sku order by count(*) desc, max(r.fecha_recepcion) desc) rk
  from registro_recepcion r where r.multiplo_aplicado > 1
  group by r.sku, r.multiplo_aplicado
), x as (
  select i.codigo_ubicacion, i.lpn, i.sku, i.lote, i.cajas, i.cantidad_unidades,
         (select max(r.multiplo_aplicado) from registro_recepcion r
           where r.bodega = i.bodega and r.lpn = i.lpn and r.sku = i.sku and r.multiplo_aplicado > 1) m_lpn,
         mae.caja, rec.m m_rec, mae.presentaciones
  from bodega_inventario_ubicacion i
  left join mae on mae.sku = i.sku
  left join rec on rec.sku = i.sku and rec.rk = 1
  where i.cajas > 0 and i.cantidad_unidades = i.cajas
)
select codigo_ubicacion as ubicacion, lpn, sku, lote, cajas, cantidad_unidades as unidades_hoy,
       coalesce(m_lpn, caja, m_rec, 1) as unidades_por_caja,
       cajas * coalesce(m_lpn, caja, m_rec, 1) as unidades_corregidas,
       case when m_lpn is not null then 'RECEPCION DEL LPN' when caja is not null then 'MAESTRA (CAJA)'
            when m_rec is not null then 'RECEPCIONES DEL SKU' else 'SIN EVIDENCIA (no se toca)' end as fuente,
       presentaciones as presentaciones_maestra
from x
order by unidades_por_caja desc, sku, ubicacion, lpn;

-- ¿La versión anterior del 17 alcanzó a cambiar la maestra? (si sale > 0, el 17 nuevo lo deshace)
-- select count(*) from public.wms_respaldo_unidades_cajas where tipo = 'MAESTRA';
