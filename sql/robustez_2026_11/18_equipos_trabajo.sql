-- =====================================================================
-- LUDIPEK WMS · 18 EQUIPOS DE TRABAJO Y ASIGNACIÓN DE OV POR EQUIPO  (requiere 07 y 08)
-- El supervisor ubica a cada usuario en un equipo desde el PC (Monitor de usuarios):
--   FARMACIA  -> recibe OV de farmacia (-FA) y OT de traslado
--   PICKING   -> recibe OV normales
--   PACKING · RECEPCION · INACTIVO -> no reciben OV
-- Generar olas YA NO asigna operador: las OV quedan "sin asignar" hasta que el
-- supervisor presiona "Cargar OV a los equipos" (wms_asignar_ovs_por_equipo).
-- Si un usuario se cambia de equipo, las OV que tenía y que no ha empezado
-- (sin unidades pickeadas) vuelven a la cola para repartirse de nuevo.
-- =====================================================================
begin;

alter table public.wms_usuarios
  add column if not exists equipo_trabajo text,
  add column if not exists equipo_actualizado_en timestamptz,
  add column if not exists equipo_actualizado_por text;

do $$ begin
  alter table public.wms_usuarios add constraint ck_usuario_equipo_trabajo
    check (equipo_trabajo is null or equipo_trabajo in ('FARMACIA', 'PICKING', 'PACKING', 'RECEPCION', 'INACTIVO'));
exception when duplicate_object then null; end $$;

-- Tipo de picking de una orden (misma regla que el celular)
create or replace function public.wms_tipo_picking_ov(p_numero text, p_canal text)
returns text language sql immutable as $$
  select case when upper(coalesce(p_numero, '')) like '%-FA' or upper(coalesce(p_numero, '')) like 'OT-%'
                   or upper(coalesce(p_canal, '')) like '%FARM%' then 'FARMACIA' else 'PICKING' end;
$$;

-- Orden de picking aún no empezada (se puede reasignar sin perder trabajo)
create or replace function public.wms_ov_sin_iniciar(p_orden_id bigint)
returns boolean language sql stable security definer set search_path = public as $$
  select upper(coalesce((select estado_ns from netsuite_ordenes_venta where id = p_orden_id), '')) in ('PENDIENTE_PICKING', 'PENDIENTE', '')
     and not exists (select 1 from netsuite_detalle_ov d where d.orden_id = p_orden_id and coalesce(d.cantidad_pickeada, 0) > 0);
$$;

-- ---------------------------------------------------------------------
-- Mover un usuario de equipo (libera las OV no iniciadas que ya no le corresponden)
-- ---------------------------------------------------------------------
create or replace function public.wms_mover_usuario_equipo(p_usuario text, p_equipo text, p_por text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  u record;
  v_equipo text := nullif(upper(btrim(coalesce(p_equipo, ''))), '');
  v_liberadas int := 0;
begin
  if v_equipo is not null and v_equipo not in ('FARMACIA', 'PICKING', 'PACKING', 'RECEPCION', 'INACTIVO') then
    raise exception 'WMS: equipo % no existe', p_equipo;
  end if;
  select * into u from wms_usuarios where upper(usuario) = upper(btrim(coalesce(p_usuario, ''))) for update;
  if not found then raise exception 'WMS: el usuario % no existe', p_usuario; end if;

  update wms_usuarios
     set equipo_trabajo = v_equipo, equipo_actualizado_en = now(),
         equipo_actualizado_por = coalesce(nullif(upper(btrim(p_por)), ''), 'PC'), updated_at = now()
   where id = u.id;

  -- Las OV que tenía y que no ha empezado, si ya no son de su nuevo equipo, vuelven a la cola
  with lib as (
    update netsuite_ordenes_venta o
       set operador_asignado = null
     where upper(coalesce(o.operador_asignado, '')) in (upper(u.usuario), upper(u.nombre_completo))
       and upper(coalesce(o.estado_ns, '')) in ('PENDIENTE_PICKING', 'PENDIENTE')
       and public.wms_ov_sin_iniciar(o.id)
       and (v_equipo is null or v_equipo not in ('FARMACIA', 'PICKING')
            or public.wms_tipo_picking_ov(o.numero_ov, o.canal_venta) <> v_equipo)
    returning o.id
  )
  select count(*) into v_liberadas from lib;

  return jsonb_build_object('usuario', u.usuario, 'equipo', coalesce(v_equipo, 'SIN EQUIPO'), 'ov_liberadas', v_liberadas);
end $$;

-- ---------------------------------------------------------------------
-- Repartir las OV sin asignar entre los usuarios de cada equipo (por carga)
-- ---------------------------------------------------------------------
create or replace function public.wms_asignar_ovs_por_equipo(p_bodega text, p_por text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_bodega text := public.wms_bodega_valida(p_bodega);
  o record;
  v_elegido text;
  v_res jsonb := '{}'::jsonb;
  v_asig_far int := 0; v_asig_pick int := 0; v_sin_far int := 0; v_sin_pick int := 0;
begin
  perform pg_advisory_xact_lock(hashtext('ASIGNAR_OV|' || v_bodega));

  create temporary table tmp_carga on commit drop as
  select upper(u.usuario) usuario, u.equipo_trabajo equipo,
         (select count(*) from netsuite_ordenes_venta x
           where upper(coalesce(x.operador_asignado, '')) in (upper(u.usuario), upper(u.nombre_completo))
             and upper(coalesce(x.estado_ns, '')) in ('PENDIENTE_PICKING', 'PICKING_EN_PROCESO', 'PENDIENTE'))::int carga
  from wms_usuarios u
  where coalesce(u.activo, true) and u.equipo_trabajo in ('FARMACIA', 'PICKING')
    and (coalesce(u.bodega, 'Bodega Santiago') = v_bodega or upper(coalesce(u.bodega, '')) in ('AMBAS', 'TODAS'));

  for o in
    select x.id, public.wms_tipo_picking_ov(x.numero_ov, x.canal_venta) tipo
    from netsuite_ordenes_venta x
    where coalesce(x.bodega, 'Bodega Santiago') = v_bodega
      and upper(coalesce(x.estado_ns, '')) in ('PENDIENTE_PICKING', 'PENDIENTE')
      and coalesce(nullif(upper(btrim(x.operador_asignado)), ''), 'SIN ASIGNAR') = 'SIN ASIGNAR'
    order by case when public.wms_tipo_picking_ov(x.numero_ov, x.canal_venta) = 'FARMACIA' then 0 else 1 end,
             x.fecha_emision_ns nulls last, x.id
    for update skip locked
  loop
    select usuario into v_elegido from tmp_carga where equipo = o.tipo order by carga, usuario limit 1;
    if v_elegido is null then
      if o.tipo = 'FARMACIA' then v_sin_far := v_sin_far + 1; else v_sin_pick := v_sin_pick + 1; end if;
      continue;
    end if;
    update netsuite_ordenes_venta set operador_asignado = v_elegido where id = o.id;
    update tmp_carga set carga = carga + 1 where usuario = v_elegido;
    if o.tipo = 'FARMACIA' then v_asig_far := v_asig_far + 1; else v_asig_pick := v_asig_pick + 1; end if;
    v_elegido := null;
  end loop;

  select coalesce(jsonb_object_agg(usuario, carga), '{}'::jsonb) into v_res from tmp_carga;
  return jsonb_build_object('farmacia_asignadas', v_asig_far, 'picking_asignadas', v_asig_pick,
                            'farmacia_sin_equipo', v_sin_far, 'picking_sin_equipo', v_sin_pick,
                            'carga_por_usuario', v_res);
end $$;

grant execute on function public.wms_tipo_picking_ov(text, text) to anon, authenticated, service_role;
grant execute on function public.wms_ov_sin_iniciar(bigint) to anon, authenticated, service_role;
grant execute on function public.wms_mover_usuario_equipo(text, text, text) to service_role;
grant execute on function public.wms_asignar_ovs_por_equipo(text, text) to service_role;

commit;
