-- =====================================================================
-- LUDIPEK WMS · 43 REVISAR PESOS UNIDAD / CAJA   (SOLO LECTURA)
-- En maestra_sku un SKU tiene una fila por unidad de medida (UNIDAD, DISPLAY, CAJA...) y cada
-- fila debe tener el peso de ESA unidad. Aquí se listan los SKU cuya fila de unidad tiene el mismo
-- peso que su fila de caja (o display): uno de los dos está mal.
-- Efecto en el WMS: el packing calcula el peso esperado con la fila más chica; si la unidad trae el
-- peso de la caja, el peso esperado sale multiplicado por el múltiplo y salta "Diferencia de peso".
-- No cambia nada. La corrección está en 43b_corregir_pesos_unidad_caja.sql.
-- =====================================================================
with filas as (
  select regexp_replace(upper(btrim(sku)), '-FA$', '') sku_base, sku, codigo_barras, unidad_medida, multiplo,
         peso_gr, peso_kg, marca, descripcion,
         coalesce(nullif(peso_gr, 0) / 1000.0, nullif(peso_kg, 0)) peso_fila_kg
    from public.maestra_sku
), unidad as (
  select distinct on (sku_base) * from filas where multiplo = 1 order by sku_base, peso_fila_kg desc nulls last
), mayores as (
  select * from filas where multiplo > 1
)
select u.sku_base as sku, u.marca, left(u.descripcion, 40) as descripcion,
       m.unidad_medida as fila_mayor, m.multiplo,
       u.peso_gr as gr_unidad, m.peso_gr as gr_mayor, u.peso_kg as kg_unidad, m.peso_kg as kg_mayor,
       round(m.peso_fila_kg / m.multiplo, 4) as kg_unidad_sugerido,
       case when upper(coalesce(u.marca, '') || ' ' || coalesce(u.descripcion, '')) ~ '(GIWI|GIGWI)' then 'GIWI' else '' end as giwi
  from unidad u
  join mayores m on m.sku_base = u.sku_base
 where u.peso_fila_kg is not null and m.peso_fila_kg is not null
   and abs(u.peso_fila_kg - m.peso_fila_kg) < 0.0005
 order by giwi desc, u.sku_base, m.multiplo;
