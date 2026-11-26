-- =====================================================================================
-- 57a · Asignar contenedor a LPN ya recibidos + lista de contenedores de una OC
--   PARTE 1 de 2. Después ejecute 57b_reporte_recepcion_contenedor.sql.
--   Copie TODO el archivo (Ctrl+A, Ctrl+C) en el SQL editor de Supabase y ejecute.
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

grant execute on function public.wms_recepcion_asignar_contenedor(text, text, bigint[], text[], text) to authenticated, service_role;
grant execute on function public.wms_recepcion_contenedores(text, text) to authenticated, service_role;
-- select * from public.wms_recepcion_contenedores('Bodega Santiago', '2141');
notify pgrst, 'reload schema';
-- FIN 57a
