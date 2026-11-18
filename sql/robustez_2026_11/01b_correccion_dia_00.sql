-- =====================================================================
-- LUDIPEK WMS · 01b CORRECCIÓN VENCIMIENTOS GS1 CON DÍA "00"
-- En etiquetas GS1 el día 00 significa "último día del mes". El script 01
-- los convirtió al día 01 (ej. 00-04-2028 -> 01-04-2028).
-- 1) La función de fechas pasa a interpretar 00 como fin de mes.
-- 2) Se corrigen SOLO las 21 filas que tenían día 00 en la exportación del
--    18-11-2026 y SOLO si todavía tienen día 01 (no pisa correcciones manuales).
-- Idempotente: se puede ejecutar más de una vez.
-- =====================================================================
begin;

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

update public.bodega_inventario_ubicacion
   set fecha_vencimiento_cl = public.wms_fecha_cl(
         (date_trunc('month', public.wms_fecha_desde_texto(fecha_vencimiento_cl)) + interval '1 month - 1 day')::date)
 where id in (2308, 2309, 2310, 2311, 2313, 2314, 2316, 2317, 2318, 2319, 2320,
              2322, 2323, 2324, 2325, 2326, 2327, 2328, 2329, 2358, 2359)
   and fecha_vencimiento_cl like '01-%';

commit;

-- Verificación: deben aparecer con el último día de su mes (30-04-2028, 31-05-2028, etc.)
select id, lpn, sku, lote, fecha_vencimiento_cl, fecha_vencimiento
from public.bodega_inventario_ubicacion
where id in (2308, 2309, 2310, 2311, 2313, 2314, 2316, 2317, 2318, 2319, 2320,
             2322, 2323, 2324, 2325, 2326, 2327, 2328, 2329, 2358, 2359)
order by lpn, id;
