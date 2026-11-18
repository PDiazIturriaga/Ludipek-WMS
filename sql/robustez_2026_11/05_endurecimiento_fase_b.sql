-- =====================================================================
-- LUDIPEK WMS · 05 ENDURECIMIENTO  (FASE B)
-- ⚠ EJECUTAR SOLO CUANDO TODOS LOS CELULARES TENGAN LA APP NUEVA y el PC
--   esté actualizado. Las versiones antiguas del celular escriben stock
--   directo en las tablas y dejarán de funcionar (recibirán "permiso denegado").
--
-- Desde aquí, el stock (inventario y recepciones) SOLO cambia a través de
-- las funciones wms_* del script 04. Nadie con la clave pública puede
-- editar, borrar o inventar stock, ni leer contraseñas.
-- El PC usa la clave secreta (service_role) y no se ve afectado.
-- =====================================================================
begin;

-- ---------------------------------------------------------------------
-- 1. Un registro por (bodega, ubicación, SKU, lote, LPN)
-- ---------------------------------------------------------------------
do $$
begin
  if exists (select 1 from public.bodega_inventario_ubicacion
             group by bodega, codigo_ubicacion, sku, lote, coalesce(lpn, '') having count(*) > 1) then
    raise warning 'WMS: NO se creó el índice único de inventario: aún hay filas duplicadas. '
                  'Resuélvalas con la consulta 3 de 00_diagnostico.sql y vuelva a ejecutar este script.';
  else
    create unique index if not exists uq_inv_bodega_ubic_sku_lote_lpn
      on public.bodega_inventario_ubicacion (bodega, codigo_ubicacion, sku, lote, coalesce(lpn, ''));
  end if;
end $$;

-- ---------------------------------------------------------------------
-- 2. Inventario y recepciones: lectura libre, escritura solo vía funciones
-- ---------------------------------------------------------------------
alter table public.bodega_inventario_ubicacion enable row level security;
drop policy if exists inv_lectura on public.bodega_inventario_ubicacion;
create policy inv_lectura on public.bodega_inventario_ubicacion for select to anon, authenticated using (true);
revoke insert, update, delete, truncate on public.bodega_inventario_ubicacion from anon, authenticated;

alter table public.registro_recepcion enable row level security;
drop policy if exists rec_lectura on public.registro_recepcion;
create policy rec_lectura on public.registro_recepcion for select to anon, authenticated using (true);
revoke insert, update, delete, truncate on public.registro_recepcion from anon, authenticated;

alter table public.bodega_ubicaciones enable row level security;
-- (la política "Permitir lectura ubicaciones" ya existe y se mantiene)
revoke insert, update, delete, truncate on public.bodega_ubicaciones from anon, authenticated;

-- ---------------------------------------------------------------------
-- 3. Kardex: el celular solo puede registrar/borrar alertas de ubicación
--    ocupada; todos los demás movimientos los escriben las funciones.
-- ---------------------------------------------------------------------
alter table public.historial_movimientos enable row level security;
drop policy if exists "Permitir inserción de historial a todos" on public.historial_movimientos;
drop policy if exists rf_insert_alertas on public.historial_movimientos;
create policy rf_insert_alertas on public.historial_movimientos for insert to anon, authenticated
  with check (tipo_movimiento = 'ALERTA_VACIA_OCUPADA');
revoke update, truncate on public.historial_movimientos from anon, authenticated;

-- ---------------------------------------------------------------------
-- 4. Usuarios: la clave pública ya no puede leer ni modificar usuarios.
--    El login del celular usa la función wms_login().
-- ---------------------------------------------------------------------
drop policy if exists "Permitir lectura de usuarios" on public.wms_usuarios;
drop policy if exists "Permitir lectura wms_usuarios" on public.wms_usuarios;
alter table public.wms_usuarios enable row level security;
revoke all on public.wms_usuarios from anon, authenticated;

commit;
