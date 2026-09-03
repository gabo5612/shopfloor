# anvil — cómo funciona

> Guía para entender el sistema sin necesidad de leer el código.
> Pensada para alguien con conocimientos técnicos básicos.

---

## 1. El problema

Una planta industrial acumula documentación que nadie puede navegar: manuales de equipo de
500 a 3000 páginas, procedimientos de soldadura, catálogos de repuestos, instructivos de
seguridad. Miles de páginas en PDF.

Cuando un técnico necesita un dato concreto —*"¿con cuánta fuerza aprieto este perno?"*—
tiene que abrir el PDF correcto, encontrar la sección correcta y leer la tabla correcta.
Eso toma entre veinte minutos y media jornada.

**anvil responde esa pregunta en dos segundos, citando el documento y la página.**

### Por qué no basta con usar ChatGPT

Tres razones, y cualquiera de ellas alcanza:

- **Los datos son secreto industrial.** La curva de temperatura de un tratamiento térmico
  es el activo competitivo de la empresa. No se sube a un servicio de terceros.
- **Los manuales del proveedor están bajo contrato de confidencialidad.** Subirlos puede ser
  un incumplimiento legal.
- **En planta muchas veces no hay internet.**

Por eso anvil corre **entero dentro de la planta**. Ningún dato sale de la máquina.

---

## 2. Las piezas

anvil no es un programa: son cuatro componentes que corren juntos en un servidor.

| Pieza | Qué hace | Comparación |
|---|---|---|
| **Postgres + pgvector** | Guarda los documentos troceados y permite buscarlos | Un archivador con dos índices distintos |
| **bge-m3** | Convierte texto en números para poder comparar significados | El "traductor de ideas a coordenadas" |
| **Qwen** | Redacta la respuesta en lenguaje natural | El que escribe, no el que decide |
| **anvil** | La lógica que coordina todo y **verifica** | El supervisor |

Los dos modelos (`bge-m3` y `Qwen`) son archivos que se descargan una vez y corren en el
servidor. No llaman a internet.

---

## 3. Qué pasa cuando cargás un documento

Se sube un PDF por el panel `/admin` y ocurre esto:

```
   PDF  →  [1] LEER  →  [2] TROCEAR  →  [3] NUMERAR  →  [4] GUARDAR
```

### [1] Leer

Una herramienta llamada **docling** convierte el PDF en texto, reconociendo qué es un
título, qué es un párrafo y **qué es una tabla**. Si el PDF es un escaneo, aplica OCR
(reconocimiento óptico) para leer la imagen.

### [2] Trocear — y acá está lo importante

El documento se corta en fragmentos de unos 1800 caracteres, porque un manual de 3000
páginas no cabe en una sola consulta.

**El problema:** si cortás sin cuidado, partís una tabla al medio.

Imaginá esta tabla en el manual:

| Perno | Grado | Torque |
|---|---|---|
| M24 cabezal | 8.8 | 680 N·m |
| M24 cabezal | 10.9 | 950 N·m |

Un corte ingenuo puede dejar un fragmento que dice `950 N·m` **sin la columna "Grado"**.
El sistema respondería *"950 N·m"* con total seguridad para un perno grado 8.8, cuyo valor
correcto es 680. Resultado: perno estirado, y posiblemente una falla mecánica.

**La solución:** una tabla nunca se parte. Si es demasiado grande, se divide por filas
**repitiendo el encabezado en cada pedazo**. Lo mismo con los procedimientos numerados: no
se corta entre el paso 4 y el paso 5.

### [3] Numerar

Cada fragmento guarda **de qué documento viene, de qué revisión y de qué página**.

Esto no es un adorno: sin página no hay cita verificable, y sin cita verificable todo el
sistema pierde sentido. Es una regla estricta del código: **un fragmento sin página se
descarta antes de entrar al índice.**

*(Para archivos Markdown, que no tienen páginas, se numera por sección.)*

### [4] Guardar

Cada fragmento se guarda de dos formas distintas, y las dos importan:

- **Como texto**, para buscar palabras exactas
- **Como una lista de 1024 números** (lo que produce `bge-m3`), para buscar por significado

---

## 4. Qué es un "embedding", en simple

Un **embedding** es convertir un texto en una lista de números que representa su
*significado*, de modo que textos parecidos tengan números parecidos.

Pensalo como coordenadas en un mapa: *"limpiar la pieza"* y *"lubricar el componente"*
quedan cerca, aunque no compartan ni una palabra. *"precio del plan"* queda lejos.

Eso permite que preguntes *"¿cómo limpio el equipo?"* y el sistema encuentre un párrafo que
dice *"aplicar una capa de lubricante"* — aunque la palabra "limpiar" no aparezca.

---

## 5. Qué pasa cuando preguntás

```
   pregunta
      ↓
   [1] ¿ya la respondimos?  ──sí, y es segura──▶  respuesta en ~140 ms
      ↓ no
   [2] BUSCAR (dos formas a la vez)
      ↓
   [3] ¿falta un dato para responder bien?  ──sí──▶  PREGUNTA de vuelta
      ↓ no
   [4] REDACTAR con el modelo local
      ↓
   [5] VERIFICAR cada número contra el documento
      ↓
   respuesta + documento + revisión + página
```

### [2] Buscar de dos formas a la vez

anvil busca **en paralelo** por dos caminos, y esto tiene una razón concreta:

- **Por significado** (embeddings) — encuentra *"cómo aprieto los pernos del cabezal"*
- **Por palabra exacta** — encuentra `E-114`

**¿Por qué hacen falta los dos?** Porque para un modelo de significados, `E-114`, `E-141` y
`E-115` son prácticamente lo mismo: tres códigos parecidos. Buscaría la alarma equivocada.
La búsqueda por palabra exacta no se confunde.

Los dos resultados se combinan y lo que aparece en ambas listas sube al primer puesto.

### [3] Preguntar en vez de adivinar

Volvamos a la tabla de torques. Si alguien pregunta *"¿cuál es el torque del M24?"*, hay
**dos respuestas válidas** según el grado del perno: 680 o 950.

La respuesta correcta no es ninguna de las dos. **Es preguntar.**

```
Vos:    ¿cuál es el torque del perno M24 del cabezal?
anvil:  ¿Para qué grado?   [ 8.8 ]  [ 10.9 ]
Vos:    (tocás 8.8)
anvil:  720 ± 30 N·m — Manual LAM-2, Rev F, pág. 1
```

**Detalle importante:** esa detección **no la hace el modelo**. Lo probamos: al modelo se le
dieron instrucciones explícitas para preguntar ante ambigüedad, y **eligió 680 con total
confianza** sin notar que existía la otra fila.

Así que la detección es un procedimiento fijo: se lee la tabla, se buscan las filas que
coinciden con la pregunta, y si empatan dos con valores distintos, se identifica qué columna
las diferencia. Es comparación de texto, no criterio de un modelo.

### [5] Verificar — la pieza que hace confiable al sistema

Después de que el modelo redacta, **antes de mostrar nada**, corre una comprobación:

> Todo número, código y referencia que aparezca en la respuesta **tiene que aparecer
> literalmente** en alguno de los fragmentos citados. Si no aparece, la respuesta se rechaza.

Esto no es otro modelo revisando al primero. Es una búsqueda de texto: se extraen los
números de la respuesta y se comprueba que estén en el documento.

Si falla, al modelo se le dice **exactamente qué dato inventó** y se le da un segundo
intento. Si vuelve a fallar, el sistema **se abstiene**.

Probado inyectando respuestas falsas a propósito:

| Respuesta | Resultado |
|---|---|
| `El voto fue 9-3` | ✅ aceptada — está en el documento |
| `El voto fue 11-2` | ❌ **rechazada** — inventó `11` y `2` |
| `Según H.R. 999...` | ❌ **rechazada** — inventó `HR999` |

### Abstenerse es una respuesta correcta

Si la documentación no dice el torque del M30, la respuesta correcta es
**"no está en la documentación"**, no una estimación razonable.

En un chatbot de marketing, inventar cuesta un párrafo raro. Acá cuesta un equipo roto o
una persona lastimada.

---

## 6. La memoria de respuestas

Cuando alguien pregunta algo por primera vez, el proceso completo tarda unos 2 segundos.
La respuesta se guarda, y la próxima vez sale en **140 milisegundos** — unas **20 veces
más rápido**.

### La trampa que había que esquivar

Lo obvio sería: *"si la pregunta nueva se parece mucho a una guardada, devolvé la misma
respuesta"*. **Lo medimos, y ese diseño era peligroso:**

| Parecido | Pregunta | Respuesta correcta |
|---|---|---|
| 84% | *"torque de apriete del M24 grado 8.8"* | 720 ✅ |
| **91%** | *"torque del M24 grado **10.9**"* | **950** ⚠️ |

**La pregunta con respuesta distinta se parece MÁS que la reformulación legítima.**
Un sistema basado sólo en parecido le habría dado 720 N·m a alguien que preguntó por el
grado 10.9.

**La solución:** para reutilizar una respuesta se exigen **dos** condiciones —
que se parezca lo suficiente **y** que mencione exactamente los mismos códigos técnicos
(`M24`, `8.8`, `E-114`). Si cambia un código, se recalcula desde cero.

### Cuando llega una revisión nueva del manual

Este es el escenario peligroso: el manual pasa de Rev D a Rev E, y el torque cambia de 680
a 720. Una respuesta guardada de la Rev D ahora es **incorrecta y peligrosa**.

anvil lo resuelve así:

1. Detecta que los fragmentos citados cambiaron
2. **Deja de servir** esa respuesta inmediatamente
3. **No la borra** — la pregunta que alguien se tomó el trabajo de hacer es información valiosa
4. La vuelve a responder contra la revisión vigente
5. La respuesta actualizada queda disponible

Probado de punta a punta: se cargó una revisión nueva y las respuestas guardadas pasaron
solas de 680 a 720, citando la revisión correcta.

---

## 7. Cómo se usa

### El portal — para cualquiera en la planta

`http://<servidor>:8080`

Se abre desde el teléfono o cualquier computadora de la red. Está pensado para usarse en
piso: botones grandes (se usa con guantes), alto contraste, y **sin depender de internet**.

### El panel de carga — `/admin`

Se sube un PDF o Markdown con sus datos: título, **revisión**, fabricante, equipo, idioma.
Muestra el progreso de la carga, los documentos indexados y las preguntas ya respondidas.

La **revisión** importa: es lo que permite avisar cuando un documento quedó superado.

---

## 8. La idea de fondo

Hay un criterio que atraviesa todo el sistema:

> **Lo que no se puede equivocar, no se le delega a un modelo.**

Los modelos son buenos redactando y encontrando textos parecidos. Son poco confiables
decidiendo si un dato es correcto o si falta información. Entonces:

| Tarea | Quién la hace |
|---|---|
| Encontrar textos parecidos | 🤖 el modelo |
| Redactar la respuesta | 🤖 el modelo |
| Detectar que falta un dato | ⚙️ procedimiento fijo |
| Verificar que los números sean reales | ⚙️ procedimiento fijo |
| Decidir si reutilizar una respuesta | ⚙️ procedimiento fijo |
| Detectar que el manual cambió | ⚙️ procedimiento fijo |

Las comprobaciones son baratas, dan siempre el mismo resultado y se pueden auditar. Ningún
modelo juzga a otro modelo.

---

## 9. Estado actual y límites

**Funcionando:** carga de PDF y Markdown · búsqueda por significado y por palabra exacta ·
detección de datos faltantes · verificación de números · memoria de respuestas con
actualización automática por revisión · portal móvil · panel de carga.

**Cifras verificadas:** 5 documentos · 1699 fragmentos indexados · 44 pruebas automáticas.

### Límites conocidos, dichos sin adornos

- **El modelo falla a veces.** En una prueba de 12 preguntas se abstuvo una vez teniendo la
  respuesta delante. Nunca inventó un dato — el verificador cumple su función — pero a veces
  se calla de más.
- **Los rangos confunden a la detección de ambigüedad.** Ante *"espesor de más de 20 mm"*
  pregunta igual, porque tanto `hasta 20` como `más de 20` contienen el número 20. Prefiere
  preguntar de más antes que elegir mal.
- **La calidad depende del documento.** Un escaneo viejo y borroso da peor resultado que un
  PDF nativo.
- **Todavía no hay una medición formal.** Sabemos que funciona porque se probaron casos a
  mano. Eso es una anécdota, no una métrica. El siguiente paso es un banco de ~50 preguntas
  con respuestas conocidas —incluyendo preguntas **sin** respuesta, para medir cuánto
  inventa— que se pueda correr después de cada cambio.
