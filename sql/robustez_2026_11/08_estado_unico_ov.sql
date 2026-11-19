-- =====================================================================
-- LUDIPEK WMS · 08 UN SOLO ESTADO POR ORDEN  (requiere 07)
-- netsuite_ordenes_venta tiene dos columnas de estado: estado_ns (la que
-- leen el PC y el celular) y estado. Se desalineaban: la OV 133409-FA quedó
-- PENDIENTE_PACKING en una y PENDIENTE_PICKING en la otra.
-- Desde ahora cualquier cambio en una se copia a la otra, y todo cambio de
-- estado (venga de donde venga) queda en wms_historial_estados.
-- =====================================================================
begin;

-- 1) Alinear lo que ya está desalineado (manda estado_ns)
update public.netsuite_ordenes_venta
   set estado = estado_ns
 where estado_ns is not null and estado is distinct from estado_ns;

update public.netsuite_ordenes_venta
   set estado_ns = estado
 where estado_ns is null and estado is not null;

-- 2) Mantenerlas iguales
create or replace function public.wms_tg_estado_unico_ov()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  if tg_op = 'INSERT' then
    new.estado_ns := upper(btrim(coalesce(nullif(btrim(new.estado_ns), ''), nullif(btrim(new.estado), ''), 'PENDIENTE_PICKING')));
    new.estado := new.estado_ns;
    return new;
  end if;
  if new.estado_ns is distinct from old.estado_ns then
    new.estado_ns := upper(btrim(new.estado_ns));
    new.estado := new.estado_ns;
  elsif new.estado is distinct from old.estado then
    new.estado_ns := upper(btrim(new.estado));
    new.estado := new.estado_ns;
  end if;
  -- Historial de cambios hechos fuera de wms_cambiar_estado_ov (ej. "Marcar facturada" del PC)
  if new.estado_ns is distinct from old.estado_ns
     and coalesce(current_setting('wms.cambio_registrado', true), '') <> 'si' then
    insert into wms_catalogo_estados (codigo, modulo, descripcion) values (new.estado_ns, 'SALIDA', new.estado_ns)
    on conflict (codigo) do nothing;
    insert into wms_historial_estados (entidad_tipo, entidad_id, documento, estado_anterior, estado_nuevo, usuario, bodega, observacion)
    values ('ORDEN_VENTA', new.id, new.numero_ov, coalesce(old.estado_ns, 'PENDIENTE'), new.estado_ns,
            coalesce(nullif(current_setting('wms.usuario', true), ''), 'PC'), new.bodega, 'Cambio directo de estado');
  end if;
  return new;
end $$;

drop trigger if exists tg_estado_unico_ov on public.netsuite_ordenes_venta;
create trigger tg_estado_unico_ov
before insert or update of estado, estado_ns on public.netsuite_ordenes_venta
for each row execute function public.wms_tg_estado_unico_ov();

-- 3) wms_cambiar_estado_ov ya registra su propio historial: evitar el registro doble
create or replace function public.wms_cambiar_estado_ov(
  p_orden_id bigint, p_estado text, p_usuario text default null,
  p_observacion text default null, p_forzar boolean default false)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  o record;
  v_ant text;
  v_nuevo text := upper(btrim(coalesce(p_estado, '')));
begin
  select * into o from netsuite_ordenes_venta where id = p_orden_id for update;
  if not found then
    raise exception 'WMS: la orden % no existe', p_orden_id;
  end if;
  update netsuite_ordenes_venta set bodega = public.wms_bodega_valida(bodega)
   where id = p_orden_id and bodega is not null and bodega not in ('Bodega Santiago', 'Bodega Concepcion');
  select * into o from netsuite_ordenes_venta where id = p_orden_id;
  v_ant := upper(coalesce(nullif(btrim(o.estado_ns), ''), nullif(btrim(o.estado), ''), 'PENDIENTE'));
  if v_ant = v_nuevo then
    return jsonb_build_object('numero_ov', o.numero_ov, 'estado_anterior', v_ant, 'estado_nuevo', v_nuevo, 'sin_cambios', true);
  end if;
  if v_ant in ('ANULADO', 'CERRADO', 'DESPACHADO') and not p_forzar then
    raise exception 'WMS: la orden % está %, no se puede modificar', o.numero_ov, v_ant;
  end if;
  if public.wms_orden_estado_ov(v_nuevo) < public.wms_orden_estado_ov(v_ant) and not p_forzar then
    raise exception 'WMS: la orden % ya está en % y no puede volver a %', o.numero_ov, v_ant, v_nuevo;
  end if;

  insert into wms_catalogo_estados (codigo, modulo, descripcion) values (v_nuevo, 'SALIDA', v_nuevo)
  on conflict (codigo) do nothing;
  perform set_config('wms.cambio_registrado', 'si', true);
  update netsuite_ordenes_venta set estado_ns = v_nuevo, estado = v_nuevo, updated_at = now() where id = p_orden_id;
  perform set_config('wms.cambio_registrado', '', true);
  insert into wms_historial_estados (entidad_tipo, entidad_id, documento, estado_anterior, estado_nuevo, usuario, bodega, observacion)
  values ('ORDEN_VENTA', p_orden_id, o.numero_ov, v_ant, v_nuevo,
          coalesce(nullif(upper(btrim(p_usuario)), ''), 'APP'), o.bodega,
          coalesce(p_observacion, case when p_forzar then 'Corrección manual de estado' end));
  return jsonb_build_object('numero_ov', o.numero_ov, 'estado_anterior', v_ant, 'estado_nuevo', v_nuevo);
end $$;

commit;

-- Verificación: debe dar 0
select count(*) as ordenes_desalineadas from public.netsuite_ordenes_venta where estado is distinct from estado_ns;
