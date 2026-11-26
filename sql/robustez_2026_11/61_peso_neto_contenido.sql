-- =====================================================================================
-- 61 · Peso NETO del despacho = contenido del producto (sin lata/envase ni pallet)
--   Prioridad del kg neto por unidad: 1) Kg/un del pedido  2) contenido neto de la ficha logística
--   3) peso de la maestra (solo si no hay nada más). El peso BRUTO no cambia (ficha / balanza).
--   Requiere 58a, 58b, 59a y 59b. Se puede ejecutar más de una vez.
--   Copie TODO el archivo (Ctrl+A). Debe terminar en "-- FIN 61".
-- =====================================================================================
alter table public.wms_sku_logistica add column if not exists contenido_neto_kg numeric;   -- kg de producto por unidad
update public.wms_sku_logistica set contenido_neto_kg = case
         when nombre ~* '(^|[^0-9])400\s*G' then 0.4
         when nombre ~* '(^|[^0-9])200\s*G' then 0.2
         when nombre ~* '(^|[^0-9])40\s*G'  then 0.04 end where contenido_neto_kg is null;
drop view if exists public.wms_sku_logistica_calc;   -- se recrea con la columna nueva
create view public.wms_sku_logistica_calc with (security_invoker = true) as
select g.*,
       (g.pallet_unidades::numeric / nullif(g.display_unidades, 0) / nullif(g.displays_por_cama, 0)) camas_pallet,
       round((g.pallet_alto_cm - g.madera_alto_cm)
             / nullif(ceil(g.pallet_unidades::numeric / nullif(g.display_unidades, 0) / nullif(g.displays_por_cama, 0)), 0), 2) cama_alto_cm,
       round(coalesce(g.display_peso_gr / 1000.0 / nullif(g.display_unidades, 0),
                      (g.pallet_peso_kg - 25) / nullif(g.pallet_unidades, 0)), 5) kg_bruto_unidad,
       case when abs(g.display_alto_cm - (g.pallet_alto_cm - g.madera_alto_cm)
                     / nullif(ceil(g.pallet_unidades::numeric / nullif(g.display_unidades, 0) / nullif(g.displays_por_cama, 0)), 0)) > 1
            then 'Alto del display no cuadra con el pallet (se usa el del pallet)' end observacion
  from public.wms_sku_logistica g;
grant select on public.wms_sku_logistica_calc to authenticated, service_role;

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
  peso_un as (   -- kg NETO por unidad (contenido): pedido > ficha logística > maestra; kg_maestra se usa para el bruto sin ficha
    select e.sku, coalesce(p.kg_un, gl.contenido_neto_kg, nullif(e.peso_unidad_kg, 0), 0) kg,
           coalesce(nullif(e.peso_unidad_kg, 0), p.kg_un, gl.contenido_neto_kg, 0) kg_maestra
      from emp e
      left join wms_despacho_pedido p on p.despacho_id = p_id and upper(p.sku) = e.sku
      left join wms_sku_logistica gl on upper(gl.sku) = e.sku
  ),
  ficha as (   -- por línea del pallet según la ficha logística del SKU (59a)
    select f.lpn, g.sku is not null tiene,
           ceil(f.unidades::numeric / nullif(g.display_unidades, 0) / nullif(g.displays_por_cama, 0)) * g.cama_alto_cm / 100.0 alto_m,
           f.unidades * g.kg_bruto_unidad peso_kg, g.pallet_largo_cm / 100.0 largo, g.pallet_ancho_cm / 100.0 ancho,
           g.madera_alto_cm / 100.0 madera
      from filas f left join wms_sku_logistica_calc g on upper(g.sku) = f.sku
  ),
  ficha_lpn as (
    select lpn, bool_and(tiene) completa, max(madera) + sum(alto_m) alto, sum(peso_kg) peso, max(largo) largo, max(ancho) ancho
      from ficha group by lpn
  ),
  lpn_tot as (   -- por pallet: unidades, peso neto, medidas
    select l.lpn, coalesce(sum(f.unidades), 0)::int unidades,
           round(coalesce(sum(f.unidades * coalesce(w.kg, 0)), 0), 2) peso_neto,
           round(coalesce(sum(f.unidades * coalesce(w.kg_maestra, 0)), 0), 2) peso_producto,   -- con envase (maestra)
           l.alto_m alto_medido, l.peso_bruto_kg balanza
      from wms_despacho_lpn l
      left join filas f on f.lpn = l.lpn
      left join peso_un w on w.sku = f.sku
     where l.despacho_id = p_id
     group by l.lpn, l.alto_m, l.peso_bruto_kg
  ),
  lpn_calc as (
    select t.lpn, t.unidades, t.peso_neto, t.balanza,
           round(coalesce(t.alto_medido, case when fl.completa then fl.alto end, (select pallet_alto_m from d)), 3) alto,
           case when t.alto_medido is not null then 'MEDIDO' when fl.completa then 'FICHA'
                when (select pallet_alto_m from d) is not null then 'GENERAL' end origen_medida,
           round(coalesce(case when fl.completa then fl.largo end, (select pallet_largo_m from d))
                 * coalesce(case when fl.completa then fl.ancho end, (select pallet_ancho_m from d))
                 * coalesce(t.alto_medido, case when fl.completa then fl.alto end, (select pallet_alto_m from d)), 3) m3,
           round(coalesce(t.balanza, case when fl.completa then fl.peso + coalesce((select tara_pallet_kg from d), 0) end,
                          t.peso_producto + coalesce((select tara_pallet_kg from d), 0)), 1) peso_bruto,
           case when t.balanza is not null then 'BALANZA' when fl.completa then 'FICHA' else 'MAESTRA + TARA' end origen_peso
      from lpn_tot t left join ficha_lpn fl on fl.lpn = t.lpn
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
               'origen_medida', c.origen_medida, 'origen_peso', c.origen_peso,
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
      'pallets_con_ficha', (select count(*) from lpn_calc where origen_medida = 'FICHA'),
      'skus_sin_peso', (select count(*) from por_sku x join peso_un w on w.sku = x.sku where coalesce(w.kg, 0) = 0),
      'pallet_largo_m', (select pallet_largo_m from d), 'pallet_ancho_m', (select pallet_ancho_m from d),
      'pallet_alto_m', (select pallet_alto_m from d), 'tara_pallet_kg', (select tara_pallet_kg from d))
  );
$$;

grant execute on function public.wms_despacho_detalle(bigint) to anon, authenticated, service_role;
notify pgrst, 'reload schema';
-- FIN 61
