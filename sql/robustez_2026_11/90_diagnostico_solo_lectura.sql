-- =====================================================================
-- LUDIPEK WMS · 90 DIAGNÓSTICO (SOLO LECTURA)
-- No modifica ningún dato ni tabla: solo consulta el catálogo y cuenta registros.
-- (Crea 2 funciones temporales en pg_temp que desaparecen al cerrar la sesión.)
--
-- Cómo usarlo: péguelo completo en el SQL Editor de Supabase y presione Run.
-- El resultado es UNA tabla ordenada por gravedad. Expórtela a CSV
-- ("Download CSV") y envíela para armar el plan de mejoras.
--   estado:   REVISAR = encontró casos · OK = sin problemas · NO SE PUDO = falta tabla/columna
--   ejemplos: hasta 8 casos para ubicarlos (nunca muestra contraseñas)
-- =====================================================================

create or replace function pg_temp.dx_contar(p_sql text) returns bigint
language plpgsql as $$
declare n bigint;
begin
  if p_sql is null then return null; end if;
  execute p_sql into n;
  return n;
exception when others then
  return null;
end $$;

create or replace function pg_temp.dx_ejemplos(p_sql text) returns text
language plpgsql as $$
declare t text;
begin
  if p_sql is null then return null; end if;
  execute format('select string_agg(x::text, '' | '') from (select * from (%s) q limit 8) z(x)', p_sql) into t;
  return t;
exception when others then
  return null;
end $$;

with chequeos (orden, area, revision, sev, sql_n, sql_ej, que_hacer) as (
values
-- =============================== SEGURIDAD ===============================
(101, 'SEGURIDAD', 'Tablas SIN RLS que la clave pública (anon) puede MODIFICAR', 'CRITICO',
 $q$select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relkind in ('r','p') and not c.relrowsecurity
      and has_table_privilege('anon', c.oid, 'INSERT,UPDATE,DELETE')$q$,
 $q$select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relkind in ('r','p') and not c.relrowsecurity
      and has_table_privilege('anon', c.oid, 'INSERT,UPDATE,DELETE') order by 1$q$,
 'Con la clave que va dentro de la app web cualquiera puede escribir en estas tablas. Activar RLS y quitar permisos a anon.'),
(102, 'SEGURIDAD', 'Tablas SIN RLS que la clave pública (anon) puede LEER', 'ALTO',
 $q$select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relkind in ('r','p') and not c.relrowsecurity
      and has_table_privilege('anon', c.oid, 'SELECT')$q$,
 $q$select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relkind in ('r','p') and not c.relrowsecurity
      and has_table_privilege('anon', c.oid, 'SELECT') order by 1$q$,
 'Datos visibles para cualquiera con la URL de la app. Activar RLS.'),
(103, 'SEGURIDAD', 'Políticas RLS abiertas (anon/public con condición "true" para escribir)', 'ALTO',
 $q$select count(*) from pg_policies where schemaname = 'public'
      and roles && array['anon','public']::name[] and cmd in ('ALL','INSERT','UPDATE','DELETE')
      and (coalesce(qual, 'true') = 'true' or coalesce(with_check, 'true') = 'true')$q$,
 $q$select tablename || ' (' || policyname || ', ' || cmd || ')' from pg_policies where schemaname = 'public'
      and roles && array['anon','public']::name[] and cmd in ('ALL','INSERT','UPDATE','DELETE')
      and (coalesce(qual, 'true') = 'true' or coalesce(with_check, 'true') = 'true') order by 1$q$,
 'Una política "true" equivale a no tener RLS. Reemplazar por políticas por usuario/rol.'),
(104, 'SEGURIDAD', 'Funciones SECURITY DEFINER que anon puede ejecutar', 'ALTO',
 $q$select count(*) from pg_proc p where p.pronamespace = 'public'::regnamespace and p.prosecdef
      and has_function_privilege('anon', p.oid, 'EXECUTE')$q$,
 $q$select p.proname from pg_proc p where p.pronamespace = 'public'::regnamespace and p.prosecdef
      and has_function_privilege('anon', p.oid, 'EXECUTE') order by 1$q$,
 'Hoy el celular las necesita así, pero el usuario viaja como texto sin verificar. Con login real de Supabase se restringen a usuarios autenticados.'),
(105, 'SEGURIDAD', 'Funciones SECURITY DEFINER sin search_path fijo', 'MEDIO',
 $q$select count(*) from pg_proc p where p.pronamespace = 'public'::regnamespace and p.prosecdef
      and not exists (select 1 from unnest(coalesce(p.proconfig, '{}')) c where c like 'search_path=%')$q$,
 $q$select p.proname from pg_proc p where p.pronamespace = 'public'::regnamespace and p.prosecdef
      and not exists (select 1 from unnest(coalesce(p.proconfig, '{}')) c where c like 'search_path=%') order by 1$q$,
 'Agregar "set search_path = public" para evitar que se suplanten tablas/funciones.'),
(106, 'SEGURIDAD', 'Contraseñas de wms_usuarios guardadas sin cifrar (no parecen hash bcrypt)', 'CRITICO',
 (select format('select count(*) from public.wms_usuarios where coalesce(%1$I::text, '''') <> '''' and %1$I::text not like ''$2%%'' and length(%1$I::text) < 50', column_name)
    from information_schema.columns
   where table_schema = 'public' and table_name = 'wms_usuarios' and column_name ~* '(pass|clave|contras)' limit 1),
 (select format('select %L', 'columna ' || column_name)
    from information_schema.columns
   where table_schema = 'public' and table_name = 'wms_usuarios' and column_name ~* '(pass|clave|contras)' limit 1),
 'Las claves se pueden leer tal cual. Migrar el login a Supabase Auth (claves cifradas) o al menos guardarlas con hash.'),
(107, 'SEGURIDAD', 'Usuarios administradores activos', 'INFO',
 $q$select count(*) from public.wms_usuarios where coalesce(activo, true) and upper(coalesce(rol, '')) like '%ADMIN%'$q$,
 $q$select usuario || ' (' || coalesce(nombre_completo, '') || ')' from public.wms_usuarios
    where coalesce(activo, true) and upper(coalesce(rol, '')) like '%ADMIN%' order by 1$q$,
 'Confirmar que todos deban ser administradores (pueden dar de baja pallets, etc.).'),

-- ============================== ESTRUCTURA ===============================
(201, 'ESTRUCTURA', 'Scripts de robustez que NO están aplicados', 'ALTO',
 $q$select count(*) from (values ('04','wms_almacenar_lpn'),('09','wms_tareas_conteo'),('12','wms_cerrar_packing'),
      ('13','wms_recibir_pallet_traslado'),('14','wms_alertas_operacion'),('15','wms_mover_lpn_a_picking'),
      ('16','wms_eliminar_stock_duplicado'),('17','wms_multiplo_sku'),('18','wms_asignar_ovs_por_equipo'),
      ('19','wms_sugerir_ubicacion_lpn'),('20','wms_ts_app'),('21','wms_eliminar_pallet'),('22','wms_consulta_stock_operador'),
      ('24','wms_iniciar_sesion'),('25','wms_anular_ov'),('26','wms_registrar_error'),('27','wms_reservar_correlativo'),
      ('29','wms_dashboard_resumen'),('30','wms_vacias_de_tarea'),('33','wms_conciliar_recepciones'),('34','wms_reportar_problema'),('40','wms_carga_cerrar')) s(n, f)
    where not exists (select 1 from pg_proc p where p.pronamespace = 'public'::regnamespace and p.proname = s.f)$q$,
 $q$select s.n || ' (' || s.f || ')' from (values ('04','wms_almacenar_lpn'),('09','wms_tareas_conteo'),('12','wms_cerrar_packing'),
      ('13','wms_recibir_pallet_traslado'),('14','wms_alertas_operacion'),('15','wms_mover_lpn_a_picking'),
      ('16','wms_eliminar_stock_duplicado'),('17','wms_multiplo_sku'),('18','wms_asignar_ovs_por_equipo'),
      ('19','wms_sugerir_ubicacion_lpn'),('20','wms_ts_app'),('21','wms_eliminar_pallet'),('22','wms_consulta_stock_operador'),
      ('24','wms_iniciar_sesion'),('25','wms_anular_ov'),('26','wms_registrar_error'),('27','wms_reservar_correlativo'),
      ('29','wms_dashboard_resumen'),('30','wms_vacias_de_tarea'),('33','wms_conciliar_recepciones'),('34','wms_reportar_problema'),('40','wms_carga_cerrar')) s(n, f)
    where not exists (select 1 from pg_proc p where p.pronamespace = 'public'::regnamespace and p.proname = s.f) order by 1$q$,
 'Ejecutar los scripts que falten, en orden (ver LEEME_DESPLIEGUE.md).'),
(202, 'ESTRUCTURA', 'Script 14 sin la última versión (reportes con módulo y SKU)', 'MEDIO',
 $q$select count(*) from pg_proc p where p.pronamespace = 'public'::regnamespace and p.proname = 'wms_alertas_operacion'
      and p.prosrc not like '%r.modulo, r.tipo%'$q$,
 $q$select 'volver a ejecutar 14_alertas_operacion.sql'$q$,
 'Volver a ejecutar el 14.'),
(200, 'ESTRUCTURA', 'Funciones WMS con dos versiones (el celular falla con "Could not choose the best candidate")', 'CRITICO',
 $q$select count(*) from (select proname from pg_proc where pronamespace = 'public'::regnamespace and proname like 'wms\_%'
      group by proname having count(*) > 1) x$q$,
 $q$select proname || ' x' || count(*) from pg_proc where pronamespace = 'public'::regnamespace and proname like 'wms\_%'
      group by proname having count(*) > 1 order by 1$q$,
 'Borrar la versión antigua (drop function con su lista de parámetros) o volver a ejecutar el script más nuevo.'),
(203, 'ESTRUCTURA', 'Tablas sin clave primaria', 'MEDIO',
 $q$select count(*) from pg_class c where c.relnamespace = 'public'::regnamespace and c.relkind = 'r'
      and not exists (select 1 from pg_constraint k where k.conrelid = c.oid and k.contype = 'p')$q$,
 $q$select c.relname from pg_class c where c.relnamespace = 'public'::regnamespace and c.relkind = 'r'
      and not exists (select 1 from pg_constraint k where k.conrelid = c.oid and k.contype = 'p') order by 1$q$,
 'Sin PK no se pueden editar filas con seguridad ni replicar. Agregar id identity.'),
(204, 'ESTRUCTURA', 'Claves foráneas sin índice (deletes/joins lentos)', 'MEDIO',
 $q$select count(*) from pg_constraint k where k.contype = 'f' and k.connamespace = 'public'::regnamespace
      and not exists (select 1 from pg_index i where i.indrelid = k.conrelid and (i.indkey::int2[])[0:cardinality(k.conkey) - 1] @> k.conkey)$q$,
 $q$select k.conrelid::regclass || ' (' || k.conname || ')' from pg_constraint k where k.contype = 'f' and k.connamespace = 'public'::regnamespace
      and not exists (select 1 from pg_index i where i.indrelid = k.conrelid and (i.indkey::int2[])[0:cardinality(k.conkey) - 1] @> k.conkey) order by 1$q$,
 'Crear índice sobre la columna de la FK.'),
(205, 'ESTRUCTURA', 'Tablas grandes leídas sin índice (muchas lecturas secuenciales)', 'MEDIO',
 $q$select count(*) from pg_stat_user_tables where schemaname = 'public' and n_live_tup > 5000
      and seq_scan > 10 * coalesce(idx_scan, 0) + 100$q$,
 $q$select relname || ' · ' || seq_scan || ' lecturas completas vs ' || coalesce(idx_scan, 0) || ' por índice · ' || n_live_tup || ' filas'
    from pg_stat_user_tables where schemaname = 'public' and n_live_tup > 5000
      and seq_scan > 10 * coalesce(idx_scan, 0) + 100 order by seq_scan desc$q$,
 'Revisar qué consultas filtran estas tablas y agregar índices (bodega, sku, lpn, codigo_ubicacion, fecha).'),
(206, 'ESTRUCTURA', 'Índices que nunca se han usado (> 1 MB)', 'INFO',
 $q$select count(*) from pg_stat_user_indexes s join pg_index i on i.indexrelid = s.indexrelid
    where s.schemaname = 'public' and s.idx_scan = 0 and not i.indisunique and pg_relation_size(s.indexrelid) > 1048576$q$,
 $q$select s.indexrelname || ' (' || pg_size_pretty(pg_relation_size(s.indexrelid)) || ')' from pg_stat_user_indexes s
      join pg_index i on i.indexrelid = s.indexrelid
    where s.schemaname = 'public' and s.idx_scan = 0 and not i.indisunique and pg_relation_size(s.indexrelid) > 1048576
    order by pg_relation_size(s.indexrelid) desc$q$,
 'Ocupan espacio y hacen más lentas las escrituras; se pueden eliminar si siguen en 0.'),
(207, 'ESTRUCTURA', 'Tablas más grandes', 'INFO',
 $q$select count(*) from pg_class where relnamespace = 'public'::regnamespace and relkind = 'r'$q$,
 $q$select relname || ' ' || pg_size_pretty(pg_total_relation_size(oid)) || ' · ~' || greatest(reltuples, 0)::bigint || ' filas'
    from pg_class where relnamespace = 'public'::regnamespace and relkind = 'r' order by pg_total_relation_size(oid) desc$q$,
 'Referencia de volumen (historial y registros crecen sin límite: definir archivado).'),
(208, 'ESTRUCTURA', 'Columnas de texto cortas en tablas clave (posibles "value too long")', 'INFO',
 $q$select count(*) from information_schema.columns where table_schema = 'public'
      and table_name in ('bodega_inventario_ubicacion','bodega_ubicaciones','registro_recepcion','historial_movimientos',
                         'netsuite_ordenes_venta','netsuite_detalle_ov','maestra_sku')
      and character_maximum_length is not null and character_maximum_length <= 30$q$,
 $q$select table_name || '.' || column_name || '(' || character_maximum_length || ')' from information_schema.columns
    where table_schema = 'public'
      and table_name in ('bodega_inventario_ubicacion','bodega_ubicaciones','registro_recepcion','historial_movimientos',
                         'netsuite_ordenes_venta','netsuite_detalle_ov','maestra_sku')
      and character_maximum_length is not null and character_maximum_length <= 30 order by character_maximum_length, 1$q$,
 'Para alinear los scripts con producción (evita los errores varchar(10)/(100)). Envíe esta lista.'),
(209, 'ESTRUCTURA', 'Zona horaria de la base y versión mínima del celular', 'INFO',
 $q$select 0$q$,
 $q$select 'TimeZone=' || current_setting('TimeZone') union all
    select 'version_minima_rf=' || coalesce((select valor from public.wms_config where clave = 'version_minima_rf'), '(sin valor)')$q$,
 'Si la base está en UTC, el celular debe enviar las horas con zona horaria.'),

-- =============================== INVENTARIO ===============================
(301, 'INVENTARIO', 'Filas con unidades NEGATIVAS', 'CRITICO',
 $q$select count(*) from public.bodega_inventario_ubicacion where cantidad_unidades < 0$q$,
 $q$select codigo_ubicacion || ' ' || sku || ' ' || coalesce(lpn, '') || ' = ' || cantidad_unidades
    from public.bodega_inventario_ubicacion where cantidad_unidades < 0 order by cantidad_unidades$q$,
 'Stock imposible: corregir con conteo cíclico y buscar en el kardex qué lo dejó negativo.'),
(302, 'INVENTARIO', 'Filas en cero que siguen guardadas', 'MEDIO',
 $q$select count(*) from public.bodega_inventario_ubicacion where coalesce(cantidad_unidades, 0) = 0$q$,
 $q$select codigo_ubicacion || ' ' || sku || ' ' || coalesce(lpn, '') from public.bodega_inventario_ubicacion
    where coalesce(cantidad_unidades, 0) = 0 order by 1$q$,
 'Ensucian consultas y pueden marcar ubicaciones como ocupadas. Se pueden limpiar.'),
(303, 'INVENTARIO', 'SKU con stock que NO existen en la maestra', 'ALTO',
 $q$select count(distinct upper(i.sku)) from public.bodega_inventario_ubicacion i
    where i.cantidad_unidades > 0 and not exists (select 1 from public.maestra_sku m where upper(m.sku) = upper(i.sku))$q$,
 $q$select distinct upper(i.sku) from public.bodega_inventario_ubicacion i
    where i.cantidad_unidades > 0 and not exists (select 1 from public.maestra_sku m where upper(m.sku) = upper(i.sku)) order by 1$q$,
 'Sin maestra no hay descripción, múltiplo ni EAN: no se pueden pickear bien. Crear el SKU o corregir el código.'),
(304, 'INVENTARIO', 'Vencimientos mal escritos (no son DD-MM-AAAA)', 'ALTO',
 $q$select count(*) from public.bodega_inventario_ubicacion where cantidad_unidades > 0
      and nullif(btrim(coalesce(fecha_vencimiento_cl, '')), '') is not null
      and upper(fecha_vencimiento_cl) not in ('S/F', 'S/V', 'SIN FECHA')
      and fecha_vencimiento_cl !~ '^\d{2}-\d{2}-\d{4}$'$q$,
 $q$select distinct fecha_vencimiento_cl || ' (' || sku || ')' from public.bodega_inventario_ubicacion where cantidad_unidades > 0
      and nullif(btrim(coalesce(fecha_vencimiento_cl, '')), '') is not null
      and upper(fecha_vencimiento_cl) not in ('S/F', 'S/V', 'SIN FECHA')
      and fecha_vencimiento_cl !~ '^\d{2}-\d{2}-\d{4}$'$q$,
 'FEFO y alertas de vencimiento no las ven. Corregir el formato.'),
(305, 'INVENTARIO', 'Vencimiento en texto distinto a la columna fecha', 'MEDIO',
 $q$select count(*) from public.bodega_inventario_ubicacion where cantidad_unidades > 0 and fecha_vencimiento is not null
      and fecha_vencimiento_cl ~ '^(0[1-9]|[12]\d|3[01])-(0[1-9]|1[0-2])-\d{4}$'
      and to_date(fecha_vencimiento_cl, 'DD-MM-YYYY') <> fecha_vencimiento$q$,
 $q$select sku || ' ' || coalesce(lote, '') || ': ' || fecha_vencimiento_cl || ' vs ' || fecha_vencimiento from public.bodega_inventario_ubicacion
    where cantidad_unidades > 0 and fecha_vencimiento is not null
      and fecha_vencimiento_cl ~ '^(0[1-9]|[12]\d|3[01])-(0[1-9]|1[0-2])-\d{4}$'
      and to_date(fecha_vencimiento_cl, 'DD-MM-YYYY') <> fecha_vencimiento$q$,
 'Dos fuentes de verdad para la misma fecha. Unificar en una sola columna.'),
(306, 'INVENTARIO', 'Stock en ubicaciones que no existen en bodega_ubicaciones', 'ALTO',
 $q$select count(distinct i.bodega || i.codigo_ubicacion) from public.bodega_inventario_ubicacion i
    where i.cantidad_unidades > 0 and coalesce(i.codigo_ubicacion, '') not like 'ZONA-%'
      and not exists (select 1 from public.bodega_ubicaciones u where u.bodega = i.bodega and upper(u.codigo_ubicacion) = upper(i.codigo_ubicacion))$q$,
 $q$select distinct coalesce(i.codigo_ubicacion, '(vacía)') || ' · ' || coalesce(i.bodega, '') from public.bodega_inventario_ubicacion i
    where i.cantidad_unidades > 0 and coalesce(i.codigo_ubicacion, '') not like 'ZONA-%'
      and not exists (select 1 from public.bodega_ubicaciones u where u.bodega = i.bodega and upper(u.codigo_ubicacion) = upper(i.codigo_ubicacion))$q$,
 'Ubicaciones mal escritas (sin guiones, minúsculas) o no creadas. Mover el stock o crear la ubicación.'),
(307, 'INVENTARIO', 'Un mismo LPN en más de una ubicación de reserva', 'ALTO',
 $q$select count(*) from (select bodega, lpn from public.bodega_inventario_ubicacion
      where cantidad_unidades > 0 and coalesce(lpn, '') <> '' and codigo_ubicacion !~ '^[A-Z]-\d{2}-01$' and codigo_ubicacion <> 'ZONA-PICKING'
      group by bodega, lpn having count(distinct codigo_ubicacion) > 1) x$q$,
 $q$select lpn || ': ' || string_agg(distinct codigo_ubicacion, ', ') from public.bodega_inventario_ubicacion
      where cantidad_unidades > 0 and coalesce(lpn, '') <> '' and codigo_ubicacion !~ '^[A-Z]-\d{2}-01$' and codigo_ubicacion <> 'ZONA-PICKING'
      group by bodega, lpn having count(distinct codigo_ubicacion) > 1$q$,
 'Un pallet físico no puede estar en dos lugares: conteo cíclico en ambas ubicaciones.'),
(308, 'INVENTARIO', 'Filas duplicadas idénticas (misma ubicación, LPN, SKU, lote, vencimiento y cantidad)', 'MEDIO',
 $q$select coalesce(sum(n - 1), 0) from (select count(*) n from public.bodega_inventario_ubicacion where cantidad_unidades > 0
      group by bodega, codigo_ubicacion, coalesce(lpn, ''), upper(sku), coalesce(lote, ''), coalesce(fecha_vencimiento_cl, ''), cantidad_unidades having count(*) > 1) x$q$,
 $q$select codigo_ubicacion || ' ' || sku || ' ' || coalesce(lote, '') || ' x' || count(*) from public.bodega_inventario_ubicacion
    where cantidad_unidades > 0
    group by bodega, codigo_ubicacion, lpn, sku, lote, fecha_vencimiento_cl, cantidad_unidades having count(*) > 1$q$,
 'Posible stock inflado. Usar el botón de eliminar duplicados (usuario autorizado) o conteo cíclico.'),
(309, 'INVENTARIO', 'Unidades iguales a cajas en SKU que vienen en caja (> 1 UN por caja)', 'ALTO',
 $q$select count(*) from public.bodega_inventario_ubicacion i where i.cantidad_unidades > 0 and i.cajas = i.cantidad_unidades and i.cajas > 1
      and (select max(m.multiplo) from public.maestra_sku m where upper(m.sku) = upper(i.sku)) > 1$q$,
 $q$select i.sku || ' ' || coalesce(i.lpn, '') || ' en ' || i.codigo_ubicacion || ' (' || i.cantidad_unidades || ')' from public.bodega_inventario_ubicacion i
    where i.cantidad_unidades > 0 and i.cajas = i.cantidad_unidades and i.cajas > 1
      and (select max(m.multiplo) from public.maestra_sku m where upper(m.sku) = upper(i.sku)) > 1$q$,
 'Mismo problema del USA603: revisar con 17b y corregir con el 17.'),
(310, 'INVENTARIO', 'Lotes vencidos todavía disponibles (fuera de merma)', 'MEDIO',
 $q$select count(*) from public.bodega_inventario_ubicacion where cantidad_unidades > 0
      and coalesce(codigo_ubicacion, '') <> 'ZONA-MERMA' and codigo_ubicacion not like 'ME-%'
      and fecha_vencimiento_cl ~ '^(0[1-9]|[12]\d|3[01])-(0[1-9]|1[0-2])-\d{4}$'
      and to_date(fecha_vencimiento_cl, 'DD-MM-YYYY') < current_date$q$,
 $q$select sku || ' lote ' || coalesce(lote, '') || ' venció ' || fecha_vencimiento_cl || ' en ' || codigo_ubicacion
    from public.bodega_inventario_ubicacion where cantidad_unidades > 0
      and coalesce(codigo_ubicacion, '') <> 'ZONA-MERMA' and codigo_ubicacion not like 'ME-%'
      and fecha_vencimiento_cl ~ '^(0[1-9]|[12]\d|3[01])-(0[1-9]|1[0-2])-\d{4}$'
      and to_date(fecha_vencimiento_cl, 'DD-MM-YYYY') < current_date order by 1$q$,
 'Mover a merma o bloquear para que no salgan en picking.'),
(311, 'INVENTARIO', 'Ubicaciones bloqueadas que tienen stock', 'MEDIO',
 $q$select count(*) from public.bodega_ubicaciones u where (u.estado ilike 'bloq%' or u.estado_ubicacion ilike 'bloq%')
      and exists (select 1 from public.bodega_inventario_ubicacion i where i.bodega = u.bodega and i.codigo_ubicacion = u.codigo_ubicacion and i.cantidad_unidades > 0)$q$,
 $q$select u.codigo_ubicacion from public.bodega_ubicaciones u where (u.estado ilike 'bloq%' or u.estado_ubicacion ilike 'bloq%')
      and exists (select 1 from public.bodega_inventario_ubicacion i where i.bodega = u.bodega and i.codigo_ubicacion = u.codigo_ubicacion and i.cantidad_unidades > 0) order by 1$q$,
 'Stock que no se puede mover con el RF. Revisar si sigue bloqueada a propósito (ej. MK antiguas).'),

-- ================================ MAESTRA ================================
(401, 'MAESTRA', 'Código de barras usado por más de un SKU', 'ALTO',
 $q$select count(*) from (select regexp_replace(codigo_barras, '^0+', '') from public.maestra_sku
      where coalesce(codigo_barras, '') <> '' group by 1 having count(distinct upper(sku)) > 1) x$q$,
 $q$select regexp_replace(codigo_barras, '^0+', '') || ': ' || string_agg(distinct upper(sku), ', ') from public.maestra_sku
      where coalesce(codigo_barras, '') <> '' group by regexp_replace(codigo_barras, '^0+', '') having count(distinct upper(sku)) > 1$q$,
 'Al escanear se puede tomar el SKU equivocado. Corregir el EAN.'),
(402, 'MAESTRA', 'Presentaciones repetidas (mismo SKU, EAN y unidad)', 'MEDIO',
 $q$select count(*) from (select 1 from public.maestra_sku group by upper(sku), codigo_barras, unidad_medida having count(*) > 1) x$q$,
 $q$select upper(sku) || ' ' || coalesce(codigo_barras, '') || ' ' || coalesce(unidad_medida, '') || ' x' || count(*)
    from public.maestra_sku group by upper(sku), codigo_barras, unidad_medida having count(*) > 1$q$,
 'Dejar una sola fila por presentación.'),
(403, 'MAESTRA', 'SKU con stock sin código de barras', 'MEDIO',
 $q$select count(distinct upper(i.sku)) from public.bodega_inventario_ubicacion i where i.cantidad_unidades > 0
      and not exists (select 1 from public.maestra_sku m where upper(m.sku) = upper(i.sku) and coalesce(m.codigo_barras, '') <> '')
      and exists (select 1 from public.maestra_sku m where upper(m.sku) = upper(i.sku))$q$,
 $q$select distinct upper(i.sku) from public.bodega_inventario_ubicacion i where i.cantidad_unidades > 0
      and not exists (select 1 from public.maestra_sku m where upper(m.sku) = upper(i.sku) and coalesce(m.codigo_barras, '') <> '')
      and exists (select 1 from public.maestra_sku m where upper(m.sku) = upper(i.sku)) order by 1$q$,
 'No se pueden pickear escaneando (picking y packing exigen escaneo). Enrolar el EAN.'),
(404, 'MAESTRA', 'SKU con stock sin múltiplo de caja válido', 'MEDIO',
 $q$select count(distinct upper(i.sku)) from public.bodega_inventario_ubicacion i where i.cantidad_unidades > 0
      and exists (select 1 from public.maestra_sku m where upper(m.sku) = upper(i.sku))
      and coalesce((select max(m.multiplo) from public.maestra_sku m where upper(m.sku) = upper(i.sku)), 0) < 1$q$,
 $q$select distinct upper(i.sku) from public.bodega_inventario_ubicacion i where i.cantidad_unidades > 0
      and exists (select 1 from public.maestra_sku m where upper(m.sku) = upper(i.sku))
      and coalesce((select max(m.multiplo) from public.maestra_sku m where upper(m.sku) = upper(i.sku)), 0) < 1 order by 1$q$,
 'Sin múltiplo las cajas y unidades no cuadran.'),
(405, 'MAESTRA', 'SKU con stock sin peso', 'MEDIO',
 $q$select count(distinct upper(i.sku)) from public.bodega_inventario_ubicacion i where i.cantidad_unidades > 0
      and not exists (select 1 from public.maestra_sku m where upper(m.sku) = upper(i.sku) and (coalesce(m.peso_kg, 0) > 0 or coalesce(m.peso_gr, 0) > 0))$q$,
 $q$select distinct upper(i.sku) from public.bodega_inventario_ubicacion i where i.cantidad_unidades > 0
      and not exists (select 1 from public.maestra_sku m where upper(m.sku) = upper(i.sku) and (coalesce(m.peso_kg, 0) > 0 or coalesce(m.peso_gr, 0) > 0)) order by 1$q$,
 'El packing no puede validar peso ni calcular el despacho.'),
(406, 'MAESTRA', 'SKU con stock en Santiago sin ubicación de picking fija', 'INFO',
 $q$select count(distinct upper(i.sku)) from public.bodega_inventario_ubicacion i where i.cantidad_unidades > 0 and i.bodega = 'Bodega Santiago'
      and not exists (select 1 from public.wms_ubicacion_picking_sku p where p.bodega = i.bodega and upper(p.sku) = upper(i.sku))$q$,
 $q$select distinct upper(i.sku) from public.bodega_inventario_ubicacion i where i.cantidad_unidades > 0 and i.bodega = 'Bodega Santiago'
      and not exists (select 1 from public.wms_ubicacion_picking_sku p where p.bodega = i.bodega and upper(p.sku) = upper(i.sku)) order by 1$q$,
 'Asignar picking fijo si son de alta rotación.'),

-- =============================== OPERACIÓN ===============================
(501, 'OPERACION', 'Pallets en andén hace más de 7 días', 'MEDIO',
 $q$select count(distinct r.lpn) from public.registro_recepcion r
    where coalesce(r.estado_pallet, '') not in ('ALMACENADO', 'CERRADO_SIN_UBICAR') and r.created_at < now() - interval '7 days'
      and not exists (select 1 from public.bodega_inventario_ubicacion i where i.bodega = r.bodega and i.lpn = r.lpn)
      and not exists (select 1 from public.historial_movimientos h where h.bodega = r.bodega and h.lpn = r.lpn
                      and h.tipo_movimiento in ('ALMACENAMIENTO', 'ENVIO_MERMA'))$q$,
 $q$select distinct r.lpn || ' (' || to_char(r.created_at, 'DD-MM-YYYY') || ')' from public.registro_recepcion r
    where coalesce(r.estado_pallet, '') not in ('ALMACENADO', 'CERRADO_SIN_UBICAR') and r.created_at < now() - interval '7 days'
      and not exists (select 1 from public.bodega_inventario_ubicacion i where i.bodega = r.bodega and i.lpn = r.lpn)
      and not exists (select 1 from public.historial_movimientos h where h.bodega = r.bodega and h.lpn = r.lpn
                      and h.tipo_movimiento in ('ALMACENAMIENTO', 'ENVIO_MERMA')) order by 1$q$,
 'O se almacenan o se dan de baja (botón rojo en Almacenamiento, solo administradores).'),
(502, 'OPERACION', 'Órdenes por estado', 'INFO',
 $q$select count(*) from public.netsuite_ordenes_venta$q$,
 $q$select coalesce(estado_ns, '(sin estado)') || ': ' || count(*) from public.netsuite_ordenes_venta group by estado_ns order by count(*) desc$q$,
 'Referencia: estados raros o muchas órdenes antiguas abiertas indican flujos sin cerrar.'),
(503, 'OPERACION', 'Órdenes en picking hace más de 3 días', 'MEDIO',
 $q$select count(*) from public.netsuite_ordenes_venta where upper(coalesce(estado_ns, '')) like '%PICKING%'
      and coalesce(updated_at, created_at) < now() - interval '3 days'$q$,
 $q$select numero_ov || ' · ' || estado_ns || ' · ' || coalesce(operador_asignado, 'sin operador') from public.netsuite_ordenes_venta
    where upper(coalesce(estado_ns, '')) like '%PICKING%' and coalesce(updated_at, created_at) < now() - interval '3 days'
    order by coalesce(updated_at, created_at)$q$,
 'Órdenes olvidadas: terminarlas o anularlas.'),
(504, 'OPERACION', 'Órdenes asignadas a un operador que no existe o está inactivo', 'MEDIO',
 $q$select count(*) from public.netsuite_ordenes_venta o
    where coalesce(nullif(upper(btrim(o.operador_asignado)), ''), 'SIN ASIGNAR') <> 'SIN ASIGNAR'
      and upper(coalesce(o.estado_ns, '')) in ('PENDIENTE_PICKING', 'PENDIENTE', 'PICKING_EN_PROCESO')
      and not exists (select 1 from public.wms_usuarios u where coalesce(u.activo, true)
                      and upper(btrim(o.operador_asignado)) in (upper(u.usuario), upper(coalesce(u.nombre_completo, ''))))$q$,
 $q$select o.numero_ov || ' → ' || o.operador_asignado from public.netsuite_ordenes_venta o
    where coalesce(nullif(upper(btrim(o.operador_asignado)), ''), 'SIN ASIGNAR') <> 'SIN ASIGNAR'
      and upper(coalesce(o.estado_ns, '')) in ('PENDIENTE_PICKING', 'PENDIENTE', 'PICKING_EN_PROCESO')
      and not exists (select 1 from public.wms_usuarios u where coalesce(u.activo, true)
                      and upper(btrim(o.operador_asignado)) in (upper(u.usuario), upper(coalesce(u.nombre_completo, '')))) order by 1$q$,
 'Nadie las va a ver en el celular. Reasignar desde el Monitor de usuarios.'),
(505, 'OPERACION', 'Líneas con más unidades pickeadas que pedidas', 'ALTO',
 $q$select count(*) from public.netsuite_detalle_ov where coalesce(cantidad_pickeada, 0) > coalesce(cantidad_pedida, 0) and coalesce(cantidad_pedida, 0) > 0$q$,
 $q$select o.numero_ov || ' ' || d.sku || ': ' || d.cantidad_pickeada || ' de ' || d.cantidad_pedida from public.netsuite_detalle_ov d
      join public.netsuite_ordenes_venta o on o.id = d.orden_id
    where coalesce(d.cantidad_pickeada, 0) > coalesce(d.cantidad_pedida, 0) and coalesce(d.cantidad_pedida, 0) > 0 order by 1$q$,
 'Se despachó de más o el inventario se descontó doble.'),

-- =============================== USUARIOS ===============================
(601, 'USUARIOS', 'Usuarios repetidos (mismo nombre con distinta mayúscula/espacios)', 'MEDIO',
 $q$select count(*) from (select upper(btrim(usuario)) from public.wms_usuarios group by 1 having count(*) > 1) x$q$,
 $q$select upper(btrim(usuario)) || ' x' || count(*) from public.wms_usuarios group by 1 having count(*) > 1$q$,
 'El historial y las asignaciones se reparten entre dos cuentas. Dejar una.'),
(602, 'USUARIOS', 'Usuarios activos sin rol o sin bodega', 'MEDIO',
 $q$select count(*) from public.wms_usuarios where coalesce(activo, true) and (coalesce(btrim(rol), '') = '' or coalesce(btrim(bodega), '') = '')$q$,
 $q$select usuario || ' (rol=' || coalesce(rol, '-') || ', bodega=' || coalesce(bodega, '-') || ')' from public.wms_usuarios
    where coalesce(activo, true) and (coalesce(btrim(rol), '') = '' or coalesce(btrim(bodega), '') = '') order by 1$q$,
 'Completar para que vean los módulos y la bodega correcta.'),

-- ================================ KARDEX ================================
(701, 'KARDEX', 'Movimientos de los últimos 30 días sin usuario', 'MEDIO',
 $q$select count(*) from public.historial_movimientos where fecha > now() - interval '30 days' and coalesce(btrim(usuario), '') in ('', 'SISTEMA', 'NULL')$q$,
 $q$select tipo_movimiento || ': ' || count(*) from public.historial_movimientos
    where fecha > now() - interval '30 days' and coalesce(btrim(usuario), '') in ('', 'SISTEMA', 'NULL') group by tipo_movimiento order by count(*) desc$q$,
 'Sin trazabilidad de quién movió el stock.'),
(702, 'KARDEX', 'Movimientos con fecha en el futuro', 'MEDIO',
 $q$select count(*) from public.historial_movimientos where fecha > now() + interval '1 hour'$q$,
 $q$select tipo_movimiento || ' ' || to_char(fecha, 'DD-MM-YYYY HH24:MI') from public.historial_movimientos where fecha > now() + interval '1 hour' order by fecha desc$q$,
 'Indica horas mal enviadas (zona horaria).'),
(703, 'KARDEX', 'Tipos de movimiento de los últimos 30 días', 'INFO',
 $q$select count(distinct tipo_movimiento) from public.historial_movimientos where fecha > now() - interval '30 days'$q$,
 $q$select tipo_movimiento || ': ' || count(*) from public.historial_movimientos where fecha > now() - interval '30 days'
    group by tipo_movimiento order by count(*) desc$q$,
 'Referencia de qué se usa y cuánto.')
),
res as (
  select c.*, pg_temp.dx_contar(c.sql_n) n,
         case when c.sev = 'INFO' or coalesce(pg_temp.dx_contar(c.sql_n), 0) > 0 then pg_temp.dx_ejemplos(c.sql_ej) end ej
  from chequeos c
)
select case when n is null then 'NO SE PUDO'
            when sev = 'INFO' then 'INFO'
            when n > 0 then 'REVISAR'
            else 'OK' end as estado,
       sev as gravedad, area, revision, n as cantidad, ej as ejemplos, que_hacer
from res
order by case when n is null then 5 when n = 0 and sev <> 'INFO' then 6
              else case sev when 'CRITICO' then 1 when 'ALTO' then 2 when 'MEDIO' then 3 else 4 end end,
         orden;
