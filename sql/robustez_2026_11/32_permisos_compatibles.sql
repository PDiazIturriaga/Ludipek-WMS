-- =====================================================================
-- LUDIPEK WMS · 32 PERMISOS COMPATIBLES CON LA APP ANTERIOR  (requiere 31)
-- Usuarios guardados desde el PC solo con permisos nuevos (APP_...) veían en un celular
-- con la app anterior solo "Consulta de stock", porque esa versión solo entiende RF_...
-- Este script agrega a cada usuario los permisos antiguos equivalentes a los nuevos que
-- tiene marcados. La app nueva (2026.11.20.7+) usa solo los APP_ y no cambia nada.
-- =====================================================================
begin;

update public.wms_usuarios u
   set modulos_rf = (
         select array(select distinct x from unnest(
                  u.modulos_rf ||
                  coalesce((select array_agg(l.antiguo) from (values
                      ('APP_RECEPCION', 'RF_RECEPCION'), ('APP_MAESTRA', 'RF_RECEPCION'), ('APP_TRASLADOS', 'RF_TRASLADOS'),
                      ('APP_ALMACENAMIENTO', 'RF_PUTAWAY'), ('APP_REABASTECIMIENTO', 'RF_REABASTECIMIENTO'),
                      ('APP_PICKING', 'RF_PICKING'), ('APP_PICKING_FARMACIA', 'RF_PICKING'), ('APP_PACKING', 'RF_PICKING'),
                      ('APP_STOCK_CONTEO', 'RF_CONSULTA'), ('APP_VACIAS', 'RF_INVENTARIO'), ('APP_CICLICO_SKU', 'RF_INVENTARIO')
                    ) l(nuevo, antiguo) where l.nuevo = any(u.modulos_rf)), '{}')) x
                order by x))
 where exists (select 1 from unnest(u.modulos_rf) p where p like 'APP\_%');

commit;

-- Revisión
select usuario, rol, modulos_rf from public.wms_usuarios order by usuario;
