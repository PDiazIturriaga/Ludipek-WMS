-- =====================================================================================
-- 58b · Detalle del despacho con peso neto, peso bruto y m³ (PARTE 2 de 3; antes ejecute 58a)
--   Peso neto por unidad: maestra (peso_kg / peso_gr); si no tiene, el Kg/un del pedido.
--   Peso bruto del pallet: el de balanza si se ingresó; si no, neto + tara del pallet.
--   m³ del pallet: largo x ancho x alto (alto del pallet si se midió; si no, el alto general).
--   Copie TODO el archivo (Ctrl+A) en el SQL editor de Supabase. Debe terminar en "-- FIN 58b".
-- =====================================================================================
create or replace function public.wms_despacho_detalle(p_id bigint)
returns jsonb language sql stable security definer set search_path = public as $$
  with d as (select * from wms_despachos where id = p_id),
  filas as (   -- cada fila de stock escaneada (sku, lote, vencimiento, unidades) con su LPN
    select l.lpn, l.ubicacion, upper(btrim(f->>'sku')) sku, coalesce(nullif(btrim(f->>'lote'), ''), 'S/L') lote,
           coalesce(nullif(btrim(f->>'fecha_vencimiento_cl'), ''), 'S/F') vencimiento,
           coalesce((f->>'cantidad_unidades')::numeric, 0)::int unidades
      from wms_despacho_lpn l, jsonb_array_elements(coalesce(l.descontado, l.filas)) f
     where l.despacho_id = p_id
  ),
  emp as (select s.sku, e.* from (select distinct sku from filas union select upper(sku) from wms_despacho_pedido where despacho_id = p_id) s,
                 lateral public.wms_empaque_sku(s.sku) e),
  peso_un as (   -- kg por unidad: maestra o, si no tiene, el pedido
    select e.sku, coalesce(nullif(e.peso_unidad_kg, 0), p.kg_un, 0) kg
      from emp e left join wms_despacho_pedido p on p.despacho_id = p_id and upper(p.sku) = e.sku
  ),
  lpn_tot as (   -- por pallet: unidades, peso neto, m³ y peso bruto
    select l.lpn, coalesce(sum(f.unidades), 0)::int unidades,
           round(coalesce(sum(f.unidades * coalesce(w.kg, 0)), 0), 2) peso_neto,
           coalesce(l.alto_m, (select pallet_alto_m from d)) alto,
           round((select pallet_largo_m * pallet_ancho_m from d) * coalesce(l.alto_m, (select pallet_alto_m from d)), 3) m3,
           l.peso_bruto_kg balanza
      from wms_despacho_lpn l
      left join filas f on f.lpn = l.lpn
      left join peso_un w on w.sku = f.sku
     where l.despacho_id = p_id
     group by l.lpn, l.alto_m, l.peso_bruto_kg
  ),
  lpn_calc as (
    select t.*, round(coalesce(t.balanza, t.peso_neto + coalesce((select tara_pallet_kg from d), 0)), 1) peso_bruto
      from lpn_tot t
  ),
  por_lote as (
    select f.sku, f.lote, f.vencimiento, sum(f.unidades)::int unidades, count(distinct f.lpn)::int pallets,
           string_agg(distinct f.lpn, ', ') lpns
      from filas f group by 1, 2, 3
  ),
  por_sku as (   -- m³ y peso bruto de cada pallet se reparten entre sus SKU según unidades
    select f.sku, sum(f.unidades)::int unidades, count(distinct f.lpn)::int pallets,
           round(sum(c.m3 * f.unidades / nullif(c.unidades, 0)), 3) m3,
           round(sum(c.peso_bruto * f.unidades / nullif(c.unidades, 0)), 1) peso_bruto
      from filas f join lpn_calc c on c.lpn = f.lpn group by 1
  ),
  skus as (select sku from por_sku union select upper(sku) from wms_despacho_pedido where despacho_id = p_id)
  select jsonb_build_object(
    'despacho', (select to_jsonb(d) from d),
    'sku', coalesce((
      select jsonb_agg(jsonb_build_object(
               'sku', s.sku,
               'descripcion', coalesce(p.descripcion, e.descripcion),
               'pedido_unidades', p.unidades, 'pedido_pallets', p.pallets, 'kg_un', w.kg,
               'unidades_pallet', p.unidades_pallet,
               'en_pedido', p.sku is not null,
               'pallets', coalesce(x.pallets, 0), 'unidades', coalesce(x.unidades, 0),
               'multiplo_caja', e.multiplo_caja, 'multiplo_display', e.multiplo_display,
               'empaque', public.wms_empaque_desglose(coalesce(x.unidades, 0), e.multiplo_caja, e.multiplo_display),
               'peso_kg', round(coalesce(x.unidades, 0) * coalesce(w.kg, 0), 2),
               'peso_bruto_kg', x.peso_bruto, 'm3', x.m3,
               'falta', greatest(0, coalesce(p.unidades, 0) - coalesce(x.unidades, 0)),
               'sobra', greatest(0, coalesce(x.unidades, 0) - coalesce(p.unidades, 0)),
               'lotes', coalesce((select jsonb_agg(jsonb_build_object(
                           'lote', pl.lote, 'vencimiento', pl.vencimiento, 'unidades', pl.unidades, 'pallets', pl.pallets,
                           'lpns', pl.lpns,
                           'empaque', public.wms_empaque_desglose(pl.unidades, e.multiplo_caja, e.multiplo_display))
                           order by pl.vencimiento, pl.lote)
                          from por_lote pl where pl.sku = s.sku), '[]'::jsonb))
             order by (p.sku is null), s.sku)
        from skus s
        left join wms_despacho_pedido p on p.despacho_id = p_id and upper(p.sku) = s.sku
        left join por_sku x on x.sku = s.sku
        left join emp e on e.sku = s.sku
        left join peso_un w on w.sku = s.sku), '[]'::jsonb),
    'lpns', coalesce((
      select jsonb_agg(jsonb_build_object(
               'lpn', l.lpn, 'ubicacion', l.ubicacion, 'escaneado_por', l.escaneado_por, 'escaneado_en', l.escaneado_en,
               'descontado', l.descontado is not null,
               'unidades', c.unidades, 'peso_neto_kg', c.peso_neto, 'peso_bruto_kg', c.peso_bruto,
               'peso_balanza', c.balanza is not null, 'alto_m', c.alto, 'alto_propio', l.alto_m is not null, 'm3', c.m3,
               'contenido', (select jsonb_agg(jsonb_build_object(
                                'sku', upper(f->>'sku'), 'lote', coalesce(nullif(f->>'lote', ''), 'S/L'),
                                'vencimiento', coalesce(nullif(f->>'fecha_vencimiento_cl', ''), 'S/F'),
                                'unidades', (f->>'cantidad_unidades')::numeric::int,
                                'peso_kg', round((f->>'cantidad_unidades')::numeric * coalesce(w.kg, 0), 2),
                                'empaque', public.wms_empaque_desglose((f->>'cantidad_unidades')::numeric::int,
                                                                       e.multiplo_caja, e.multiplo_display)))
                              from jsonb_array_elements(coalesce(l.descontado, l.filas)) f
                              left join emp e on e.sku = upper(btrim(f->>'sku'))
                              left join peso_un w on w.sku = upper(btrim(f->>'sku'))))
             order by l.escaneado_en desc)
        from wms_despacho_lpn l join lpn_calc c on c.lpn = l.lpn where l.despacho_id = p_id), '[]'::jsonb),
    'totales', jsonb_build_object(
      'pallets', (select count(*) from wms_despacho_lpn where despacho_id = p_id),
      'unidades', (select coalesce(sum(unidades), 0) from filas),
      'pedido_unidades', (select coalesce(sum(unidades), 0) from wms_despacho_pedido where despacho_id = p_id),
      'pedido_pallets', (select sum(pallets) from wms_despacho_pedido where despacho_id = p_id),
      'cajas', (select coalesce(sum((public.wms_empaque_desglose(x.unidades, e.multiplo_caja, e.multiplo_display)->>'cajas')::int), 0)
                  from por_sku x join emp e on e.sku = x.sku),
      'displays', (select coalesce(sum((public.wms_empaque_desglose(x.unidades, e.multiplo_caja, e.multiplo_display)->>'displays')::int), 0)
                     from por_sku x join emp e on e.sku = x.sku),
      'peso_kg', (select round(coalesce(sum(peso_neto), 0), 1) from lpn_calc),
      'peso_bruto_kg', (select round(coalesce(sum(peso_bruto), 0), 1) from lpn_calc),
      'm3', (select round(sum(m3), 2) from lpn_calc),
      'pallets_sin_alto', (select count(*) from lpn_calc where alto is null),
      'skus_sin_peso', (select count(*) from por_sku x join peso_un w on w.sku = x.sku where coalesce(w.kg, 0) = 0),
      'pallet_largo_m', (select pallet_largo_m from d), 'pallet_ancho_m', (select pallet_ancho_m from d),
      'pallet_alto_m', (select pallet_alto_m from d), 'tara_pallet_kg', (select tara_pallet_kg from d))
  );
$$;

grant execute on function public.wms_despacho_detalle(bigint) to anon, authenticated, service_role;
notify pgrst, 'reload schema';
-- FIN 58b
