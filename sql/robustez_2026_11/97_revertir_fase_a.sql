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
drop function if exists public.wms_alertas_operacion(text);
drop function if exists public.wms_marcar_alerta_revisada(text, text[], text, text, text);
drop function if exists public.wms_sugerir_ubicacion_lpn(text, text);
drop function if exists public.wms_asignar_picking_fijo(text, text, text, text);
drop function if exists public.wms_picking_fijo_skus(text, text[]);
drop function if exists public.wms_picking_fijo_sku(text, text);
-- La tabla wms_ubicacion_picking_sku se conserva (asignaciones de picking).
drop function if exists public.wms_asignar_ovs_por_equipo(text, text);
drop function if exists public.wms_mover_usuario_equipo(text, text, text);
drop function if exists public.wms_ov_sin_iniciar(bigint);
drop function if exists public.wms_tipo_picking_ov(text, text);
drop function if exists public.wms_multiplo_sku(text, text, text);
-- La corrección de unidades queda en wms_respaldo_unidades_cajas (columna antes) por si hay que deshacerla.
drop function if exists public.wms_mis_almacenamientos(text, text, integer);
drop function if exists public.wms_crear_reporte_operacion(text, text, text, text, text, text, text, text);
drop function if exists public.wms_eliminar_stock_duplicado(bigint, text, text);
drop function if exists public.wms_puede_depurar_stock(text);
drop function if exists public.wms_mover_lpn_a_picking(bigint, text, text);
drop function if exists public.wms_es_ubicacion_picking(text);
drop function if exists public.wms_es_ubicacion_arena(text);
drop function if exists public.wms_es_ubicacion_merma(text);
-- Las ubicaciones de arena (MK/ME/BE) se conservan: pueden tener stock.
drop function if exists public.wms_version_minima();
drop function if exists public.wms_despacho_de_orden(bigint);
drop function if exists public.wms_crear_tarea_conteo(text, text, text, text, text, text);
drop function if exists public.wms_tareas_conteo(text, text, boolean);
drop function if exists public.wms_ts_app(timestamptz);
drop function if exists public.wms_eliminar_pallet(text, text, text, text, text);
drop function if exists public.wms_lpns_en_anden(text);
drop function if exists public.wms_es_admin(text);
drop function if exists public.wms_consulta_stock_operador(text, text);
-- 24: primero desinstalar el portero
alter role authenticator reset pgrst.db_pre_request;
notify pgrst, 'reload config';
drop function if exists public.wms_pre_request();
drop function if exists public.wms_iniciar_sesion(text, text, text);
drop function if exists public.wms_cerrar_sesion();
drop function if exists public.wms_cerrar_sesiones_usuario(text);
drop function if exists public.wms_anular_ov(bigint, text, text);
drop function if exists public.wms_registrar_error(text, text, text, text, text, text, text);
drop function if exists public.wms_reservar_lpn(text, integer, text);
drop function if exists public.wms_reservar_correlativo(text, integer, text, bigint);
drop function if exists public.wms_max_lpn_rango(text, bigint, bigint);
drop function if exists public.wms_dashboard_resumen(text, integer);
-- 30: la función wms_tareas_conteo vuelve a la versión del 20 ejecutando ese script
drop function if exists public.wms_vacias_de_tarea(text, text, timestamptz);
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
