# shopfloor — demo estática

Copia funcional para mostrar, sin servidor ni base de datos.

## Qué corre acá y qué no

| Componente | En la demo | Por qué |
|---|---|---|
| Búsqueda léxica | ✅ idéntica al servidor | Es índice invertido + IDF, no necesita modelo |
| Detección de ambigüedad | ✅ idéntica | Parseo de tablas, puro determinismo |
| Verificador de datos | ✅ idéntico | Expresiones regulares + conjuntos |
| Guard del caché | ✅ idéntico | Comparación exacta de términos |
| Búsqueda semántica | ❌ | Requiere embeber la pregunta con `bge-m3` |
| Redacción de respuestas | ❌ precomputadas | Requiere el modelo local |

Las respuestas que muestra **fueron generadas por el modelo local corriendo on-prem**.
La demo no las inventa: las sirve desde el corpus exportado, y **re-verifica sus datos
contra el documento citado en el navegador del visitante**.

## Desplegar

```bash
cd demo
vercel --prod
```

No necesita variables de entorno, base de datos ni build. Son tres archivos estáticos.

## Regenerar el corpus

Con shopfloor corriendo local:

```bash
.venv/bin/python src/shopfloor/export_demo.py
```
