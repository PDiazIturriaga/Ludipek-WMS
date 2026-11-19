-- =====================================================================
-- LUDIPEK WMS · 22 CONSULTA DE STOCK PARA OPERADORES (celular)  (requiere 15 y 19)
-- El operador escanea un EAN / escribe un SKU o parte de la descripción y ve:
-- total disponible, cuánto hay en picking (nivel 01), su picking fijo y cada
-- ubicación con LPN, lote y vencimiento (primero picking, luego el que vence antes).
-- Solo lectura. Después de este script vuelva a ejecutar el 14 (los reportes de los
-- operadores ahora muestran el módulo y el SKU).
-- =====================================================================
begin;

create or replace function public.wms_consulta_stock_operador(p_bodega text, p_texto text)
returns jsonb language sql stable security definer set search_path = public as $$
  with prm as (
    select public.wms_bodega_valida(p_bodega) bod,
           upper(btrim(coalesce(p_texto, ''))) txt,
           regexp_replace(upper(btrim(coalesce(p_texto, ''))), '^0+', '') sin_ceros
  ),
  exactos as (     -- SKU exacto o código de barras (con o sin ceros a la izquierda)
    select distinct upper(m.sku) sku
    from maestra_sku m, prm
    where prm.txt <> ''
      and (upper(m.sku) = prm.txt
           or regexp_replace(upper(coalesce(m.codigo_barras, '')), '^0+', '') = prm.sin_ceros)
  ),
  por_texto as (   -- si no hubo exacto: por descripción o parte del SKU
    select upper(m.sku) sku
    from maestra_sku m, prm
    where length(prm.txt) >= 3 and not exists (select 1 from exactos)
      and (upper(m.sku) like '%' || prm.txt || '%' or upper(coalesce(m.descripcion, '')) like '%' || prm.txt || '%')
    group by upper(m.sku)
    order by upper(m.sku)
    limit 8
  ),
  skus as (select sku from exactos union select sku from por_texto),
  inv as (
    select upper(i.sku) sku, i.codigo_ubicacion ub, i.lpn, coalesce(i.lote, 'S/L') lote, i.fecha_vencimiento_cl venc,
           i.cantidad_unidades un, coalesce(i.cajas, 0) cajas,
           public.wms_es_ubicacion_picking(i.codigo_ubicacion) or i.codigo_ubicacion = 'ZONA-PICKING' es_pick,
           i.codigo_ubicacion = 'ZONA-MERMA' or i.codigo_ubicacion like 'ME-%' es_merma,
           case when i.fecha_vencimiento_cl ~ '^\d{2}-\d{2}-\d{4}$' then to_date(i.fecha_vencimiento_cl, 'DD-MM-YYYY') end fv
    from bodega_inventario_ubicacion i, prm
    where i.bodega = prm.bod and i.cantidad_unidades > 0 and upper(i.sku) in (select sku from skus)
  )
  select jsonb_build_object(
    'texto', (select txt from prm),
    'skus', coalesce(jsonb_agg(x.obj order by x.total desc, x.sku), '[]'::jsonb))
  from (
    select s.sku,
           coalesce((select sum(un) from inv where inv.sku = s.sku and not es_merma), 0) total,
           jsonb_build_object(
             'sku', s.sku,
             'descripcion', (select m.descripcion from maestra_sku m where upper(m.sku) = s.sku and m.descripcion is not null limit 1),
             'multiplo', (select max(greatest(coalesce(m.multiplo, 1), 1)) from maestra_sku m where upper(m.sku) = s.sku),
             'picking_fijo', (select p.ubicacion from wms_ubicacion_picking_sku p, prm where p.bodega = prm.bod and upper(p.sku) = s.sku limit 1),
             'total', coalesce((select sum(un) from inv where inv.sku = s.sku and not es_merma), 0),
             'en_picking', coalesce((select sum(un) from inv where inv.sku = s.sku and es_pick), 0),
             'en_reserva', coalesce((select sum(un) from inv where inv.sku = s.sku and not es_pick and not es_merma), 0),
             'en_merma', coalesce((select sum(un) from inv where inv.sku = s.sku and es_merma), 0),
             'proximo_vencimiento', (select to_char(min(fv), 'DD-MM-YYYY') from inv where inv.sku = s.sku and not es_merma),
             'ubicaciones', coalesce((
               select jsonb_agg(jsonb_build_object('ubicacion', ub, 'lpn', lpn, 'lote', lote, 'vencimiento', venc,
                                                   'unidades', un, 'cajas', cajas,
                                                   'zona', case when es_pick then 'PICKING' when es_merma then 'MERMA' else 'RESERVA' end)
                                order by es_merma, (not es_pick), fv nulls last, ub)
               from inv where inv.sku = s.sku), '[]'::jsonb)
           ) obj
    from skus s
  ) x;
$$;

grant execute on function public.wms_consulta_stock_operador(text, text) to anon, authenticated, service_role;

commit;
