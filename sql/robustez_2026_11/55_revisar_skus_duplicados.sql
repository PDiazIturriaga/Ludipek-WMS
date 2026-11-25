-- =====================================================================
-- LUDIPEK WMS · 55 REVISAR SKU DUPLICADOS EN LA MAESTRA  (PASO 1 solo lectura)
--
-- Caso típico: la maestra tiene "50907CL" y NetSuite usa "VPCO50907CL" para el mismo producto, o un
-- mismo código de barras quedó en dos SKU distintos. Al escanear, el celular puede tomar cualquiera.
--
-- PASO 1 (solo lectura): tres listados para decidir qué SKU queda.
-- PASO 2 (opcional, comentado): pasar el SKU antiguo al de NetSuite. Revise el PASO 1 antes.
-- =====================================================================

-- 1-A · Mismo código de barras en SKU distintos
select m.codigo_barras,
       count(distinct upper(btrim(m.sku))) as skus,
       string_agg(distinct upper(btrim(m.sku)) || ' (' || coalesce(m.unidad_medida, '?') || ' x' || m.multiplo || ')', ' | ') as detalle
  from maestra_sku m
 where nullif(btrim(m.codigo_barras), '') is not null
   and upper(btrim(m.codigo_barras)) <> upper(btrim(m.sku))
 group by m.codigo_barras
having count(distinct upper(btrim(m.sku))) > 1
 order by skus desc, m.codigo_barras;

-- 1-B · SKU que está contenido en otro (ej. 50907CL dentro de VPCO50907CL), con lo que tiene cada uno
with s as (
  select upper(btrim(sku)) sku, max(descripcion) descripcion, count(*) filas_maestra,
         string_agg(distinct coalesce(unidad_medida, '?') || ' x' || multiplo, ', ') presentaciones
    from maestra_sku group by 1
),
uso as (
  select s.sku,
         (select coalesce(sum(i.cantidad_unidades), 0) from bodega_inventario_ubicacion i where upper(btrim(i.sku)) = s.sku) as stock_un,
         (select count(*) from registro_recepcion r where upper(btrim(r.sku)) = s.sku) as recepciones,
         (select count(*) from asn_detalle d where upper(btrim(d.sku)) = s.sku) as lineas_oc
    from s
)
select corto.sku as sku_antiguo, corto.descripcion as desc_antiguo, corto.presentaciones as pres_antiguo,
       ua.stock_un as stock_antiguo, ua.recepciones as recep_antiguo, ua.lineas_oc as oc_antiguo,
       largo.sku as sku_netsuite, largo.descripcion as desc_netsuite, largo.presentaciones as pres_netsuite,
       ub.stock_un as stock_netsuite, ub.recepciones as recep_netsuite, ub.lineas_oc as oc_netsuite
  from s corto
  join s largo on largo.sku <> corto.sku and largo.sku like '%' || corto.sku and length(corto.sku) >= 5
  join uso ua on ua.sku = corto.sku
  join uso ub on ub.sku = largo.sku
 order by corto.sku, largo.sku;

-- 1-C · SKU de OC (NetSuite) que no están en la maestra
select distinct upper(btrim(d.sku)) as sku_en_oc, a.numero_oc, a.proveedor
  from asn_detalle d join asn_cabecera a on a.id = d.asn_id
 where not exists (select 1 from maestra_sku m where upper(btrim(m.sku)) = upper(btrim(d.sku)))
 order by 1;

-- =====================================================================
-- PASO 2 (OPCIONAL) · Pasar un SKU antiguo al código de NetSuite.
-- Quite los "--" del bloque, ponga los pares (antiguo, nuevo) y ejecútelo. Hace todo junto o nada:
--   · stock, recepciones y líneas de OC del SKU antiguo pasan al nuevo;
--   · las filas de la maestra del antiguo pasan al nuevo si el nuevo no tiene esa presentación
--     (mismo código de barras y unidad); las que sobran quedan inactivas.
-- =====================================================================
-- do $$
-- declare p record;
-- begin
--   for p in select upper(antiguo) antiguo, upper(nuevo) nuevo from (values
--       ('50907CL', 'VPCO50907CL')              -- (antiguo, nuevo); agregue más pares separados por coma
--     ) v(antiguo, nuevo)
--   loop
--     update bodega_inventario_ubicacion set sku = p.nuevo where upper(btrim(sku)) = p.antiguo;
--     update registro_recepcion set sku = p.nuevo where upper(btrim(sku)) = p.antiguo;
--     update asn_detalle d set sku = p.nuevo where upper(btrim(d.sku)) = p.antiguo
--        and not exists (select 1 from asn_detalle d2 where d2.asn_id = d.asn_id and upper(btrim(d2.sku)) = p.nuevo);
--     update maestra_sku m set sku = p.nuevo
--      where upper(btrim(m.sku)) = p.antiguo
--        and not exists (select 1 from maestra_sku n where upper(btrim(n.sku)) = p.nuevo
--                          and n.codigo_barras = m.codigo_barras and coalesce(n.unidad_medida, '') = coalesce(m.unidad_medida, ''));
--     update maestra_sku set activo = false where upper(btrim(sku)) = p.antiguo;
--     raise notice 'SKU % pasado a %', p.antiguo, p.nuevo;
--   end loop;
-- end $$;
