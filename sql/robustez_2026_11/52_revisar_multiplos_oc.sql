-- =====================================================================
-- LUDIPEK WMS · 52 REVISAR Y CORREGIR EL MÚLTIPLO (UN/CAJA) DE LAS OC CARGADAS
--
-- Problema: al bajar una OC de NetSuite, el PC tomaba el múltiplo de la ÚLTIMA fila de la maestra
-- del SKU (la maestra tiene varias filas por SKU: UNIDAD, DISPLAY, CAJA). Así quedaban OC con
-- "1056 Cj x 1" en vez de "22 Cj x 48", y la conciliación mostraba cajas y estatus raros.
-- El PC ya está corregido (usa la fila CAJA). Este script:
--   PASO 1 (solo lectura): muestra, por OC abierta, el múltiplo de la OC, el de la maestra (CAJA) y el
--          que usó el celular al recibir, para ver si alguna recepción quedó con unidades mal calculadas.
--   PASO 2: corrige el múltiplo y las cajas esperadas de las OC abiertas (no toca lo recibido).
-- Ejecute primero el PASO 1 y revise; el PASO 2 se puede ejecutar más de una vez.
-- =====================================================================

-- ---------------------------------------------------------------------
-- PASO 1 · REVISIÓN (no cambia nada). Cambie '2398' por la OC a revisar, o deje null para todas las abiertas.
-- ---------------------------------------------------------------------
with params as (select null::text as oc),          -- ej: select '2398'::text as oc
maestra as (
  select upper(btrim(sku)) sku,
         string_agg(coalesce(unidad_medida, '?') || ' x' || multiplo || ' (' || coalesce(codigo_barras, '') || ')', ' | '
                    order by multiplo) presentaciones,
         max(multiplo) filter (where upper(replace(coalesce(unidad_medida, ''), ' ', '_')) in ('CAJA', 'CAJA_MASTER', 'MASTER', 'CJ')) mult_caja,
         max(multiplo) mult_max
    from maestra_sku group by 1
),
recibido as (
  select asn_id, upper(btrim(sku)) sku,
         string_agg(distinct multiplo_aplicado::text, ', ') multiplos_usados,
         sum(cajas) cajas, sum(unidades_totales) unidades, count(distinct lpn) lpns
    from registro_recepcion where asn_id is not null group by 1, 2
)
select a.numero_oc, d.sku, m.presentaciones,
       d.multiplo_empaque as mult_en_oc,
       coalesce(m.mult_caja, m.mult_max) as mult_correcto,
       d.unidades_esperadas as un_oc, d.cajas_esperadas as cj_oc_actual,
       ceil(d.unidades_esperadas::numeric / greatest(1, coalesce(m.mult_caja, m.mult_max, 1)))::int as cj_oc_correcto,
       r.multiplos_usados as mult_usado_al_recibir, r.cajas as cj_recibidas, r.unidades as un_recibidas, r.lpns,
       case
         when r.unidades is null then 'SIN RECEPCIÓN'
         when r.unidades = d.unidades_esperadas then 'OK'
         when r.cajas * coalesce(m.mult_caja, m.mult_max) = d.unidades_esperadas then 'REVISAR: con x' || coalesce(m.mult_caja, m.mult_max) || ' cuadra con la OC'
         when r.unidades > d.unidades_esperadas then 'SOBRANTE: confirme cuántas unidades trae cada caja'
         else 'PARCIAL'
       end as revision
  from asn_cabecera a
  join asn_detalle d on d.asn_id = a.id
  left join maestra m on m.sku = upper(btrim(d.sku))
  left join recibido r on r.asn_id = a.id and r.sku = upper(btrim(d.sku))
  cross join params p
 where (p.oc is null and a.estado not in ('COMPLETADO', 'CERRADA', 'ANULADA'))
    or public.wms_numero_oc(a.numero_oc) = public.wms_numero_oc(p.oc)
 order by a.numero_oc, d.sku;

-- ---------------------------------------------------------------------
-- PASO 2 · CORREGIR las OC abiertas (múltiplo = fila CAJA de la maestra; cajas = unidades / múltiplo)
-- ---------------------------------------------------------------------
begin;
with maestra as (
  select upper(btrim(sku)) sku,
         coalesce(max(multiplo) filter (where upper(replace(coalesce(unidad_medida, ''), ' ', '_')) in ('CAJA', 'CAJA_MASTER', 'MASTER', 'CJ')),
                  max(multiplo)) mult
    from maestra_sku where coalesce(multiplo, 0) > 0 group by 1
),
cambios as (
  update asn_detalle d
     set multiplo_empaque = m.mult,
         cajas_esperadas = greatest(1, ceil(coalesce(d.unidades_esperadas, 0)::numeric / m.mult))::int
    from maestra m, asn_cabecera a
   where m.sku = upper(btrim(d.sku)) and a.id = d.asn_id
     and a.estado not in ('COMPLETADO', 'CERRADA', 'ANULADA')
     and coalesce(d.unidades_esperadas, 0) > 0
     and coalesce(d.multiplo_empaque, 0) <> m.mult
  returning d.asn_id, d.sku
)
select count(*) as lineas_corregidas, count(distinct asn_id) as oc_corregidas from cambios;
commit;
