-- =====================================================================
-- LUDIPEK WMS · 01 LIMPIEZA Y NORMALIZACIÓN DE DATOS  (FASE A)
-- · Se ejecuta en UNA transacción: si algo falla no queda nada a medias.
-- · Es idempotente: se puede volver a ejecutar sin efectos adicionales.
-- · NO borra stock. Lo único que elimina son líneas repetidas de traslados
--   (OT-) que aún no tienen nada pickeado (el importador las triplicaba).
-- Antes de ejecutar: respaldo en Supabase (Database > Backups) y correr 00.
-- =====================================================================
begin;

-- ---------------------------------------------------------------------
-- Funciones de normalización (las reutilizan los triggers y las funciones
-- de operación de los scripts 02 y 04).
-- ---------------------------------------------------------------------
create or replace function public.wms_normalizar_sku(p text)
returns text language sql immutable as $$
  select upper(regexp_replace(coalesce(p, ''), '[[:space:]]', '', 'g'));
$$;

create or replace function public.wms_normalizar_lote(p text)
returns text language plpgsql immutable as $$
declare
  v_base text;
  v_qa   text := '';
begin
  v_base := upper(btrim(coalesce(p, '')));
  if position('|QA:' in v_base) > 0 then
    v_qa   := '|QA:' || btrim(split_part(v_base, '|QA:', 2));
    v_base := btrim(split_part(v_base, '|QA:', 1));
  end if;
  if regexp_replace(v_base, '\s', '', 'g') in ('', 'SL', 'S/L', 'SINLOTE', 'NONE', 'NULL', '-') then
    v_base := 'S/L';
  end if;
  if v_qa in ('|QA:', '|QA:APROBADO', '|QA:LIBERADO') then
    v_qa := '';
  end if;
  return v_base || v_qa;
end $$;

-- Interpreta vencimientos 'DD-MM-YYYY', 'DD/MM/YYYY', 'DD.MM.YYYY' o 'YYYY-MM-DD'.
-- Día 00 (estándar GS1) = último día del mes.
-- Devuelve NULL si viene vacío / S/F o si no es una fecha válida.
create or replace function public.wms_fecha_desde_texto(p text)
returns date language plpgsql immutable as $$
declare
  t text := btrim(coalesce(p, ''));
  d date;
  v_dia int; v_mes int; v_anio int;
begin
  if t = '' or upper(replace(t, ' ', '')) in ('S/F', 'SF', 'SINFECHA', 'NULL', 'NONE', '-') then
    return null;
  end if;
  begin
    if t ~ '^\d{4}-\d{2}-\d{2}' then
      d := to_date(left(t, 10), 'YYYY-MM-DD');
    elsif t ~ '^\d{1,2}[-/.]\d{1,2}[-/.](\d{4}|\d{2})$' then
      t := regexp_replace(t, '[/.]', '-', 'g');
      v_dia  := split_part(t, '-', 1)::int;
      v_mes  := split_part(t, '-', 2)::int;
      v_anio := split_part(t, '-', 3)::int;
      if v_anio < 100 then v_anio := 2000 + v_anio; end if;   -- '28' o '0028' -> 2028
      if v_mes < 1 or v_mes > 12 then return null; end if;
      if v_dia = 0 then
        -- Estándar GS1: día 00 = último día del mes
        d := (make_date(v_anio, v_mes, 1) + interval '1 month - 1 day')::date;
      else
        d := make_date(v_anio, v_mes, v_dia);                -- falla si el día no existe (31-02)
      end if;
    else
      return null;
    end if;
  exception when others then
    return null;
  end;
  if d < date '2000-01-01' or d > date '2100-12-31' then
    return null;
  end if;
  return d;
end $$;

create or replace function public.wms_fecha_cl(p date)
returns text language sql immutable as $$
  select case when p is null then null else to_char(p, 'DD-MM-YYYY') end;
$$;

-- ---------------------------------------------------------------------
-- 1. SKU sin espacios ni saltos de línea y en mayúsculas
-- ---------------------------------------------------------------------
update public.bodega_inventario_ubicacion set sku = public.wms_normalizar_sku(sku)
 where sku <> public.wms_normalizar_sku(sku);
update public.registro_recepcion set sku = public.wms_normalizar_sku(sku)
 where sku <> public.wms_normalizar_sku(sku);
update public.netsuite_detalle_ov set sku = public.wms_normalizar_sku(sku)
 where sku <> public.wms_normalizar_sku(sku);
update public.asn_detalle set sku = public.wms_normalizar_sku(sku)
 where sku <> public.wms_normalizar_sku(sku);
-- maestra_sku tiene llave (sku, codigo_barras, unidad_medida): solo se corrige si no choca
update public.maestra_sku m set sku = public.wms_normalizar_sku(m.sku)
 where m.sku <> public.wms_normalizar_sku(m.sku)
   and not exists (select 1 from public.maestra_sku x
                   where x.sku = public.wms_normalizar_sku(m.sku)
                     and x.codigo_barras = m.codigo_barras and x.unidad_medida = m.unidad_medida);

-- ---------------------------------------------------------------------
-- 2. Lotes: mayúsculas, sin espacios sobrantes y 'S/L' uniforme
-- ---------------------------------------------------------------------
update public.bodega_inventario_ubicacion set lote = public.wms_normalizar_lote(lote)
 where lote is distinct from public.wms_normalizar_lote(lote);
update public.registro_recepcion set lote = public.wms_normalizar_lote(lote)
 where lote is distinct from public.wms_normalizar_lote(lote);

-- ---------------------------------------------------------------------
-- 3. Vencimientos del inventario en un solo formato: DD-MM-YYYY
--    (había DD/MM/YYYY y DD-MM-YYYY mezclados)
-- ---------------------------------------------------------------------
update public.bodega_inventario_ubicacion
   set fecha_vencimiento_cl = public.wms_fecha_cl(public.wms_fecha_desde_texto(fecha_vencimiento_cl))
 where public.wms_fecha_desde_texto(fecha_vencimiento_cl) is not null
   and fecha_vencimiento_cl is distinct from public.wms_fecha_cl(public.wms_fecha_desde_texto(fecha_vencimiento_cl));
update public.bodega_inventario_ubicacion set fecha_vencimiento_cl = null
 where fecha_vencimiento_cl is not null and upper(btrim(fecha_vencimiento_cl)) in ('', 'S/F');

-- ---------------------------------------------------------------------
-- 4. Bodega obligatoria (los registros antiguos sin bodega son de Santiago)
-- ---------------------------------------------------------------------
update public.bodega_inventario_ubicacion set bodega = 'Bodega Santiago' where coalesce(btrim(bodega), '') = '';
update public.registro_recepcion          set bodega = 'Bodega Santiago' where coalesce(btrim(bodega), '') = '';
update public.bodega_ubicaciones          set bodega = 'Bodega Santiago' where coalesce(btrim(bodega), '') = '';
update public.netsuite_ordenes_venta      set bodega = 'Bodega Santiago' where coalesce(btrim(bodega), '') = '';
update public.bodega_inventario_ubicacion set bodega = 'Bodega Concepcion' where bodega ilike '%concepci%n%' and bodega <> 'Bodega Concepcion';
update public.registro_recepcion          set bodega = 'Bodega Concepcion' where bodega ilike '%concepci%n%' and bodega <> 'Bodega Concepcion';

-- ---------------------------------------------------------------------
-- 5. Códigos de ubicación consistentes (X-NN-NN) y zonas especiales
-- ---------------------------------------------------------------------
update public.bodega_inventario_ubicacion set codigo_ubicacion = upper(btrim(codigo_ubicacion))
 where codigo_ubicacion <> upper(btrim(codigo_ubicacion));
update public.bodega_inventario_ubicacion   -- 'G05-01' -> 'G-05-01'
   set codigo_ubicacion = regexp_replace(codigo_ubicacion, '^([A-Z])(\d{2})-(\d{2})$', '\1-\2-\3')
 where codigo_ubicacion ~ '^[A-Z]\d{2}-\d{2}$';
update public.bodega_inventario_ubicacion set codigo_ubicacion = 'ZONA-PICKING'
 where codigo_ubicacion in ('PICKING', 'ZONAPICKING', 'ZONA PICKING');
update public.bodega_inventario_ubicacion set zona = split_part(codigo_ubicacion, '-', 1)
 where zona is distinct from split_part(codigo_ubicacion, '-', 1) and codigo_ubicacion not like 'ZONA-%';

insert into public.bodega_ubicaciones (codigo_ubicacion, zona, bodega, tipo_ubicacion, estado)
select z.cod, z.zona, b.bodega, 'ZONA_ESPECIAL', 'Habilitada'
from (values ('ZONA-PICKING', 'PICKING'), ('ZONA-MERMA', 'MERMA')) z(cod, zona)
cross join (values ('Bodega Santiago'), ('Bodega Concepcion')) b(bodega)
on conflict (bodega, codigo_ubicacion) do nothing;

-- Ubicaciones usadas en inventario que no existen en la maestra: se crean
-- marcadas 'REVISAR' para que queden visibles (no se pierde el stock).
insert into public.bodega_ubicaciones (codigo_ubicacion, zona, bodega, estado, bloqueada_motivo)
select distinct i.codigo_ubicacion, split_part(i.codigo_ubicacion, '-', 1), i.bodega, 'REVISAR',
       'Creada por migración 01: existía stock en una ubicación no registrada'
from public.bodega_inventario_ubicacion i
where coalesce(i.codigo_ubicacion, '') <> ''
  and not exists (select 1 from public.bodega_ubicaciones u
                  where u.bodega = i.bodega and u.codigo_ubicacion = i.codigo_ubicacion)
on conflict (bodega, codigo_ubicacion) do nothing;

-- ---------------------------------------------------------------------
-- 6. Cajas vacías -> se recalculan con el múltiplo de caja de la maestra
-- ---------------------------------------------------------------------
update public.bodega_inventario_ubicacion i
   set cajas = coalesce(i.cantidad_unidades / nullif((select max(m.multiplo) from public.maestra_sku m where m.sku = i.sku), 0), 0)
 where i.cajas is null;

-- ---------------------------------------------------------------------
-- 7. Traslados (OT-) con líneas triplicadas por el importador de NetSuite.
--    Solo se tocan OT SIN NADA pickeado. Se conserva la primera línea.
-- ---------------------------------------------------------------------
delete from public.netsuite_detalle_ov d
using public.netsuite_ordenes_venta o
where o.id = d.orden_id
  and o.numero_ov like 'OT-%'
  and not exists (select 1 from public.netsuite_detalle_ov p
                  where p.orden_id = d.orden_id and coalesce(p.cantidad_pickeada, 0) > 0)
  and exists (select 1 from public.netsuite_detalle_ov k
              where k.orden_id = d.orden_id and k.sku = d.sku
                and k.cantidad_pedida = d.cantidad_pedida and k.linea_ns < d.linea_ns);

-- ---------------------------------------------------------------------
-- 8. lotes_pickeados corrupto: "(2 UN) (2 UN) (2 UN)" -> "(2 UN)"
-- ---------------------------------------------------------------------
update public.netsuite_detalle_ov
   set lotes_pickeados = regexp_replace(lotes_pickeados, '(\(\d+ UN\))(\s*\(\d+ UN\))+', '\1', 'g')
 where lotes_pickeados ~ '\(\d+ UN\)\s*\(\d+ UN\)';

commit;

-- ---------------------------------------------------------------------
-- OPCIONAL (decidir después del conteo físico): filas de inventario
-- duplicadas. El diagnóstico (consulta 3) las lista. Si el conteo confirma
-- que el stock real es el de UNA sola fila, borrar la(s) otra(s) por id:
--   delete from public.bodega_inventario_ubicacion where id in (2264, 2367);
-- ---------------------------------------------------------------------
