-- =====================================================================================
-- 57 · Asignar contenedor a LPN ya recibidos + reporte por contenedor
--   Caso: se recibió parcial una OC sin escribir el contenedor. Desde el PC (Recepción ›
--   Historial) se marcan los LPN, se les asigna el contenedor y se saca el Resumen Excel
--   solo de ese contenedor.
--   Ejecutar completo en Supabase (SQL editor). Se puede ejecutar más de una vez.
-- =====================================================================================

-- 1) Asignar (o corregir) el contenedor de LPN ya recibidos -----------------------------
--    p_ids: id de registro_recepcion (lo que envía el PC) · p_lpns: alternativa por código LPN
create or replace function public.wms_recepcion_asignar_contenedor(
  p_bodega text, p_contenedor text, p_ids bigint[] default null, p_lpns text[] default null,
  p_usuario text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_bodega  text := public.wms_bodega_valida(p_bodega);
  v_cont    text := public.wms_contenedor_normal(p_contenedor);
  v_usuario text := public.wms_contexto(p_usuario, 'recepcion_asignar_contenedor');
  v_ids     bigint[] := coalesce(p_ids, '{}');
  v_lpns    text[] := (select coalesce(array_agg(distinct upper(btrim(x))), '{}')
                         from unnest(coalesce(p_lpns, '{}')) x where nullif(btrim(x), '') is not null);
  v_antes   text;
  v_filas   int;
  v_cant    int;
begin
  if v_cont is null then
    raise exception 'WMS: escriba el número de contenedor';
  end if;
  if cardinality(v_ids) = 0 and cardinality(v_lpns) = 0 then
    raise exception 'WMS: no hay LPN marcados';
  end if;

  select string_agg(distinct coalesce(nullif(btrim(r.contenedor), ''), 'vacío'), ', ')
    into v_antes
    from registro_recepcion r
   where r.bodega = v_bodega
     and (r.id = any(v_ids) or upper(btrim(r.lpn)) = any(v_lpns));

  with u as (
    update registro_recepcion r
       set contenedor = v_cont,
           observaciones = left(concat_ws(' | ', nullif(btrim(r.observaciones), ''),
                              format('Contenedor %s asignado por %s el %s (antes: %s)', v_cont, coalesce(v_usuario, '?'),
                                     to_char(now() at time zone 'America/Santiago', 'DD-MM-YYYY HH24:MI'),
                                     coalesce(nullif(btrim(r.contenedor), ''), 'vacío'))), 2000)
     where r.bodega = v_bodega
       and (r.id = any(v_ids) or upper(btrim(r.lpn)) = any(v_lpns))
       and coalesce(r.contenedor, '') is distinct from v_cont
    returning r.lpn
  )
  select count(*), count(distinct lpn) into v_filas, v_cant from u;

  return jsonb_build_object('contenedor', v_cont, 'filas', v_filas, 'lpns', v_cant, 'antes', v_antes);
end $$;

-- 2) Contenedores recibidos de una OC (para elegir el reporte) --------------------------
create or replace function public.wms_recepcion_contenedores(p_bodega text, p_numero_oc text)
returns table(contenedor text, lpns int, unidades int, desde timestamptz, hasta timestamptz)
language sql stable security definer set search_path = public as $$
  select coalesce(case when r.contenedor ~* '^PO-' or upper(btrim(r.contenedor)) = 'SIN-CONTENEDOR' then null
                       else nullif(btrim(r.contenedor), '') end, 'SIN CONTENEDOR'),
         count(distinct r.lpn)::int, coalesce(sum(r.unidades_totales), 0)::int,
         min(coalesce(r.fecha_recepcion, r.created_at)), max(coalesce(r.fecha_recepcion, r.created_at))
    from registro_recepcion r
    join asn_cabecera a on a.id = r.asn_id
   where r.bodega = public.wms_bodega_valida(p_bodega)
     and public.wms_numero_oc(a.numero_oc) = public.wms_numero_oc(p_numero_oc)
   group by 1
   order by 4;
$$;

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
                                          'cajas_oc', coc) order by d.sku)
        from (select upper(sku) sku, max(descripcion_proveedor) max_desc,
                     sum(coalesce(unidades_oc, unidades_esperadas))::int uoc, sum(unidades_packing_list)::int upl,
                     sum(cajas_esperadas)::int coc
                from asn_detalle where asn_id in (select id from asns) group by 1) d), '[]'::jsonb)
  );
$$;

grant execute on function public.wms_recepcion_asignar_contenedor(text, text, bigint[], text[], text) to authenticated, service_role;
grant execute on function public.wms_recepcion_contenedores(text, text) to authenticated, service_role;
grant execute on function public.wms_reporte_recepcion(text, text, text, text) to authenticated, service_role;
notify pgrst, 'reload schema';

-- Revisión (opcional): contenedores recibidos de una OC
-- select * from public.wms_recepcion_contenedores('Bodega Santiago', '2141');
