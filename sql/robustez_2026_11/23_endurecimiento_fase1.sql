-- =====================================================================
-- LUDIPEK WMS · 23 ENDURECIMIENTO FASE 1 (resultado del diagnóstico 90)
-- Cierra los huecos de seguridad SIN romper el celular actual: cada tabla queda
-- solo con lo que el celular realmente hace (leer, insertar o actualizar).
--  1) RLS en las 6 tablas que estaban abiertas, con políticas mínimas:
--       asn_cabecera, netsuite_ordenes_venta, netsuite_detalle_ov -> solo lectura
--       maestra_sku            -> leer + enrolar/actualizar (sin borrar)
--       auditoria_ciclico_sku  -> solo insertar
--       wms_packing_lists_fa   -> leer + insertar + actualizar (sin borrar)
--  2) Políticas abiertas reemplazadas:
--       historial_movimientos: el celular solo puede crear/borrar avisos
--         ALERTA_VACIA_OCUPADA (antes podía borrar CUALQUIER movimiento del kardex)
--       wms_recepcion_traslados_ccp: sin escritura directa (el celular usa la función del 13)
--  3) Nadie con la clave pública puede vaciar (TRUNCATE) tablas: TRUNCATE salta el RLS.
--  4) Índices para las 5 claves foráneas sin índice y clave primaria en wms_carga_picking_fijo.
--  5) Duplicados: dos filas con distinto LPN son dos pallets, ya no se ofrecen para eliminar.
-- El PC usa la clave de servicio y no se ve afectado.
-- Si algo del celular dejara de funcionar, al final está el bloque para deshacer el punto 1.
-- =====================================================================
begin;

-- ---------------------------------------------------------------------
-- 1) RLS + políticas mínimas
-- ---------------------------------------------------------------------
alter table public.asn_cabecera           enable row level security;
alter table public.netsuite_ordenes_venta enable row level security;
alter table public.netsuite_detalle_ov    enable row level security;
alter table public.maestra_sku            enable row level security;
alter table public.auditoria_ciclico_sku  enable row level security;
alter table public.wms_packing_lists_fa   enable row level security;

drop policy if exists rf_leer_asn_cabecera on public.asn_cabecera;
create policy rf_leer_asn_cabecera on public.asn_cabecera for select to anon, authenticated using (true);

drop policy if exists rf_leer_ov on public.netsuite_ordenes_venta;
create policy rf_leer_ov on public.netsuite_ordenes_venta for select to anon, authenticated using (true);

drop policy if exists rf_leer_detalle_ov on public.netsuite_detalle_ov;
create policy rf_leer_detalle_ov on public.netsuite_detalle_ov for select to anon, authenticated using (true);

drop policy if exists rf_leer_maestra on public.maestra_sku;
drop policy if exists rf_enrolar_maestra on public.maestra_sku;
drop policy if exists rf_actualizar_maestra on public.maestra_sku;
create policy rf_leer_maestra on public.maestra_sku for select to anon, authenticated using (true);
create policy rf_enrolar_maestra on public.maestra_sku for insert to anon, authenticated
  with check (coalesce(btrim(sku), '') <> '');
create policy rf_actualizar_maestra on public.maestra_sku for update to anon, authenticated
  using (true) with check (coalesce(btrim(sku), '') <> '');

drop policy if exists rf_insertar_ciclico_sku on public.auditoria_ciclico_sku;
create policy rf_insertar_ciclico_sku on public.auditoria_ciclico_sku for insert to anon, authenticated
  with check (coalesce(btrim(sku), '') <> '');

drop policy if exists rf_leer_packing_fa on public.wms_packing_lists_fa;
create policy rf_leer_packing_fa on public.wms_packing_lists_fa for select to anon, authenticated using (true);

-- Sin borrar desde el celular en estas tablas
revoke delete on public.asn_cabecera, public.netsuite_ordenes_venta, public.netsuite_detalle_ov,
                 public.maestra_sku, public.auditoria_ciclico_sku, public.wms_packing_lists_fa from anon;
revoke insert, update on public.asn_cabecera, public.netsuite_ordenes_venta, public.netsuite_detalle_ov from anon;

-- ---------------------------------------------------------------------
-- 2) Políticas abiertas del kardex y de recepción de traslados
-- ---------------------------------------------------------------------
alter table public.historial_movimientos enable row level security;
-- Cualquier otra política que deje escribir/borrar el kardex con la clave pública se elimina
-- (el celular registra movimientos a través de las funciones, que no dependen de estas políticas)
do $$
declare p record;
begin
  for p in select policyname from pg_policies
           where schemaname = 'public' and tablename = 'historial_movimientos'
             and cmd in ('INSERT', 'UPDATE', 'DELETE', 'ALL')
             and policyname not in ('rf_insert_alertas', 'rf_delete_alertas')
  loop
    execute format('drop policy %I on public.historial_movimientos', p.policyname);
    raise notice 'Política del kardex eliminada: %', p.policyname;
  end loop;
end $$;
drop policy if exists rf_insert_alertas on public.historial_movimientos;
drop policy if exists rf_delete_alertas on public.historial_movimientos;
create policy rf_insert_alertas on public.historial_movimientos for insert to anon, authenticated
  with check (tipo_movimiento = 'ALERTA_VACIA_OCUPADA');
create policy rf_delete_alertas on public.historial_movimientos for delete to anon, authenticated
  using (tipo_movimiento = 'ALERTA_VACIA_OCUPADA');

drop policy if exists recepcion_ccp_insert on public.wms_recepcion_traslados_ccp;
drop policy if exists recepcion_ccp_update on public.wms_recepcion_traslados_ccp;

-- ---------------------------------------------------------------------
-- 3) TRUNCATE nunca desde la clave pública (no respeta RLS)
-- ---------------------------------------------------------------------
do $$
declare t record;
begin
  for t in select c.oid::regclass r from pg_class c
           where c.relnamespace = 'public'::regnamespace and c.relkind in ('r', 'p')
  loop
    execute format('revoke truncate, references, trigger on %s from anon, authenticated', t.r);
  end loop;
end $$;

-- ---------------------------------------------------------------------
-- 4) Índices de claves foráneas y PK faltante
-- ---------------------------------------------------------------------
do $$
declare k record; v_cols text; v_nombre text;
begin
  for k in
    select c.conrelid, c.conname, c.conkey
    from pg_constraint c
    where c.contype = 'f' and c.connamespace = 'public'::regnamespace
      and not exists (select 1 from pg_index i where i.indrelid = c.conrelid
                      and (i.indkey::int2[])[0:cardinality(c.conkey) - 1] @> c.conkey)
  loop
    select string_agg(quote_ident(a.attname), ', ' order by x.ord) into v_cols
    from unnest(k.conkey) with ordinality x(attnum, ord)
    join pg_attribute a on a.attrelid = k.conrelid and a.attnum = x.attnum;
    v_nombre := left('idx_fk_' || k.conname, 63);
    execute format('create index if not exists %I on %s (%s)', v_nombre, k.conrelid::regclass, v_cols);
    raise notice 'Índice % creado', v_nombre;
  end loop;
end $$;

do $$
begin
  if to_regclass('public.wms_carga_picking_fijo') is not null
     and not exists (select 1 from pg_constraint where conrelid = 'public.wms_carga_picking_fijo'::regclass and contype = 'p') then
    alter table public.wms_carga_picking_fijo add column if not exists id bigint generated by default as identity;
    alter table public.wms_carga_picking_fijo add primary key (id);
  end if;
end $$;

-- ---------------------------------------------------------------------
-- 5) Duplicados: también debe coincidir el LPN
-- ---------------------------------------------------------------------
create or replace function public.wms_eliminar_stock_duplicado(p_inventario_id bigint, p_usuario text, p_motivo text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_usuario text := public.wms_contexto(p_usuario, 'wms_eliminar_stock_duplicado');
  o record;
  v_gemelo bigint;
begin
  if not public.wms_puede_depurar_stock(p_usuario) then
    raise exception 'WMS: su usuario no está autorizado para eliminar stock duplicado';
  end if;
  select * into o from bodega_inventario_ubicacion where id = p_inventario_id for update;
  if not found then raise exception 'WMS: esa fila de stock ya no existe (actualice la consulta)'; end if;
  select i.id into v_gemelo
  from bodega_inventario_ubicacion i
  where i.id <> o.id and i.bodega = o.bodega and i.codigo_ubicacion = o.codigo_ubicacion and i.sku = o.sku
    and coalesce(i.lote, 'S/L') = coalesce(o.lote, 'S/L')
    and coalesce(i.fecha_vencimiento_cl, '') = coalesce(o.fecha_vencimiento_cl, '')
    and i.cantidad_unidades = o.cantidad_unidades
    and coalesce(i.lpn, '') = coalesce(o.lpn, '')   -- dos pallets distintos (otro LPN) no son duplicado
  order by i.id
  limit 1;
  if v_gemelo is null then
    raise exception 'WMS: no hay otra fila igual en % (mismo LPN, SKU, lote, vencimiento y cantidad). Si el stock está mal, corríjalo con conteo cíclico.', o.codigo_ubicacion;
  end if;
  delete from bodega_inventario_ubicacion where id = o.id;
  perform public.wms_kardex(o.bodega, 'ELIMINAR_DUPLICADO', o.lpn, o.sku, o.lote, o.codigo_ubicacion,
                            left('DUPLICADO DE ID ' || v_gemelo || coalesce(' · ' || nullif(btrim(p_motivo), ''), ''), 120),
                            coalesce(o.cajas, 0), o.cantidad_unidades);
  return jsonb_build_object('eliminado', o.id, 'se_conserva', v_gemelo, 'ubicacion', o.codigo_ubicacion,
                            'sku', o.sku, 'lpn', o.lpn, 'unidades', o.cantidad_unidades);
end $$;

commit;

-- Resultado: estado de seguridad de las tablas tocadas
select c.relname as tabla, c.relrowsecurity as rls_activo,
       has_table_privilege('anon', c.oid, 'DELETE') as anon_puede_borrar,
       (select string_agg(p.policyname || ' (' || p.cmd || ')', ', ' order by p.policyname)
          from pg_policies p where p.schemaname = 'public' and p.tablename = c.relname) as politicas
from pg_class c
where c.relnamespace = 'public'::regnamespace
  and c.relname in ('asn_cabecera', 'netsuite_ordenes_venta', 'netsuite_detalle_ov', 'maestra_sku',
                    'auditoria_ciclico_sku', 'wms_packing_lists_fa', 'historial_movimientos', 'wms_recepcion_traslados_ccp')
order by 1;

-- ---------------------------------------------------------------------
-- DESHACER EL PUNTO 1 (solo si el celular falla al leer/guardar alguna de estas tablas):
-- alter table public.asn_cabecera disable row level security;
-- alter table public.netsuite_ordenes_venta disable row level security;
-- alter table public.netsuite_detalle_ov disable row level security;
-- alter table public.maestra_sku disable row level security;
-- alter table public.auditoria_ciclico_sku disable row level security;
-- alter table public.wms_packing_lists_fa disable row level security;
