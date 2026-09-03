# anvil — asistente on-prem de documentación técnica

**Fecha:** 2026-09-02
**Relación:** proyecto insignia del paso 2 de `~/Desktop/Gabo/CONTEXTO-AI-PORTFOLIO-CV.md` §7.
Es la reorientación del "JARVIS" descrita en §5 de ese documento.
**Hermano obligatorio:** `~/Desktop/Gabo/assay/CONTEXTO-ASSAY.md` — sin él, esto es
"otro RAG que parece que anda".
**Nombre:** *anvil* = yunque. Coherente con `crew`, `crucible`, `assay`.

---

## 0. Qué es, en una frase

Un asistente que responde preguntas sobre la documentación técnica de una planta
—manuales de equipo, WPS, SOPs, catálogos de repuestos— **corriendo entero dentro de la
planta, sin internet**, y donde **ningún número llega al usuario sin haber sido verificado
contra el documento fuente**.

**Lo que NO es:** un chatbot. La diferencia operativa es que se abstiene cuando no sabe,
cita documento + revisión + página en cada respuesta, y tiene un verificador determinista
entre el modelo y el usuario.

---

## 1. El escenario real

### Los documentos que existen en una planta metalúrgica

| Tipo | Volumen típico | Quién consulta |
|---|---|---|
| Manuales de equipo (horno, laminador, grúas) — SMS, Danieli, Primetals | 500–3000 pág. por equipo | Mantenimiento, muchas veces de madrugada |
| WPS / PQR — procedimientos de soldadura calificados | cientos | Soldadores, inspectores |
| SOPs e instrucciones de trabajo | cientos | Operarios |
| Catálogos de repuestos y tablas de equivalencia | miles de SKUs | Almacén, compras |
| ITPs, manual de calidad ISO 9001 | decenas | Calidad |
| SDS, permisos de trabajo, procedimientos LOTO | cientos | HSE |
| Informes de incidentes y análisis causa-raíz | acumulados por años | Ingeniería |

### Las preguntas reales

Hoy cada una cuesta entre 20 minutos y media jornada de buscar en PDFs:

1. *"¿Cuál es el torque de apriete de los pernos del cabezal del laminador 2?"*
2. *"¿Qué precalentamiento exige soldar A516 Gr.70 de 25 mm?"*
3. *"El horno de inducción tiró alarma E-114 — ¿qué significa y cuál es el procedimiento?"*
4. *"¿Qué rodamiento Timken equivale al SKF 22320 que ya no conseguimos?"*
5. *"¿Cuál es el procedimiento de bloqueo y etiquetado de la línea de colada?"*
6. *"¿Cada cuánto hay que calibrar el espectrómetro según nuestro manual de calidad?"*

### Por qué no pueden usar un servicio en la nube

Tres razones simultáneas, cualquiera basta:

- **Los parámetros de proceso son el activo competitivo.** La curva de un tratamiento
  térmico es secreto industrial.
- **Los manuales de proveedor están bajo NDA.** Subirlos puede ser incumplimiento contractual.
- **La planta suele no tener internet en piso**, y donde lo hay pesa la residencia de datos.

Esto es el eje del §1 del contexto —*los datos no salen de la máquina*— convertido en
requisito duro, no en preferencia.

---

## 2. Verificación técnica — hecha el 2026-09-02

No asumido. Consultado contra las fuentes oficiales desde esta máquina.

| Pieza | Estado verificado |
|---|---|
| **`bge-m3`** en Ollama | ✅ existe (`bge-m3:567m`, tipo *embedding*) |
| **Dimensiones de `bge-m3`** | ✅ `hidden_size: 1024`, `max_position_embeddings: 8194`, arquitectura `XLMRobertaModel` (→ multilingüe real) |
| `nomic-embed-text`, `mxbai-embed-large` | ✅ existen en Ollama (alternativas) |
| **`BAAI/bge-reranker-v2-m3`** | ✅ existe en HuggingFace (HTTP 200) |
| **pgvector — límites** | ✅ `vector` hasta 2.000 dims · `halfvec` hasta 4.000 · `bit` hasta 64.000 |
| **Imagen Docker `pgvector/pgvector`** | ✅ tags `pg13`…`pg18` disponibles |
| Parsers de PDF con tablas | ✅ `docling 2.124.0`, `marker-pdf 2.0.0`, `unstructured 0.27.5`, `pymupdf 1.28.2` |
| OCR local | ✅ `pytesseract 0.3.13`, `rapidocr-onnxruntime 1.4.4` |
| Stemmer de árabe en Postgres | ⚠️ Snowball lo trae; **confirmar con `\dF` dentro del contenedor** antes de prometerlo |

**Consecuencia de diseño:** con 1024 dimensiones, `bge-m3` entra holgado en el tipo
`vector` (límite 2000). `halfvec` acá **no hace falta** —a diferencia del Content Tool, que
usó `halfvec(1536)`— y sólo se justificaría si más adelante se indexan >2000 dims.
**Decisión: `vector(1024)` con índice HNSW.** Documentar el porqué, no copiar el patrón anterior por inercia.

### Entorno local (verificado el 2026-09-02)
Python 3.14.6 ✅ · Node 24.16.0 ✅ · `uv` ✅ · Ollama instalado pero **apagado** ·
**Docker ❌ NO instalado** ← bloqueante de M0.

---

## 3. Los cuatro problemas de ingeniería reales

Acá está la diferencia entre "monté un RAG en un fin de semana" y un sistema usable.

### Problema 1 — Las tablas se rompen y nadie se entera

Un manual trae:

```
Perno            Grado    Torque (N·m)   Secuencia
M24 cabezal      8.8      680 ± 30       cruzada, 3 pasadas
M24 cabezal      10.9     950 ± 40       cruzada, 3 pasadas
M16 tapa         8.8      190 ± 10       cruzada, 2 pasadas
```

Con chunking ingenuo de 512 tokens la tabla se corta. El sistema recupera el fragmento con
`950 ± 40` **sin la columna "Grado"** y responde *"950 N·m"* con total seguridad — para un
perno 8.8 donde el valor correcto es 680. Sobreapriete, perno estirado, falla.

**Solución — chunking consciente de estructura:**
- Una tabla **nunca** se parte. Si excede el chunk, se fragmenta por filas **repitiendo el
  encabezado en cada fragmento**.
- Un procedimiento numerado no se corta entre el paso 4 y el 5.
- Cada chunk lleva su ruta de sección (`4.3.2 Montaje del cabezal › Tabla 4-7`).

Esto no es un detalle de tuning: **es el corazón del proyecto.**

### Problema 2 — Los códigos alfanuméricos matan a los embeddings

Preguntá *"alarma E-114"*. Un embedding es búsqueda **semántica**: `E-114`, `E-141` y
`E-115` quedan a distancia casi nula. Recupera la alarma equivocada.
Igual con `SKF 22320`, `A516 Gr.70`, `SAES-W-011`.

**Solución — búsqueda híbrida.** Postgres da las dos en la misma base:
- **Densa** (`pgvector`, HNSW) → *"cómo aprieto los pernos del cabezal"*
- **Léxica** (`tsvector` / BM25) → `E-114` exacto
- Fusión con **Reciprocal Rank Fusion (RRF)**, después **rerank** con `bge-reranker-v2-m3`

> Es la causa #1 de que un RAG funcione en la demo y falle en producción. Un proyecto de
> fin de semana no la tiene.

### Problema 3 — Revisiones: citar un documento obsoleto es riesgo de seguridad

Los manuales se revisan. Contestar el precalentamiento de la **Rev B** cuando vigente es la
**Rev D** produce una respuesta que *parece* correcta, *está citada*, y es **peligrosa**.

**Solución:** cada documento lleva `revision` y `effective_date`. El retrieval prefiere la
revisión vigente; si un chunk supersedido entra al contexto, la respuesta lo marca:
*"Rev B — SUPERSEDIDA por Rev D (2025-11-14)"*.

### Problema 4 — Abstenerse es una respuesta correcta

Si la documentación no dice el torque del M30, la respuesta correcta es
**"no está en la documentación"**, no una estimación plausible.

En un chat de marketing inventar cuesta un párrafo raro. Acá cuesta un equipo roto o una
persona lastimada.

---

## 4. El verificador determinista — la pieza que lo hace defendible

Entre el modelo y el usuario hay un gate que **no es un modelo**:

> **INVARIANTE.** Todo número, código de alarma, número de norma y part number que aparezca
> en la respuesta debe aparecer **literalmente** en alguno de los chunks citados. Si no
> aparece, la respuesta se rechaza: se reintenta una vez y, si vuelve a fallar, se abstiene.

No es un LLM juzgando a otro LLM. Es normalización + `grep`.

**Es `crew` aplicado a RAG**, y es la frase que se dice en una entrevista:
> *"El modelo redacta, pero ningún número llega al usuario sin haber sido verificado contra
> el documento fuente."*

Este invariante va **escrito en el código**, igual que el
`"cosine distance is meaningless"` del Content Tool.

---

## 5. Arquitectura

```
 PDF nativo ──┐
 PDF escaneado ┼─▶ OCR local ─▶ chunking ESTRUCTURAL ─▶ bge-m3 ─▶ vector(1024) HNSW
 .docx/.xlsx ─┘     (rapidocr)   (tablas y pasos          (Ollama)          +
                                  intactos, con              │           tsvector
                                  encabezado repetido)       │              │
                                                             └──────┬───────┘
                                                                    │
 pregunta ─▶ HÍBRIDO (denso + léxico) ─▶ RRF ─▶ rerank ─▶ contexto ─▶ Qwen local
                                                                    │
                                                    VERIFICADOR DETERMINISTA
                                                  (números ⊂ chunks citados)
                                                          ├── falla ─▶ reintento → abstención
                                                          └── pasa
                                                                    │
                                            respuesta + doc + revisión + página
```

Todo en un `docker compose`: `pgvector/pgvector:pg18`, Ollama, API FastAPI, UI React.

---

## 6. Modelo de datos

```sql
doc.document (
  doc_id, title, vendor, equipment_tag,
  revision, effective_date, superseded_by,
  lang, source_path, sha256, ingested_at
)

doc.page (doc_id, page_no, raw_text, ocr_confidence)

doc.chunk (
  chunk_id, doc_id, page_from, page_to,
  section_path,          -- "4.3.2 Montaje del cabezal › Tabla 4-7"
  kind,                  -- prose | table | procedure | figure_caption
  content,
  embedding vector(1024),        -- bge-m3
  tsv tsvector,                  -- búsqueda léxica
  embed_model, embed_dim,        -- para el invariante de abajo
  chunk_strategy_version
)

qa.query   (query_id, question, lang, asked_at, user_id)
qa.answer  (query_id, answer, abstained, model, latency_ms, verifier_passed, retry_count)
qa.citation(query_id, chunk_id, rank, score_dense, score_lexical, score_rerank)
```

### Invariantes que van en el código

1. *"Ingesta y retrieval DEBEN usar el mismo modelo de embedding y la misma dimensión, o la
   distancia coseno no significa nada. Ambos importan el modelo desde este módulo, por eso."*
   ← heredado literal del Content Tool, y sigue siendo cierto.
2. *"Ningún número sale sin estar literal en un chunk citado."* (§4)
3. *"Un chunk supersedido nunca se presenta sin su marca de superseded_by."*

---

## 7. Stack y hardware

| Capa | Elección | Por qué |
|---|---|---|
| Parseo | `docling` | Ver §7.1: decisión medida, no asumida |
| Embeddings | `bge-m3` vía Ollama, 1024 dims | Multilingüe real (XLM-R): la planta opera en inglés y árabe, vos documentás en español. 8192 tokens de contexto: los párrafos técnicos son largos. 567M: corre en CPU si hace falta |
| Vector store | Postgres 18 + pgvector, `vector(1024)` HNSW | 1024 < 2000 → no hace falta `halfvec` |
| Léxico | `tsvector` en el mismo Postgres | Una sola base, una sola transacción |
| Rerank | `bge-reranker-v2-m3` | Mismo linaje multilingüe que el embedder |
| Generación | Qwen local vía Ollama | Ya lo tenés instalado |
| API / UI | FastAPI + React | Consistente con `crucible` |

### 7.1 Por qué NO `markitdown` — decisión medida el 2026-09-02

`microsoft/markitdown` (177.800 ⭐, mantenido activamente) es el candidato obvio: rapidísimo
y convierte casi cualquier formato a Markdown. **Se probó de verdad antes de descartarlo.**

**Corrección a una suposición previa:** este documento asumía que markitdown no extraía
tablas. **Es falso.** Su conversor de PDF usa `pdfplumber` con clustering de posiciones X
para formularios sin bordes, y funciona: en la prueba, una tabla de distribución sin líneas
salió como tabla Markdown bien formada. Tardó **2,9 s**. Como herramienta de "sacar texto de
cualquier cosa, rápido", es excelente.

**Los dos descalificadores para `anvil`:**

1. **No emite números de página.** Verificado en el código fuente — itera `pdf.pages` pero
   une todo con `markdown = "\n\n".join(markdown_chunks)` y **descarta `page_idx`**.
   Confirmado en la salida: **0 referencias a número de página** en todo el documento
   convertido.
   → `anvil` cita *documento + revisión + **página***. Sin página no hay cita verificable,
   y sin cita verificable no hay §4 (el verificador determinista). **Rompe el requisito
   central del proyecto.**

2. **No hace OCR.** `grep -i "ocr|tesseract|scan"` sobre su conversor de PDF: **cero
   coincidencias.** Su ruta para escaneos es `azure-ai-documentintelligence` — un servicio
   **en la nube**, que viola el requisito on-prem (§1).

**`docling` gana por lo que el README declara y markitdown no tiene:** *"Advanced PDF
understanding incl. page layout, reading order, table structure"* y *"Extensive OCR support
for scanned PDFs and images"*. Página + orden de lectura + OCR local son exactamente los
tres ejes que `anvil` necesita.

### 7.2 Rendimiento medido — 2026-09-02, Mac local

La pregunta operativa real: *¿200 manuales en un servidor tardan 3 días?*
Medido, no estimado. PDF de prueba: manual técnico real de **356 páginas**.

| Etapa | Medición | Extrapolación a 100.000 pág (200 manuales × 500) |
|---|---|---|
| **Parseo ruta rápida** (pdfplumber, motor de markitdown) | **24,8 ms/pág** · mediana 24,2 · p95 53,3 | **0,7 h** en 1 core · **0,1 h** en 8 |
| **Embedding** `bge-m3` vía Ollama, **batch 32** | **23,6 chunks/s** | ~300.000 chunks → **3,5 h** |
| Embedding, **batch 1** | 7,2 chunks/s | → 11,6 h |
| Parseo `docling` (ruta lenta, con OCR) | ⏳ pendiente de medir | — |

**Conclusiones que cambian el diseño:**

1. **El cuello de botella NO es el parseo: es el embedding.** 3,5 h contra 0,7 h — 5× más
   caro. Optimizar el parser más allá de la ruta rápida sería trabajo perdido.
2. **Batching = 3,3× gratis.** batch 1 → 7,2 chunks/s; batch 32 → 23,6 chunks/s.
   Es la misma decisión ya tomada en el Content Tool (lotes de 100). **El ingester debe
   agrupar por defecto**, nunca embeber de a uno.
3. Números de una Mac. En el servidor con GPU de la planta son otros — eso lo mide el
   proyecto #4 (benchmark de inferencia). **No extrapolar estos números a hardware ajeno.**

### 7.3 La arquitectura que sale de los números: TRIAJE por capa de texto

```
PDF ─▶ ¿la página tiene capa de texto?
        ├── SÍ  (mayoría de manuales modernos) ─▶ ruta rápida  ~25 ms/pág
        └── NO  (escaneos viejos)              ─▶ ruta lenta: OCR local  ~1-3 s/pág
```

Sólo la minoría escaneada paga el costo caro. Con 15% de escaneos sobre 100.000 páginas:
15.000 × 2 s ≈ 8 h, paralelizable por documento. **Nunca 3 días.**

Es mejor que "docling para todo" *o* "markitdown para todo": el motor barato donde alcanza,
el caro sólo donde hace falta. La decisión la toma un chequeo de una línea.

### 7.4 Qué se toma de markitdown, y cómo se atribuye

**Licencia verificada: MIT** → el fork es legal.

Lo valioso de markitdown **no es el parser** (eso es `pdfplumber`, una librería). Es
`_extract_form_content_from_words`: el clustering de posiciones X que reconstruye **tablas
sin bordes** — lógica no trivial, ya probada, y exactamente el Problema 1 de `anvil`.

```
TOMAR   : _extract_form_content_from_words + _to_markdown_table
CAMBIAR : guardar (page_no, contenido, kind) en vez de "\n\n".join(...)   ← ~20 líneas
AGREGAR : detección de capa de texto → enruta escaneos a OCR local
```

> ⚠️ **Regla §8 del contexto aplica con fuerza.** MIT permite redistribuir **conservando
> aviso de copyright y atribución**. La forma honesta de contarlo en el README y el CV:
>
> *"El chunker estructural, el enrutado por capa de texto y el rastreo de página son míos.
> La extracción de tablas sin bordes deriva de `microsoft/markitdown` (MIT), atribuida en
> el código y en el README."*
>
> Contado así **suma**: muestra saber leer código ajeno, identificar la parte valiosa y
> adaptarla. Presentarlo como propio hunde la credibilidad de todo el portfolio.

**Alternativas si docling da problemas:** `opendatalab/MinerU` (79.000 ⭐) o
`datalab-to/marker` (39.500 ⭐), ambos diseñados específicamente para PDF→Markdown con
layout. Evaluar en M1 con el mismo criterio: **¿conserva la página?**

> Esta comparación se conserva en el repo. Un README que dice *"se evaluó markitdown, se
> midió, y se descartó por estas dos razones con esta evidencia"* vale más que la elección
> misma — es la diferencia entre elegir una librería y **justificar** una elección.

**Hardware:** el número exacto lo da el proyecto #4 (benchmark de inferencia) — **medido,
no estimado**. Regla §8: no inventar métricas.

---

## 8. Hitos y criterios de aceptación

| # | Hito | Se acepta cuando |
|---|---|---|
| **M0** | Docker + Postgres/pgvector arriba | `docker compose up` levanta; `\dx` muestra `vector`; `\dF` confirma (o descarta) config de árabe |
| **M1** | Ingesta con chunking estructural | Sobre un manual con tablas: **ninguna tabla queda partida sin encabezado**. Test que lo verifica sobre un PDF fixture |
| **M2** | Retrieval híbrido + rerank | Consulta `E-114` recupera el chunk correcto en top-3. La búsqueda **sólo densa** falla el mismo caso — documentado lado a lado, es la evidencia de por qué existe el híbrido |
| **M3** | Generación con citas | Toda respuesta trae doc + revisión + página. Sin cita → no hay respuesta |
| **M4** | **Verificador determinista** | Inyectando a propósito una respuesta con un número inventado, el verificador la rechaza. Test en CI |
| **M5** | Vigencia de revisión | Con Rev B y Rev D cargadas, responde desde D y marca B como supersedida |
| **M6** | Abstención | Ante una pregunta cuya respuesta no está en el corpus, se abstiene en vez de estimar |
| **M7** | `assay` conectado | Las métricas del harness corren contra este sistema y hay un baseline publicado (ver doc de `assay`) |
| **M8** | Offline real | Corre con el wifi apagado, imágenes y modelos precacheados |

> **Orden crítico:** M7 **no va al final en la práctica**. Ver §11.

---

## 9. Riesgos y decisiones abiertas

| Riesgo | Mitigación |
|---|---|
| **No hay corpus real de una planta** | Arrancar con documentación pública equivalente: manuales de equipo industrial, normas abiertas, SDS públicas. El sistema es el entregable, no el corpus |
| Calidad de OCR en escaneos viejos | Guardar `ocr_confidence` por página; excluir del retrieval lo que esté bajo umbral y **decirlo**, no ocultarlo |
| Árabe en búsqueda léxica | Verificar en M0. Si Postgres no trae la config, el híbrido cae a `simple` para árabe y se documenta la limitación |
| Docling es pesado | Si el arranque se complica, `pymupdf` + extracción de tablas propia como plan B |
| Tentación de retro-ajustar | Ver §11 |

---

## 10. Cómo se cuenta en el CV

Cierra, de §4 del contexto:

| Hueco | Cómo |
|---|---|
| ❌ Sustrato on-prem | Todo el RAG sobre Ollama + Postgres auto-hospedado |
| ❌ Servir modelos on-prem | Embeddings, rerank y generación locales |
| ❌ Infra / red aislada | `docker compose` sin internet |
| ❌ Evals de RAG | Vía `assay` (M7) |
| ❌ Dominio metalúrgico | WPS, torques, LOTO, alarmas, repuestos |

Y sostiene el eje narrativo de §1: **los datos no salen de la máquina.**

---

## 11. Antes de escribir código

1. **Instalar Docker** — `brew install colima docker docker-compose && colima start`. Bloqueante de M0.
2. **`ollama serve`** y `ollama pull bge-m3` + un Qwen.
3. **Construir `assay` PRIMERO, con un corpus chico** (20 preguntas, unos pocos PDFs).
   Al revés se termina retro-ajustando el eval para que el sistema apruebe — que es el
   fracaso clásico y silencioso de este tipo de proyecto.
4. **Conseguir/armar el corpus semilla** antes de M1: sin documentos con tablas reales, el
   Problema 1 no se puede ni ver.
