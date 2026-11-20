# LUDIPEK WMS · Guía de respaldo, ambiente de pruebas y seguridad del PC

Esta guía acompaña a los scripts **35** y **36**. Los pasos están en orden: haga uno, compruébelo y siga con el siguiente.

---

## 1. Salud del sistema (script 35)

1. En Supabase, ejecute `sql/robustez_2026_11/35_salud_respaldos.sql`.
2. En el PC abra **Desarrollador › 4. Salud del sistema**. Ahí encuentra:
   - **Este PC:** muestra si el programa se conecta con sesión de usuario o con la llave maestra, y si apunta a producción o a pruebas.
   - **Versión mínima del celular:** el botón *Exigir X* sube la versión mínima a la más nueva que está en uso. Ya no hace falta escribir el SQL.
   - **Sesión obligatoria del celular:** la lista de operadores muestra quién ya entra con la app nueva y sesión verificada.
     - Cuando todos los que trabajaron en la semana aparezcan como **Listo**, presione **Activar sesión obligatoria**.
     - Si algo falla, el botón **Volver a opcional** lo revierte al instante.
   - **Diagnóstico completo:** es el mismo diagnóstico del script 90, más chequeos nuevos (versiones, respaldos, PC con llave maestra). Revíselo una vez al mes.

---

## 2. Respaldos

### 2.1 Respaldo de Supabase (lo primero)
En Supabase › **Project Settings › Billing / Database › Backups** revise qué incluye su plan:

| Plan | Respaldo automático de Supabase |
|---|---|
| Free | **Ninguno descargable.** Dependen 100 % de su propio respaldo (punto 2.2). |
| Pro | Diario, guardado 7 días. Restaurar es un clic. |
| Pro + PITR | Restaura a cualquier minuto (ideal para un WMS). |

**Recomendación:** plan Pro como mínimo, sumado al respaldo propio del punto 2.2. Así tiene dos copias independientes.

### 2.2 Respaldo propio (todas las tablas a un .zip)
- **Manual:** Desarrollador › **5. Respaldos** › *Respaldar ahora*.
  - Genera `respaldos\WMS_respaldo_AAAAMMDD_HHMM.zip`, con un CSV por tabla y un `manifiesto.json` que indica cuántas filas tiene cada una.
  - Se conservan los últimos 30.
  - La carpeta del programa está en OneDrive, así que los respaldos quedan también en la nube.
- **Automático, todos los días:**
  1. Si el .env usa la llave pública (punto 4), agregue al `.env` un usuario ADMIN o con permiso Desarrollador:
     ```
     WMS_RESPALDO_USUARIO=SU_USUARIO
     WMS_RESPALDO_CLAVE=SU_CLAVE
     ```
  2. Abra el **Programador de tareas** de Windows y elija *Crear tarea básica*:
     - nombre: "WMS respaldo";
     - frecuencia: diariamente, 23:30;
     - acción: *Iniciar un programa* con `herramientas\respaldo_programado.bat`.
  3. Ejecute la tarea una vez a mano. El resultado queda en `respaldos\ultimo_respaldo.log` y aparece en el historial de la pantalla Respaldos.
- **Control:** si pasan más de 7 días sin un respaldo, *Salud del sistema* lo marca como ALTO.

### 2.3 Restaurar (solo si se perdió información)
- **Con plan Pro:** use la restauración de Supabase (Database › Backups).
- **Desde el .zip propio:**
  1. Abra el CSV de la tabla.
  2. En Supabase vaya a **Table Editor › tabla › Insert › Import data from CSV**.
  3. Para una tabla completa: primero en el proyecto de **pruebas**, revise, y recién después en producción.

---

## 3. Ambiente de pruebas

Su objetivo es que todo script o cambio nuevo se pruebe primero en una base de pruebas y nunca directo en la real.

### 3.1 Crear el proyecto de pruebas (una sola vez)
1. En Supabase cree un proyecto nuevo con *New project*, por ejemplo **ludipek-wms-pruebas** (el plan Free sirve).
2. Vaya a Authentication › Sign In / Providers y active **Allow anonymous sign-ins**.
3. Instale las *Command Line Tools* de **PostgreSQL 17** en el PC (https://www.postgresql.org/download/windows/).
4. En la carpeta del programa ejecute:
   ```
   powershell -ExecutionPolicy Bypass -File herramientas\clonar_esquema_a_pruebas.ps1
   ```
   - El script pide las dos cadenas de conexión, que están en Supabase › **Connect** › *Session pooler*.
   - No las guarda en ningún archivo.
   - Copia toda la estructura (tablas, funciones, políticas, permisos) y los datos de referencia: maestra, ubicaciones, usuarios, configuración.
   - **No** copia stock ni movimientos.

### 3.2 PC en modo pruebas
1. Copie `herramientas\env.pruebas.ejemplo` como `.env.pruebas`, junto a `main.py`.
2. Complete la URL y la llave pública del proyecto de pruebas.
3. Ábralo con `herramientas\abrir_wms_pruebas.bat` (o con `python main.py --pruebas`).
4. Se ve una **franja naranja "AMBIENTE DE PRUEBAS"** en todas las pantallas, y la ventana lo indica en el título.

### 3.3 Celular en modo pruebas (opcional)
1. En Render cree un segundo sitio estático, por ejemplo *wms-rf-pruebas*, desde el mismo repositorio.
2. Use este comando de build:
   ```
   flutter build web --dart-define=WMS_AMBIENTE=PRUEBAS --dart-define=SUPABASE_URL=https://<pruebas>.supabase.co --dart-define=SUPABASE_KEY=<llave pública de pruebas>
   ```
3. La app de pruebas muestra la cinta **PRUEBAS** en la esquina. El sitio de producción no cambia.

### 3.4 Forma de trabajo desde ahora
1. **Script nuevo:** se ejecuta primero en el proyecto de pruebas, se prueba con el PC en modo pruebas y recién después va a producción.
2. **Git:** una rama por cambio, por ejemplo `git checkout -b conciliacion-sin-oc`.
   - Para pasarlo a producción: `git checkout master` y luego `git merge conciliacion-sin-oc`.
   - Si algo sale mal, `git revert` deshace el cambio con historial.
3. **Archivos que nunca se suben a git:** `.env`, `.env.pruebas` y la carpeta `respaldos`. Ya están en `.gitignore`.

---

## 4. El PC con sesión de usuario, sin llave maestra (script 36)

**Hoy:** el `.env` de cada PC tiene la llave `service_role`. Quien copie ese archivo tiene acceso total a la base.

**Con el script 36:** cada usuario entra con su contraseña verificada en el servidor y la base aplica sus permisos.
- Los operadores **no** pueden abrir sesión de PC.
- Solo un administrador de usuarios puede cambiar contraseñas o modificar usuarios.
- La tabla de usuarios, con los hash de contraseña, deja de ser legible con la llave pública de la app web.

### Pasos (primero en PRUEBAS)
1. Ejecute `36_sesion_pc.sql`, primero en el proyecto de pruebas.
   - Al final muestra el portero instalado y qué usuarios podrán entrar al PC: ADMIN, SUPERVISOR o quienes tengan algún módulo PC marcado.
2. Actualice la librería del PC: `pip install -U supabase` (requiere la versión 2.10 o superior).
3. En `.env.pruebas` use la **llave pública**. Abra el PC en modo pruebas y recorra todos los módulos con su usuario y con uno no-admin.
4. Cuando todo funcione:
   1. Ejecute el 36 en **producción**.
   2. En cada PC, reemplace en el `.env` el valor de `SUPABASE_KEY` por la llave **pública** (la misma `sb_publishable_…` del celular, o la *anon* "legacy").
   3. Guarde la llave secreta solo en un lugar seguro, como un gestor de contraseñas. No debe quedar en ningún PC.
5. *Salud del sistema* muestra qué equipos siguen entrando con la llave maestra. Cuando ese chequeo quede en OK, la migración terminó.
6. Opcional, al final: en Supabase › API Keys **rote la llave secreta**. Así la que estuvo en los PC deja de servir.

> El cambio es gradual: los PC que sigan con la llave maestra funcionan igual que hoy. Si un PC con llave pública tuviera problemas, basta con volver a poner la llave anterior en su `.env`.

---

## 5. Chequeo mensual (10 minutos)
- [ ] *Salud del sistema* sin críticos ni altos pendientes.
- [ ] Último respaldo de hace menos de 7 días; abrir un zip y revisar el `manifiesto.json`.
- [ ] *Errores* sin grupos "Reapareció" y *Tickets* sin pendientes antiguos.
- [ ] Versión mínima igual a la más nueva en uso.
- [ ] Ningún PC con llave maestra.
