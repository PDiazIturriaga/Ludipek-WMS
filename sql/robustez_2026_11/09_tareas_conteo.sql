-- =====================================================================
-- LUDIPEK WMS · 09 TAREAS DE CONTEO ASIGNADAS  (requiere 04)
-- Antes el PC guardaba "RACK A -> usuario" en wms_asignaciones_pasillo, pero
-- el celular nunca lo leía (y la tabla no deja leer a la app: RLS sin
-- políticas). Ahora una tarea de conteo es:
--   PASILLO : contar todas las ubicaciones con stock de un pasillo
--   VACIAS  : auditar las ubicaciones vacías de un pasillo
--   SKU     : conteo cíclico dirigido de un SKU (todas sus ubicaciones)
-- (el avance reconoce al operador por usuario o por nombre completo, como lo guarda el celular)
-- El celular ve sus tareas, y el avance se calcula solo con lo que registra.
-- =====================================================================
begin;

alter table public.wms_asignaciones_pasillo
  add column if not exists tipo text not null default 'PASILLO',
  add column if not exists sku text,
  add column if not exists creado_por text,
  add column if not exists creada_en timestamptz not null default now(),
  add column if not exists cerrada_en timestamptz,
  add column if not exists cerrada_por text;
alter table public.wms_asignaciones_pasillo alter column pasillo drop not null;

-- Datos antiguos: "RACK A" -> "A", estados unificados
update public.wms_asignaciones_pasillo
   set pasillo = upper(btrim(regexp_replace(pasillo, '^\s*RACK\s*', '', 'i')))
 where pasillo ~* '^\s*RACK';
update public.wms_asignaciones_pasillo
   set estado = case when upper(coalesce(estado, '')) in ('COMPLETADA', 'COMPLETADO', 'CERRADO', 'AUDITADO') then 'COMPLETADA'
                     when upper(coalesce(estado, '')) = 'ANULADA' then 'ANULADA'
                     else 'PENDIENTE' end;
update public.wms_asignaciones_pasillo set bodega = 'Bodega Santiago' where bodega is null;
update public.wms_asignaciones_pasillo set usuario = upper(btrim(usuario));

do $$ begin
  alter table public.wms_asignaciones_pasillo add constraint ck_tarea_tipo check (tipo in ('PASILLO', 'VACIAS', 'SKU'));
exception when duplicate_object then null; end $$;
do $$ begin
  alter table public.wms_asignaciones_pasillo add constraint ck_tarea_estado check (estado in ('PENDIENTE', 'EN_PROCESO', 'COMPLETADA', 'ANULADA'));
exception when duplicate_object then null; end $$;

create index if not exists idx_tareas_conteo_usuario on public.wms_asignaciones_pasillo (bodega, usuario, estado);

-- Fecha guardada como texto en inventario (columna "fecha"): conversión que nunca falla
create or replace function public.wms_ts_seguro(p text)
returns timestamptz language plpgsql immutable as $$
begin
  return p::timestamptz;
exception when others then
  return null;
end $$;

-- ---------------------------------------------------------------------
-- Crear tarea
-- ---------------------------------------------------------------------
create or replace function public.wms_crear_tarea_conteo(
  p_bodega text, p_tipo text, p_pasillo text, p_sku text, p_usuario text, p_creado_por text default null)
returns bigint language plpgsql security definer set search_path = public as $$
declare
  v_bodega text := public.wms_bodega_valida(p_bodega);
  v_tipo text := upper(btrim(coalesce(p_tipo, 'PASILLO')));
  v_pasillo text := nullif(upper(btrim(regexp_replace(coalesce(p_pasillo, ''), '^\s*RACK\s*', '', 'i'))), '');
  v_sku text := nullif(public.wms_normalizar_sku(p_sku), '');
  v_usuario text := upper(btrim(coalesce(p_usuario, '')));
  v_id bigint;
begin
  if v_tipo not in ('PASILLO', 'VACIAS', 'SKU') then
    raise exception 'WMS: tipo de tarea inválido %', p_tipo;
  end if;
  if not exists (select 1 from wms_usuarios where upper(usuario) = v_usuario and coalesce(activo, true)) then
    raise exception 'WMS: el usuario % no existe o está inactivo', p_usuario;
  end if;
  if v_tipo in ('PASILLO', 'VACIAS') then
    if v_pasillo is null or not exists (select 1 from bodega_ubicaciones
                                        where bodega = v_bodega and upper(codigo_ubicacion) like v_pasillo || '-%') then
      raise exception 'WMS: el pasillo % no existe en %', coalesce(v_pasillo, '(vacío)'), v_bodega;
    end if;
    v_sku := null;
  else
    if v_sku is null or not exists (select 1 from maestra_sku where upper(sku) = v_sku) then
      raise exception 'WMS: el SKU % no existe en la maestra', coalesce(v_sku, '(vacío)');
    end if;
    v_pasillo := null;
  end if;
  if exists (select 1 from wms_asignaciones_pasillo
             where bodega = v_bodega and usuario = v_usuario and tipo = v_tipo
               and coalesce(pasillo, '') = coalesce(v_pasillo, '') and coalesce(sku, '') = coalesce(v_sku, '')
               and estado in ('PENDIENTE', 'EN_PROCESO')) then
    raise exception 'WMS: % ya tiene esa tarea abierta', v_usuario;
  end if;
  insert into wms_asignaciones_pasillo (bodega, tipo, pasillo, sku, usuario, estado, fecha_asignacion, creado_por)
  values (v_bodega, v_tipo, v_pasillo, v_sku, v_usuario, 'PENDIENTE', to_char(now(), 'YYYY-MM-DD HH24:MI'),
          coalesce(nullif(upper(btrim(p_creado_por)), ''), 'PC'))
  returning id into v_id;
  return v_id;
end $$;

-- ---------------------------------------------------------------------
-- Tareas con avance (PC: todas las de la bodega · celular: las del usuario)
-- ---------------------------------------------------------------------
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
           when 'VACIAS' then (select count(*) from bodega_ubicaciones u
                               where u.bodega = t.bodega and upper(u.codigo_ubicacion) like t.pasillo || '-%'
                                 and not exists (select 1 from bodega_inventario_ubicacion i
                                                 where i.bodega = u.bodega and i.codigo_ubicacion = upper(u.codigo_ubicacion)))
           else (select count(*) from bodega_inventario_ubicacion i
                 where i.bodega = t.bodega and i.sku = t.sku and i.cantidad_unidades > 0)
         end::int,
         case t.tipo
           when 'PASILLO' then (select count(distinct x.ub) from (
                                  select i.codigo_ubicacion ub from bodega_inventario_ubicacion i
                                   where i.bodega = t.bodega and i.codigo_ubicacion like t.pasillo || '-%'
                                     and upper(coalesce(i.auditor, '')) in (t.usuario, t.nombre)
                                     and public.wms_ts_seguro(i.fecha) >= t.creada_en
                                  union
                                  select h.ubicacion_destino from historial_movimientos h
                                   where h.bodega = t.bodega and h.tipo_movimiento like 'AJUSTE_CICLICO%'
                                     and h.ubicacion_destino like t.pasillo || '-%'
                                     and upper(coalesce(h.usuario, '')) in (t.usuario, t.nombre) and h.fecha >= t.creada_en) x)
           when 'VACIAS' then (select count(distinct v.codigo_ubicacion) from auditoria_ubicaciones_vacias v
                               where coalesce(v.bodega, 'Bodega Santiago') = t.bodega
                                 and upper(v.codigo_ubicacion) like t.pasillo || '-%'
                                 and upper(coalesce(v.auditor, '')) in (t.usuario, t.nombre) and v.fecha >= t.creada_en)
           else (select count(distinct c.codigo_ubicacion) from auditoria_ciclico_sku c
                 where coalesce(c.bodega, 'Bodega Santiago') = t.bodega and upper(c.sku) = t.sku
                   and upper(coalesce(c.auditor, '')) in (t.usuario, t.nombre) and c.fecha >= t.creada_en
                   and upper(c.estado_auditoria) <> 'PENDIENTE')
         end::int
  from t
  order by case t.estado when 'EN_PROCESO' then 0 when 'PENDIENTE' then 1 else 2 end, t.creada_en desc;
$$;

-- ---------------------------------------------------------------------
-- Cambiar estado: EN_PROCESO (el celular la abre), COMPLETADA, ANULADA
-- ---------------------------------------------------------------------
create or replace function public.wms_actualizar_tarea_conteo(p_id bigint, p_estado text, p_usuario text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  a record;
  v_estado text := upper(btrim(coalesce(p_estado, '')));
begin
  select * into a from wms_asignaciones_pasillo where id = p_id for update;
  if not found then raise exception 'WMS: la tarea % no existe', p_id; end if;
  if v_estado not in ('EN_PROCESO', 'COMPLETADA', 'ANULADA') then
    raise exception 'WMS: estado inválido %', p_estado;
  end if;
  if a.estado in ('COMPLETADA', 'ANULADA') then
    raise exception 'WMS: la tarea ya está %', a.estado;
  end if;
  update wms_asignaciones_pasillo
     set estado = v_estado,
         cerrada_en = case when v_estado in ('COMPLETADA', 'ANULADA') then now() end,
         cerrada_por = case when v_estado in ('COMPLETADA', 'ANULADA') then coalesce(nullif(upper(btrim(p_usuario)), ''), 'APP') end
   where id = p_id;
  return jsonb_build_object('id', p_id, 'estado', v_estado);
end $$;

-- Si un usuario se desactiva, sus tareas abiertas quedan visibles en el PC para reasignarlas
grant execute on function public.wms_crear_tarea_conteo(text, text, text, text, text, text) to anon, authenticated, service_role;
grant execute on function public.wms_tareas_conteo(text, text, boolean) to anon, authenticated, service_role;
grant execute on function public.wms_actualizar_tarea_conteo(bigint, text, text) to anon, authenticated, service_role;

commit;
