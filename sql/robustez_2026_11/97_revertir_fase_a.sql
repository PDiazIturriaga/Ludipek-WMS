-- =====================================================================
-- LUDIPEK WMS · 97 REVERTIR FASE A (02-04)  — solo en caso de emergencia
-- Quita triggers, reglas y funciones nuevas. La limpieza de datos (01) no
-- se revierte con SQL: para eso use el respaldo previo de Supabase.
-- La tabla de auditoría NO se borra (conserva el historial capturado).
-- =====================================================================
begin;
drop trigger if exists trg_a_inventario_normalizar on public.bodega_inventario_ubicacion;
drop trigger if exists trg_z_auditar_inventario   on public.bodega_inventario_ubicacion;
drop trigger if exists trg_a_recepcion_normalizar  on public.registro_recepcion;
drop trigger if exists trg_a_kardex_normalizar     on public.historial_movimientos;
drop trigger if exists trg_kardex_inmutable        on public.historial_movimientos;

alter table public.bodega_inventario_ubicacion drop constraint if exists ck_inv_bodega_valida;
alter table public.bodega_inventario_ubicacion drop constraint if exists ck_inv_cajas_no_neg;
alter table public.bodega_inventario_ubicacion drop constraint if exists ck_inv_ubicacion;
alter table public.bodega_inventario_ubicacion drop constraint if exists fk_inv_ubicacion_maestra;
alter table public.registro_recepcion          drop constraint if exists ck_rec_bodega_valida;
alter table public.registro_recepcion          drop constraint if exists ck_rec_cantidades;
alter table public.bodega_ubicaciones          drop constraint if exists ck_ubic_bodega_valida;
alter table public.netsuite_ordenes_venta      drop constraint if exists ck_ov_bodega_valida;
alter table public.netsuite_detalle_ov         drop constraint if exists ck_det_pickeado_rango;
alter table public.historial_movimientos       drop constraint if exists ck_kardex_bodega_valida;

drop function if exists public.wms_cerrar_pallet_recepcion(text, text, jsonb, bigint, text, text);
drop function if exists public.wms_consultar_lpn(text, text);
drop function if exists public.wms_almacenar_lpn(text, text, text, text);
drop function if exists public.wms_mover_a_picking(bigint, integer, text, text);
drop function if exists public.wms_salida_picking(text, text, text, integer, text, text, text);
drop function if exists public.wms_registrar_conteo(text, text, text, text, text, text, integer, text, bigint, text);
drop function if exists public.wms_recibir_pallet_traslado(bigint, text, jsonb, text, text, text);
drop function if exists public.wms_cerrar_recepcion_traslado(bigint, text, text);
drop function if exists public.wms_traslado_ccp_detalle(bigint);
drop function if exists public.wms_traslados_ccp(boolean);
drop function if exists public.wms_traslado_lineas_despachadas(bigint);
drop function if exists public.wms_version_minima();
drop function if exists public.wms_despacho_de_orden(bigint);
drop function if exists public.wms_crear_tarea_conteo(text, text, text, text, text, text);
drop function if exists public.wms_tareas_conteo(text, text, boolean);
drop function if exists public.wms_actualizar_tarea_conteo(bigint, text, text);
drop trigger if exists tg_estado_unico_ov on public.netsuite_ordenes_venta;
drop function if exists public.wms_tg_estado_unico_ov();
drop function if exists public.wms_cerrar_packing(bigint, text, jsonb, integer, text, text, text, numeric, numeric, bigint, text);
drop function if exists public.wms_cerrar_packing(bigint, text, jsonb, integer, text, text, text, numeric, numeric, bigint, text, text);
drop function if exists public.wms_cerrar_picking(bigint, jsonb, text);
drop function if exists public.wms_cerrar_picking(bigint, jsonb, text, text);
drop function if exists public.wms_ordenes_en_mesa(text, text);
drop function if exists public.wms_asignar_mesa_packing(bigint, text, text);
drop function if exists public.wms_normalizar_mesa(text);
drop function if exists public.wms_cambiar_estado_ov(bigint, text, text, text, boolean);
drop function if exists public.wms_orden_estado_ov(text);
-- wms_login y wms_cambiar_password se conservan: las apps nuevas las necesitan para entrar.
commit;
