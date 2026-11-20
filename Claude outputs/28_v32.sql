-- =====================================================================
-- LUDIPEK WMS · 28 PERMISOS DEL PC (clave de servicio) SOBRE LAS TABLAS NUEVAS
-- Error que corrige: "permission denied for table wms_cencosud_hu" (y lo mismo en otras
-- tablas creadas por los scripts: wms_correlativos, wms_lpn_lotes, wms_sesiones,
-- wms_log_errores, wms_bajas_pallet, wms_reportes_operacion, wms_ubicacion_picking_sku...).
-- En este proyecto de Supabase las tablas nuevas NO quedan habilitadas automáticamente para
-- la clave de servicio que usa el PC; hay que darle el permiso explícito.
-- No abre nada al celular ni a la clave pública: solo a service_role (el PC).
-- Se puede ejecutar las veces que quiera.
-- =====================================================================
grant usage on schema public to service_role;
grant select, insert, update, delete on all tables in schema public to service_role;
grant usage, select, update on all sequences in schema public to service_role;
grant execute on all functions in schema public to service_role;

-- Tablas y funciones que se creen en el futuro quedan habilitadas para el PC desde el inicio
alter default privileges in schema public grant select, insert, update, delete on tables to service_role;
alter default privileges in schema public grant usage, select, update on sequences to service_role;
alter default privileges in schema public grant execute on functions to service_role;

-- Revisión: todas deben decir true
select c.relname as tabla,
       has_table_privilege('service_role', c.oid, 'SELECT') as pc_lee,
       has_table_privilege('service_role', c.oid, 'INSERT') as pc_escribe
from pg_class c
where c.relnamespace = 'public'::regnamespace and c.relkind = 'r'
  and c.relname in ('wms_cencosud_hu', 'wms_correlativos', 'wms_lpn_lotes', 'wms_sesiones', 'wms_log_errores',
                    'wms_bajas_pallet', 'wms_reportes_operacion', 'wms_ubicacion_picking_sku', 'wms_config')
order by 1;
