-- =====================================================================================
-- 59a · Ficha logística por SKU (display y pallet): medidas y pesos reales (PARTE 1 de 2)
--   Con esto el peso bruto y los m³ de cada pallet del despacho se calculan por SKU:
--   · alto del pallet = madera + camas (displays / displays por cama) x alto de cama
--   · alto de cama = (alto pallet completo - madera) / camas del pallet completo  (sale del pallet medido)
--   · peso bruto = unidades x peso del display / unidades del display + tara del pallet
--   Se puede ejecutar más de una vez (actualiza los SKU). Luego ejecute 59b.
--   Copie TODO el archivo (Ctrl+A). Debe terminar en "-- FIN 59a".
-- =====================================================================================
create table if not exists public.wms_sku_logistica (
  sku               text primary key,
  sku_proveedor     text,
  nombre            text,
  ean_display       text,
  display_alto_cm   numeric, display_ancho_cm numeric, display_largo_cm numeric,
  display_peso_gr   numeric,
  display_unidades  integer,          -- unidades por display
  pallet_alto_cm    numeric,          -- alto del pallet completo, CON la madera
  pallet_ancho_cm   numeric, pallet_largo_cm numeric,
  pallet_peso_kg    numeric,          -- peso del pallet completo, CON la madera
  pallet_unidades   integer,          -- unidades por pallet completo
  displays_por_cama integer,
  madera_alto_cm    numeric not null default 14.4,   -- pallet europeo
  actualizado_por   text,
  actualizado_en    timestamptz not null default now()
);
alter table public.wms_sku_logistica enable row level security;
revoke all on public.wms_sku_logistica from anon;
grant select on public.wms_sku_logistica to authenticated;
grant select, insert, update, delete on public.wms_sku_logistica to service_role;

-- Datos entregados el 26-11-2026 (Feral)
insert into public.wms_sku_logistica (sku, sku_proveedor, nombre, ean_display, display_alto_cm, display_ancho_cm,
       display_largo_cm, display_peso_gr, display_unidades, pallet_alto_cm, pallet_ancho_cm, pallet_largo_cm,
       pallet_peso_kg, pallet_unidades, displays_por_cama)
values
  ('FEWTC136784', 'CAFC136784', 'FERAL-ADULT HUNTERS PREY PATELAMB+WILD BOAR 200GR', '10726529136781', 6, 15, 23, 1548, 6, 92, 79, 120, 529, 1950, 25),
  ('FEWTC136821', 'CAFC136821', 'FERAL-ADULT RIVER CHASE PATE DUCK+SALMON 200GR', '10726529136828', 6, 15, 23, 1505, 6, 92, 79, 120, 529, 1950, 25),
  ('FEWTK136708', 'CKFC136708', 'FERAL-KITTEN RAWBORN HUNT PATE CHICKEN+SALMON 200GR', '10726529136705', 6, 15, 23, 1510, 6, 92, 79, 120, 529, 1950, 25),
  ('FEWTC136746', 'CMFC136746', 'FERAL-ADULT WILDERNESS BOUNTY MONO PATE PORK 200GR', '10726529136743', 6, 15, 23, 1513, 6, 92, 79, 120, 529, 1950, 25),
  ('FEWTC136869', 'CSFC136869', 'FERAL-SENIOR ELDERS LEGACY TRAY PATE TURKEY+RABBIT 200GR', '10726529136866', 11, 15, 23, 1524, 6, 92, 79, 120, 529, 1950, 25),
  ('FEWTK136722', 'CKFC136722', 'FERAL-KITTEN RAWBORN HUNT PATE CHICKEN+SALMON 400GR', '10726529136729', 11, 15, 23, 2751, 6, 91.5, 79, 120, 504, 1050, 25),
  ('FEWTD136586', 'DAFC136586', 'FERAL WET ADULT DOG BEEF/SALMON 400G', '10726529136583', 11, 15, 23, 2751, 6, 91.5, 79, 120, 504, 1050, 25),
  ('FEWTD136548', 'DMFC136548', 'FERAL- ADULTO HUNTERS CALL MONOPROTEIN PATE BEEF 400GR', '10726529136545', 11, 15, 23, 2751, 6, 91.5, 79, 120, 504, 1050, 25),
  ('FEWTP136463', 'DPFC136463', 'FERAL-PUPPY WILDBORN INSTINCT PATE BEEF+SALMON 400GR', '10726529136460', 11, 15, 23, 2751, 6, 91.5, 79, 120, 504, 1050, 25),
  ('FESPC898217', 'CSFP898217', 'FERAL SP SOUP CAT SALMON POUCH 40GR', '10726529898214', 12.5, 18, 9, 654, 12, 77, 80, 120, 185.5, 3120, 52),
  ('FESPC898231', 'CSFP898231', 'FERAL SP SOUP CAT BEEF POUCH 40GR', '10726529898238', 12.5, 18, 9, 654, 12, 77, 80, 120, 185.5, 3120, 52),
  ('FESPC898255', 'CSFP898255', 'FERAL SP SOUP CAT CHICKEN POUCH 40GR', '10726529898252', 12.5, 18, 9, 654, 12, 77, 80, 120, 185.5, 3120, 52)
on conflict (sku) do update set
  sku_proveedor = excluded.sku_proveedor, nombre = excluded.nombre, ean_display = excluded.ean_display,
  display_alto_cm = excluded.display_alto_cm, display_ancho_cm = excluded.display_ancho_cm,
  display_largo_cm = excluded.display_largo_cm, display_peso_gr = excluded.display_peso_gr,
  display_unidades = excluded.display_unidades, pallet_alto_cm = excluded.pallet_alto_cm,
  pallet_ancho_cm = excluded.pallet_ancho_cm, pallet_largo_cm = excluded.pallet_largo_cm,
  pallet_peso_kg = excluded.pallet_peso_kg, pallet_unidades = excluded.pallet_unidades,
  displays_por_cama = excluded.displays_por_cama, actualizado_en = now();

-- Cálculos por SKU (alto de cama y peso por unidad), con controles de coherencia
create or replace view public.wms_sku_logistica_calc with (security_invoker = true) as
select g.*,
       (g.pallet_unidades::numeric / nullif(g.display_unidades, 0) / nullif(g.displays_por_cama, 0)) camas_pallet,
       round((g.pallet_alto_cm - g.madera_alto_cm)
             / nullif(ceil(g.pallet_unidades::numeric / nullif(g.display_unidades, 0) / nullif(g.displays_por_cama, 0)), 0), 2) cama_alto_cm,
       round(coalesce(g.display_peso_gr / 1000.0 / nullif(g.display_unidades, 0),
                      (g.pallet_peso_kg - 25) / nullif(g.pallet_unidades, 0)), 5) kg_bruto_unidad,
       case when abs(g.display_alto_cm - (g.pallet_alto_cm - g.madera_alto_cm)
                     / nullif(ceil(g.pallet_unidades::numeric / nullif(g.display_unidades, 0) / nullif(g.displays_por_cama, 0)), 0)) > 1
            then 'Alto del display no cuadra con el pallet (se usa el del pallet)' end observacion
  from public.wms_sku_logistica g;
grant select on public.wms_sku_logistica_calc to authenticated, service_role;

notify pgrst, 'reload schema';
-- Revisión: select sku, camas_pallet, cama_alto_cm, kg_bruto_unidad, observacion from wms_sku_logistica_calc order by sku;
-- FIN 59a
