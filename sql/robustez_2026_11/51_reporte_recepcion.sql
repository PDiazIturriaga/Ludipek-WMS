-- =====================================================================
-- LUDIPEK WMS · 51 DATOS DEL RESUMEN EJECUTIVO DE RECEPCIÓN (Excel)      (requiere 46)
-- Todo lo recibido de una OC (todas sus recepciones, contenedores y días) o de una recepción
-- libre (CONT:xxx), con lo pedido en la OC y en el PL por SKU. El PC arma el Excel con esto.
-- Se puede ejecutar más de una vez.
-- =====================================================================
begin;

create or replace function public.wms_reporte_recepcion(p_bodega text, p_numero_oc text default null, p_clave text default null)
returns jsonb language sql stable security definer set search_path = public as $$
  with oc as (select public.wms_numero_oc(p_numero_oc) n),
  asns as (
    select a.* from asn_cabecera a, oc
     where (oc.n is not null and public.wms_numero_oc(a.numero_oc) = oc.n)
        or (p_clave ~ '^ASN:' and a.id = substring(p_clave from 5)::bigint)
  ),
  r as (
    select x.* from registro_recepcion x
     where x.bodega = public.wms_bodega_valida(p_bodega)
       and ((exists (select 1 from asns) and x.asn_id in (select id from asns))
            or (p_clave is not null and public.wms_clave_recepcion(x.asn_id, x.contenedor) = p_clave))
  ),
  desc_sku as (
    select upper(m.sku) sku, max(m.descripcion) descripcion
      from maestra_sku m where upper(m.sku) in (select upper(btrim(sku)) from r)
       and nullif(btrim(m.descripcion), '') is not null
     group by 1
  )
  select jsonb_build_object(
    'numero_oc', (select max(numero_oc) from asns),
    'proveedor', (select max(proveedor) from asns),
    'contenedor', coalesce((select string_agg(distinct nullif(btrim(contenedor_referencia), ''), ', ') from asns),
                           (select string_agg(distinct contenedor, ', ') from r where contenedor !~* '^PO-')),
    'bodega', public.wms_bodega_valida(p_bodega),
    'cargada_ns', case when exists (select 1 from asns) then public.wms_oc_estado_ns_recepcion((select max(numero_oc) from asns)) end,
    'estado_oc', (select string_agg(distinct estado, ', ') from asns),
    'nota_oc', (select n.nota from wms_oc_netsuite n, oc where n.numero_oc = oc.n),
    'pallets', (select count(distinct lpn) from r),
    'lineas', coalesce((
      select jsonb_agg(jsonb_build_object(
               'fecha', z.fecha, 'sku', z.sku, 'descripcion', coalesce(d.descripcion, z.sku), 'lote', z.lote,
               'vencimiento', z.venc, 'contenedor', z.contenedor, 'cajas', z.cajas, 'unidades', z.unidades,
               'pallets', z.pallets, 'operadores', z.operadores, 'estado_pallet', z.qa)
             order by z.fecha, z.sku, z.lote)
        from (select (coalesce(x.fecha_recepcion, x.created_at) at time zone 'America/Santiago')::date fecha,
                     upper(btrim(x.sku)) sku, coalesce(nullif(btrim(x.lote), ''), 'S/L') lote,
                     max(x.fecha_vencimiento_cl) venc,
                     string_agg(distinct case when x.contenedor ~* '^PO-' then null else x.contenedor end, ', ') contenedor,
                     sum(x.cajas)::int cajas, sum(x.unidades_totales)::int unidades, count(distinct x.lpn)::int pallets,
                     string_agg(distinct x.operador, ', ') operadores, string_agg(distinct x.estado_pallet, ', ') qa
                from r x group by 1, 2, 3) z
        left join desc_sku d on d.sku = z.sku), '[]'::jsonb),
    'oc', coalesce((
      select jsonb_agg(jsonb_build_object('sku', upper(d.sku), 'descripcion', max_desc,
                                          'unidades_oc', uoc, 'unidades_pl', upl, 'cajas_oc', coc) order by d.sku)
        from (select upper(sku) sku, max(descripcion_proveedor) max_desc,
                     sum(coalesce(unidades_oc, unidades_esperadas))::int uoc, sum(unidades_packing_list)::int upl,
                     sum(cajas_esperadas)::int coc
                from asn_detalle where asn_id in (select id from asns) group by 1) d), '[]'::jsonb)
  );
$$;

revoke execute on function public.wms_reporte_recepcion(text, text, text) from public, anon;
grant execute on function public.wms_reporte_recepcion(text, text, text) to authenticated, service_role;

commit;
