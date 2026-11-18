-- =====================================================================
-- LUDIPEK WMS · 98 REVERTIR FASE B (05)  — solo en caso de emergencia
-- Vuelve a permitir escritura directa con la clave pública (apps antiguas).
-- NO descifra contraseñas (06 es irreversible): si ya corrió 06, las apps
-- antiguas del celular no podrán iniciar sesión; use wms_login().
-- =====================================================================
begin;
drop index if exists public.uq_inv_bodega_ubic_sku_lote_lpn;

grant insert, update, delete on public.bodega_inventario_ubicacion to anon, authenticated;
drop policy if exists inv_lectura on public.bodega_inventario_ubicacion;
alter table public.bodega_inventario_ubicacion disable row level security;

grant insert, update, delete on public.registro_recepcion to anon, authenticated;
drop policy if exists rec_lectura on public.registro_recepcion;
alter table public.registro_recepcion disable row level security;

grant insert, update, delete on public.bodega_ubicaciones to anon, authenticated;
alter table public.bodega_ubicaciones disable row level security;

drop policy if exists rf_insert_alertas on public.historial_movimientos;
create policy "Permitir inserción de historial a todos" on public.historial_movimientos for insert to public with check (true);
alter table public.historial_movimientos disable row level security;

grant select, insert, update, delete on public.wms_usuarios to anon, authenticated;
create policy "Permitir lectura wms_usuarios" on public.wms_usuarios for all to public using (true) with check (true);
alter table public.wms_usuarios disable row level security;
commit;
