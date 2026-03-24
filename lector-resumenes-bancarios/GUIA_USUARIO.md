# Guía de uso — Conta Tools

## ¿Qué hace esta herramienta?

Conta Tools convierte extractos bancarios en PDF a archivos Excel listos para trabajar. Podés procesar PDFs escaneados y PDFs digitales. El resultado es un Excel formateado con todos los movimientos organizados por columnas, con colores según el tipo de operación.

---

## Cómo iniciar la aplicación

1. Abrí una terminal
2. Escribí:
   ```
   conda activate conta-tools
   uvicorn server:app --reload
   ```
3. Abrí tu navegador y entrá a: **http://localhost:8000**

Vas a ver la pantalla de inicio de Conta Tools con dos opciones.

---

## Pantalla de inicio

Desde acá podés ir a:

- **Calibrador** — para configurar un banco nuevo que todavía no está en el sistema
- **Convertir a Excel** — para procesar extractos de bancos ya configurados

---

## Convertir un extracto a Excel

### Paso 1 — Completar los datos

- **Empresa**: escribí el nombre del cliente (aparece en el encabezado del Excel)
- **Perfil de calibración**: elegí el banco y tipo de documento del extracto que vas a procesar

### Paso 2 — Subir los PDFs

Hacé click en el botón para seleccionar uno o varios archivos PDF.

Si el PDF tiene texto seleccionable (digital), la app te va a preguntar cómo procesarlo:

- **Extracción directa** — recomendado para PDFs digitales, más rápido y sin errores de OCR
- **Usar OCR** — procesa el PDF como si fuera un escaneo

### Paso 3 — Convertir

Hacé click en **Convertir**. La barra de progreso muestra el avance página por página.

Cuando termina, aparece un botón de descarga para cada archivo Excel generado.

---

## El Excel generado

Cada PDF genera un Excel con el mismo nombre (por ejemplo, `06-2025 ICBC.pdf` → `06-2025 ICBC.xlsx`).

### Hoja "Movimientos"

Contiene todos los movimientos del extracto con:

- **Encabezado** con empresa, titular, CUIT, período y saldo inicial (cuando el OCR los detecta)
- **Tabla de movimientos** con las columnas del extracto
- **Colores por tipo de operación:**
  - Rojo claro → débito (egreso)
  - Verde claro → crédito (ingreso)
  - Amarillo → fila sin monto detectado (revisar manualmente)
  - Alternado gris/blanco → fila normal

### Hoja "OCR Raw"

Datos tal como los leyó el OCR. Útil para revisar si una fila quedó mal procesada.

### Hoja "Alertas" *(aparece solo si hay filas amarillas)*

Lista las filas que no tienen monto, con página, fecha y concepto para encontrarlas rápido.

---

## Calibrar un banco nuevo

Si necesitás procesar un extracto de un banco que todavía no está configurado, necesitás crear un perfil de calibración. Esto se hace una sola vez y después sirve para todos los extractos de ese banco y tipo de documento.

### Qué vas a necesitar

Un PDF de muestra del banco — puede ser cualquier extracto de ese banco.

### Paso 1 — Datos del perfil

Completá:
- **Banco**: nombre del banco (ej: ICBC, Galicia, Santander)
- **Tipo de documento**: tipo de cuenta (ej: cuenta-corriente, caja-ahorro, visa)
- **Período**: mes y año del PDF de muestra, en formato AAAA-MM (ej: 2025-06)

Hacé click en **Continuar**.

### Paso 2 — Subir el PDF

Subí el PDF de muestra. La app lo carga en el visualizador.

### Paso 3 — Marcar las columnas

Esta es la parte más importante. Vas a ver el PDF en el área de trabajo con herramientas para marcar.

**Qué tenés que marcar:**

Las **líneas verticales** que separan las columnas. Por ejemplo, si el extracto tiene las columnas FECHA | CONCEPTO | DÉBITOS | CRÉDITOS | SALDO, tenés que marcar 4 líneas verticales (una entre cada par de columnas).

**Cómo marcar:**

- Hacé click donde querés poner una línea vertical
- La línea aparece en azul sobre el PDF
- Si te equivocaste, hacé click derecho sobre la línea para eliminarla
- El contador arriba muestra cuántas líneas marcaste vs. cuántas necesitás

**Páginas pares e impares:**

Muchos bancos tienen márgenes espejo (las columnas están corridas en páginas pares vs. impares). Marcá las columnas en la página 1 (impar) y después en la página 2 (par). Usá los botones ◀ ▶ para navegar entre páginas.

Si el extracto es de una sola página o las columnas están en el mismo lugar en todas las páginas, podés marcar solo la página impar.

**Límites horizontales (opcional):**

Cambiá el modo a "Horizontal" y marcá dos líneas: una en el inicio del área de datos y otra al final. Esto ayuda a ignorar el encabezado y pie de página del extracto.

### Paso 4 — Preview

Antes de guardar podés hacer un preview para ver las primeras filas detectadas. Si las columnas están bien asignadas, guardá el perfil.

### Paso 5 — Guardar

Hacé click en **Guardar perfil**. El perfil queda disponible en el menú de conversión.

---

## Preguntas frecuentes

**¿Qué pasa si una fila queda amarilla en el Excel?**

Significa que el OCR no detectó un monto en esa fila. Puede ser un subtotal, un texto de encabezado de sección, o una línea que el OCR no leyó bien. Revisala en la hoja "Alertas" y completala manualmente si corresponde.

**¿El perfil de calibración sirve para todos los meses?**

Sí, siempre que el banco no cambie el formato del extracto. Un perfil por banco y tipo de documento cubre todos los períodos.

**¿Qué pasa si subo un PDF nuevo del mismo banco pero el formato cambió?**

Vas a ver filas vacías o datos en las columnas incorrectas. En ese caso hay que crear un perfil nuevo para ese formato actualizado.

**¿Dónde se guardan los Excel generados?**

Se descargan desde el navegador con el botón que aparece al terminar la conversión. El nombre del Excel es igual al del PDF original.

**¿Puedo procesar varios PDFs a la vez?**

Sí, seleccioná varios archivos en el paso de subida. Se procesan de a uno y podés descargar cada Excel por separado.

**La conversión tarda mucho, ¿es normal?**

Para PDFs escaneados, el OCR procesa cada página de a una. Un extracto de 12 páginas puede tardar entre 30 segundos y 2 minutos según la computadora. La barra de progreso muestra el avance en tiempo real.

Para PDFs digitales con extracción directa, el proceso es mucho más rápido.
