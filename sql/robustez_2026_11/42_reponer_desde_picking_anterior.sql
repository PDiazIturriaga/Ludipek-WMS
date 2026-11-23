-- =====================================================================
-- LUDIPEK WMS · 42 REPONER DESDE EL PICKING ANTERIOR   (requiere 15 y 41)
-- Cuando un SKU cambia de ubicación de picking (ej. Giwi: de A-17-01 a ESTANTE-GIWI), el stock
-- que quedó en el picking anterior se puede mover al nuevo desde el celular (Movimiento a picking).
-- Antes se rechazaba por ser "ubicación de picking" y el celular decía "No hay reserva para bajar".
-- Solo se permite hacia el picking asignado; desde el propio picking asignado sigue bloqueado.
-- =====================================================================
begin;

CREATE OR REPLACE FUNCTION public.wms_mover_a_picking(p_inventario_id bigint, p_cajas integer, p_destino text DEFAULT NULL::text, p_usuario text DEFAULT NULL::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  v_usuario text := public.wms_contexto(p_usuario, 'wms_mover_a_picking');
  o record;
  v_dest text;
  v_mult int;
  v_cajas int;
  v_unid int;
  v_fija text;
begin
  select * into o from bodega_inventario_ubicacion where id = p_inventario_id for update;
  if not found then
    raise exception 'WMS: el stock seleccionado ya no existe (otro operador lo movió). Vuelva a buscar el SKU.';
  end if;
  if o.lote like '%|QA:%' then
    raise exception 'WMS: el lote % está bloqueado por calidad y no puede ir a picking', o.lote;
  end if;
  if public.wms_es_ubicacion_merma(o.codigo_ubicacion) then
    raise exception 'WMS: % es merma; ese stock no puede ir a picking', o.codigo_ubicacion;
  end if;
  if nullif(btrim(coalesce(p_destino, '')), '') is null then
    raise exception 'WMS: indique la ubicación de picking de destino (termina en -01, ej. H-02-01)';
  end if;
  v_dest := public.wms_ubicacion_valida(o.bodega, p_destino);
  if not public.wms_es_ubicacion_picking(v_dest) then
    raise exception 'WMS: % no es una ubicación de picking. El picking es el nivel 01 de los racks (ej. H-02-01).', v_dest;
  end if;
  -- (42) Desde una ubicación de picking solo se puede mover hacia el picking asignado del producto
  -- (ej. de su picking anterior A-17-01 al ESTANTE-GIWI). Desde su propio picking, nunca.
  if public.wms_es_ubicacion_picking(o.codigo_ubicacion) then
    v_fija := public.wms_picking_fijo_sku(o.bodega, o.sku);
    if v_fija is null or upper(o.codigo_ubicacion) = upper(v_fija) or upper(v_dest) <> upper(v_fija) then
      raise exception 'WMS: % ya es una ubicación de picking. Desde ahí solo se puede mover al picking asignado del producto (%).',
        o.codigo_ubicacion, coalesce(v_fija, 'sin asignar');
    end if;
  end if;
  if v_dest = o.codigo_ubicacion then
    raise exception 'WMS: el destino debe ser distinto del origen (%)', o.codigo_ubicacion;
  end if;
  if coalesce(p_cajas, 0) <= 0 then
    raise exception 'WMS: indique cuántas cajas mover';
  end if;

  v_mult := case when coalesce(o.cajas, 0) > 0 then greatest(round(o.cantidad_unidades::numeric / o.cajas)::int, 1) else 1 end;
  if coalesce(o.cajas, 0) > 0 and p_cajas > o.cajas then
    raise exception 'WMS: solo hay % cajas en %', o.cajas, o.codigo_ubicacion;
  end if;
  v_cajas := least(p_cajas, greatest(coalesce(o.cajas, 0), p_cajas));
  v_unid  := case when coalesce(o.cajas, 0) > 0 and v_cajas >= o.cajas then o.cantidad_unidades
                  else least(v_cajas * v_mult, o.cantidad_unidades) end;

  if o.cantidad_unidades - v_unid <= 0 then
    delete from bodega_inventario_ubicacion where id = o.id;
  else
    update bodega_inventario_ubicacion
       set cantidad_unidades = cantidad_unidades - v_unid,
           cajas = greatest(coalesce(cajas, 0) - v_cajas, 0),
           auditor = v_usuario, fecha = now()::text
     where id = o.id;
  end if;
  perform public.wms_sumar_en_ubicacion(o.bodega, v_dest, o.sku, o.lote, o.lpn, o.fecha_vencimiento_cl, v_cajas, v_unid);
  perform public.wms_kardex(o.bodega, 'MOVIMIENTO_PICKING', o.lpn, o.sku, o.lote, o.codigo_ubicacion, v_dest, v_cajas, v_unid);

  return jsonb_build_object('origen', o.codigo_ubicacion, 'destino', v_dest, 'cajas', v_cajas, 'unidades', v_unid, 'sku', o.sku, 'lote', o.lote);
end $function$;

commit;
