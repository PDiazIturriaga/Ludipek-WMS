-- =====================================================================================
-- 62 · Contenedores con y sin guion (ej. DFSU713216-8 / DFSU7132168)
--   · "Asignar contenedor" guarda el número tal como se escribe (mayúsculas, sin espacios) y
--     corrige también los LPN que solo difieren en el guion (antes lo quitaba y no cambiaba nada).
--   · La lista de contenedores de una OC agrupa sin importar guiones ni espacios (antes salían
--     dos contenedores distintos). Requiere 57a. Se puede ejecutar más de una vez.
--   Copie TODO el archivo (Ctrl+A). Debe terminar en "-- FIN 62".
-- =====================================================================================

create or replace function public.wms_recepcion_asignar_contenedor(
  p_bodega text, p_contenedor text, p_ids bigint[] default null, p_lpns text[] default null,
  p_usuario text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_bodega  text := public.wms_bodega_valida(p_bodega);
  v_cont    text := nullif(upper(regexp_replace(btrim(coalesce(p_contenedor, '')), '\s+', '', 'g')), '');   -- como se escribió
  v_usuario text := public.wms_contexto(p_usuario, 'recepcion_asignar_contenedor');
  v_ids     bigint[] := coalesce(p_ids, '{}');
  v_lpns    text[] := (select coalesce(array_agg(distinct upper(btrim(x))), '{}')
                         from unnest(coalesce(p_lpns, '{}')) x where nullif(btrim(x), '') is not null);
  v_antes   text;
  v_filas   int;
  v_cant    int;
begin
  if public.wms_contenedor_normal(v_cont) is null then
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
       and coalesce(r.contenedor, '') is distinct from v_cont          -- también si solo cambia el guion
    returning r.lpn
  )
  select count(*), count(distinct lpn) into v_filas, v_cant from u;

  return jsonb_build_object('contenedor', v_cont, 'filas', v_filas, 'lpns', v_cant, 'antes', v_antes);
end $$;

-- Contenedores recibidos de una OC: uno solo aunque esté escrito con y sin guion
create or replace function public.wms_recepcion_contenedores(p_bodega text, p_numero_oc text)
returns table(contenedor text, lpns int, unidades int, desde timestamptz, hasta timestamptz)
language sql stable security definer set search_path = public as $$
  with x as (
    select case when r.contenedor ~* '^PO-' or upper(btrim(r.contenedor)) = 'SIN-CONTENEDOR' then null
                else nullif(upper(btrim(r.contenedor)), '') end cont,
           r.lpn, r.unidades_totales, coalesce(r.fecha_recepcion, r.created_at) f
      from registro_recepcion r
      join asn_cabecera a on a.id = r.asn_id
     where r.bodega = public.wms_bodega_valida(p_bodega)
       and public.wms_numero_oc(a.numero_oc) = public.wms_numero_oc(p_numero_oc)
  )
  select coalesce(mode() within group (order by x.cont), 'SIN CONTENEDOR'),     -- la forma más usada
         count(distinct x.lpn)::int, coalesce(sum(x.unidades_totales), 0)::int, min(x.f), max(x.f)
    from x
   group by public.wms_contenedor_normal(x.cont)
   order by 4;
$$;

grant execute on function public.wms_recepcion_asignar_contenedor(text, text, bigint[], text[], text) to authenticated, service_role;
grant execute on function public.wms_recepcion_contenedores(text, text) to authenticated, service_role;
notify pgrst, 'reload schema';

-- Revisión (opcional): LPN de una OC cuyo contenedor está escrito de más de una forma
-- select public.wms_contenedor_normal(r.contenedor) contenedor, string_agg(distinct r.contenedor, ' / ') formas, count(*) lpns
--   from registro_recepcion r join asn_cabecera a on a.id = r.asn_id
--  where public.wms_numero_oc(a.numero_oc) = public.wms_numero_oc('2141')
--  group by 1 having count(distinct r.contenedor) > 1;
-- FIN 62
