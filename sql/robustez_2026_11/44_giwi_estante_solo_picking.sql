-- =====================================================================
-- LUDIPEK WMS · 44 GIWI: EL PICKING ES SOLO EL ESTANTE   (requiere 19, 41 y 42)
-- Para un SKU cuyo picking asignado es una zona (ESTANTE-GIWI o FARMACIA), cualquier otra ubicación
-- es almacenamiento, aunque sea nivel 01 de un rack (ej. Giwi en A-17-01):
-- · Al descontar el picking se usa primero el estante; lo de otras ubicaciones va al final, como reserva.
-- · Desde el celular, Movimiento a picking ofrece ese stock para subirlo al estante (script 42).
-- =====================================================================
begin;

CREATE OR REPLACE FUNCTION public.wms_salida_picking(p_bodega text, p_sku text, p_lote text, p_unidades integer, p_numero_ov text, p_usuario text DEFAULT NULL::text, p_ubicacion text DEFAULT NULL::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  v_fija text;
  v_bodega text := public.wms_bodega_valida(p_bodega);
  v_usuario text := public.wms_contexto(p_usuario, 'wms_salida_picking');
  v_sku text := public.wms_normalizar_sku(p_sku);
  v_lote text := split_part(public.wms_normalizar_lote(p_lote), '|QA:', 1);
  v_ubic text := public.wms_normalizar_ubicacion(p_ubicacion);
  v_ov text := upper(btrim(coalesce(p_numero_ov, 'S/OV')));
  v_pend int := coalesce(p_unidades, 0);
  v_tomar int;
  v_cajas_nuevas int;
  v_mult int;
  v_detalle jsonb := '[]'::jsonb;
  r record;
begin
  v_fija := public.wms_picking_fijo_sku(p_bodega, p_sku);
  if v_sku like '%-FA' then v_sku := left(v_sku, length(v_sku) - 3); end if;
  if v_pend <= 0 then
    raise exception 'WMS: la cantidad a descontar debe ser mayor a 0';
  end if;

  for r in
    select * from bodega_inventario_ubicacion
     where bodega = v_bodega and sku in (v_sku, v_sku || '-FA') and lote = v_lote
       and not public.wms_es_ubicacion_merma(codigo_ubicacion) and cantidad_unidades > 0
     order by case when v_ubic <> '' and codigo_ubicacion = v_ubic then 0
                   when codigo_ubicacion = v_fija then 1
                   -- (44) otra ubicación nivel 01 cuenta como picking solo si el SKU pickea en rack;
                   -- si su picking es una zona (ESTANTE-GIWI, FARMACIA) lo demás es almacenamiento
                   when public.wms_es_ubicacion_picking(codigo_ubicacion)
                        and (v_fija is null or v_fija ~ '^[A-Z]-[0-9]{2}-01$') then 2
                   when codigo_ubicacion = 'ZONA-PICKING' then 3
                   when public.wms_es_ubicacion_arena(codigo_ubicacion) then 4 else 5 end,
              fecha_vencimiento nulls last, id
     for update
  loop
    exit when v_pend <= 0;
    v_tomar := least(v_pend, r.cantidad_unidades);
    if r.cantidad_unidades - v_tomar <= 0 then
      delete from bodega_inventario_ubicacion where id = r.id;
      v_cajas_nuevas := 0;
    else
      v_mult := case when coalesce(r.cajas, 0) > 0 then greatest(round(r.cantidad_unidades::numeric / r.cajas)::int, 1) else 1 end;
      v_cajas_nuevas := case when coalesce(r.cajas, 0) > 0 then (r.cantidad_unidades - v_tomar) / v_mult else 0 end;
      update bodega_inventario_ubicacion
         set cantidad_unidades = cantidad_unidades - v_tomar, cajas = v_cajas_nuevas,
             auditor = v_usuario, fecha = now()::text
       where id = r.id;
    end if;
    perform public.wms_kardex(v_bodega, 'SALIDA_PICKING (' || v_ov || ')', r.lpn, r.sku, r.lote, r.codigo_ubicacion,
                              'PACKING ' || v_ov, coalesce(r.cajas, 0) - v_cajas_nuevas, v_tomar);
    v_detalle := v_detalle || jsonb_build_object('ubicacion', r.codigo_ubicacion, 'lpn', r.lpn, 'unidades', v_tomar);
    v_pend := v_pend - v_tomar;
  end loop;

  if v_pend > 0 then
    perform public.wms_kardex(v_bodega, 'SALIDA_PICKING_SIN_STOCK (' || v_ov || ')', null, v_sku, v_lote, 'SIN_REGISTRO',
                              'PACKING ' || v_ov, 0, v_pend);
  end if;

  return jsonb_build_object('sku', v_sku, 'lote', v_lote, 'solicitado', p_unidades,
                            'descontado', p_unidades - v_pend, 'faltante', v_pend, 'detalle', v_detalle);
end $function$;

commit;
