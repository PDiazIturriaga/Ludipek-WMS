-- =====================================================================
-- LUDIPEK WMS · 53 OC TAL CUAL NETSUITE
-- Guarda en cada línea de la OC la cantidad y la unidad con que está en NetSuite (ej. 2 "Caja x48"),
-- además de las unidades base que usa el WMS para recibir. El PC funciona sin este script, pero sin él
-- la conciliación muestra la OC convertida a cajas en vez de la cantidad de NetSuite.
-- Se puede ejecutar más de una vez.
-- =====================================================================
alter table public.asn_detalle add column if not exists cantidad_oc_ns numeric;
alter table public.asn_detalle add column if not exists unidad_oc_ns text;
notify pgrst, 'reload schema';
