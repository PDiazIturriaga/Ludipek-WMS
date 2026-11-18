-- =====================================================================
-- LUDIPEK WMS · 04b RECEPCIONES QUE NUNCA SE ALMACENARON
-- Hay LPN recepcionados que no tienen stock en inventario ni movimiento de
-- almacenamiento. Si se dejan abiertos, cualquiera que escanee una etiqueta
-- antigua en "Almacenamiento" crearía stock que quizás ya se despachó.
--
-- PASO 1 (solo lectura): planilla para revisar en piso / andén.
-- PASO 2: los pallets que SÍ están físicamente se almacenan normal con el RF.
-- PASO 3: el resto se cierra como CERRADO_SIN_UBICAR (no se borra nada:
--         la recepción queda como respaldo y el avance de la OC no cambia).
-- PASO 4: inventariar con Conteo Cíclico los SKU de la consulta final.
-- =====================================================================

-- PASO 1 · Planilla de revisión (exportar a CSV desde el SQL Editor)
select r.lpn, min(r.created_at)::date as recibido, r.bodega,
       string_agg(distinct coalesce(r.contenedor, ''), ', ') as contenedor,
       string_agg(r.sku || ' / ' || r.lote || ' / ' || r.unidades_totales || ' UN', ' | ' order by r.sku) as contenido,
       sum(r.unidades_totales) as unidades
from public.registro_recepcion r
where coalesce(r.estado_pallet, '') not in ('ALMACENADO', 'CERRADO_SIN_UBICAR')
  and not exists (select 1 from public.bodega_inventario_ubicacion i where i.lpn = r.lpn)
  and not exists (select 1 from public.historial_movimientos h where h.lpn = r.lpn
                  and h.tipo_movimiento in ('ALMACENAMIENTO', 'ENVIO_MERMA'))
group by r.lpn, r.bodega
order by recibido, r.lpn;

-- ---------------------------------------------------------------------
-- La función de almacenamiento pasa a rechazar recepciones cerradas
-- ---------------------------------------------------------------------
begin;
create or replace function public.wms_consultar_lpn(p_bodega text, p_lpn text)
returns jsonb language plpgsql stable security definer set search_path = public as $$
declare
  v_bodega text := public.wms_bodega_valida(p_bodega);
  v_lpn text := upper(btrim(coalesce(p_lpn, '')));
  v_ubics text[];
  v_otra text;
begin
  if v_lpn ~ '^\d{18}$' then v_lpn := 'SSCC-' || v_lpn; end if;

  select array_agg(distinct codigo_ubicacion) into v_ubics
  from bodega_inventario_ubicacion
  where bodega = v_bodega and lpn = v_lpn and codigo_ubicacion <> 'ZONA-PICKING' and cantidad_unidades > 0;

  if coalesce(array_length(v_ubics, 1), 0) > 1 then
    return jsonb_build_object('estado', 'VARIAS_UBICACIONES', 'lpn', v_lpn, 'ubicaciones', to_jsonb(v_ubics),
      'mensaje', format('El LPN %s figura en %s ubicaciones (%s). Haga conteo cíclico antes de moverlo.', v_lpn, array_length(v_ubics, 1), array_to_string(v_ubics, ', ')));
  elsif coalesce(array_length(v_ubics, 1), 0) = 1 then
    return jsonb_build_object('estado', 'EN_RACK', 'lpn', v_lpn, 'origen', v_ubics[1], 'lineas',
      (select jsonb_agg(jsonb_build_object('id', id, 'sku', sku, 'lote', lote, 'fecha_vencimiento_cl', fecha_vencimiento_cl,
                                           'cajas', cajas, 'unidades_totales', cantidad_unidades) order by id)
       from bodega_inventario_ubicacion
       where bodega = v_bodega and lpn = v_lpn and codigo_ubicacion = v_ubics[1] and cantidad_unidades > 0));
  end if;

  if exists (select 1 from bodega_inventario_ubicacion where bodega = v_bodega and lpn = v_lpn)
     or exists (select 1 from historial_movimientos where bodega = v_bodega and lpn = v_lpn
                and tipo_movimiento in ('ALMACENAMIENTO', 'ENVIO_MERMA')) then
    return jsonb_build_object('estado', 'SIN_SALDO', 'lpn', v_lpn,
      'mensaje', format('El LPN %s ya fue almacenado y no tiene saldo en rack (consumido o movido a picking).', v_lpn));
  end if;

  if exists (select 1 from registro_recepcion where bodega = v_bodega and lpn = v_lpn
             and coalesce(estado_pallet, '') = 'CERRADO_SIN_UBICAR') then
    return jsonb_build_object('estado', 'SIN_SALDO', 'lpn', v_lpn,
      'mensaje', format('La recepción del LPN %s fue cerrada sin ubicar (histórico). Si el pallet está físicamente en bodega, regístrelo con Conteo Cíclico.', v_lpn));
  end if;

  if exists (select 1 from registro_recepcion where bodega = v_bodega and lpn = v_lpn) then
    return jsonb_build_object('estado', 'EN_ANDEN', 'lpn', v_lpn, 'origen', 'ANDEN_TRANSITO', 'lineas',
      (select jsonb_agg(jsonb_build_object('id', id, 'sku', sku, 'lote', lote, 'fecha_vencimiento_cl', fecha_vencimiento_cl,
                                           'cajas', cajas, 'unidades_totales', unidades_totales) order by id)
       from registro_recepcion where bodega = v_bodega and lpn = v_lpn));
  end if;

  select bodega into v_otra from registro_recepcion where lpn = v_lpn limit 1;
  return jsonb_build_object('estado', 'NO_EXISTE', 'lpn', v_lpn, 'mensaje',
    case when v_otra is not null then format('El LPN %s pertenece a %s, no a %s.', v_lpn, v_otra, v_bodega)
         else format('El LPN %s no existe en recepción ni en inventario de %s.', v_lpn, v_bodega) end);
end $$;
commit;

-- PASO 3 · Cerrar las recepciones antiguas no ubicadas.
-- ⚠ Ajuste la fecha de corte: solo se cierran LPN recibidos ANTES de ella.
--   Lo recibido después se asume en andén y se debe almacenar con el RF.
-- begin;
-- update public.registro_recepcion r
--    set estado_pallet = 'CERRADO_SIN_UBICAR',
--        observaciones = trim(coalesce(observaciones, '') || ' Cerrado sin ubicar el ' || to_char(now(), 'DD-MM-YYYY'))
--  where r.created_at < date '2026-11-17'
--    and coalesce(r.estado_pallet, '') not in ('ALMACENADO', 'CERRADO_SIN_UBICAR')
--    and not exists (select 1 from public.bodega_inventario_ubicacion i where i.lpn = r.lpn)
--    and not exists (select 1 from public.historial_movimientos h where h.lpn = r.lpn
--                    and h.tipo_movimiento in ('ALMACENAMIENTO', 'ENVIO_MERMA'));
-- commit;

-- PASO 4 · SKU recibidos que hoy no tienen NINGUNA unidad en inventario
--          (prioridad para Conteo Cíclico por SKU)
select r.sku, r.bodega, count(distinct r.lpn) as lpn_recibidos, sum(r.unidades_totales) as unidades_recibidas,
       max(r.created_at)::date as ultima_recepcion
from public.registro_recepcion r
where not exists (select 1 from public.bodega_inventario_ubicacion i where i.sku = r.sku and i.bodega = r.bodega)
group by r.sku, r.bodega
order by unidades_recibidas desc;
