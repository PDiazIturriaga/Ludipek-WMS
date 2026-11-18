-- =====================================================================
-- LUDIPEK WMS · 00 DIAGNÓSTICO (SOLO LECTURA: no modifica nada)
-- Ejecutar en Supabase > SQL Editor ANTES y DESPUÉS de la limpieza.
-- La primera consulta es el resumen; las siguientes muestran el detalle.
-- =====================================================================

-- 1) RESUMEN: cantidad de casos por tipo de problema ---------------------
with
inv as (select * from public.bodega_inventario_ubicacion),
rec as (select * from public.registro_recepcion),
fmt_inv as (
  select count(*) filter (where fecha_vencimiento_cl ~ '^\d{2}/\d{2}/\d{4}$') as dd_slash,
         count(*) filter (where coalesce(btrim(fecha_vencimiento_cl),'') <> ''
                            and fecha_vencimiento_cl !~ '^\d{2}[-/.]\d{2}[-/.]\d{4}$'
                            and fecha_vencimiento_cl !~ '^\d{4}-\d{2}-\d{2}$') as no_reconocida
  from inv)
select 'SKU con espacios, saltos de línea o minúsculas (inventario)' as problema,
       count(*) as casos from inv where sku <> upper(regexp_replace(sku, '[[:space:]]', '', 'g'))
union all select 'SKU con espacios, saltos de línea o minúsculas (recepción)',
       count(*) from rec where sku <> upper(regexp_replace(sku, '[[:space:]]', '', 'g'))
union all select 'SKU con espacios o minúsculas (líneas de OV)',
       count(*) from public.netsuite_detalle_ov where sku <> upper(regexp_replace(sku, '[[:space:]]', '', 'g'))
union all select 'Vencimiento en formato DD/MM/YYYY (inventario usa dos formatos)', dd_slash from fmt_inv
union all select 'Vencimiento NO reconocible (inventario)', no_reconocida from fmt_inv
union all select 'Inventario con bodega vacía', count(*) from inv where coalesce(btrim(bodega),'') = ''
union all select 'Inventario sin código de ubicación', count(*) from inv where coalesce(btrim(codigo_ubicacion),'') = ''
union all select 'Inventario en ubicación que NO existe en bodega_ubicaciones', count(*)
       from inv i where coalesce(btrim(i.codigo_ubicacion),'') <> '' and not exists (
         select 1 from public.bodega_ubicaciones u
         where u.bodega = coalesce(nullif(btrim(i.bodega),''),'Bodega Santiago')
           and upper(btrim(u.codigo_ubicacion)) = upper(btrim(i.codigo_ubicacion)))
union all select 'Inventario duplicado (misma bodega+ubicación+SKU+lote+LPN)', coalesce(sum(n - 1), 0)
       from (select count(*) n from inv group by bodega, upper(btrim(codigo_ubicacion)), upper(btrim(sku)), upper(btrim(lote)), coalesce(lpn,'') having count(*) > 1) d
union all select 'LPN repartido en más de una ubicación de rack', count(*)
       from (select lpn from inv where lpn is not null and codigo_ubicacion not like 'ZONA-%'
             group by bodega, lpn having count(distinct codigo_ubicacion) > 1) d
union all select 'Inventario con cajas vacías', count(*) from inv where cajas is null
union all select 'LPN de recepción en dos bodegas', count(*)
       from (select lpn from rec group by lpn having count(distinct bodega) > 1) d
union all select 'Recepción: unidades <> cajas x múltiplo + sueltas', count(*)
       from rec where unidades_totales <> cajas * multiplo_aplicado + unidades_sueltas
union all select 'LPN recepcionados que nunca fueron almacenados', count(distinct r.lpn)
       from rec r where coalesce(r.estado_pallet, '') <> 'CERRADO_SIN_UBICAR'
         and not exists (select 1 from inv i where i.lpn = r.lpn)
         and not exists (select 1 from public.historial_movimientos h where h.lpn = r.lpn and h.tipo_movimiento in ('ALMACENAMIENTO','ENVIO_MERMA'))
union all select 'OV de traslado (OT-) con líneas repetidas (mismo SKU y cantidad)', count(*)
       from (select d.orden_id from public.netsuite_detalle_ov d join public.netsuite_ordenes_venta o on o.id = d.orden_id
             where o.numero_ov like 'OT-%' group by d.orden_id, d.sku, d.cantidad_pedida having count(*) > 1) x
union all select 'Líneas de OV con lotes_pickeados corrupto ("(N UN)" repetido)', count(*)
       from public.netsuite_detalle_ov where lotes_pickeados ~ '\(\d+ UN\)\s*\(\d+ UN\)'
union all select 'Líneas de OV con pickeado > pedido', count(*)
       from public.netsuite_detalle_ov where coalesce(cantidad_pickeada,0) > cantidad_pedida
union all select 'Usuarios con contraseña en texto plano', count(*)
       from public.wms_usuarios where password !~ '^\$2[aby]\$'
union all select 'Tablas con RLS activo y SIN políticas (el celular no puede usarlas; el PC sí)', count(*)
       from pg_class c where c.relnamespace = 'public'::regnamespace and c.relkind = 'r' and c.relrowsecurity
         and not exists (select 1 from pg_policies p where p.schemaname = 'public' and p.tablename = c.relname)
order by casos desc;

-- 2) DETALLE: inventario en ubicaciones inexistentes ---------------------
select i.id, i.bodega, i.codigo_ubicacion, i.sku, i.lote, i.lpn, i.cantidad_unidades
from public.bodega_inventario_ubicacion i
where not exists (select 1 from public.bodega_ubicaciones u
                  where u.bodega = coalesce(nullif(btrim(i.bodega),''),'Bodega Santiago')
                    and upper(btrim(u.codigo_ubicacion)) = upper(btrim(i.codigo_ubicacion)))
order by i.codigo_ubicacion;

-- 3) DETALLE: inventario duplicado (revisar con conteo cíclico) ----------
select bodega, codigo_ubicacion, sku, lote, lpn, count(*) as filas, sum(cantidad_unidades) as unidades_sumadas,
       string_agg(id::text || ':' || cantidad_unidades, ', ' order by id) as ids_y_unidades
from public.bodega_inventario_ubicacion
group by bodega, codigo_ubicacion, sku, lote, lpn having count(*) > 1;

-- 4) DETALLE: LPN repartido en varias ubicaciones de rack ----------------
select bodega, lpn, string_agg(distinct codigo_ubicacion, ', ') as ubicaciones, sum(cantidad_unidades) as unidades
from public.bodega_inventario_ubicacion
where lpn is not null and codigo_ubicacion not like 'ZONA-%'
group by bodega, lpn having count(distinct codigo_ubicacion) > 1;

-- 5) DETALLE: traslados (OT-) con líneas repetidas ------------------------
select o.numero_ov, d.orden_id, d.sku, d.cantidad_pedida, count(*) as veces,
       sum(coalesce(d.cantidad_pickeada,0)) as ya_pickeado
from public.netsuite_detalle_ov d join public.netsuite_ordenes_venta o on o.id = d.orden_id
where o.numero_ov like 'OT-%'
group by o.numero_ov, d.orden_id, d.sku, d.cantidad_pedida having count(*) > 1
order by d.orden_id, d.sku;

-- 6) DETALLE: vencimientos que no se pueden interpretar -------------------
select 'inventario' as tabla, id, sku, lote, fecha_vencimiento_cl
from public.bodega_inventario_ubicacion
where coalesce(btrim(fecha_vencimiento_cl),'') not in ('', 'S/F')
  and fecha_vencimiento_cl !~ '^\d{1,2}[-/.]\d{1,2}[-/.]\d{4}$'
  and fecha_vencimiento_cl !~ '^\d{4}-\d{2}-\d{2}';
