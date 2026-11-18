-- =====================================================================
-- LUDIPEK WMS · 02 REGLAS DE INTEGRIDAD  (FASE A · requiere 01)
-- La base de datos pasa a rechazar datos inválidos, venga de donde venga
-- (PC, celular, Excel o un script): SKU sucio, fechas mal escritas,
-- ubicaciones inexistentes, bodegas desconocidas, cantidades negativas.
-- Compatible con las apps actuales.
-- =====================================================================
begin;

-- ---------------------------------------------------------------------
-- 1. Inventario: columna de fecha real (para FEFO) y normalización automática
-- ---------------------------------------------------------------------
alter table public.bodega_inventario_ubicacion add column if not exists fecha_vencimiento date;
update public.bodega_inventario_ubicacion
   set fecha_vencimiento = public.wms_fecha_desde_texto(fecha_vencimiento_cl)
 where fecha_vencimiento is distinct from public.wms_fecha_desde_texto(fecha_vencimiento_cl);

create or replace function public.wms_trg_inventario_normalizar()
returns trigger language plpgsql as $$
declare
  v_fecha date;
begin
  new.sku := public.wms_normalizar_sku(new.sku);
  if new.sku = '' then
    raise exception 'WMS: el SKU es obligatorio';
  end if;
  new.lote   := public.wms_normalizar_lote(new.lote);
  new.bodega := coalesce(nullif(btrim(new.bodega), ''), 'Bodega Santiago');
  new.codigo_ubicacion := upper(btrim(coalesce(new.codigo_ubicacion, '')));
  if new.codigo_ubicacion = '' then
    raise exception 'WMS: la ubicación es obligatoria (SKU %)', new.sku;
  end if;
  new.lpn := nullif(upper(btrim(coalesce(new.lpn, ''))), '');

  if upper(btrim(coalesce(new.fecha_vencimiento_cl, ''))) in ('', 'S/F') then
    if tg_op = 'INSERT' or new.fecha_vencimiento_cl is distinct from old.fecha_vencimiento_cl then
      new.fecha_vencimiento_cl := public.wms_fecha_cl(new.fecha_vencimiento);
    end if;
  else
    v_fecha := public.wms_fecha_desde_texto(new.fecha_vencimiento_cl);
    if v_fecha is null then
      raise exception 'WMS: vencimiento inválido "%" (SKU %). Use DD-MM-YYYY', new.fecha_vencimiento_cl, new.sku;
    end if;
    new.fecha_vencimiento    := v_fecha;
    new.fecha_vencimiento_cl := public.wms_fecha_cl(v_fecha);
  end if;

  new.cajas := coalesce(new.cajas, 0);
  new.zona  := case when new.codigo_ubicacion like 'ZONA-%' then split_part(new.codigo_ubicacion, '-', 2)
                    else split_part(new.codigo_ubicacion, '-', 1) end;
  new.updated_at := now();
  return new;
end $$;

drop trigger if exists trg_a_inventario_normalizar on public.bodega_inventario_ubicacion;
create trigger trg_a_inventario_normalizar
  before insert or update on public.bodega_inventario_ubicacion
  for each row execute function public.wms_trg_inventario_normalizar();

-- ---------------------------------------------------------------------
-- 2. Recepción: normaliza ANTES del trigger existente (que exige DD-MM-YYYY)
--    Así '22/05/2028' o '2028-05-22' se aceptan y quedan como '22-05-2028'.
-- ---------------------------------------------------------------------
create or replace function public.wms_trg_recepcion_normalizar()
returns trigger language plpgsql as $$
declare
  v_fecha date;
begin
  new.sku    := public.wms_normalizar_sku(new.sku);
  new.lote   := public.wms_normalizar_lote(new.lote);
  new.lpn    := upper(btrim(new.lpn));
  new.bodega := coalesce(nullif(btrim(new.bodega), ''), 'Bodega Santiago');
  new.codigo_barras_escaneado := coalesce(nullif(btrim(new.codigo_barras_escaneado), ''), new.sku);
  if upper(btrim(coalesce(new.fecha_vencimiento_cl, ''))) in ('', 'S/F') then
    new.fecha_vencimiento_cl := null;
  else
    v_fecha := public.wms_fecha_desde_texto(new.fecha_vencimiento_cl);
    if v_fecha is null then
      raise exception 'WMS: vencimiento inválido "%" (LPN %, SKU %). Use DD-MM-YYYY', new.fecha_vencimiento_cl, new.lpn, new.sku;
    end if;
    new.fecha_vencimiento_cl := public.wms_fecha_cl(v_fecha);
  end if;
  return new;
end $$;

-- el nombre empieza con "trg_a_" para ejecutarse antes que trg_procesar_linea_recepcion
drop trigger if exists trg_a_recepcion_normalizar on public.registro_recepcion;
create trigger trg_a_recepcion_normalizar
  before insert or update on public.registro_recepcion
  for each row execute function public.wms_trg_recepcion_normalizar();

-- ---------------------------------------------------------------------
-- 3. Avance de la OC: el trigger original no recalculaba al borrar o al
--    cambiar el SKU de una recepción (usaba solo NEW).
-- ---------------------------------------------------------------------
create or replace function public.fn_actualizar_avance_asn()
returns trigger language plpgsql as $$
declare
  r record;
begin
  for r in
    select distinct x.asn_id, x.sku
    from (select new.asn_id as asn_id, new.sku as sku where tg_op in ('INSERT', 'UPDATE')
          union all
          select old.asn_id, old.sku where tg_op in ('UPDATE', 'DELETE')) x
    where x.asn_id is not null
  loop
    update public.asn_detalle d
       set unidades_recibidas = (select coalesce(sum(rr.unidades_totales), 0)
                                 from public.registro_recepcion rr
                                 where rr.asn_id = r.asn_id and rr.sku = r.sku)
     where d.asn_id = r.asn_id and d.sku = r.sku;
    update public.asn_cabecera set estado = 'EN_RECEPCION'
     where id = r.asn_id and estado = 'PENDIENTE';
  end loop;
  return coalesce(new, old);
end $$;

-- ---------------------------------------------------------------------
-- 4. Kardex: la fecha la pone el servidor (los teléfonos enviaban hora
--    local sin zona y quedaba desfasada 3 horas) y el SKU va normalizado.
-- ---------------------------------------------------------------------
create or replace function public.wms_trg_kardex_normalizar()
returns trigger language plpgsql as $$
begin
  new.fecha  := now();
  new.sku    := coalesce(nullif(public.wms_normalizar_sku(new.sku), ''), 'S/SKU');
  new.lote   := public.wms_normalizar_lote(new.lote);
  new.lpn    := nullif(upper(btrim(coalesce(new.lpn, ''))), '');
  new.bodega := coalesce(nullif(btrim(new.bodega), ''), 'Bodega Santiago');
  return new;
end $$;

drop trigger if exists trg_a_kardex_normalizar on public.historial_movimientos;
create trigger trg_a_kardex_normalizar
  before insert on public.historial_movimientos
  for each row execute function public.wms_trg_kardex_normalizar();

-- ---------------------------------------------------------------------
-- 5. Reglas (CHECK) y relación inventario -> maestra de ubicaciones
-- ---------------------------------------------------------------------
do $$
declare
  c record;
begin
  for c in select * from (values
    ('bodega_inventario_ubicacion', 'ck_inv_bodega_valida',   $c$check (bodega in ('Bodega Santiago','Bodega Concepcion'))$c$),
    ('bodega_inventario_ubicacion', 'ck_inv_cajas_no_neg',    $c$check (cajas >= 0)$c$),
    ('bodega_inventario_ubicacion', 'ck_inv_ubicacion',       $c$check (codigo_ubicacion is not null and codigo_ubicacion <> '')$c$),
    ('registro_recepcion',          'ck_rec_bodega_valida',   $c$check (bodega in ('Bodega Santiago','Bodega Concepcion'))$c$),
    ('registro_recepcion',          'ck_rec_cantidades',      $c$check (cajas >= 0 and unidades_sueltas >= 0)$c$),
    ('bodega_ubicaciones',          'ck_ubic_bodega_valida',  $c$check (bodega in ('Bodega Santiago','Bodega Concepcion'))$c$),
    ('netsuite_ordenes_venta',      'ck_ov_bodega_valida',    $c$check (bodega in ('Bodega Santiago','Bodega Concepcion'))$c$),
    ('netsuite_detalle_ov',         'ck_det_pickeado_rango',  $c$check (coalesce(cantidad_pickeada,0) between 0 and cantidad_pedida)$c$),
    ('historial_movimientos',       'ck_kardex_bodega_valida',$c$check (bodega in ('Bodega Santiago','Bodega Concepcion'))$c$),
    ('bodega_inventario_ubicacion', 'fk_inv_ubicacion_maestra',
       $c$foreign key (bodega, codigo_ubicacion) references public.bodega_ubicaciones (bodega, codigo_ubicacion) on update cascade on delete restrict$c$)
  ) as t(tabla, nombre, def)
  loop
    if not exists (select 1 from pg_constraint where conname = c.nombre) then
      execute format('alter table public.%I add constraint %I %s not valid', c.tabla, c.nombre, c.def);
    end if;
    begin
      execute format('alter table public.%I validate constraint %I', c.tabla, c.nombre);
    exception when others then
      raise warning 'WMS: la regla % quedó activa solo para datos NUEVOS; hay filas antiguas que no la cumplen (%). Revise 00_diagnostico.sql', c.nombre, sqlerrm;
    end;
  end loop;
end $$;

-- ---------------------------------------------------------------------
-- 6. Índices para las consultas de la operación (FEFO, LPN, kardex)
-- ---------------------------------------------------------------------
create index if not exists idx_inv_bodega_sku_venc on public.bodega_inventario_ubicacion (bodega, sku, fecha_vencimiento);
create index if not exists idx_inv_lpn            on public.bodega_inventario_ubicacion (lpn);
create index if not exists idx_inv_bodega_ubic    on public.bodega_inventario_ubicacion (bodega, codigo_ubicacion);
create index if not exists idx_kardex_lpn         on public.historial_movimientos (lpn);
create index if not exists idx_kardex_sku_fecha   on public.historial_movimientos (sku, fecha desc);
create index if not exists idx_det_orden          on public.netsuite_detalle_ov (orden_id);

-- ---------------------------------------------------------------------
-- 7. Acceso del celular (clave pública) a tablas con RLS sin políticas.
--    Sin esto el teléfono NO ve las líneas de la OC (asn_detalle) y las
--    auditorías de ubicaciones vacías se pierden en silencio.
-- ---------------------------------------------------------------------
drop policy if exists rf_select_asn_detalle on public.asn_detalle;
create policy rf_select_asn_detalle on public.asn_detalle for select to anon, authenticated using (true);

drop policy if exists rf_select_vacias on public.auditoria_ubicaciones_vacias;
create policy rf_select_vacias on public.auditoria_ubicaciones_vacias for select to anon, authenticated using (true);
drop policy if exists rf_insert_vacias on public.auditoria_ubicaciones_vacias;
create policy rf_insert_vacias on public.auditoria_ubicaciones_vacias for insert to anon, authenticated with check (true);

drop policy if exists rf_select_asignaciones on public.wms_asignaciones_pasillo;
create policy rf_select_asignaciones on public.wms_asignaciones_pasillo for select to anon, authenticated using (true);

commit;
