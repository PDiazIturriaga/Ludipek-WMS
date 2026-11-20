-- =====================================================================
-- LUDIPEK WMS · 25 ANULAR ÓRDENES DESDE EL PC  (requiere 08, 18, 21 y 24)
-- Botón "Anular" en el Monitor de usuarios (cola de picking), solo administradores.
-- Solo se puede anular una orden que NO ha empezado (nada pickeado): así el stock no
-- queda descuadrado. Si ya tiene unidades pickeadas, primero hay que devolverlas.
-- Queda en el historial de estados con el motivo y el usuario.
-- =====================================================================
begin;

create or replace function public.wms_anular_ov(p_orden_id bigint, p_usuario text, p_motivo text)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  o record;
  v_motivo text := btrim(coalesce(p_motivo, ''));
  v_res jsonb;
begin
  if not public.wms_es_admin(p_usuario) then
    raise exception 'WMS: solo un administrador puede anular órdenes';
  end if;
  if length(v_motivo) < 4 then
    raise exception 'WMS: escriba el motivo de la anulación';
  end if;
  select * into o from netsuite_ordenes_venta where id = p_orden_id for update;
  if not found then
    raise exception 'WMS: la orden % no existe', p_orden_id;
  end if;
  if not public.wms_ov_sin_iniciar(p_orden_id) then
    raise exception 'WMS: la orden % ya tiene unidades pickeadas o está en %: no se puede anular desde aquí (devuelva primero lo pickeado)',
      o.numero_ov, coalesce(o.estado_ns, o.estado);
  end if;
  update netsuite_ordenes_venta set operador_asignado = null where id = p_orden_id;
  v_res := public.wms_cambiar_estado_ov(p_orden_id, 'ANULADO', upper(btrim(coalesce(p_usuario, ''))),
                                        left('ANULADA: ' || v_motivo, 500));
  return v_res;
end $$;

revoke all on function public.wms_anular_ov(bigint, text, text) from public, anon, authenticated;
grant execute on function public.wms_anular_ov(bigint, text, text) to service_role;

commit;
