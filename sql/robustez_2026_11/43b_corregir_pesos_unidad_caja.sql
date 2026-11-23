-- =====================================================================
-- LUDIPEK WMS · 43b CORREGIR PESOS UNIDAD / CAJA   (revisar antes 43_revisar_pesos_unidad_caja.sql)
-- Regla: cuando la fila UNIDAD (múltiplo 1) tiene el mismo peso que la fila de la caja, se asume que
-- ese peso es el de la CAJA y la unidad pasa a peso_caja / múltiplo. La caja no se toca.
-- (Si en la revisión ve que es al revés —la caja quedó con el peso de la unidad— NO ejecute este
--  script para ese SKU: corríjalo en PC › Maestra.)
-- Por defecto corrige solo Giwi; para todos los SKU, borre la línea marcada "SOLO GIWI".
-- Guarda los pesos anteriores en wms_maestra_pesos_respaldo (al final está cómo volver atrás).
-- Ejecútelo una sola vez: después ya no detecta esos SKU (la unidad queda distinta de la caja).
-- =====================================================================
begin;

create table if not exists public.wms_maestra_pesos_respaldo (
  sku text not null, codigo_barras text not null, unidad_medida text not null,
  peso_gr numeric, peso_kg numeric, guardado_en timestamptz not null default now(),
  primary key (sku, codigo_barras, unidad_medida, guardado_en)
);
alter table public.wms_maestra_pesos_respaldo enable row level security;
revoke all on public.wms_maestra_pesos_respaldo from anon, authenticated;

-- Un solo comando (el editor SQL de Supabase no conserva tablas temporales entre comandos)
with filas as (
  select regexp_replace(upper(btrim(sku)), '-FA$', '') sku_base, sku, codigo_barras, unidad_medida, multiplo,
         peso_gr, peso_kg, marca, descripcion,
         coalesce(nullif(peso_gr, 0) / 1000.0, nullif(peso_kg, 0)) peso_fila_kg
    from public.maestra_sku
), caja as (   -- la fila de mayor múltiplo de cada SKU
  select distinct on (sku_base) * from filas where multiplo > 1 order by sku_base, multiplo desc
), corregir as (
  select u.sku, u.codigo_barras, u.unidad_medida, u.peso_gr, u.peso_kg,
         round(c.peso_fila_kg / c.multiplo, 4) as kg_nuevo
    from filas u
    join caja c on c.sku_base = u.sku_base
   where u.multiplo = 1
     and u.peso_fila_kg is not null and c.peso_fila_kg is not null
     and abs(u.peso_fila_kg - c.peso_fila_kg) < 0.0005
     and upper(coalesce(u.marca, '') || ' ' || coalesce(u.descripcion, '')) ~ '(GIWI|GIGWI)'   -- SOLO GIWI
), respaldo as (
  insert into public.wms_maestra_pesos_respaldo (sku, codigo_barras, unidad_medida, peso_gr, peso_kg)
  select sku, codigo_barras, unidad_medida, peso_gr, peso_kg from corregir
  returning sku
), cambio as (
  update public.maestra_sku m
     set peso_kg = x.kg_nuevo,
         peso_gr = case when m.peso_gr is not null then round(x.kg_nuevo * 1000, 1) end
    from corregir x
   where m.sku = x.sku and m.codigo_barras = x.codigo_barras and m.unidad_medida = x.unidad_medida
  returning m.sku
)
select x.sku, x.unidad_medida, x.peso_gr as gr_antes, x.peso_kg as kg_antes, x.kg_nuevo,
       (select count(*) from respaldo) as respaldadas, (select count(*) from cambio) as corregidas
  from corregir x order by x.sku;

commit;

-- VOLVER ATRÁS (a mano): restaura los pesos guardados la última vez
-- update public.maestra_sku m set peso_gr = r.peso_gr, peso_kg = r.peso_kg
--   from (select distinct on (sku, codigo_barras, unidad_medida) * from public.wms_maestra_pesos_respaldo
--          order by sku, codigo_barras, unidad_medida, guardado_en desc) r
--  where m.sku = r.sku and m.codigo_barras = r.codigo_barras and m.unidad_medida = r.unidad_medida;
