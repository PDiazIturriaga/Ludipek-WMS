-- =====================================================================================
-- 57b · Reporte de recepción por contenedor (Resumen Excel y acta parcial por contenedor)
--   PARTE 2 de 2 (antes ejecute 57a_asignar_contenedor_lpn.sql).
--   Copie TODO el archivo (Ctrl+A, Ctrl+C) en el SQL editor de Supabase y ejecute.
--   El archivo debe terminar en la línea "-- FIN 57b"; si no la ve en el editor, se cortó al copiar.
-- =====================================================================================

-- 3) Reporte de recepción: ahora acepta p_contenedor (solo lo recibido en ese contenedor) -
drop function if exists public.wms_reporte_recepcion(text, text, text);
create or replace function public.wms_reporte_recepcion(p_bodega text, p_numero_oc text default null,
                                                        p_clave text default null, p_contenedor text default null)
returns jsonb language sql stable security definer set search_path = public as $$
  with oc as (select public.wms_numero_oc(p_numero_oc) n),
  filtro as (select public.wms_contenedor_normal(p_contenedor) c),
  asns as (
    select a.* from asn_cabecera a, oc
     where (oc.n is not null and public.wms_numero_oc(a.numero_oc) = oc.n)
        or (p_clave ~ '^ASN:' and a.id = substring(p_clave from 5)::bigint)
  ),
  r as (
    select x.* from registro_recepcion x, filtro f
     where x.bodega = public.wms_bodega_valida(p_bodega)
       and ((exists (select 1 from asns) and x.asn_id in (select id from asns))
            or (p_clave is not null and public.wms_clave_recepcion(x.asn_id, x.contenedor) = p_clave))
       and (f.c is null or public.wms_contenedor_normal(x.contenedor) = f.c
            or (f.c = 'SINCONTENEDOR' and (public.wms_contenedor_normal(x.contenedor) is null
                                          or x.contenedor ~* '^PO-' or x.contenedor = 'SIN-CONTENEDOR')))
  ),
  pl as (   -- packing list de ese contenedor (si se cargó)
    select upper(d.sku) sku, sum(d.unidades)::int unidades
      from wms_pl_contenedores p
      join wms_pl_contenedor_detalle d on d.pl_id = p.id, filtro f, oc
     where f.c is not null and p.contenedor = f.c
       and (oc.n is null or p.numero_oc = oc.n or p.asn_id in (select id from asns))
     group by 1
  ),
  rec_oc as (   -- recibido acumulado de toda la OC (todos los contenedores), para el pendiente
    select upper(btrim(x.sku)) sku, sum(x.unidades_totales)::int unidades, sum(x.cajas)::int cajas
      from registro_recepcion x
     where x.bodega = public.wms_bodega_valida(p_bodega) and x.asn_id in (select id from asns)
     group by 1
  ),
  desc_sku as (
    select upper(m.sku) sku, max(m.descripcion) descripcion
      from maestra_sku m where upper(m.sku) in (select upper(btrim(sku)) from r)
       and nullif(btrim(m.descripcion), '') is not null
     group by 1
  )
  select jsonb_build_object(
    'numero_oc', (select max(numero_oc) from asns),
    'codigo_asn', (select string_agg(distinct codigo_asn, ' ') from asns),
    'proveedor', (select max(proveedor) from asns),
    'contenedor', coalesce((select case when c = 'SINCONTENEDOR' then 'SIN CONTENEDOR' else c end from filtro),
                           (select string_agg(distinct nullif(btrim(contenedor_referencia), ''), ', ') from asns),
                           (select string_agg(distinct contenedor, ', ') from r where contenedor !~* '^PO-' and contenedor <> 'SIN-CONTENEDOR')),
    'solo_contenedor', (select c from filtro) is not null,
    'pl_contenedor', exists (select 1 from pl),
    'bodega', public.wms_bodega_valida(p_bodega),
    'cargada_ns', case when exists (select 1 from asns) then public.wms_oc_estado_ns_recepcion((select max(numero_oc) from asns)) end,
    'estado_oc', (select string_agg(distinct estado, ', ') from asns),
    'nota_oc', (select n.nota from wms_oc_netsuite n, oc where n.numero_oc = oc.n),
    'pallets', (select count(distinct lpn) from r),
    'pallets_oc', (select count(distinct x.lpn) from registro_recepcion x
                    where x.bodega = public.wms_bodega_valida(p_bodega) and x.asn_id in (select id from asns)),
    'unidades_rec_oc', (select coalesce(sum(unidades), 0) from rec_oc),
    'fecha_desde', (select min(coalesce(fecha_recepcion, created_at)) from r),
    'fecha_hasta', (select max(coalesce(fecha_recepcion, created_at)) from r),
    'lineas', coalesce((
      select jsonb_agg(jsonb_build_object(
               'fecha', z.fecha, 'sku', z.sku, 'descripcion', coalesce(d.descripcion, z.sku), 'lote', z.lote,
               'vencimiento', z.venc, 'contenedor', z.contenedor, 'cajas', z.cajas, 'unidades', z.unidades,
               'pallets', z.pallets, 'operadores', z.operadores, 'estado_pallet', z.qa)
             order by z.fecha, z.sku, z.lote)
        from (select (coalesce(x.fecha_recepcion, x.created_at) at time zone 'America/Santiago')::date fecha,
                     upper(btrim(x.sku)) sku, coalesce(nullif(btrim(x.lote), ''), 'S/L') lote,
                     max(x.fecha_vencimiento_cl) venc,
                     string_agg(distinct case when x.contenedor ~* '^PO-' or x.contenedor = 'SIN-CONTENEDOR' then null
                                              else x.contenedor end, ', ') contenedor,
                     sum(x.cajas)::int cajas, sum(x.unidades_totales)::int unidades, count(distinct x.lpn)::int pallets,
                     string_agg(distinct x.operador, ', ') operadores, string_agg(distinct x.estado_pallet, ', ') qa
                from r x group by 1, 2, 3) z
        left join desc_sku d on d.sku = z.sku), '[]'::jsonb),
    'oc', coalesce((
      select jsonb_agg(jsonb_build_object('sku', upper(d.sku), 'descripcion', max_desc,
                                          'unidades_oc', uoc,
                                          'unidades_pl', case when exists (select 1 from pl)
                                                              then coalesce((select pl.unidades from pl where pl.sku = upper(d.sku)), 0)
                                                              else upl end,
                                          'cajas_oc', coc,
                                          'unidades_rec_oc', coalesce((select ro.unidades from rec_oc ro where ro.sku = upper(d.sku)), 0))
                       order by d.sku)
        from (select upper(sku) sku, max(descripcion_proveedor) max_desc,
                     sum(coalesce(unidades_oc, unidades_esperadas))::int uoc, sum(unidades_packing_list)::int upl,
                     sum(cajas_esperadas)::int coc
                from asn_detalle where asn_id in (select id from asns) group by 1) d), '[]'::jsonb)
  );
$$;

grant execute on function public.wms_reporte_recepcion(text, text, text, text) to authenticated, service_role;
notify pgrst, 'reload schema';

-- Revisión (opcional): contenedores recibidos de una OC
-- select * from public.wms_recepcion_contenedores('Bodega Santiago', '2141');
-- FIN 57b
