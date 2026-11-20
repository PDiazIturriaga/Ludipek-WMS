-- =====================================================================
-- LUDIPEK WMS · 29 DATOS DEL TABLERO (m0_dashboard)  (requiere 14, 15 y 21)
-- Una sola llamada entrega todo lo que muestra el tablero, calculado en la base con datos
-- reales (antes había valores fijos o estimados en la pantalla). Fechas en hora de Chile.
-- Solo lectura.
-- =====================================================================
begin;

create or replace function public.wms_dashboard_resumen(p_bodega text, p_dias integer default 14)
returns jsonb language plpgsql stable security definer set search_path = public as $$
declare
  v_bodega text := public.wms_bodega_valida(p_bodega);
  v_hoy date := (now() at time zone 'America/Santiago')::date;
  v_dias int := least(greatest(coalesce(p_dias, 14), 7), 60);
  v_res jsonb;
begin
  with
  ov as (
    select upper(coalesce(nullif(btrim(o.estado_ns), ''), nullif(btrim(o.estado), ''), 'PENDIENTE')) est,
           public.wms_tipo_picking_ov(o.numero_ov, o.canal_venta) tipo,
           coalesce(nullif(upper(btrim(o.operador_asignado)), ''), 'SIN ASIGNAR') op
    from netsuite_ordenes_venta o
    where coalesce(o.bodega, 'Bodega Santiago') = v_bodega
  ),
  inv as (
    select i.codigo_ubicacion ub, upper(i.sku) sku, i.lote, i.cantidad_unidades un,
           coalesce(i.fecha_vencimiento, public.wms_fecha_desde_texto(i.fecha_vencimiento_cl)) fv
    from bodega_inventario_ubicacion i
    where i.bodega = v_bodega and i.cantidad_unidades > 0
  ),
  ubic as (
    select upper(u.codigo_ubicacion) ub,
           case when upper(u.codigo_ubicacion) ~ '^[A-Z]-\d{2}-\d{2}$' then 'Rack ' || left(upper(u.codigo_ubicacion), 1)
                when upper(u.codigo_ubicacion) like 'MK-%' then 'Arena MK'
                when upper(u.codigo_ubicacion) like 'BE-%' then 'Arena BE'
                when upper(u.codigo_ubicacion) like 'ME-%' then 'Merma arena'
           end grupo
    from bodega_ubicaciones u
    where u.bodega = v_bodega
      and coalesce(u.estado, '') not ilike 'bloq%' and coalesce(u.estado_ubicacion, '') not ilike 'bloq%'
      and upper(u.codigo_ubicacion) not like 'ZONA-%'
  ),
  kardex as (
    select (h.fecha at time zone 'America/Santiago')::date dia, upper(coalesce(h.usuario, '')) usuario,
           case when h.tipo_movimiento like 'RECEPCION%' then 'RECEPCION'
                when h.tipo_movimiento like 'SALIDA_PICKING%' then 'DESPACHO'
                when h.tipo_movimiento = 'ALMACENAMIENTO' then 'ALMACENAMIENTO'
                when h.tipo_movimiento like 'MOVIMIENTO_PICKING%' then 'REABASTECIMIENTO'
                when h.tipo_movimiento like 'AJUSTE_CICLICO%' then 'CONTEO'
           end grupo,
           abs(coalesce(h.unidades_afectadas, 0)) un
    from historial_movimientos h
    where h.bodega = v_bodega
      and h.fecha >= ((v_hoy - (v_dias - 1))::timestamp at time zone 'America/Santiago')
  ),
  estados_hoy as (
    select e.estado_nuevo, count(distinct e.entidad_id) n
    from wms_historial_estados e
    where e.entidad_tipo = 'ORDEN_VENTA' and coalesce(e.bodega, v_bodega) = v_bodega
      and (e.created_at at time zone 'America/Santiago')::date = v_hoy
    group by e.estado_nuevo
  )
  select jsonb_build_object(
    'bodega', v_bodega,
    'generado', to_char(now() at time zone 'America/Santiago', 'DD-MM-YYYY HH24:MI'),
    'kpis', jsonb_build_object(
      'ov_picking', (select count(*) from ov where est in ('PENDIENTE_PICKING', 'PENDIENTE', 'PICKING_EN_PROCESO')),
      'ov_picking_farmacia', (select count(*) from ov where est in ('PENDIENTE_PICKING', 'PENDIENTE', 'PICKING_EN_PROCESO') and tipo = 'FARMACIA'),
      'ov_sin_asignar', (select count(*) from ov where est in ('PENDIENTE_PICKING', 'PENDIENTE') and op = 'SIN ASIGNAR'),
      'ov_packing', (select count(*) from ov where est = 'PENDIENTE_PACKING'),
      'ov_por_facturar', (select count(*) from ov where est = 'PENDIENTE_FACTURACION'),
      'ov_en_transito', (select count(*) from ov where est = 'EN_TRANSITO_CCP'),
      'cerradas_hoy', coalesce((select sum(n) from estados_hoy
                                 where estado_nuevo in ('PENDIENTE_FACTURACION', 'EN_TRANSITO_CCP', 'DESPACHADO')), 0),
      'anden', (select count(*) from public.wms_lpns_en_anden(v_bodega)),
      'unidades_stock', coalesce((select sum(un) from inv where ub <> 'ZONA-MERMA' and ub not like 'ME-%'), 0),
      'skus_stock', (select count(distinct sku) from inv),
      'posiciones_total', (select count(*) from ubic where grupo like 'Rack %'),
      'posiciones_ocupadas', (select count(distinct i.ub) from inv i join ubic u on u.ub = i.ub where u.grupo like 'Rack %')
    ),
    -- Unidades por día y tipo de movimiento
    'movimientos_dia', (
      select coalesce(jsonb_agg(jsonb_build_object(
               'dia', to_char(d, 'DD-MM'), 'dow', extract(isodow from d)::int,
               'recepcion', coalesce((select sum(un) from kardex k where k.dia = d and k.grupo = 'RECEPCION'), 0),
               'almacenamiento', coalesce((select sum(un) from kardex k where k.dia = d and k.grupo = 'ALMACENAMIENTO'), 0),
               'despacho', coalesce((select sum(un) from kardex k where k.dia = d and k.grupo = 'DESPACHO'), 0)
             ) order by d), '[]'::jsonb)
      from generate_series(v_hoy - (v_dias - 1), v_hoy, interval '1 day') g(d0), lateral (select g.d0::date d) x
    ),
    -- Productividad de hoy por operador
    'operadores_hoy', (
      select coalesce(jsonb_agg(jsonb_build_object('usuario', usuario, 'movimientos', movs, 'unidades', un,
                                                   'recepcion', rec, 'almacenamiento', alm, 'despacho', des)
                                order by un desc), '[]'::jsonb)
      from (select usuario, count(*) movs, sum(un) un,
                   sum(un) filter (where grupo = 'RECEPCION') rec,
                   sum(un) filter (where grupo = 'ALMACENAMIENTO') alm,
                   sum(un) filter (where grupo = 'DESPACHO') des
            from kardex where dia = v_hoy and grupo is not null and usuario not in ('', 'APP', 'SISTEMA', 'APP_RF')
            group by usuario order by sum(un) desc limit 10) z
    ),
    -- Ocupación por rack / zona
    'ocupacion', (
      select coalesce(jsonb_agg(jsonb_build_object('grupo', grupo, 'total', total, 'ocupadas', ocupadas) order by grupo), '[]'::jsonb)
      from (select u.grupo, count(*) total, count(*) filter (where exists (select 1 from inv i where i.ub = u.ub)) ocupadas
            from ubic u where u.grupo is not null group by u.grupo) z
    ),
    -- Unidades por tramo de vencimiento
    'vencimientos', (
      select jsonb_agg(jsonb_build_object('tramo', t.tramo, 'orden', t.orden,
               'unidades', coalesce((select sum(un) from inv where ub <> 'ZONA-MERMA' and ub not like 'ME-%' and
                                       case t.orden when 1 then fv < v_hoy
                                                    when 2 then fv >= v_hoy and fv < v_hoy + 30
                                                    when 3 then fv >= v_hoy + 30 and fv < v_hoy + 90
                                                    when 4 then fv >= v_hoy + 90 and fv < v_hoy + 180
                                                    when 5 then fv >= v_hoy + 180
                                                    else fv is null end), 0),
               'lotes', (select count(distinct sku || '|' || coalesce(lote, '')) from inv where ub <> 'ZONA-MERMA' and ub not like 'ME-%' and
                                       case t.orden when 1 then fv < v_hoy
                                                    when 2 then fv >= v_hoy and fv < v_hoy + 30
                                                    when 3 then fv >= v_hoy + 30 and fv < v_hoy + 90
                                                    when 4 then fv >= v_hoy + 90 and fv < v_hoy + 180
                                                    when 5 then fv >= v_hoy + 180
                                                    else fv is null end)) order by t.orden)
      from (values (1, 'Vencido'), (2, 'Menos de 30 días'), (3, '30 a 90 días'), (4, '90 a 180 días'),
                   (5, 'Más de 180 días'), (6, 'Sin fecha')) t(orden, tramo)
    ),
    -- Recepciones (OC) abiertas
    'oc_abiertas', (
      select coalesce(jsonb_agg(jsonb_build_object('codigo', codigo_asn, 'proveedor', proveedor, 'estado', estado,
                                                   'pallets_esperados', pallets_esperados, 'lpns', lpns, 'unidades', un)
                                order by id desc), '[]'::jsonb)
      from (select a.id, a.codigo_asn, a.proveedor, a.estado, a.pallets_esperados,
                   (select count(distinct r.lpn) from registro_recepcion r where r.asn_id = a.id) lpns,
                   (select coalesce(sum(r.unidades_totales), 0) from registro_recepcion r where r.asn_id = a.id) un
            from asn_cabecera a
            where coalesce(a.bodega, 'Bodega Santiago') = v_bodega and upper(coalesce(a.estado, '')) not like 'COMPLET%'
              and upper(coalesce(a.estado, '')) not like 'CERRAD%'
            order by a.id desc limit 8) z
    ),
    -- Alertas por severidad (centro de alertas del script 14)
    'alertas', (
      select coalesce(jsonb_agg(jsonb_build_object('codigo', codigo, 'severidad', severidad, 'titulo', titulo, 'cantidad', cantidad)
                                order by case severidad when 'ALTA' then 0 when 'MEDIA' then 1 else 2 end, cantidad desc), '[]'::jsonb)
      from public.wms_alertas_operacion(v_bodega)
    )
  ) into v_res;
  return v_res;
end $$;

revoke all on function public.wms_dashboard_resumen(text, integer) from public, anon, authenticated;
grant execute on function public.wms_dashboard_resumen(text, integer) to service_role;

commit;

-- Prueba:  select jsonb_pretty(public.wms_dashboard_resumen('Bodega Santiago'));
