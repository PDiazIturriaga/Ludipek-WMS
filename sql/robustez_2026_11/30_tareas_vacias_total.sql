-- =====================================================================
-- LUDIPEK WMS · 30 TAREAS "AUDITAR VACÍAS": MISMO TOTAL QUE EL CELULAR  (requiere 20)
-- El PC decía "0/11" en el pasillo E y el celular mostraba 6: el PC contaba también las
-- ubicaciones ya marcadas como "ocupada pendiente de inventario" (lista roja del celular),
-- que el celular no muestra porque ya fueron revisadas.
-- Ahora el total de la tarea = ubicaciones sin stock del pasillo, sin las que ya estaban
-- marcadas como ocupadas ANTES de crear la tarea. Las que el operador marca como ocupadas
-- durante la tarea cuentan como revisadas.
-- =====================================================================
begin;

-- Ubicaciones que corresponde revisar en una tarea de vacías
create or replace function public.wms_vacias_de_tarea(p_bodega text, p_pasillo text, p_desde timestamptz)
returns table (ub text) language sql stable security definer set search_path = public as $$
  select upper(u.codigo_ubicacion)
  from bodega_ubicaciones u
  where u.bodega = p_bodega and upper(u.codigo_ubicacion) like upper(p_pasillo) || '-%'
    and not exists (select 1 from bodega_inventario_ubicacion i
                    where i.bodega = u.bodega and upper(i.codigo_ubicacion) = upper(u.codigo_ubicacion)
                      and i.cantidad_unidades > 0)
    and not exists (select 1 from historial_movimientos h
                    where h.tipo_movimiento = 'ALERTA_VACIA_OCUPADA'
                      and upper(h.ubicacion_destino) = upper(u.codigo_ubicacion)
                      and coalesce(h.bodega, p_bodega) = p_bodega
                      and public.wms_ts_app(h.fecha) < p_desde);
$$;
grant execute on function public.wms_vacias_de_tarea(text, text, timestamptz) to anon, authenticated, service_role;

create or replace function public.wms_tareas_conteo(
  p_bodega text, p_usuario text default null, p_solo_abiertas boolean default true)
returns table (id bigint, tipo text, pasillo text, sku text, descripcion text, usuario text, estado text,
               creada_en timestamptz, cerrada_en timestamptz, total integer, avance integer)
language sql stable security definer set search_path = public as $$
  with t as (
    select a.*, coalesce((select upper(btrim(w.nombre_completo)) from wms_usuarios w where upper(w.usuario) = a.usuario limit 1), a.usuario) as nombre
    from wms_asignaciones_pasillo a
    where a.bodega = public.wms_bodega_valida(p_bodega)
      and (p_usuario is null or a.usuario = upper(btrim(p_usuario)))
      and (not p_solo_abiertas or a.estado in ('PENDIENTE', 'EN_PROCESO')
           or a.cerrada_en > now() - interval '1 day')
  )
  select t.id::bigint, t.tipo, t.pasillo, t.sku,
         (select m.descripcion from maestra_sku m where upper(m.sku) = t.sku limit 1),
         t.usuario, t.estado, t.creada_en, t.cerrada_en,
         case t.tipo
           when 'PASILLO' then (select count(distinct i.codigo_ubicacion) from bodega_inventario_ubicacion i
                                where i.bodega = t.bodega and i.codigo_ubicacion like t.pasillo || '-%' and i.cantidad_unidades > 0)
           when 'VACIAS' then (select count(*) from public.wms_vacias_de_tarea(t.bodega, t.pasillo, t.creada_en))
           else (select count(distinct i.codigo_ubicacion) from bodega_inventario_ubicacion i
                 where i.bodega = t.bodega and i.sku = t.sku and i.cantidad_unidades > 0)
         end::int,
         case t.tipo
           when 'PASILLO' then (select count(distinct x.ub) from (
                                  select i.codigo_ubicacion ub from bodega_inventario_ubicacion i
                                   where i.bodega = t.bodega and i.codigo_ubicacion like t.pasillo || '-%'
                                     and upper(coalesce(i.auditor, '')) in (t.usuario, t.nombre)
                                     and public.wms_ts_app(public.wms_ts_seguro(i.fecha)) >= t.creada_en
                                  union
                                  select h.ubicacion_destino from historial_movimientos h
                                   where h.bodega = t.bodega and h.tipo_movimiento like 'AJUSTE_CICLICO%'
                                     and h.ubicacion_destino like t.pasillo || '-%'
                                     and upper(coalesce(h.usuario, '')) in (t.usuario, t.nombre) and h.fecha >= t.creada_en) x)
           when 'VACIAS' then (select count(*) from public.wms_vacias_de_tarea(t.bodega, t.pasillo, t.creada_en) z
                               where exists (select 1 from auditoria_ubicaciones_vacias v
                                             where upper(v.codigo_ubicacion) = z.ub
                                               and coalesce(v.bodega, 'Bodega Santiago') = t.bodega
                                               and upper(coalesce(to_jsonb(v)->>'resultado_auditoria', to_jsonb(v)->>'estado', '')) <> 'SIN_REVISAR'
                                               and upper(coalesce(v.auditor, '')) in (t.usuario, t.nombre)
                                               and public.wms_ts_app(v.fecha) >= t.creada_en)
                                  or exists (select 1 from historial_movimientos h
                                             where h.tipo_movimiento = 'ALERTA_VACIA_OCUPADA'
                                               and upper(h.ubicacion_destino) = z.ub
                                               and coalesce(h.bodega, t.bodega) = t.bodega
                                               and public.wms_ts_app(h.fecha) >= t.creada_en))
           else (select count(distinct c.codigo_ubicacion) from auditoria_ciclico_sku c
                 where coalesce(c.bodega, 'Bodega Santiago') = t.bodega and upper(c.sku) = t.sku
                   and upper(coalesce(c.auditor, '')) in (t.usuario, t.nombre)
                   and public.wms_ts_app(c.fecha) >= t.creada_en
                   and upper(coalesce(c.estado_auditoria, '')) not in ('PENDIENTE', 'SIN_REVISAR', ''))
         end::int
  from t
  order by case t.estado when 'EN_PROCESO' then 0 when 'PENDIENTE' then 1 else 2 end, t.creada_en desc;
$$;
grant execute on function public.wms_tareas_conteo(text, text, boolean) to anon, authenticated, service_role;

commit;
