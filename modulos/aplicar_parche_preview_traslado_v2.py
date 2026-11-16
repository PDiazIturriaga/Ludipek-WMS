from pathlib import Path
import re
import sys

entrada = Path(sys.argv[1] if len(sys.argv) > 1 else 'm3_picking.py')
salida = Path(sys.argv[2] if len(sys.argv) > 2 else 'm3_picking_preview_traslado.py')

if not entrada.exists():
    raise SystemExit(f'ERROR: No existe {entrada.resolve()}')

s = entrada.read_text(encoding='utf-8-sig')

# Busca el bloque por funciones reales, no por un comentario exacto.
pat_inicio = re.search(r'(?m)^\s{8}def procesar_excel_traslado_scl_ccp\s*\(', s)
pat_fin = re.search(r'(?m)^\s{8}def descargar_archivo_web\s*\(', s)

if not pat_inicio:
    raise SystemExit(
        'ERROR: No encontre def procesar_excel_traslado_scl_ccp(...). '
        'Verifica que este sea el m3_picking.py que contiene el boton de traslado.'
    )
if not pat_fin or pat_fin.start() <= pat_inicio.start():
    raise SystemExit(
        'ERROR: No encontre def descargar_archivo_web(...) despues del bloque de traslado. '
        'No se modifico ningun archivo.'
    )

# Incluye comentarios inmediatamente anteriores al procesador, si existen.
inicio = pat_inicio.start()
linea_inicio = s.rfind('\n', 0, inicio) + 1
scan = linea_inicio
for _ in range(5):
    prev_end = scan - 1
    if prev_end <= 0:
        break
    prev_start = s.rfind('\n', 0, prev_end) + 1
    prev_line = s[prev_start:prev_end].strip()
    if prev_line.startswith('#') or prev_line == '':
        scan = prev_start
    else:
        break
inicio = scan
fin = pat_fin.start()

bloque = '''        # --- 3. EXCEL TRASLADO SCL -> CCP: PREVISUALIZACION Y LIBERACION ---
        ruta_excel_traslado_pendiente = None

        def _numero_ot_traslado_preview() -> str:
            base = f"OT-SCL-CCP-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            numero = base
            correlativo = 1
            while True:
                try:
                    existe_db = (supabase.table("netsuite_ordenes_venta")
                                 .select("id").eq("numero_ov", numero).limit(1).execute())
                    existe_mem = any(str(x.get("ov") or "") == numero for x in olas_extraidas_ns)
                    if not existe_db.data and not existe_mem:
                        return numero
                except Exception:
                    if not any(str(x.get("ov") or "") == numero for x in olas_extraidas_ns):
                        return numero
                correlativo += 1
                numero = f"{base}-{correlativo:02d}"

        def procesar_excel_traslado_scl_ccp(ruta_excel: str):
            nonlocal ruta_excel_traslado_pendiente
            try:
                df_tras = pd.read_excel(ruta_excel, sheet_name="Traslado", header=2)
                requeridas = {"Artículo", "Descripción", "SCL a CCP (Un)"}
                faltantes = sorted(requeridas.difference(set(df_tras.columns)))
                if faltantes:
                    raise ValueError("Faltan columnas: " + ", ".join(faltantes))

                mapa = {}
                for _, row in df_tras.iterrows():
                    sku_raw = row.get("Artículo")
                    if pd.isna(sku_raw):
                        continue
                    sku = str(sku_raw).strip().upper()
                    if not sku or sku == "NAN" or "TOTAL" in sku:
                        continue
                    try:
                        cantidad = int(float(row.get("SCL a CCP (Un)", 0) or 0))
                    except (TypeError, ValueError):
                        cantidad = 0
                    if cantidad <= 0:
                        continue
                    descripcion = str(row.get("Descripción") or "TRASLADO SCL-CCP").strip().upper()
                    if sku not in mapa:
                        mapa[sku] = {
                            "sku": sku, "descripcion": descripcion,
                            "cantidad": 0, "cantidad_pedida": 0,
                            "cantidad_pickeada": 0, "es_farmacia": False,
                        }
                    mapa[sku]["cantidad"] += cantidad
                    mapa[sku]["cantidad_pedida"] += cantidad

                lineas = list(mapa.values())
                if not lineas:
                    raise ValueError("No hay valores mayores que cero en SCL a CCP (Un).")

                numero_ot = _numero_ot_traslado_preview()
                total = sum(int(x["cantidad"]) for x in lineas)
                corte_forzado = None if dd_corte_asignar.value == "AUTO" else dd_corte_asignar.value
                item = {
                    "ov": numero_ot, "ov_base": numero_ot, "ov_original": numero_ot,
                    "id_externo_ns": numero_ot,
                    "fecha_ov": datetime.now().strftime("%Y-%m-%d"),
                    "cliente": "BODEGA CONCEPCION (TRASLADO SCL-CCP)",
                    "comuna": "CONCEPCION", "fecha_hora": datetime.now().isoformat(),
                    "corte": clasificar_corte_horario(None, corte_forzado),
                    "es_farmacia": False, "es_traslado_excel": True,
                    "directo_packing": True, "unidades": total,
                    "lineas_cnt": len(lineas), "estado": "PREVISUALIZADA",
                    "seleccionada": True, "lineas_detalle": lineas,
                    "archivo_origen": os.path.basename(ruta_excel),
                }
                olas_extraidas_ns[:] = [x for x in olas_extraidas_ns if not x.get("es_traslado_excel")]
                olas_extraidas_ns.append(item)
                ruta_excel_traslado_pendiente = ruta_excel
                cont_tabla_prev_ns.visible = True
                txt_estado_erp.value = (
                    f"Excel Traslado cargado: OT propuesta {numero_ot} | "
                    f"{len(lineas)} SKU | {total} UN. Revise y luego libere."
                )
                txt_estado_erp.color = "#34D399"
                renderizar_tabla_previsualizacion()
                page.update()
                notificar(f"Previsualización lista: {numero_ot} ({len(lineas)} SKU / {total} UN)", "#047857")
            except Exception as ex:
                txt_estado_erp.value = f"Error leyendo Excel Traslado: {ex}"
                txt_estado_erp.color = "#F87171"
                page.update()
                notificar(f"Error leyendo hoja Traslado: {ex}", "#B91C1C")

        async def al_seleccionar_excel_traslado(e):
            archivos = getattr(e, "files", None)
            if not archivos:
                notificar("Selección cancelada.", "#D97706")
                return
            f_obj = archivos[0]
            ruta = getattr(f_obj, "path", None)
            if ruta and os.path.exists(ruta):
                procesar_excel_traslado_scl_ccp(ruta)
                return
            nombre = os.path.basename(str(getattr(f_obj, "name", "traslado.xlsx")))
            os.makedirs(os.path.join("assets", "uploads"), exist_ok=True)
            datos = getattr(f_obj, "bytes", None)
            if datos:
                destino = os.path.join("assets", "uploads", nombre)
                with open(destino, "wb") as f_out:
                    f_out.write(bytes(datos))
                procesar_excel_traslado_scl_ccp(destino)
                return
            try:
                url = self.page.get_upload_url(nombre, 600)
                res = picker_excel_traslado.upload([ft.FilePickerUploadFile(nombre, upload_url=url)])
                if inspect.isawaitable(res):
                    await res
                txt_estado_erp.value = f"Subiendo {nombre}..."
                page.update()
            except Exception as ex:
                notificar(f"No fue posible subir el Excel: {ex}", "#B91C1C")

        async def on_result_traslado_event(e):
            await al_seleccionar_excel_traslado(e)

        async def on_upload_traslado_event(e):
            if float(getattr(e, "progress", 0) or 0) < 1:
                return
            nombre = os.path.basename(str(getattr(e, "name", "traslado.xlsx")))
            candidatos = [
                os.path.join("assets", "uploads", nombre),
                os.path.join(os.getcwd(), "assets", "uploads", nombre),
                os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "uploads", nombre),
            ]
            ruta = next((x for x in candidatos if os.path.exists(x)), None)
            if ruta:
                procesar_excel_traslado_scl_ccp(ruta)
            else:
                notificar(f"Carga terminada, pero no se encontró {nombre} en assets/uploads.", "#B91C1C")

        sig_fp_tr = inspect.signature(ft.FilePicker.__init__).parameters
        kwargs_fp_tr = {}
        if "on_result" in sig_fp_tr:
            kwargs_fp_tr["on_result"] = on_result_traslado_event
        if "on_upload" in sig_fp_tr:
            kwargs_fp_tr["on_upload"] = on_upload_traslado_event
        usa_evento_on_result = "on_result" in sig_fp_tr
        picker_excel_traslado = ft.FilePicker(**kwargs_fp_tr)
        try:
            if hasattr(ft, "Service") and isinstance(picker_excel_traslado, ft.Service) and hasattr(self.page, "services"):
                self.page.services.append(picker_excel_traslado)
            else:
                self.page.overlay.append(picker_excel_traslado)
        except Exception:
            self.page.overlay.append(picker_excel_traslado)

        async def abrir_selector_traslado(e=None):
            sig_pick = inspect.signature(picker_excel_traslado.pick_files).parameters
            kwargs = {"allow_multiple": False, "allowed_extensions": ["xlsx", "xls"]}
            if "with_data" in sig_pick:
                kwargs["with_data"] = True
            resultado = picker_excel_traslado.pick_files(**kwargs)
            if inspect.isawaitable(resultado):
                resultado = await resultado
            if resultado and not usa_evento_on_result:
                evento = type("FilePickerResult", (), {"files": resultado})()
                await al_seleccionar_excel_traslado(evento)

        btn_subir_traslado = boton_primario(
            "SUBIR EXCEL TRASLADO SCL->CCP", ft.Icons.UPLOAD_FILE_ROUNDED,
            abrir_selector_traslado, "#B45309", height_val=34,
        )

'''

nuevo = s[:inicio] + bloque + s[fin:]

# Cambios de liberacion tolerantes a variantes del archivo.
payload_pat = re.compile(
    r'(?P<i>\s*)payload_ov\s*=\s*\{(?P<body>.*?)\n(?P=i)\}', re.S
)

def ajustar_payload(m):
    body = m.group('body')
    if '"estado_ns": "PENDIENTE_PICKING"' not in body:
        return m.group(0)
    indent = m.group('i')
    body = body.replace(
        '"estado_ns": "PENDIENTE_PICKING"',
        '"estado_ns": "PENDIENTE_PACKING" if item.get("directo_packing") else "PENDIENTE_PICKING"'
    )
    return f'{indent}payload_ov = {{{body}\n{indent}}}'

nuevo, n_payload = payload_pat.subn(ajustar_payload, nuevo, count=1)

nuevo, n_cant = re.subn(
    r'"cantidad_pickeada"\s*:\s*0\s*,',
    '"cantidad_pickeada": int(float(lin.get("cantidad") or lin.get("cantidad_pedida") or 1)) if item.get("directo_packing") else 0,',
    nuevo, count=1
)
nuevo, n_estado = re.subn(
    r'"estado_linea"\s*:\s*"PENDIENTE"\s*,',
    '"estado_linea": "PICKEADO" if item.get("directo_packing") else "PENDIENTE",',
    nuevo, count=1
)

salida.write_text(nuevo, encoding='utf-8')
print(f'OK: salida creada en {salida.resolve()}')
print(f'Bloque reemplazado: si | payload ajustado: {n_payload} | cantidad: {n_cant} | estado: {n_estado}')
if not (n_payload and n_cant and n_estado):
    print('ADVERTENCIA: La previsualizacion fue instalada, pero una parte de la liberacion no coincidio. Envia este resumen.')
