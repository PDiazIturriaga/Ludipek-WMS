-- =====================================================================
-- LUDIPEK WMS · 54 DESPACHO DE EXPORTACIÓN: PALLETS DE CUALQUIER LUGAR, INCLUIDO EL ANDÉN   (requiere 50)
-- El despacho acepta LPN en cualquier ubicación (racks, picking, estantes) y también pallets que están
-- en el andén de recepción todavía sin ubicar. Al cerrar descontando stock, el pallet del andén deja la
-- recepción cerrada (CERRADO_SIN_UBICAR, con el despacho en las observaciones) y queda en el kardex
-- como DESPACHO_EXPORTACION desde ANDEN. Se puede ejecutar más de una vez.
-- =====================================================================
begin;

-- Escanear un LPN: lee su contenido del stock (cualquier ubicación) o del andén de recepción
create or replace function public.wms_despacho_escanear(p_id bigint, p_lpn text, p_usuario text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_usuario text := public.wms_usuario_despacho(p_usuario);
  v_d wms_despachos;
  v_lpn text := upper(btrim(coalesce(p_lpn, '')));
  v_filas jsonb;
  v_ubic text;
  v_otro text;
  v_avisos text[] := '{}';
  v_sku record;
begin
  select * into v_d from wms_despachos where id = p_id for update;
  if v_d.id is null then raise exception 'WMS: el despacho no existe'; end if;
  if v_d.estado <> 'ABIERTO' then raise exception 'WMS: el despacho % está %', v_d.numero, v_d.estado; end if;
  if v_lpn ~ '^\d{18}$' then v_lpn := 'SSCC-' || v_lpn; end if;
  if v_lpn = '' then raise exception 'WMS: escanee el LPN'; end if;

  if exists (select 1 from wms_despacho_lpn where despacho_id = p_id and lpn = v_lpn) then
    return jsonb_build_object('resultado', 'YA_ESTABA', 'lpn', v_lpn, 'detalle', public.wms_despacho_detalle(p_id));
  end if;
  select d.numero into v_otro
    from wms_despacho_lpn l join wms_despachos d on d.id = l.despacho_id
   where l.lpn = v_lpn and d.estado = 'ABIERTO' and d.id <> p_id limit 1;
  if v_otro is not null then raise exception 'WMS: el LPN % ya está en el despacho %', v_lpn, v_otro; end if;

  select coalesce(jsonb_agg(jsonb_build_object(
           'id', i.id, 'sku', upper(btrim(i.sku)), 'lote', i.lote, 'fecha_vencimiento_cl', i.fecha_vencimiento_cl,
           'cantidad_unidades', i.cantidad_unidades, 'cajas', i.cajas, 'codigo_ubicacion', i.codigo_ubicacion) order by i.sku, i.lote), '[]'::jsonb),
         string_agg(distinct i.codigo_ubicacion, ', ')
    into v_filas, v_ubic
    from bodega_inventario_ubicacion i
   where i.bodega = v_d.bodega and upper(btrim(i.lpn)) = v_lpn and coalesce(i.cantidad_unidades, 0) > 0;
  if jsonb_array_length(v_filas) = 0 then
    -- Pallet en el andén de recepción (recibido y todavía sin ubicar)
    select coalesce(jsonb_agg(jsonb_build_object(
             'registro_id', r.id, 'sku', upper(btrim(r.sku)), 'lote', r.lote, 'fecha_vencimiento_cl', r.fecha_vencimiento_cl,
             'cantidad_unidades', r.unidades_totales, 'cajas', r.cajas, 'codigo_ubicacion', 'ANDÉN RECEPCIÓN',
             'origen', 'ANDEN') order by r.sku, r.lote), '[]'::jsonb)
      into v_filas
      from registro_recepcion r
     where r.bodega = v_d.bodega and upper(btrim(r.lpn)) = v_lpn
       and coalesce(r.estado_pallet, '') not in ('ALMACENADO', 'CERRADO_SIN_UBICAR')
       and coalesce(r.unidades_totales, 0) > 0;
    v_ubic := 'ANDÉN RECEPCIÓN';
  end if;
  if jsonb_array_length(v_filas) = 0 then
    raise exception 'WMS: el LPN % no tiene stock ni está en el andén de % (¿ya salió o es de otra bodega?)', v_lpn, v_d.bodega;
  end if;

  insert into wms_despacho_lpn (despacho_id, lpn, ubicacion, filas, escaneado_por)
  values (p_id, v_lpn, v_ubic, v_filas, v_usuario);

  -- avisos: SKU fuera del pedido o que pasa lo pedido
  if exists (select 1 from wms_despacho_pedido where despacho_id = p_id) then
    for v_sku in
      select upper(f->>'sku') sku from jsonb_array_elements(v_filas) f group by 1
    loop
      if not exists (select 1 from wms_despacho_pedido where despacho_id = p_id and upper(sku) = v_sku.sku) then
        v_avisos := v_avisos || format('%s no está en el pedido', v_sku.sku);
      elsif (select coalesce(sum((f->>'cantidad_unidades')::numeric), 0)
               from wms_despacho_lpn l, jsonb_array_elements(l.filas) f
              where l.despacho_id = p_id and upper(f->>'sku') = v_sku.sku)
            > (select unidades from wms_despacho_pedido where despacho_id = p_id and upper(sku) = v_sku.sku) then
        v_avisos := v_avisos || format('%s pasa lo pedido', v_sku.sku);
      end if;
    end loop;
  end if;

  return jsonb_build_object('resultado', 'AGREGADO', 'lpn', v_lpn, 'ubicacion', v_ubic, 'avisos', to_jsonb(v_avisos),
                            'detalle', public.wms_despacho_detalle(p_id));
end $$;

-- Cerrar: si p_descontar, cada LPN sale del stock o del andén (kardex DESPACHO_EXPORTACION)
create or replace function public.wms_despacho_cerrar(p_id bigint, p_descontar boolean, p_usuario text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_usuario text := public.wms_usuario_despacho(p_usuario);
  v_d wms_despachos;
  l record;
  r record;
  v_filas jsonb;
  v_n int := 0;
  v_un int := 0;
  v_max_obs int;
begin
  select character_maximum_length into v_max_obs from information_schema.columns
   where table_schema = 'public' and table_name = 'registro_recepcion' and column_name = 'observaciones';
  select * into v_d from wms_despachos where id = p_id for update;
  if v_d.id is null or v_d.estado <> 'ABIERTO' then raise exception 'WMS: el despacho no está abierto'; end if;
  if not exists (select 1 from wms_despacho_lpn where despacho_id = p_id) then
    raise exception 'WMS: el despacho no tiene LPN escaneados';
  end if;

  if coalesce(p_descontar, false) then
    for l in select * from wms_despacho_lpn where despacho_id = p_id loop
      perform pg_advisory_xact_lock(hashtext('LPN|' || l.lpn));
      select coalesce(jsonb_agg(jsonb_build_object(
               'id', i.id, 'sku', upper(btrim(i.sku)), 'lote', i.lote, 'fecha_vencimiento_cl', i.fecha_vencimiento_cl,
               'cantidad_unidades', i.cantidad_unidades, 'cajas', i.cajas, 'codigo_ubicacion', i.codigo_ubicacion)), '[]'::jsonb)
        into v_filas
        from bodega_inventario_ubicacion i
       where i.bodega = v_d.bodega and upper(btrim(i.lpn)) = l.lpn and coalesce(i.cantidad_unidades, 0) > 0;
      for r in select * from bodega_inventario_ubicacion i
                where i.bodega = v_d.bodega and upper(btrim(i.lpn)) = l.lpn and coalesce(i.cantidad_unidades, 0) > 0 loop
        perform public.wms_kardex(v_d.bodega, 'DESPACHO_EXPORTACION', l.lpn, r.sku, r.lote, r.codigo_ubicacion,
                                  left(v_d.numero || ' ' || v_d.destino, 60), -coalesce(r.cajas, 0), -coalesce(r.cantidad_unidades, 0));
        v_un := v_un + coalesce(r.cantidad_unidades, 0);
      end loop;
      delete from bodega_inventario_ubicacion i
       where i.bodega = v_d.bodega and upper(btrim(i.lpn)) = l.lpn and coalesce(i.cantidad_unidades, 0) > 0;
      if jsonb_array_length(v_filas) = 0 then
        -- pallet del andén: su recepción queda cerrada (no pasa por almacenamiento)
        select coalesce(jsonb_agg(jsonb_build_object(
                 'registro_id', rr.id, 'sku', upper(btrim(rr.sku)), 'lote', rr.lote, 'fecha_vencimiento_cl', rr.fecha_vencimiento_cl,
                 'cantidad_unidades', rr.unidades_totales, 'cajas', rr.cajas, 'codigo_ubicacion', 'ANDÉN RECEPCIÓN',
                 'origen', 'ANDEN')), '[]'::jsonb)
          into v_filas
          from registro_recepcion rr
         where rr.bodega = v_d.bodega and upper(btrim(rr.lpn)) = l.lpn
           and coalesce(rr.estado_pallet, '') not in ('ALMACENADO', 'CERRADO_SIN_UBICAR')
           and coalesce(rr.unidades_totales, 0) > 0;
        for r in select * from registro_recepcion x
                  where x.bodega = v_d.bodega and upper(btrim(x.lpn)) = l.lpn
                    and coalesce(x.estado_pallet, '') not in ('ALMACENADO', 'CERRADO_SIN_UBICAR')
                    and coalesce(x.unidades_totales, 0) > 0 loop
          perform public.wms_kardex(v_d.bodega, 'DESPACHO_EXPORTACION', l.lpn, r.sku, r.lote, 'ANDEN',
                                    left(v_d.numero || ' ' || v_d.destino, 60), -coalesce(r.cajas, 0), -coalesce(r.unidades_totales, 0));
          v_un := v_un + coalesce(r.unidades_totales, 0);
        end loop;
        update registro_recepcion x
           set estado_pallet = 'CERRADO_SIN_UBICAR',
               observaciones = left(btrim(coalesce(x.observaciones || ' | ', '') || 'DESPACHO ' || v_d.numero || ' ' || v_d.destino
                                    || ' ' || to_char(now() at time zone 'America/Santiago', 'DD-MM-YYYY HH24:MI') || ' ' || v_usuario),
                                    coalesce(v_max_obs, 4000))
         where x.bodega = v_d.bodega and upper(btrim(x.lpn)) = l.lpn
           and coalesce(x.estado_pallet, '') not in ('ALMACENADO', 'CERRADO_SIN_UBICAR');
      end if;
      update wms_despacho_lpn set descontado = v_filas where id = l.id;
      v_n := v_n + 1;
    end loop;
  end if;

  update wms_despachos
     set estado = 'CERRADO', stock_descontado = coalesce(p_descontar, false), cerrado_por = v_usuario, cerrado_en = now()
   where id = p_id;
  return jsonb_build_object('numero', v_d.numero, 'lpn_descontados', v_n, 'unidades_descontadas', v_un,
                            'detalle', public.wms_despacho_detalle(p_id));
end $$;

commit;
