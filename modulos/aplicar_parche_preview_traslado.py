from pathlib import Path
import sys

entrada = Path(sys.argv[1] if len(sys.argv) > 1 else 'm3_picking.py')
salida = Path(sys.argv[2] if len(sys.argv) > 2 else 'm3_picking_preview_traslado.py')
s = entrada.read_text(encoding='utf-8')

inicio = s.index('        # --- 3. EXCEL TRASLADO SCL -> CCP COMO OT PARA RF Y PACKING ---')
fin = s.index('        def descargar_archivo_web(', inicio)

bloque = r'''        # --- 3. EXCEL TRASLADO SCL -> CCP: PREVISUALIZACION Y LIBERACION ---
        # El Excel NO se guarda al seleccionarlo. Primero genera una OT temporal,
        # la muestra en la tabla de previsualizacion y solo se guarda al liberar.
        ruta_excel_traslado_pendiente = None

        def _numero_ot_traslado_preview() -> str:
            base = f"OT-SCL-CCP-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            numero = base
            correlativo = 1
            while True:
                try:
                    existe_db = (supabase.table("netsuite_ordenes_venta")
                                 .select("id")
                                 .eq("numero_ov", numero)
                                 .limit(1)
                                 .execute())
                    existe_mem = any(str(x.get("ov") or "") == numero for x in olas_extraidas_ns)
                    if not existe_db.data and not existe_mem:
                        return numero
                except Exception:
                    if not any(str(x.get("ov") or "") == numero for x in olas_extraidas_ns):
                        return numero
                correlativo += 1
                numero = f"{base}-{correlativo:02d}"

        def procesar_excel_traslado_scl_ccp(ruta_excel: str):
            nonlocal olas_extraidas_ns, ruta_excel_traslado_pendiente
            try:
                df_tras = pd.read_excel(ruta_excel, sheet_name="Traslado", header=2)
                requeridas = {"Artículo", "Descripción", "SCL a CCP (Un)"}
                faltantes = sorted(requeridas.difference(set(df_tras.columns)))
                if faltantes:
                    raise ValueError("Faltan columnas en hoja Traslado: " + ", ".join(faltantes))

                lineas_por_sku = {}
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
                    if sku not in lineas_por_sku:
                        lineas_por_sku[sku] = {
                            "sku": sku,
                            "descripcion": descripcion,
                            "cantidad": 0,
                            "cantidad_pedida": 0,
                            "cantidad_pickeada": 0,
                            "es_farmacia": False,
                        }
                    lineas_por_sku[sku]["cantidad"] += cantidad
                    lineas_por_sku[sku]["cantidad_pedida"] += cantidad

                lineas_ot = list(lineas_por_sku.values())
                if not lineas_ot:
                    raise ValueError("No existen valores mayores que cero en 'SCL a CCP (Un)'.")

                numero_ot = _numero_ot_traslado_preview()
                total_unidades = sum(int(x["cantidad"]) for x in lineas_ot)
                fecha_hoy = datetime.now().strftime("%Y-%m-%d")
                corte_forzado = None if dd_corte_asignar.value == "AUTO" else dd_corte_asignar.value

                item_preview = {
                    "ov": numero_ot,
                    "ov_base": numero_ot,
                    "ov_original": numero_ot,
                    "id_externo_ns": numero_ot,
                    "fecha_ov": fecha_hoy,
                    "cliente": "BODEGA CONCEPCION (TRASLADO SCL-CCP)",
                    "comuna": "CONCEPCION",
                    "fecha_hora": datetime.now().isoformat(),
                    "corte": clasificar_corte_horario(None, corte_forzado),
                    "es_farmacia": False,
                    "es_traslado_excel": True,
                    "directo_packing": True,
                    "unidades": total_unidades,
                    "lineas_cnt": len(lineas_ot),
                    "estado": "PREVISUALIZADA",
                    "seleccionada": True,
                    "lineas_detalle": lineas_ot,
                    "archivo_origen": os.path.basename(ruta_excel),
                }

                # Conserva otras previsualizaciones y reemplaza solo la anterior del Excel.
                olas_extraidas_ns[:] = [x for x in olas_extraidas_ns if not x.get("es_traslado_excel")]
                olas_extraidas_ns.append(item_preview)
                ruta_excel_traslado_pendiente = ruta_excel
                cont_tabla_prev_ns.visible = True
                txt_estado_erp.value = (
                    f"Excel Traslado cargado: OT propuesta {numero_ot} | "
                    f"{len(lineas_ot)} SKU | {total_unidades} UN. "
                    "Revise VER SKUs y luego libere la seleccionada."
                )
                txt_estado_erp.color = "#34D399"
                renderizar_tabla_previsualizacion()
                page.update()
                notificar(f"Previsualización lista: {numero_ot} ({len(lineas_ot)} SKU / {total_unidades} UN)", "#047857")
            except Exception as ex:
                txt_estado_erp.value = f"Error leyendo Excel Traslado: {ex}"
                txt_estado_erp.color = "#F87171"
                page.update()
                notificar(f"Error leyendo hoja Traslado: {ex}", "#B91C1C")

        async def al_seleccionar_excel_traslado(e):
            archivos = getattr(e, "files", None)
            if not archivos:
                notificar("Selección de archivo cancelada.", "#D97706")
                return
            f_obj = archivos[0]
            ruta_local = getattr(f_obj, "path", None)
            if ruta_local and os.path.exists(ruta_local):
                procesar_excel_traslado_scl_ccp(ruta_local)
                return

            # Flet Web: el navegador no entrega una ruta local. Se sube a assets/uploads.
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
                resultado_upload = picker_excel_traslado.upload([
                    ft.FilePickerUploadFile(nombre, upload_url=url)
                ])
                if inspect.isawaitable(resultado_upload):
                    await resultado_upload
                # on_upload procesa el archivo al completar.
                txt_estado_erp.value = f"Subiendo {nombre} al servidor..."
                txt_estado_erp.color = ACCENT_CYAN
                page.update()
            except Exception as ex:
                notificar(f"No fue posible subir el Excel desde el navegador: {ex}", "#B91C1C")

        async def on_result_traslado_event(e):
            await al_seleccionar_excel_traslado(e)

        async def on_upload_traslado_event(e):
            progreso = float(getattr(e, "progress", 0) or 0)
            if progreso < 1:
                return
            nombre = os.path.basename(str(getattr(e, "name", "traslado.xlsx")))
            candidatos = [
                os.path.join("assets", "uploads", nombre),
                os.path.join(os.getcwd(), "assets", "uploads", nombre),
                os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "uploads", nombre),
            ]
            ruta = next((x for x in candidatos if os.path.exists(x)), None)
            if not ruta:
                notificar(f"El archivo {nombre} terminó de subir, pero no se encontró en assets/uploads.", "#B91C1C")
                return
            procesar_excel_traslado_scl_ccp(ruta)

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
            kwargs_pick = {"allow_multiple": False, "allowed_extensions": ["xlsx", "xls"]}
            if "with_data" in sig_pick:
                kwargs_pick["with_data"] = True
            resultado = picker_excel_traslado.pick_files(**kwargs_pick)
            if inspect.isawaitable(resultado):
                resultado = await resultado
            if resultado and not usa_evento_on_result:
                evento = type("FilePickerResult", (), {"files": resultado})()
                await al_seleccionar_excel_traslado(evento)

        btn_subir_traslado = boton_primario(
            "SUBIR EXCEL TRASLADO SCL->CCP",
            ft.Icons.UPLOAD_FILE_ROUNDED,
            abrir_selector_traslado,
            "#B45309",
            height_val=34,
        )

'''
s = s[:inicio] + bloque + s[fin:]

# Liberacion: una previsualizacion de Excel debe ir directamente a Packing para esta prueba.
s = s.replace(
'''                payload_ov = {
                    "bodega": bodega_act,
                    "id_externo_ns": id_ext_str,
                    "numero_ov": ov_final,
                    "cliente_nombre": cli_nom,
                    "canal_venta": canal_str,
                    "fecha_emision_ns": datetime.now().isoformat(),
                    "estado_ns": "PENDIENTE_PICKING",
                    "operador_asignado": operador_elegido,
                }''',
'''                es_traslado_excel = bool(item.get("es_traslado_excel"))
                directo_packing = bool(item.get("directo_packing"))
                if es_traslado_excel:
                    canal_str = "TRASLADO SCL-CCP"
                payload_ov = {
                    "bodega": bodega_act,
                    "id_externo_ns": id_ext_str,
                    "numero_ov": ov_final,
                    "cliente_nombre": cli_nom,
                    "canal_venta": canal_str,
                    "fecha_emision_ns": datetime.now().isoformat(),
                    "estado_ns": "PENDIENTE_PACKING" if directo_packing else "PENDIENTE_PICKING",
                    "operador_asignado": operador_elegido,
                }''', 1)

s = s.replace(
'''                            "cantidad_pickeada": 0,
                            "lote_asignado": "",
                            "estado_linea": "PENDIENTE",''',
'''                            "cantidad_pickeada": int(float(lin.get("cantidad") or 1)) if directo_packing else 0,
                            "lote_asignado": "",
                            "estado_linea": "PICKEADO" if directo_packing else "PENDIENTE",''', 1)

s = s.replace(
'''            notificar(f"¡{liberadas_ok} OVs liberadas y asignadas automáticamente a operadores RF!", "#047857")''',
'''            notificar(f"¡{liberadas_ok} orden(es) liberadas! Las OT del Excel quedaron disponibles en Packing RF.", "#047857")''', 1)

s = s.replace(
'''boton_primario("2. LIBERAR OLAS A PICKING RF", ft.Icons.SEND_ROUNDED, liberar_olas_a_terminal_rf, "#047857", height_val=30)''',
'''boton_primario("2. LIBERAR SELECCIONADAS A RF / PACKING", ft.Icons.SEND_ROUNDED, liberar_olas_a_terminal_rf, "#047857", height_val=30)''', 1)

salida.write_text(s, encoding='utf-8')
print(f'OK: {salida}')
